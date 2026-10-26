"""Symbol catalog: which names exist, incl. page-object property chains (``nav.<area>.<page>``).

Types are resolved statically from annotations (``-> Navigator``, ``api: ApiClient``), from
``return Navigator(...)`` in unannotated code, and from
``self.x = Callee(...)`` assignments, following base classes. A chain step that reaches a
type outside the repo (e.g. a library's ``WebDriver``) can't be checked further and is
reported as ``unknown_type`` rather than as an invented name.
"""

from __future__ import annotations

import re
from collections import deque
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, PrivateAttr

from ticket2test.index.extract import Assign, FileInfo, FunctionInfo

SymbolKind = Literal[
    "module", "class", "function", "method", "property", "attribute", "variable", "fixture"
]
MemberKind = Literal["method", "property", "attribute"]

_TYPING_WORDS = frozenset(
    {
        "Optional", "Union", "None", "Any", "list", "dict", "tuple", "set", "frozenset", "type",
        "str", "int", "float", "bool", "bytes", "Callable", "Iterator", "Iterable", "Sequence",
        "Mapping", "Generator", "Literal", "ClassVar", "Final", "Self", "typing", "collections",
        "abc",
    }
)  # fmt: skip
_IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_MAX_MRO = 25


class Symbol(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    qualname: str  # "module.Class.method"
    kind: SymbolKind
    file_path: str
    line: int


class Member(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    kind: MemberKind
    type_text: str | None = None  # annotation / callee / return annotation, as written
    returns_self: bool = False
    line: int


class ClassEntry(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    qualname: str  # "module.Class"
    name: str
    module: str
    file_path: str
    line: int
    bases: list[str] = Field(default_factory=list)  # as written
    members: dict[str, Member] = Field(default_factory=dict)


class ChainEntry(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    chain: str  # "nav.inventory.items.search"
    kind: MemberKind
    owner: str  # class qualname that has the last step
    type: str | None = None  # resolved class qualname of the last step, if any


class ChainResolution(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    status: Literal["ok", "missing", "unknown_type", "no_root"]
    types: list[str | None] = Field(default_factory=list)  # resolved type after each step
    failed_step: int | None = None  # index into the steps
    message: str = ""

    @property
    def ok(self) -> bool:
        return self.status == "ok"


class SymbolCatalog(BaseModel):
    model_config = ConfigDict(extra="forbid")

    symbols: list[Symbol] = Field(default_factory=list)
    classes: dict[str, ClassEntry] = Field(default_factory=dict)
    fixtures: dict[str, bool] = Field(default_factory=dict)  # name -> parametrized
    markers: dict[str, list[str]] = Field(default_factory=dict)  # marker -> values seen
    chain_roots: list[str] = Field(default_factory=list)
    chains: list[ChainEntry] = Field(default_factory=list)
    chains_truncated: bool = False  # the chain list hit index.max_chain_entries
    _resolving: set[str] = PrivateAttr(default_factory=set)  # return chains being followed
    page_objects: list[str] = Field(default_factory=list)  # class qualnames

    # --- lookups -------------------------------------------------------------------------

    def has(self, name: str) -> bool:
        """True if a symbol with this simple name, qualname, or chain exists."""
        return bool(self.find(name)) or any(c.chain == name for c in self.chains)

    def find(self, name: str) -> list[Symbol]:
        return [s for s in self.symbols if name in (s.name, s.qualname)]

    def class_named(self, name: str, prefer_module: str | None = None) -> ClassEntry | None:
        simple = name.rsplit(".", 1)[-1]
        if name in self.classes:
            return self.classes[name]
        candidates = sorted(
            (c for c in self.classes.values() if c.name == simple), key=lambda c: c.qualname
        )
        if not candidates:
            return None
        for candidate in candidates:
            if candidate.module == prefer_module:
                return candidate
        return candidates[0]

    def resolve_type(self, type_text: str | None, module: str | None = None) -> ClassEntry | None:
        """First identifier in an annotation that names a class in the repo."""
        if not type_text:
            return None
        for word in _IDENT.findall(type_text.replace("'", "").replace('"', "")):
            if word in _TYPING_WORDS:
                continue
            found = self.class_named(word, module)
            if found is not None:
                return found
        return None

    def mro(self, qualname: str) -> list[ClassEntry]:
        """The class and its in-repo bases, depth-first, without repeats (bounded)."""
        order: list[ClassEntry] = []
        stack = [qualname]
        seen: set[str] = set()
        while stack and len(order) < _MAX_MRO:
            current = self.classes.get(stack.pop(0))
            if current is None or current.qualname in seen:
                continue
            seen.add(current.qualname)
            order.append(current)
            resolved = [self.resolve_type(b, current.module) for b in current.bases]
            stack = [b.qualname for b in resolved if b is not None] + stack
        return order

    def member(self, qualname: str, name: str) -> tuple[ClassEntry, Member] | None:
        for entry in self.mro(qualname):
            if name in entry.members:
                return entry, entry.members[name]
        return None

    def external_bases(self, qualname: str) -> list[str]:
        """Bases (as written) up the class's lineage that aren't repo classes, such as
        ``unittest.TestCase``: members may come from them, so a name not found isn't proof
        that it doesn't exist."""
        found: list[str] = []
        for entry in self.mro(qualname):
            for written in entry.bases:
                bare = written.split("[")[0].strip()
                if bare in ("object", "") or self.resolve_type(bare, entry.module) is not None:
                    continue
                if bare not in found:
                    found.append(bare)
        return found

    def members_of(self, qualname: str) -> dict[str, tuple[ClassEntry, Member]]:
        found: dict[str, tuple[ClassEntry, Member]] = {}
        for entry in self.mro(qualname):
            for name, member in entry.members.items():
                found.setdefault(name, (entry, member))
        return found

    def member_types(self, qualname: str) -> dict[str, ClassEntry]:
        """Property/attribute members of the class (and its bases) whose type is a repo class."""
        owner = self.classes.get(qualname)
        if owner is None:
            return {}
        found: dict[str, ClassEntry] = {}
        for name, (defined_in, member) in self.members_of(qualname).items():
            if member.kind in ("property", "attribute"):
                target = self._member_type(defined_in, member, owner)
                if target is not None:
                    found[name] = target
        return found

    def referrers(self, qualname: str) -> list[str]:
        """Classes with a property/attribute whose type is this class (its parent pages)."""
        return sorted(
            c.qualname
            for c in self.classes.values()
            if any(t.qualname == qualname for t in self.member_types(c.qualname).values())
        )

    def resolve_chain(self, start: str, steps: list[str]) -> ChainResolution:
        """Resolve ``steps`` (e.g. ["nav", "inventory", "items", "search"]) from class ``start``.

        A step may end in "()" to mean "call it" (its return type is used).
        """
        owner = self.class_named(start)
        if owner is None:
            return ChainResolution(status="no_root", message=f"unknown class {start!r}")
        types: list[str | None] = []
        for index, raw in enumerate(steps):
            name = raw.removesuffix("()")
            found = self.member(owner.qualname, name)
            if found is None:
                outside = self.external_bases(owner.qualname)
                if outside:  # may be inherited from a class outside the repo
                    return ChainResolution(
                        status="unknown_type",
                        types=types,
                        failed_step=index,
                        message=f"{owner.name}.{name} may come from {', '.join(outside)}",
                    )
                return ChainResolution(
                    status="missing",
                    types=types,
                    failed_step=index,
                    message=f"{owner.name} has no member {name!r}",
                )
            defined_in, member = found
            next_type = self._member_type(defined_in, member, owner)
            types.append(next_type.qualname if next_type else None)
            if index == len(steps) - 1:
                break
            if next_type is None:
                return ChainResolution(
                    status="unknown_type",
                    types=types,
                    failed_step=index,
                    message=f"type of {owner.name}.{name} is not a class in this repo",
                )
            owner = next_type
        return ChainResolution(status="ok", types=types)

    def resolve_chain_from_roots(self, chain: str) -> ChainResolution:
        """Resolve a dotted chain starting at a configured root (e.g. ``nav.users.invite``)."""
        steps = chain.split(".")
        owners = (
            [c.qualname for c in self.classes.values() if steps[0] in c.members]
            if steps and steps[0] in self.chain_roots
            else []
        )
        if not owners:
            return ChainResolution(status="no_root", message=f"{steps[0]!r} is not a chain root")
        best: ChainResolution | None = None
        for owner in sorted(owners):
            result = self.resolve_chain(owner, steps)
            if result.ok:
                return result
            best = best or result
        assert best is not None
        return best

    def _member_type(
        self, defined_in: ClassEntry, member: Member, owner: ClassEntry
    ) -> ClassEntry | None:
        if member.returns_self:
            return owner
        text = member.type_text or ""
        if text.startswith("self."):  # ``return self.nav.area.page``: follow it from the owner
            key = f"{owner.qualname}:{text}"
            if key in self._resolving or len(self._resolving) > 32:
                return None  # a cycle, or too deep
            self._resolving.add(key)
            try:
                result = self.resolve_chain(owner.qualname, text.split(".")[1:])
            finally:
                self._resolving.discard(key)
            last = result.types[-1] if result.ok and result.types else None
            return self.classes.get(last) if last else None
        return self.resolve_type(member.type_text, defined_in.module)


# --- building -------------------------------------------------------------------------------


def _is_property(fn: FunctionInfo) -> bool:
    return any(
        d.split("(")[0].split(".")[-1] in ("property", "cached_property") for d in fn.decorators
    )


def _is_fixture(fn: FunctionInfo) -> bool:
    return any(d.split("(")[0] in ("pytest.fixture", "fixture") for d in fn.decorators)


def _returns_self(fn: FunctionInfo, class_name: str) -> bool:
    if not fn.returns:
        return False
    returns = fn.returns.strip().strip("'\"")
    self_annotation = fn.params[0].annotation if fn.params else None
    return returns in ("Self", "typing.Self", class_name) or (
        self_annotation is not None and returns == self_annotation.strip("'\"")
    )


def _return_type(fn: FunctionInfo) -> str | None:
    """The return annotation, else the callee when every ``return`` builds one thing."""
    if fn.returns:
        return fn.returns
    return fn.returned_calls[0] if len(fn.returned_calls) == 1 else None


def _assign_type(assign: Assign) -> str | None:
    return assign.annotation or assign.call


def build_catalog(
    files: list[FileInfo],
    markers: dict[str, set[str]] | None = None,
    chain_roots: list[str] | None = None,
    max_chain_depth: int = 4,
    max_chain_entries: int = 5000,
) -> SymbolCatalog:
    catalog = SymbolCatalog(chain_roots=list(chain_roots or []))
    for info in files:
        _add_file(catalog, info)
    catalog.markers = {k: sorted(v) for k, v in sorted((markers or {}).items())}
    catalog.chains, catalog.chains_truncated = _enumerate_chains(
        catalog, max_chain_depth, max_chain_entries
    )
    catalog.page_objects = _page_objects(catalog)
    return catalog


def _add_file(catalog: SymbolCatalog, info: FileInfo) -> None:
    module_short = info.module.rsplit(".", 1)[-1]
    catalog.symbols.append(
        Symbol(name=module_short, qualname=info.module, kind="module", file_path=info.path, line=1)
    )
    for fn in info.functions:
        kind: SymbolKind = "fixture" if _is_fixture(fn) else "function"
        catalog.symbols.append(
            Symbol(
                name=fn.name,
                qualname=f"{info.module}.{fn.name}",
                kind=kind,
                file_path=info.path,
                line=fn.start_line,
            )
        )
        if kind == "fixture":
            catalog.fixtures[fn.name] = any("params=" in d for d in fn.decorators)
    for assign in info.assignments:
        catalog.symbols.append(
            Symbol(
                name=assign.name,
                qualname=f"{info.module}.{assign.name}",
                kind="variable",
                file_path=info.path,
                line=assign.line,
            )
        )

    for cls in info.classes:
        qual = f"{info.module}.{cls.name}"
        catalog.symbols.append(
            Symbol(
                name=cls.name, qualname=qual, kind="class", file_path=info.path, line=cls.start_line
            )
        )
        members: dict[str, Member] = {}
        for assign in cls.attributes:
            members[assign.name] = Member(
                name=assign.name, kind="attribute", type_text=_assign_type(assign), line=assign.line
            )
        for fn in cls.methods:
            if _is_fixture(fn):
                catalog.fixtures[fn.name] = any("params=" in d for d in fn.decorators)
            member_kind: MemberKind = "property" if _is_property(fn) else "method"
            # A property setter (``@x.setter``) has the getter's name; the getter comes first.
            members.setdefault(
                fn.name,
                Member(
                    name=fn.name,
                    kind=member_kind,
                    type_text=_return_type(fn),
                    returns_self=_returns_self(fn, cls.name),
                    line=fn.start_line,
                ),
            )
            for assign in fn.self_assignments:
                existing = members.get(assign.name)
                if existing is None or (
                    existing.kind == "attribute" and existing.type_text is None
                ):
                    members[assign.name] = Member(
                        name=assign.name,
                        kind="attribute",
                        type_text=_assign_type(assign),
                        line=assign.line,
                    )
        for name, member in members.items():
            symbol_kind: SymbolKind = "method" if member.kind == "method" else member.kind
            catalog.symbols.append(
                Symbol(
                    name=name,
                    qualname=f"{qual}.{name}",
                    kind=symbol_kind,
                    file_path=info.path,
                    line=member.line,
                )
            )
        catalog.classes[qual] = ClassEntry(
            qualname=qual,
            name=cls.name,
            module=info.module,
            file_path=info.path,
            line=cls.start_line,
            bases=cls.bases,
            members=members,
        )


def _enumerate_chains(
    catalog: SymbolCatalog, max_depth: int, max_entries: int
) -> tuple[list[ChainEntry], bool]:
    """Breadth-first over property/attribute steps from each root, bounded by depth and size.
    Also says whether the size bound cut the list (nothing else depends on it being whole:
    page objects and validation follow the class types directly)."""
    entries: dict[str, ChainEntry] = {}
    queue: deque[tuple[str, str, int, frozenset[str]]] = deque()
    for root in catalog.chain_roots:
        for owner in sorted(c.qualname for c in catalog.classes.values() if root in c.members):
            found = catalog.member(owner, root)
            if found is None:
                continue
            defined_in, member = found
            target = catalog._member_type(defined_in, member, catalog.classes[owner])
            entries.setdefault(
                root,
                ChainEntry(
                    chain=root,
                    kind=member.kind,
                    owner=owner,
                    type=target.qualname if target else None,
                ),
            )
            if target is not None:
                queue.append((target.qualname, root, 1, frozenset({target.qualname})))

    while queue and len(entries) < max_entries:
        owner, prefix, depth, path_types = queue.popleft()
        for name, (defined_in, member) in sorted(catalog.members_of(owner).items()):
            if name.startswith("_"):
                continue
            chain = f"{prefix}.{name}"
            target = catalog._member_type(defined_in, member, catalog.classes[owner])
            if chain not in entries:
                entries[chain] = ChainEntry(
                    chain=chain,
                    kind=member.kind,
                    owner=owner,
                    type=target.qualname if target else None,
                )
            if (
                target is not None
                and member.kind in ("property", "attribute")
                and depth < max_depth
                and target.qualname not in path_types
            ):
                queue.append((target.qualname, chain, depth + 1, path_types | {target.qualname}))
            if len(entries) >= max_entries:
                break
    return list(entries.values()), bool(queue) or len(entries) >= max_entries


def reachable_types(catalog: SymbolCatalog) -> set[str]:
    """Classes reached from the chain roots through property/attribute types, however deep or
    many (bounded by the number of classes, each visited once)."""
    reached: set[str] = set()
    queue: deque[str] = deque()
    for root in catalog.chain_roots:
        for owner in (c for c in catalog.classes.values() if root in c.members):
            found = catalog.member(owner.qualname, root)
            if found is None:
                continue
            target = catalog._member_type(found[0], found[1], owner)
            if target is not None and target.qualname not in reached:
                reached.add(target.qualname)
                queue.append(target.qualname)
    while queue:
        owner_q = queue.popleft()
        owner = catalog.classes[owner_q]
        for _, (defined_in, member) in catalog.members_of(owner_q).items():
            if member.kind not in ("property", "attribute"):
                continue
            target = catalog._member_type(defined_in, member, owner)
            if target is not None and target.qualname not in reached:
                reached.add(target.qualname)
                queue.append(target.qualname)
    return reached


def _page_objects(catalog: SymbolCatalog) -> list[str]:
    """Classes reachable from a root through property types, plus their in-repo base classes."""
    reached = reachable_types(catalog)
    found: set[str] = set()
    for qualname in reached:
        found.update(entry.qualname for entry in catalog.mro(qualname))
    return sorted(found)
