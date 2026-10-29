"""Build the suite map from the index. Plain code: no LLM, deterministic for the same repo.

Areas are the generator's domains (folders, ``generate.domain_globs`` / ``generate.domains``);
when none match, each test folder is an area. For every area the map records how its tests are
built: classes and their setup, test shapes, markers, the page-object chains and helpers the
tests use, and the shape of their data entries. Each area also records the files it was built
from (with their hashes), so a later step can tell when it is out of date.
"""

from __future__ import annotations

import ast
import hashlib
import json
import re
from collections import Counter
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any

from ticket2test.adapters.repo.git_history import GitHistoryReader
from ticket2test.config import Settings
from ticket2test.generate.domain import Domain, domains
from ticket2test.index.catalog import SymbolCatalog
from ticket2test.index.extract import ClassInfo
from ticket2test.index.indexer import IndexData
from ticket2test.models.chunk import Chunk
from ticket2test.models.suite_map import (
    AreaSummary,
    Count,
    CoverageGap,
    KeyValues,
    SuiteMap,
    SuiteOverview,
    TestClassSummary,
)
from ticket2test.retrieve.shape import shape_of_test

_BRACE = re.compile(r"\{[A-Za-z_][A-Za-z_0-9]*(?::\d+)?\}")
_ID_SEGMENT = re.compile(r"(?<=/)\d+(?=/|$)")  # "/rules/42" -> "/rules/N"; "v1" stays
_DECORATOR_HEAD = re.compile(r"^[A-Za-z_][\w.]*")


def build_map(index: IndexData, settings: Settings, previous: SuiteMap | None = None) -> SuiteMap:
    repo = Path(index.repo_root)
    catalog = index.catalog
    tests = [c for c in index.chunks if c.kind == "test" and not c.inherited_from]
    owners = _owners(index, settings, tests)
    by_area: dict[str, list[Chunk]] = {}
    areas: dict[str, Domain] = {}
    for test in tests:
        area = owners[test.id]
        areas[area.name] = area
        by_area.setdefault(area.name, []).append(test)
    summaries = [_area(areas[name], by_area[name], index, settings) for name in sorted(areas)]
    assigned = set(owners)
    built = SuiteMap(
        repo_root=index.repo_root,
        built_at=datetime.now(UTC),
        commit=_head(repo),
        index_fingerprint=index.settings_fingerprint,
        overview=_overview(tests, summaries, index, assigned),
        areas=summaries,
        coverage=_coverage(summaries, tests, catalog, index),
    )
    if previous is not None:
        before = {a.name: a.digest for a in previous.areas}
        built.changed_areas = [a.name for a in summaries if before.get(a.name) != a.digest]
    return built


# --- areas -------------------------------------------------------------------------------


def _owners(index: IndexData, settings: Settings, tests: list[Chunk]) -> dict[str, Domain]:
    """Test id -> its area: the configured domain that contains it, else an area for the
    test's own folder (only the files directly in it, so ``tests/`` can't swallow
    ``tests/client/``)."""
    configured = [d for d in domains(index, settings) if d.folders]
    owners: dict[str, Domain] = {}
    for test in tests:
        domain = next((d for d in configured if d.contains(test.file_path)), None)
        if domain is None:
            folder = str(PurePosixPath(test.file_path).parent)
            domain = Domain(folder if folder != "." else "root", (folder,))
        owners[test.id] = domain
    sizes: dict[str, int] = {}
    for domain in owners.values():
        sizes[domain.name] = sizes.get(domain.name, 0) + 1
    limit = settings.map.max_tests_per_area
    first = dict(owners)  # two tests can share an id (a method defined twice): look up the first
    for test in tests:  # a very large area: one sub-area per module, so a guide stays specific
        domain = first[test.id]
        if sizes.get(domain.name, 0) > limit:
            owners[test.id] = Domain(sub_area(domain.name, test.file_path), (test.file_path,))
    return owners


