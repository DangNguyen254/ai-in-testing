"""Command-line entry point: one subcommand per pipeline stage."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Annotated

import typer

from ticket2test import __version__
from ticket2test.config import Settings, load_settings

app = typer.Typer(
    name="ticket2test",
    help="Turn a bug ticket into draft test cases and runnable test code for QE review.",
    no_args_is_help=True,
    add_completion=False,
)


@dataclass
class AppState:
    settings: Settings
    debug_log: bool


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"ticket2test {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    ctx: typer.Context,
    config: Annotated[
        Path | None,
        typer.Option(help="Path to config YAML (default: ./config.yaml or $T2T_CONFIG)."),
    ] = None,
    debug_log: Annotated[
        bool,
        typer.Option(
            "--debug-log",
            help="Write full prompts/responses to the git-ignored debug log dir. Off by default.",
        ),
    ] = False,
    version: Annotated[
        bool,
        typer.Option("--version", callback=_version_callback, is_eager=True, help="Show version."),
    ] = False,
) -> None:
    try:
        settings = load_settings(config)
    except FileNotFoundError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=2) from exc
    ctx.obj = AppState(settings=settings, debug_log=debug_log)


@app.command()
def normalize(
    ctx: typer.Context,
    ref: Annotated[
        str,
        typer.Argument(
            help="GitHub 'owner/repo#123' or issue URL; or a Jira key with --jira-export."
        ),
    ],
    jira_export: Annotated[
        Path | None,
        typer.Option(help="Read the Jira issue REF from this exported JSON file (no network)."),
    ] = None,
    out: Annotated[
        Path | None,
        typer.Option(help="Output JSON path (default: <output_dir>/tickets/<id>.json)."),
    ] = None,
    raw_out: Annotated[
        Path | None,
        typer.Option(help="Also save the raw source payload here (useful for fixtures)."),
    ] = None,
) -> None:
    """Fetch a ticket and normalize it into a Ticket."""
    # Imported here so `--help` stays fast and adapters load only when needed.
    from ticket2test.adapters.tickets.base import TicketSource, TicketSourceError
    from ticket2test.adapters.tickets.github import GitHubIssueSource, is_github_ref
    from ticket2test.adapters.tickets.jira import JiraExportSource
    from ticket2test.normalize import NormalizationError
    from ticket2test.normalize import normalize as normalize_ticket

    state: AppState = ctx.obj
    source: TicketSource
    if jira_export is not None:
        source = JiraExportSource(jira_export)
    elif is_github_ref(ref):
        source = GitHubIssueSource(state.settings.tickets.github)
    else:
        typer.echo(
            f"Error: {ref!r} is not a GitHub issue reference. "
            "For Jira, pass the issue key with --jira-export FILE.",
            err=True,
        )
        raise typer.Exit(code=2)

    try:
        raw = source.fetch(ref)
        ticket = normalize_ticket(raw, state.settings)
    except (TicketSourceError, NormalizationError) as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    if raw_out is not None:
        raw_out.parent.mkdir(parents=True, exist_ok=True)
        raw_out.write_text(raw.model_dump_json(indent=2), encoding="utf-8")

    target = out or state.settings.paths.output_dir / "tickets" / f"{_safe_name(ticket.id)}.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(ticket.model_dump_json(indent=2), encoding="utf-8")
    typer.echo(f"Wrote {target}")


def _safe_name(ticket_id: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "-_." else "_" for ch in ticket_id)


@app.command()
def draft(
    ctx: typer.Context,
    ticket_file: Annotated[Path, typer.Argument(help="Normalized ticket JSON (from `normalize`).")],
    out: Annotated[
        Path | None,
        typer.Option(help="Output directory (default: <output_dir>/drafts)."),
    ] = None,
) -> None:
    """Generate structured test-case drafts (JSON + Markdown) from a Ticket."""
    from pydantic import ValidationError

    from ticket2test.draft import generate_drafts, render_markdown
    from ticket2test.llm.base import LLMError
    from ticket2test.llm.factory import create_llm_client, model_name
    from ticket2test.models import Ticket
    from ticket2test.prompts import PromptError

    state: AppState = ctx.obj
    settings = state.settings
    try:
        ticket = Ticket.model_validate_json(ticket_file.read_text(encoding="utf-8"))
    except (OSError, ValidationError) as exc:
        typer.echo(f"Error: cannot read ticket {ticket_file}: {exc}", err=True)
        raise typer.Exit(code=2) from exc

    try:
        client = create_llm_client(settings, debug_log=state.debug_log)
        result = generate_drafts(
            ticket, client, settings, provider=settings.llm.provider, model=model_name(settings)
        )
    except PromptError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=2) from exc
    except LLMError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    target_dir = out or settings.paths.output_dir / "drafts"
    target_dir.mkdir(parents=True, exist_ok=True)
    stem = _safe_name(ticket.id)
    json_path = target_dir / f"{stem}.drafts.json"
    md_path = target_dir / f"{stem}.drafts.md"
    json_path.write_text(result.model_dump_json(indent=2), encoding="utf-8")
    md_path.write_text(render_markdown(result, ticket), encoding="utf-8")
    summary = (
        f"{len(result.drafts)} draft(s)"
        if result.status == "ok"
        else f"insufficient info: {', '.join(result.missing_info)}"
    )
    typer.echo(f"{ticket.id}: {summary}\nWrote {json_path}\nWrote {md_path}")


@app.command()
def index(
    ctx: typer.Context,
    repo_path: Annotated[Path, typer.Argument(help="Target repo to index (read-only).")],
    force: Annotated[
        bool, typer.Option("--force", help="Rebuild from scratch instead of reusing the cache.")
    ] = False,
) -> None:
    """Index a target repo: chunks, symbol catalog, BM25 search tokens."""
    from ticket2test.index.indexer import update_index

    state: AppState = ctx.obj
    if not repo_path.is_dir():
        typer.echo(f"Error: not a directory: {repo_path}", err=True)
        raise typer.Exit(code=2)
    _, stats, path = update_index(repo_path, state.settings, force=force)
    kinds = ", ".join(f"{n} {k}" for k, n in sorted(stats.chunks_by_kind.items()))
    typer.echo(
        f"Indexed {repo_path}: {stats.files} files ({stats.parsed} parsed, {stats.reused} reused, "
        f"{len(stats.skipped)} skipped) in {stats.seconds:.1f}s\n"
        f"Chunks: {kinds or 'none'}\n"
        f"Symbols: {stats.symbols}, page-object chains: {stats.chains}\n"
        f"Saved {path}"
    )
    for skipped in stats.skipped[:10]:
        typer.echo(f"  skipped: {skipped.reason}")
    if len(stats.skipped) > 10:
        typer.echo(f"  ... and {len(stats.skipped) - 10} more")


@app.command()
def search(
    ctx: typer.Context,
    query: Annotated[str, typer.Argument(help="Words or identifiers to search for.")],
    repo: Annotated[Path, typer.Option(help="Repo that was indexed with `index`.")] = Path("."),
    top_k: Annotated[int | None, typer.Option(help="Results (default: retrieval.top_k).")] = None,
    kind: Annotated[
        list[str] | None,
        typer.Option(help="Only these chunk kinds: test, function, class, page_object."),
    ] = None,
) -> None:
    """Search an indexed repo (BM25 over chunks)."""
    from ticket2test.index.indexer import index_dir, load_index

    state: AppState = ctx.obj
    allowed = {"test", "function", "class", "page_object"}
    unknown = set(kind or []) - allowed
    if unknown:
        typer.echo(f"Error: unknown kind(s): {', '.join(sorted(unknown))}", err=True)
        raise typer.Exit(code=2)
    data = load_index(index_dir(repo, state.settings), state.settings)
    if data is None:
        typer.echo(f"Error: no index for {repo}. Run `ticket2test index {repo}` first.", err=True)
        raise typer.Exit(code=1)
    hits = data.search_index().search(
        query,
        top_k=top_k or state.settings.retrieval.top_k,
        kinds=kind or None,  # type: ignore[arg-type]
    )
    if not hits:
        typer.echo("No results.")
        return
    for rank, hit in enumerate(hits, start=1):
        c = hit.chunk
        where = f"{c.file_path}:{c.start_line}"
        typer.echo(f"{rank:>2}. {hit.score:6.2f}  {c.kind:<11} {c.qualname}  ({where})")


@app.command()
def retrieve(
    ctx: typer.Context,
    ticket_file: Annotated[Path, typer.Argument(help="Normalized ticket JSON (from `normalize`).")],
    repo: Annotated[Path, typer.Option(help="Target repo (indexed on demand, read-only).")],
    draft: Annotated[
        Path | None,
        typer.Option(help="Drafts JSON (from `draft`); the primary draft refines the query."),
    ] = None,
    no_llm: Annotated[
        bool, typer.Option("--no-llm", help="Deterministic only: no query rewrite or follow-ups.")
    ] = False,
    out: Annotated[
        Path | None,
        typer.Option(help="Output JSON (default: <output_dir>/retrieval/<id>.retrieval.json)."),
    ] = None,
) -> None:
    """Retrieve relevant code, similar tests, and JSON-entry templates for a ticket."""
    from pydantic import ValidationError

    from ticket2test.index.indexer import update_index
    from ticket2test.llm.base import LLMError
    from ticket2test.llm.factory import create_llm_client
    from ticket2test.models import DraftResult, Ticket
    from ticket2test.prompts import PromptError
    from ticket2test.retrieve.pipeline import retrieve as run_retrieval

    state: AppState = ctx.obj
    settings = state.settings
    try:
        ticket = Ticket.model_validate_json(ticket_file.read_text(encoding="utf-8"))
        primary = None
        if draft is not None:
            drafts = DraftResult.model_validate_json(draft.read_text(encoding="utf-8"))
            primary = next((d for d in drafts.drafts if d.kind == "primary"), None)
    except (OSError, ValidationError) as exc:
        typer.echo(f"Error: cannot read input: {exc}", err=True)
        raise typer.Exit(code=2) from exc
    if not repo.is_dir():
        typer.echo(f"Error: not a directory: {repo}", err=True)
        raise typer.Exit(code=2)

    index, _, _ = update_index(repo, settings)
    try:
        client = None if no_llm else create_llm_client(settings, debug_log=state.debug_log)
        result = run_retrieval(ticket, index, settings, client, primary)
    except PromptError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=2) from exc
    except LLMError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    target = (
        out or settings.paths.output_dir / "retrieval" / f"{_safe_name(ticket.id)}.retrieval.json"
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(result.model_dump_json(indent=2), encoding="utf-8")
    typer.echo(
        f"{ticket.id}: {len(result.hits)} hits, {len(result.templates)} templates, "
        f"{result.followup_rounds} follow-up round(s), {result.llm_calls} LLM call(s)"
    )
    for rank, hit in enumerate(result.hits, start=1):
        why = "; ".join(r.detail for r in hit.reasons[:2])
        typer.echo(f"{rank:>2}. [{hit.kind}] {hit.qualname} ({hit.file_path}) <- {why}")
    typer.echo(f"Wrote {target}")


@app.command()
def generate(
    ctx: typer.Context,
    draft_file: Annotated[Path, typer.Argument(help="Drafts JSON (from `draft`).")],
    retrieval_file: Annotated[
        Path, typer.Option("--retrieval", help="Retrieval JSON (from `retrieve`).")
    ],
    draft_id: Annotated[
        str | None, typer.Option(help="Which draft to generate (default: the primary one).")
    ] = None,
    conventions: Annotated[
        Path | None,
        typer.Option(help="Conventions doc (Markdown); overrides generate.conventions_doc."),
    ] = None,
    out: Annotated[
        Path | None, typer.Option(help="Output directory (default: <output_dir>/generated).")
    ] = None,
) -> None:
    """Generate a test (code file + JSON data entries) from a draft and retrieval results."""
    from pydantic import ValidationError

    from ticket2test.generate.context import ContextBudgetError
    from ticket2test.index.indexer import update_index
    from ticket2test.llm.base import LLMError
    from ticket2test.llm.factory import create_llm_client, model_name
    from ticket2test.models import DraftResult
    from ticket2test.models.retrieval import RetrievalResult
    from ticket2test.prompts import PromptError
    from ticket2test.style import format_entries
    from ticket2test.validate.repair import generate_with_repair

    state: AppState = ctx.obj
    settings = state.settings
    try:
        drafts = DraftResult.model_validate_json(draft_file.read_text(encoding="utf-8"))
        retrieval = RetrievalResult.model_validate_json(retrieval_file.read_text(encoding="utf-8"))
        conventions_path = conventions or settings.generate.conventions_doc
        conventions_text = (
            conventions_path.read_text(encoding="utf-8") if conventions_path else None
        )
    except (OSError, ValidationError) as exc:
        typer.echo(f"Error: cannot read input: {exc}", err=True)
        raise typer.Exit(code=2) from exc
    if drafts.status != "ok":
        typer.echo(f"Error: {drafts.ticket_id} has no drafts ({drafts.status}).", err=True)
        raise typer.Exit(code=2)
    chosen = next(
        (
            d
            for d in drafts.drafts
            if d.id == draft_id or (draft_id is None and d.kind == "primary")
        ),
        None,
    )
    if chosen is None:
        typer.echo(f"Error: draft {draft_id or '(primary)'} not found.", err=True)
        raise typer.Exit(code=2)

    repo_root = Path(retrieval.repo_root)
    target_dir = (out or settings.paths.output_dir / "generated").resolve()
    if target_dir == repo_root.resolve() or repo_root.resolve() in target_dir.parents:
        typer.echo("Error: the output directory must be outside the target repo.", err=True)
        raise typer.Exit(code=2)

    index, _, _ = update_index(repo_root, settings)
    try:
        client = create_llm_client(settings, debug_log=state.debug_log)
        repaired = generate_with_repair(
            chosen,
            retrieval,
            index,
            settings,
            client,
            provider=settings.llm.provider,
            model=model_name(settings),
            conventions=conventions_text,
        )
        generated, report = repaired.generated, repaired.report
    except (PromptError, ContextBudgetError) as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=2) from exc
    except LLMError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    folder = target_dir / _safe_name(chosen.id)
    code_path = folder / generated.file_name
    data_path = folder / generated.data_file_name
    code_path.parent.mkdir(parents=True, exist_ok=True)
    data_text = format_entries(
        generated.data_entries, settings.data, settings.style.json_files, generated.data_format
    )
    code_path.write_text(generated.code, encoding="utf-8", newline="\n")
    data_path.write_text(data_text, encoding="utf-8", newline="\n")
    (folder / "generated.json").write_text(generated.model_dump_json(indent=2), encoding="utf-8")
    typer.echo(
        f"{chosen.id}: {len(generated.test_ids)} test id(s), template "
        f"{generated.template_entry_ref.entry_key if generated.template_entry_ref else '-'}, "
        f"{generated.attempts} LLM call(s), ~{generated.context_tokens} context tokens"
    )
    typer.echo(f"Wrote {code_path}\nWrote {data_path}\nWrote {folder / 'generated.json'}")
    typer.echo(
        f"Validation: {'ok' if report.ok else 'FAILED'} after {report.repairs} repair round(s), "
        f"{len(report.errors)} error(s), {len(report.warnings)} warning(s)"
    )
    for finding in report.findings:
        typer.echo(f"  {finding.severity}: {finding.render()}")
    if generated.review_checklist:
        typer.echo("Review checklist (needs a real run):")
        for item in generated.review_checklist:
            typer.echo(f"  - {item}")


@app.command()
def validate(
    ctx: typer.Context,
    generated_dir: Annotated[
        Path, typer.Argument(help="Output of `generate` (folders with generated.json).")
    ],
    repo: Annotated[Path, typer.Option(help="The target repo the tests were generated for.")],
    collect: Annotated[
        bool, typer.Option("--collect", help="Also run `pytest --collect-only` in the sandbox.")
    ] = False,
    run: Annotated[
        bool, typer.Option("--run", help="Execute the tests in the sandbox (not available yet).")
    ] = False,
) -> None:
    """Validate generated tests; with --collect, collect them in a container sandbox."""
    from ticket2test.generate.generator import first_party
    from ticket2test.index.indexer import update_index
    from ticket2test.models.generated import GeneratedTest
    from ticket2test.sandbox.runner import SandboxError, collect_generated
    from ticket2test.validate.validator import validate_generated

    state: AppState = ctx.obj
    settings = state.settings
    if run:
        typer.echo("Error: --run is not available yet (optional, after Phase 7).", err=True)
        raise typer.Exit(code=2)
    files = sorted(generated_dir.rglob("generated.json"))
    if not files:
        typer.echo(f"Error: no generated.json under {generated_dir}", err=True)
        raise typer.Exit(code=2)
    if not repo.is_dir():
        typer.echo(f"Error: repo not found: {repo}", err=True)
        raise typer.Exit(code=2)
    index, _, _ = update_index(repo, settings)
    roots = first_party(index, settings)
    failed = 0
    for path in files:
        generated = GeneratedTest.model_validate_json(path.read_text(encoding="utf-8"))
        data_path = path.parent / generated.data_file_name
        data_text = data_path.read_text(encoding="utf-8") if data_path.is_file() else None
        report = validate_generated(generated, index.catalog, settings, roots, data_text=data_text)
        update: dict[str, object] = {"validation_report": report.model_dump(mode="json")}
        typer.echo(
            f"{generated.ticket_id} {generated.file_name}: {'ok' if report.ok else 'FAILED'} "
            f"({len(report.errors)} error(s), {len(report.warnings)} warning(s))"
        )
        for finding in report.findings:
            typer.echo(f"  {finding.severity}: {finding.render()}")
        collect_ok = True
        if collect:
            try:
                collected = collect_generated(generated, repo, settings)
            except SandboxError as exc:
                typer.echo(f"Error: {exc}", err=True)
                raise typer.Exit(code=2) from exc
            update["collect_report"] = collected.model_dump(mode="json")
            collect_ok = collected.ok
            details = [
                f"missing {collected.missing}" if collected.missing else "",
                f"unexpected {collected.unexpected}" if collected.unexpected else "",
                "timed out" if collected.timed_out else "",
            ]
            typer.echo(
                f"  collect ({collected.runtime}, {collected.duration_seconds}s): "
                + ", ".join(["ok" if collected.ok else "FAILED", *filter(None, details)])
            )
            if not collected.ok and collected.output_tail:
                typer.echo(collected.output_tail[-800:])
        failed += int(not report.ok or not collect_ok)
        path.write_text(
            generated.model_copy(update=update).model_dump_json(indent=2), encoding="utf-8"
        )
    typer.echo(f"{len(files) - failed}/{len(files)} passed")
    if failed:
        raise typer.Exit(code=1)


@app.command()
def sandbox(
    ctx: typer.Context,
    build: Annotated[
        bool, typer.Option("--build", help="Build the sandbox image (pulls a public base image).")
    ] = False,
) -> None:
    """Show (or build) the container sandbox used to collect generated tests."""
    from ticket2test.sandbox.runner import SandboxError, build_image, find_runtime, image_exists

    state: AppState = ctx.obj
    settings = state.settings
    try:
        exe = find_runtime(settings.sandbox)
        if build:
            build_image(settings)
        ready = image_exists(settings)
    except SandboxError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=2) from exc
    typer.echo(f"Runtime: {exe}")
    typer.echo(f"Image {settings.sandbox.image}: {'ready' if ready else 'missing (use --build)'}")
    if not ready:
        raise typer.Exit(code=1)


@app.command(name="eval")
def eval_(
    ctx: typer.Context,
    pair_set: Annotated[
        Path, typer.Option("--set", help="A pair-set JSON file, or a folder of them (eval_data/).")
    ],
    stage: Annotated[str, typer.Option(help="retrieval, generation, or all.")] = "retrieval",
    runs: Annotated[
        int, typer.Option(help="Retrieval runs per set (variance of the LLM steps).", min=1, max=10)
    ] = 1,
    k: Annotated[int | None, typer.Option(help="Cut-off for recall@k (default: top_k).")] = None,
    no_llm: Annotated[bool, typer.Option("--no-llm", help="Deterministic retrieval only.")] = False,
    judge: Annotated[
        bool, typer.Option("--judge", help="LLM judge: draft vs. ticket (unvalidated; +1 call).")
    ] = False,
    no_collect: Annotated[
        bool, typer.Option("--no-collect", help="Skip `pytest --collect-only` in the sandbox.")
    ] = False,
    no_leave_one_out: Annotated[
        bool,
        typer.Option("--no-leave-one-out", help="Keep each ticket's linked test in the index."),
    ] = False,
    fresh_drafts: Annotated[
        bool, typer.Option("--fresh-drafts", help="Don't reuse cached drafts.")
    ] = False,
    out: Annotated[
        Path | None, typer.Option(help="Report directory (default: <output_dir>/reports).")
    ] = None,
) -> None:
    """Run the eval harness: retrieval (recall@k, MRR), generation (validators, sandbox)."""
    from datetime import UTC, datetime

    from ticket2test.eval.report import render_markdown
    from ticket2test.eval.run import load_pair_sets, run_eval
    from ticket2test.llm.base import LLMError
    from ticket2test.llm.factory import create_llm_client

    state: AppState = ctx.obj
    settings = state.settings
    folder = out or settings.paths.output_dir / "reports"
    stem = f"eval-{datetime.now(UTC):%Y%m%dT%H%M%S}"
    try:
        sets = load_pair_sets(pair_set)
        client = None if no_llm else create_llm_client(settings, debug_log=state.debug_log)
        report = run_eval(
            sets,
            Path.cwd(),
            settings,
            client,
            stage=stage,
            runs=runs,
            k=k,
            leave_one_out=not no_leave_one_out,
            collect=not no_collect,
            judge=judge,
            reuse_drafts=not fresh_drafts,
            keep_dir=folder / stem / "generated",
        )
    except (OSError, ValueError, LLMError) as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    folder.mkdir(parents=True, exist_ok=True)
    markdown = render_markdown(report)
    (folder / f"{stem}.json").write_text(report.model_dump_json(indent=2), encoding="utf-8")
    (folder / f"{stem}.md").write_text(markdown, encoding="utf-8")
    typer.echo(markdown)
    typer.echo(f"Wrote {folder / stem}.json and .md")


@app.command()
def mine(
    ctx: typer.Context,
    repo: Annotated[Path, typer.Argument(help="A git repo (read only) to mine.")],
    out: Annotated[Path, typer.Option(help="Pair-set JSON to write (e.g. eval_data/x.json).")],
    name: Annotated[str, typer.Option(help="Pair-set name.")] = "mined",
    repo_path: Annotated[
        str, typer.Option(help="Indexed checkout for retrieval, relative to the project root.")
    ] = "",
    jira_export: Annotated[
        str | None, typer.Option(help="Jira export with the tickets, relative to the project root.")
    ] = None,
) -> None:
    """Mine ticket <-> test pairs from commits that remove a ticket-id skip."""
    import json

    from ticket2test.adapters.repo.git_history import GitHistoryError, GitHistoryReader
    from ticket2test.eval.mining import mine_skip_removals

    state: AppState = ctx.obj
    try:
        mined = mine_skip_removals(GitHistoryReader(repo), state.settings)
    except GitHistoryError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    pairs = [
        {
            "id": f"mined-{m.ticket}",
            "ticket": m.ticket,
            "tests": [m.test],
            "source": f"mined: {m.commit[:10]} {m.kind} ({m.subject})",
        }
        for m in mined
    ]
    pair_set = {
        "name": name,
        "description": f"Ticket <-> test pairs mined from {repo.as_posix()}: commits that remove "
        "a skip citing the ticket id. Ground truth: the re-enabled test.",
        "repo_path": repo_path or repo.as_posix(),
        "ticket_source": "jira_export",
        "jira_export": jira_export,
        "ground_truth": "tests",
        "pairs": pairs,
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(pair_set, indent=2) + "\n", encoding="utf-8", newline="\n")
    for m in mined:
        typer.echo(f"{m.ticket}: {m.test} ({m.kind}, {m.commit[:10]})")
    typer.echo(f"{len(mined)} pair(s) -> {out}")
