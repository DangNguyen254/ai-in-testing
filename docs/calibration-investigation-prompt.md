# Prompt: investigate the check-suite errors that config alone can't explain

Give the text below to a model session that can read the private folder, the tool and the
real repo (the same setup as for `docs/company-yaml-prompt.md`). It looks at a few examples
of each remaining error group in the latest check-suite report, finds out why the suite's
own tests trip the check, sets the config values it can confirm, and writes a short general
summary that can be shared with the tool's developer.

This file holds the current round's prompt; earlier rounds are in git history.

---

## Prompt (copy from here)

You are helping calibrate a tool called ticket2test against a real test suite. The tool ran
`check-suite`: every validator over the suite's own tests. The suite's tests are known-good,
so each error means either a config value doesn't describe the suite yet, or the tool misses
something the suite does. Find out which, for the groups below.

Paths:
- PRIVATE = `/root/work/t2t-private` (`company.yaml`, `calibration-findings.md`, the reports
  in `output/reports/`)
- TOOL = `/root/work/ai-prj` (the tool and its `config.yaml` with every key and its format;
  read only)
- REPO = `/root/work/<repo>` (the real suite; read only; tests are under the folders in
  `index.test_paths` of `company.yaml`)

### Rules
- Read only in REPO and TOOL. Never run the suite's tests. Searching and reading are fine.
- **Heavy commands one at a time.** Don't run check-suite, the indexer, or any script that
  walks the whole repo unless a step below needs it, and never two at once. If you start one
  in the background, watch it with a single monitor and start nothing else heavy until it
  ends. The machine has little memory; a second heavy job can kill both.
- Start from the newest `PRIVATE/output/reports/check-suite-*.md` (and the `.json` next to
  it): "Errors by check", "Message patterns", "Examples" and "data_keys by key". For more
  examples of a group, search REPO for what the messages name.
- Look at **at most 5 examples per question**. Stop a question once the cause is clear.
- You may change only `PRIVATE/company.yaml`, and only with values you confirmed in REPO.
  First copy it to `PRIVATE/company.yaml.bak4`. Keep every existing key; use only keys that
  exist in `TOOL/config.yaml`. After each value, a comment with the evidence (`path:line`).
- When a cause needs a change in the tool rather than in config, don't work around it: write
  it down for the summary.
- No secrets, hosts or people's names anywhere.

### Questions

**1. Expectation helpers "the test never calls"** (check `data_keys`, messages "only read
by ...(), which the test never calls"). Take the 1–2 sections with the most such messages.
For 5 tests reported this way: does the test, or anything it runs, really call one of the
listed helpers? Trace from the test method, through its class and base classes:
- a `setup`/`teardown` (or `setup_method`, `teardown_method`, ...) that calls the helper,
  directly or through `super().<method>()`;
- a pytest fixture (autouse or requested by name, in the class, a base class or a
  `conftest.py`) that calls it before or after the test;
- a decorator on the test or class that calls it;
- a helper with another name, or a call on another object (`self.<obj>.<helper>()`);
- nothing at all (the section is old data).

Say which, with `path:line`. If the helper is called under a name the config doesn't list
yet, add it to that section in `data.expectation_sections`.

**2. Custom keys "never read by the test"** (check `data_keys`). Take the 8 most common keys
in "data_keys by key". For each, who reads it?
- the framework when it sets up the test (then it belongs in `data.seed_sections`);
- the framework per entry, e.g. to skip or select a test (`data.per_entry_keys`);
- a helper the test calls. How does the helper get the entry: `self.params` inside a method,
  the entry passed under another name, a module function given `self`, a data object with
  attribute access, a fixture with another name? Check whether that access is in
  `data.access`;
- nobody (old data).

Add the keys the framework reads to the right list. For keys read in a way the tool can't
see, describe the way.

**3. Keys "read, but missing from the entry"** (check `data_keys`). For the 2 most common
keys, with 3 examples each: where does the test's value come from? A defaults entry in the
data file (`data.defaults_row`, `data.defaults_merge`), the framework filling it in,
another data file, a read guarded by a check, or a real gap in the data.

**4. Tests that "check nothing"** (check `assertions`). For 5 reported tests from different
areas: what checks the result instead of the assertion object? A helper of the class or a
base class, a page-object method, a log-polling wait, a module function, an exception raised
on failure, or nothing. Add clearly-checking name patterns to `validation.check_helpers`.

**5. "is not an allowed assertion"** (check `assertions`). List the assertion methods the
messages name (from the report's examples or the `.json`). Add those that are real
`unittest.TestCase` methods the suite uses to `validation.assertion_methods`.

**6. ids** (check `ids`). For 2 examples of each of "entries for ids the code doesn't
produce", "the test reads its data entry but has none" and "duplicate entries": which data
file holds the entries, how are they named, and what ids does the suite really run? Note if
the cause is a data file picked up by name prefix that belongs to another test.

**7. base_class** (check `base_class`). For 3 reported classes: what do they inherit? If it
is a base the suite really uses for tests, add it to `validation.base_classes`. If the area
is old code no new test should copy, say so.

### Before finishing
1. If you changed `company.yaml`, run from TOOL (after `source PRIVATE/env.sh`):
   `T2T_CONFIG=PRIVATE/company.yaml uv run --frozen python -c "from ticket2test.config import load_settings; load_settings(); print('config ok')"`
   (with the real path for PRIVATE). Fix and retry until it prints `config ok`, at most 5
   times.
2. Append a section **"Investigation 3"** to the end of `PRIVATE/calibration-findings.md`.
   Read the file again first; it may have changed since you last read it. Two parts:
   - **Details** (private): per question, the examples you looked at, with `path:line`.
   - **Summary to share**: per question, two to five lines in **general words**. Describe
     roles, not names: "a helper method on the area's base class", "a key the framework's
     setup reads", "an autouse fixture in a conftest file", "a data file named after another
     test". No key, class, helper, file, area or host names. Then the config keys you
     changed (key names only), and a list of things the tool would need to handle, one line
     each.
3. Stop there. Don't run check-suite.
