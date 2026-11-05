# Commands

Every `ticket2test` command, what it does, and its arguments and options. Run them from the tool's
folder with `uv run ticket2test <command> ...` (or `ticket2test ...` inside the activated
environment). `uv run ticket2test <command> --help` prints the same from the code itself.

`[LLM]` marks commands that call the model. Everything is written to the tool's output folder
(`paths.output_dir`, default `output/`); the target repo is only read, never changed.

## Global options and settings

Put these **before** the command name: `uv run ticket2test --config my.yaml run ABC-1`.

| Option | What it does |
|---|---|
| `--config <path>` | The config YAML to use. Default: `./config.yaml`, or the file in `T2T_CONFIG`. |
| `--debug-log` | Also write full prompts and model answers to the git-ignored debug-log folder. Off by default (they may contain source code). |
| `--version` | Print the version. |

**Any config value can be overridden for one run** with an environment variable: `T2T_` +
section + `__` + key, upper case, nested with `__`. They win over the config file. Examples:

```bash
T2T_GUIDES__USE_IN_GENERATION=false uv run ticket2test run ABC-1 --continue
T2T_GENERATE__REUSE__COVERAGE_CHECK=true uv run ticket2test run ABC-1 --continue
T2T_REPAIR__WARNING_CHECKS='[]' uv run ticket2test golden golden.json --label no-warning-repair
```

Lists are written as JSON. Secrets (API keys) are never config: they come from their own
environment variables.

---

## One ticket

### `new-ticket <KEY>`

Writes an empty ticket file, `<tickets folder>/<KEY>.md`, with the sections to fill in by hand
(title, description, steps to reproduce, expected, actual, components, labels, comments, links).
Use it while the tracker's API can't be used: copy the ticket's text into it, then `run <KEY>`.

| Argument / option | What it does |
|---|---|
| `KEY` (required) | The ticket id, e.g. `ABC-123`. Also the file name. |
| `--dir <path>` | Where pasted tickets are kept: a private folder, never the repo. Default: `paths.tickets_dir`. |

### `run <KEY>` `[LLM]`

One ticket end to end, in two halves with your review between them.

- **First half** (`run <KEY>`): reads the ticket, normalizes it, writes the draft
  (`drafts/<KEY>.drafts.json` and a readable `.md`), then stops so you can read it. To change the
  draft, edit the `.json` (the `.md` is only a copy) or improve the ticket file and run again.
- **Second half** (`run <KEY> --continue`): search, reuse decision, generation, validators and
  repair; writes the test to `generated/<KEY>_d1/`.

| Argument / option | What it does |
|---|---|
| `KEY` (required) | The ticket id. |
| `--paste <dir>` | Read the ticket from `<dir>/<KEY>.md`. Default: `paths.tickets_dir`. |
| `--jira-export <file>` | Read the ticket from an exported Jira JSON file instead. |
| `--continue` | Run the second half (after you reviewed the draft). |
| `--repo <path>` | The target repo. Default: `paths.repo`. |
| `--hide <test or file>` | With `--continue`: something the tool must not see, as if it didn't exist. A test (`path::Class::method`, or just the method name) or a whole test file (its path in the repo ending in `.py`; its data file goes too). Repeatable. Works on a copy of the repo in the cache; the repo isn't changed. Paths are relative to the repo root, as `target_file` in `decision.json`. |
| `--coverage-check` / `--no-coverage-check` | With `--continue`: ask the model first whether an existing test already covers the draft (one extra call). Default: `generate.reuse.coverage_check` (off). |

To run the second half again, delete `generated/<KEY>_d1/` first.

---

## The steps on their own

`run` calls these in order; use them to repeat or inspect one step.

### `normalize <REF>`

Fetches a ticket and turns it into the tool's ticket format (`tickets/<id>.json`). Nothing is
guessed: missing sections stay empty.

| Argument / option | What it does |
|---|---|
| `REF` (required) | A GitHub issue (`owner/repo#123` or its URL); a Jira key with `--jira-export`; a ticket key or `.md` file with `--paste`. |
| `--jira-export <file>` | Read the Jira issue from this exported JSON file (no network). |
| `--paste <dir>` | Read `<dir>/<REF>.md`, a pasted ticket (no network). |
| `--out <path>` | Output file. Default: `<output>/tickets/<id>.json`. |
| `--raw-out <path>` | Also save the raw source data (for test fixtures). |

### `draft <TICKET_FILE>` `[LLM]`

Writes the structured test-case drafts (JSON + Markdown) from a normalized ticket: intent,
markers, test kind, deployment type, preconditions, steps, expected outcome, variants, and the
facts code checked about how well the ticket supports them. A ticket without steps or an
expected result gets questions instead.

| Argument / option | What it does |
|---|---|
| `TICKET_FILE` (required) | A normalized ticket (from `normalize`). |
| `--out <dir>` | Output folder. Default: `<output>/drafts`. |

### `retrieve <TICKET_FILE> --repo <path>` `[LLM]`

Finds the code and tests the new test relates to (keyword search, exact names, the code's
structure, follow-up searches) and the template tests whose data can seed the new one.

