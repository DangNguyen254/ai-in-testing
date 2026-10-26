# ticket2test: integration fit check

This document describes a tool called **ticket2test** in enough detail to judge, from the test repository alone, whether the tool fits that repository. You will not get the tool's code. Everything you need to know about it is here.

---

## Part 0. Your task (read this first)

You are working inside a checkout of a real test repository (the **target repo**). A team wants to know whether ticket2test will work on it before they bring the tool in. Your job:

1. Read Parts 1 to 7 to understand what the tool does and what it assumes about a test suite.
2. Examine the target repo and answer every question in **Part 8**, with evidence.
3. Write your answer as **`fit-report.md`** in the repo root, in the format of **Part 9**. Create no other file.

Rules:
- **Read only.** Do not change, add, commit or delete anything except `fit-report.md`. Do not install anything.
- **Never run the tests**, the app, or anything that reaches a browser, a server or the network. Reading files, searching, and `git log` / `git show` are fine.
- **No secrets or personal data** in your report: no passwords, tokens, keys, connection strings, internal hostnames, IP addresses, emails or people's names. Write `<secret>`, `<host>` or `<user>` instead. Class, file and helper names from the repo are fine.
- **Evidence for every claim.** Cite `path:line` for each finding. Look at enough files to know a pattern is general: at least 3 test files in each of the 8 largest test folders, plus the base test class, shared helpers, the code that loads test data, and 2 page objects. Say how many files you checked for each pattern.
- **Don't guess.** If you can't tell, write "unknown" and what you looked for.
- Judge the repo against what the tool **actually** does (Parts 3 to 6). Don't credit it with things it doesn't claim, and don't mark something as a blocker when Part 6 shows it is handled.

---

## Part 1. What the tool is

ticket2test turns a **bug ticket** into a **draft test** for a human Quality Engineer (QE) to review: test code plus its JSON test data, written in the target suite's own style and reusing its own base classes, page objects and helpers.

- **Input:** one ticket (from a Jira JSON export or GitHub issues): title, description, steps to reproduce, expected and actual behaviour, components, labels, comments.
- **Output**, one of:
  - **covered**: an existing test already does exactly this; nothing is written, and the test id is reported;
  - **a new case** of an existing parametrized test (one more parameter value plus one data entry), as a patch;
  - **a new test method** in an existing class, as a patch;
  - **a new test module** plus its data file, scaffolded from the closest existing class.

  Each output comes with a reviewer checklist of things only a real run can confirm. When the suite lacks something the test needs (a page-object member or a helper), the output also includes a separate proposed patch that adds it.
- **A human always reviews**, and a human runs the test. The tool never runs tests against real systems, never writes to the target repo, and never commits anything.

It is built as a **fixed workflow**: code decides the steps and their order. An LLM is used only where language understanding is needed (reading the ticket, writing test steps, and a few bounded helper agents). Every LLM answer is structured JSON and is checked by code before use.

## Part 2. How and where it runs

| Need | Detail |
|---|---|
| Language of the target suite | **Python only** (pytest). Rust support is planned, not built. |
| Tool runtime | Python 3.11+, managed with `uv`; a CLI (`ticket2test <command>`). Runs on Linux, macOS or Windows. |
| Target repo access | A local, read-only checkout. The tool reads files and git history only. |
| Container runtime | Docker or Podman, to load (`pytest --collect-only`) generated tests in a sandbox: no network, read-only copy of the repo, memory and process limits. It needs a base image with the suite's Python version, plus a requirements file with the packages needed to **import** the suite. |
| LLM | Through one interface. Providers: the Claude Code CLI (default), the Anthropic API, or Gemini; another endpoint needs a small adapter. The target model is a small, cheap one (Claude Haiku class). A stronger model is optional, for a one-time "area guide" pass. |
| Data sent to the LLM | Ticket text and selected pieces of the test suite's code (tests, page objects, helpers, data entries). Secrets are scrubbed first; a configurable list of private terms is blanked; prompt-injection text in data is masked. |
| Cost and time (measured on the synthetic suite) | About 3 to 5 LLM calls per ticket; about $0.01 per ticket with a Haiku-class model; 1 to 2 minutes per ticket. The optional area guides are a one-time cost with a hard dollar cap ($50 by default). |

