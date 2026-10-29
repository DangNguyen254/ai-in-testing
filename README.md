# ticket2test

Turns a bug ticket into **structured draft test cases**, then into **runnable test code**, for a
human QE to review. Generic and company-agnostic: ticket source, codebase, LLM endpoint, and
conventions all sit behind adapters and config. Built and evaluated on public data only.

> Status: Phases 0–8 done, plus the real-suite fit plan (sandbox import settings, mixed and
> legacy suites, import-aware names, risky-pattern warnings) and two bounded agents
> (investigation, missing-piece proposals). Ready for integration with a real suite; see
> `docs/project-overview.md` for the whole flow and `PROJECT_STATUS.md` for the log.

## Quick start

Requires Python 3.11+ and [uv](https://docs.astral.sh/uv/).

```bash
# 1. Install uv (skip if you already have it)
pip install uv            # or see https://docs.astral.sh/uv/getting-started/installation/

# 2. Clone and install (creates .venv/ in the project folder)
git clone <this-repo-url> ticket2test
cd ticket2test
uv sync

# 3. Try it
uv run ticket2test --help

# 4. Run the checks
uv run ruff check .
uv run ruff format --check .
uv run mypy src
uv run pytest
```

### Without uv (plain pip + venv)

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate     macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
pip install -e . --no-deps
ticket2test --help
```

`requirements.txt` is generated from `uv.lock` (runtime + dev deps, pinned). After changing
dependencies in `pyproject.toml`, regenerate it:

```bash
uv lock
uv export --format requirements-txt --no-hashes --no-emit-project -o requirements.txt
```

## Usage

### Normalize a ticket

```bash
# GitHub issue (public repos work without a token; set GITHUB_TOKEN for a higher rate limit)
uv run ticket2test normalize encode/httpx#1498 --out ticket.json
uv run ticket2test normalize https://github.com/encode/httpx/issues/1498

# Jira: read one issue from an exported JSON file (no network)
uv run ticket2test normalize DEMO-101 --jira-export export.json --out ticket.json

# Pasted by hand (when the tracker's API can't be used): write the template, fill it in, read it
uv run ticket2test new-ticket DEMO-101 --dir <private folder>/tickets
uv run ticket2test normalize DEMO-101 --paste <private folder>/tickets --out ticket.json
```

A pasted ticket is one Markdown file with `##` sections, in any order (type, epic, components,
labels, description, steps to reproduce, expected, actual, acceptance criteria, test plan,
attachments, comments, links). Type and epic become labels; acceptance criteria count as the
expected result when there is no expected section. When the steps or
expected result live in a linked test plan, paste that part under `## Test plan`: steps and
expected come from their own sections first, then from the description, then from the test plan.
Attachments are local files listed one per line; `.md`, `.txt` and `.csv` are read, others only
listed. Links are recorded, never opened. Keep the folder private: real tickets never go in the
repo.

### One ticket end to end

```bash
# 1. normalize + draft, then stop so a person reviews the draft (output/drafts/<id>.drafts.md)
uv run ticket2test run DEMO-101 --paste <private folder>/tickets
# 2. after the review: retrieve, generate (validators and repair included), write the test
uv run ticket2test run DEMO-101 --continue --repo <target repo>
```

`--repo` can be left out once `paths.repo` is set in the config, and `--paste` / `--dir` once
`paths.tickets_dir` is (`new-ticket TEST-095`, then `run TEST-095`).

To compare with a test that already exists for the ticket, hide it: `run TEST-095 --continue
--hide <path::Class::test or method name>`. The tool then works on a copy of the repo without that
test and its data entries (in the cache folder; the repo itself is never changed). Each half runs the same steps as
the separate commands below and writes the same files.

Without `--out`, the ticket is written to `output/tickets/<id>.json`. `--raw-out FILE` also saves
the raw source payload. Steps, expected, and actual are extracted by rules (section headings
such as "Steps to reproduce", "Expected behavior", "Actual:"). If a section is missing, the
field is left empty. Nothing is guessed.

### Draft test cases from a ticket

```bash
uv run ticket2test draft ticket.json            # -> output/drafts/<id>.drafts.json + .md
uv run ticket2test draft ticket.json --out drafts/
```