| Argument / option | What it does |
|---|---|
| `TICKET_FILE` (required) | A normalized ticket. |
| `--repo <path>` (required) | The target repo (indexed on demand). |
| `--draft <file>` | The drafts JSON; its primary draft sharpens the search. |
| `--no-llm` | Code only: no query rewrite or follow-up searches. |
| `--out <path>` | Output file. Default: `<output>/retrieval/<id>.retrieval.json`. |

### `generate <DRAFT_FILE> --retrieval <file>` `[LLM]`

Decides how to reuse the suite (already covered, a new case of a parametrized test, a new method
in an existing class, or a new file), then writes the test and its data, validates it and
repairs it. A new case or method comes out as patched copies of the existing files plus
`changes.patch`; the repo itself is never written.

| Argument / option | What it does |
|---|---|
| `DRAFT_FILE` (required) | The drafts JSON (from `draft`). |
| `--retrieval <file>` (required) | The retrieval JSON (from `retrieve`). |
| `--draft-id <id>` | Which draft (default: the primary one). |
| `--conventions <file>` | A conventions doc (Markdown) to use instead of `generate.conventions_doc`. |
| `--out <dir>` | Output folder. Default: `<output>/generated`. |
| `--as <kind>` | `auto` (default: decided in code), or force `variant`, `method` or `module`. |
| `--coverage-check` / `--no-coverage-check` | As for `run`. |

### `validate <GENERATED_DIR> --repo <path>`

Runs the validators again over generated output (folders with `generated.json`), for example
after you edited a test by hand.

| Argument / option | What it does |
|---|---|
| `GENERATED_DIR` (required) | Output of `generate`. |
| `--repo <path>` (required) | The repo the tests were generated for. |
| `--collect` | Also load the tests with `pytest --collect-only` in the container sandbox. |
| `--run` | Run the tests in the sandbox (not available yet). |

### `results <LOG_FILE> <GENERATED_DIR>`

Reads the console log of a real run (`pytest -v`) after a person ran the generated tests, and
records one verdict per test and case in `generated.json`: passed; environment (the system
couldn't be reached; rerun); test_problem (the test is wrong, e.g. an unknown name or a missing
data key); check_failed (an assertion failed: the bug was caught, or the expectation is wrong);
error (setup or teardown); not_run; unclear.

| Argument | What it does |
|---|---|
| `LOG_FILE` (required) | The console log. |
| `GENERATED_DIR` (required) | Output of `generate`. |

---

## Once per suite (and again when it changes)

### `index [REPO]`

Parses the suite into chunks (tests with their data entries, page objects, helpers, classes),
the symbol catalog (names, page-object chains, test ids) and the keyword index. Cached; only
changed files are read again. Most commands index on demand, so this is mainly for a first run
or a check.

| Argument / option | What it does |
|---|---|
| `REPO` | The repo. Default: `paths.repo`. |
| `--force` | Rebuild from scratch instead of reusing the cache. |

### `check-suite [REPO]`

Calibration: runs every validator over the suite's own tests. They are known-good, so each error
points at a config value to fix or a pattern the tool doesn't know yet. Writes a report.

| Argument / option | What it does |
|---|---|
| `REPO` | The suite. Default: `paths.repo`. |
| `--collect` | Also compare the computed test ids with a sandbox collect. |
| `--out <dir>` | Report folder. Default: `<output>/reports`. |

### `map [REPO]`

The suite map, from the index by code (no model): per area, the classes, setup options, test
shapes, page objects, helpers, data keys and their known values, typical tests.

| Argument / option | What it does |
|---|---|
| `REPO` | The repo. Default: `paths.repo`. |
| `--out <dir>` | Output folder. Default: `<output>/map/<repo folder name>`. |

### `guides [REPO]` `[LLM]`

