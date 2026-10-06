"""Sandbox runner (Phase 7). Unit tests use a fake runtime; ``-m sandbox`` runs a real one.

The real tests need Podman or Docker with the sandbox image built
(``ticket2test sandbox --build``) and ``T2T_SANDBOX__RUNTIME`` set if the runtime isn't Docker.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

from ticket2test.config import Settings
from ticket2test.models.generated import GeneratedTest
from ticket2test.sandbox.runner import (
    SandboxError,
    collect_generated,
    image_exists,
    parse_collected,
    run_args,
)

from .test_validate import GOOD_CODE, GOOD_ENTRY

STANDIN = Path(__file__).resolve().parents[1] / "standin"
TEST_FILE = "tests/rules/test_rules_list_filter.py"
TEST_ID = "test_rules_list_filter_next_page"


def _generated(code: str = GOOD_CODE, test_ids: list[str] | None = None) -> GeneratedTest:
    return GeneratedTest(
        code=code,
        file_name=TEST_FILE,
        data_file_name=TEST_FILE.replace(".py", ".json"),
        data_entries=[GOOD_ENTRY],
        data_format="array",
        test_ids=[TEST_ID] if test_ids is None else test_ids,
        template_entry_ref=None,
        ticket_id="STND-106",
        draft_ref="STND-106/d1",
        retrieved_chunk_ids=[],
        prompt_version="test",
        provider="fake",
        model="fake",
        attempts=1,
        context_tokens=0,
    )


def _settings(tmp_path: Path, runtime: str = "podman", **sandbox: Any) -> Settings:
    return Settings.model_validate(
        {"sandbox": {"runtime": runtime, "work_dir": str(tmp_path / "sandbox"), **sandbox}}
    )


class FakeRuntime:
    """Records commands; answers ``image inspect`` and ``run`` like a container runtime."""

    def __init__(
        self,
        stdout: str = "",
        returncode: int = 0,
        image: bool = True,
        timeout: bool = False,
    ) -> None:
        self.stdout, self.returncode, self.image, self.timeout = stdout, returncode, image, timeout
        self.calls: list[dict[str, Any]] = []
        self.staged: dict[str, str] = {}

    def __call__(self, args: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        self.calls.append({"args": args, **kwargs})
        if args[1:3] == ["image", "inspect"]:
            return subprocess.CompletedProcess(args, 0 if self.image else 1, "", "")
        if args[1] == "run":
            stage = Path(args[args.index("-v", args.index("-v") + 1) + 1].rsplit(":/work", 1)[0])
            self.staged = {
                p.relative_to(stage).as_posix(): p.read_text(encoding="utf-8")
                for p in stage.rglob("*")
                if p.is_file()
            }
            if self.timeout:
                raise subprocess.TimeoutExpired(args, kwargs["timeout"], output=b"partial")
        return subprocess.CompletedProcess(args, self.returncode, self.stdout, "")


@pytest.fixture
def runtime_on_path(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(shutil, "which", lambda name: f"/usr/bin/{name}")


# --- unit tests (no container) ----------------------------------------------------------------


def test_run_args_isolate_the_container(tmp_path: Path) -> None:
    sandbox = _settings(tmp_path, memory="512m", pids_limit=64).sandbox
    args = run_args("podman", sandbox, Path("/r"), Path("/s"), "t2t-x", TEST_FILE)
    assert args[:2] == ["podman", "run"]
    for flag in ("--rm", "--network=none", "--read-only", "--cap-drop=ALL"):
        assert flag in args
    assert args[args.index("--security-opt") + 1] == "no-new-privileges"
    assert args[args.index("--memory") + 1] == "512m"
    assert args[args.index("--pids-limit") + 1] == "64"
    mounts = [args[i + 1] for i, a in enumerate(args) if a == "-v"]
    assert mounts == [f"{Path('/r')}:/repo:ro", f"{Path('/s')}:/work:rw"]  # nothing else
    script = args[-1]
    assert f"pytest --collect-only -q -p no:cacheprovider '{TEST_FILE}'" in script
    assert args[-4] == sandbox.image


def test_unsafe_test_paths_are_refused(tmp_path: Path) -> None:
    sandbox = _settings(tmp_path).sandbox
    for bad in ("tests/x.py'; rm -rf /work; '", "../outside/test_x.py", "tests/$(id).py"):
        with pytest.raises(SandboxError, match="unsafe"):
            run_args("podman", sandbox, Path("/r"), Path("/s"), "n", bad)


def test_a_missing_runtime_is_a_clear_error_never_a_host_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(shutil, "which", lambda name: None)
    fake = FakeRuntime()
    with pytest.raises(SandboxError, match="never collected on the host"):
        collect_generated(_generated(), STANDIN, _settings(tmp_path), runner=fake)
    assert fake.calls == []


def test_a_missing_image_is_a_clear_error(tmp_path: Path, runtime_on_path: None) -> None:
    fake = FakeRuntime(image=False)
    with pytest.raises(SandboxError, match="sandbox --build"):
        collect_generated(_generated(), STANDIN, _settings(tmp_path), runner=fake)
    assert [c["args"][1] for c in fake.calls] == ["image"]  # no run


def test_collect_stages_the_pair_and_compares_ids(tmp_path: Path, runtime_on_path: None) -> None:
    stdout = f"{TEST_FILE}::TestRulesListFilter::{TEST_ID}\n\n1 test collected in 0.1s\n"
    fake = FakeRuntime(stdout=stdout)
    settings = _settings(tmp_path, timeout_seconds=42)
    report = collect_generated(_generated(), STANDIN, settings, runner=fake)
    assert report.ok and report.collected == [TEST_ID] and report.exit_code == 0
    assert set(fake.staged) == {f"generated/{TEST_FILE}", f"generated/{TEST_FILE[:-3]}.json"}
    assert fake.staged[f"generated/{TEST_FILE}"] == GOOD_CODE
    run = next(c for c in fake.calls if c["args"][1] == "run")
    assert run["timeout"] == 42
    assert not any((tmp_path / "sandbox").iterdir())  # the staging folder is removed


def test_id_mismatches_and_failures_are_reported(tmp_path: Path, runtime_on_path: None) -> None:
    stdout = f"{TEST_FILE}::TestRulesListFilter::{TEST_ID}[x]\n"
    report = collect_generated(
        _generated(), STANDIN, _settings(tmp_path), runner=FakeRuntime(stdout=stdout)
    )
    assert not report.ok
    assert report.missing == [TEST_ID] and report.unexpected == [f"{TEST_ID}[x]"]
    broken = FakeRuntime(stdout="ERROR collecting\n", returncode=2)
    report = collect_generated(_generated(), STANDIN, _settings(tmp_path), runner=broken)
    assert not report.ok and report.exit_code == 2 and "ERROR collecting" in report.output_tail


def test_a_timeout_kills_the_container(tmp_path: Path, runtime_on_path: None) -> None:
    fake = FakeRuntime(timeout=True)
    report = collect_generated(_generated(), STANDIN, _settings(tmp_path), runner=fake)
    assert report.timed_out and not report.ok and report.exit_code is None
    assert report.output_tail == "partial"
    assert fake.calls[-1]["args"][1:3] == ["rm", "-f"]


def test_parse_collected_reads_pytest_quiet_output() -> None:
    out = "a.py::T::test_x[1-a]\na.py::test_y\n\n2 tests collected in 0.01s\n"
    assert parse_collected(out) == ["test_x[1-a]", "test_y"]


# --- real container (-m sandbox) --------------------------------------------------------------


def _real_settings() -> Settings:
    settings = Settings()
    if shutil.which(settings.sandbox.runtime) is None or not image_exists(settings):
        pytest.skip(f"{settings.sandbox.runtime} or image {settings.sandbox.image} not available")
    return settings


@pytest.mark.sandbox
def test_real_sandbox_collects_a_generated_standin_test() -> None:
    report = collect_generated(_generated(), STANDIN, _real_settings())
    assert report.ok, report.output_tail
    assert report.collected == [TEST_ID] and report.duration_seconds < 120


@pytest.mark.sandbox
def test_real_sandbox_reports_an_import_error_and_wrong_ids() -> None:
    settings = _real_settings()
    broken = GOOD_CODE.replace(
        "from framework.base_test import BaseTest", "from framework.base_test import NoSuch"
    )
    report = collect_generated(_generated(broken), STANDIN, settings)
    assert not report.ok and report.exit_code != 0 and "NoSuch" in report.output_tail
    wrong_ids = collect_generated(_generated(test_ids=["test_other"]), STANDIN, settings)
    assert not wrong_ids.ok and wrong_ids.missing == ["test_other"]
    assert wrong_ids.unexpected == [TEST_ID]
