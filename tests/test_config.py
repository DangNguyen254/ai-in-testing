from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from tests.conftest import REPO_ROOT
from ticket2test.config import Settings, load_settings


def _write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "config.yaml"
    path.write_text(text, encoding="utf-8")
    return path


def test_defaults_match_documented_limits() -> None:
    s = Settings()
    assert s.llm.max_retries_on_bad_json == 2
    assert s.retrieval.top_k == 10
    assert s.retrieval.max_followup_rounds == 2
    assert s.context.max_tokens == 12000
    assert s.repair.max_attempts == 3
    assert s.sandbox.timeout_seconds == 120
    assert s.llm.temperature == 0.0


def test_repo_config_yaml_loads_and_matches_defaults() -> None:
    assert load_settings(REPO_ROOT / "config.yaml") == Settings()


def test_loads_values_from_yaml(tmp_path: Path) -> None:
    path = _write(tmp_path, "retrieval:\n  top_k: 7\nrepair:\n  max_attempts: 1\n")
    s = load_settings(path)
    assert s.retrieval.top_k == 7
    assert s.repair.max_attempts == 1
    assert s.retrieval.max_followup_rounds == 2  # untouched keys keep defaults


def test_env_overrides_yaml(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = _write(tmp_path, "retrieval:\n  top_k: 7\n  max_followup_rounds: 1\n")
    monkeypatch.setenv("T2T_RETRIEVAL__TOP_K", "3")
    s = load_settings(path)
    assert s.retrieval.top_k == 3  # env wins
    assert s.retrieval.max_followup_rounds == 1  # yaml value kept for other keys


def test_env_overrides_without_yaml(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("T2T_SANDBOX__TIMEOUT_SECONDS", "30")
    assert load_settings().sandbox.timeout_seconds == 30


def test_default_config_yaml_in_cwd_is_used(tmp_path: Path) -> None:
    _write(tmp_path, "context:\n  max_tokens: 500\n")  # cwd is tmp_path (conftest)
    assert load_settings().context.max_tokens == 500


def test_config_path_from_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    other = tmp_path / "other.yaml"
    other.write_text("context:\n  max_tokens: 99\n", encoding="utf-8")
    monkeypatch.setenv("T2T_CONFIG", str(other))
    assert load_settings().context.max_tokens == 99


def test_missing_default_config_falls_back_to_defaults() -> None:
    assert load_settings() == Settings()


def test_missing_explicit_config_is_an_error(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        load_settings(tmp_path / "nope.yaml")


@pytest.mark.parametrize(
    "yaml_text",
    [
        "repair:\n  max_attempts: -1\n",
        "retrieval:\n  top_k: 0\n",
        "sandbox:\n  timeout_seconds: 0\n",
        "sandbox:\n  runtime: host\n",  # never allow host execution
        "retrieval:\n  topk: 5\n",  # typo'd key
        "unknown_section: {}\n",
    ],
)
def test_invalid_yaml_is_rejected(tmp_path: Path, yaml_text: str) -> None:
    with pytest.raises(ValidationError):
        load_settings(_write(tmp_path, yaml_text))


def test_invalid_env_value_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("T2T_REPAIR__MAX_ATTEMPTS", "-5")
    with pytest.raises(ValidationError):
        load_settings()
