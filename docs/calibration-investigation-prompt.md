# Prompt: investigate the check-suite errors that config alone can't explain

Give the text below to a model session that can read the private folder, the tool and the
real repo (the same setup as for `docs/company-yaml-prompt.md`). This file holds the current
round's prompt; earlier rounds are in git history.

This round asks for **code shapes**: short skeletons of the suite's code with every name
replaced, so the tool can be made to match them exactly.

---

## Prompt (copy from here)

You are helping calibrate a tool called ticket2test against a real test suite. Its
`check-suite` command runs the tool's validators over the suite's own (known-good) tests.
Some error groups stayed the same after tool changes meant to fix them, so the tool's
developer needs to see exactly how the suite's code is shaped there.

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
- Use the newest `PRIVATE/output/reports/check-suite-*.md` and the `.json` next to it.
- At most 3 examples per question, from different files where possible.
- Don't change `company.yaml` this round.
- No secrets, hosts or people's names anywhere.

### How to write a shape
A shape is the smallest code skeleton that shows the path from the test to where the value
is used, with every name replaced by a role: `TestClass`, `test_method`, `Base`, `helper`,
`module`, `KEY`, `SECTION`, `obj`. Keep the real syntax: `self.`, `super()`, decorators,
`params[...]`, `.get(...)`, `in`, how arguments are passed, assignments. Drop everything
else. Example:

```python
# tests/<area>/test_x.py
class TestClass(Base):
    def test_method(self):
        runner = module.Helper(self)        # self handed to a class from another module
        runner.run()

# <lib>/module.py
class Helper:
    def __init__(self, test):
        self.test = test
    def run(self):
        value = self.test.params["KEY"]      # where KEY is read
```

### Questions

**1. Keys "never read by the test".** Pick 3 of the most common such keys in "data_keys by
key", each from a different area. For each, find the line that really reads the key, and
write the shape from the test method to that line. If nothing reads it, say "unread".

**2. Sections "only read by <helper>(), which the test never calls".** For 3 reported tests
of the most common section: the shape from the test (or its class's setup, teardown,
fixtures, decorators) to the helper call. If the helper is never called, also show how the
test or its entry is marked when it is skipped or retired (a decorator, an entry key and
its value type, a naming rule), or say it is just old data.

**3. The key "read, but missing from the entry"** (the most common one). The shape of the
read and of any check around it, wherever the check is (same method, a base class, a
decorator, a fixture).

**4. ids.** One example each of "the test reads its data entry but has none", "entries for
ids the code doesn't produce" and "duplicate entries". For each:
- the shape of the test (decorators, parametrize, class decorators);
- the data file(s) involved: names as roles (`<module>.json`, `<function>.json`,
  `<function><suffix>.json`), where they sit relative to the test file, and their top-level
  layout;
- 2 entry ids in the form the file has them, with names replaced, keeping separators and
  brackets (e.g. `case_a`, `<function>[case_a]`);
- the ids the message says were computed, in the same masked form.

### Before finishing
Append a section **"Investigation 4"** to the end of `PRIVATE/calibration-findings.md`.
Read the file again first; it may have changed. Two parts:
- **Details** (private): the examples with `path:line`.
- **Summary to share**: per question, the shapes (already masked) and one or two lines on
  what they show. No key, class, helper, file, area or host names anywhere in this part.

Then stop. Don't run check-suite.