Writes the area guides and the framework guide, one model call each (the `guide` step's model),
within a dollar budget. Up-to-date guides are skipped. Guides written by a Claude Code session
(`<area>.authored.json`, `docs/guide-authoring-prompt.md`) are never overwritten and are used
first.

| Argument / option | What it does |
|---|---|
| `REPO` | The repo. Default: `paths.repo`. |
| `--estimate` | Show the size and worst-case cost per area; no model calls. |
| `--budget <usd>` | Budget for this run (default and maximum: `guides.max_budget_usd`). |
| `--force` | Rebuild guides that are up to date. |
| `--area <name>` | Only these areas (repeatable). `_framework` is the framework guide. |
| `--out <dir>` | Guides folder. Default: `<output>/guides/<repo folder name>`. |

### `search <QUERY>`

Keyword search over an indexed repo, for checking what the tool can find.

| Argument / option | What it does |
|---|---|
| `QUERY` (required) | Words or identifiers. |
| `--repo <path>` | The indexed repo. Default: `.`. |
| `--top-k <n>` | Number of results. Default: `retrieval.top_k`. |
| `--kind <kind>` | Only `test`, `function`, `class` or `page_object` (repeatable). |

### `sandbox`

Shows the container sandbox used to load generated tests (`pytest --collect-only`, no network,
read-only repo copy).

| Option | What it does |
|---|---|
| `--build` | Build the sandbox image (pulls a public base image). |

---

## Measuring

### `golden <PAIR_SET>` `[LLM]`

The design step's yardstick (`docs/golden-set.md`): runs every golden ticket several times with
its reference test hidden, and scores each run against the reference (placement, helpers called,
data blocks, made-up values, cases, validators, context recall). Reports pass@1 and pass^k per
criterion; writes `c6.csv` (your yes/no) and `open-coding.md` (your notes) next to it.

| Argument / option | What it does |
|---|---|
| `PAIR_SET` (required) | The golden pair-set JSON (private). |
| `--repeat <n>` | Runs per ticket (default 3; capped by `eval.max_golden_repeat`). |
| `--label <name>` | A name for this configuration, e.g. `baseline-0`, `no-guides`. |
| `--collect` | Also load each test in the sandbox. |
| `--pairs <ids>` | Only these pairs, by id (repeatable, or comma-separated: `--pairs g09,g10`), e.g. one failure group while trying a change. |
| `--out <dir>` | Report folder. Default: `<output>/golden`. |

### `golden-rescore <REPORT_FILE> --set <PAIR_SET>`

Scores a finished golden run again from its kept outputs, after a change to the scorer. No model
calls; your C6 answers stay. Rewrites `report.json` and `report.md`.

| Argument / option | What it does |
|---|---|
| `REPORT_FILE` (required) | The run's `report.json`. |
| `--set <file>` (required) | The golden pair set the run used. |

### `golden-report <REPORT_FILE>`

Renders a golden run's report again, with your C6 answers merged in.

| Argument / option | What it does |
|---|---|
| `REPORT_FILE` (required) | The run's `report.json`. |
| `--c6 <file>` | The filled-in `c6.csv`. |

### `eval --set <path>` `[LLM]`

The older eval harness, for the public and stand-in pair sets: retrieval (recall@k, MRR) and
generation (validators, sandbox), with each ticket's linked test hidden.

| Option | What it does |
|---|---|
| `--set <path>` (required) | A pair-set JSON, or a folder of them. |
| `--stage <stage>` | `retrieval` (default), `generation`, or `all`. |
| `--runs <n>` | Retrieval runs per set (1–10). |
| `--k <n>` | Cut-off for recall@k (default: `retrieval.top_k`). |
| `--no-llm` | Code-only retrieval. |
| `--judge` | A model judges each draft against its ticket (unvalidated; one more call). |
| `--no-collect` | Skip the sandbox collect. |
| `--no-leave-one-out` | Keep each ticket's linked test in the index. |
| `--fresh-drafts` | Don't reuse cached drafts. |
| `--out <dir>` | Report folder. Default: `<output>/reports`. |

### `mine [REPO] --out <file>`

Finds ticket ↔ test pairs: commits that removed a skip citing a ticket id, or (`--from-skips`)
skips citing a ticket in the current files when there's no history.

| Argument / option | What it does |
|---|---|
| `REPO` | A git repo (read only). Default: `paths.repo`. |
| `--out <file>` (required) | The pair-set JSON to write. |
| `--name <name>` | The pair set's name. Default: `mined`. |
| `--repo-path <path>` | The indexed checkout for retrieval, relative to the project root. |
| `--jira-export <file>` | A Jira export with the tickets. |
| `--from-skips` | Use skips in the current tree (no git history needed). |

---

## Safety

### `privacy-scan [REPO]`

Checks the files git would commit for the private terms in `security.private_terms`. Run it
before committing to this public repo. Hits name a term by its position in the list, never by its
text.

| Argument | What it does |
|---|---|
| `REPO` | The repo to scan. Default: this one. |

---

## Scripts (outside the CLI)

| Script | What it does |
|---|---|
| `python scripts/to_container.py <container> [--target <path>]` | Copies this project's committed files into a container, replacing the previous copy and keeping its `.scratch`. Only when nothing is running from that copy. |
| `scripts/to-container.cmd` | The same, for Windows. |
| `uv run --frozen python scripts/compare_collect.py <collect file> <repo root> <rootdir>` | Compares a collect run made with the suite's own runner against the tool's computed test ids, file by file (counts and masked shapes only). |
| `python scripts/index_sizes.py <path to index.json>` | Measures the index's size per section (memory investigations). |

---

## Typical sequences

**A ticket:**
```bash
uv run ticket2test new-ticket ABC-123       # then paste the ticket into the file
uv run ticket2test run ABC-123              # read and fix drafts/ABC-123.drafts.json
uv run ticket2test run ABC-123 --continue   # the test in generated/ABC-123_d1/
```

**The same ticket without some tests (as if they didn't exist):**
```bash
uv run ticket2test run ABC-123 --continue --hide <path/to/test_file.py> --hide <path>::<Class>::<test>
```

**After the suite changed:** `index`, then `check-suite` (and `map` and `guides` if you use them).

**The golden set (design step):** see `docs/golden-set.md`.