The Markdown file is for human review. If the ticket lacks steps or expected behavior, the
result is `insufficient_info` with a list of what's missing instead of a guessed test.

### LLM providers

Set `llm.provider` in `config.yaml`:

| Provider | Auth | Notes |
|---|---|---|
| `claude_code_cli` (default) | Your Claude Code login | Runs `claude -p` as a plain LLM: all tools, MCP servers, skills and settings files disabled, in `.scratch/claude-cli`. No temperature control. Needs `claude` on PATH, or set `T2T_LLM__CLAUDE_CODE_CLI__EXECUTABLE` to the full path. |
| `claude` | `ANTHROPIC_API_KEY` | Anthropic API. Current models don't accept `temperature`. |
| `gemini` | `GEMINI_API_KEY` | Set `llm.gemini.model` first. Uses `temperature` and `seed`. |

If `ANTHROPIC_API_KEY` is set in the environment, the Claude CLI uses it (API billing) instead
of your subscription login. Full prompts and responses are logged only with `--debug-log`.

### Index and search a repo

```bash
uv run ticket2test index standin                     # parse, chunk, catalog, BM25; cached
uv run ticket2test search "invite user" --repo standin --kind test --top-k 5
```

The index is cached under `.t2t_cache/index/` (git-ignored) and rebuilt incrementally: only
files whose content changed are parsed again (`--force` rebuilds everything). Test chunks
carry their decorators, markers, statically computed pytest ids, and matching JSON data entries;
the symbol catalog includes page-object property chains such as `nav.inventory.items.search`.

### Map a suite

```bash
uv run ticket2test map standin                       # code only, no LLM
```

Writes `output/map/<repo>/`: `overview.md` (areas, base classes, page areas, shared helpers,
marker values), one `areas/<area>.md` per area (test classes with their decorators and setup
options, test shapes, markers, page-object chains and actions, helpers, assertions, data keys
with their role, expectations, placeholders, typical tests), `coverage.md` (test-side code that
nothing references), and `map.json` with everything. Each area records the files it was built
from with their hashes; a rerun reports which areas changed.

### Area guides (one strong-model call per area)

```bash
uv run ticket2test guides standin --estimate          # tokens and worst-case cost; no calls
uv run ticket2test guides standin --budget 5          # write guides, largest areas first
```

Each area gets one call with material the tool picks (the area summary, typical tests with a
data entry, the class scaffold, the page objects and helpers it uses) up to
`guides.max_input_tokens`; the model never explores. Names in the guide are checked against the
index and removed if they don't exist. The model is the `guide` step's (default: the provider's
model, Sonnet 5.5; set `step_models: {guide: claude-opus-5-5}` for Opus). `--budget` can't
exceed `guides.max_budget_usd` (50 by default); before each call the worst case (estimated
input + the full output cap, at `guides.prices`) must fit in what is left. Up-to-date guides
(same area digest, prompt and model) are skipped; `--force` rebuilds. Guides and run reports
go to `output/guides/<repo>/`; the generator puts the ticket's area guide into its context
(`guides.use_in_generation`).

For the public stand-in used in tests: `git clone --depth 1 --branch 0.28.1
https://github.com/encode/httpx .scratch/repos/httpx` (tests that need it skip without it).

### Retrieve code and tests for a ticket

```bash
uv run ticket2test retrieve ticket.json --repo standin --draft drafts/X.drafts.json
uv run ticket2test retrieve ticket.json --repo standin --no-llm      # deterministic only
```

Each hit records why it was retrieved (`bm25`, `grep`, `expansion`, `followup`, `template`).
A deterministic reranker then re-scores candidates and keeps the top k varied (at most 3 chunks
per file, at least 2 tests); each hit records its `rank_features`.
Templates are existing tests whose JSON entries can seed new ones. The LLM may request extra
searches (own search tools only) for at most `retrieval.max_followup_rounds` rounds.

