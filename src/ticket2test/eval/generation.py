"""Generation eval: ticket -> draft -> retrieval -> generate + repair -> validate -> collect.

For pair sets whose ground truth is the ticket's linked tests (the stand-in). Measured per
ticket: whether drafting worked, the validator result on the first attempt and after repair,
invented names on the first attempt (``names`` / ``imports`` errors), repair rounds, whether the
module collects in the sandbox, LLM calls, and time.

Leave-one-out (default): the ticket's own linked tests are removed from the index before
retrieval and generation, so the generator can't copy the answer.

Drafts can be reused from a cache (``<cache_dir>/eval/drafts``, keyed by ticket content, draft
prompt version, and model) to save LLM calls on repeated runs; each result says whether its
draft came from the cache.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import shutil
import time
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from ticket2test.config import Settings
from ticket2test.draft import generate_drafts
from ticket2test.eval.judge import JudgeVerdict, judge_draft
from ticket2test.eval.pairs import EvalCache, EvalPair, PairSet
from ticket2test.eval.retrieval import manifest_test_to_chunk_id
from ticket2test.generate.generator import first_party
from ticket2test.generate.pipeline import generate_reusing
from ticket2test.index.datafile import layout_of
from ticket2test.index.indexer import IndexData, update_index
from ticket2test.index.tokens import split_identifier
from ticket2test.llm.base import LLMClient, LLMError
from ticket2test.llm.factory import model_name
from ticket2test.llm.meter import Usage, usage_of
from ticket2test.models.chunk import Chunk
from ticket2test.models.draft import DraftResult
from ticket2test.models.gaps import GapVerdict
from ticket2test.models.ticket import Ticket
from ticket2test.normalize import normalize
from ticket2test.retrieve.pipeline import retrieve
from ticket2test.sandbox.runner import SandboxError, collect_generated
from ticket2test.style import FormatError, format_entries, format_python
from ticket2test.validate.claims import norm
from ticket2test.validate.suite import read_suite_data

_INVENTED = ("[names]", "[imports]")


class GenerationPairResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pair_id: str
    ticket: str
    status: str  # "generated", "covered", "out_of_scope", "insufficient_info", "failed"
    error: str = ""
    reuse_kind: str | None = None  # covered / variant / method / module (after fallbacks)
    decided: str | None = None  # the decision before fallbacks
    reuse_target: str | None = None
    reuse_notes: list[str] = Field(default_factory=list)  # fallbacks taken
    expected: str = "test"  # what a correct run produces (see EvalPair.expect)
    gaps_found: list[str] = Field(default_factory=list)  # reported gaps matching the expected
    expectation_met: bool | None = None  # gap, insufficient-info and out-of-scope pairs only
    guide: str = ""  # the area guide in the context ("" when none)
    missing: list[str] = Field(default_factory=list)  # "<status> <owner>.<name>" per candidate
    proposals: list[str] = Field(default_factory=list)  # "<ok|rejected> <Owner>.<member>"
    fixed_in_code: str = ""  # fixes made in code instead of an LLM retry (from notes)
    draft_cached: bool = False
    test_kind: str | None = None
    file_name: str | None = None
    test_ids: list[str] = Field(default_factory=list)
    template: str | None = None
    leave_one_out_ok: bool | None = None  # the linked test stayed out of the context
    first_errors: list[str] = Field(default_factory=list)  # validator errors, first attempt
    invented_names: int = 0  # names / imports errors on the first attempt
    final_ok: bool = False
    final_errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    repairs: int = 0
    collect_ok: bool | None = None  # None: not run
    collect_note: str = ""
    llm_calls: int = 0
    usage: Usage | None = None  # metered clients only
    seconds: float = 0.0
    judge: JudgeVerdict | None = None


class GenerationReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    set_name: str
    created_at: datetime
    leave_one_out: bool
    collect: bool
    judge: bool
    models: dict[str, str] = Field(default_factory=dict)
    pairs: list[GenerationPairResult] = Field(default_factory=list)
    llm_calls: int = 0
    usage: Usage | None = None
    elapsed_seconds: float = 0.0

    def _rate(self, values: list[bool]) -> float | None:
        return round(sum(values) / len(values), 4) if values else None

    @property
    def generated(self) -> list[GenerationPairResult]:
        return [p for p in self.pairs if p.status == "generated"]

    def metrics(self) -> dict[str, Any]:
        gen = self.generated
        collected = [p.collect_ok for p in gen if p.collect_ok is not None]
        return {
            "pairs": len(self.pairs),
            "generated": len(gen),
            "covered": sum(p.status == "covered" for p in self.pairs),
            "out_of_scope": sum(p.status == "out_of_scope" for p in self.pairs),
            "reuse_kinds": {
                k: sum(p.reuse_kind == k for p in self.pairs)
                for k in ("covered", "variant", "method", "module")
            },
            "fallbacks": sum(bool(p.reuse_notes) for p in self.pairs),
            "fixed_in_code": sum(bool(p.fixed_in_code) for p in gen),
            "insufficient_info": sum(p.status == "insufficient_info" for p in self.pairs),
            "failed": sum(p.status == "failed" for p in self.pairs),
            "first_attempt_pass_rate": self._rate([not p.first_errors for p in gen]),
            "final_pass_rate": self._rate([p.final_ok for p in gen]),
            "invented_name_rate": self._rate([p.invented_names > 0 for p in gen]),
            "invented_names_total": sum(p.invented_names for p in gen),
            "collect_pass_rate": self._rate(collected),
            "collect_runs": len(collected),
            "mean_repairs": round(sum(p.repairs for p in gen) / len(gen), 2) if gen else None,
            "warnings_per_test": round(sum(len(p.warnings) for p in gen) / len(gen), 2)
            if gen
            else None,
            "leave_one_out_violations": sum(p.leave_one_out_ok is False for p in gen),
            "gap_pairs": sum(p.expected == "gap" for p in self.pairs),
            "gaps_found": sum(p.expected == "gap" and bool(p.expectation_met) for p in self.pairs),
            "proposals": sum(len(p.proposals) for p in self.pairs),
            "proposals_ok": sum(x.startswith("ok ") for p in self.pairs for x in p.proposals),
            "proposals_used": sum(
                x.endswith("(used by the test)") for p in self.pairs for x in p.proposals
            ),
            "vague_pairs": sum(p.expected == "insufficient_info" for p in self.pairs),
            "vague_recognized": sum(
                p.expected == "insufficient_info" and bool(p.expectation_met) for p in self.pairs
            ),
        }


def index_without(index: IndexData, chunk_ids: set[str]) -> IndexData:
    """A copy of the index without these chunks (for leave-one-out)."""
    return index.model_copy(
        update={
            "chunks": [c for c in index.chunks if c.id not in chunk_ids],
            "tokens": {k: v for k, v in index.tokens.items() if k not in chunk_ids},
        }
    )


def leave_one_out_repo(
    repo: Path, index: IndexData, chunk_ids: set[str], settings: Settings, dest: Path
) -> Path:
    """A copy of the repo without these tests: their code and their data entries are cut, so
    the index, patches (which read files) and the sandbox collect all see the same suite.

    The copy goes to ``dest`` (inside the git-ignored cache); the target repo is only read.
    A class left without methods gets ``pass``.
    """
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(repo, dest, ignore=shutil.ignore_patterns(".git", "__pycache__"))
    chunks = [c for c in index.chunks if c.id in chunk_ids and not c.inherited_from]
    by_file: dict[str, list[Chunk]] = {}
    for chunk in chunks:
        by_file.setdefault(chunk.file_path, []).append(chunk)
    id_field = settings.data.id_field
    for file_path, cut in by_file.items():
        path = dest / file_path
        lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
        for chunk in sorted(cut, key=lambda c: -c.start_line):
            start, end = chunk.start_line - 1, chunk.end_line
            while end < len(lines) and not lines[end].strip():  # the blank lines after it
                end += 1
            del lines[start:end]
        text = _fill_empty_classes("".join(lines), settings)
        with contextlib.suppress(FormatError):  # the cut leaves blank lines: restyle the file
            text = format_python(text, settings.style.python, first_party(index, settings))
        path.write_text(text, encoding="utf-8", newline="\n")
        removed = {i for c in cut for i in c.test_ids}
        for chunk in cut:  # a test with its own data file: the file goes with it
            own = layout_of(chunk.file_path, chunk.symbol_name, chunk.data_file, settings.index)
            if own == "function" and chunk.data_file:
                (dest / chunk.data_file).unlink(missing_ok=True)
        entries, layout, data_text = read_suite_data(dest, file_path, settings)
        if data_text is not None:
            kept = [e for e in entries if str(e.get(id_field)) not in removed]
            data_path = dest / PurePosixPath(file_path).with_suffix(settings.index.data_file_suffix)
            data_path.write_text(
                format_entries(kept, settings.data, settings.style.json_files, layout),
                encoding="utf-8",
                newline="\n",
            )
    return dest


def _fill_empty_classes(text: str, settings: Settings) -> str:
    """``pass`` in a class whose last method was cut (so the module still parses)."""
    import ast

    try:
        ast.parse(text)
        return text
    except SyntaxError:
        pass
    lines = text.splitlines(keepends=True)
    out: list[str] = []
    indent = " " * settings.style.python.indent_width
    for n, line in enumerate(lines):
        out.append(line)
        nxt = next((ln for ln in lines[n + 1 :] if ln.strip()), "")
        if (
            line.lstrip().startswith("class ")
            and line.rstrip().endswith(":")
            and (not nxt or not nxt.startswith((" ", "\t")))
        ):
            out.append(f"{indent}pass\n")
    return "".join(out)


def evaluate_generation(
    pair_set: PairSet,
    project_root: Path,
    settings: Settings,
    client: LLMClient,
    cache: EvalCache | None = None,
    leave_one_out: bool = True,
    collect: bool = True,
    judge: bool = False,
    reuse_drafts: bool = True,
    keep_dir: Path | None = None,
) -> GenerationReport:
    """Run the generation pipeline for each pair. ``keep_dir``: write each generated pair."""
    if pair_set.ground_truth != "tests":
        raise ValueError(f"{pair_set.name}: generation needs a pair set with linked tests")
    repo = project_root / pair_set.repo_path
    index, _, _ = update_index(repo, settings)
    cache = cache or EvalCache(settings)
    conventions = (
        (project_root / pair_set.conventions_doc).read_text(encoding="utf-8")
        if pair_set.conventions_doc
        else None
    )
    report = GenerationReport(
        set_name=pair_set.name,
        created_at=datetime.now(UTC),
        leave_one_out=leave_one_out,
        collect=collect,
        judge=judge,
        models={
            step: model_name(settings, step) for step in ("draft", "query_rewrite", "generate")
        },
    )
    started = time.monotonic()
    before = usage_of(client)
    for pair in pair_set.pairs:
        pair_before = usage_of(client)
        report.pairs.append(
            _one(
                pair, pair_set, project_root, repo, index, settings, client, cache,
                conventions, leave_one_out, collect, judge, reuse_drafts, keep_dir,
            )
        )  # fmt: skip
        pair_after = usage_of(client)
        if pair_before is not None and pair_after is not None:
            report.pairs[-1].usage = pair_after.minus(pair_before)
    report.llm_calls = sum(p.llm_calls for p in report.pairs)
    after = usage_of(client)
    if before is not None and after is not None:
        report.usage = after.minus(before)
    report.elapsed_seconds = round(time.monotonic() - started, 1)
    return report


def _one(
    pair: EvalPair,
    pair_set: PairSet,
    project_root: Path,
    repo: Path,
    index: IndexData,
    settings: Settings,
    client: LLMClient,
    cache: EvalCache,
    conventions: str | None,
    leave_one_out: bool,
    collect: bool,
    judge: bool,
    reuse_drafts: bool,
    keep_dir: Path | None,
) -> GenerationPairResult:
    started = time.monotonic()
    result = GenerationPairResult(
        pair_id=pair.id, ticket=pair.ticket, status="failed", expected=pair.expect
    )
    linked = {manifest_test_to_chunk_id(t) for t in pair.tests}
    used_repo, used_index = repo, index
    if leave_one_out:  # a real copy without the linked tests, so files and index agree
        loo_settings = settings.model_copy(
            update={
                "paths": settings.paths.model_copy(
                    update={"cache_dir": settings.paths.cache_dir / "eval" / "loo-index"}
                )
            }
        )
        used_repo = leave_one_out_repo(
            repo, index, linked, settings, settings.paths.cache_dir / "eval" / "loo" / pair.id
        )
        used_index, _, _ = update_index(used_repo, loo_settings)
    try:
        ticket = normalize(cache.raw_ticket(pair_set, pair, project_root), settings)
        drafts, cached, calls = _drafts(ticket, client, settings, cache, reuse_drafts)
        result.draft_cached, result.llm_calls = cached, calls
        if judge:
            verdict, judge_calls = judge_draft(ticket, drafts, client, settings)
            result.judge, result.llm_calls = verdict, result.llm_calls + judge_calls
        if drafts.status != "ok":
            result.status = "insufficient_info"
            return _finish(result, started)
        primary = next(d for d in drafts.drafts if d.kind == "primary")
        result.test_kind = primary.test_kind
        retrieval = retrieve(ticket, used_index, settings, client, primary)
        result.llm_calls += retrieval.llm_calls
        outcome = generate_reusing(
            primary,
            retrieval,
            used_index,
            settings,
            client,
            provider=settings.llm.provider,
            model=model_name(settings, "generate"),
            repo_root=used_repo,
            conventions=conventions,
        )
    except LLMError as exc:
        result.error = str(exc)[:500]
        return _finish(result, started)
    except Exception as exc:  # one ticket's bug must not lose the whole run
        result.error = f"unexpected {type(exc).__name__}: {exc}"[:500]
        return _finish(result, started)

    result.reuse_kind, result.decided = outcome.kind, outcome.decision.kind
    result.reuse_target, result.reuse_notes = outcome.decision.target, list(outcome.notes)
    result.guide = outcome.guide
    result.gaps_found = _matching_gaps(pair, outcome.missing, used_index)
    result.missing = [
        f"{v.status} {v.piece.owner + '.' if v.piece.owner else ''}{v.piece.name}"
        for v in outcome.missing
    ]
    used = {id(x) for x in outcome.uses_proposals}
    result.proposals = [
        f"{'ok' if x.ok else 'rejected'} {x.owner_class.rsplit('.', 1)[-1]}.{x.member}"
        + (" (used by the test)" if id(x) in used else "")
        for x in outcome.proposals
    ]
    if outcome.kind == "out_of_scope":  # a legacy area: nothing generated
        result.status = "out_of_scope"
        return _finish(result, started)
    if outcome.generated is None or outcome.report is None:  # covered: nothing generated
        result.status = "covered"
        result.test_ids = [outcome.decision.test_id or ""]
        return _finish(result, started)
    generated, final = outcome.generated, outcome.report
    result.status = "generated"
    result.llm_calls += generated.attempts  # generation + repairs, or the variant plan
    fixed = generated.notes.partition("Fixed in code:")[2].strip()
    result.fixed_in_code = fixed
    result.file_name = generated.file_name
    result.test_ids = generated.new_test_ids or generated.test_ids
    ref = generated.template_entry_ref
    result.template = ref.entry_key if ref else None
    if leave_one_out:  # off: the linked test is meant to be used (e.g. to add a case to it)
        result.leave_one_out_ok = not (
            linked & set(generated.retrieved_chunk_ids) or (ref and ref.chunk_id in linked)
        )
    result.first_errors = final.history[0] if final.history else [f.render() for f in final.errors]
    result.invented_names = sum(e.startswith(_INVENTED) for e in result.first_errors)
    result.final_ok = final.ok
    result.final_errors = [f.render() for f in final.errors]
    result.warnings = [f.render() for f in final.warnings]
    result.repairs = final.repairs
    if collect:
        try:
            collected = collect_generated(generated, used_repo, settings)
        except SandboxError as exc:
            result.collect_note = f"not run: {exc}"
        else:
            result.collect_ok = collected.ok
            if not collected.ok:
                result.collect_note = (
                    "timed out" if collected.timed_out else collected.output_tail[-400:]
                )
            generated = generated.model_copy(
                update={"collect_report": collected.model_dump(mode="json")}
            )
    if keep_dir is not None:
        _keep(keep_dir / pair.id, generated, settings)
        if outcome.proposals:  # agent 2's patches, for review
            (keep_dir / pair.id / "proposals.json").write_text(
                json.dumps([p.model_dump(mode="json") for p in outcome.proposals], indent=2),
                encoding="utf-8",
            )
    return _finish(result, started)


def _drafts(
    ticket: Ticket, client: LLMClient, settings: Settings, cache: EvalCache, reuse: bool
) -> tuple[DraftResult, bool, int]:
    model = model_name(settings, "draft")
    key = hashlib.sha256(
        f"{ticket.model_dump_json()}|{settings.draft.prompt_version}|{model}".encode()
    ).hexdigest()[:24]
    path = cache.root / "drafts" / f"{key}.json"
    if reuse and path.is_file():
        return DraftResult.model_validate_json(path.read_text(encoding="utf-8")), True, 0
    no_skeleton = settings.model_copy(  # the eval measures drafts and generation only
        update={"draft": settings.draft.model_copy(update={"skeleton": "never"})}
    )
    drafts = generate_drafts(
        ticket, client, no_skeleton, provider=settings.llm.provider, model=model
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(drafts.model_dump_json(indent=2), encoding="utf-8")
    return drafts, False, drafts.attempts


def _keep(folder: Path, generated: Any, settings: Settings) -> None:
    (folder / Path(generated.file_name).parent).mkdir(parents=True, exist_ok=True)
    (folder / generated.file_name).write_text(generated.code, encoding="utf-8", newline="\n")
    data = format_entries(
        generated.data_entries, settings.data, settings.style.json_files, generated.data_format
    )
    (folder / generated.data_file_name).write_text(data, encoding="utf-8", newline="\n")
    (folder / "generated.json").write_text(generated.model_dump_json(indent=2), encoding="utf-8")


def _finish(result: GenerationPairResult, started: float) -> GenerationPairResult:
    result.seconds = round(time.monotonic() - started, 1)
    if result.expected == "insufficient_info":
        result.expectation_met = result.status == "insufficient_info"
    elif result.expected == "gap":
        result.expectation_met = bool(result.gaps_found)
    elif result.expected == "out_of_scope":
        result.expectation_met = result.status == "out_of_scope"
    return result


def _matching_gaps(pair: EvalPair, missing: list[GapVerdict], index: IndexData) -> list[str]:
    """Reported gaps (missing or close match) on the expected owner whose name has the expected
    words. The owner matches when it is the expected class or related to it by inheritance."""
    catalog = index.catalog
    found: list[str] = []
    for expected in pair.gaps:
        resolution = (
            catalog.resolve_chain_from_roots(expected.owner)
            if expected.owner.split(".")[0] in catalog.chain_roots
            else None
        )
        if resolution is not None:
            want = resolution.types[-1] if resolution.ok and resolution.types else None
        else:
            entry = catalog.class_named(expected.owner)
            want = entry.qualname if entry else None
        related = {want} | {e.qualname for e in catalog.mro(want)} if want else set()
        words = {norm(w) for w in expected.words}
        for verdict in missing:
            if verdict.status not in ("missing", "close_match"):
                continue
            owner = verdict.owner_class
            owner_line = {owner} | {e.qualname for e in catalog.mro(owner)} if owner else set()
            name_words = {norm(w) for w in split_identifier(verdict.piece.name)}
            if related & owner_line and words <= name_words:
                found.append(f"{verdict.status} {verdict.piece.owner}.{verdict.piece.name}")
    return found
