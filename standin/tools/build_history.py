"""Build a throwaway git history for the stand-in, for mining ticket <-> test pairs.

    python standin/tools/build_history.py [--out .scratch/standin-history] [--force]

Commits (fixed author and dates, so the history is reproducible):
1. The suite with three known bugs. Their tests are skipped, citing the ticket:
   STND-103 by a code skip, STND-104 and STND-117 by JSON data-entry skips.
2. "Fix STND-103 ..." restores the duplicate-name check and removes the code skip.
3. "Fix STND-104 ..." makes deletes stick and removes its JSON skip.
4. "Fix STND-117 ..." inspects nested archive members and removes its JSON skip.
The last commit's tree equals the stand-in as committed in this repo. (STND-105 and STND-116
are open bugs: their skips are still in the suite.)
"""

import argparse
import json
import os
import shutil
import stat
import subprocess
from pathlib import Path

STANDIN = Path(__file__).resolve().parents[1]
DEFAULT_OUT = STANDIN.parent / ".scratch" / "standin-history"
IGNORE = shutil.ignore_patterns("__pycache__", "*.pyc", "artifacts")

AUTHOR = ("Stand-in Bot", "standin-bot@example.com")
DATES = (
   "2026-01-05T10:00:00+00:00",
   "2026-01-12T15:30:00+00:00",
   "2026-01-19T11:45:00+00:00",
   "2026-01-26T09:15:00+00:00",
)

RULES_TEST = "tests/rules/test_rules.py"
RULES_DATA = "tests/rules/test_rules.json"
STATE = "app/state.py"
FILES_APP = "app/files.py"
ARCHIVES_DATA = "tests/files/test_files_archives.json"

# STND-103: without this check, duplicate rule names are accepted.
DUPLICATE_CHECK = (
   '      if any(r["name"] == rule["name"] for r in tenant.view()["rules"]):\n'
   "         raise ValidationError(f\"A rule named '{rule['name']}' already exists\")\n"
)
# STND-104: deleting from a copy of the rules leaves the policy unchanged.
DELETE_FIXED = '      rules = tenant.edit()["rules"]\n'
DELETE_BUGGY = '      rules = copy.deepcopy(tenant.edit()["rules"])\n'
SKIP_DECORATOR = '   @pytest.mark.skip(reason="STND-103: duplicate rule names are accepted")\n'
SKIP_TARGET = "   def test_rules_add_duplicate_name("
DELETE_TEST_ID = "test_rules_delete_single"
# STND-117: nested archives are skipped, so only top-level members are inspected.
NESTED_FIXED = (
   "            problem = _inspect("
   'rules, f"{name}/{member}", archive.read(member), depth + 1, findings)\n'
)
NESTED_BUGGY = (
   '            nested = file_type(member) == "zip"\n'
   '            problem = "" if nested else _inspect('
   "rules, member, archive.read(member), depth + 1, findings)\n"
)
ARCHIVE_TEST_ID = "test_files_archive_member_blocked"
ID_FIELD = "test_id"


def _edit(path, change):
   text = path.read_text(encoding="utf-8")
   new = change(text)
   if new == text:
      raise RuntimeError(f"history patch did not apply to {path}")
   path.write_text(new, encoding="utf-8", newline="\n")


def _rmtree(path):
   """Delete a folder; git marks its object files read-only, which blocks deletion on Windows."""

   def clear_read_only(function, name, _error):
      os.chmod(name, stat.S_IWRITE)
      function(name)

   shutil.rmtree(path, onexc=clear_read_only)


def _remove_first(text, snippet):
   return text.replace(snippet, "", 1)


def _replace_first(text, old, new):
   return text.replace(old, new, 1)


def _add_skip(text):
   return text.replace(SKIP_TARGET, SKIP_DECORATOR + SKIP_TARGET, 1)


def _json_skip(test_id, ticket, reason):
   def add(text):
      entries = json.loads(text)
      entry = next(e for e in entries if e[ID_FIELD] == test_id)
      entry["skip"] = {"ticket": ticket, "reason": reason}
      # The suite's JSON style: indent 3, "key":value, final newline.
      return json.dumps(entries, indent=3, separators=(",", ":"), ensure_ascii=False) + "\n"

   return add


_add_json_skip = _json_skip(
   DELETE_TEST_ID, "STND-104", "a deleted rule comes back after publishing"
)
_add_archive_skip = _json_skip(
   ARCHIVE_TEST_ID, "STND-117", "nested archive members are not inspected"
)


def _nested_bug(text):
   return _replace_first(text, NESTED_FIXED, NESTED_BUGGY)


def _git(repo, *args, date=None):
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


def _commit(repo, message, date):
   _git(repo, "add", "-A")
   _git(repo, "commit", "-q", "-m", message, date=date)


def _sync(repo):
   """Make the work tree match the current stand-in (keeps .git)."""
   for child in repo.iterdir():
      if child.name == ".git":
         continue
      if child.is_dir():
         shutil.rmtree(child)
      else:
         child.unlink()
   shutil.copytree(STANDIN, repo, ignore=IGNORE, dirs_exist_ok=True)


def build(out, force=False):
   out = out.resolve()
   if STANDIN in (out, *out.parents):
      raise ValueError("--out must be outside the stand-in folder")
   if out.exists() and any(out.iterdir()):
      if not force:
         raise FileExistsError(f"{out} is not empty (use --force to rebuild)")
      _rmtree(out)
   out.mkdir(parents=True, exist_ok=True)
   _git(out, "init", "-q", "-b", "main")

   # Commit 1: all three bugs present, their tests skipped with the ticket id.
   _sync(out)
   _edit(
      out / STATE,
      lambda t: _replace_first(_remove_first(t, DUPLICATE_CHECK), DELETE_FIXED, DELETE_BUGGY),
   )
   _edit(out / RULES_TEST, _add_skip)
   _edit(out / RULES_DATA, _add_json_skip)
   _edit(out / FILES_APP, _nested_bug)
   _edit(out / ARCHIVES_DATA, _add_archive_skip)
   _commit(out, "Add stand-in suite", DATES[0])

   # Commit 2: fix STND-103 (name check back, code skip removed). STND-104, -117 remain.
   _sync(out)
   _edit(out / STATE, lambda t: _replace_first(t, DELETE_FIXED, DELETE_BUGGY))
   _edit(out / RULES_DATA, _add_json_skip)
   _edit(out / FILES_APP, _nested_bug)
   _edit(out / ARCHIVES_DATA, _add_archive_skip)
   _commit(out, "Fix STND-103: reject duplicate rule names", DATES[1])

   # Commit 3: fix STND-104 (delete edits the policy, its JSON skip removed). STND-117 remains.
   _sync(out)
   _edit(out / FILES_APP, _nested_bug)
   _edit(out / ARCHIVES_DATA, _add_archive_skip)
   _commit(out, "Fix STND-104: deleted rules stay deleted after publishing", DATES[2])

   # Commit 4: fix STND-117 (nested members inspected, JSON skip removed) = current stand-in.
   _sync(out)
   _commit(out, "Fix STND-117: inspect members of nested archives", DATES[3])
   return out


def main():
   parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
   parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
   parser.add_argument("--force", action="store_true", help="delete and rebuild --out")
   args = parser.parse_args()
   repo = build(args.out, args.force)
   print(f"Built stand-in history in {repo}")
   print(_git(repo, "log", "--oneline"))


if __name__ == "__main__":
   main()