def sub_area(area: str, file_path: str) -> str:
    """The sub-area name of a module inside a split area: ``<area>/<module stem>``."""
    return f"{area}/{PurePosixPath(file_path).stem}"


def _area(area: Domain, tests: list[Chunk], index: IndexData, settings: Settings) -> AreaSummary:
    catalog = index.catalog
    roots = set(settings.index.chain_roots)
    files = sorted({t.file_path for t in tests})
    classes = _classes(files, tests, index, settings)
    class_qualnames = {
        f"{index.files[t.file_path].info.module}.{t.class_name}"  # type: ignore[union-attr]
        for t in tests
        if t.class_name and index.files[t.file_path].info is not None
    }
    base_members, base_files = _base_members(class_qualnames, catalog)
    sources: dict[str, str] = {}

    shapes, markers, chains, actions, helpers, functions, asserts, fixtures = (
        Counter[str]() for _ in range(8)
    )
    page_types: set[str] = set()
    local_functions: dict[str, dict[str, str]] = {}  # test file -> name -> defining file
    for test in tests:
        shape = shape_of_test(test, settings)
        shapes[f"{shape.kind} {shape.action}"] += 1
        markers.update({_marker(m.name, m.args) for m in test.markers})
        used = {".".join(c) for c in test.refs.self_chains if c and c[0] in roots}
        chains.update(used)
        reached = _chain_types(used, catalog)
        page_types |= reached
        members = {name for q in reached for name in catalog.members_of(q)}
        calls = set(test.refs.calls)
        actions.update(c for c in calls if c in members)
        helpers.update(c for c in calls if c in base_members and c not in members)
        asserts.update(c for c in calls if c.startswith("assert"))
        local = local_functions.setdefault(test.file_path, _local_functions(test.file_path, index))
        functions.update(c for c in calls if c in local and c not in members)
        fixtures.update(test.fixtures)

    entries = _entries(tests, settings)
    for path in files + sorted({t.data_file for t in tests if t.data_file}):
        sources[path] = _sha(index, Path(index.repo_root), path)
    for q in sorted(page_types):
        entry = catalog.classes.get(q)
        if entry is not None:
            sources[entry.file_path] = _sha(index, Path(index.repo_root), entry.file_path)
    for path in sorted(base_files):
        sources[path] = _sha(index, Path(index.repo_root), path)
    decorators = {
        m.group(0).rsplit(".", 1)[-1]
        for c in classes
        for d in c.decorators
        if (m := _DECORATOR_HEAD.match(d))
    }
    for path in files:
        local = local_functions.get(path) or _local_functions(path, index)
        for name in sorted((set(functions) | decorators) & set(local)):
            sources[local[name]] = _sha(index, Path(index.repo_root), local[name])
    sources = dict(sorted(sources.items()))

    data_keys, expectations, placeholders = Counter[str](), Counter[str](), Counter[str]()
    skipped_entries = 0
    for data_entry in entries:
        keys = [k for k in data_entry if k != settings.data.id_field]
        data_keys.update(keys)
        skipped_entries += bool(data_entry.get("skip"))
        for section in settings.data.expectation_sections:
            items = data_entry.get(section)
            if isinstance(items, list):
                expectations.update(f"{section}: {_request(item)}" for item in items)
        placeholders.update(set(_BRACE.findall(json.dumps(data_entry, ensure_ascii=False))))
    skipped_tests = sum(any(m.name == "skip" for m in t.markers) for t in tests)
    data_values = known_values(entries, settings)
    limit = settings.map.max_items
    return AreaSummary(
        name=area.name,
        folders=list(area.folders),
        test_files=files,
        data_files=sorted({t.data_file for t in tests if t.data_file}),
        tests=len(tests),
        test_ids=sum(len(t.test_ids) for t in tests),
        parametrized=sum(bool(t.parametrize) for t in tests),
        classes=classes,
        shapes=_top(shapes, limit),
        markers=_top(markers, limit),
        chains=_top(chains, limit),
        page_actions=_top(actions, limit),
        base_helpers=_top(helpers, limit),
        functions=_top(functions, limit),
        assertions=_top(asserts, limit),
        fixtures=_top(fixtures, limit),
        data_entries=len(entries),
        data_keys=_top(data_keys, limit),
        data_key_roles={k: _role(k, settings) for k in data_keys},
        expectations=_top(expectations, limit),
        placeholders=_top(placeholders, limit),
        data_values=data_values,
        skipped=skipped_tests + skipped_entries,
        examples=_examples(tests, settings, chains, actions | helpers),
        sources=sources,
        digest=hashlib.sha256(json.dumps(sources).encode()).hexdigest(),
    )


