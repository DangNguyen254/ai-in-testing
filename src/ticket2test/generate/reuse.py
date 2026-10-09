"""Reuse first: is the draft already covered, a new variant, a new method, or a new module?

Decided by code, inside the ticket's domain (see ``domain.py``), from what the index already
knows about each test there:

- **flow**: the words of its name (area, action, sub-area), its docstring, the names it
  references (page-object steps and helpers, e.g. ``download_file``, ``expect_verdict``), its
  parametrize argument names, and its data keys; without generic words (pytest, markers,
  assertions, data access, the page-object root). Words are weighted by how rare they are in
  the domain (inverse document frequency), so "download" in every file test counts little and
  "dlp" counts a lot;
- **values**: its parametrize ids and the string values of its data entries.

The flow score is the weighted F1 of the draft's words against the test's words, counting only
draft words that occur somewhere in the domain's tests (ticket prose doesn't count against a
test). Then, in order:

1. **covered**: the best test's words match closely on their own (``reuse.covered_min``) and
   the draft names one of its parametrize ids, or every value the draft lists is in its data:
   point to it (strict: nothing is generated);
2. **variant**: the flow matches (``reuse.variant_min``), the test is its own (not inherited)
   with one parametrize decorator, and it is the same kind (UI or API): add a parametrize value
   and an entry to it;
3. **method**: a class in the domain matches (``reuse.method_min``), or is named after what the
   draft tests and matches at least weakly (``reuse.method_named_min``): add a method to it;
4. **module**: a new module; its base and scaffold come from the domain's class whose tests are
   of the same kind and closest in flow (one base class may serve several domains).

Every decision records the candidates, their scores, and why each earlier option was rejected.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field

from ticket2test.config import ReuseSettings, Settings
from ticket2test.generate.domain import DomainChoice
from ticket2test.index.indexer import IndexData
from ticket2test.index.tokens import split_identifier
from ticket2test.models.chunk import Chunk
from ticket2test.models.draft import TestCaseDraft
from ticket2test.models.generated import ReuseKind
from ticket2test.models.retrieval import RetrievalResult
from ticket2test.validate.claims import norm

# A class-name word names the draft's subject only if at most this share of the domain's tests
# use it (stand-in: "download" is in 100% of file tests; "browser", "limit" in 57% of agent tests).
NAME_WORD_MAX_SHARE = 0.75
PARAM_BONUS = 0.2  # ranking only: the draft names one of a test's parametrize values
_WORD = re.compile(r"[A-Za-z][A-Za-z0-9]+|\d+")
_QUOTED = re.compile(r"[\"'`{]{1,2}([^\"'`{}]{1,60})[\"'`}]{1,2}")
_STOP = frozenset(
    norm(w)
    for w in _WORD.findall(
        """the a an and or of to in on at by for with from is are be it its this that
    then when after before into page test tests check checks open click user should must
    shows show same new not no all only each"""
    )
)


@dataclass
class Candidate:
    chunk_id: str
    test: str  # function name
    class_name: str | None
    file_path: str
    kind: str  # "ui" or "api"
    flow: float  # weighted F1 of words (thresholds use this alone)
    parametrized: bool  # its own test with one parametrize decorator: it can take a case
    param_ids: list[str] = field(default_factory=list)
    matched_param: str | None = None  # a parametrize id the draft names
    values_covered: bool = False

    @property
    def rank_score(self) -> float:
        """For ordering candidates: a named parametrize value moves a test up, nothing more."""
        return self.flow + (PARAM_BONUS if self.matched_param else 0.0)


@dataclass
class ReuseDecision:
    kind: ReuseKind
    domain: str | None
    domain_uncertain: bool
    target: str | None  # chunk id (covered / variant), class (method), template class (module)
    target_file: str | None
    test_id: str | None = None  # covered: the existing test id
    candidates: list[Candidate] = field(default_factory=list)
    class_scores: dict[str, float] = field(default_factory=dict)
    reasons: list[str] = field(default_factory=list)


def decide(
    draft: TestCaseDraft,
    retrieval: RetrievalResult,
    index: IndexData,
    settings: Settings,
    choice: DomainChoice,
) -> ReuseDecision:
    reuse = settings.generate.reuse
    domain = choice.domain
    tests = [
        c
        for c in index.chunks
        if c.kind == "test" and (domain is None or domain.contains(c.file_path))
    ]
    decision = ReuseDecision(
        kind="module",
        domain=domain.name if domain else None,
        domain_uncertain=choice.uncertain,
        target=None,
        target_file=None,
    )
    decision.reasons.append(
        f"domain: {choice.reason or 'none'}" + (" (uncertain)" if choice.uncertain else "")
    )
    if not tests:
        decision.reasons.append("no tests in the domain: new module")
        return decision

    generic = _generic_words(settings)
    flows = {c.id: _flow_words(c, generic, settings) for c in tests}
    vocabulary = set().union(*flows.values())
    all_draft_words = _draft_words(draft)
    draft_words = all_draft_words & vocabulary
    weights = _idf(flows.values())
    values = _draft_values(draft)
    retrieved = {h.chunk_id: h.score for h in retrieval.hits}
    candidates = sorted(
        (
            _candidate(c, flows[c.id], draft_words, all_draft_words, values, weights, settings)
            for c in tests
        ),
        key=lambda c: (-c.rank_score, -retrieved.get(c.chunk_id, 0.0), c.chunk_id),
    )[: reuse.candidates]
    decision.candidates = candidates
    best = candidates[0]
    kind = draft.test_kind

    covered = next((c for c in candidates if _covers(c, values, reuse)), None)
    if covered is not None:
        decision.kind, decision.target = "covered", covered.chunk_id
        decision.target_file = covered.file_path
        case = f"[{covered.matched_param}]" if covered.matched_param else ""
        decision.test_id = covered.test + case
        why = (
            f"names its case {covered.matched_param!r}"
            if covered.matched_param
            else "all the draft's values are in its data"
        )
        decision.reasons.append(f"covered by {decision.test_id} (score {covered.flow:.2f}, {why})")
        return decision
    decision.reasons.append(
        "not covered: no test in the domain has the draft's case"
        + (f" (values {sorted(values)})" if values else "")
    )

    same_kind = kind == "hybrid" or best.kind == kind
    if best.flow >= reuse.variant_min and best.parametrized and same_kind:
        decision.kind, decision.target, decision.target_file = (
            "variant",
            best.chunk_id,
            best.file_path,
        )
        decision.reasons.append(f"new variant of {best.test} (flow {best.flow:.2f})")
        return decision
    decision.reasons.append(
        "no variant: "
        + (
            f"best flow {best.flow:.2f} < {reuse.variant_min}"
            if best.flow < reuse.variant_min
            else f"{best.test} has no single parametrize to add a case to"
            if not best.parametrized
            else f"{best.test} is a {best.kind} test, the draft is {kind}"
        )
    )

    classes: dict[tuple[str, str], list[float]] = {}
    for c in candidates:
        if c.class_name is not None and (kind == "hybrid" or c.kind == kind):
            classes.setdefault((c.file_path, c.class_name), []).append(c.flow)
    scores = {f"{path}::{name}": max(flows_) for (path, name), flows_ in classes.items()}
    decision.class_scores = dict(sorted(scores.items(), key=lambda kv: -kv[1]))
    if scores:
        target, score = max(scores.items(), key=lambda kv: (kv[1], kv[0]))
        path, name = target.split("::", 1)
        named = _named_after(name, all_draft_words, domain.name if domain else "", settings)
        common = {
            w
            for w in named
            if sum(w in f for f in flows.values()) > NAME_WORD_MAX_SHARE * len(flows)
        }
        named -= common  # "download" in every file test names nothing
        if score >= reuse.method_min or (named and score >= reuse.method_named_min):
            decision.kind, decision.target, decision.target_file = "method", name, path
            why = f"class match {score:.2f}" + (f", named after {sorted(named)}" if named else "")
            decision.reasons.append(f"new method in {name} ({why})")
            return decision
        decision.reasons.append(
            f"no method: best class match {score:.2f} < {reuse.method_min}"
            + ("" if named else f", and {name}'s name says nothing the draft does")
        )
    else:
        decision.reasons.append(f"no method: no {kind} test class in the domain")

    template = next(
        (c for c in candidates if c.class_name and (kind == "hybrid" or c.kind == kind)),
        candidates[0],
    )
    decision.target, decision.target_file = template.class_name, template.file_path
    decision.reasons.append(
        f"new module; scaffold and base from {template.class_name} ({template.kind}, "
        f"flow {template.flow:.2f})"
    )
    return decision


def _candidate(
    chunk: Chunk,
    flow: set[str],
    draft_words: set[str],
    all_draft_words: set[str],
    values: set[str],
    weights: dict[str, float],
    settings: Settings,
) -> Candidate:
    roots = {f"self.{r}" for r in settings.index.chain_roots}
    ui = any(".".join(["self", *chain[:1]]) in roots for chain in chunk.refs.self_chains)
    param_ids = [i for p in chunk.parametrize for i in (p.ids or [])]
    matched = _named_case(chunk, all_draft_words)
    score = _weighted_f1(flow, draft_words, weights)
    entry_values = {
        v.lower() for entry in chunk.data_entries.values() for v in _strings(entry) if len(v) < 80
    }
    return Candidate(
        chunk_id=chunk.id,
        test=chunk.symbol_name,
        class_name=chunk.class_name,
        file_path=chunk.file_path,
        kind="ui" if ui else "api",
        flow=round(score, 3),
        parametrized=len(chunk.parametrize) == 1 and not chunk.inherited_from,
        param_ids=param_ids,
        matched_param=matched,
        values_covered=bool(values) and values <= entry_values,
    )


def _covers(candidate: Candidate, values: set[str], reuse: ReuseSettings) -> bool:
    """The test already has the draft's case: strict, because "covered" generates nothing.

    The flow must match closely on words alone (``reuse.covered_min``, without the bonus for a
    named parametrize value: in the step-7 eval, values like ``allow`` or ``low`` matched tests
    that missed the ticket's point, e.g. a reset or a second tenant), and every concrete value
    the draft lists must be the named case or in the test's data. A false "covered" silently
    drops a ticket; a false "not covered" only gives the reviewer a test to discard.
    """
    if candidate.flow < reuse.covered_min:
        return False
    if not values:
        return candidate.matched_param is not None
    named = {candidate.matched_param.lower()} if candidate.matched_param else set()
    return candidate.values_covered or values <= named


def _named_case(chunk: Chunk, draft_words: set[str]) -> str | None:
    """The parametrize id the draft names, in context.

    The draft must use the id and a word of its argument name: "block exe files by file type"
    names ``exe`` of ``file_type``; "the print policy blocks" does not name ``block`` of
    ``rule_action``.
    """
    for p in chunk.parametrize:
        context = {norm(w) for a in p.argnames for w in split_identifier(a)}
        if not context & draft_words:
            continue
        for case in p.ids or []:
            if norm(case.lower()) in draft_words:
                return case
    return None


def _named_after(
    class_name: str, draft_words: set[str], domain: str, settings: Settings
) -> set[str]:
    """Words of the class name (without the test prefix and the domain's own name) that the
    draft uses: ``TestAgentBrowserLimit`` is named after a draft about the browser limit, while
    ``TestFilesDownloads`` says nothing about a print policy. Step-7 eval: classes named after
    the draft's subject scored just under ``method_min`` and became duplicate modules. The
    caller drops words most of the domain's tests use (they don't single out a class)."""
    prefix = settings.index.test_class_prefix
    parts = {norm(w.lower()) for w in split_identifier(class_name.removeprefix(prefix))}
    parts -= {norm(domain.lower()), *_STOP}
    return {w for w in parts if len(w) > 2} & draft_words


def _generic_words(settings: Settings) -> set[str]:
    words = {"self", "pytest", "mark", "parametrize", "check", "assert"}
    words |= set(settings.markers.required) | set(settings.index.chain_roots)
    words |= {a.rsplit(".", 1)[-1] for a in settings.data.access}
    words |= {h.rsplit(".", 1)[-1] for h in settings.data.expectation_sections.values()}
    words |= set(settings.validation.assertion_methods)
    return {norm(p) for w in words for p in split_identifier(w)} | {norm(w) for w in words}


def _flow_words(chunk: Chunk, generic: set[str], settings: Settings) -> set[str]:
    names = set(chunk.refs.names) | {step for chain in chunk.refs.self_chains for step in chain}
    names |= {chunk.symbol_name} | {a for p in chunk.parametrize for a in p.argnames}
    fixed = {settings.data.id_field, *settings.data.seed_sections, *settings.data.per_entry_keys}
    fixed |= set(settings.data.expectation_sections)
    names |= {k for entry in chunk.data_entries.values() for k in entry if k not in fixed}
    words = {norm(part) for name in names for part in split_identifier(name)}
    words |= {norm(w.lower()) for w in _WORD.findall(chunk.docstring or "")}
    return {w for w in words if w not in generic and w not in _STOP and len(w) > 2}


def _idf(flows: object) -> dict[str, float]:
    """Inverse document frequency of each word over the domain's tests."""
    documents = list(flows)  # type: ignore[call-overload]
    counts: dict[str, int] = {}
    for words in documents:
        for word in words:
            counts[word] = counts.get(word, 0) + 1
    total = len(documents)
    return {w: math.log((1 + total) / (1 + c)) + 1.0 for w, c in counts.items()}


def _weighted_f1(flow: set[str], draft: set[str], weights: dict[str, float]) -> float:
    if not flow or not draft:
        return 0.0
    overlap = sum(weights.get(w, 1.0) for w in flow & draft)
    recall = overlap / sum(weights.get(w, 1.0) for w in flow)  # the test's words the draft has
    precision = overlap / sum(weights.get(w, 1.0) for w in draft)  # the draft's words it has
    return 2 * recall * precision / (recall + precision) if overlap else 0.0


def _draft_words(draft: TestCaseDraft) -> set[str]:
    texts = [draft.intent, draft.expected_outcome, *draft.steps, *draft.preconditions]
    for variant in draft.variants:
        texts += [variant.name, variant.expected, *(f"{i.name} {i.value}" for i in variant.inputs)]
    words: set[str] = set()
    for text in texts:
        for word in _WORD.findall(text):
            words |= {norm(p) for p in split_identifier(word)} | {norm(word.lower())}
    return {w for w in words if w not in _STOP}


def _draft_values(draft: TestCaseDraft) -> set[str]:
    """Concrete values the draft names: variant inputs and quoted terms in its steps."""
    values = {i.value.lower() for v in draft.variants for i in v.inputs if i.value}
    for text in [*draft.steps, draft.expected_outcome]:
        values |= {m.group(1).strip().lower() for m in _QUOTED.finditer(text)}
    return {v for v in values if v}


def _strings(value: object) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [s for item in value for s in _strings(item)]
    if isinstance(value, dict):
        return [s for item in value.values() for s in _strings(item)]
    return []
