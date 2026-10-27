"""Generated tests: what the LLM returns (wire model) and the stored code + data pair.

Wire model (``generate_v2``): the code, a module name, and for each data entry a *plan*
(which sections of the base entry to keep, and which values to change). The entries
themselves are built deterministically from the base entry (``generate/entries.py``).
"""

from __future__ import annotations

import json
import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, model_validator

from ticket2test.models.chunk import DataFormat

# Validation context keys (set by the generator).
CTX_TEST_PREFIX = "test_function_prefix"
CTX_CLASS_PREFIX = "test_class_prefix"
CTX_BASE_ENTRY = "base_entry"
CTX_BASE_ID = "base_id"
CTX_ID_FIELD = "id_field"
CTX_PER_ENTRY_KEYS = "per_entry_keys"
CTX_DATA_ACCESS = "data_access"
CTX_EXPECTATIONS = "expectation_sections"  # section -> helper that reads it
CTX_EXPECTATION_SETS = "allowed_expectation_sets"  # sections an entry may carry together
CTX_SEED_SECTIONS = "seed_sections"
CTX_TICKET_ID = "ticket_id"
CTX_INHERITED_IDS = "inherited_ids"  # ids of tests the template class inherits

# How a draft becomes code (generate/reuse.py): already covered by an existing test, a new
# case of an existing parametrized test, a new method in an existing class, or a new module.
ReuseKind = Literal["covered", "variant", "method", "module", "out_of_scope"]


