"""Check a missing-piece candidate against the index. Code only; the index is the truth.

1. The owner must resolve: a page-object chain (``nav.files.policy``), a class, or "" for a
   module-level function. Otherwise: ``owner_unknown``.
2. The owner must be test-side, something the tests can reach: a page object, a base class of
   the test classes, or a class in a module that test files import. Product code is out of
   scope (``not_test_side``).
3. The name must not exist already, on the owner or its base classes (``exists``). The catalog
   is read directly, so a name used in many places can't hide.
4. Close matches are shown, nearest first: members of the owner and its base classes, of the
   pages next to it (same parent chain), the test classes' base-class helpers, and functions in
   modules the tests import; then the exact name on another test-side class. Words are split and
   lightly stemmed (``add_hash_to_blocklist`` ~ ``blocklist_add_hash``). With any, the
   candidate is a ``close_match`` for the reviewer; with none, ``missing``.
"""

from __future__ import annotations

from dataclasses import dataclass

from ticket2test.config import Settings
from ticket2test.index.catalog import ClassEntry, SymbolCatalog
from ticket2test.index.indexer import IndexData
from ticket2test.index.tokens import split_identifier
from ticket2test.models.gaps import GapVerdict, MissingPiece
from ticket2test.suitemap.build import imported_files
from ticket2test.validate.claims import norm

CLOSE_MIN = 0.5  # word overlap (Jaccard) for a close match
MAX_CLOSE = 3


@dataclass
class _Scope:
    test_side: set[str]  # class qualnames tests can reach
    base_classes: set[str]  # in-repo bases of the test classes
    imported_modules: set[str]  # modules test files import


def check_pieces(
    pieces: list[MissingPiece], index: IndexData, settings: Settings
) -> list[GapVerdict]:
    scope = _scope(index, settings)
    return [check_piece(p, index, settings, scope) for p in pieces]


def check_piece(
    piece: MissingPiece, index: IndexData, settings: Settings, scope: _Scope | None = None
) -> GapVerdict:
    scope = scope or _scope(index, settings)
    catalog = index.catalog
    if piece.kind == "fixture":
        if piece.name in catalog.fixtures:
            return GapVerdict(piece=piece, status="exists", found=f"fixture {piece.name}")
        close = _close(piece.name, list(catalog.fixtures))
        return _verdict(piece, None, close, "no fixture with this name")
    if not piece.owner:
        functions = [s for s in catalog.symbols if s.kind == "function" and "." not in s.name]
        same = [s for s in functions if s.name == piece.name]
        if same:
            return GapVerdict(piece=piece, status="exists", found=same[0].qualname)
        # A model often leaves the owner out for helpers on the test base class (``self.x()``).
        for base in sorted(scope.base_classes):
            if piece.name in catalog.classes[base].members:
                found = f"{catalog.classes[base].name}.{piece.name}"
                return GapVerdict(piece=piece, status="exists", owner_class=base, found=found)
        nearby = [
            s.name for s in functions if s.qualname.rsplit(".", 1)[0] in scope.imported_modules
        ]
        helpers = [n for b in scope.base_classes for n in _members(catalog, b)]
        elsewhere = [
            f"{c.name}.{piece.name} (on another class)"
            for c in catalog.classes.values()
            if piece.name in c.members and _reachable(c, catalog, scope)
        ]
        close = (_close(piece.name, nearby + helpers) + elsewhere)[:MAX_CLOSE]
        return _verdict(piece, None, close, "")

    owner = _resolve_owner(piece.owner, catalog, settings)
    if owner is None:
        return GapVerdict(
            piece=piece,
            status="owner_unknown",
            reason=f"{piece.owner!r} is not a page-object chain or a class in the repo",
        )
    if not _reachable(owner, catalog, scope):
        return GapVerdict(
            piece=piece,
            status="not_test_side",
            owner_class=owner.qualname,
            reason=f"{owner.name} is not something the tests reach (product code?)",
        )
    members = catalog.members_of(owner.qualname)
    if piece.name in members:
        defined_in, _ = members[piece.name]
        return GapVerdict(
            piece=piece,
            status="exists",
            owner_class=owner.qualname,
            found=f"{defined_in.name}.{piece.name}",
        )
    candidates = [f"{owner.name}.{n}" for n in members]
    candidates += [f"{c.name}.{n}" for c in _siblings(owner, catalog) for n in c.members]
    if piece.kind == "helper":
        candidates += [f"{catalog.classes[b].name}.{n}" for b in scope.base_classes
                       for n in catalog.classes[b].members]  # fmt: skip
    close = _close(piece.name, candidates)
    elsewhere = [
        f"{c.name}.{piece.name} (on another class)"
        for c in catalog.classes.values()
        if piece.name in c.members
        and c.qualname != owner.qualname
        and _reachable(c, catalog, scope)
    ]
    return _verdict(piece, owner, (close + elsewhere)[:MAX_CLOSE], "")


