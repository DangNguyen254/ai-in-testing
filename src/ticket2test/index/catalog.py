"""Symbol catalog: which names exist, incl. page-object property chains (``nav.<area>.<page>``).

Types are resolved statically from annotations (``-> Navigator``, ``api: ApiClient``) and from
``self.x = Callee(...)`` assignments, following base classes. A chain step that reaches a
type outside the repo (e.g. a library's ``WebDriver``) can't be checked further and is
reported as ``unknown_type`` rather than as an invented name.
"""

from __future__ import annotations

import re
from collections import deque
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

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

    def members_of(self, qualname: str) -> dict[str, tuple[ClassEntry, Member]]:
        found: dict[str, tuple[ClassEntry, Member]] = {}
        for entry in self.mro(qualname):
            for name, member in entry.members.items():
                found.setdefault(name, (entry, member))
        return found

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
    catalog.chains = _enumerate_chains(catalog, max_chain_depth, max_chain_entries)
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
            members.setdefault(
                fn.name,
                Member(
                    name=fn.name,
                    kind=member_kind,
                    type_text=fn.returns,
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


def _enumerate_chains(catalog: SymbolCatalog, max_depth: int, max_entries: int) -> list[ChainEntry]:
    """Breadth-first over property/attribute steps from each root, bounded by depth and size."""
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
    return list(entries.values())


def _page_objects(catalog: SymbolCatalog) -> list[str]:
    """Classes reachable through chains below a root, plus their in-repo base classes."""
    reached = {c.type for c in catalog.chains if c.type is not None}
    found: set[str] = set()
    for qualname in reached:
        found.update(entry.qualname for entry in catalog.mro(qualname))
    return sorted(found)
