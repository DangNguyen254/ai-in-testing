"""The retrieval investigator: a bounded agent that explores the indexed suite.

Each turn the LLM reads the ticket, the first search results and everything its earlier tool
calls returned, then asks for a few more read-only tool calls, updates the list of chunks the
new test needs, and says when it is done. Code runs the tools, enforces the budgets (turns,
actions per turn, output size per tool, transcript size) and checks what comes back: kept ids
that don't exist are dropped and recorded. The tools only read the index; nothing is executed.

Cheap first: lists give chunk ids (and, when cut, how many more and where); a large chunk opens
as an outline of its members, and ``open_member`` reads one member; a test's data opens as its
entry ids and keys, and ``data_entry`` reads one entry. ``class_hierarchy`` and
``list_members`` read the catalog, for any class (not only pages reached from the chain root).
"""

from __future__ import annotations

import ast
import json
import textwrap
from collections import Counter
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import TYPE_CHECKING

from ticket2test.config import InvestigatorSettings, Settings
from ticket2test.index.catalog import ClassEntry
from ticket2test.llm.base import LLMClient, LLMRequest, Message
from ticket2test.llm.factory import model_name
from ticket2test.llm.schema import strict_schema
from ticket2test.llm.structured import complete_structured
from ticket2test.models.chunk import Chunk
from ticket2test.models.retrieval import (
    Investigation,
    InvestigatorAction,
    InvestigatorStep,
    KeptChunk,
)
from ticket2test.prompts import PromptTemplate
from ticket2test.retrieve.query import verify_identifiers
from ticket2test.security import scrub_text

if TYPE_CHECKING:  # avoids an import cycle with retrieve.pipeline
    from ticket2test.retrieve.pipeline import Retriever


@dataclass
class _Transcript:
    """Tool calls and their outputs, oldest first; older output is cut to fit the budget."""

    max_chars: int
    entries: list[tuple[str, str]] = field(default_factory=list)  # (call, output)

    def add(self, call: str, output: str) -> None:
        self.entries.append((call, output))

    def render(self) -> str:
        if not self.entries:
            return "(no tool calls yet)"
        blocks = [f"> {call}\n{output}" for call, output in self.entries]
        total = sum(len(b) for b in blocks)
        i = 0
        while total > self.max_chars and i < len(blocks) - 1:
            call = self.entries[i][0]
            short = f"> {call}\n(output removed to fit the budget; run it again if needed)"
            total -= len(blocks[i]) - len(short)
            blocks[i] = short
            i += 1
        return "\n\n".join(blocks)


