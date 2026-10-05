"""Command-line entry point. Subcommands are placeholders until their phase lands."""

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


def _not_implemented(phase: int) -> None:
    typer.echo(f"Not implemented yet (planned for Phase {phase}).", err=True)
    raise typer.Exit(code=1)


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
def retrieve() -> None:
    """Retrieve relevant code and similar tests for a draft (Phase 5)."""
    _not_implemented(5)


@app.command()
def generate() -> None:
    """Generate test code + JSON data from a draft and retrieval results (Phase 6)."""
    _not_implemented(6)


@app.command()
def validate() -> None:
    """Validate generated tests; collect them in a sandbox (Phase 7)."""
    _not_implemented(7)


@app.command(name="eval")
def eval_() -> None:
    """Run the eval harness over ticket/test pairs (Phase 8)."""
    _not_implemented(8)
