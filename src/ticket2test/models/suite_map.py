"""The suite map: what the test suite looks like, per area, built from the index by code."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class Count(BaseModel):
    """A name and how often it occurs (tests, classes or entries, as the field says)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    count: int


class TestClassSummary(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    file_path: str
    bases: list[str]  # as written
    decorators: list[str]  # source order, without "@"
    setup_calls: list[str]  # calls with keywords in setup/teardown methods, e.g. "base_setup(x=1)"
    tests: int  # test functions (inherited ones not counted)


class AreaSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    folders: list[str]
    test_files: list[str]
    data_files: list[str]
    tests: int  # test functions
    test_ids: int  # pytest ids, parametrize included
    parametrized: int  # test functions with at least one parametrize
    classes: list[TestClassSummary]
    shapes: list[Count]  # "ui add", "api other", ... -> tests
    markers: list[Count]  # "priority=p1" -> tests (function and class markers)
    chains: list[Count]  # page-object chains -> tests using them
    page_actions: list[Count]  # calls to members of the page objects the area reaches
    base_helpers: list[Count]  # calls to members of the test classes' base classes
    functions: list[Count]  # calls to other functions defined in the repo
    assertions: list[Count]  # assert* calls
    fixtures: list[Count]  # fixture parameters of the tests
    data_entries: int
    data_keys: list[Count]  # top-level entry keys -> entries
    data_key_roles: dict[str, str]  # key -> seed / expectation / per entry / read by the test
    expectations: list[Count]  # "<section>: <method> <path>" -> entries
    placeholders: list[Count]  # brace placeholders in entry values -> entries
    skipped: int  # tests with a skip marker or an entry-level skip
    examples: list[str]  # chunk ids: the most typical test per shape
    sources: dict[str, str]  # path -> sha256: the files this summary was built from
    digest: str  # sha256 over ``sources``; changes when any source changes


class CoverageGap(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: str  # "page_object", "page_member", "base_helper", "function"
    name: str  # qualname, or "Class.member"
    file_path: str


class SuiteOverview(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tests: int
    test_ids: int
    test_classes: int
    data_entries: int
    base_classes: list[Count]  # in-repo bases of test classes -> test classes using them
    chain_roots: list[str]
    page_areas: list[Count]  # first chain step below a root, e.g. "nav.rules" -> tests
    shared_helpers: list[Count]  # base-class helpers used in two or more areas -> areas
    marker_values: dict[str, list[str]]
    unassigned_tests: list[str]  # test chunk ids outside every area


class SuiteMap(BaseModel):
    model_config = ConfigDict(extra="forbid")

    repo_root: str
    built_at: datetime
    commit: str | None = None  # HEAD when the repo is a git checkout
    index_fingerprint: str
    overview: SuiteOverview
    areas: list[AreaSummary]
    coverage: list[CoverageGap] = Field(default_factory=list)
    changed_areas: list[str] | None = None  # vs the previous map; None when there was none
