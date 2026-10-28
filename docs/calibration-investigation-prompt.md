# Prompt: calibration, config-only pass

Give the text below to a model session that can read the private folder, the tool and the
real repo (the same setup as for `docs/company-yaml-prompt.md`). This file holds the current
round's prompt; earlier rounds are in git history.

This round fixes what config alone can fix in the small error groups that are left. It
changes nothing but the private config.

---

## Prompt (copy from here)

You are helping calibrate a tool called ticket2test against a real test suite. Its
`check-suite` command runs the tool's validators over the suite's own (known-good) tests.
Most of what is left is real leftovers in the suite or needs tool changes. Your job is only
the part that config can fix.

Paths:
- PRIVATE = `/root/work/t2t-private` (`company.yaml`, `calibration-findings.md`, the reports
  in `output/reports/`)
- TOOL = `/root/work/ai-prj` (the tool; its `config.yaml` lists every key with its format;
  read only)
- REPO = `/root/work/<repo>` (the real suite; read only)

### Rules
- Read only in REPO and TOOL. Never run the suite's tests. Searching and reading are fine.
- **Heavy commands one at a time.** Don't run check-suite, the indexer, or any script that
  walks the whole repo, and never two heavy jobs at once. A background job gets a single
  monitor, and nothing else heavy starts until it ends.
- Use the newest `PRIVATE/output/reports/check-suite-*.json`: `by_check` has, per check,
  `pattern_examples` (up to 5 examples per message pattern, each from a different file).
- Change only `PRIVATE/company.yaml`. First copy it to `PRIVATE/company.yaml.bak7`. Keep every
  existing key; use only keys that exist in `TOOL/config.yaml`. After each value you add or
  change, a comment with the evidence (`path:line`).
- Add a value only when you confirmed it in REPO. When a group needs a tool change or is old
  code or old data, change nothing for it and note it for the summary.
- No secrets, hosts or people's names anywhere, including your chat reply.

### Steps

**0. The repo path.** Set `paths.repo` to the real suite's checkout (the REPO path above), if
it isn't set yet.

**1. base_class** ("class ... must inherit one of ..."). For the reported classes (up to 5):
what do they inherit?
- a base the suite really uses for tests: add it to `validation.base_classes`;
- nothing at all, and the class is a plain API test: check that `validation.baseless_classes`
  is `true`;
- old code no new test should copy: note it.

**2. assertions, "is not an allowed assertion".** Name the method. If it is a real
`unittest.TestCase` method the suite uses, add it to `validation.assertion_methods`; if it is
a helper of the suite, note it.

**3. imports, "unknown module".** Find the module: a third-party package (add its top-level
name to `validation.external_modules`), a module of the suite in a folder that is missing
from `index.import_roots` (add the folder), or a module that doesn't exist (note it).

**4. data_keys, keys "never read by the test".** For the 5 most common keys in "data_keys by
key" that no earlier round looked at: is the key read by the framework when it sets up a test
(add it to `data.seed_sections`) or per entry, e.g. to skip or select a test
(`data.per_entry_keys`)? If a helper or the test reads it in a way the tool doesn't see, or
nothing reads it, change nothing and note which.

**5. data_keys, keys "read, but missing from the entry".** For each such key (they are few):
does the value come from a defaults entry in the data file (`data.defaults_row`,
`data.defaults_merge`), from a read guarded in a way the tool doesn't see, or is it a real gap
in the data? Change config only for the first.

### Before finishing
1. Run from TOOL (after `source PRIVATE/env.sh`):
   `T2T_CONFIG=PRIVATE/company.yaml uv run --frozen python -c "from ticket2test.config import load_settings; load_settings(); print('config ok')"`
   (with the real path for PRIVATE). Fix and retry until it prints `config ok`, at most 5
   times.
2. Append a section **"Config pass 7"** to the end of `PRIVATE/calibration-findings.md`. Read
   the file again first; it may have changed. Two parts:
   - **Details** (private): per step, the examples with `path:line` and the values set.
   - **Summary to share**: per step, one or two lines in general words (roles, not names),
     the config keys you changed (key names only), and the groups left alone with the reason
     (needs a tool change, old code, old data), one line each.
3. Stop there. Don't run check-suite.
