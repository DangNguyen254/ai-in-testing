# Prompt: investigate the check-suite errors that config alone can't explain

Give the text below to a model session that can read the private folder, the tool and the
real repo (the same setup as for `docs/company-yaml-prompt.md`). This file holds the current
round's prompt; earlier rounds are in git history.

This round asks for **code shapes** (short skeletons with every name replaced) for the
largest group left, tests the tool says check nothing, plus one data group.

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
  a single monitor, and nothing else heavy starts until it ends.
- Use the newest `PRIVATE/output/reports/check-suite-*.json`. In it, each check under
  `by_check` has `pattern_examples`: for each message pattern, up to 5 examples, each from
  a different file. Take examples from there. If a question needs more than it holds, find
  more by searching REPO for tests like them, and say so.
- You may change only `PRIVATE/company.yaml`, and only to add check-helper name patterns in
  question 1 that you confirmed in at least two areas (copy it to
  `PRIVATE/company.yaml.bak6` first; a comment with `path:line` after each value).
- No secrets, hosts or people's names anywhere, including your chat reply.

### How to write a shape
The smallest code skeleton that shows the path from the test to the line that matters, with
every name replaced by a role: `TestClass`, `test_method`, `Base`, `helper`, `module`,
`Obj`, `KEY`. Keep the real syntax: `self.`, `super()`, decorators, `params[...]`,
`.get(...)`, `**`, how arguments are passed, assignments, `raise`, `assert`, `yield`.
Drop everything else. Example:

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

**1. Tests that "check nothing"** (check `assertions`, pattern "the test checks nothing").
Take the 5 examples in `pattern_examples`, and add 3 more tests from other areas with the
most such tests (8 in all, from at least 5 areas). For each, the shape from the test method
to the line that makes the test fail when the result is wrong:
- an assertion or `fail` on some object (which one: the class, a base class, a page object,
  a helper object built in the test, a module-level object, a module function);
- a `raise` or an exception a called method throws on failure;
- a wait that times out;
- a fixture, decorator or hook that checks after the test;
- nothing at all (the test only drives the UI or calls something and ignores the result).

Say how the test reaches the check (a call on `self`, on a page object from a chain, on an
object built in the test, through a module function). If a checking helper's name pattern
shows up in at least two areas, add it to `validation.check_helpers`.

**2. Keys "never read by the test"** (check `data_keys`). The two key pairs that most often
appear together. For one test of each pair (from `pattern_examples` where possible): the
shape from the test to the line that reads the keys, keeping exactly how the entry travels
(a local alias, `**params`, a loop over its items, a call on an object, an attribute of
another object, a fixture with another name, a framework hook). If nothing reads them, say
"unread".

### Before finishing
1. If you changed `company.yaml`, run from TOOL (after `source PRIVATE/env.sh`):
   `T2T_CONFIG=PRIVATE/company.yaml uv run --frozen python -c "from ticket2test.config import load_settings; load_settings(); print('config ok')"`
   (with the real path for PRIVATE). Fix and retry until it prints `config ok`, at most 5
   times.
2. Append a section **"Investigation 6"** to the end of `PRIVATE/calibration-findings.md`.
   Read the file again first; it may have changed. Two parts:
   - **Details** (private): the examples with `path:line`.
   - **Summary to share**: per question, the shapes (already masked), and for question 1
     how many of the 8 tests fall into each kind of check. No key, class, helper, file,
     area or host names anywhere in this part. Then the config keys you changed (key names
     only).
3. Stop there. Don't run check-suite.
