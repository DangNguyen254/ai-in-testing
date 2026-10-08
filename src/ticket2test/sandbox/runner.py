"""Collect tests inside a container (Hard Constraint 3).

Generated code is untrusted, and ``pytest --collect-only`` imports it, so it never runs on the
host. The container gets no network, a read-only root file system, no capabilities, a process
and memory limit, the target repo mounted read-only at ``/repo``, and one writable staging
folder at ``/work`` (inside this repo's git-ignored ``.scratch/``). Inside, the repo is copied
to ``/work/repo``, generated files (if any) are placed at their repo paths, and pytest collects
either the generated module or the whole suite (``collect_suite``, used by ``check-suite``).
A missing runtime or image is a clear error, never a host run. Runs never pull images
(``--pull=never``), and unless ``sandbox.registry_auth`` is set, every runtime call gets an
empty credentials file, so the developer's registry logins (and credential helpers) are never
used.

The image is built from the packaged ``Containerfile`` with a configurable base image and
requirements file, so it can hold the target suite's test-time dependencies.
"""

from __future__ import annotations

import os
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
DEFAULT_REQUIREMENTS = Path(__file__).with_name("requirements.txt")
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


def build_args(exe: str, sandbox: SandboxSettings, context: Path) -> list[str]:
    return [
        exe,
        "build",
        "-t",
        sandbox.image,
        "--build-arg",
        f"BASE_IMAGE={sandbox.base_image}",
        "-f",
        str(context / "Containerfile"),
        str(context),
    ]


def build_image(settings: Settings, runner: Runner = subprocess.run) -> str:
    """Build the sandbox image: the packaged Containerfile, ``sandbox.base_image``, and the
    ``sandbox.requirements`` file (staged as the only build context). Returns the output."""
    sandbox = settings.sandbox
    exe = find_runtime(sandbox)
    requirements = sandbox.requirements or DEFAULT_REQUIREMENTS
    if not requirements.is_file():
        raise SandboxError(f"Requirements file not found: {requirements} (sandbox.requirements)")
    context = sandbox.work_dir / f"build-{uuid.uuid4().hex[:12]}"
    context.mkdir(parents=True)
    try:
        shutil.copyfile(CONTAINERFILE, context / "Containerfile")
        shutil.copyfile(requirements, context / "requirements.txt")
        proc = _call(runner, settings, build_args(exe, sandbox, context.resolve()))
    finally:
        shutil.rmtree(context, ignore_errors=True)
    if proc.returncode != 0:
        raise SandboxError(f"Image build failed:\n{(proc.stdout + proc.stderr)[-_OUTPUT_TAIL:]}")
    return proc.stdout + proc.stderr


def image_exists(settings: Settings, runner: Runner = subprocess.run) -> bool:
    exe = find_runtime(settings.sandbox)
    proc = _call(runner, settings, [exe, "image", "inspect", settings.sandbox.image])
    return proc.returncode == 0


def collect_generated(
    generated: GeneratedTest,
    repo_root: Path,
    settings: Settings,
    runner: Runner = subprocess.run,
) -> CollectReport:
    stage = _stage(generated, settings)
    run = _run(repo_root, stage, generated.file_name, settings, runner)
    expected = list(generated.test_ids)
    if run.timed_out:
        return CollectReport(
            ok=False,
            runtime=settings.sandbox.runtime,
            image=settings.sandbox.image,
            exit_code=None,
            timed_out=True,
            duration_seconds=run.seconds,
            expected=expected,
            missing=expected,
            output_tail=run.output_tail,
        )
    collected = parse_collected(run.stdout)
    missing = [t for t in expected if t not in collected]
    unexpected = [t for t in collected if t not in expected]
    return CollectReport(
        ok=run.exit_code == 0 and not missing and not unexpected,
        runtime=settings.sandbox.runtime,
        image=settings.sandbox.image,
        exit_code=run.exit_code,
        duration_seconds=run.seconds,
        expected=expected,
        collected=collected,
        missing=missing,
        unexpected=unexpected,
        output_tail=run.output_tail,
    )


class SuiteCollect(BaseModel):
    """``pytest --collect-only`` over a whole suite (hand-written tests, in the sandbox)."""

    model_config = ConfigDict(extra="forbid")

    exit_code: int | None
    timed_out: bool = False
    duration_seconds: float
    node_ids: list[str] = Field(default_factory=list)  # "path::Class::test[id]"
    output_tail: str = ""


def collect_suite(
    repo_root: Path, settings: Settings, runner: Runner = subprocess.run
) -> SuiteCollect:
    stage = settings.sandbox.work_dir / f"run-{uuid.uuid4().hex[:12]}"
    stage.mkdir(parents=True)
    run = _run(repo_root, stage, None, settings, runner)
    return SuiteCollect(
        exit_code=run.exit_code,
        timed_out=run.timed_out,
        duration_seconds=run.seconds,
        node_ids=[] if run.timed_out else parse_node_ids(run.stdout),
        output_tail=run.output_tail,
    )