class IndexTools:
    """The investigator's tools. Read-only over the index; every output is scrubbed and cut."""

    def __init__(self, retriever: Retriever, cfg: InvestigatorSettings) -> None:
        self.retriever = retriever
        self.cfg = cfg

    def run(self, action: InvestigatorAction) -> str:
        arg = action.arg.strip()
        handler = getattr(self, f"_{action.tool}")
        text: str = handler(arg)
        text = scrub_text(text)
        limit = self.cfg.max_tool_output_chars
        if len(text) > limit:
            text = text[:limit] + f"\n... (cut at {limit} characters)"
        return text

    # --- tools ---------------------------------------------------------------------------

    def _search(self, query: str) -> str:
        hits = self.retriever.bm25(query, "investigator")[: self.cfg.results_per_search]
        return self._list([c for c, _ in hits]) or "no results"

    def _grep(self, identifier: str) -> str:
        names, _ = verify_identifiers([identifier], self.retriever.catalog)
        if not names:
            return f"{identifier!r} is not a known identifier"
        name = names[0]
        found = self.retriever.grep(name, "investigator")
        if found:
            return self._list([c for c, _ in found])
        uses = self.retriever.count_containing(name)
        if uses:  # a refusal is not absence: a weak model read it as "doesn't exist"
            defined = [c.id for c in self.retriever.definitions_of(name)][:3]
            where = f"; defined in {', '.join(defined)}" if defined else ""
            return (
                f"{name!r} exists: it is used in {uses} chunks, too many to list{where}. "
                "Use search with more words, or tests_using / callers, to narrow it down"
            )
        return f"{name!r} matches nothing"

    def _open(self, chunk_id: str) -> str:
        chunk = self._chunk(chunk_id)
        if chunk is None:
            return self._unknown(chunk_id)
        lines = [f"{chunk.id} [{chunk.kind}] lines {chunk.start_line}-{chunk.end_line}"]
        if chunk.kind == "test":
            lines.append(f"test ids: {', '.join(chunk.test_ids) or '(none)'}")
            if chunk.data_entries:
                first = next(iter(chunk.data_entries.values()))
                keys = sorted(first) if isinstance(first, dict) else []
                lines.append(f"data entries: {len(chunk.data_entries)}, keys: {', '.join(keys)}")
        if len(chunk.code) <= self.cfg.max_tool_output_chars:
            lines.append(chunk.code)
            return "\n".join(lines)
        outline = _outline(chunk.code)
        lines.append(
            f"(the code has {len(chunk.code)} characters, so here is its outline; "
            "open_member <Class>.<member> reads one member)"
        )
        lines += outline or chunk.code.splitlines()[:40]
        return "\n".join(lines)

    def _open_member(self, arg: str) -> str:
        """The code of one member of a class (inherited ones too): ``Class.member``."""
        class_name, _, member = arg.strip().rpartition(".")
        entry = self.retriever.catalog.class_named(class_name) if class_name else None
        if entry is None:
            return f"no class {class_name!r} (use class_hierarchy or grep to find its name)"
        found = self.retriever.catalog.member(entry.qualname, member)
        if found is None:
            return f"{entry.name} has no member {member!r} (list_members {entry.name} shows them)"
        owner, info = found
        record = self.retriever.index.files.get(owner.file_path)
        cls = next(
            (c for c in record.info.classes if c.name == owner.name),
            None,
        ) if record and record.info else None  # fmt: skip
        head = f"{owner.name}.{member} ({info.kind}) in {owner.file_path}"
        if cls is None:
            return head
        methods = [m.code for m in cls.methods if m.name == member]  # a property and its setter
        if methods:
            return "\n".join([head, *methods])
        source = cls.code.splitlines()
        offset = info.line - cls.start_line
        line = source[offset].strip() if 0 <= offset < len(source) else ""
        return f"{head}\n{line}" if line else head

    def _class_hierarchy(self, name: str) -> str:
        """Bases going up (repo classes, then outside ones) and subclasses going down."""
        catalog = self.retriever.catalog
        entry = catalog.class_named(name.strip())
        if entry is None:
            return f"no class {name.strip()!r} (use grep or search to find its name)"
        up = [c.name for c in catalog.mro(entry.qualname)[1:]]
        outside = catalog.external_bases(entry.qualname)
        down = sorted(
            c.qualname
            for c in catalog.classes.values()
            if c.qualname != entry.qualname
            and any(b.qualname == entry.qualname for b in catalog.mro(c.qualname)[1:])
        )
        rows = [f"{entry.qualname} ({entry.file_path})"]
        rows.append("bases: " + (" -> ".join(up) if up else "(none in the repo)"))
        if outside:
            rows.append(f"bases outside the repo: {', '.join(outside)}")
        limit = self.cfg.results_per_search
        shown = down[:limit]
        rows.append("subclasses: " + (", ".join(shown) if shown else "(none)"))
        if len(down) > limit:
            rows.append(f"... and {len(down) - limit} more subclasses")
        return "\n".join(rows)

    def _list_members(self, name: str) -> str:
        """Every member of a class, inherited ones included: kind, where it is defined, and a
        method's signature."""
        catalog = self.retriever.catalog
        entry = catalog.class_named(name.strip())
        if entry is None:
            return f"no class {name.strip()!r} (use grep or search to find its name)"
        rows: list[tuple[bool, str]] = []
        for member, (owner, info) in sorted(catalog.members_of(entry.qualname).items()):
            if member.startswith("__"):
                continue
            where = "" if owner.qualname == entry.qualname else f", from {owner.name}"
            signature = self._signature(owner, member) if info.kind == "method" else ""
            rows.append(
                (owner.qualname == entry.qualname, f"{member} ({info.kind}{where}){signature}")
            )
        ordered = [r for own, r in rows if own] + [r for own, r in rows if not own]
        head = f"{entry.name}: {len(ordered)} members (own first; open_member reads one)"
        return "\n".join([head, *ordered]) if ordered else f"{entry.name} has no members"

    def _signature(self, owner: ClassEntry, member: str) -> str:
        record = self.retriever.index.files.get(owner.file_path)
        if record is None or record.info is None:
            return ""
        cls = next((c for c in record.info.classes if c.name == owner.name), None)
        method = next((m for m in cls.methods if m.name == member), None) if cls else None
        if method is None:
            return ""
        first = next(
            (line.strip() for line in method.code.splitlines() if line.strip().startswith("def ")),
            "",
        )
        return f": {first.removeprefix('def ').rstrip(':')}" if first else ""

    def _callers(self, name: str) -> str:
        short = name.rsplit(".", 1)[-1]
        found = [c for c in self.retriever.chunks.values() if short in c.refs.calls]
        return self._list(sorted(found, key=lambda c: c.id)) or f"nothing calls {short!r}"

    def _tests_using(self, name: str) -> str:
        short = name.rsplit(".", 1)[-1]
        found = [c for c in self.retriever.users_of(short) if c.kind == "test"]
        return self._list(found) or f"no test references {short!r}"

    def _chain(self, prefix: str) -> str:
        """Members one level below the chain, resolved from the catalog (not the chain list,
        which a large suite can cut)."""
        catalog = self.retriever.catalog
        prefix = prefix.strip().rstrip(".")
        resolution = catalog.resolve_chain_from_roots(prefix) if prefix else None
        last = resolution.types[-1] if resolution and resolution.ok and resolution.types else None
        if last is None or last not in catalog.classes:
            return f"no page-object members under {prefix!r}"
        owner = catalog.classes[last]
        rows = []
        for name, (defined_in, member) in sorted(catalog.members_of(last).items()):
            if name.startswith("_"):
                continue
            target = catalog._member_type(defined_in, member, owner)
            arrow = f" -> {target.qualname}" if target else ""
            rows.append(f"{prefix}.{name} ({member.kind}{arrow})")
        return "\n".join(rows) or f"no page-object members under {prefix!r}"

    def _data(self, chunk_id: str) -> str:
        chunk = self._chunk(chunk_id)
        if chunk is None:
            return self._unknown(chunk_id)
        if not chunk.data_entries:
            return f"{chunk.id} has no data entries"
        text = json.dumps(chunk.data_entries, indent=1, ensure_ascii=False)
        if len(text) <= self.cfg.max_tool_output_chars:
            return text
        rows = [
            f"{key}: keys {', '.join(sorted(entry)) if isinstance(entry, dict) else '?'}"
            for key, entry in chunk.data_entries.items()
        ]
        return "\n".join(
            [
                f"{len(rows)} entries ({len(text)} characters in all); "
                f"data_entry {chunk.id} <entry id> shows one:",
                *rows,
            ]
        )

    def _data_entry(self, arg: str) -> str:
        """One data entry: ``<test chunk id> <entry id>``."""
        chunk_id, _, entry_id = arg.strip().partition(" ")
        chunk = self._chunk(chunk_id)
        if chunk is None:
            return self._unknown(chunk_id)
        entry = chunk.data_entries.get(entry_id.strip())
        if entry is None:
            known = ", ".join(list(chunk.data_entries)[: self.cfg.results_per_search])
            return f"{chunk.id} has no entry {entry_id.strip()!r} (entries: {known or 'none'})"
        return json.dumps(entry, indent=1, ensure_ascii=False)

    # --- helpers -------------------------------------------------------------------------

    def _chunk(self, chunk_id: str) -> Chunk | None:
        return self.retriever.chunks.get(chunk_id)

    def _unknown(self, chunk_id: str) -> str:
        return f"no chunk with id {chunk_id!r} (use an id exactly as a tool listed it)"

    def _list(self, chunks: list[Chunk]) -> str:
        limit = self.cfg.results_per_search
        rows = [f"{c.id} [{c.kind}]" for c in chunks[:limit]]
        rest = chunks[limit:]
        if rest:
            folders = Counter(str(PurePosixPath(c.file_path).parent) for c in rest)
            where = ", ".join(f"{n} in {f}/" for f, n in folders.most_common(3))
            more = f" (and {len(folders) - 3} more folders)" if len(folders) > 3 else ""
            rows.append(
                f"... and {len(rest)} more: {where}{more}. Add words or a more specific "
                "name to narrow it"
            )
        return "\n".join(rows)


