from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from ticket2test import __version__
from ticket2test.cli import app

SUBCOMMANDS = ["normalize", "draft", "index", "search", "retrieve", "generate", "validate", "eval"]

runner = CliRunner()


def test_help_lists_all_subcommands() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    for name in SUBCOMMANDS:
        assert name in result.output
    assert "--debug-log" in result.output


def test_version() -> None:
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert __version__ in result.output


@pytest.mark.parametrize("name", SUBCOMMANDS)
def test_placeholder_subcommands_fail_clearly(name: str) -> None:
    result = runner.invoke(app, [name])
    assert result.exit_code == 1
    assert "Not implemented yet" in result.output


def test_missing_config_file_is_reported(tmp_path: Path) -> None:
    result = runner.invoke(app, ["--config", str(tmp_path / "missing.yaml"), "draft"])
    assert result.exit_code == 2
    assert "Config file not found" in result.output
