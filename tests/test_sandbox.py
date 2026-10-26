"""Sandbox runner (Phase 7). Unit tests use a fake runtime; ``-m sandbox`` runs a real one.

The real tests need Podman or Docker with the sandbox image built
(``ticket2test sandbox --build``) and ``T2T_SANDBOX__RUNTIME`` set if the runtime isn't Docker.
"""

from __future__ import annotations

import os
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
    assert not list((tmp_path / "sandbox").glob("run-*"))  # the staging folder is removed


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


# --- image build, credentials, whole-suite collect ------------------------------------------


def test_runs_never_pull_and_never_use_the_developers_registry_logins(
    tmp_path: Path, runtime_on_path: None
) -> None:
    fake = FakeRuntime(stdout=f"{TEST_FILE}::TestRulesListFilter::{TEST_ID}\n")
    collect_generated(_generated(), STANDIN, _settings(tmp_path), runner=fake)
    run = next(c for c in fake.calls if c["args"][1] == "run")
    assert "--pull=never" in run["args"]
    for call in fake.calls:  # inspect and run alike
        env = call["env"]
        auth = Path(env["REGISTRY_AUTH_FILE"])
        assert auth.read_text(encoding="utf-8").strip() == "{}"
        assert (Path(env["DOCKER_CONFIG"]) / "config.json").read_text().strip() == "{}"
        assert (tmp_path / "sandbox").resolve() in auth.parents
    with_logins = FakeRuntime(stdout="")
    collect_generated(
        _generated(), STANDIN, _settings(tmp_path, registry_auth=True), runner=with_logins
    )
    # With registry_auth the developer's own environment is used unchanged.
    env = with_logins.calls[0]["env"]
    assert env.get("REGISTRY_AUTH_FILE") == os.environ.get("REGISTRY_AUTH_FILE")
    assert env.get("DOCKER_CONFIG") == os.environ.get("DOCKER_CONFIG")


