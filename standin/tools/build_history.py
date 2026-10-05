"""Build a throwaway git history for the stand-in, for mining ticket <-> test pairs.

    python standin/tools/build_history.py [--out .scratch/standin-history] [--force]

Commits (fixed author and dates, so the history is reproducible):
1. The suite with two known bugs. Their tests are skipped, citing the ticket:
   STND-103 by a code skip, STND-104 by a JSON data-entry skip.
2. "Fix STND-103 ..." restores quantity validation and removes the code skip.
3. "Fix STND-104 ..." restores order cancellation and removes the JSON skip.
The last commit's tree equals the stand-in as committed in this repo.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path

STANDIN = Path(__file__).resolve().parents[1]
DEFAULT_OUT = STANDIN.parent / ".scratch" / "standin-history"
IGNORE = shutil.ignore_patterns("__pycache__", "*.pyc", "artifacts")

AUTHOR = ("Stand-in Bot", "standin-bot@example.com")
DATES = ("2026-01-05T10:00:00+00:00", "2026-01-12T15:30:00+00:00", "2026-01-19T11:45:00+00:00")

INVENTORY_TEST = "tests/inventory/test_inventory.py"
ORDERS_DATA = "tests/orders/test_orders.json"
STATE = "app/state.py"

QUANTITY_CHECK = (
    '        if quantity < 1:\n            raise ValidationError("Quantity must be at least 1")\n'
)
CANCEL_LINE = '        order["status"] = "cancelled"\n'
SKIP_DECORATOR = '    @pytest.mark.skip(reason="STND-103: items can be saved with quantity 0")\n'
SKIP_TARGET = "    def test_create_item_rejects_invalid_quantity("


def _edit(path: Path, change: Callable[[str], str]) -> None:
    text = path.read_text(encoding="utf-8")
    new = change(text)
    if new == text:
        raise RuntimeError(f"history patch did not apply to {path}")
    path.write_text(new, encoding="utf-8", newline="\n")


def _remove_first(text: str, snippet: str) -> str:
    return text.replace(snippet, "", 1)


def _add_skip(text: str) -> str:
    return text.replace(SKIP_TARGET, SKIP_DECORATOR + SKIP_TARGET, 1)


def _add_json_skip(text: str) -> str:
    data = json.loads(text)
    data["test_cancel_order"]["skip"] = {
        "ticket": "STND-104",
        "reason": "cancelling an order leaves it open",
    }
    return json.dumps(data, indent=2) + "\n"


def _git(repo: Path, *args: str, date: str | None = None) -> str:
    env = dict(os.environ)
    if date:
        env.update(GIT_AUTHOR_DATE=date, GIT_COMMITTER_DATE=date)
    name, email = AUTHOR
    result = subprocess.run(
        ["git", "-c", f"user.name={name}", "-c", f"user.email={email}", *args],
        cwd=repo,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout


def _commit(repo: Path, message: str, date: str) -> None:
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", message, date=date)


def _sync(repo: Path) -> None:
    """Make the work tree match the current stand-in (keeps .git)."""
    for child in repo.iterdir():
        if child.name == ".git":
            continue
        if child.is_dir():
            shutil.rmtree(child)
        else:
            child.unlink()
    shutil.copytree(STANDIN, repo, ignore=IGNORE, dirs_exist_ok=True)


def build(out: Path, force: bool = False) -> Path:
    out = out.resolve()
    if STANDIN in (out, *out.parents):
        raise ValueError("--out must be outside the stand-in folder")
    if out.exists() and any(out.iterdir()):
        if not force:
            raise FileExistsError(f"{out} is not empty (use --force to rebuild)")
        shutil.rmtree(out)
    out.mkdir(parents=True, exist_ok=True)
    _git(out, "init", "-q", "-b", "main")

    # Commit 1: both bugs present, both tests skipped with the ticket id.
    _sync(out)
    _edit(out / STATE, lambda t: _remove_first(_remove_first(t, QUANTITY_CHECK), CANCEL_LINE))
    _edit(out / INVENTORY_TEST, _add_skip)
    _edit(out / ORDERS_DATA, _add_json_skip)
    _commit(out, "Add stand-in suite", DATES[0])

    # Commit 2: fix STND-103 (validation back, code skip removed). Bug STND-104 remains.
    _sync(out)
    _edit(out / STATE, lambda t: _remove_first(t, CANCEL_LINE))
    _edit(out / ORDERS_DATA, _add_json_skip)
    _commit(out, "Fix STND-103: reject item quantities below 1", DATES[1])

    # Commit 3: fix STND-104 (cancellation back, JSON skip removed) = current stand-in.
    _sync(out)
    _commit(out, "Fix STND-104: cancelling an order sets it to cancelled", DATES[2])
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--force", action="store_true", help="delete and rebuild --out")
    args = parser.parse_args()
    repo = build(args.out, args.force)
    print(f"Built stand-in history in {repo}")
    print(_git(repo, "log", "--oneline"))


if __name__ == "__main__":
    main()
