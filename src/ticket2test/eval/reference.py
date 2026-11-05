"""Score a generated test against the test a person wrote for the same ticket (the design step's
yardstick, docs/design-step-plan.md). Binary criteria, all graded by code:

- **C1 placement**: the new test is in the reference's file and class.
- **C2 helpers**: the share of the reference's calls (``self.<...>(...)``, assertion object
  aside) that the new test makes too; passes at 1.0. ``inlined`` lists reference helpers of the
  class the new test didn't call while calling two or more of the calls inside them (their steps
  copied instead of the helper called).
- **C3 data blocks**: the share of the reference entry's key paths, two levels deep
  (``policy.<block>``, ``targets[].<key>``), that the new entries have; passes at 1.0.
- **C4 no made-up values**: no ``unsupported_values`` warning.
- **C5 cases**: as many new test ids as the reference has.
- **C7 checks**: the validators pass, and the sandbox collect too when it ran.
- **C8 context recall**: the generation context named the reference's helpers (``c8_helpers``)
  and its data blocks (``c8_blocks``). With C2/C3: C8 fails -> retrieval missed it; C8 passes
  but C2/C3 fail -> the model had it and didn't use it.

C6 (the checks cover the expected outcome) is a person's yes/no, merged in from a sheet.
"""

from __future__ import annotations

import ast
import textwrap
from dataclasses import dataclass, field
from typing import Any

from ticket2test.config import Settings
from ticket2test.eval.retrieval import manifest_test_to_chunk_id
from ticket2test.generate.entries import function_of
from ticket2test.index.indexer import IndexData
from ticket2test.models.generated import GeneratedTest
from ticket2test.validate.code import dotted

CRITERIA = ("c1", "c2", "c3", "c4", "c5", "c7", "c8")


@dataclass
class Scores:
    c1: bool = False
    c1_why: str = ""  # why C1 failed, without names (``c1_why``)
    c2: bool = False
    c3: bool = False
    c4: bool = False
    c5: bool = False
    c7: bool = False
    c8: bool = False
    c2_recall: float = 0.0
    c3_recall: float = 0.0
    c8_helpers: float = 0.0
    c8_blocks: float = 0.0
    inlined: list[str] = field(default_factory=list)
    missing_helpers: list[str] = field(default_factory=list)
    missing_blocks: list[str] = field(default_factory=list)
    note: str = ""

    def as_dict(self) -> dict[str, Any]:
        return dict(self.__dict__)


@dataclass(frozen=True)
class ReferenceFacts:
    """What scoring needs from the reference, taken from the full index once, so the full
    index needn't stay in memory while the runs build their own (a large suite's two indexes
    together outgrew the container's memory)."""

    file_path: str
    class_name: str | None
    calls: frozenset[str]  # as written (self.<chain>, locals resolved to their chain)
    entries: tuple[dict[str, Any], ...]
    test_count: int
    class_methods: tuple[tuple[str, str], ...]  # (name, code) of the reference class's methods
    call_keys: frozenset[str] = frozenset()  # what each call resolves to (``call_key``)
    # No other test of the reference's class is left once the hidden ones are gone: the class
    # was written for this ticket, so a new file in the reference's folder is the right placement
    # (nothing points the tool at an empty class).
    new_class_expected: bool = False


def reference_facts(
    reference_ids: list[str],
    full_index: IndexData,
    settings: Settings,
    hidden: set[str] | None = None,
) -> ReferenceFacts | None:
    """``reference_ids``: the pair's tests (pytest ids, ``path::Class::test``), looked up in
    the suite with the reference in it; ``hidden``: the chunk ids the run hides (the reference
    and the pair's ``hide``). None when no reference is in the index."""
    chunks = {c.id: c for c in full_index.chunks}
    refs = [chunks[i] for i in (manifest_test_to_chunk_id(t) for t in reference_ids) if i in chunks]
    if not refs:
        return None
    first = refs[0]
    record = full_index.files.get(first.file_path)
    info = record.info if record is not None else None
    cls = next((c for c in info.classes if c.name == first.class_name), None) if info else None
    calls = set().union(*(_calls(_function(c.code), settings) for c in refs))
    gone = (hidden or set()) | {c.id for c in refs}
    others = [
        c
        for c in full_index.chunks
        if c.kind == "test"
        and c.file_path == first.file_path
        and c.class_name == first.class_name
        and not c.inherited_from
        and c.id not in gone
    ]
    return ReferenceFacts(
        file_path=first.file_path,
        class_name=first.class_name,
        calls=frozenset(calls),
        entries=tuple(e for c in refs for e in c.data_entries.values() if isinstance(e, dict)),
        test_count=sum(len(c.test_ids) for c in refs),
        class_methods=tuple((m.name, m.code) for m in cls.methods) if cls else (),
        call_keys=frozenset(call_key(c, first.class_name, full_index) for c in calls),
        new_class_expected=not others,
    )