def test_the_image_build_uses_the_configured_base_image_and_requirements(
    tmp_path: Path, runtime_on_path: None
) -> None:
    from ticket2test.sandbox.runner import build_image

    requirements = tmp_path / "suite-requirements.txt"
    requirements.write_text("pytest==9.1.1\nrequests==2.32.0\n", encoding="utf-8")
    staged: dict[str, str] = {}

    def runner(args: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        context = Path(args[-1])
        staged.update({p.name: p.read_text(encoding="utf-8") for p in context.iterdir()})
        return subprocess.CompletedProcess(args, 0, "built", "")

    settings = _settings(
        tmp_path, base_image="registry.example.com/python:3.12", requirements=str(requirements)
    )
    build_image(settings, runner=runner)
    assert staged["requirements.txt"] == requirements.read_text(encoding="utf-8")
    assert "ARG BASE_IMAGE" in staged["Containerfile"]
    assert not list((tmp_path / "sandbox").glob("build-*"))  # the build context is removed

    from ticket2test.sandbox.runner import build_args

    args = build_args("podman", settings.sandbox, Path("/ctx"))
    assert args[args.index("--build-arg") + 1] == "BASE_IMAGE=registry.example.com/python:3.12"
    assert args[args.index("-t") + 1] == settings.sandbox.image


def test_a_missing_requirements_file_is_a_clear_error(
    tmp_path: Path, runtime_on_path: None
) -> None:
    from ticket2test.sandbox.runner import build_image

    settings = _settings(tmp_path, requirements=str(tmp_path / "nope.txt"))
    with pytest.raises(SandboxError, match="Requirements file not found"):
        build_image(settings, runner=FakeRuntime())


def test_the_default_requirements_match_the_lock_file() -> None:
    from ticket2test.sandbox.runner import DEFAULT_REQUIREMENTS

    lock = (Path(__file__).resolve().parents[1] / "uv.lock").read_text(encoding="utf-8")
    for line in DEFAULT_REQUIREMENTS.read_text(encoding="utf-8").splitlines():
        if line and not line.startswith("#"):
            name, version = line.split("==")
            assert f'name = "{name}"\nversion = "{version}"' in lock, line


def test_collect_suite_runs_the_whole_suite(tmp_path: Path, runtime_on_path: None) -> None:
    from ticket2test.sandbox.runner import collect_suite

    stdout = f"{TEST_FILE}::TestX::test_a\ntests/b.py::test_b[1]\n\n2 tests collected in 0.1s\n"
    fake = FakeRuntime(stdout=stdout)
    result = collect_suite(STANDIN, _settings(tmp_path), runner=fake)
    assert result.node_ids == [f"{TEST_FILE}::TestX::test_a", "tests/b.py::test_b[1]"]
    run = next(c for c in fake.calls if c["args"][1] == "run")
    assert run["args"][-1].endswith("pytest --collect-only -q -p no:cacheprovider")
    assert "if [ -d /work/generated ]" in run["args"][-1]


# --- import-time needs of a real suite (env, stubs, paths, ignores) ---------------------------


def test_env_stubs_and_paths_reach_the_container(tmp_path: Path, runtime_on_path: None) -> None:
    from ticket2test.sandbox.runner import collect_suite

    stubs = tmp_path / "stubs"
    (stubs / "runtime_config").mkdir(parents=True)
    (stubs / "runtime_config" / "__init__.py").write_text("MODE = 'stub'\n", encoding="utf-8")
    settings = _settings(
        tmp_path,
        env={"APP_MODE": "test", "PYTHONPATH": "/opt/extra"},
        stub_dir=str(stubs),
        extra_paths=["lib/deploy"],
        collect_ignore=["tests/legacy", "tests/old_test.py"],
    )
    fake = FakeRuntime(stdout="")
    collect_suite(STANDIN, settings, runner=fake)
    args = next(c for c in fake.calls if c["args"][1] == "run")["args"]
    env = [args[i + 1] for i, a in enumerate(args) if a == "-e"]
    assert "APP_MODE=test" in env
    assert "PYTHONPATH=/work/t2t:/work/stubs:/work/repo/lib/deploy:/opt/extra" in env
    assert fake.staged["stubs/runtime_config/__init__.py"] == "MODE = 'stub'\n"  # copied in
    assert "def find_spec" in fake.staged["t2t/t2t_stubs.py"]  # the plugin that makes them win
    assert " -p t2t_stubs " in args[-1]
    mounts = [args[i + 1] for i, a in enumerate(args) if a == "-v"]
    assert len(mounts) == 2  # still only the repo (read-only) and the staging folder
    assert args[-1].endswith("--ignore='tests/legacy' --ignore='tests/old_test.py'")
    single = run_args("podman", settings.sandbox, Path("/r"), Path("/s"), "n", TEST_FILE)
    assert "--ignore" not in single[-1]  # a generated module is collected on its own


@pytest.mark.parametrize(
    ("key", "value", "message"),
    [
        ("env", {"API_TOKEN": "x"}, "looks like a secret"),
        ("env", {"DB_PASSWORD": "x"}, "looks like a secret"),
        ("env", {"bad name": "x"}, "not a variable name"),
        ("extra_paths", ["../outside"], "repo-relative"),
        ("collect_ignore", ["/etc"], "repo-relative"),
        ("collect_ignore", ["tests/x.py'; rm -rf /"], "repo-relative"),
    ],
)
def test_unsafe_sandbox_settings_are_refused(
    tmp_path: Path, key: str, value: Any, message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        _settings(tmp_path, **{key: value})


def test_a_missing_stub_dir_is_a_clear_error(tmp_path: Path, runtime_on_path: None) -> None:
    from ticket2test.sandbox.runner import collect_suite

    settings = _settings(tmp_path, stub_dir=str(tmp_path / "nope"))
    with pytest.raises(SandboxError, match="stub_dir not found"):
        collect_suite(STANDIN, settings, runner=FakeRuntime())


def test_import_problems_are_named_per_module() -> None:
    from ticket2test.sandbox.runner import parse_import_problems

    output = "\n".join(
        [
            "ImportError while loading conftest '/work/repo/tests/conftest.py'.",
            "tests/conftest.py:3: in <module>",
            "    import deploy",
            "E   ModuleNotFoundError: No module named 'deploy'",
            "==== ERRORS ====",
            "____ ERROR collecting tests/area/test_a.py ____",
            "tests/area/test_a.py:1: in <module>",
            "E   KeyError: 'APP_ROOT'",
            "____ ERROR collecting tests/area/test_b.py ____",
            "E   PermissionError: [Errno 13] Permission denied: 'logs'",
            "E   OSError: sudo: not found",
        ]
    )
    found = [(p.path, p.error) for p in parse_import_problems(output)]
    assert found == [
        ("tests/conftest.py", "ModuleNotFoundError: No module named 'deploy'"),
        ("tests/area/test_a.py", "KeyError: 'APP_ROOT'"),
        ("tests/area/test_b.py", "OSError: sudo: not found"),  # the last error wins
    ]


def _side_effect_repo(root: Path) -> Path:
    """A tiny suite that fails to import in a sandbox: its conftest needs an env var, and a
    test module imports a config module that reads a host file at import time."""
    (root / "tests").mkdir(parents=True)
    (root / "tests" / "conftest.py").write_text(
        "import os\n\nMODE = os.environ['APP_MODE']\n", encoding="utf-8"
    )
    (root / "runtime_config.py").write_text(
        "SETTINGS = open('/etc/app/settings.ini').read()\n", encoding="utf-8"
    )
    (root / "tests" / "test_a.py").write_text(
        "import runtime_config\n\n\ndef test_a():\n   pass\n", encoding="utf-8"
    )
    (root / "tests" / "test_b.py").write_text("def test_b():\n   pass\n", encoding="utf-8")
    (root / "pytest.ini").write_text("[pytest]\npythonpath = .\n", encoding="utf-8")
    return root


@pytest.mark.sandbox
def test_real_sandbox_stubs_and_env_make_a_side_effect_suite_load(tmp_path: Path) -> None:
    from ticket2test.sandbox.runner import collect_suite

    repo = _side_effect_repo(tmp_path / "repo")
    base = _real_settings()
    plain = collect_suite(repo, base)
    assert plain.exit_code not in (0, None)
    assert [p.path for p in plain.import_problems] == ["tests/conftest.py"]
    stubs = tmp_path / "stubs"
    stubs.mkdir()
    (stubs / "runtime_config.py").write_text("SETTINGS = ''\n", encoding="utf-8")
    sandbox = base.sandbox.model_copy(update={"env": {"APP_MODE": "test"}, "stub_dir": stubs})
    fixed = collect_suite(repo, base.model_copy(update={"sandbox": sandbox}))
    assert fixed.exit_code == 0, fixed.output_tail
    assert fixed.node_ids == ["tests/test_a.py::test_a", "tests/test_b.py::test_b"]
    ignore = sandbox.model_copy(update={"stub_dir": None, "collect_ignore": ["tests/test_a.py"]})
    partial = collect_suite(repo, base.model_copy(update={"sandbox": ignore}))
    assert partial.exit_code == 0 and partial.node_ids == ["tests/test_b.py::test_b"]


def test_the_stub_plugin_replaces_one_module_inside_a_real_package(tmp_path: Path) -> None:
    """The plugin itself (our code, run here in a subprocess): a stub for ``pkg.conf`` without
    ``pkg/__init__.py`` replaces only that module; the real package and its other modules
    stay."""
    import sys

    from ticket2test.sandbox.runner import STUB_PLUGIN

    repo, stubs = tmp_path / "repo", tmp_path / "stubs"
    (repo / "pkg").mkdir(parents=True)
    (repo / "pkg" / "__init__.py").write_text("REAL = True\n", encoding="utf-8")
    needs_host = "raise RuntimeError('needs the host')\n"
    (repo / "pkg" / "conf.py").write_text(needs_host, encoding="utf-8")
    (repo / "pkg" / "other.py").write_text("NAME = 'other'\n", encoding="utf-8")
    (stubs / "pkg").mkdir(parents=True)
    (stubs / "pkg" / "conf.py").write_text("MODE = 'stub'\n", encoding="utf-8")
    script = (
        f"import sys; sys.path[:0] = [{str(repo)!r}, {str(STUB_PLUGIN.parent)!r}]; "
        "import t2t_stubs, pkg, pkg.conf, pkg.other; "
        "print(pkg.REAL, pkg.conf.MODE, pkg.other.NAME)"
    )
    result = subprocess.run(
        [sys.executable, "-I", "-c", script],
        env={**os.environ, "T2T_STUBS_DIR": str(stubs)},
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.stdout.split() == ["True", "stub", "other"], result.stderr


@pytest.mark.sandbox
def test_real_sandbox_collects_the_standin_with_its_stub() -> None:
    """Stand-in v7: the legacy area imports a module that needs the deployed host; the whole
    suite collects in the sandbox only with the stand-in's stub."""
    from ticket2test.sandbox.runner import collect_suite

    base = _real_settings()
    plain = collect_suite(STANDIN, base)
    assert any(p.path == "tests/units/test_units_reports.py" for p in plain.import_problems)
    sandbox = base.sandbox.model_copy(update={"stub_dir": STANDIN / "sandbox" / "stubs"})
    fixed = collect_suite(STANDIN, base.model_copy(update={"sandbox": sandbox}))
    assert fixed.exit_code == 0, fixed.output_tail
    assert "tests/units/test_units_reports.py::TestUnitsReports::test_units_reports_names" in (
        fixed.node_ids
    )