**Investigator** (opt, `retrieval.investigator.enabled: true`; replaces the follow-up rounds):
a bounded agent that explores the index with read-only tools until it has enough context:
`search`, `grep`, `open`, `open_member`, `callers`, `tests_using`, `chain`, `class_hierarchy`,
`list_members`, `data`, `data_entry`. Outputs are cheap first (a large class opens as an outline
of its members; cut lists say how many more results exist and in which folders), every output
is capped, and the run is bounded by turns, calls per turn and transcript size. Kept chunk ids
that don't exist are dropped; the pieces it reports as missing are checked by code.

### Generate a test (code + JSON data)

```bash
uv run --env-file .env ticket2test generate drafts/X.drafts.json --retrieval X.retrieval.json \
    --conventions standin/CONVENTIONS.md --out output/generated
```

Writes `<draft id>/<path>/test_<area>_<action>.py`, its JSON data file, and `generated.json`
(traceability) under the output directory, never into the target repo. The LLM writes the code
and a plan per entry (sections to copy from the nearest existing entry, values to change); the
entries are built from that plan deterministically, keyed by the pytest ids computed from the
code. The result is then validated, and validator errors go back to the LLM for repair (at most
`repair.max_attempts` rounds). The validation report is stored in `generated.json`.

**Reuse first** (`--as auto`, the default). Before writing anything, code decides how the draft
fits the suite, inside the ticket's domain (a folder from `generate.domain_globs`):

- **covered**: an existing test already has the case (e.g. the draft names one of its
  parametrize values); nothing is generated and no LLM is called;
- **out of scope**: the ticket's area is legacy (`generate.reuse.legacy_domains`); only
  "covered" is decided there and nothing is generated;
- **variant**: a new case of an existing parametrized test: the value is appended to its
  parametrize list and an entry cloned from the nearest case goes into its data file. Planned
  in code when the draft's inputs name the data keys they change; otherwise one small LLM
  call (`generate.variant_prompt`);
- **method**: a new test method in an existing class (generated with that class as template,
  then spliced in, with only the imports it needs);
- **module**: a new test file, scaffolded from the domain's closest class.

New methods never go into frozen classes (`generate.reuse.frozen_classes`), into classes gated
to a narrower deployment than the draft, or, for UI tests, into classes that don't use page
objects. A variant that can't be patched falls back to a method, and a method that can't be
spliced is kept as a new module. `decision.json` records the decision and every fallback. Patches are
written as `patched/<path>` copies plus `changes.patch` (never into the target repo), and are
validated whole, reporting only findings the unpatched file doesn't already have.
`--as variant|method|module` forces a kind.

