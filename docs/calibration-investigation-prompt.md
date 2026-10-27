# Prompt: investigate the check-suite errors that config alone can't explain

Give the text below to a model session that can read the private folder, the tool and the
real repo (the same setup as for `docs/company-yaml-prompt.md`). It looks at a few examples
of each remaining error group in the latest check-suite report, finds out why the suite's
own tests trip the check, sets the config values it can confirm, and writes a short general
summary that can be shared with the tool's developer.

---

## Prompt (copy from here)

You are helping calibrate a tool called ticket2test against a real test suite. The tool ran
`check-suite`: every validator over the suite's own tests. The suite's tests are known-good,
so each error means either a config value doesn't describe the suite yet, or the tool misses
something the suite does. Find out which, for the groups below.

Paths:
- PRIVATE = `/root/work/t2t-private` (`company.yaml`, the reports in `output/reports/`)
- TOOL = `/root/work/ai-prj` (the tool and its `config.yaml` with every key; read only)
- REPO = `/root/work/<repo>` (the real suite; read only; tests are under the folders in
  `index.test_paths` of `company.yaml`)

### Rules
- Read only in REPO and TOOL. Never run the suite's tests. Searching and reading are fine.
- Start from the newest `PRIVATE/output/reports/check-suite-*.md` (and the `.json` next to
  it): its "Errors by check", "Message patterns", "Examples" and "data_keys by key" sections.
  For more examples of a group, search REPO for what the messages name.
- Look at **at most 5 examples per question**. Stop a question once the cause is clear.
- You may change only `PRIVATE/company.yaml`, and only with values you confirmed in REPO.
  First copy it to `PRIVATE/company.yaml.bak2`. Keep every existing key; use only keys that
  exist in `TOOL/config.yaml`. After each value, a comment with the evidence (`path:line`).
- When a cause needs a change in the tool rather than in config, don't work around it: write
  it down in the summary (question 7).
- No secrets, hosts or people's names anywhere.

### Questions

**1. Tests that "check nothing"** (check `assertions`). Pick 5 of the reported tests. For
each, what does it use to check its result, if not the assertion object
(`validation.assertion_object`)? For example a helper method of its class or base class
(`verify_...`, `check_...`), a method of a page object, a log-polling wait, a function from a
helper module, an exception raised on failure, or nothing at all.
If the calls share name patterns, set `validation.check_helpers` to them (e.g.
`["verify_*", "wait_for_log*"]`). Only patterns that are clearly used for checking.

**2. Keys "only read by `<helper>()`, not called"** (check `data_keys`). For the 1–3 most
common such sections: how does that helper get called, if the tests don't call it? (Search
the framework for the helper's name: a base-class `teardown`, a pytest hook, a fixture, a
wrapper method with another name the tests do call.)
- If the framework always calls it by itself: the section is applied by the framework. Move
  it from `data.expectation_sections` to `data.seed_sections`.
- If tests call it through a wrapper: map the section to the wrapper instead
  (`data.expectation_sections: {<section>: self.<wrapper>}`).

**3. Keys "never read by the test"** (check `data_keys`). For the 10 most common keys in
"data_keys by key": who reads each one? The framework when it sets up the test (then it
belongs in `data.seed_sections`), the framework per entry, e.g. to skip or select a test
(`data.per_entry_keys`), a helper the test calls, or nobody (just old data). Add the keys
the framework reads to the right list.

**4. Keys "read, but missing from the entry"** (check `data_keys`). For 3 examples: where
does the test's value come from? A defaults entry in the data file (`data.defaults_row`,
`data.defaults_merge`), another data file, `params.get(key, default)` with a default, or a
real gap in the data.

**5. "has no member"** (check `names`). Pick 5 examples from different files. For each, find
where the member is really defined:
(a) in the class the message names; (b) in one of its base classes; (c) set at runtime
(`setattr`, a loop, from a config file, `__getattr__`); (d) on a class generated at import
time (e.g. one per browser); (e) in a class outside the repo; (f) nowhere: the variable
really has another type than the message says; (g) nowhere at all.
If (a) or (b), say which file and whether that file was skipped by the index (the report's
first lines and the index output list skipped files, e.g. too large or not Python 3).

**6. Tests that "read their data entry but have none"** (check `ids`). For 3 examples: where
is the test's data? Its file name compared with the test file's name and folder (same name
with `.json`, named after the function, another name, another folder, inside the code, or
no data at all).

**7. Unknown modules** (check `imports`). List the top-level module names reported as
unknown. For each: a third-party package (add it to `validation.external_modules`), a module
of the suite that the tool doesn't find (where is it, and is that folder in
`index.import_roots`?), or a module that doesn't exist.

### Before finishing
1. If you changed `company.yaml`, run from TOOL (after `source PRIVATE/env.sh`):
   `T2T_CONFIG=PRIVATE/company.yaml uv run --frozen python -c "from ticket2test.config import load_settings; load_settings(); print('config ok')"`
   (with the real path for PRIVATE). Fix and retry until it prints `config ok` (at most 5 times).
2. Write `PRIVATE/calibration-findings.md` with two parts:
   - **Details** (private): per question, the examples you looked at, with `path:line`.
   - **Summary to share**: per question, two to five lines in general words. Describe
     roles, not names: "a helper method on the area's base class", "a key the framework's
     setup reads", "a member set in a loop from a config file", "a data file named after the
     class". Then the config keys you changed (key names only), and a list of things the
     tool would need to handle, one line each.
