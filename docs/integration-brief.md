# Integration brief: connecting ticket2test to a real test suite

**Who this is for:** an AI assistant (e.g. a small Claude model) working inside the company
environment. You can read the **real test suite** (the "target repo") and this project
("ticket2test"). Your job is to **write the input files that connect them**, and to check
your work with ticket2test's own reports. Read the quick card below first and keep it in
mind the whole time. Read the numbered sections when a step needs them; **re-read the section
for the step you are on** instead of relying on memory. When this file says "stop and ask",
stop and ask the human.

---

## Quick card (keep this in front of you)

**Rules.** Read the target repo only; never write to it. Never edit ticket2test. Write only
your files, in the private folder the human names. No company values in ticket2test's repo.
No secrets in any file. Never run generated tests yourself. If a value isn't found: keep the
default, mark `# TODO`, list it in the report. Building a container image is the human's step.

**Your files.** `company.yaml` (only values that differ from the defaults, each with a
`# evidence: file:line` comment) · `CONVENTIONS.md` · `sandbox-requirements.txt` ·
`tickets.json` (if needed) · `integration-notes.md` (your report).

**Search, don't read.** Use text search (patterns are in section 5). Open a whole file only
when a search result needs context.

**Sessions.** One session per part; start each with this file plus your `integration-notes.md`:

| Session | Do | Sections |
|---|---|---|
| 1 | `company.yaml` + the calibration loop | 3, 5, 6 |
| 2 | `CONVENTIONS.md` | 4, 7 |
| 3 | `sandbox-requirements.txt`, `tickets.json`, final report | 8, 9, 10 |

**The loop (session 1, max 10 rounds).**
1. `ticket2test index <repo>`: tests and page-object chains must be > 0.
2. Draft `company.yaml` from section 5.
3. `ticket2test check-suite <repo>` → open the newest `output/reports/check-suite-*.json`.
4. `"ok": true` → stop. Else take `by_check[0]`, read its `examples` and `hint`, change **one
   or two keys** (table below), count the round, go to 3.
5. Errors left in under 2% of files with no config fix → note them in the report and stop.

| Error check | Change |
|---|---|
| `markers` | `markers.priorities` / `suites` / `project` (exact casing); `markers.required` |
| `assertions` | `validation.assertion_object` / `assertion_methods` (bare `assert` suite → stop and ask) |
| `base_class` | `validation.base_classes` |
| `imports` | add the package to `validation.external_modules` |
| `names` | `index.chain_roots`, `validation.base_classes` |
| `style` | `style.python.indent_width` / `line_length` / `quote_style`; annotations → `strip_annotations: false` |
| `data_file` | `style.json.indent` / `key_separator` / `final_newline` |
| `ids` | `data.id_field`, `data.format`, `index.data_file_suffix`, `data.access` |
| `data_keys` | `data.seed_sections`, `data.per_entry_keys`, `data.expectation_sections` |
| `names_unique` / `name_length` | `validation.name_keys`, `placeholder_pattern`, `unique_name_pattern`, `name_max_length` |
| `naming` | `validation.naming.*` |
| `page_objects` | suite doesn't use property-style page objects → stop and ask |

Never fix a test to make the check pass: the suite is right, the config is wrong.

**Stop and ask** when: the suite has no base class, page objects, or JSON data files; tests use
bare `assert`; you need the allowed registry or base image; a needed package is private; you
can't find the app's name length limit; or 10 rounds are used up.

**Done when** `check-suite --collect` reports `"ok": true` (the human builds the image first),
and `integration-notes.md` follows section 10.

---

## 1. The goal in one paragraph

ticket2test turns a ticket into a draft test case, then into test code plus a JSON data
file, written in the style of the target suite. It does not know the target suite yet. It
learns the suite only from **files you write** (a config file, a conventions document, a
requirements file, a ticket export). You are done when `ticket2test check-suite <target repo>
--collect` reports `"ok": true`, and one ticket goes through the whole pipeline with
`validate --collect` passing.