def _classes(
    files: list[str], tests: list[Chunk], index: IndexData, settings: Settings
) -> list[TestClassSummary]:
    per_class = Counter(t.class_name for t in tests if t.class_name)
    found: list[TestClassSummary] = []
    for path in files:
        info = index.files[path].info
        if info is None:
            continue
        for cls in info.classes:
            if cls.name not in per_class:
                continue
            found.append(
                TestClassSummary(
                    name=cls.name,
                    file_path=path,
                    bases=list(cls.bases),
                    decorators=list(cls.decorators),
                    setup_calls=_setup_calls(cls, settings.generate.scaffold_methods),
                    tests=per_class[cls.name],
                )
            )
    return found


def _setup_calls(cls: ClassInfo, names: list[str]) -> list[str]:
    """Calls with keyword arguments in setup/teardown methods: the per-class options."""
    calls: list[str] = []
    for method in cls.methods:
        if method.name not in names:
            continue
        try:
            tree = ast.parse(_dedent(method.code))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and node.keywords:
                callee = ast.unparse(node.func).removeprefix("self.").removeprefix("super().")
                args = ", ".join(
                    f"{k.arg}={ast.unparse(k.value)}" if k.arg else f"**{ast.unparse(k.value)}"
                    for k in node.keywords
                )
                calls.append(f"{method.name}: {callee}({args})")
    return calls


def _base_members(class_qualnames: set[str], catalog: SymbolCatalog) -> tuple[set[str], set[str]]:
    """Members of the in-repo base classes of the area's test classes, and their files."""
    members: set[str] = set()
    files: set[str] = set()
    for qualname in class_qualnames:
        for base in catalog.mro(qualname)[1:]:
            members.update(base.members)
            files.add(base.file_path)
    return members, files


_CHAIN_CACHE: dict[tuple[int, str], frozenset[str]] = {}


def _chain_types(chains: Iterable[str], catalog: SymbolCatalog) -> set[str]:
    """Classes reached along the chains (every step that resolves to a repo class)."""
    reached: set[str] = set()
    for chain in chains:
        key = (id(catalog), chain)
        if key not in _CHAIN_CACHE:
            if len(_CHAIN_CACHE) > 50_000:  # bounded; one map build needs far fewer
                _CHAIN_CACHE.clear()
            resolution = catalog.resolve_chain_from_roots(chain)
            _CHAIN_CACHE[key] = frozenset(t for t in resolution.types if t)
        reached |= _CHAIN_CACHE[key]
    return reached


def _local_functions(path: str, index: IndexData) -> dict[str, str]:
    """Functions a test file can call by bare name: its own module-level functions and the
    repo functions it imports by name (``from module import name [as alias]``)."""
    info = index.files[path].info
    if info is None:
        return {}
    found = {fn.name: path for fn in info.functions}
    modules = _modules(index)
    for line in info.imports:
        words = line.replace(",", " ").replace("(", " ").replace(")", " ").split()
        if len(words) < 4 or words[0] != "from" or words[2] != "import":
            continue
        target = modules.get(words[1])
        target_info = index.files[target].info if target else None
        if target is None or target_info is None:
            continue
        defined = {fn.name for fn in target_info.functions}
        rest = words[3:]
        i = 0
        while i < len(rest):
            name, alias = rest[i], rest[i]
            if i + 2 < len(rest) and rest[i + 1] == "as":
                alias = rest[i + 2]
                i += 2
            if name in defined:
                found[alias] = target
            i += 1
    return found