def _verdict(
    piece: MissingPiece, owner: ClassEntry | None, close: list[str], reason: str
) -> GapVerdict:
    return GapVerdict(
        piece=piece,
        status="close_match" if close else "missing",
        owner_class=owner.qualname if owner else None,
        close=close,
        reason=reason or ("may already exist under another name" if close else "not found"),
    )


def _scope(index: IndexData, settings: Settings) -> _Scope:
    catalog = index.catalog
    tests = [c for c in index.chunks if c.kind == "test"]
    bases: set[str] = set()
    for test in tests:
        info = index.files[test.file_path].info
        if info is None or not test.class_name:
            continue
        for base in catalog.mro(f"{info.module}.{test.class_name}")[1:]:
            bases.add(base.qualname)
    modules = {
        info.module
        for path in imported_files(tests, catalog, index)
        if (info := index.files[path].info) is not None
    }
    imported_classes = {c.qualname for c in catalog.classes.values() if c.module in modules}
    return _Scope(set(catalog.page_objects) | bases | imported_classes, bases, modules)


def _resolve_owner(owner: str, catalog: SymbolCatalog, settings: Settings) -> ClassEntry | None:
    text = owner.removesuffix("()").strip()
    if text.split(".")[0] in catalog.chain_roots:
        resolution = catalog.resolve_chain_from_roots(text)
        last = resolution.types[-1] if resolution.ok and resolution.types else None
        return catalog.classes.get(last) if last else None
    return catalog.class_named(text)


def _reachable(owner: ClassEntry, catalog: SymbolCatalog, scope: _Scope) -> bool:
    return owner.qualname in scope.test_side or any(
        b.qualname in scope.test_side for b in catalog.mro(owner.qualname)
    )


def _siblings(owner: ClassEntry, catalog: SymbolCatalog) -> list[ClassEntry]:
    """Pages next to the owner: the other page types of the classes that hold the owner
    (``nav.files.*``). From the type graph, so a cut chain list can't hide any."""
    page_objects = set(catalog.page_objects)
    found: dict[str, ClassEntry] = {}
    for parent in catalog.referrers(owner.qualname):
        for target in catalog.member_types(parent).values():
            if target.qualname != owner.qualname and target.qualname in page_objects:
                found[target.qualname] = target
    return [found[q] for q in sorted(found)]


def _members(catalog: SymbolCatalog, qualname: str) -> list[str]:
    entry = catalog.classes.get(qualname)
    return [f"{entry.name}.{n}" for n in entry.members] if entry else []


def _close(name: str, candidates: list[str]) -> list[str]:
    wanted = _words(name)
    if not wanted:
        return []
    scored: dict[str, float] = {}
    for candidate in candidates:
        member = candidate.rsplit(".", 1)[-1]
        if member.startswith("_") or member == name:
            continue
        words = _words(member)
        if not words:
            continue
        score = len(wanted & words) / len(wanted | words)
        if score >= CLOSE_MIN:
            scored[candidate] = max(score, scored.get(candidate, 0.0))
    ranked = sorted(scored.items(), key=lambda kv: (-kv[1], kv[0]))
    return [c for c, _ in ranked[:MAX_CLOSE]]


def _words(name: str) -> set[str]:
    return {norm(w) for w in split_identifier(name) if w}