## 2. Rules (never break these)

1. **Never modify the target repo.** Read it only. Never commit, push, or write files into it.
2. **Never edit ticket2test's code, prompts, or `config.yaml`.** You only write the four input
   files listed in section 3, outside both repos (in the private folder the human names).
3. **Company values stay private.** Never copy names, paths, URLs, or code from the target repo
   into ticket2test's repo (it is public). Only the private files hold them.
4. **No secrets in files.** API keys and tokens go in environment variables only. If a value
   looks like a password, key, or token, do not write it anywhere; tell the human.
5. **Never run generated tests on the host.** Only ticket2test's sandbox runs them (in a
   container). Do not run `pytest` on generated files yourself.
6. **Don't guess silently.** If you can't find a value, keep the default, mark it `# TODO`
   with what you looked for, and list it in your report (section 10).
7. **Bounded work.** The calibration loop in section 6 runs at most **10 rounds**. Then stop
   and report.

## 3. The interface (what goes in, what comes out)

### Inputs: files you write (all in the private folder, e.g. `/private/ticket2test/`)

| # | File | What it is | Used by |
|---|---|---|---|
| 1 | `company.yaml` | Config **overrides** only (section 5). Anything you leave out keeps the built-in default. | every command, via `T2T_CONFIG` |
| 2 | `CONVENTIONS.md` | How tests are written in this suite (section 7). Always shown to the generating model. | `generate.conventions_doc` in `company.yaml` |
| 3 | `sandbox-requirements.txt` | The Python packages needed to *import* the suite's tests (section 8). | `sandbox.requirements` in `company.yaml` |
| 4 | `tickets.json` | One or more tickets as a Jira export (section 9). Only if tickets don't come from GitHub. | `normalize --jira-export` |
| 5 | `integration-notes.md` | Your report to the human (section 10). | the human |

### Environment variables (the human sets them; never write their values into files)

| Variable | Meaning |
|---|---|
| `T2T_CONFIG` | Path to `company.yaml`. Every ticket2test command then uses it. |
| `T2T_SANDBOX__RUNTIME` | `docker` or `podman`. |
| `ANTHROPIC_API_KEY` / `GEMINI_API_KEY` | Only if the LLM provider needs a key. |

### Outputs: files ticket2test writes (you read them; never edit them)

| Command | Writes | What to read |
|---|---|---|
| `ticket2test index <repo>` | an index cache (git-ignored) | the printed counts (section 6, step A) |
| `ticket2test check-suite <repo> [--collect]` | `output/reports/check-suite-<time>.json` and `.md` | `ok`, `errors`, `by_check[]`, `ids` (section 6) |
| `ticket2test generate ...` | `output/generated/<draft id>/`: `decision.json` (covered / variant / method / module, and why); for a new module the test file, its JSON data file and `generated.json`; for a new case or method `patched/<path>` copies of the existing files, `changes.patch`, and `generated.json` | `decision.json` → `kind`, `reasons`; `generated.json` → `validation_report` |
| `ticket2test validate <dir> --repo <repo> --collect` | updates each `generated.json` | `validation_report.findings`, `collect_report.ok` |

`check-suite` JSON fields you need:

```json
{
  "ok": false,                 // true = config matches the suite (your goal)
  "test_files": 120, "tests": 940, "clean_files": 30,
  "errors": 812,               // each error = a config value that doesn't fit the suite
  "by_check": [                // errors grouped by check, biggest first
    {"check": "markers", "errors": 600, "files": 90,
     "hint": "markers.priorities, markers.suites, markers.project, markers.required",
     "examples": ["tests/x/test_y.py: [markers] test_a: priority value 'P1' is not approved (known: p0, p1, p2, p3)"]}
  ],
  "warnings": 300, "warnings_by_check": {"claims": 280},   // heuristics: ignore for calibration
  "not_static": ["tests/z/test_w.py"],                      // fine; see section 6
  "ids": {"ran": true, "exit_code": 0, "static": 940, "collected": 940,
          "only_static": [], "only_collected": [], "not_computed_tests": [], "note": ""}
}
```

