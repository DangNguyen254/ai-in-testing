"""Provider clients against fakes. No subprocess, no network."""

from __future__ import annotations

import json
import logging
import subprocess
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from ticket2test.config import Settings
from ticket2test.llm import FakeLLMClient, LLMError, LLMRequest, Message
from ticket2test.llm.claude_api import ClaudeAPIClient
from ticket2test.llm.claude_code_cli import ClaudeCodeCLIClient, render_messages
from ticket2test.llm.debug import DebugLoggingClient
from ticket2test.llm.factory import create_llm_client, model_name
from ticket2test.llm.gemini import GeminiClient

SCHEMA = {"type": "object", "properties": {"ok": {"type": "boolean"}}, "required": ["ok"]}


def _request(**kwargs: Any) -> LLMRequest:
    return LLMRequest(
        messages=(
            Message(role="system", content="SYSTEM TEXT"),
            Message(role="user", content="USER TEXT"),
        ),
        **kwargs,
    )


# --- Claude Code CLI -------------------------------------------------------------------------


class FakeRunner:
    def __init__(self, stdout: str = "", returncode: int = 0, raises: Exception | None = None):
        self.stdout, self.returncode, self.raises = stdout, returncode, raises
        self.calls: list[dict[str, Any]] = []

    def __call__(self, args: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        self.calls.append({"args": args, **kwargs})
        if self.raises:
            raise self.raises
        return subprocess.CompletedProcess(args, self.returncode, self.stdout, "")


def _cli(runner: FakeRunner, tmp_path: Path) -> ClaudeCodeCLIClient:
    exe = tmp_path / "claude.exe"
    exe.write_text("", encoding="utf-8")
    return ClaudeCodeCLIClient(
        model="claude-sonnet-5-5", executable=str(exe), workdir=tmp_path / "wd", runner=runner
    )


def _cli_result(**overrides: Any) -> str:
    data = {
        "type": "result",
        "subtype": "success",
        "is_error": False,
        "result": '{"ok":true}',
        "structured_output": {"ok": True},
        "total_cost_usd": 0.0066,
        "usage": {"input_tokens": 2, "cache_creation_input_tokens": 1284, "output_tokens": 52},
    }
    data.update(overrides)
    return json.dumps(data)


def test_cli_runs_as_plain_llm_with_tools_disabled(tmp_path: Path) -> None:
    runner = FakeRunner(_cli_result())
    response = _cli(runner, tmp_path).complete(_request(json_schema=SCHEMA))

    call = runner.calls[0]
    args = call["args"]
    for flag, value in (
        ("--output-format", "json"),
        ("--model", "claude-sonnet-5-5"),
        ("--tools", ""),
        ("--setting-sources", ""),
        ("--system-prompt", "SYSTEM TEXT"),
    ):
        assert args[args.index(flag) + 1] == value
    for flag in (
        "-p",
        "--strict-mcp-config",
        "--disable-slash-commands",
        "--no-session-persistence",
    ):
        assert flag in args
    assert "--bare" not in args  # would force API-key auth
    assert json.loads(args[args.index("--json-schema") + 1]) == SCHEMA
    assert "USER TEXT" not in " ".join(args)  # prompt goes via stdin only
    assert call["input"] == "USER TEXT"
    assert Path(call["cwd"]) == tmp_path / "wd"  # isolated workdir, not the project
    assert call["timeout"] == 300.0

    assert json.loads(response.text) == {"ok": True}
    assert response.input_tokens == 1286
    assert response.output_tokens == 52
    assert response.cost_usd == pytest.approx(0.0066)


def test_cli_without_schema_returns_result_text(tmp_path: Path) -> None:
    runner = FakeRunner(_cli_result(structured_output=None, result="plain"))
    assert _cli(runner, tmp_path).complete(_request()).text == "plain"
    assert "--json-schema" not in runner.calls[0]["args"]


@pytest.mark.parametrize(
    ("stdout", "message"),
    [
        (_cli_result(is_error=True, subtype="error_during_execution", result="boom"), "boom"),
        ("Invalid API key · Please run /login", "failed"),
        ("[1, 2]", "unexpected"),
    ],
)
def test_cli_errors(tmp_path: Path, stdout: str, message: str) -> None:
    with pytest.raises(LLMError, match=message):
        _cli(FakeRunner(stdout, returncode=1), tmp_path).complete(_request())


def test_cli_timeout(tmp_path: Path) -> None:
    runner = FakeRunner(raises=subprocess.TimeoutExpired("claude", 300))
    with pytest.raises(LLMError, match="timed out"):
        _cli(runner, tmp_path).complete(_request())


def test_cli_not_found() -> None:
    client = ClaudeCodeCLIClient(model="m", executable="definitely-not-claude", runner=FakeRunner())
    with pytest.raises(LLMError, match="not found"):
        client.complete(_request())


def test_cli_default_workdir_is_inside_the_repo_scratch(tmp_path: Path) -> None:
    # cwd is tmp_path (conftest), standing in for the repo root.
    runner = FakeRunner(_cli_result())
    exe = tmp_path / "claude.exe"
    exe.write_text("", encoding="utf-8")
    ClaudeCodeCLIClient(model="m", executable=str(exe), runner=runner).complete(_request())
    assert Path(runner.calls[0]["cwd"]) == Path(".scratch") / "claude-cli"
    assert (tmp_path / ".scratch" / "claude-cli").is_dir()


def test_cli_warns_when_api_key_would_switch_billing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "placeholder")
    with caplog.at_level(logging.WARNING):
        _cli(FakeRunner(_cli_result()), tmp_path).complete(_request())
    assert "API billing" in caplog.text
    assert "placeholder" not in caplog.text


