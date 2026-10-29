"""The copy script (scripts/to_container.py): safe targets and the command it builds. No
container is started; the script itself never reads from one."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from tests.conftest import REPO_ROOT

_SPEC = importlib.util.spec_from_file_location(
    "to_container", REPO_ROOT / "scripts" / "to_container.py"
)
assert _SPEC is not None and _SPEC.loader is not None
script = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(script)


@pytest.mark.parametrize(
    "target", ["/root/work/ai-prj", "/root/work/ai-prj-test", "/home/u/ai-prj"]
)
def test_safe_targets(target: str) -> None:
    assert script.check_target(target) == target


@pytest.mark.parametrize(
    "target",
    [
        "/root/work/realrepo",  # not an ai-prj folder: could be the real repo
        "/root/work",
        "/ai-prj",  # too shallow
        "/root/work/../ai-prj",
        "root/work/ai-prj",  # relative
        "/root/work/ai-prj; rm -rf /",
        "/root/work/ai-prj'x",
    ],
)
def test_unsafe_targets_are_refused(target: str) -> None:
    with pytest.raises(ValueError):
        script.check_target(target)


def test_the_container_command() -> None:
    command = script.container_command(
        "podman", "test-runner", "root", "/root/work/ai-prj", "abc1234def56"
    )
    assert command[:7] == ["podman", "exec", "-i", "--user", "root", "test-runner", "sh"]
    assert "-t" not in command  # a terminal would garble the tar stream
    shell = command[-1]
    assert shell.startswith("rm -rf '/root/work/ai-prj' && mkdir -p '/root/work/ai-prj'")
    assert "tar -x -C '/root/work/ai-prj'" in shell and "abc1234def56" in shell
    assert shell.endswith("mkdir -p '/root/work/ai-prj/.scratch'")  # not in the archive
    with pytest.raises(ValueError):
        script.container_command("podman", "x; rm", "root", "/root/work/ai-prj", "abc1234")
    with pytest.raises(ValueError):
        script.container_command("podman", "x", "root", "/root/work/ai-prj", "HEAD; rm")


def test_the_wrapper_calls_the_script() -> None:
    wrapper = (Path(REPO_ROOT) / "scripts" / "to-container.cmd").read_text(encoding="utf-8")
    assert 'to_container.py" %*' in wrapper