## 4. What the target suite is expected to look like

ticket2test was built for suites with this shape. Your config describes **how** the real suite
does each thing. If the real suite is very different (e.g. no page objects, no JSON data files
at all), **stop and ask**.

- pytest, with a framework layer on top: a **base test class** every test class inherits.
- Mostly **browser UI tests** using **page objects** reached through a chain of properties
  from one root attribute (e.g. `self.nav.<area>.<page>`), plus some API tests.
- Page objects: **value fields are properties** (assign to set, read to get); **actions are
  methods** (`open()`, `save()`). No chaining.
- An **assertion object** (a `unittest.TestCase` instance, e.g. `self.check.assertEqual(...)`).
- Each test file has a **JSON data file** next to it with one entry per test id (parametrize
  variants included). The test reads its entry as a dict (`self.params["key"]`).
- Entries have **seed sections** (state applied before the test), at most one
  **expectation section** (read by a validation helper), and custom keys the test reads.
- **Markers** for priority, project, component, and suite, with approved values.
- Data values use **placeholders** (e.g. a unique name derived from the test id).

## 5. `company.yaml`: every value you may need to set

Write **only keys whose value differs** from the default. Format:

```yaml
# company.yaml: private overrides for ticket2test. Generated by <you>, <date>.
markers:
  priorities: [P0, P1, P2, P3]     # evidence: tests/.../test_x.py:12
```

For each key below: **what it means**, **how to find it**, **stand-in example** (the default),
and **if not found**. "Grep" means a text search over the target repo.

### 5.1 Finding test files (`index`)

| Key | Meaning | How to find it | Default (stand-in) |
|---|---|---|---|
| `index.test_file_globs` | Test file name patterns | pytest config (`pytest.ini`, `pyproject.toml` `[tool.pytest.ini_options]`, `setup.cfg`): `python_files`. Else look at names of files with tests. | `["test_*.py", "*_test.py"]` |
| `index.test_function_prefix` | Test function prefix | pytest config `python_functions`; else `test` | `test` |
| `index.test_class_prefix` | Test class prefix | pytest config `python_classes`; else `Test` | `Test` |
| `index.data_file_suffix` | Data file next to a test file | If `tests/a/test_b.py` has `tests/a/test_b.json`, it's `.json`. | `.json` |
| `index.chain_roots` | Root attribute(s) of page-object chains | Grep tests for `= self.` lines like `rules = self.nav.rules.list`; the first word after `self.` that leads to pages is the root. | `[nav]` |
| `index.ignore` | Folders to skip | Add vendored/generated folders you see (keep the defaults too). | see `config.yaml` |

### 5.2 Data files (`data`)

Open 3–5 data files from different areas before deciding.

| Key | Meaning | How to find it | Default |
|---|---|---|---|
| `data.format` | `array` (a list of entries, each with an id key) or `object` (a dict keyed by test id) | The top-level JSON shape. | `array` |
| `data.id_field` | Entry key holding the pytest test id (array format) | The key whose value equals a test name like `test_x[variant]`. | `test_id` |
| `data.access` | Expressions a test indexes to read its entry | Grep tests for `["` after `self.params`, `params`, `self.data`, ... List each spelling. | `["self.params", "params"]` |
| `data.seed_sections` | Top-level keys the framework applies before the test | Read the base class / fixtures that load the entry: which keys do they read and apply? | `[settings, policy, tenants]` |
| `data.expectation_sections` | Expectation key → the helper that reads it | Grep the base class for methods that read the entry and compare backend responses (e.g. `def verify_...`). Map `key: self.<helper>`. | `{targets: self.verify_targets, interactions: self.verify_interactions}` |
| `data.per_entry_keys` | Keys handled per entry by the framework (not read by the test) | Grep conftest/base for keys like `priority`, `skip`, `xfail` read from the entry. | `[priority, skip]` |