def test_render_messages_flattens_retry_conversation() -> None:
    system, prompt = render_messages(
        [
            Message(role="system", content="S"),
            Message(role="user", content="first"),
            Message(role="assistant", content="bad"),
            Message(role="user", content="fix it"),
        ]
    )
    assert system == "S"
    assert prompt.index("<user_turn>\nfirst") < prompt.index("<assistant_turn>\nbad")
    assert prompt.rstrip().endswith("<user_turn>\nfix it\n</user_turn>")


# --- Claude API ------------------------------------------------------------------------------


class FakeAnthropic:
    def __init__(self, stop_reason: str = "end_turn", text: str = '{"ok": true}') -> None:
        self.calls: list[dict[str, Any]] = []
        response = SimpleNamespace(
            stop_reason=stop_reason,
            model="claude-sonnet-5-5",
            content=[SimpleNamespace(type="text", text=text)],
            usage=SimpleNamespace(input_tokens=10, output_tokens=5),
        )

        def create(**kwargs: Any) -> Any:
            self.calls.append(kwargs)
            return response

        self.messages = SimpleNamespace(create=create)
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=create))


def test_claude_api_request_shape() -> None:
    fake = FakeAnthropic()
    client = ClaudeAPIClient(model="claude-sonnet-5-5", effort="medium", client=fake)
    response = client.complete(_request(json_schema=SCHEMA, temperature=0.0, seed=1))

    call = fake.calls[0]
    assert call["model"] == "claude-sonnet-5-5"
    assert call["system"] == "SYSTEM TEXT"
    assert call["messages"] == [{"role": "user", "content": "USER TEXT"}]
    assert call["output_config"] == {
        "format": {"type": "json_schema", "schema": SCHEMA},
        "effort": "medium",
    }
    assert call["fallbacks"] == "default"
    assert call["betas"] == ["server-side-fallback-2026-07-01"]
    assert "temperature" not in call and "seed" not in call  # rejected by current models
    assert response.text == '{"ok": true}'
    assert response.input_tokens == 10


def test_claude_api_without_fallbacks_uses_plain_endpoint() -> None:
    fake = FakeAnthropic()
    ClaudeAPIClient(model="m", fallbacks=False, client=fake).complete(_request())
    assert "fallbacks" not in fake.calls[0] and "betas" not in fake.calls[0]


@pytest.mark.parametrize(
    ("stop", "message"), [("refusal", "declined"), ("max_tokens", "max_tokens")]
)
def test_claude_api_bad_stop_reasons(stop: str, message: str) -> None:
    with pytest.raises(LLMError, match=message):
        ClaudeAPIClient(model="m", client=FakeAnthropic(stop_reason=stop)).complete(_request())


# --- Gemini ----------------------------------------------------------------------------------


class FakeGemini:
    def __init__(self, text: str | None = '{"ok": true}') -> None:
        self.calls: list[dict[str, Any]] = []
        response = SimpleNamespace(
            text=text,
            usage_metadata=SimpleNamespace(prompt_token_count=7, candidates_token_count=3),
        )

        def generate_content(**kwargs: Any) -> Any:
            self.calls.append(kwargs)
            return response

        self.models = SimpleNamespace(generate_content=generate_content)


def test_gemini_request_shape() -> None:
    fake = FakeGemini()
    client = GeminiClient(model="gemini-test-model", client=fake)
    response = client.complete(_request(json_schema=SCHEMA, temperature=0.0, seed=42))

    call = fake.calls[0]
    assert call["model"] == "gemini-test-model"
    assert call["contents"] == [{"role": "user", "parts": [{"text": "USER TEXT"}]}]
    config = call["config"]
    assert config.system_instruction == "SYSTEM TEXT"
    assert config.temperature == 0.0
    assert config.seed == 42
    assert config.response_mime_type == "application/json"
    assert config.response_json_schema == SCHEMA
    assert response.text == '{"ok": true}'
    assert (response.input_tokens, response.output_tokens) == (7, 3)


def test_gemini_requires_model_and_key(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(LLMError, match=r"llm\.gemini\.model"):
        GeminiClient(model="", client=FakeGemini())
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    with pytest.raises(LLMError, match="GEMINI_API_KEY"):
        GeminiClient(model="gemini-test-model")


def test_gemini_empty_response() -> None:
    with pytest.raises(LLMError, match="no text"):
        GeminiClient(model="g", client=FakeGemini(text=None)).complete(_request())


# --- Factory and debug logging ---------------------------------------------------------------


def test_factory_default_is_claude_code_cli() -> None:
    settings = Settings()
    assert isinstance(create_llm_client(settings), ClaudeCodeCLIClient)
    assert model_name(settings) == "claude-sonnet-5-5"


def test_factory_gemini_needs_model() -> None:
    settings = Settings.model_validate({"llm": {"provider": "gemini"}})
    with pytest.raises(LLMError, match="model is not set"):
        create_llm_client(settings)


def test_factory_claude_api(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-not-real")
    settings = Settings.model_validate({"llm": {"provider": "claude"}})
    assert isinstance(create_llm_client(settings), ClaudeAPIClient)


def test_debug_log_only_when_enabled(tmp_path: Path) -> None:
    settings = Settings.model_validate({"paths": {"debug_log_dir": str(tmp_path / "dbg")}})
    assert not isinstance(create_llm_client(settings), DebugLoggingClient)
    assert isinstance(create_llm_client(settings, debug_log=True), DebugLoggingClient)

    client = DebugLoggingClient(FakeLLMClient(["reply"]), tmp_path / "dbg")
    client.complete(_request())
    [log_file] = (tmp_path / "dbg").glob("llm-*.jsonl")
    record = json.loads(log_file.read_text(encoding="utf-8"))
    assert record["request"]["messages"][1]["content"] == "USER TEXT"
    assert record["response"]["text"] == "reply"
