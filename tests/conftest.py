from __future__ import annotations

import os
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(autouse=True)
def _isolate_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Keep tests independent of the developer's shell env and working directory."""
    for key in list(os.environ):
        if key.startswith("T2T_"):
            monkeypatch.delenv(key)
    monkeypatch.chdir(tmp_path)