### 5.3 Style (`style`)

| Key | How to find it | Default |
|---|---|---|
| `style.python.indent_width` | Count leading spaces of a method body in 3 test files. | `3` |
| `style.python.line_length` | Formatter config in the repo (`ruff`, `black`, `flake8` `max-line-length`); else the longest common line. | `100` |
| `style.python.quote_style` | Do strings use `"` or `'`? | `double` |
| `style.python.strip_annotations` | `false` if test code uses type annotations (`def f(self) -> None`). | `true` |
| `style.python.first_party` | Top-level package names of the repo's own code (for import sorting). Leave empty unless `check-suite` reports style errors about import order. | `[]` |
| `style.json.indent` | Spaces of indentation in data files. | `3` |
| `style.json.key_separator` | `":"` if written `"key":value`, `": "` if `"key": value`. | `":"` |
| `style.json.final_newline` | Does the data file end with a newline? | `true` |

### 5.4 Markers (`markers`)

| Key | How to find it | Default |
|---|---|---|
| `markers.priorities` | Grep `@pytest.mark.<priority marker>("...")`; list every value, **exact casing**, highest first. Registered markers in pytest config may list them. | `[p0, p1, p2, p3]` |
| `markers.suites` | Same for the suite marker. | `[smoke, regression]` |
| `markers.project` | The project marker's value (most common one). | `example-project` |
| `markers.required` | Marker names every test carries (method or class level). If the suite uses other marker names, list those names. | `[priority, project, component, suite]` |

Component values are learned automatically from the suite.

### 5.5 Validators (`validation`)

| Key | How to find it | Default |
|---|---|---|
| `validation.base_classes` | Grep `class Test\w*\((\w+)\)` and follow each base up: list every **root** base the test classes inherit (there may be several, with no common root). | `[BaseTest]` |
| `validation.assertion_object` | Grep `self\.\w+\.assert`; the part before `.assert`. | `self.check` |
| `validation.assertion_methods` | All `assert*` method names used on that object. | see `config.yaml` |
| `validation.external_modules` | Top-level packages tests and framework import that are neither stdlib nor the repo's own (e.g. `pytest`, `selenium`, `requests`). | `[pytest, selenium]` |
| `validation.naming.module` / `test_class` / `test_function` | Regexes the suite's names fit (full match). Keep defaults unless `check-suite` reports `naming` errors. | `test_[a-z0-9_]+` / `Test[A-Z][A-Za-z0-9]*` / `test_[a-z0-9_]+` |
| `validation.name_keys` | Keys in seed sections that hold object names | Look at seeded objects in data files: `name`, `title`, ... | `[name]` |
| `validation.placeholder_pattern` | Regex matching **any** data placeholder | Look at data values with `{...}`, `${...}`, `<...>` | `\{[a-z_]+\d*(?::\d+)?\}` |
| `validation.unique_name_pattern` | Regex for the **unique-name** placeholder; group 1 = max length | e.g. `{test_id:24}` → `\{test_id:(\d+)\}` | `\{test_id:(\d+)\}` |
| `validation.unique_name_helper` | Base-class method returning the same unique name in code | Grep the base class for the method that builds names from the test id. | `self.unique_name` |
| `validation.name_max_length` | The app's maximum object name length | App docs, UI validation messages, or tests about long names. If not found: keep the default, **TODO**. | `32` |
| `validation.capability_gates` | Component → capability/feature flags its features use | Look at the settings seed section. If unclear, set `{}` (this check only warns). | stand-in map |
| `validation.capability_path` | Where gates sit in a seed section | e.g. `settings.capabilities` | `settings.capabilities` |
| `validation.paging_actions` / `constant_properties` | Page-object method names for paging, and the page-size property | Grep page objects for `next`/`page`. If none, set both to `[]`. | `[next_page, previous_page]` / `[page_size]` |

### 5.6 Generation (`generate`)