class _Run(BaseModel):
    exit_code: int | None
    timed_out: bool
    seconds: float
    stdout: str
    output_tail: str


def _run(
    repo_root: Path,
    stage: Path,
    test_file: str | None,
    settings: Settings,
    runner: Runner,
) -> _Run:
    """One container run; the staging folder is removed afterwards."""
    sandbox = settings.sandbox
    try:
        exe = find_runtime(sandbox)
        if not image_exists(settings, runner):
            raise SandboxError(
                f"Sandbox image {sandbox.image!r} not found. Build it with "
                "`ticket2test sandbox --build`."
            )
        name = f"t2t-collect-{stage.name}"
        args = run_args(exe, sandbox, repo_root.resolve(), stage.resolve(), name, test_file)
        started = time.monotonic()
        try:
            proc = _call(runner, settings, args, timeout=sandbox.timeout_seconds)
        except subprocess.TimeoutExpired as exc:
            _call(runner, settings, [exe, "rm", "-f", name])
            return _Run(
                exit_code=None,
                timed_out=True,
                seconds=round(time.monotonic() - started, 1),
                stdout="",
                output_tail=_tail(_text(exc.stdout) + _text(exc.stderr)),
            )
        return _Run(
            exit_code=proc.returncode,
            timed_out=False,
            seconds=round(time.monotonic() - started, 1),
            stdout=proc.stdout,
            output_tail=_tail(proc.stdout + proc.stderr),
        )
    finally:
        shutil.rmtree(stage, ignore_errors=True)


def run_args(
    exe: str,
    sandbox: SandboxSettings,
    repo: Path,
    stage: Path,
    name: str,
    test_file: str | None,
) -> list[str]:
    """The container command. ``test_file`` None: collect the whole suite."""
    target = ""
    if test_file is not None:
        target = PurePosixPath(test_file).as_posix()
        if not re.fullmatch(r"[\w./-]+", target) or ".." in target.split("/"):
            raise SandboxError(f"unsafe test file path: {test_file!r}")
        target = f" '{target}'"
    script = (
        "set -e; cp -r /repo /work/repo; "
        "if [ -d /work/generated ]; then cp -r /work/generated/. /work/repo/; fi; cd /work/repo; "
        f"python -m pytest --collect-only -q -p no:cacheprovider{target}"
    )
    return [
        exe,
        "run",
        "--rm",
        "--pull=never",
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
    return [node.rsplit("::", 1)[1] for node in parse_node_ids(stdout)]


_NODE_LINE = re.compile(r"^[^\s<=][^:\s]*\.py::\S")


def parse_node_ids(stdout: str) -> list[str]:
    """Full node ids from ``pytest --collect-only -q`` output: the first block of lines that
    start with a ``path.py::`` node id. Parametrize ids may contain spaces; the block ends at
    the first blank line or section header (a warnings summary may repeat node ids)."""
    ids: list[str] = []
    for line in stdout.splitlines():
        if _NODE_LINE.match(line):
            ids.append(line.rstrip())
        elif ids and (not line.strip() or line.startswith("=")):
            break
    return ids


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


def _call(
    runner: Runner, settings: Settings, args: list[str], timeout: float | None = None
) -> subprocess.CompletedProcess[str]:
    kwargs: dict[str, Any] = {
        "capture_output": True,
        "text": True,
        "encoding": "utf-8",
        "errors": "replace",
        "check": False,
        "env": runtime_env(settings),
    }
    if timeout is not None:
        kwargs["timeout"] = timeout
    return runner(args, **kwargs)


def runtime_env(settings: Settings) -> dict[str, str]:
    """The environment for runtime calls: the current one, plus (unless registry_auth) an
    empty credentials file for Podman and an empty config folder for Docker, under the
    sandbox work dir. That keeps the developer's registry logins out of the sandbox."""
    env = dict(os.environ)
    if settings.sandbox.registry_auth:
        return env
    folder = (settings.sandbox.work_dir / "auth").resolve()
    (folder / "docker").mkdir(parents=True, exist_ok=True)
    for path in (folder / "auth.json", folder / "docker" / "config.json"):
        if not path.is_file():
            path.write_text("{}\n", encoding="utf-8")
    env["REGISTRY_AUTH_FILE"] = str(folder / "auth.json")
    env["DOCKER_CONFIG"] = str(folder / "docker")
    return env


def _text(value: Any) -> str:
    if value is None:
        return ""
    return value.decode("utf-8", "replace") if isinstance(value, bytes) else str(value)


def _tail(text: str) -> str:
    return text[-_OUTPUT_TAIL:]