_MODULES_CACHE: dict[int, dict[str, str]] = {}


def _modules(index: IndexData) -> dict[str, str]:
    key = id(index)
    if key not in _MODULES_CACHE:
        _MODULES_CACHE.clear()  # one index at a time
        _MODULES_CACHE[key] = {
            info.module: path for path, record in index.files.items() if (info := record.info)
        }
    return _MODULES_CACHE[key]


def _entries(tests: list[Chunk], settings: Settings) -> list[dict[str, Any]]:
    seen: set[tuple[str, str]] = set()
    found: list[dict[str, Any]] = []
    for test in tests:
        for test_id, entry in test.data_entries.items():
            key = (test.data_file or "", test_id)
            if key in seen or not isinstance(entry, dict):
                continue
            seen.add(key)
            found.append(entry)
    return found


def _request(item: Any) -> str:
    if not isinstance(item, dict):
        return "?"
    inner = item.get("request")
    request: dict[str, Any] = inner if isinstance(inner, dict) else item
    method = str(request.get("method", "?")).upper()
    path = _ID_SEGMENT.sub("N", str(request.get("path", "?")))  # literal ids split the counts
    return f"{method} {path}"


def _examples(
    tests: list[Chunk], settings: Settings, chains: Counter[str], calls: Counter[str]
) -> list[str]:
    """Per shape, the test that uses most of what the area commonly uses (ties: shortest)."""
    roots = set(settings.index.chain_roots)
    common = {name for name, n in (chains + calls).items() if n >= 2}
    best: dict[str, tuple[int, int, str]] = {}
    for test in tests:
        shape = shape_of_test(test, settings)
        key = f"{shape.kind} {shape.action}"
        used = {".".join(c) for c in test.refs.self_chains if c and c[0] in roots}
        score = len((used | set(test.refs.calls)) & common)
        candidate = (-score, test.end_line - test.start_line, test.id)
        if key not in best or candidate < best[key]:
            best[key] = candidate
    return [best[k][2] for k in sorted(best)][: settings.map.max_examples]


# --- overview ----------------------------------------------------------------------------


def _overview(
    tests: list[Chunk], areas: list[AreaSummary], index: IndexData, assigned: set[str]
) -> SuiteOverview:
    catalog = index.catalog
    bases: Counter[str] = Counter()
    for area in areas:
        for cls in area.classes:
            module = index.files[cls.file_path].info
            qualname = f"{module.module}.{cls.name}" if module else cls.name
            bases.update({b.qualname for b in catalog.mro(qualname)[1:]})
    page_areas: Counter[str] = Counter()
    roots = set(catalog.chain_roots)
    for test in tests:
        page_areas.update(
            {".".join(c[:2]) for c in test.refs.self_chains if len(c) >= 2 and c[0] in roots}
        )
    shared: Counter[str] = Counter()
    for area in areas:
        shared.update({h.name for h in area.base_helpers})
    return SuiteOverview(
        tests=len(tests),
        test_ids=sum(len(t.test_ids) for t in tests),
        test_classes=sum(len(a.classes) for a in areas),
        data_entries=sum(a.data_entries for a in areas),
        base_classes=_top(bases, None),
        chain_roots=list(catalog.chain_roots),
        page_areas=_top(page_areas, None),
        shared_helpers=[c for c in _top(shared, None) if c.count >= 2],
        marker_values={k: sorted(v) for k, v in sorted(catalog.markers.items())},
        unassigned_tests=sorted(t.id for t in tests if t.id not in assigned),
        skipped_files=sorted(
            f"{path}: {record.error or 'skipped'}"
            for path, record in index.files.items()
            if record.info is None
        ),
    )