| Key | How to find it | Default |
|---|---|---|
| `generate.conventions_doc` | Path to your `CONVENTIONS.md` (section 7). **Always set this.** | `null` |
| `generate.placeholder_token` | The unique-name placeholder written in new data, with a typical length | `{test_id:24}` |
| `generate.scaffold_methods` | Names of per-class setup/teardown methods in test classes | `[setup, teardown, setup_method, teardown_method]` |
| `generate.deployment_decorators` | Decorators that limit a test to one deployment type (`cloud` / `on_prem`) | `{cloud: cloud_only, on_prem: on_prem_only}` |
| `generate.review_checklist_defaults` | Things a reviewer must always confirm in a real run. Keep the defaults unless the human gives others. | 3 items |
| `generate.domain_globs` | Folder globs whose matching folders are the suite's **domains** (one feature area per folder; `*` = one folder level). Look at how test folders are grouped: if tests sit in `<root>/<group>/<domain>/`, use `<root>/<group>/*`. Generation stays inside the ticket's domain. | `["tests/*"]` |
| `generate.domains` | Only when one domain spans several folders: `name: [folder globs]` (overrides `domain_globs`). Usually `{}`. | `{}` |
| `generate.reuse` | Thresholds for covered / variant / method. Keep the defaults. | see `config.yaml` |

### 5.7 Sandbox, tickets, LLM

| Key | Value |
|---|---|
| `sandbox.requirements` | Path to your `sandbox-requirements.txt` (section 8). |
| `sandbox.base_image` | An approved image with the suite's Python version. **Ask the human** which registry is allowed. |
| `sandbox.registry_auth` | `true` only if that registry needs a login (the human decides). |
| `sandbox.timeout_seconds` | Raise (e.g. `600`) if collecting the whole suite takes long. |
| `tickets.jira.field_map` | Custom Jira field IDs for `steps_to_reproduce`, `expected`, `actual` (section 9). |
| `tickets.jira.browse_url` | e.g. `https://<jira host>/browse` (private file only). |
| `eval.ticket_id_pattern` | Regex of ticket ids in skip reasons; the default fits `ABC-123`. |
| `security.masking.keys` | Data keys where the suite keeps prompt-injection payloads (their values are always hidden from the LLM). Look at the AI-agent tests' data files: which keys hold the injected text? |
| `security.masking.patterns` | Keep the defaults; add a regex only for payload phrasing the suite uses that the defaults miss (check: `ticket2test` never needs to show those strings to the LLM). |
| `security.private_terms` | **The human sets it**, in `company.yaml` or `T2T_SECURITY__PRIVATE_TERMS`: regexes for names that must never reach the LLM or the public repo. You may suggest candidates in your report (by description, e.g. "the product name"), never in a file of the public repo. |
| `retrieval.shape_actions` | Action words in test names, for test shapes: `add`, `edit`, `delete` (and any action the suite names its tests by, e.g. `download: [download]`). Grep test names and list the verbs that start a flow. | add/edit/delete words |
| `llm.provider` and model | **The human decides.** Don't change. |

## 6. Procedure: calibrate until clean (max 10 rounds)

Run from the ticket2test folder, with `T2T_CONFIG` pointing at your `company.yaml`.

**A. Index.** Run `ticket2test index <target repo>`. Check the printed counts: test chunks > 0,
page-object chains > 0. If chains = 0, `index.chain_roots` is wrong. If tests = 0,
`index.test_file_globs` or the prefixes are wrong.

**B. First draft of `company.yaml`.** Fill section 5 from what you read. Write evidence
(`file:line`) as a comment next to every value you set.

**C. Check.** Run `ticket2test check-suite <target repo>` (without `--collect` first). Open the
newest `output/reports/check-suite-*.json`.

**D. Fix.** Take `by_check[0]` (the biggest group). Read its `examples` and `hint`. Use the
table below to change **one or two keys**, then go back to C. Count rounds.