def investigate(
    client: LLMClient,
    prompt: PromptTemplate,
    retriever: Retriever,
    ticket_text: str,
    first_results: list[str],
    settings: Settings,
) -> Investigation:
    cfg = settings.retrieval.investigator
    tools = IndexTools(retriever, cfg)
    transcript = _Transcript(cfg.max_transcript_chars)
    calls: list[str] = []
    seen: set[tuple[str, str]] = set()
    step = InvestigatorStep(thought="", actions=[], keep=[], missing=[], done=False)
    llm_calls = 0
    stopped = "budget"
    steps = 0
    for steps in range(1, cfg.max_steps + 1):
        user = prompt.render_user(
            ticket_text=scrub_text(ticket_text),
            first_results=scrub_text("\n".join(first_results)) or "(no results)",
            transcript=transcript.render(),
            kept=_render_kept(step.keep),
            step=str(steps),
            max_steps=str(cfg.max_steps),
            max_actions=str(cfg.max_actions_per_step),
            max_kept=str(cfg.max_kept),
        )
        result = complete_structured(
            client,
            LLMRequest(
                messages=(
                    Message(role="system", content=prompt.system),
                    Message(role="user", content=user),
                ),
                temperature=settings.llm.temperature,
                seed=settings.llm.seed,
                max_output_tokens=min(settings.llm.max_output_tokens, 4000),
                json_schema=strict_schema(InvestigatorStep),
                model=model_name(settings, "investigate"),
            ),
            InvestigatorStep,
            max_retries=settings.llm.max_retries_on_bad_json,
        )
        llm_calls += result.attempts
        step = result.value
        if step.done:
            stopped = "done"
            break
        if not step.actions:
            stopped = "no_actions"
            break
        for action in step.actions[: cfg.max_actions_per_step]:
            call = f"{action.tool}({action.arg!r})"
            if (action.tool, action.arg) in seen:
                transcript.add(call, "(already run; see its output above)")
                continue
            seen.add((action.tool, action.arg))
            output = tools.run(action)
            transcript.add(call, output)
            calls.append(f"{call} -> {output.count(chr(10)) + 1} line(s)")
    kept, dropped = _checked_keep(step.keep, retriever, cfg.max_kept)
    return Investigation(
        steps=steps,
        tool_calls=calls,
        kept=kept,
        missing=list(step.missing),
        dropped_ids=dropped,
        stopped=stopped,  # type: ignore[arg-type]
        llm_calls=llm_calls,
    )