More is done in code, around the one generation call: templates of the draft's **shape**
(UI or API; add, edit, delete or other, words in `retrieval.shape_actions`) rank first after
the component; a new module gets the template class's **shell** (imports, decorators, base
class, setup/teardown) with only the generated test methods spliced in; data keys the test
never reads are removed and a single mislabelled entry is re-keyed without a retry; and
every variant the draft lists must become a case (validator `variants`). With
`style.follow_local` (the default) cosmetic style follows the local file: code added to a file
takes its indent and quotes, a new module its template's, and no existing line is reformatted
(data entries are inserted as text in the file's own JSON style).

**Missing pieces.** After generation, names the test needed that the suite lacks (in the final
code, in any repair attempt, or among the investigator's hints) are checked against the
catalog and written to `missing_pieces.json`; each real gap adds a reviewer-checklist note.
With `proposals.enabled: true` (opt), the model writes each missing member of an existing
page-object or helper class; code checks that nothing existing changed, the name and kind match
the use, only existing names are used and (in the sandbox) the suite still loads, then keeps it
as `proposal_<member>.diff` (never applied). With `proposals.regenerate` the test is generated
again using the accepted members, and its checklist names the patch to apply first.

### Check the config against an existing suite

```bash
uv run ticket2test check-suite standin                 # validators over the suite's own tests
uv run ticket2test check-suite standin --collect       # + static ids vs. a sandbox collect
```

The suite's own tests are known-good, so every validator error on them points at a config
value that doesn't describe the suite. Errors are grouped by check with the config keys to look
at (e.g. `markers` → `markers.priorities`, `style` → `style.python`). Run it first when
pointing the tool at a new suite, and rerun until it reports "clean". Older code that breaks a
correctness rule (`validation.deviation_checks`: raw driver, page locators, pages built by
constructors, star imports) is listed per area as a **deviation**, not an error; legacy areas
are skipped. With `--collect`, every module that fails to import is named with its error.

### Validate generated tests, and collect them in a sandbox

```bash
uv run ticket2test validate output/generated --repo standin
uv run ticket2test sandbox --build                 # once: builds the container image
uv run ticket2test validate output/generated --repo standin --collect
```

The validators are deterministic and never run the code. **Errors** block a test: invented
names or page-object chains, unresolved imports, data keys and ids that don't match the code,
missing or unapproved markers, style, literal or too-long seeded names, unread data keys.
**Warnings** are heuristics for the reviewer: checks that don't cover what the docstring or
draft claims (e.g. "only allow rules" checked only by a count), unused capability gates, and
page arithmetic without a page-size read.

`--collect` runs `pytest --collect-only` on each generated module inside a container (Docker or
Podman, `sandbox.runtime`): no network, read-only root file system, no capabilities, the
target repo mounted read-only, and one writable staging folder under `.scratch/sandbox/`. If
the runtime or the image is missing, the command fails; it never falls back to the host.
The image is built from `sandbox.base_image` (default: the public `python:3.12-slim`) and the
requirements file `sandbox.requirements` (default: pytest and selenium, pinned). For a real
suite, point `sandbox.requirements` at the suite's own test requirements. Runs never pull an
image, and the runtime gets an empty credentials file, so your registry logins and credential
helpers are never used (set `sandbox.registry_auth: true` if the base image's registry needs a
login).

Suites that do things at import time (read environment variables or host files, write files,
need secrets) need private sandbox settings: `sandbox.env` (non-secret variables; names that
look like secrets are refused), `sandbox.stub_dir` (stand-in modules copied into the staging
folder; a small pytest plugin makes them win over the suite's own import path, for a top-level
module or one module inside a real package), `sandbox.extra_paths` and `sandbox.collect_ignore`.
Still only two mounts: the repo, read-only, and the staging folder.

### Record a real run's results

```bash
uv run ticket2test results run.log output/generated
```

ticket2test never runs generated tests outside the sandbox. Run them with the suite's own
runner, save its console output (pytest `-v`, with or without `-s`), and pass it here. Each
`generated.json` gets a `run_report`: its results (one per class variant and case), the
error lines, session links (`results.link_pattern`), and a verdict: `passed`,
`test_problem` (the test itself is wrong: `results.test_problem_errors`), `check_failed`
(an assertion failed: the bug, or a wrong expectation; open the link), `error` (setup or
teardown), `not_run`, or `unclear`. Reports stay in the git-ignored output folder.

### Evaluate

```bash
uv run ticket2test eval --set eval_data --no-llm                      # retrieval, deterministic
uv run ticket2test eval --set eval_data --stage all --judge           # + generation + LLM judge
uv run ticket2test mine .scratch/standin-history --out eval_data/standin_mined.json \
    --name standin-mined --repo-path standin --jira-export standin/tickets/export.json
```

`--set` takes one pair set or the whole `eval_data/` folder. One report per run (JSON +
Markdown) goes to `output/reports/`:

- **Retrieval** (every set): recall@k and MRR; `--runs N` repeats the run to show the spread
  of the LLM steps (deterministic runs are identical).
- **Generation** (the set marked `"generation": true`, i.e. the stand-in): per ticket, draft →
  retrieve → generate + repair → validate → `pytest --collect-only` in the sandbox. Leave-one-out
  by default (the ticket's own linked test is removed from the index). Measures the validator
  pass rate on the first attempt and after repair, the invented-name rate, the collect pass
  rate, repair rounds, LLM calls, and time. Drafts are cached between runs (`--fresh-drafts`
  to redo them); the report flags cached drafts.
- **LLM judge** (`--judge`, one extra call per ticket): does the draft match the ticket? Kept in
  its own UNVALIDATED section until checked against human labels.

Pairs: public httpx issues with their fix PRs (ground truth: the PR's changed Python files,
fetched from GitHub on first use and cached in `.t2t_cache/`), the stand-in's fake tickets with
their linked tests, and pairs mined from git history by `mine` (commits that remove a skip
citing a ticket id; read-only; `--from-skips` reads skips in the current tree when there is no
history). A pair may expect another outcome than a test: a reported gap (`"expect": "gap"`), a
vague ticket (`insufficient_info`) or a legacy area (`out_of_scope`); the report says whether
each was met, and the dollar cost per ticket.

## Stand-in suite

`standin/` is a synthetic target suite (invented names only) that mirrors the target test
style: page objects, a base test class, markers, and a JSON data file per test file. See
`standin/README.md`. `uv run pytest` checks it with `pytest --collect-only` (no browser needed).
Since v7 it also has a mixed area with older code and a legacy area whose module needs runtime
settings at import (`STANDIN_RUNTIME_ROOT`; the sandbox uses `standin/sandbox/stubs`).

## Running it inside a container

When the target suite lives in a container, copy this project's last commit into it and
run the tool there (the copy replaces the previous one; only committed files go):

```bash
scripts	o-container.cmd <container>                      # Windows, from this folder
python scripts/to_container.py <container> --target /root/work/ai-prj
```

The target folder must be named `ai-prj` (or `ai-prj-<something>`), so the removal can never
hit another folder. Inside the container, keep the virtual environment, the uv cache and every
output outside the copy (`UV_PROJECT_ENVIRONMENT`, `UV_CACHE_DIR`, and `paths.*` in the private
config), and run the tool with `uv run --frozen ticket2test ...`. If the suite runs on an older
Python, set `style.python.target_version` (e.g. `"3.8"`): generated code must then parse with
that version's grammar, and the formatter targets it.

## Configuration

Settings live in `config.yaml`. Any value can be overridden with an env var
`T2T_<SECTION>__<KEY>`:

```bash
T2T_RETRIEVAL__TOP_K=5 uv run ticket2test ...
```

Use `--config path.yaml` or `T2T_CONFIG=path.yaml` to point at another file.

Secrets (API tokens) are **never** in `config.yaml`. Copy `.env.example` to `.env` (git-ignored),
fill it in, and load it with `uv run --env-file .env ticket2test ...`.
Write Windows paths in `.env` with forward slashes (`C:/path/to/claude.exe`): uv's `.env`
parser treats backslashes in unquoted values as escapes.

`uv` is also a dev dependency, so after the first `uv sync` an activated venv has its own `uv`.
If `uv` isn't on PATH at all, `py -m uv ...` works when uv was installed with `pip install uv`.

## Tests

- `uv run pytest` runs unit tests only. The LLM is always mocked (`FakeLLMClient`).
- Tests that hit real services are marked `@pytest.mark.live` and run only with
  `uv run pytest -m live` (GitHub API, and real LLM calls with the configured provider).
- Tests that start a real container are marked `@pytest.mark.sandbox` and run only with
  `uv run pytest -m sandbox` (needs the runtime and the image; set `T2T_SANDBOX__RUNTIME=podman`
  for Podman).

## Safety

- Generated tests are untrusted and run only inside a network-less container, never on the host.
- Target repos are read-only. The pipeline writes only to its own output directory.
- Full prompts/responses are logged only with `--debug-log`, to a git-ignored directory.
- Prompt-injection payloads (in tickets, test data, code) never reach the LLM: every request is
  masked (`security.masking`: instruction-like phrasing, and the values of configured data keys
  become `[[PAYLOAD_n]]` tokens with a short legend), and the originals are restored in the
  structured result by code. Leftover tokens are a validator error; new instruction-like text
  in generated output is a reviewer warning.
- Private terms (`security.private_terms`: case-insensitive regexes for company, product or
  customer names, internal hosts) are set only in the private config or
  `T2T_SECURITY__PRIVATE_TERMS` (a JSON list). Every LLM request has them redacted to
  `[PRIVATE]` (outermost wrapper); generated output containing one is a validator error; and
  `ticket2test privacy-scan` checks the files git would commit before you commit. Reports
  name a term by its position (`term #2`), never by its text.

## License

MIT. See `LICENSE`.