| Check | Typical message | What to change |
|---|---|---|
| `markers` | `priority value 'P1' is not approved` | `markers.priorities` (exact casing) |
| `markers` | `missing @pytest.mark.suite(...)` | `markers.required` (only markers every test has) |
| `assertions` | `not a bare assert` / `is not an allowed assertion` | `validation.assertion_object`, `assertion_methods`. If the suite really uses bare `assert`, **stop and ask**. |
| `base_class` | `class TestX must inherit BaseTest` | `validation.base_classes` (add the missing root) |
| `imports` | `unknown module 'requests'` | add it to `validation.external_modules` |
| `imports` | `<module> has no name 'X'` | usually fine to report as TODO (dynamic exports); check `index.ignore` didn't skip that module |
| `names` | `X (SomePage) has no member 'y'` | `index.chain_roots`, `validation.base_classes`; if the member is created dynamically, report it |
| `page_objects` | `y is a property: ... don't call it` | the suite may not follow the property style: **stop and ask** |
| `style` | `not formatted to the suite's style` | `style.python.indent_width`, `line_length`, `quote_style`, `first_party` |
| `style` | `type annotations are not used` | `style.python.strip_annotations: false` |
| `data_file` | `not formatted to the suite's JSON style` | `style.json.indent`, `key_separator`, `final_newline` |
| `ids` | `entries for ids the code doesn't produce` | `data.id_field`, `data.format` |
| `ids` | `the test reads its data entry but has none` | `index.data_file_suffix`, `data.access` |
| `data_keys` | `custom key 'k' is never read` | add framework-applied keys to `data.seed_sections` or `data.per_entry_keys` |
| `data_keys` | `'targets' is only read by self.verify_targets()...` | `data.expectation_sections` (helper names) |
| `names_unique` | `seeded name '...' is a literal` | `validation.name_keys`, `validation.placeholder_pattern` |
| `name_length` | `... can be 40 characters; the limit is 32` | `validation.name_max_length`, `validation.unique_name_pattern` |
| `naming` | `class name ... doesn't match` | `validation.naming.*` |

Notes:
- **Don't fix individual tests.** The suite is the reference; only the config changes.
- A few leftover errors in a handful of files can be real oddities in the suite. If one group
  has fewer than 2% of files and no config change explains it, record it in your report and
  move on.
- `not_static` (files with computed parametrize values) is fine. Ignore warnings.

**E. Sandbox.** When `errors` is 0 (or only explained leftovers): write
`sandbox-requirements.txt`, set `sandbox.requirements` and `sandbox.base_image`. Ask the human
to run `ticket2test sandbox --build` (it builds a container image outside both repos: the human
approves this). Then run `ticket2test check-suite <target repo> --collect`.

**F. Read `ids`.** `exit_code` must be 0, `only_static` and `only_collected` empty.
- `exit_code` not 0 and `note` shows `ModuleNotFoundError: X` → add the package to
  `sandbox-requirements.txt`; the human rebuilds.
- `only_static` / `only_collected` not empty → check `index.test_*_prefix` and
  `index.test_file_globs`; report what remains.

**G. Done when** `"ok": true`. Then go to section 7 (conventions) if not written yet, and
section 10 (report).

## 7. `CONVENTIONS.md`: how to write it

The generating model reads this on every ticket. Write **facts from the suite, with short
examples copied from real tests** (generic snippets are fine; keep them short). Use these
headings, in this order (the stand-in's version is in `standin/CONVENTIONS.md`; copy its
structure, not its content):

1. **Structure**: one class per area? Where do new test files go? File and class naming. The
   class decorator stack, in order. Per-class `setup` / `teardown` and the options passed to
   the base setup.
2. **Markers**: which markers sit on the class vs. on each method; approved values.
3. **Page objects and save flows**: the root and how to reach pages; properties vs. actions;
   the save levels (object save, a shared save/publish/reset bar, settings save) and when each
   is used; what actions wait for by themselves.
4. **Test shapes**: the 3–5 common shapes (e.g. add, edit, delete, UI-only search/filter), each
   as a numbered list of steps.