def _outline(code: str) -> list[str]:
    """The members of a large chunk, one line each: classes with their methods (signature),
    properties and attributes; module functions. Empty when the code doesn't parse."""
    try:
        tree = ast.parse(textwrap.dedent(code))
    except SyntaxError:
        return []
    rows: list[str] = []

    def signature(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
        kind = "property " if any(_name(d).endswith("property") for d in fn.decorator_list) else ""
        setter = any(_name(d).endswith(".setter") for d in fn.decorator_list)
        return f"{'setter ' if setter else kind}def {fn.name}({ast.unparse(fn.args)})"

    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            bases = ", ".join(ast.unparse(b) for b in node.bases)
            rows.append(f"class {node.name}({bases}):")
            for item in node.body:
                if isinstance(item, ast.FunctionDef | ast.AsyncFunctionDef):
                    rows.append(f"   {signature(item)}")
                elif isinstance(item, ast.Assign | ast.AnnAssign):
                    targets = item.targets if isinstance(item, ast.Assign) else [item.target]
                    names = [t.id for t in targets if isinstance(t, ast.Name)]
                    rows += [f"   {n} = ..." for n in names]
        elif isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            rows.append(signature(node))
    return rows


def _name(node: ast.expr) -> str:
    return ast.unparse(node.func if isinstance(node, ast.Call) else node)


def _render_kept(keep: list[KeptChunk]) -> str:
    return "\n".join(f"{k.chunk_id}: {k.why}" for k in keep) or "(nothing kept yet)"


def _checked_keep(
    keep: list[KeptChunk], retriever: Retriever, max_kept: int
) -> tuple[list[KeptChunk], list[str]]:
    """Only ids that exist, each once, at most ``max_kept``."""
    kept: list[KeptChunk] = []
    dropped: list[str] = []
    for item in keep:
        if item.chunk_id not in retriever.chunks:
            dropped.append(item.chunk_id)
        elif all(k.chunk_id != item.chunk_id for k in kept) and len(kept) < max_kept:
            kept.append(item)
    return kept, dropped