class EntryChange(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    op: Literal["set", "delete"]
    path: str  # dotted; list items by index, e.g. "interactions.0.response.body.quantity"
    value_json: str  # the new value as JSON text ("" for delete)


class EntryPlan(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    test_id: str
    copy_sections: list[str]  # top-level keys of the base entry to keep
    changes: list[EntryChange]

    def change_tuples(self) -> list[tuple[str, str, str]]:
        return [(c.op, c.path, c.value_json) for c in self.changes]


class VariantPlan(BaseModel):
    """A new case of an existing parametrized test: its parametrize value, the existing case
    whose data entry it clones, and the values that change in the clone."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    case: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,40}$")  # the new parametrize value
    base_case: str  # an existing parametrize value
    changes: list[EntryChange] = Field(min_length=1)
    notes: str  # what else may need to change (reviewer)

    @model_validator(mode="after")
    def _values_are_json(self) -> VariantPlan:
        """Caught here, a bad value (e.g. a regex with an unescaped backslash) goes back to the
        LLM with the error instead of failing the patch."""
        for change in self.changes:
            if change.op == "set":
                try:
                    json.loads(change.value_json)
                except json.JSONDecodeError as exc:
                    raise ValueError(
                        f"{change.path}: value_json is not valid JSON ({exc}); escape "
                        "backslashes and quotes inside JSON strings"
                    ) from exc
        return self


class VariantPlanResponse(BaseModel):
    """What the ``variant_v1`` prompt returns (only when the deterministic plan can't)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    variants: list[VariantPlan] = Field(min_length=1, max_length=10)


class PatchedFile(BaseModel):
    """An existing target-repo file changed by a reuse patch (the repo itself is never written:
    the patched copy and this diff go to the output directory)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    path: str  # repo-relative
    diff: str  # unified diff, a/<path> -> b/<path>


class GenerationResponse(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    module_name: str  # file name stem, e.g. "test_orders_detail_restock"
    code: str
    entries: list[EntryPlan]
    review_checklist: list[str]  # things only a real run can confirm
    notes: str

    @model_validator(mode="after")
    def _consistent(self, info: ValidationInfo) -> GenerationResponse:
        """Ids, entries, data keys, and names must agree, so mistakes go back to the LLM."""
        from ticket2test.generate.entries import EntryError, build_entry, function_of
        from ticket2test.generate.inspect import computed_test_ids, data_use, defined_names

        ctx: dict[str, Any] = info.context if isinstance(info.context, dict) else {}
        test_prefix = ctx.get(CTX_TEST_PREFIX, "test")
        class_prefix = ctx.get(CTX_CLASS_PREFIX, "Test")
        ids = computed_test_ids(self.code, test_prefix, class_prefix)

        problems = _name_problems(
            [self.module_name, *defined_names(self.code, test_prefix, class_prefix)],
            ctx.get(CTX_TICKET_ID),
        )
        if not re.fullmatch(rf"{re.escape(test_prefix)}_[a-z0-9_]+", self.module_name):
            problems.append(
                f"module_name {self.module_name!r} must look like {test_prefix}_area_action"
            )
        if problems:
            raise ValueError("; ".join(problems))

        keys = [e.test_id for e in self.entries]
        if len(keys) != len(set(keys)):
            raise ValueError("entries contain duplicate test_id values")
        uses = data_use(
            self.code,
            ctx.get(CTX_DATA_ACCESS, ["self.params", "params"]),
            _helper_list(ctx.get(CTX_EXPECTATIONS, {})),
            test_prefix,
        )
        inherited = set(ctx.get(CTX_INHERITED_IDS, []))  # their entries are added in code
        extra = [k for k in keys if k not in ids and k not in inherited]
        missing = [
            i for i in ids if uses.get(function_of(i)) and uses[function_of(i)].reads_data
            and i not in keys
        ]  # fmt: skip
        if len(extra) == 1 and len(missing) == 1:  # one mislabelled entry: re-keyed in code
            keys = [missing[0] if k == extra[0] else k for k in keys]
            extra, missing = [], []
        if extra:
            raise ValueError(
                f"entries for ids the code doesn't produce: {extra}. Computed from the code: {ids}."
            )
        if missing:
            raise ValueError(
                f"these tests use their data entry but have no entry: {missing}. Give one "
                "entry per pytest id of every test that reads keys or calls a validation helper."
            )

        base = ctx.get(CTX_BASE_ENTRY)
        if base is None:
            return self
        for plan, test_id in zip(self.entries, keys, strict=True):
            try:
                entry = build_entry(
                    base,
                    ctx.get(CTX_BASE_ID, ""),
                    test_id,
                    plan.copy_sections,
                    plan.change_tuples(),
                    id_field=ctx.get(CTX_ID_FIELD, "id"),
                    per_entry_keys=ctx.get(CTX_PER_ENTRY_KEYS, []),
                    test_prefix=test_prefix,
                )
            except EntryError as exc:
                raise ValueError(str(exc)) from exc
            use = uses.get(function_of(test_id))
            absent = sorted(use.keys - set(entry)) if use else []
            if absent:
                raise ValueError(
                    f"{test_id} reads keys its entry lacks: {absent}. Add them with "
                    "changes (op set) or copy them from the base entry."
                )
            _unread, conflict = unconsumed_keys(entry, use, ctx)
            if conflict:  # unread keys alone are removed in code (generator.assemble)
                raise ValueError(f"{test_id}: {conflict}")
        return self


def unconsumed_keys(
    entry: dict[str, Any], use: Any, ctx: dict[str, Any]
) -> tuple[dict[str, str], str]:
    """Keys nobody reads (key -> why), and a conflict code can't fix ("" if none).

    Every key must be read by the test or consumed by the framework or a helper it calls. An
    unread key can simply be removed; two expectation sections whose helpers are both called
    can't (which one is meant?).
    """
    from ticket2test.generate.inspect import helper_matches

    expectations = {
        section: [h] if isinstance(h, str) else list(h)
        for section, h in ctx.get(CTX_EXPECTATIONS, {}).items()
    }
    fixed = {ctx.get(CTX_ID_FIELD, "id"), *ctx.get(CTX_SEED_SECTIONS, [])}
    fixed |= set(ctx.get(CTX_PER_ENTRY_KEYS, []))
    read = (use.keys | use.optional_keys) if use else frozenset()
    helpers = use.helpers if use else frozenset()
    whole = bool(getattr(use, "passes_whole", False))  # the entry goes to a call: any key
    unread: dict[str, str] = {}
    for key in entry:
        if key in fixed or key in read or whole:
            continue
        if key in expectations:
            if not any(helper_matches(h, expectations[key]) for h in helpers):
                names = " or ".join(f"{p}()" for p in expectations[key])
                unread[key] = f"{key!r} is only read by {names}, which the test never calls"
        else:
            unread[key] = f"custom key {key!r} is never read by the test"
    present = [k for k in expectations if k in entry and k not in unread]
    allowed = [sorted(group) for group in ctx.get(CTX_EXPECTATION_SETS, [])]
    together = len(present) > 1 and sorted(present) not in allowed
    conflict = f"an entry has one expectation section, not {present}" if together else ""
    return unread, conflict


def _helper_list(sections: dict[str, Any]) -> list[str]:
    return [h for v in sections.values() for h in ([v] if isinstance(v, str) else v)]


def _unconsumed_keys(entry: dict[str, Any], use: Any, ctx: dict[str, Any]) -> str:
    """The problems as one message (for the validator)."""
    unread, conflict = unconsumed_keys(entry, use, ctx)
    if conflict:
        return conflict
    if unread:
        return "; ".join(unread.values()) + ". Remove it, or read it in the test."
    return ""


def _name_problems(names: list[str], ticket_id: str | None) -> list[str]:
    """Names must not contain the ticket key or its number."""
    if not ticket_id:
        return []
    number = re.findall(r"\d+", ticket_id)
    slug = re.sub(r"[^a-z0-9]+", "_", ticket_id.lower()).strip("_")
    bad = [
        n for n in names
        if slug in n.lower() or any(re.search(rf"(?<!\d){d}(?!\d)", n) for d in number)
    ]  # fmt: skip
    return [f"names must not contain the ticket id {ticket_id}: {bad}"] if bad else []


class TemplateEntryRef(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    chunk_id: str
    entry_key: str


class GeneratedTest(BaseModel):
    """A generated test: a code file plus its JSON data entries, with traceability."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    code: str
    file_name: str  # where it would go in the target repo (repo-relative); never written there
    data_file_name: str
    data_entries: list[dict[str, Any]]  # each with its id field, in code order
    data_format: DataFormat  # how the data file is written
    test_ids: list[str]
    template_entry_ref: TemplateEntryRef | None  # the base entry
    ticket_id: str
    draft_ref: str
    retrieved_chunk_ids: list[str]  # chunks actually placed in the context
    prompt_version: str
    provider: str
    model: str
    attempts: int = Field(ge=0)  # LLM calls (0: a deterministic patch)
    context_tokens: int = Field(ge=0)  # estimated
    redactions: int = Field(default=0, ge=0)
    notes: str = ""
    review_checklist: list[str] = Field(default_factory=list)  # "needs a real run" items
    entry_plans: list[EntryPlan] = Field(default_factory=list)  # as the LLM chose them
    validation_report: dict[str, Any] | None = None  # Phase 7
    collect_report: dict[str, Any] | None = None  # Phase 7
    # Reuse (variant / method): ``code`` and ``data_entries`` are the whole patched files.
    reuse_kind: ReuseKind = "module"
    reuse_target: str | None = None  # chunk id (variant) or class name (method)
    reuse_reasons: list[str] = Field(default_factory=list)
    variant_plans: list[VariantPlan] = Field(default_factory=list)
    patches: list[PatchedFile] = Field(default_factory=list)
    # The ids this output adds (a patch's test_ids list the whole patched file); empty: test_ids.
    new_test_ids: list[str] = Field(default_factory=list)
    run_report: dict[str, Any] | None = None  # from a real run's log (`ticket2test results`)
