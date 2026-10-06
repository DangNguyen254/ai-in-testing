"""Collect a generated test inside a container (Hard Constraint 3).

Generated code is untrusted, and ``pytest --collect-only`` imports it, so it never runs on the
host. The container gets no network, a read-only root file system, no capabilities, a process
and memory limit, the target repo mounted read-only at ``/repo``, and one writable staging
folder at ``/work`` (inside this repo's git-ignored ``.scratch/``). Inside, the repo is copied
to ``/work/repo``, the generated files are placed at their repo paths, and pytest collects
only the generated module. A missing runtime or image is a clear error, never a host run.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import time
import uuid
from collections.abc import Callable
from pathlib import Path, PurePosixPath
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from ticket2test.config import SandboxSettings, Settings
from ticket2test.models.generated import GeneratedTest
from ticket2test.style import format_entries

Runner = Callable[..., subprocess.CompletedProcess[str]]

CONTAINERFILE = Path(__file__).with_name("Containerfile")
_OUTPUT_TAIL = 4000


class SandboxError(RuntimeError):
    """The sandbox can't run (no runtime, no image). Never falls back to the host."""


class CollectReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ok: bool
    runtime: str
    image: str
    exit_code: int | None  # None when timed out
    timed_out: bool = False
    duration_seconds: float
    expected: list[str]  # pytest names the generator computed
    collected: list[str] = Field(default_factory=list)  # pytest names pytest reported
    missing: list[str] = Field(default_factory=list)
    unexpected: list[str] = Field(default_factory=list)
    output_tail: str = ""  # last part of stdout + stderr


def find_runtime(sandbox: SandboxSettings) -> str:
    exe = shutil.which(sandbox.runtime)
    if exe is None:
        raise SandboxError(
            f"Container runtime {sandbox.runtime!r} not found. Install Docker or Podman, or set "
            "sandbox.runtime. Generated tests are never collected on the host."
        )
    return exe


def build_image(settings: Settings, runner: Runner = subprocess.run) -> str:
    """Build the sandbox image from the packaged Containerfile. Returns the build output."""
    exe = find_runtime(settings.sandbox)
    args = [exe, "build", "-t", settings.sandbox.image, "-f", str(CONTAINERFILE)]
    proc = runner(
        [*args, str(CONTAINERFILE.parent)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if proc.returncode != 0:
        raise SandboxError(f"Image build failed:\n{(proc.stdout + proc.stderr)[-_OUTPUT_TAIL:]}")
    return proc.stdout + proc.stderr


def image_exists(settings: Settings, runner: Runner = subprocess.run) -> bool:
    exe = find_runtime(settings.sandbox)
    proc = runner(
        [exe, "image", "inspect", settings.sandbox.image],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    return proc.returncode == 0


def collect_generated(
    generated: GeneratedTest,
    repo_root: Path,
    settings: Settings,
    runner: Runner = subprocess.run,
) -> CollectReport:
    sandbox = settings.sandbox
    exe = find_runtime(sandbox)
    if not image_exists(settings, runner):
        raise SandboxError(
            f"Sandbox image {sandbox.image!r} not found. Build it with "
            "`ticket2test sandbox --build`."
        )
    stage = _stage(generated, settings)
    name = f"t2t-collect-{stage.name}"
    args = run_args(exe, sandbox, repo_root.resolve(), stage.resolve(), name, generated.file_name)
    started = time.monotonic()
    try:
        proc = runner(
            args,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=sandbox.timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        runner(
            [exe, "rm", "-f", name],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        return CollectReport(
            ok=False,
            runtime=sandbox.runtime,
            image=sandbox.image,
            exit_code=None,
            timed_out=True,
            duration_seconds=round(time.monotonic() - started, 1),
            expected=list(generated.test_ids),
            missing=list(generated.test_ids),
            output_tail=_tail(_text(exc.stdout) + _text(exc.stderr)),
        )
    finally:
        shutil.rmtree(stage, ignore_errors=True)
    collected = parse_collected(proc.stdout)
    missing = [t for t in generated.test_ids if t not in collected]
    unexpected = [t for t in collected if t not in generated.test_ids]
    return CollectReport(
        ok=proc.returncode == 0 and not missing and not unexpected,
        runtime=sandbox.runtime,
        image=sandbox.image,
        exit_code=proc.returncode,
        duration_seconds=round(time.monotonic() - started, 1),
        expected=list(generated.test_ids),
        collected=collected,
        missing=missing,
        unexpected=unexpected,
        output_tail=_tail(proc.stdout + proc.stderr),
    )


def run_args(
    exe: str, sandbox: SandboxSettings, repo: Path, stage: Path, name: str, test_file: str
) -> list[str]:
    target = PurePosixPath(test_file).as_posix()
    if not re.fullmatch(r"[\w./-]+", target) or ".." in target.split("/"):
        raise SandboxError(f"unsafe test file path: {test_file!r}")
    script = (
        "set -e; cp -r /repo /work/repo; cp -r /work/generated/. /work/repo/; cd /work/repo; "
        f"python -m pytest --collect-only -q -p no:cacheprovider '{target}'"
    )
    return [
        exe,
        "run",
        "--rm",
        "--name",
        name,
        "--network=none",
        "--read-only",
        "--tmpfs",
        "/tmp",
        "--cap-drop=ALL",
        "--security-opt",
        "no-new-privileges",
        "--pids-limit",
        str(sandbox.pids_limit),
        "--memory",
        sandbox.memory,
        "-v",
        f"{repo}:/repo:ro",
        "-v",
        f"{stage}:/work:rw",
        "-w",
        "/work",
        sandbox.image,
        "sh",
        "-c",
        script,
    ]


def parse_collected(stdout: str) -> list[str]:
    """``tests/x.py::TestX::test_y[a]`` lines -> ["test_y[a]"] (pytest -q --collect-only)."""
    return [line.strip().rsplit("::", 1)[1] for line in stdout.splitlines() if "::" in line]


def _stage(generated: GeneratedTest, settings: Settings) -> Path:
    """Write the generated code and data into a fresh staging folder (repo paths kept)."""
    stage = settings.sandbox.work_dir / f"run-{uuid.uuid4().hex[:12]}"
    out = stage / "generated"
    _safe_write(out, generated.file_name, generated.code)
    if generated.data_entries:
        data = format_entries(
            generated.data_entries,
            settings.data,
            settings.style.json_files,
            generated.data_format,
        )
        _safe_write(out, generated.data_file_name, data)
    return stage


def _safe_write(root: Path, relative: str, text: str) -> None:
    path = (root / relative).resolve()
    if root.resolve() not in path.parents:
        raise SandboxError(f"refusing to write outside the staging folder: {relative}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def _text(value: Any) -> str:
    if value is None:
        return ""
    return value.decode("utf-8", "replace") if isinstance(value, bytes) else str(value)


def _tail(text: str) -> str:
    return text[-_OUTPUT_TAIL:]
