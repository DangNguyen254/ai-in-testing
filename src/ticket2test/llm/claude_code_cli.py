"""LLMClient backed by the Claude Code CLI in print mode (``claude -p``).

The CLI is used as a plain LLM, not an agent:
- ``--tools ""``: no built-in tools (only the internal StructuredOutput tool remains when a
  JSON schema is given), ``--strict-mcp-config``: no MCP servers,
  ``--disable-slash-commands``: no skills, ``--setting-sources ""``: no settings files,
  ``--system-prompt``: replaces the agent system prompt, ``--no-session-persistence``.
- It runs in a dedicated working directory (default ``.scratch/claude-cli`` in the repo).
- The prompt goes through stdin (no command-line length limits, nothing in the process list).

``--bare`` would be even more minimal, but it forces API-key auth and disables the
subscription login, so it is deliberately not used.

Caveats: the CLI has no temperature control, and billing for ``-p`` usage depends on how the
CLI is authenticated. If ``ANTHROPIC_API_KEY`` is set, the CLI uses API billing.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
from collections.abc import Callable, Iterable, Sequence
from pathlib import Path
from typing import Any

from ticket2test.llm.base import LLMClient, LLMError, LLMRequest, LLMResponse, Message

log = logging.getLogger(__name__)

Runner = Callable[..., "subprocess.CompletedProcess[str]"]

DEFAULT_WORKDIR = Path(".scratch") / "claude-cli"
_MAX_ERROR_CHARS = 500


def find_executable(configured: str) -> str | None:
    """Resolve the CLI from config: an existing file path, or a command name on PATH."""
    if Path(configured).is_file():
        return configured
    return shutil.which(configured)


class ClaudeCodeCLIClient(LLMClient):
    def __init__(
        self,
        model: str,
        executable: str = "claude",
        timeout_seconds: float = 300.0,
        workdir: Path | None = None,
        runner: Runner | None = None,
    ) -> None:
        self._model = model
        self._executable = executable
        self._timeout = timeout_seconds
        self._workdir = workdir
        self._run: Runner = runner or subprocess.run

    def complete(self, request: LLMRequest) -> LLMResponse:
        exe = find_executable(self._executable)
        if exe is None:
            raise LLMError(
                f"Claude Code CLI not found ({self._executable!r}). Put `claude` on PATH, or set "
                "llm.claude_code_cli.executable (or T2T_LLM__CLAUDE_CODE_CLI__EXECUTABLE) to the "
                "full path of the claude binary."
            )
        if os.environ.get("ANTHROPIC_API_KEY"):
            log.warning("ANTHROPIC_API_KEY is set: the Claude CLI will use API billing.")

        system, prompt = render_messages(request.messages)
        model = request.model or self._model
        args = build_args(exe, model, system, request.json_schema)
        workdir = self._ensure_workdir()
        try:
            proc = self._run(
                args,
                input=prompt,
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=self._timeout,
                cwd=workdir,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise LLMError(f"Claude CLI timed out after {self._timeout:.0f}s") from exc
        except OSError as exc:
            raise LLMError(f"Could not start the Claude CLI: {exc}") from exc

        return parse_output(proc.returncode, proc.stdout, proc.stderr, model)

    def _ensure_workdir(self) -> Path:
        workdir = self._workdir or DEFAULT_WORKDIR
        workdir.mkdir(parents=True, exist_ok=True)
        return workdir


def build_args(exe: str, model: str, system: str, json_schema: dict[str, Any] | None) -> list[str]:
    args = [
        exe,
        "-p",
        "--output-format",
        "json",
        "--model",
        model,
        "--tools",
        "",
        "--strict-mcp-config",
        "--setting-sources",
        "",
        "--disable-slash-commands",
        "--no-session-persistence",
        "--system-prompt",
        system or "You are a precise assistant. Follow the user's instructions exactly.",
    ]
    if json_schema is not None:
        args += ["--json-schema", json.dumps(json_schema, separators=(",", ":"))]
    return args


def render_messages(messages: Sequence[Message]) -> tuple[str, str]:
    """Split system messages out and flatten the rest into one prompt (print mode is one turn)."""
    system = "\n\n".join(m.content for m in messages if m.role == "system")
    turns = [m for m in messages if m.role != "system"]
    if len(turns) == 1 and turns[0].role == "user":
        return system, turns[0].content
    parts = [f"<{m.role}_turn>\n{m.content}\n</{m.role}_turn>" for m in turns]
    header = "The conversation so far is below. Reply to the last user turn.\n\n"
    return system, header + "\n\n".join(parts)


def parse_output(returncode: int, stdout: str, stderr: str, model: str) -> LLMResponse:
    try:
        data = json.loads(stdout)
    except json.JSONDecodeError:
        detail = (stderr or stdout).strip()[:_MAX_ERROR_CHARS]
        raise LLMError(f"Claude CLI failed (exit {returncode}): {detail}") from None
    if not isinstance(data, dict):
        raise LLMError("Claude CLI returned an unexpected JSON shape")

    if data.get("is_error") or data.get("subtype") != "success":
        detail = str(data.get("result") or data.get("subtype") or "unknown error")
        raise LLMError(f"Claude CLI error: {detail[:_MAX_ERROR_CHARS]}")

    structured = data.get("structured_output")
    text = json.dumps(structured) if structured is not None else str(data.get("result") or "")
    raw_usage = data.get("usage")
    usage: dict[str, Any] = raw_usage if isinstance(raw_usage, dict) else {}
    cost = data.get("total_cost_usd")
    return LLMResponse(
        text=text,
        model=model,
        input_tokens=_sum_ints(
            usage.get(k)
            for k in ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")
        ),
        output_tokens=_int_or_none(usage.get("output_tokens")),
        cost_usd=float(cost) if isinstance(cost, int | float) else None,
    )


def _int_or_none(value: Any) -> int | None:
    return value if isinstance(value, int) else None


def _sum_ints(values: Iterable[Any]) -> int | None:
    ints = [v for v in values if isinstance(v, int)]
    return sum(ints) if ints else None