def c1_why(generated: GeneratedTest, facts: ReferenceFacts) -> str:
    """Where the placement went wrong, from the decision the run recorded: ``area`` (the
    chosen domain doesn't hold the reference file), ``excluded`` (its class was filtered
    out), ``not a candidate`` (no test of its class reached the class match), ``rank r/n``
    (scored, with its match and the winner's), or ``moved`` (decided right, a fallback moved
    it). No names, so the report can be pasted."""
    p = generated.reuse_placement
    if not p:
        return "no placement recorded"
    folders = p.get("domain_folders") or []
    if folders and not any(
        facts.file_path == f or facts.file_path.startswith(f + "/") for f in folders
    ):
        return "area"
    if facts.new_class_expected:
        return f"{generated.reuse_kind}, not a new file next to it"
    key = f"{facts.file_path}::{facts.class_name}"
    if p.get("decided_class") == key:  # the decision was right; something after it moved it
        return f"decided right, output is {generated.reuse_kind} in another place"
    if key in (p.get("excluded") or {}):
        return "excluded"
    scores: dict[str, float] = p.get("class_scores") or {}
    if key not in scores:
        return "not a candidate"
    ranked = sorted(scores.values(), reverse=True)
    rank = 1 + sum(v > scores[key] for v in ranked)
    home = (
        "; template's class"
        if p.get("home") == key
        else "; template in another class"
        if p.get("home")
        else "; no template in the area"
    )
    if rank == 1 and generated.reuse_kind == "method":
        return "moved" + home
    return f"rank {rank}/{len(ranked)} ({scores[key]:.2f} vs {ranked[0]:.2f}){home}"


def call_key(call: str, class_name: str | None, index: IndexData | None) -> str:
    """What a call (``self.`` dropped) resolves to: the class its chain leads to and the member
    (``RulesListPage.open``), or the class defining a helper (``BaseTest.verify_targets``), so
    the same page action reached by another chain or a page a helper returns counts the same.
    The call as written when it doesn't resolve."""
    if index is None or class_name is None:
        return call
    catalog = index.catalog
    *steps, member = call.split(".")
    member = member.removesuffix("()")
    if not steps:
        owner = catalog.class_named(class_name)
        found = catalog.member(owner.qualname, member) if owner is not None else None
        return f"{found[0].name}.{member}" if found is not None else call
    resolution = catalog.resolve_chain(class_name, steps)
    last = resolution.types[-1] if resolution.ok and resolution.types else None
    entry = catalog.classes.get(last) if last else None
    return f"{entry.name}.{member}" if entry is not None else call


def score(
    generated: GeneratedTest | None,
    facts: ReferenceFacts | None,
    settings: Settings,
    warnings: list[str],
    final_ok: bool,
    collect_ok: bool | None,
    index: IndexData | None = None,
) -> Scores:
    """One run against the reference (``reference_facts``). ``index``: the one the test was
    generated against, to resolve its calls (``call_key``); without it, calls compare as
    written."""
    found = Scores()
    if generated is None:
        found.note = "nothing generated"
        return found
    if facts is None:
        found.note = "reference test not in the index"
        return found
    new = _new_functions(generated)
    gen_calls = set().union(*(_calls(fn, settings) for _, fn in new)) if new else set()
    resolve = index is not None and bool(facts.call_keys)
    if resolve:
        ref_keys = set(facts.call_keys)
        gen_keys = {
            call_key(c, cls or None, index) for cls, fn in new for c in _calls(fn, settings)
        }
    else:
        ref_keys, gen_keys = set(facts.calls), gen_calls

    classes = {cls for cls, _ in new}
    if facts.new_class_expected:  # a new file next to the reference counts as the right place
        folder = facts.file_path.rsplit("/", 1)[0]
        found.c1 = generated.reuse_kind == "module" and generated.file_name.startswith(folder + "/")
    else:
        found.c1 = generated.file_name == facts.file_path and facts.class_name in classes
    if not found.c1:
        found.c1_why = c1_why(generated, facts)
    found.c2_recall = _share(ref_keys, gen_keys)
    found.missing_helpers = sorted(ref_keys - gen_keys)
    missing_raw = sorted(
        c
        for c in facts.calls
        if (call_key(c, facts.class_name, index) if resolve else c) not in gen_keys
    )
    found.inlined = _inlined(missing_raw, gen_calls, dict(facts.class_methods))
    found.c2 = found.c2_recall == 1.0 and not found.inlined

    id_field = settings.data.id_field
    ref_entries = list(facts.entries)
    new_ids = set(generated.new_test_ids or generated.test_ids)
    gen_entries = [e for e in generated.data_entries if str(e.get(id_field)) in new_ids]
    ref_paths = (
        set().union(*(block_paths(e, id_field) for e in ref_entries)) if ref_entries else set()
    )
    gen_paths = (
        set().union(*(block_paths(e, id_field) for e in gen_entries)) if gen_entries else set()
    )
    found.c3_recall = _share(ref_paths, gen_paths)
    found.missing_blocks = sorted(ref_paths - gen_paths)
    found.c3 = found.c3_recall == 1.0

    found.c4 = not any(w.startswith("[unsupported_values]") for w in warnings)
    found.c5 = len(new_ids) == facts.test_count
    found.c7 = final_ok and collect_ok is not False

    names = set(generated.context_names)
    helper_names = {c.rsplit(".", 1)[-1].removesuffix("()") for c in facts.calls}
    block_names = {p.replace("[]", ".").split(".")[-1] for p in ref_paths}
    found.c8_helpers = _share(helper_names, names)
    found.c8_blocks = _share(block_names, names)
    found.c8 = found.c8_helpers == 1.0 and found.c8_blocks == 1.0
    if not generated.context_names:
        found.note = "no context names recorded (generated before the context report)"
    return found