# --- coverage ----------------------------------------------------------------------------


def _coverage(
    areas: list[AreaSummary], tests: list[Chunk], catalog: SymbolCatalog, index: IndexData
) -> list[CoverageGap]:
    """Test-side code that nothing in the repo references: page objects and their members,
    helpers of the test classes' bases, and functions in modules that test files import.
    Product code is not listed. A definition doesn't count as a reference to itself."""
    referenced = referenced_names(index)
    gaps: list[CoverageGap] = []
    for qualname in sorted(catalog.page_objects):
        entry = catalog.classes.get(qualname)
        if entry is None:
            continue
        if entry.name not in referenced and not _reached_by_chain(qualname, catalog):
            gaps.append(CoverageGap(kind="page_object", name=qualname, file_path=entry.file_path))
            continue
        for name, member in sorted(entry.members.items()):
            if name.startswith("_") or (member.kind == "attribute" and name.isupper()):
                continue  # private members and locator constants
            if name not in referenced:
                gaps.append(
                    CoverageGap(
                        kind="page_member", name=f"{entry.name}.{name}", file_path=entry.file_path
                    )
                )
    bases = {
        b.qualname: b
        for a in areas
        for cls in a.classes
        if (info := index.files[cls.file_path].info) is not None
        for b in catalog.mro(f"{info.module}.{cls.name}")[1:]
    }
    hooks = set(_HOOKS)
    for base in sorted(bases.values(), key=lambda b: b.qualname):
        for name, member in sorted(base.members.items()):
            if name.startswith(("_", "test")) or member.kind != "method" or name in hooks:
                continue
            if name not in referenced:
                gaps.append(
                    CoverageGap(
                        kind="base_helper", name=f"{base.name}.{name}", file_path=base.file_path
                    )
                )
    for path in sorted(imported_files(tests, catalog, index)):
        info = index.files[path].info
        if info is None:
            continue
        for fn in info.functions:
            if not fn.name.startswith("_") and fn.name not in referenced:
                gaps.append(
                    CoverageGap(kind="function", name=f"{info.module}.{fn.name}", file_path=path)
                )
    return gaps


# pytest calls these itself (xunit-style setup/teardown); nothing in the repo has to.
_HOOKS = (
    "setup", "teardown", "setup_method", "teardown_method", "setup_class", "teardown_class",
    "setup_module", "teardown_module", "setUp", "tearDown", "setUpClass", "tearDownClass",
)  # fmt: skip


def referenced_names(index: IndexData) -> set[str]:
    """Every identifier referenced anywhere in the repo, decorators included."""
    names: set[str] = set()
    for record in index.files.values():
        info = record.info
        if info is None:
            continue
        for fn in info.functions:
            names.update(fn.refs.names)
            names.update(_decorator_names(fn.decorators))
        for cls in info.classes:
            names.update(cls.refs.names)
            names.update(_decorator_names(cls.decorators))
            for method in cls.methods:
                names.update(_decorator_names(method.decorators))
        names.update(a.call for a in info.assignments if a.call)
    return names


def _decorator_names(decorators: list[str]) -> set[str]:
    return {
        part
        for d in decorators
        if (m := _DECORATOR_HEAD.match(d))
        for part in m.group(0).split(".")
    }


def _reached_by_chain(qualname: str, catalog: SymbolCatalog) -> bool:
    """The class is reached from a root through property types, or is a base of one that is
    (page objects are exactly those; see index/catalog.py)."""
    return qualname in set(catalog.page_objects)


def imported_files(tests: list[Chunk], catalog: SymbolCatalog, index: IndexData) -> set[str]:
    """Repo files that test files import (one level)."""
    modules = {info.module: path for path, record in index.files.items() if (info := record.info)}
    found: set[str] = set()
    for path in {t.file_path for t in tests}:
        info = index.files[path].info
        for line in info.imports if info else []:
            words = line.replace(",", " ").split()
            if len(words) >= 2 and words[0] in ("from", "import") and words[1] in modules:
                target = modules[words[1]]
                if target != path:
                    found.add(target)
    return found


