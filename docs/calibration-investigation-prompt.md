# Prompt: investigate the check-suite errors that config alone can't explain

Give the text below to a model session that can read the private folder, the tool and the
real repo (the same setup as for `docs/company-yaml-prompt.md`). This file holds the current
round's prompt; earlier rounds are in git history.

This round asks for **code shapes** (short skeletons with every name replaced) for the three
groups that are left, so the tool can be made to match them exactly.

---

## Prompt (copy from here)

You are helping calibrate a tool called ticket2test against a real test suite. Its
`check-suite` command runs the tool's validators over the suite's own (known-good) tests.
The tool's developer needs to see exactly how the suite's code is shaped for the groups
below.

Paths:
- PRIVATE = `/root/work/t2t-private` (`company.yaml`, `calibration-findings.md`, the reports
  in `output/reports/`)
- TOOL = `/root/work/ai-prj` (the tool; read only)
- REPO = `/root/work/<repo>` (the real suite; read only)

### Rules
- Read only in REPO and TOOL. Never run the suite's tests. Searching and reading are fine.
- **Heavy commands one at a time.** Don't run check-suite, the indexer, or any script that
  walks the whole repo unless a step needs it, and never two at once. A background job gets
  a single monitor, and nothing else heavy starts until it ends. The machine has little
  memory.
- Use the newest `PRIVATE/output/reports/check-suite-*.md` and the `.json` next to it. Take
  examples from this report only, and say if one isn't.
- At most the number of examples each question asks for, from different files and areas.
- You may change only `PRIVATE/company.yaml`, and only to add check-helper name patterns in
  question 1 that you confirmed (copy it to `PRIVATE/company.yaml.bak5` first; a comment
  with `path:line` after each value).
- No secrets, hosts or people's names anywhere.

### How to write a shape
The smallest code skeleton that shows the path from the test to the line that matters, with
every name replaced by a role: `TestClass`, `test_method`, `Base`, `helper`, `module`,
`Obj`, `KEY`. Keep the real syntax: `self.`, `super()`, decorators, `params[...]`,
`.get(...)`, `**`, how arguments are passed, assignments, `raise`, `assert`. Drop everything
else. Example:

```python
class TestClass(Base):
    def test_method(self):
        page = self.nav.area.page
        page.verify_rows(expected)            # the check: a page-object method
# pages module
class Page:
    def verify_rows(self, expected):
        assert self.rows == expected          # what it does on failure
```

### Questions

**1. Tests that "check nothing"** (check `assertions`). Pick 6 reported tests from 6
different areas, favouring the areas with the most such tests. For each, the shape from the
test method to the line that would make the test fail when the result is wrong: an
assertion, a `raise`, a `pytest.fail`, a wait that times out, a helper's return value the
test ignores, or nothing at all. Show which object the check sits on (the class, a base
class, a page object, a helper object built in the test, a module function) and how the test
reaches it. If several areas use a helper with a clear checking name, add its pattern to
`validation.check_helpers`.

**2. Keys "never read by the test"** (check `data_keys`). The 2–3 keys that most often appear
together in the same message: 2 tests that carry them. The shape from the test to the line
that reads them, keeping exactly how the entry travels (a local alias such as
`data = self.params`, `**params`, a loop over its items, a copy, an attribute of another
object, a fixture with another name). If nothing reads them, say "unread".

**3. "the test reads its data entry but has none"** (check `ids`). 2 examples. For each:
- the test's shape (decorators, parametrize, class decorators, how it reads data);
- which data files sit next to the test file, as roles (`<module>.json`, `<function>.json`,
  `<function><suffix>.json`, other), and their top-level layout;
- 2 entry ids in those files, masked, keeping separators and brackets;
- the id the message names, masked the same way.

### Before finishing
1. If you changed `company.yaml`, run from TOOL (after `source PRIVATE/env.sh`):
   `T2T_CONFIG=PRIVATE/company.yaml uv run --frozen python -c "from ticket2test.config import load_settings; load_settings(); print('config ok')"`
   (with the real path for PRIVATE). Fix and retry until it prints `config ok`, at most 5
   times.
2. Append a section **"Investigation 5"** to the end of `PRIVATE/calibration-findings.md`.
   Read the file again first; it may have changed. Two parts:
   - **Details** (private): the examples with `path:line`.
   - **Summary to share**: per question, the shapes (already masked) and one or two lines on
     what they show. No key, class, helper, file, area or host names anywhere in this part.
     Then the config keys you changed (key names only).
3. Stop there. Don't run check-suite.
