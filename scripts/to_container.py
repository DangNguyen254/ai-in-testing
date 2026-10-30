"""Copy this project's committed files into a container, replacing the previous copy.

    python scripts/to_container.py <container> [--target /root/work/ai-prj]

Only committed files go (``git archive HEAD``): no virtual environment, ``.env``, ``.scratch``
or git history. The previous copy's ``.scratch`` is kept (an empty one is made the first time),
since the tool writes its working files there. The copy is replaced in place: copy only when
nothing is running from it. The target must be a folder named ``ai-prj`` (or
``ai-prj-<something>``), so a typo can't point a removal at another folder, such as the real
repo next to it. Nothing is read from the container. A
``.copied-from`` file in the copy records the commit.

Standard library only, so it runs with any Python on the host.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
_SAFE = re.compile(r"^/[\w./-]+$")
_NAME = re.compile(r"^ai-prj(-[\w.-]+)?$")


def check_target(target: str) -> str:
    """The target folder, if it is safe to remove and write again; else ``ValueError``."""
    path = PurePosixPath(target)
    if not _SAFE.match(target) or ".." in path.parts or len(path.parts) < 3:
        raise ValueError(f"{target!r} must be an absolute folder path at least two levels deep")
    if not _NAME.match(path.name):
        raise ValueError(f"{target!r}: the folder must be named ai-prj (or ai-prj-<something>)")
    return str(path)


def container_command(runtime: str, container: str, user: str, target: str, sha: str) -> list[str]:
    """The command that receives the tar stream on stdin and replaces the copy."""
    if not re.fullmatch(r"[\w.-]+", container) or not re.fullmatch(r"[\w.-]+", user):
        raise ValueError("the container and user names may only use letters, digits, . _ -")
    if not re.fullmatch(r"[0-9a-f]{7,40}", sha):
        raise ValueError(f"unexpected commit id {sha!r}")
    script = (
        # everything but .scratch (git-ignored, so not in the archive; the tool writes its
        # working files there) is replaced; leftovers of the earlier swap-by-rename are removed
        f"rm -rf '{target}.new' '{target}.old' && mkdir -p '{target}/.scratch' "
        f"&& find '{target}' -mindepth 1 -maxdepth 1 ! -name .scratch -exec rm -rf {{}} + "
        f"&& tar -x -C '{target}' && printf '%s\\n' {sha} > '{target}/.copied-from'"
    )
    return [runtime, "exec", "-i", "--user", user, container, "sh", "-c", script]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    parser.add_argument("container", help="container name, e.g. from `podman ps`")
    parser.add_argument("--target", default="/root/work/ai-prj", help="folder in the container")
    parser.add_argument("--user", default="root", help="user inside the container")
    parser.add_argument("--runtime", default="podman", choices=["podman", "docker"])
    args = parser.parse_args(argv)
    try:
        target = check_target(args.target)
        sha = _git("rev-parse", "--short=12", "HEAD").strip()
        command = container_command(args.runtime, args.container, args.user, target, sha)
    except (ValueError, subprocess.CalledProcessError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if _git("status", "--porcelain", "--untracked-files=no").strip():
        print("note: uncommitted changes are not copied (only the last commit is)")
    archive = subprocess.Popen(
        ["git", "archive", "--format=tar", "HEAD"], cwd=ROOT, stdout=subprocess.PIPE
    )
    assert archive.stdout is not None
    copy = subprocess.run(command, stdin=archive.stdout, check=False)
    archive.stdout.close()
    if archive.wait() != 0 or copy.returncode != 0:
        print("error: the copy failed (see the messages above)", file=sys.stderr)
        return 1
    print(f"copied {sha} to {args.container}:{target}")
    return 0


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout


if __name__ == "__main__":
    sys.exit(main())