## Part 3. The pipeline, step by step

Each step lists what it **assumes about the target suite**, because that is what decides fit.

### 3.1 Ticket intake
Jira export (JSON in Jira's REST shape) or GitHub issues. Custom Jira fields for steps, expected and actual are mapped in config; otherwise they are found in the description (Jira wiki headings or Markdown). Comments are trimmed.

### 3.2 Draft
The LLM writes a short structured plan with these fields:
- intent;
- markers (priority, component, suite);
- test kind (`ui`, `api` or `hybrid`);
- deployment type (`cloud`, `on_prem` or `both`);
- preconditions, steps and expected outcome;
- parametrized variants.

If the ticket lacks steps or an expected result, the result is **`insufficient_info`**, with a list of questions for the reporter and a partial draft; nothing is guessed. Code checks whether the draft is grounded in the ticket, for example by rejecting numbers the ticket doesn't contain.

### 3.3 Index of the suite (built once, cached, updated per changed file)
- Every Python file is parsed into a syntax tree (tree-sitter). Files that don't parse as Python 3 (e.g. Python 2 code) are skipped and reported.
- **Chunks:** one per test function (with its decorators, markers, parametrize stack and its JSON data entries), and one per page object, helper, function and class.
- **Test ids are computed statically**, as pytest would name them:
  - stacked `@pytest.mark.parametrize`, with the bottom decorator's ids first;
  - inherited tests;
  - class variants generated by decorators.
- **Symbol catalog:** every class, method, property, attribute, fixture and marker value, and the **page-object property chains** reachable from a configured root attribute (e.g. `self.nav.<area>.<page>.<member>`). Types come from:
  - assignments and annotations;
  - property return values;
  - `return self.<chain>` in helpers;
  - helpers that take a dotted page path string (e.g. `self.go_to("area.page")`).
- **Keyword index:** BM25, with code names split into words.

### 3.4 Retrieval
- Query words come from the ticket, plus code words an LLM suggests (invented ones are dropped).
- BM25 search and exact name lookups ("grep") run, and their results are merged.
- The best hits are expanded through the code structure: callers, callees, tests using a helper, and pages a test reaches.
- Results are re-ranked with at most 3 chunks per file.
- Then either up to 2 follow-up searches, or an optional **investigator agent**: an LLM exploring the index with read-only tools, with step and size budgets.
- It also returns the **nearest existing tests that have data entries** as templates, preferring the same component and the same test shape (add / edit / delete / other).

### 3.5 Domain and reuse decision (code only)
- **Domain:** the feature-area folder the ticket belongs to, chosen in this order:
  1. the ticket's own component, if it names exactly one folder;
  2. for a cross-area ticket, the area holding a class marked with all of its components;
  3. otherwise, where the best search hits concentrate.

  All later work stays inside that domain.
- **Reuse:** the draft is compared with every test in the domain: its name, docstring, pages and helpers used, parameters and data keys. Fixed thresholds then decide between covered, new case, new method and new module.
- A new method goes into the class whose component marker matches the ticket. It skips:
  - classes gated to a narrower deployment than the draft;
  - "frozen" (legacy) classes listed in config.

### 3.6 Generation
- The **context** must fit a token budget (12,000 by default); pieces are dropped whole, by relevance. It contains:
  - the template tests;
  - the target class;
  - the relevant page objects and helpers;
  - the **team conventions document**;
  - the area guide, if one exists.
- The LLM writes only the test **steps** and says which data sections to keep and which values change. Code does the rest:
  - **Scaffold:** imports, the decorator stack, the base class and `setup`/`teardown` are copied from the nearest existing class.
  - **Data entry:** copied from the nearest existing entry, trimmed to what the test uses, cloned once per parametrize value, and relabelled with the new test ids.
  - **Unique names:** they use the suite's placeholder.
  - **Formatting:** code and JSON are formatted to the suite's style (indent, line length, quotes, import order, annotations stripped or kept, JSON indent and separators).

### 3.7 Validation (24 code checks) and repair
| Check | What it enforces |
|---|---|
| syntax, imports | parses; every import resolves to the repo, the standard library or an allowed external module |
| names, chains | every name and every page-object chain step exists in the catalog (no invented members) |
| base_class | the class inherits one of the suite's base classes (discovered automatically, or configured) |
| assertions | uses the suite's assertion object (e.g. `self.check.assertEqual`), or `self.assert*` in `unittest.TestCase`-style classes; no bare `assert` |
| markers | required markers present; values from the approved sets (exact casing; comma-joined values checked part by part) |
| naming | module, class and test names match configurable regexes; no ticket numbers in names |
| style, data_file | code and JSON are a fixed point of the suite's formatter settings |
| ids | every data entry's id equals a computed test id, with one entry per parametrize variant |
| data_keys, data_shape | every key the test reads exists in its entries; every seed or expectation key is read by the test or used by the framework or a helper it calls; never two expectation sections |
| seeded_names | seeded object names use the unique-name placeholder and fit the app's name length limit |
| capabilities | warns about feature/capability gates the component doesn't use |
| claims | heuristic: the final checks touch what the test's name and docstring promise |
| hooks | no setup/teardown hook that nothing will call (e.g. `setUp` in a class that isn't a `unittest.TestCase`) |
| page_locators | tests use page actions and properties, never a page's locator constants |
| raw_driver | UI tests never touch the raw browser driver (e.g. `self.driver`); missing actions are reported instead |
| path_strings | dotted page path strings resolve to real pages |
| draft_outcome, variants | the test checks the draft's expected outcome, and every variant the draft lists becomes a case |
| constants | count checks after paging read the page size instead of assuming a number |
| payloads, private | no unmasked injection payloads; no private terms or secrets in output |

Errors go back to the LLM with the exact messages, at most 3 rounds. Then `pytest --collect-only` runs **in the sandbox**, so imports resolve and the collected ids match the data.

### 3.8 Missing pieces (gap report and proposal agent)
- **Gap report:** names the test needed but the suite lacks are checked against the catalog. Some come from the final code, some from earlier repair attempts, some from the investigator's hints. Each gets a verdict: missing / exists / close match / owner unknown / not test-side code. A real gap adds a reviewer note: "this test may work around it".
- **Proposal agent (opt-in):** for a gap on an existing page object or helper class, the LLM writes **only the missing member**. Code then checks:
  - nothing existing changed (syntax-tree comparison);
  - the name and kind match the use (called → method, read or assigned → property);
  - only existing names are used, with no new imports;
  - the suite still loads with the patch, in the sandbox.

  The patch is kept as a separate diff, never applied. The test is then generated again using the new member, and is kept only if it validates. On the synthetic suite, all 3 gap tickets got a correct one-line member, and the final tests used it.
- Today the agent may **not** add new locators, so a member that needs a selector nobody has written yet is left to the reviewer.

### 3.9 After a human runs the test
- The human runs the test with the suite's normal runner and gives the tool the **console log** (pytest `-v` output, xdist lines, failure blocks, remote-browser session links).
- Code reads it into a verdict per test: passed / environment problem / test problem / check failed / not run / unclear.
- An LLM triage agent on top of this is planned, not built.

### 3.10 Suite-level tools
- **`check-suite`:** runs every validator over the suite's **own** tests. Since those are known-good, every error points at a config value that doesn't describe the suite. With `--collect`, it compares the statically computed test ids with a real collect in the sandbox. This is the calibration loop for a new repo.
- **Suite map:** per-area summaries built from the index, without an LLM.
- **Area guides:** one stronger-model call per area, under a budget, then reused by the cheap model.
- **Mining:** ticket ↔ test pairs found in git history (a commit that removes a skip whose reason cites a ticket id), used for evaluation.
- **Eval harness:** retrieval recall and MRR, validator and collect pass rates, and invented-name rate. It runs with each ticket's own test removed from the index (leave-one-out).

## Part 4. What the tool assumes about the target suite

This is the core of the fit check. "Strictness" means:
- **Required:** without it, the tool doesn't work as designed.
- **Config:** a setting describes how the suite does it.
- **Optional:** the tool works without it, with less value.

| # | Assumption | Strictness | Setting / note |
|---|---|---|---|
| A1 | Tests are Python and collected by **pytest** (unittest-style classes collected by pytest are fine). | Required | Python 2 files are skipped, not handled. |
| A2 | Test files match name patterns (default `test_*.py`, `*_test.py`); tests start with `test`, classes with `Test`. | Config | `index.test_file_globs`, prefixes |
| A3 | The suite **collects with no network, no browser and no secrets**: importing the test modules and `conftest.py` must not connect anywhere or require secret env vars. | **Required** for the sandbox check | If import needs network or secrets, the collect check fails or needs stubs. |
| A4 | Test classes inherit one or more **framework base classes** that provide setup, the page-object root and the assertion object. | Config (several roots allowed; discovered automatically) | `validation.base_classes` |
| A5 | UI tests reach pages through **property chains from a root attribute** (e.g. `self.nav.<area>.<page>`), or through helpers that take a **dotted path string**, or helpers that `return self.<chain>`. | Config | `index.chain_roots`, `validation.path_string_helpers`. Pages created any other way (constructor calls such as `LoginPage(driver)`, factories, fixtures returning pages) are not typed, so their members **go unchecked** (no errors, but no protection against invented names either). |
| A6 | Page objects: **value fields are properties** (assign to set, read to get); **actions are methods**; no fluent chaining. | Config for the checks; the style is assumed | Suites with getter/setter methods or chaining still index, but the "property vs action" checks would need turning off. |
| A7 | Page-object members are **defined statically** in class bodies (methods, properties, attributes). | Required for the name checks | Members created by `__getattr__`, metaclasses or runtime `setattr` can't be seen. Members inherited from a base **outside** the repo count as unknown, not missing. |
| A8 | An **assertion object** (a `unittest.TestCase` instance, e.g. `self.check.assertEqual`), or `self.assert*` in TestCase-style classes. | Config | Suites using bare `assert` would need the assertions check turned off. |
| A9 | Each test module has a **JSON data file** next to it (`test_x.py` → `test_x.json`), or a per-function file. | Config; optional per test | `index.data_file_suffix`. Tests that read no data need no entry. Data in YAML, CSV, Python modules or a database is **not** supported. |
| A10 | Data file shape: a top-level **array** of entries with an id field, or an **object** keyed by test id. An optional **defaults entry** shallow-merged into every entry (one top-level key at a time). | Config | `data.format`, `data.id_field` |
| A11 | Entry ids equal **pytest test ids** (incl. parametrize suffixes, stacked decorators bottom-first). | Required for the id checks | Ids built at runtime (computed parametrize values) are listed as "not static" and skipped. |
| A12 | Tests read their entry as a **dict** (`self.params["key"]`, `params.get(...)`, nested keys); no attribute access. | Config | `data.access` |
| A13 | Entries have **seed sections** (state applied before the test by the framework), at most **one expectation section** read by a validation helper that takes no arguments, per-entry keys (priority, skip), and custom keys the test reads. | Config | `data.seed_sections`, `data.expectation_sections`, `data.per_entry_keys` |
| A14 | **Placeholders** in data: a unique-name placeholder derived from the test id with a length cap, plus a helper that returns the same name in code; optionally tenant / user placeholders; colon path placeholders. | Config; optional | `validation.unique_name_pattern`, `unique_name_helper`, `name_max_length` |
| A15 | **Markers** for priority, project, component and suite, with approved value sets. | Config (names and values) | `markers.*`; component values are learned from the suite |
| A16 | A **decorator stack** on classes (platform, environment / deployment gating, data loading, markers) that new tests copy from neighbours. | Optional | Copied as found; deployment gate decorator names are configured. |
| A17 | Tests are grouped in **feature-area folders** (one domain per folder). | Config | `generate.domain_globs` / `generate.domains` |
| A18 | A consistent **code style** (indent, line length, quotes, annotations) and JSON style. | Config | `style.*`; checked by running the suite's own files through the formatter |
| A19 | **Ticket ids in skip reasons** and fix commits. | Optional | Only for mining evaluation pairs |
| A20 | Tickets in **Jira** (exported JSON) or GitHub. | Config | A live Jira API needs a new adapter. |
| A21 | Mostly **UI tests** with backend checks; API tests are also handled. | Optional | Pure API suites work; the page-object machinery is then unused. |

## Part 5. What gets configured, and what has to be written

Nothing in the tool's code is specific to one suite. Integration means writing these files (kept private, outside the tool's repo):

1. **`company.yaml`:** config overrides. It covers:
   - test file patterns and the chain root;
   - data format, id field, data access, seed and expectation sections;
   - style;
   - marker names and values;
   - base classes and the assertion object;
   - allowed external modules;
   - naming regexes;
   - unique-name pattern and length limit;
   - domain folders;
   - deployment decorators and frozen legacy classes;
   - the raw-driver access expressions;
   - path-string helpers;
   - sandbox base image and requirements;
   - Jira field map;
   - private terms;
   - LLM provider and model.
2. **`CONVENTIONS.md`:** the suite's conventions as rules, under ~1,800 words. It goes into every generation context.
3. **A requirements file** for the sandbox image: the packages needed to import the suite.
4. **A ticket export** (Jira JSON), if tickets don't come from GitHub.

Calibration loop:
1. Run `ticket2test index <repo>`, then `ticket2test check-suite <repo>`.
2. Fix the config keys named in the biggest error group. Never fix a test: the suite is the reference.
3. Repeat until clean (at most 10 rounds).
4. Run `check-suite --collect` to compare static and real test ids.
5. Take one ticket end to end, then have a human check the style.

## Part 6. Variations already handled

These came from describing real-suite patterns to the tool's authors. Don't count them as blockers.

- Several unrelated base classes. Test classes inheriting `unittest.TestCase` directly or through a base.
- Base classes from outside the repo: their members are treated as unknown, not missing.
- Inherited tests. Class variants created by decorators (e.g. one class per browser), including their generated node names in run logs.
- A defaults entry merged into every entry. Per-function data files. Both array and object data layouts.
- Python 2 files: skipped and reported, never indexed or imported.
- Dotted path-string helpers to open pages; helpers whose return value is a page.
- Comma-joined marker values. Several component values on one class.
- Legacy or frozen classes: never chosen for new methods. Classes gated to one deployment are skipped when the draft needs both.
- Very large page objects: shown to the LLM as an outline. Very large areas: split into sub-areas. Very many chains: page objects found by type traversal, not a capped list.
- Prompt-injection text inside test data (for suites that test an AI agent): masked before the LLM sees it, restored by code.
- Vague tickets: `insufficient_info` with questions, never a guessed test.

## Part 7. Known limits

- **Not run, only loaded.** The sandbox proves a test imports and its ids match. Whether it passes, and whether it **would catch the bug**, needs a real run by a human. Specific gaps:
  - Expected backend responses are not from a real capture.
  - The save flow, refresh needs and feature gates are listed for the reviewer, not proven.
- **Right name, wrong thing.** If the model uses a member that exists but is the wrong one (e.g. the page heading instead of the browser tab title), every static check passes. The reviewer must catch it.
- **New selectors.** A missing page-object member that needs a locator nobody has written yet can't be proposed; it is reported for the reviewer.
- **Untyped pages.** Pages obtained by constructors, factories or fixtures are not followed, so the "no invented names" protection doesn't cover them (A5).
- **Dynamic code.** `__getattr__`-based page objects, runtime-built tests and runtime-computed parametrize values are partly invisible (A7, A11).
- **Data outside JSON files** is not supported (A9).
- **Python only.** No JavaScript/TypeScript, Java or Rust tests.
- **Import-time side effects** (network, secrets, a browser started at import) break the sandbox collect (A3).
- **Measured only on a synthetic suite.** Results on the synthetic suite (v6, a small stand-in suite):
  - **Held-out tickets:** 7/7 generated tests passed every check after repair and loaded in the sandbox, with 0 invented names.
  - **Gaps and vague tickets:** the missing-piece ticket's gap was reported, and the vague ticket was recognized.
  - **Cost:** about $0.07 for the whole set with a Haiku-class model.

  Real-suite numbers don't exist yet.

---

## Part 8. Questions to answer about the target repo

Answer each one with: the answer, evidence (`path:line`, several where it matters), how many files you checked, and the matching assumption (A#).

**8.1 Size and layout**
1. How many test files, test functions and page-object classes, roughly? Which folders hold tests, and are they grouped by feature area (A17)?
2. What runs the tests: pytest directly, a wrapper script, plugins (xdist, reruns, custom plugins)? Where is the pytest config?

**8.2 Collection safety (A3)**

3. Does importing the test modules and `conftest.py` files connect to anything, start a browser, read secrets or env vars, or need files outside the repo? Quote the lines.
4. Which packages are needed just to import the suite? Are any private (internal index) or tied to system libraries? Which Python version?

**8.3 Test classes (A4, A16)**

5. Which base classes do test classes inherit (follow each chain to its roots)? Are any outside the repo?
6. What is the typical decorator stack on a class, in order? How are deployment or environment gates expressed?
7. How do classes set up and tear down (`setup`, `setup_method`, fixtures, `setUp`)?

**8.4 Page objects (A5 to A7)**

8. How do tests get a page object? Root attribute chains, path-string helpers, helpers returning pages, constructors, factories, fixtures? Give the share of each.
9. Are value fields properties and actions methods? Any fluent chaining?
10. Are members defined statically, or created dynamically (`__getattr__`, metaclasses, `setattr`, generated classes)?
11. Do tests ever use locator constants or the raw driver directly? How often?

**8.5 Checks (A8)**

12. What do tests assert with: an assertion object, `self.assert*`, bare `assert`, custom helpers? How are backend states verified?

**8.6 Test data (A9 to A14)**

13. Where does test data live: JSON next to tests, other formats, inline in code, generated at runtime? Give the share.
14. For JSON: the top-level shape, the id field, whether ids equal pytest ids including parametrize suffixes, whether there is a defaults entry, and whether there are per-function files.
15. How do tests read their entry? Which top-level sections exist, and which are seed / expectation / per-entry keys? Which helper reads each expectation section?
16. Which placeholders appear in data values and paths? Is there a unique-name helper and a name length limit?

**8.7 Markers and style (A15, A18)**

17. Marker names and their values, exact casing; where they sit (class or method); joined values?
18. Code style: indent width, line length, quotes, type annotations, import order; a formatter config? JSON style: indent and separators.

**8.8 Tickets and history (A19, A20)**

19. Do skip reasons or commit messages cite ticket ids? What format? Are there commits that remove such skips?
20. (If visible from the repo) Where do tickets live, and do they have steps / expected / actual sections?

**8.9 Anything else**

21. Patterns not covered by Parts 4 and 6 that would confuse a tool that writes new tests here (code generation, unusual inheritance, test-ordering dependencies, shared state between tests, tests that call other tests).
22. Legacy areas or classes new tests must not copy (Python 2, an old base class, deprecated helpers).

## Part 9. The report format (`fit-report.md`)

```markdown
# ticket2test fit report: <repo name> (<date>)

## Verdict
- Overall fit: <High / Medium / Low / Not suitable>, in one sentence why.
- Will it work: <yes as is after config / yes with listed additions / only for part of the suite / no>.
- Share of the suite it can serve: about <n>% of tests (which kinds), with how you estimated it.

## Assumptions (Part 4)
| # | Holds? (yes / partly / no / unknown) | What the repo does | Evidence (path:line) | Files checked | Fix type |
|---|---|---|---|---|---|
| A1 | ... | ... | ... | ... | none / config / conventions doc / sandbox stub / tool change / blocker |

## Blockers
- <Anything that stops the tool working: what, where, why, and the smallest change that would remove it.> (or "none")

## What it will need
1. Config values (draft the key ones as `key: value  # evidence`, no secrets).
2. Conventions doc topics specific to this repo.
3. Sandbox: Python version, packages, import-time stubs if any.
4. Tool changes, if any, each with the assumption it relates to and how often the pattern occurs.

## Risks
- <Where generated tests are most likely to be wrong in this repo, and why.>

## Answers to Part 8
<Numbered answers 1 to 22, each with evidence.>

## Open questions for a human
- <question>
```

Before finishing, check that:
- every table row has evidence or says "unknown";
- the verdict follows from the assumption table and the blockers;
- the report contains no secrets, hosts, emails or people's names.