# --- helpers -----------------------------------------------------------------------------


def _role(key: str, settings: Settings) -> str:
    data = settings.data
    if key in data.seed_sections:
        return "seed"
    if key in data.expectation_sections:
        return "expectation"
    if key in data.per_entry_keys:
        return "per entry"
    return "read by the test"


_MAX_DEPTH = 5  # nesting followed into entries (a.b.c...)
_FREE_TEXT_SHARE = 0.6  # distinct values / occurrences above this (with many values): free text


def known_values(entries: Iterable[dict[str, Any]], settings: Settings) -> list[KeyValues]:
    """Per key path, the distinct short values the entries use, most common first. A key whose
    values nearly all differ (generated names, payloads) is marked free text, not listed."""
    m = settings.map
    values: dict[str, Counter[str]] = {}
    holders: Counter[str] = Counter()
    long_text: Counter[str] = Counter()
    id_field = settings.data.id_field
    for entry in entries:
        seen: set[str] = set()
        for path, leaf in _leaves(entry, "", 0):
            if path == id_field:
                continue
            seen.add(path)
            if isinstance(leaf, str) and len(leaf) > m.max_value_chars:
                long_text[path] += 1
                continue
            counter = values.setdefault(path, Counter())
            if len(counter) <= 20 * m.max_values_per_key or leaf in counter:  # bounded
                counter[_value_text(leaf)] += 1
        holders.update(seen)
    found: list[KeyValues] = []
    for path, count in sorted(holders.items(), key=lambda kv: (-kv[1], kv[0]))[: m.max_value_keys]:
        counter = values.get(path, Counter())
        occurrences = sum(counter.values())
        free = len(counter) > m.max_values_per_key and len(counter) > _FREE_TEXT_SHARE * occurrences
        found.append(
            KeyValues(
                key=path,
                entries=count,
                distinct=len(counter),
                values=[] if free else _top(counter, m.max_values_per_key),
                long_text=long_text[path],
                free_text=free or (not counter and long_text[path] > 0),
            )
        )
    return found


def _leaves(value: Any, path: str, depth: int) -> Iterable[tuple[str, Any]]:
    """(key path, scalar) pairs: dict keys joined by ".", list items as "[]"."""
    if isinstance(value, dict):
        if depth >= _MAX_DEPTH:
            return
        for key, item in value.items():
            yield from _leaves(item, f"{path}.{key}" if path else str(key), depth + 1)
    elif isinstance(value, list):
        if depth >= _MAX_DEPTH:
            return
        for item in value:
            yield from _leaves(item, f"{path}[]", depth + 1)
    elif path:
        yield path, value


def _value_text(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _top(counter: Counter[str], limit: int | None) -> list[Count]:
    ranked = sorted(counter.items(), key=lambda kv: (-kv[1], kv[0]))
    return [Count(name=k, count=v) for k, v in ranked[:limit]]


def _marker(name: str, args: list[Any]) -> str:
    return f"{name}={','.join(str(a) for a in args)}" if args else name


def _sha(index: IndexData, repo: Path, path: str) -> str:
    record = index.files.get(path)
    if record is not None:
        return record.sha256
    try:
        return hashlib.sha256((repo / path).read_bytes()).hexdigest()
    except OSError:
        return "missing"


def _dedent(code: str) -> str:
    lines = code.splitlines()
    indent = min((len(x) - len(x.lstrip()) for x in lines if x.strip()), default=0)
    return "\n".join(x[indent:] for x in lines)


def _head(repo: Path) -> str | None:
    if not (repo / ".git").exists():
        return None
    try:
        commits = GitHistoryReader(repo).commits(1)
    except Exception:  # not a usable checkout: the map works without a commit
        return None
    return commits[0].sha if commits else None