def block_paths(entry: dict[str, Any], id_field: str) -> set[str]:
    """Key paths two levels deep: ``key``, ``key.sub``, ``key[].sub`` (list items' keys)."""
    paths: set[str] = set()
    for key, value in entry.items():
        if key == id_field:
            continue
        paths.add(key)
        if isinstance(value, dict):
            paths |= {f"{key}.{sub}" for sub in value}
        elif isinstance(value, list):
            paths |= {f"{key}[].{sub}" for item in value if isinstance(item, dict) for sub in item}
    return paths


def _share(wanted: set[str], have: set[str]) -> float:
    return round(len(wanted & have) / len(wanted), 3) if wanted else 1.0


def _function(code: str) -> ast.FunctionDef | None:
    """The first function in a chunk's code. A method's code starts at its first character
    while its other lines keep the class indent: the first line gets the next line's indent."""
    lines = code.splitlines()
    following = next((ln for ln in lines[1:] if ln.strip()), "")
    indent = following[: len(following) - len(following.lstrip())]
    if lines and not lines[0].startswith((" ", "\t")):
        lines[0] = indent + lines[0]
    try:
        tree = ast.parse(textwrap.dedent("\n".join(lines)))
    except SyntaxError:
        return None
    return next((n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)), None)


def _new_functions(generated: GeneratedTest) -> list[tuple[str, ast.FunctionDef]]:
    """(class name, function) for the tests this output adds."""
    wanted = {function_of(i) for i in (generated.new_test_ids or generated.test_ids)}
    try:
        tree = ast.parse(generated.code)
    except SyntaxError:
        return []
    found: list[tuple[str, ast.FunctionDef]] = []
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            found += [
                (node.name, f)
                for f in node.body
                if isinstance(f, ast.FunctionDef) and f.name in wanted
            ]
        elif isinstance(node, ast.FunctionDef) and node.name in wanted:
            found.append(("", node))
    return found


def _calls(fn: ast.FunctionDef | None, settings: Settings) -> set[str]:
    """``self.<...>`` call names (``self.`` dropped), the assertion objects' calls aside. A call
    on a local bound to a ``self`` chain (``rules = self.nav.rules.list`` then ``rules.open()``)
    counts as the chain's call (``nav.rules.list.open``)."""
    if fn is None:
        return set()
    v = settings.validation
    skip = {o.removeprefix("self.") for o in [v.assertion_object, *v.extra_assertion_objects]}
    bound: dict[str, str] = {}
    for node in ast.walk(fn):  # locals bound to a self chain, or to what a self call returns
        if not (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
        ):
            continue
        value = node.value
        called = isinstance(value, ast.Call)
        target = value.func if isinstance(value, ast.Call) else value
        if not isinstance(target, ast.Attribute):
            continue
        name = dotted(target)
        head, _, rest = name.partition(".")
        if head in bound and rest:
            name = f"{bound[head]}.{rest}"
        if name.startswith("self."):
            bound[node.targets[0].id] = name + ("()" if called else "")
    found: set[str] = set()
    for node in ast.walk(fn):
        if isinstance(node, ast.Call):
            name = dotted(node.func)
            head, _, rest = name.partition(".")
            if head in bound and rest:
                name = f"{bound[head]}.{rest}"
            if name.startswith("self.") and name.count(".") >= 1:
                short = name.removeprefix("self.")
                if short.split(".")[0] not in skip and not short.startswith("assert"):
                    found.add(short)
    return found


def _inlined(missing: list[str], gen_calls: set[str], methods: dict[str, str]) -> list[str]:
    """Reference helpers of the class the new test didn't call, but whose inside calls (two or
    more) it makes: their steps copied instead of the helper called. ``methods``: name -> code
    of the reference class's methods."""
    copied: list[str] = []
    for name in missing:
        code = methods.get(name)
        if code is None:
            continue
        inside = {
            dotted(n.func).removeprefix("self.")
            for n in ast.walk(_function(code) or ast.Module(body=[], type_ignores=[]))
            if isinstance(n, ast.Call) and dotted(n.func).startswith("self.")
        }
        if len(inside & gen_calls) >= 2:
            copied.append(name)
    return copied
