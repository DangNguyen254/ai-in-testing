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
def normalize() -> None:
    """Fetch a ticket and normalize it into a Ticket (Phase 1)."""
    _not_implemented(1)


@app.command()
def draft() -> None:
    """Generate structured test-case drafts from a Ticket (Phase 2)."""
    _not_implemented(2)


@app.command()
def index() -> None:
    """Index a target repo: chunks, symbol catalog, BM25 (Phase 3)."""
    _not_implemented(3)


@app.command()
def search() -> None:
    """Search the index (Phase 3)."""
    _not_implemented(3)


@app.command()
def retrieve() -> None:
    """Retrieve relevant code and similar tests for a draft (Phase 4)."""
    _not_implemented(4)


@app.command()
def generate() -> None:
    """Generate test code from a draft and retrieval results (Phase 5)."""
    _not_implemented(5)


@app.command()
def validate() -> None:
    """Validate generated tests and optionally run them in a sandbox (Phase 6)."""
    _not_implemented(6)


@app.command(name="eval")
def eval_() -> None:
    """Run the eval harness over issue/fix-PR pairs (Phase 7)."""
    _not_implemented(7)