5. **Checks**: the assertion object and its methods; argument order habits; whether messages
   are passed; the backend validation helpers and that they take no arguments.
6. **Data**: file format and the id field; how a test reads its entry; seed sections and what
   each holds; expectation sections and their format; placeholders (unique names, users,
   tenants) and the length limit; custom keys only for values the test reads.
7. **List pages** (if the suite has them): sort order, page size, what counts mean.
8. **Style**: indent, line endings, imports, annotations; JSON style.
9. **Deployment and flakiness**: deployment-only decorators; retry decorators and when allowed.

Keep it under ~300 lines. Every rule must be true for most of the suite; if a rule has common
exceptions, say so.

## 8. `sandbox-requirements.txt`

The sandbox only **collects** tests (`pytest --collect-only`): it imports every test module and
the framework, but runs nothing and needs no browser. So list what's needed **to import**.

1. Look for the suite's own requirement files (`requirements*.txt`, `pyproject.toml`
   dependencies, `Pipfile`, `setup.cfg`). Prefer the file used for running tests.
2. Copy the package lines with **pinned versions** (`name==1.2.3`). Include `pytest`.
3. Leave out packages that need private indexes or system libraries unless imports need them;
   if a needed package is private, **stop and ask** (the image may need a private index).
4. If the suite needs its own code installed (e.g. `pip install -e .`), tell the human; the
   sandbox copies the repo and runs pytest from its root, so `pythonpath` in the pytest config
   usually covers it.

## 9. `tickets.json` (Jira export)

ticket2test reads a single issue, a list of issues, or `{"issues": [...]}` in Jira's REST
format. Minimal example of what each issue needs:

```json
{"issues": [{
  "key": "ABC-123",
  "fields": {
    "summary": "One-line title",
    "description": "Text or Jira wiki markup (h3. Steps to Reproduce / # step / h3. Expected Behavior / h3. Actual Behavior)",
    "labels": ["area-label"],
    "components": [{"name": "area"}],
    "comment": {"comments": [{"author": {"displayName": "Name"}, "created": "2026-01-01T00:00:00.000+0000", "body": "..."}]}
  }
}]}
```

- If steps / expected / actual live in **custom fields**, set
  `tickets.jira.field_map: {steps_to_reproduce: customfield_NNNNN, expected: customfield_NNNNN,
  actual: customfield_NNNNN}`. Find the ids in an exported issue (keys that start with
  `customfield_` and hold those texts).
- Check: `ticket2test normalize ABC-123 --jira-export tickets.json --out t.json` → `t.json`
  must have non-empty `steps_to_reproduce` and `expected` for a well-written ticket.

## 10. Your report: `integration-notes.md`

Use exactly this structure:

```markdown
# Integration notes (<date>)

## Result
- check-suite: ok = <true/false>, errors = <n>, rounds used = <n>/10
- ids (--collect): <collected> collected, <only_static> only static, <only_collected> only collected
  (or "not run: waiting for the image build")

## Values set in company.yaml
| Key | Value | Evidence (file:line) | Confidence (high/medium/low) |
|---|---|---|---|

## TODO / not found
- <key>: what I looked for, where; current value = default

## Leftover errors (explained)
- <check>: <n> errors in <files>; why no config change fixes them

## Questions for the human
- <question>

## Suite differences from the expected shape (section 4)
- <difference> (or "none")
```

## 11. After calibration (the human runs these; you can help read results)

```bash
ticket2test normalize ABC-123 --jira-export /private/ticket2test/tickets.json --out t.json
ticket2test draft t.json --out drafts/
ticket2test retrieve t.json --repo <target repo> --draft drafts/ABC-123.drafts.json --out r.json
ticket2test generate drafts/ABC-123.drafts.json --retrieval r.json --out output/generated
ticket2test validate output/generated --repo <target repo> --collect
```

Then a human compares the generated test with real ones (style check), and
`ticket2test mine <target repo> --out <private>/mined.json` builds eval pairs from the git
history (read-only).
