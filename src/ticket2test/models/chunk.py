"""Retrieval units extracted from a target repo."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

ChunkKind = Literal["test", "function", "class", "page_object"]
DataFormat = Literal["array", "object"]  # list of entries with an id field, or id -> entry


class Refs(BaseModel):
    """What a definition references, read from the syntax tree (not from text).

    Comments, docstrings and string literals are ignored (f-string ``{...}`` code is not);
    parameter declarations, keyword-argument names and the definition's own name are not
    references.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    calls: list[str] = Field(default_factory=list)  # called names, in order: f(...) / x.f(...)
    names: dict[str, int] = Field(default_factory=dict)  # referenced identifiers -> count
    self_chains: list[list[str]] = Field(default_factory=list)  # ["nav", "users", "open()", ...]


class Marker(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    args: list[Any] = Field(default_factory=list)  # literal values; source text if not literal
    source: Literal["function", "class"] = "function"


class Parametrize(BaseModel):
    """One ``@pytest.mark.parametrize`` decorator, in source order (top to bottom)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    source: str
    argnames: list[str] = Field(default_factory=list)
    ids: list[str] | None = None  # per-decorator ids; None if not statically computable


class Chunk(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str  # "<file_path>::<qualname>"
    file_path: str  # repo-relative, POSIX separators
    symbol_name: str
    qualname: str  # "Class.method" or "function"
    kind: ChunkKind
    language: Literal["python"] = "python"
    code: str  # whole definition including decorators; never cut mid-function
    start_line: int
    end_line: int
    docstring: str | None = None
    refs: Refs = Field(default_factory=Refs)  # from the syntax tree

    # Tests only
    class_name: str | None = None
    decorators: list[str] = Field(default_factory=list)
    markers: list[Marker] = Field(default_factory=list)
    parametrize: list[Parametrize] = Field(default_factory=list)
    fixtures: list[str] = Field(default_factory=list)
    test_ids: list[str] = Field(default_factory=list)  # pytest names, e.g. "test_x[1-a]"
    test_ids_computed: bool = True  # False: ids need `pytest --collect-only` to know
    test_ids_note: str | None = None
    data_file: str | None = None
    data_entries: dict[str, Any] = Field(default_factory=dict)  # test id -> JSON entry
    data_format: DataFormat | None = None  # layout of data_file
