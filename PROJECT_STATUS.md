# PROJECT_STATUS.md

Tracks progress, scope, and acceptance criteria for each phase. Read together with `CLAUDE.md`, whose hard constraints and guardrails apply to **every** phase.

**How to use this file (for Claude Code):**
- Before starting a phase, check that the previous phase is `✅ Done`.
- Update the phase's status, checklist, and log when you start, pause, or finish.
- A phase is `✅ Done` only when **every** Definition of Done (DoD) item is checked.
- Put anything unresolved under **Open questions** and stop for the human to answer.

**Status legend:** ⬜ Not started · 🟡 In progress · ⏸️ Blocked or paused · ✅ Done

---

## Overview

| Phase | Name | Status | Depends on |
|---|---|---|---|
| 0 | Skeleton | ✅ (models extended, see notes) | – |
| 1 | Ticket normalizer | ✅ | 0 |
| 2 | Draft generation | ✅ | 1 |
| 3 | Synthetic stand-in repo | ✅ | 0 |
| 3b | Stand-in v2/v3 (real-framework patterns) | ✅ | 3 |
| 4 | Indexer (Python) | ✅ | 3 |
| 5 | Retrieval | ✅ | 2, 4 |
| 6 | Code generation (code + JSON pair) | ✅ (real-codebase style check deferred to integration) | 5, 3b |
| 7 | Validators, repair, sandbox | ✅ | 6 |
| 8 | Eval harness | ✅ | 5 (minimal), 7 (full) |
| 9 | Rust support | ⬜ | 8 |

Phases run strictly in order (CLAUDE.md rule). Renumbered on 2026-10-05: the synthetic stand-in became Phase 3; former Phases 3–8 are now 4–9.

---

## Current state (handoff, 2026-10-06)

Read this first when resuming in a new session.

**Where we are:** Phases 0–8 are ✅. The baseline eval report is `output/reports/phase8/eval-20261006T102640.md` (summary in the Phase 8 log). Phase 9 (Rust) is marked "later" in `CLAUDE.md`; **ask the human before starting it**.

**Decision (2026-10-06, human):** keep LLM use to a minimum. No LLM reviewer step: semantic gaps are handled by a stronger generation prompt and by deterministic heuristics (Phase 7 warnings). Sonnet 5.5 for every LLM step (the Haiku trial for retrieval was worse). Latency and pricing evals come later (calls and time are already recorded).

**Next steps (for the human to choose):**
1. Phase 9 (Rust support), or skip it for now.
2. Hand-label the 12 LLM-judge verdicts in the baseline report to validate the judge (it marks default metadata such as `deployment_type: both` as "unsupported").
3. Port to the company environment: `docs/porting-checklist.md`. The order: approvals → install → private config (`T2T_CONFIG`) → `index` → `sandbox --build` with the suite's requirements → **`check-suite <repo> --collect` until clean** → conventions doc → one ticket end to end → the real-codebase style check deferred from Phase 6 → `mine` + eval baseline.

**Known open points (not blocking):**
- Template choice: STND-106 used `test_rules_add_basic[allow]` as the base instead of a list or pagination test. Ranking is same component first, then the retrieval score.
- Retrieval without the LLM misses STND-104 (recall@10 0.833 on the stand-in); with the LLM it was found before.
- The stand-in is too easy to separate configurations: the baseline scores 12/12 on every generation metric. Real discrimination needs the real codebase (or a harder stand-in).

**How to run (Windows, from the repo root):**
- Checks: `.venv/Scripts/ruff.exe check .`, `.venv/Scripts/python.exe -m mypy src`, `.venv/Scripts/python.exe -m pytest -q` (basetemp is `.scratch/pytest`, set in `pyproject.toml`).
- Live generation (real LLM calls via the Claude Code CLI, about 15 calls, about 2.5 minutes): `.venv/Scripts/uv.exe run --env-file .env pytest -m live tests/test_generate_live.py -q`. It writes to `output/generated/live-<prompt version>/`.
- Stand-in: `cd standin && ../.venv/Scripts/python.exe -m pytest --collect-only -q`; history: `python standin/tools/build_history.py --out .scratch/standin-history --force`.
- `uv` is installed in the venv (`.venv/Scripts/uv.exe`).
- Validate generated tests: `.venv/Scripts/ticket2test.exe validate output/generated/live-v4 --repo standin` (add `--collect` for the sandbox).
- Sandbox: Podman runs here (Docker's daemon doesn't), so set `T2T_SANDBOX__RUNTIME=podman`. The image `t2t-sandbox:py3.12` is built (`ticket2test sandbox --build`, approved by the human on 2026-10-06: public `python:3.12-slim` + pytest/selenium from PyPI). Real-container tests: `T2T_SANDBOX__RUNTIME=podman .venv/Scripts/python.exe -m pytest -m sandbox`.
- The machine's Podman store also holds an unrelated image from a private registry. Never use or reference it (Hard Constraint 1); the sandbox uses only its own image.
- This machine's container setup has a registry credential helper whose login can expire; Podman then fails even for local images. The sandbox now passes an empty credentials file on every runtime call (`sandbox.registry_auth: false`), so it doesn't depend on it. Never touch the developer's registry or cloud logins.
- Calibration: `.venv/Scripts/ticket2test.exe check-suite standin --collect` (stand-in: clean, 36/36 ids match).

**Working notes for Claude Code:**
- **Rules:**
  - Never read `.env`; `uv run --env-file .env` loads it. It holds the `claude` CLI path (forward slashes).
  - Commit locally with the repo-local identity (DangNguyen254). Never `git push` without the human's explicit OK. There are local commits not yet pushed.
  - No Claude co-author trailers or "Generated with Claude Code" lines (CLAUDE.md).
- **Tooling pitfalls:**
  - Env overrides of dict settings are deep-merged with `config.yaml`: `T2T_LLM__CLAUDE_CODE_CLI__STEP_MODELS='{}'` changes nothing; set each key explicitly. Check the report header (`Models:`) after an eval.
  - Bash heredocs mangle `\n` and `\b` in Python snippets: write scripts to `.scratch/*.py` with the editor tools instead.
  - Git object files are read-only on Windows (`build_history.py` handles this).
- **Stand-in conventions:** the stand-in has its own `standin/ruff.toml` (3-space indent). Its JSON data is written with indent 3 and `"key":value`; the throwaway builders in `.scratch/` are not part of the repo.

---

## Phase 0: Skeleton
**Status:** ✅ Done

**Goal:** A clean, runnable project foundation that every later phase plugs into.

**Inputs:** None.

**Outputs:**
- Project layout as defined in `CLAUDE.md`
- `pyproject.toml` (uv), `config.yaml`, `.env.example`, `.gitignore`, `LICENSE` (MIT), `README.md`
- Interfaces: `TicketSource`, `RepoSource`, `LLMClient` (abstract base classes or Protocols)
- Config loader (Pydantic settings: YAML + env vars)
- CLI entry point `ticket2test` with placeholder subcommands: `normalize`, `draft`, `index`, `retrieve`, `generate`, `validate`, `eval`
- A `FakeLLMClient` for tests (returns canned responses)

**Constraints:**
- No real LLM provider implementation yet, only the interface and the fake
- `.env` and any cache/output/debug dirs must be git-ignored
- No dependencies beyond: pydantic, pydantic-settings, typer, pyyaml, httpx, pytest, ruff, mypy

**Definition of Done:**
- [x] `uv run ticket2test --help` lists all subcommands
- [x] `uv run ruff check .`, `uv run mypy src`, and `uv run pytest` all pass
- [x] Config loads from `config.yaml`, and env vars override it (tested)
- [x] README has a quick start that works from a fresh clone in under 5 minutes
- [x] No secrets or placeholder real keys anywhere in the repo

**Open questions:**
- Indirect dependencies that are not MIT/BSD/Apache (all pulled in by pre-approved packages): `certifi` MPL-2.0 (via httpx), `pathspec` MPL-2.0 (via mypy, dev only), `shellingham` ISC (via typer), `typing_extensions` PSF-2.0 (via pydantic). All are permissive or weak-copyleft and used unmodified; flagged for the company dependency review. **Resolved 2026-10-05: accepted by the human.**

**Model changes after completion (2026-10-05):** additive only; no existing behavior changes.
- `LLMRequest` gains optional `json_schema`; `LLMResponse` gains optional `cost_usd` (done in the uncommitted Phase 2 work).
- `Settings` gains `llm.*` provider sections and `draft.*` (done in the uncommitted Phase 2 work). The `llm.model` key moved into per-provider sections, and `llm.provider` became a fixed set (`claude_code_cli` | `claude` | `gemini`).
- Later phases will add config sections for markers (required markers, allowed values), data-file naming, the stand-in path, and git-history mining (ticket-id regex). All additive.
- `RepoSource` stays unchanged. Git history mining gets its own read-only adapter in `adapters/repo/`, so `tests/test_interfaces.py::test_repo_source_has_no_write_methods` stays valid.
- Code to update when work resumes: `tests/test_config.py` for the new sections (the defaults test still holds). The `cli.py` subcommand list is unchanged.

**Log:**
- 2026-10-05: Started. Decisions: phases run strictly in order (CLAUDE.md rule wins over the "Phase 3 in parallel" note); `search` placeholder added to the CLI now; `types-PyYAML` (Apache-2.0) added as a dev dep for strict mypy; build backend `uv_build`.
- 2026-10-05: Built the skeleton: package layout per CLAUDE.md, `config.py` (pydantic-settings; defaults < `config.yaml` < `T2T_*` env vars; caps validated, unknown keys rejected, `sandbox.runtime` limited to docker/podman), ABC interfaces `TicketSource` (returns `RawTicket`), `RepoSource` (read-only), `LLMClient` + `FakeLLMClient`, typer CLI with `--config`, `--debug-log`, `--version` and 8 placeholder subcommands. `.venv/` in-project via `uv sync`; `requirements.txt` exported from `uv.lock`.
- 2026-10-05: Verified. ruff check + format, mypy strict (21 files), pytest 54 passed. Repo-hygiene tests: secret-pattern scan (with self-test on fake samples), `.env.example` placeholders only, `.gitignore` coverage, provider SDK imports only in `llm/`. Fresh-clone simulation (`git checkout-index` to a scratch dir, uv cache disabled): `uv sync` → help → ruff → mypy → pytest in 109 s. Done.

---

## Phase 1: Ticket normalizer
**Status:** ✅ Done

**Goal:** Turn raw tickets from any source into one clean `Ticket` object, so the rest of the pipeline never depends on the source.

**Inputs:**
- GitHub issue reference (`owner/repo#number`) via the GitHub REST API
- Jira-exported JSON file (stub adapter, for future use)

**Outputs:**
- `Ticket` model (fields per `CLAUDE.md`)
- `adapters/tickets/github.py`, `adapters/tickets/jira.py` (file-based stub)
- `normalize/` module: rich text and Markdown → plain text; extracts steps to reproduce, expected, and actual when present
- CLI: `ticket2test normalize <ref> --out ticket.json`

**Constraints:**
- GitHub token is optional and read from env only. Handle rate limits with clear errors.
- The Jira stub never makes network calls. It reads a local file only.
- Extraction of steps/expected/actual is rule-based in this phase (headings, keywords). No LLM yet.
- Missing fields become `None` or empty lists, never invented text.

**Definition of Done:**
- [x] 5 real public `httpx` issues saved as fixtures (raw API JSON) and normalized correctly in tests
- [x] A Jira-style sample JSON (hand-written, fake data) normalizes correctly
- [x] Unit tests cover: missing description, no steps section, very long comment threads
- [x] Unit tests make no live network calls (fixtures only; live test marked `@pytest.mark.live`)

**Open questions:**
- GitHub has no "components" field. `Ticket.components` stays empty for GitHub unless `tickets.github.component_label_prefixes` is configured (e.g. `["component:"]`). httpx labels like `proxies` or `http/2` are not treated as components. Phase 2's insufficient-info check must therefore not rely on `components` alone for GitHub tickets. **Resolved 2026-10-05:** the LLM infers the component from ticket text (labels as hints); if it can't, `component: "unknown"` with lowered confidence. Not a reason for `insufficient_info`.

**Model changes after completion (2026-10-05):** none. `Ticket` is unchanged by the scope update. Ticket ids found in test skip reasons are handled by the eval miner (Phase 8), not the normalizer.

**Log:**
- 2026-10-05: Started. Fixtures: `encode/httpx` #2985 (no sections, no comments), #1482 (full template), #1498 (code steps, multi-paragraph expected/actual), #1234 (free-form, no sections), #914 (open, 43 comments, external links). Saved as raw `issue.json` + `comments.json` under `tests/fixtures/github/`.
- 2026-10-05: Built. `Ticket`/`Comment`/`SourceInfo` models (`Ticket` adds `comments_omitted`; `source` is `{system, ref, url}`). `GitHubIssueSource` (httpx; optional `GITHUB_TOKEN`; comment pagination capped by `tickets.github.max_comment_pages`; clear errors for rate limit with reset time/retry-after, 404/410, 401, PRs, network). `JiraExportSource` (local file only; single issue, `{"issues": [...]}`, or list). Normalizer: ADF and wiki markup → Markdown → plain text; HTML template comments and markup stripped; fenced code kept verbatim; steps/expected/actual from headings, bold lines, and `Label:` lines, ignoring code; links from prose URLs and `#123` refs (not code or inline code). Long threads keep first + latest comments up to `normalize.max_comments` (50); each comment capped at `normalize.max_comment_chars` (4000) on a line boundary. Optional Jira `field_map` for custom steps/expected/actual fields. CLI `normalize <ref> [--jira-export F] [--out F] [--raw-out F]`. New config sections `tickets.github`, `tickets.jira`, `normalize` (additive to the Phase 0 `Settings`). Approved by the human on 2026-10-05, along with keeping code fences in plain-text output.
- 2026-10-05: Verified. ruff check + format, mypy strict (28 files), pytest 147 passed (1 live deselected). Autouse fixture blocks sockets in all non-live tests (with its own test). Live test (`pytest -m live`) passed against the real API, and `ticket2test normalize https://github.com/encode/httpx/issues/1498` gives the same result as the fixture. Done.

---

## Phase 2: Draft generation
**Status:** ✅ Done (2026-10-05)

**Goal:** Turn a `Ticket` into structured `TestCaseDraft`(s) a QE can review before any code is written.

**Inputs:** `Ticket` (from Phase 1).

**Outputs:**
- `TestCaseDraft` model (fields per `CLAUDE.md`, incl. `markers` {priority, component, suite}, `test_kind` (ui | api | hybrid), `deployment_type` (cloud | on_prem | both))
- `LLMClient` implementations: `claude_code_cli` (default; `claude -p --output-format json --json-schema`, all tools disabled), `claude` (Anthropic API), `gemini` (model ID config-only, to be provided)
- `prompts/draft_v1.md`
- `draft/` module with structured output, JSON validation, and retry-with-error
- Secret scrubber in `security/`, applied to all prompt input and to the output
- Markdown renderer for human review
- CLI: `ticket2test draft ticket.json --out drafts/`

**Constraints:**
- Temperature 0 where the provider supports it (Gemini). The Claude CLI has no temperature setting, and current Claude models reject non-default values, so Claude runs are best-effort.
- Max JSON retries from config (default 2); then fail with a clear error
- Must return `status: "insufficient_info"` with `missing_info[]` when the ticket lacks steps or expected behavior
- Component: inferred by the LLM from ticket text, using labels as hints. If it can't be inferred, `component: "unknown"` and confidence capped at 0.5 (`draft.unknown_component_max_confidence`). Never `insufficient_info` for that alone.
- `test_kind` and `deployment_type` come from the ticket. Defaults when the ticket doesn't say: `deployment_type: "both"`, and `test_kind` inferred from the steps (browser actions → `ui`, API calls only → `api`, both → `hybrid`).
- `markers.priority`: one of `markers.priorities` from config (generic placeholders `p0`–`p3`). `markers.suite`: one of `markers.suites` from config (placeholders `smoke`, `regression`), or `"unknown"` if it can't be determined. Real values are set later in the company environment.
- LLM providers: Claude and Gemini, both behind `LLMClient`, selected via config
- Each draft records its `prompt_version`
- One ticket may produce 1 primary draft (reproduce + verify fix) plus 0–3 edge-case drafts. No more.

**Definition of Done:**
- [x] Runs end-to-end on the 5 fixture tickets (live test, run by the human; default provider `claude_code_cli`)
- [x] A deliberately vague ticket returns `insufficient_info`
- [x] Malformed LLM output triggers a retry and then a clean failure (tested with the fake LLM)
- [x] Secret scrubber has unit tests for at least: API-key-like strings, bearer tokens, passwords in URLs
- [x] Drafts include `markers`, `test_kind`, and `deployment_type` (schema-tested)
- [x] Markdown output is readable by a non-engineer (checked by a human)

**Open questions:**
- The `httpx` fixture tickets are library bugs, so their drafts will be `test_kind: "api"`. UI drafts get exercised by the stand-in's fake tickets once Phase 3 exists. Is that OK for this phase's DoD? **Resolved 2026-10-05:** yes.
- Prompt improvement for a future `draft_v2`: in the #1498 review, a precondition said "Install httpx 0.17.0 or the latest version with the fix", but 0.17.0 is the version where the bug appeared. Add a rule against citing versions unless the ticket makes them essential. Not blocking.

**Log:**
- 2026-10-05: Decisions from the human: SDKs `anthropic` (MIT) and `google-genai` (Apache-2.0) approved; default model `claude-sonnet-5-5`; Gemini model config-only (ID to be provided later); new `claude_code_cli` provider as the default (no API key available); unknown-component confidence cap 0.5; live tests run by the human.
- 2026-10-05: Claude CLI probe (one tiny call). `apiKeySource: "none"` (subscription login, no API key in the environment). Only the internal `StructuredOutput` tool was available (no file/shell/web tools, no MCP, no slash commands). Structured result arrives in `structured_output`. The CLI also made a small internal Haiku call. `--bare` is **not** usable: it forces API-key auth. Where the usage is billed still needs the human to check on their account dashboard.
- 2026-10-05: Built (uncommitted, paused): config `llm.*` / `draft.*` sections; `LLMRequest.json_schema`; `llm/schema.py` (provider-safe JSON schema), `llm/structured.py` (capped retry-with-error), `llm/claude_code_cli.py`, `llm/claude_api.py`, `llm/gemini.py`, `llm/factory.py`, `llm/debug.py` (`--debug-log` only); `security/scrubber.py`; `models/draft.py` (first version); `prompts.py` loader; `prompts/draft_v1.md` (first version). `.env.example` provider keys are commented out so a placeholder `ANTHROPIC_API_KEY` can't switch the CLI to API billing. Dependencies added: `anthropic`, `google-genai` (+ transitive; all MIT/BSD/Apache, `cffi` MIT-0). Not yet run through ruff/mypy/pytest.
- Code to update when resuming (scope change): `models/draft.py` (add `markers`, `test_kind`, `deployment_type`; move `priority`/`component` into `markers`); `prompts/draft_v1.md` (new fields; edit in place since it was never released); the draft generator, Markdown renderer, CLI command, and tests (not written yet). **Done 2026-10-05 (see next entry).**
- 2026-10-05: Resumed and finished the build (uncommitted, awaiting human review). Config: `markers` (placeholders `P0`–`P3`, `smoke`/`regression`, `example-project`, required markers) and `eval.ticket_id_pattern` (Jira-style regex). `models/draft.py`: `DraftMarkers` {priority, component, suite} validated against config via a Pydantic validation context; `test_kind`, `deployment_type`; `DraftResult` wrapper holds status/missing_info (so `insufficient_info` needs no empty draft). `draft/generator.py`: deterministic precheck (no description and no steps/expected → `insufficient_info` without an LLM call); ticket JSON scrubbed before the prompt; comment budget `draft.max_comment_chars`; provider-safe schema with config marker values as enums; capped retry-with-error; output scrubbed; unknown component → `"unknown"` + confidence cap 0.5; primary draft first; ids `<ticket>/dN`. `draft/render.py`: Markdown for non-engineers. CLI `draft <ticket.json> [--out DIR]` writes `<id>.drafts.json` + `<id>.drafts.md`. CLI placeholder help updated to the new phase numbers. README: draft usage + provider table. `requirements.txt` regenerated.
- 2026-10-05: Verified (offline). ruff check + format, mypy strict (40 files), pytest 234 passed, 7 live deselected. Tests cover: CLI provider args (tools/MCP/skills/settings off, no `--bare`, prompt via stdin, isolated workdir, timeout, errors, VS Code binary fallback, API-key billing warning), Claude API request shape (structured output, fallbacks, no temperature/seed), Gemini request shape (temperature, seed, JSON schema), retry cap, scrubber (incl. no false positives on normal code), draft ok/insufficient/precheck paths, invalid marker values and draft counts trigger retries, secrets removed from prompt and output, Markdown, CLI. The CLI resolves to the bundled VS Code `claude.exe` on this machine. **Not yet run:** the live draft tests (`uv run pytest -m live`), left for the human as agreed. Known noise: a `DeprecationWarning` from `google-genai` on Python 3.14 (third-party).
- 2026-10-05: Hard Constraint 9 applied. pytest temp → `.scratch/pytest` (`--basetemp`), uv cache → `.scratch/uv-cache` (`[tool.uv] cache-dir`), CLI provider workdir → `.scratch/claude-cli` (config `llm.claude_code_cli.workdir`). VS Code binary lookup removed; the binary comes from `llm.claude_code_cli.executable` (PATH name or full path via env). Repo secret scan skips `.scratch/`. Re-verified: ruff, mypy strict (40 files), pytest 234 passed, 7 live deselected. One real CLI call (via the provider class, from Python) with a canary `CLAUDE.md` in a parent folder of the workdir: the model reported no project instructions and did not return the canary codeword, so parent `CLAUDE.md` files are not loaded with these flags (single sample).
- 2026-10-05: Live run by the human (`uv run --env-file .env pytest -m live -v`): 7 passed in 116 s (5 fixture tickets, vague ticket → `insufficient_info`, GitHub fetch). Two setup bugs fixed first: the autouse conftest fixture stripped `T2T_*` env vars from live tests too (live tests are now exempt); and uv's `.env` parser rejected a backslash Windows path (use forward slashes). `uv` added as a dev dependency so an activated venv has it. Remaining: Markdown readability review and the billing check (both by the human).
- 2026-10-05: Markdown review by the human: `encode/httpx#1498` (1 primary + 2 edge-case drafts; edge-case values traced to the ticket's comments) and the vague `DEMO-900` (`insufficient_info`, both items missing) judged readable. Billing check by the human: no usage on the Claude Console (API), so the CLI calls appear to count against the Pro subscription; Pro usage can't be broken down far enough to confirm. Consistent with the probe's `apiKeySource: "none"`. Every DoD item checked. Done.

---

## Phase 3: Synthetic stand-in repo
**Status:** ✅ Done (2026-10-05)

**Goal:** A small, invented target repo that follows the target test-suite patterns (see `CLAUDE.md`), so the indexer, generator, validators, and eval can be built against the real shape without private data.

**Inputs:** The generic patterns in `CLAUDE.md` → "Target test-suite patterns".

**Outputs (all under `standin/`):**
- `app/`: a tiny fake web app (a few HTML pages + a small JSON API + in-memory backend state that tests can seed and check)
- Framework layer:
  - base test class (setup/teardown: driver, config, cleanup, failure artifacts)
  - page-object hierarchy reached through property chains (`nav.<area>.<page>`)
  - shared helpers and validation methods, mixins
  - decorators: retry, per-browser skip, deployment-type skip (cloud-only / on-prem-only)
  - a name-generator helper with a placeholder token
  - a data loader that resolves a test's JSON entry by its pytest-generated id
- `tests/<area>/`: one class/file per feature area, each with a matching JSON data file
  - markers for priority, project, component, and suite
  - stacked `parametrize` (so the bottom-first id order matters); one JSON entry per variant
  - entries with seed state, expected backend results, and inputs; large config blocks repeated across entries; placeholder names; per-entry priority override and skip by ticket id
  - mix: ~85–90% UI tests, at least one pure API test, at least one hybrid
- Fake tickets for the stand-in (hand-written; generic names) linked to specific tests
- A script that builds a throwaway git history for the stand-in (in a git-ignored cache dir) with at least one ticket-id skip added and later removed by a "fix" commit, for eval mining

**Constraints:**
- Invented, generic names only. No real company, product, URL, or internal tool names; hosts are `localhost` / `example.com`.
- Collectable with `pytest --collect-only` without a browser and without network
- The pipeline treats `standin/` as a target repo: read-only, indexed from a copy when sandboxed
- Hand-written stand-in code is trusted project code: this project's unit tests may run `pytest --collect-only` on it on the host. Generated tests for it still run only in the sandbox (Hard Constraint 3).
- Minimal dependencies; anything new (e.g. a browser-automation library) needs approval first

**Definition of Done:**
- [x] At least 4 feature areas and 20 tests, with the UI/API/hybrid mix above
- [x] `pytest --collect-only` on the stand-in succeeds with no browser and no network
- [x] Every JSON data file's keys exactly match the collected test ids (checked by a project test), including a stacked-parametrize case
- [x] At least one entry overrides priority and at least one is skipped by ticket id; at least one test is deployment-type skipped
- [x] At least 5 fake tickets mapped to tests, and the scripted git history contains a skip-removal fix
- [x] Human review: all names are generic and invented

**Open questions:**
- Browser automation in the stand-in: depend on `selenium` (Apache-2.0) so imports look like the real target, or use a small fake driver interface with no new dependency? **Resolved 2026-10-05:** use `selenium` (approved dependency for the stand-in). Collecting tests doesn't launch a browser.
- Fake web app: stdlib `http.server` (no new dependency) is the proposal. OK? **Resolved 2026-10-05:** yes.
- Can this project's own unit tests run `pytest --collect-only` on the hand-written stand-in on the host? It's trusted code, not generated. Generated tests always use the sandbox. **Resolved 2026-10-05:** yes, for the hand-written stand-in only. Generated tests always go through the sandbox.

**Log:**
- 2026-10-05: Started. `selenium` 4.50 added as a dev dependency (approved for the stand-in; Apache-2.0; transitive deps MIT/BSD/Apache, plus the already-accepted `certifi` MPL-2.0).
- 2026-10-05: Built `standin/`: stdlib `http.server` fake app (inventory, users, orders, settings; HTML pages with stable element ids + JSON API with seed/reset); framework layer (`BaseTest` with data entry, backend reset+seed, lazy browser, failure artifacts, cleanup; page objects via `nav.<area>.<page>`; API client; `ValidationMixin`; `retry`, `skip_browser`, `cloud_only`, `on_prem_only`; `{{unique}}` placeholder + name generator; data loader keyed by pytest test name); 4 test classes with 22 functions / 31 ids (19 UI, 2 API, 1 hybrid = 86% UI), markers priority/project/component/suite, stacked parametrize; 4 JSON data files with a repeated large `config` block; `tests/conftest.py` applies per-entry priority overrides and ticket skips at collection; 6 fake tickets (`STND-101`..`106`, Jira export shape); `manifest.json` (test kinds, ticket → tests); `tools/build_history.py` (3 commits: suite with two ticket skips, then one fix commit per ticket removing its skip; fixed author/dates; final tree = `standin/`). STND-105 is a deliberate open bug, still skipped by ticket id. ruff `src` now includes `standin` for import grouping.
- 2026-10-05: Verified. Collected 31 ids with no browser/network; stacked parametrize confirmed bottom-first (`[0-typed]`). `tests/test_standin.py` (18 tests): JSON keys == collected ids per file; four markers with config values; base class used; priority override (`test_create_item[50]` → P2); ticket skip (`STND-105`); deployment skips flip between cloud and on_prem; placeholders in unique names; repeated config block; manifest == collected functions; kind mix; API tests never touch the browser; tickets normalize with steps + expected; history fix commits remove the ticket skips (matched with `eval.ticket_id_pattern`); app state rules; only `localhost` / `example.com` hosts. ruff, mypy strict (src), non-strict mypy over `standin/` (25 files), pytest 252 passed, 7 live deselected. **Pending:** human review that all names are generic.
- 2026-10-05: Human reviewed the stand-in names (generic and invented) and ran `uv run pytest` (252 passed). Every DoD item checked. Done.

---

## Phase 3b: Stand-in v2/v3 (real-framework patterns)
**Status:** ✅ Done (v3)

**Why:** the human compared a Phase 6 generated pair with the real framework (2026-10-06) and listed ten generic structural differences: class scaffold, data loading, page-object style, assertion style, data-file shape and content, expectation format, marker values, style rules, and "needs a real run" behaviours. Several came from the v1 stand-in itself, which the generator copied faithfully. The updated patterns are in `CLAUDE.md` → "Target test-suite patterns".

**Goal:** make `standin/` mirror the real patterns, so the indexer, generator, and validators target the real shape.

**Outputs:**
- Class scaffold: base class with setup/teardown methods; class decorator stack for platform selection, environment gating, data loading, and markers
- Page objects: value fields as properties (assign/read), actions as methods, no fluent chaining
- Framework assertion object for UI checks; validation helper that replays each `interactions` request against the fake app and compares responses as a subset
- Data files: top-level array of entries with `id` = pytest id; framework keys (`settings`, `policy`, `tenants`, `targets`, `interactions`, `priority`, `skip`) plus custom keys; a large `policy`/`settings` seed repeated across many entries; variants differing by one value; self-referencing names derived from the test name; some tests with no entry
- Data access: `self.params` via the class-level data fixture, and a `params` argument in a few classes
- Simple UI inputs inline in tests; names summarize area/action/sub-area, no ticket numbers
- Style: 3-space indent, LF, final newline, alphabetical imports, no type annotations; JSON indent 3 with `"key":value` (config `style`, these defaults)
- Updated fake tickets, manifest, eval pairs, history builder, and project tests

**Constraints:** generic, invented names only (as Phase 3); collectable without a browser or network; host `--collect-only` allowed for the hand-written stand-in only.

**v3 (2026-10-06, after the second style check):** the human's review of the v2 STND-104 pair found that the remaining gaps came mostly from the stand-in's data roles and mechanics. Their answers (summarized in `CLAUDE.md` → "Target test-suite patterns"):
- seed state lives in `settings` (capability gates, roles) and `policy` (the object the UI edits), and `tenants` holds per-tenant blocks;
- `targets` is a list of flat `{method, path, payload?, status_code?, response}` expectations, and `interactions` is a nested alternative, each read by its own helper (never both in one entry);
- paths use `:tid` / `:rev_id`, and data uses `{tenant_id1}` / `{user_1}` / `{test_id:N}`;
- the identifier key is configurable (stand-in: `test_id`);
- the assertion object is a `unittest.TestCase`, with argument order not to be relied on;
- per-class `setup` calls the base setup with options;
- an object-level save comes first, then a shared top bar with save / publish / reset;
- tests follow four shapes (add, edit, delete, UI-only).

**v3 outputs:**
- **App:** an editable per-tenant policy app (rules and profiles, a multi-step add wizard, a list with search, filter, and pagination; working copy → saved draft → published revision; top bar save / publish / reset; capability gates and roles in settings; a read-only policy endpoint with `:tid` / `:rev_id`).
- **Framework and tests:** the matching framework and tests, covering the four shapes, a UI state helper, a policy manager, an import file, a multi-tenant class, and runtime-style API tests.
- **Supporting files:** new fake tickets and the history (code skip, JSON skip, open bug).

**v3 Definition of Done:** the v2 items, plus:
- [x] every v3 pattern is checked by a project test (`tests/test_standin.py`, 55 checks);
- [x] `targets` and `interactions` are replayed in-process against the app (a mutation check confirmed the replay catches the STND-104 bug).

**Definition of Done:**
- [x] Every updated pattern above is present and checked by a project test (`tests/test_standin.py`, 35 checks, `ast`-based)
- [x] `pytest --collect-only` on the stand-in succeeds with no browser and no network (35 tests)
- [x] Every entry `id` equals a collected test id; every test that reads `params` has an entry; tests without data are allowed (2 such tests)
- [x] Every data key a test reads exists in its entries
- [x] Stand-in code and JSON pass the style rules (`ruff format --check` / `ruff check` with `standin/ruff.toml`; JSON re-serialized byte-identical). The `style` config section that the generator will use lands in step C
- [x] Fake tickets, manifest, eval pairs, and history builder updated; indexer and retrieval tests pass on v2

**Open questions:** –

**Log:**
- 2026-10-06: Started after the human approved the plan (docs → Phase 3b → pipeline changes → Phase 6 live rerun → human style check → close Phase 6 → Phase 7), the model changes (`GeneratedTest` writes entries as an array and gets a new wire model with `generate_v2`; `Chunk` records its data-file format; new config `style` and `data` sections; `TestCaseDraft` / `Ticket` unchanged), and `ruff` as a runtime dependency for formatting generated code. Human's answers: repeated blocks are real (identical seeds, one-value variants, self-referencing names, no templating seen) → the 5-step entry rule; style values as above (they may differ per repo, so config); data access as a dict (`self.params` or a `params` argument), entry `id` = pytest id, entries optional.
- 2026-10-06: Built. Stand-in v2:
  - **Scaffold:** every class has `@browsers` / `@environments` / `@data_driven` / project / component. `BaseTest.setup_method` / `teardown_method`.
  - **Data access:** conftest fixtures `load_params` (sets `self.params`) and `params` (an argument; `TestOrders` uses it). Both resolve `{{unique}}` and apply the seed sections.
  - **Page objects and checks:** value fields are properties with setters, actions return `None`. `self.check` is the assertion object. `validate_backend()` replays `interactions` and compares responses as a subset.
  - **Data and names:** array data files with `id`, a large pasted `policy` block named after the test, custom keys. Names are area_action_subarea (25 test functions, 35 ids). 3-space indent, no annotations.
  - **App:** gained a policy (allowed categories, max order quantity) and `/api/policy`; unknown ids return 404.
- 2026-10-06: Project tests check every pattern with `ast`, including: no bare `assert`, no chaining, setters present, keys read exist, policy names derived from the test name, variants differing by one value, and the platform / deployment / ticket skips. `interactions` are replayed in-process against the app's API router, with the backend effect of each UI flow simulated, so expectations are checked without a browser or server.
- 2026-10-06: The indexer needed two changes for v2:
  - **Array data files:** read via the new config section `data` (`format`, `id_field`). `Chunk.data_format` records the layout (approved model change).
  - **Return-type inference:** types are now inferred from `return Callee(...)` when there is no annotation, so property chains still resolve without annotations. `INDEX_VERSION` is now 3.
  - **Retry on save:** the index save retries the rename up to `index.save_attempts` (a Windows lock made one test flaky).
- 2026-10-06: Stand-in v2 retrieval baseline (deterministic, no LLM): recall@10 0.833, MRR 0.367 (v1: 0.833 / 0.376). The v1 generator tests (`test_generate.py`, `test_generate_live.py`) are skipped until `generate_v2` (step C): they build entries in the v1 shape, which no longer exists.

- 2026-10-06: v3 built.
  - **App:** a per-tenant policy app (rules, profiles, settings), with a working copy → saved draft → published revisions, the top bar, a role-checked API, and `:tid` / `:rev_id` endpoints.
  - **Framework:** a framework fixture with per-class `setup` → `base_setup(fresh_driver, policy_wait, skip_seed)`; `self.check = unittest.TestCase()`; `verify_targets` / `verify_interactions`; brace placeholders with `unique_name`; policy and settings managers; page objects for the top bar, rules (list / wizard / editor / confirm / import), profiles, and capabilities.
  - **Tests and data:** 28 test functions (36 ids) in 5 areas, covering the four shapes, a UI helper, a manager, an import file, a multi-tenant class with login/logout, and a runtime-style API class with a stacked parametrize and a PUT + 403 permission check. The data uses `test_id`, one expectation section per entry, and a repeated 12-rule list policy.
  - **Tickets and history:** new STND-101..106 for the new domain, and a history with the duplicate-name code skip and the delete JSON skip.
  - **Project tests:** check rule (1) on the stand-in itself (every custom key read, expectation sections only with their helper, never both), replay every expectation, and compare the UI-only counts against the app.
  - **Pipeline:** `data.id_field: test_id`, `data.seed_sections` and `data.expectation_sections` (section → helper; replaces `reading_helpers`), `generate.placeholder_token: {test_id:24}`, `generate.scaffold_methods` (the scaffold piece now includes the class's setup/teardown), and prompt `generate_v3` (the final checks must verify the name's claim; save flows; the assertion object as in the examples; helpers take no arguments; seed only what is needed). The response self-checks now include rule (1): unread custom keys, an expectation section whose helper isn't called, and two expectation sections.
- 2026-10-06: Verified: ruff, mypy strict (64 files), pytest 428 passed, 12 live deselected. Stand-in v3 deterministic retrieval: recall@10 0.833, MRR 0.311 (STND-104 missed without the LLM, as in v2).

---

## Phase 4: Indexer (Python)
**Status:** ✅ Done (2026-10-05)

**Goal:** Make a codebase searchable by structure and keywords, and know which names (incl. page-object chains) really exist.

**Inputs:** A local path to a target repo (via `RepoSource`): the stand-in and `httpx`.

**Outputs:**
- tree-sitter Python parsing
- Chunks (`Chunk` model). Chunk unit for tests = test function + its decorators/markers + its JSON entries (resolved via the computed test ids). Also chunks for page objects, helpers, non-test functions, and classes.
- Static pytest-id computation: stacked `parametrize` (bottom decorator first), explicit `ids=`, literal values. Cases it can't compute statically are flagged and left to `pytest --collect-only` in the sandbox (Phase 7).
- Symbol catalog: every function, class, method, module, fixture, and marker value, with file and line, **plus page-object property chains** (each attribute/property step from a root such as `nav`, with the type it resolves to)
- BM25 index with identifier splitting (`snake_case` / `CamelCase` → words), including JSON entry text
- Index persisted to disk (git-ignored cache dir); rebuild only changed files when possible
- CLI: `ticket2test index <repo_path>` and `ticket2test search "<query>"`

**Constraints:**
- Read-only access to the target repo
- Never chunk mid-function
- Skip vendored, generated, and binary files (configurable ignore list)
- Must handle a repo of ~1,000 Python files in a reasonable time (target under 2 minutes)

**Definition of Done:**
- [x] Indexing the stand-in and `httpx` completes, and the cache reloads without re-parsing
- [x] Stand-in test chunks carry their decorators, markers, and matching JSON entries
- [x] Static id computation matches `pytest --collect-only` on the stand-in, incl. stacked parametrize (tested)
- [x] For 5 hand-picked known functions or pages, a search returns their tests in the top 5
- [x] Symbol catalog confirms existence and non-existence of names **and property chains** (tested)
- [x] Identifier splitting has unit tests
- [x] Parsing errors in a single file are logged and skipped, not fatal

**Open questions:** –

**Log:**
- 2026-10-05: Started. Dependencies from the CLAUDE.md tech stack: `tree-sitter` 0.26 (MIT), `tree-sitter-python` 0.25 (MIT), `rank-bm25` 0.2.2 (Apache-2.0). Flagged: `rank-bm25` pulls in `numpy` 2.5, licensed `BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0` (Zlib and CC0 are permissive but outside MIT/BSD/Apache). `encode/httpx` cloned at tag 0.28.1 into `.scratch/repos/httpx` (public, git-ignored).
- 2026-10-05: Built. `adapters/repo/local_path.py` (read-only; ignore patterns per path segment, binary/oversize/non-UTF-8 detection, refuses paths outside the root). `index/extract.py` (tree-sitter: module functions, classes, methods, decorators, params, return/attribute annotations, `self.x = Callee(...)`; syntax errors raise and the file is skipped). `index/pytest_ids.py` (mirrors pytest's IdMaker for literal values: explicit ids, ASCII escaping, `<argname><idx>` fallback, duplicate counters, stacked bottom-first, class-level after function; non-literals, `ids=` callables, parametrized fixtures and a custom `pytest_make_parametrize_id` hook mark ids "not computed"). `index/catalog.py` (symbols incl. fixtures and markers; classes with members through base classes; property-chain resolution with `ok` / `missing` / `unknown_type` / `no_root`, call steps `x()`, self-returning methods; chain enumeration from `index.chain_roots` bounded by depth and size; page objects = classes reached by chains + their bases). `index/chunks.py` (test chunk = function + decorators + markers + parametrize + fixtures + test ids + JSON entries; page objects chunked whole; plain classes as header-only; methods as function chunks). `index/tokens.py` (snake/Camel/acronym/digit splitting + whole identifier). `index/search.py` (BM25 over name-boosted text incl. ids, markers, entry data). `index/indexer.py` (cache `<cache_dir>/index/<repo>-<hash>/index.json`; per-file SHA-256 reuse; settings fingerprint invalidates; unreadable/unparsable files logged and skipped). CLI `index <repo> [--force]` and `search "<q>" --repo <path> [--top-k] [--kind]`. `Chunk` model adds `qualname`, `docstring`, `fixtures`, `test_ids_computed`, `test_ids_note` to the CLAUDE.md fields. (2026-10-05, during Phase 5: `refs` added for syntax-tree references; index format version 2.) Config `index.*`. The repo secret scan now checks only files git tracks or would add, so git-ignored index caches (copies of third-party code) don't trip it.
- 2026-10-05: Verified. Stand-in: 25 files, 22 test / 16 page_object / 12 class / 162 function chunks, 345 symbols, 225 chains; static ids equal `pytest --collect-only` exactly. httpx: 60 files in ~2 s, 539 test chunks, 1515 symbols; cached rebuild parses 0 files. Search: `get_environment_proxies`, `URLPattern`, `DigestAuth`, `Cookies`, `BasicAuth` (httpx) and `item_editor`, `invite` (stand-in) return tests that use them within the top 5. Pytest-id rules checked against pytest's own IdMaker on 14 decorator shapes. Benchmark: 1,020 files cold build 33 s, cached rebuild 10 s (target < 2 min). ruff, mypy strict (49 files), pytest 318 passed, 7 live deselected. Done.

---

## Phase 5: Retrieval
**Status:** ✅ Done (2026-10-05)

**Goal:** Given a ticket and draft, find the relevant code, the most similar existing tests, and the nearest JSON entries to use as templates.

**Inputs:** `Ticket`, `TestCaseDraft`, index and symbol catalog (Phase 4).

**Outputs:**
- `prompts/query_rewrite_v1.md`: ticket wording → likely code terms
- Retrieval pipeline: query rewrite → BM25 + grep → merge and de-duplicate → AST expansion (callers, callees, related tests, page objects used) → ranked list
- Template selection: nearest similar existing JSON entries (same area/component/test kind first)
- Follow-up rounds: the LLM may request extra searches when results are thin
- Retrieval result records every chunk ID and why it was retrieved (bm25 / grep / expansion / follow-up / template)
- CLI: `ticket2test retrieve ticket.json --draft draft.json`
- **Minimal eval** (pulled forward from Phase 8): recall@k on a small set of pairs

**Constraints:**
- `retrieval.top_k` and `retrieval.max_followup_rounds` from config (defaults 10 and 2)
- Follow-up rounds may only call the project's own search tools. No arbitrary shell or network.
- No embeddings in this phase

**Definition of Done:**
- [x] At least 10 public `httpx` issue ↔ fix-PR pairs collected in `eval_data/` (IDs/URLs only), plus the stand-in's ticket ↔ test pairs
- [x] Recall@10 measured on both sets and recorded in the log below (no target yet; this is the baseline)
- [x] Follow-up rounds provably stop at the configured cap (tested)
- [x] Each retrieved chunk carries its retrieval reason

**Open questions:**
- After the baseline: is recall good enough, or do we need embeddings? Decide based on data. (Baselines above: LLM on reaches 0.618 on httpx and 1.000 on the stand-in. Revisit after Phase 8's larger set.)

**Plan: LLM reranker (not built; only if Phase 8 data says it's needed)**
- *Trigger to build it:* on the Phase 8 set (30+ pairs, several runs per config), recall@10 or MRR with the deterministic reranker stays clearly below what the generator needs, and the misses are ranking problems (the right chunk is in the top 30 but not the top 10), not search problems.
- *Placement:* after the deterministic rerank, on its top `N` candidates (config, default 30); output replaces the order of the final top k. Off by default (`retrieval.llm_rerank.enabled`).
- *Input per candidate:* chunk id, kind, qualname, file path, signature line, first docstring line, matched identifiers, and the deterministic rank. No full code by default; optional snippet with a character cap. Ticket text scrubbed like other prompts.
- *Output:* `prompts/rerank_v1.md`, structured JSON `{ "order": [chunk ids], "reason": str }`, validated so it contains only given ids (unknown ids rejected → retry with the error, max `llm.max_retries_on_bad_json`); ids it leaves out keep their deterministic order after the ones it ranked. On failure, fall back to the deterministic order and record that.
- *Cost/limits:* +1 LLM call per ticket, bounded input size; not a tool-use step (no searches), so it doesn't touch the follow-up-only tool-use rule.
- *Evaluation:* A/B in Phase 8 (deterministic vs + LLM rerank), repeated runs to measure variance, report both; keep it only if the gain exceeds the run-to-run spread.

**Log:**
- 2026-10-05: Started. Eval pairs: 13 `encode/httpx` bug issues with the merged PR that fixed them, found via issue timelines (`eval_data/httpx_retrieval.json`, IDs/URLs only), and the 6 stand-in tickets → linked tests (`eval_data/standin_retrieval.json`). Fix-PR file lists and ticket payloads are fetched on demand and cached in `.t2t_cache/eval/` (git-ignored); finding the pairs used 29 unauthenticated GitHub requests (issue list, PR pages, issue timelines) and filling the cache 22 more, reusing already-downloaded issue JSON and the committed fixtures. #1428 was excluded (its linked PR only added docs).
- 2026-10-05: Built. `prompts/query_rewrite_v1.md`, `prompts/retrieval_followup_v1.md`. `retrieve/query.py` (deterministic ticket+draft text; code-like identifiers verified against the catalog, so guessed names that don't exist are dropped and reported as `rejected_identifiers`). `retrieve/pipeline.py`: BM25 on the ticket text and on the LLM rewrite terms, "grep" over indexed code for verified identifiers (definitions first; identifiers matching more than `grep_max_matches` chunks are skipped as too common), reciprocal-rank fusion, expansion from the top seeds (non-test seeds: callees, tests that use it, callers; test seeds: page objects their `self.nav...` chains resolve to), follow-up rounds only while results are thin and only with the project's own tools (bm25 / grep / symbol), capped by `retrieval.max_followup_rounds` and `followup_max_searches`, stopping early on `done` or when a round adds nothing; templates = nearest tests with JSON entries (same component first). Every hit carries reasons (`bm25` / `grep` / `expansion` / `followup` / `template`). `eval/pairs.py` (pair sets + on-demand cache), `eval/retrieval.py` (recall@k and MRR: file-level for fix-PR files, test-level for linked tests; JSON + Markdown report). CLI `retrieve <ticket.json> --repo <path> [--draft] [--no-llm] [--out]` and `eval --set <file> [--stage retrieval] [--k] [--no-llm] [--out]`. Config `retrieval.*` additions.
- 2026-10-05: Verified. **Baseline recall@10 (deterministic, `--no-llm`): httpx 0.591 (MRR 0.526, 13 pairs); stand-in 0.667 (MRR 0.218, 6 pairs).** Misses: httpx #1482, #1468, #1365, #1311 (tickets dominated by long tracebacks or describing behaviour without the code's words); stand-in STND-103, STND-104. Tuning note: callee expansion from test seeds crowded out tests (stand-in recall 0.667 → 0.500), so test seeds now expand only to the page objects their chains reach. Tests: query/identifier verification, reference extraction, reasons on every hit, expansion kinds, templates are real entries, rewrite terms used and invented identifiers rejected, follow-up cap (0/1/2/3 rounds against a fake that never stops), stop on `done` / not-thin, follow-up tools limited and capped, eval from cache without network, CLI. ruff, mypy strict (56 files), pytest 333 passed, 7 live deselected. **Not measured yet:** recall with the LLM steps on (query rewrite + follow-ups); it needs ~19+ live LLM calls: `uv run --env-file .env ticket2test eval --set eval_data/httpx_retrieval.json` (and the stand-in set).
- 2026-10-05: **AST references (requested by the human before Phase 6).** Retrieval expansion and exact-identifier search used regex over chunk text; they now use references read from the tree-sitter syntax tree at index time (`Chunk.refs`: `calls`, `names` with counts, `self_chains`). Comments, docstrings and string literals no longer count as uses (f-string code does); keyword-argument names, parameter declarations and the definition's own name are not references; `self.x = ...` detection also moved from regex to the tree. Index format version 2 (one-time rebuild). The regex module `retrieve/refs.py` was removed.
- 2026-10-05: **Baselines after the AST change (recall@10 / MRR):**

  | Set | LLM off, regex refs | LLM off, AST refs | LLM on, AST refs |
  |---|---|---|---|
  | httpx (13 pairs) | 0.591 / 0.526 | 0.591 / 0.481 | **0.618 / 0.671** |
  | stand-in (6 pairs) | 0.667 / 0.218 | 0.667 / 0.354 | **1.000 / 0.557** |

  LLM on used 23 calls through the Claude CLI (19 query rewrites + 4 follow-up rounds, all on httpx), about 1m46s per set. With the rewrite, httpx #1482 (multipart) and #1365 (WSGI path) are now found, and STND-103 / STND-104 rank first; but some fix-PR **test** files dropped out of the top 10 (#2985, #2139, #1405) because the rewrite pulls source code up. Still missed: #1468, #1311. Claude-backed runs are not deterministic, so these LLM numbers will vary between runs.
- 2026-10-05: **Deterministic reranker** (`retrieve/rerank.py`, config `retrieval.rerank`). Problem it fixes: with the rewrite on, several methods of one source file (e.g. `httpx/_client.py`) took most of the 10 slots and pushed the fix PR's test file to rank 11+. Each fused candidate is re-scored: normalized fused score + small bonuses for referencing verified ticket identifiers (0.3, scaled by count), defining one (0.2), being a test linked to a top source chunk by expansion (0.15), and ticket words in its file path (0.15). Then the top k is picked greedily with at most `max_chunks_per_file` (3) per file and at least `min_tests` (2) tests; the cap is relaxed only if there aren't enough files to fill k. Each hit records `fused_score` and `rank_features`. No LLM, same input → same order.

  | Set | LLM off | LLM off + rerank | LLM on | **LLM on + rerank** |
  |---|---|---|---|---|
  | httpx (13 pairs) | 0.591 / 0.481 | 0.591 / 0.455 | 0.618 / 0.671 | **0.772 / 0.782** |
  | stand-in (6 pairs) | 0.667 / 0.354 | 0.833 / 0.376 | 1.000 / 0.557 | **1.000 / 0.694** |

  (recall@10 / MRR; AST refs in all columns; LLM-on runs used ~23 calls each.) With rerank + LLM, every httpx pair now has at least one ground-truth file in the top 10; #1468 and #1311 are found for the first time, and the test files of #2985 / #2139 are back. Lowest recall: #2532 (7 changed files, 2 found) and #1498 (4 files, 1 found). The weights were set once, not tuned per pair; with 19 pairs and LLM run-to-run variation, treat the gains as directional.

---

## Phase 6: Code generation (code + JSON pair)
**Status:** ✅ Done (2026-10-06; the final style check against the real codebase is deferred to integration)

**Goal:** Generate a test (code file + JSON data entries) from a draft, in the style of the existing tests.

**Inputs:** `TestCaseDraft`, retrieval results incl. template entries (Phase 5), optional conventions doc (path from config).

**Outputs:**
- Context builder: ranks and trims chunks to fit `context.max_tokens`, putting similar tests first as few-shot examples
- `prompts/generate_v1.md`: the LLM returns the test code plus only the **unique** parts of each JSON entry (inputs, seed state, expected backend results)
- Deterministic entry assembly: copy large repeated config blocks verbatim from the nearest existing entry, merge the unique parts, and key each entry by the pytest-generated id (one per variant). Unique names use the placeholder token + name-generator helper.
- Code follows the suite patterns: base class, markers from the draft (priority, component, suite, project), page-object property chains, deployment-type skip from `deployment_type`, parametrize from `variants`
- `GeneratedTest` pair with full traceability (ticket, draft, chunk IDs, template entry, prompt version)
- CLI: `ticket2test generate draft.json --retrieval retrieval.json --out generated/`

**Constraints:**
- Never truncate mid-function when trimming context
- The conventions doc, if configured, is always included in context
- Secret scrubber runs on both the prompt and the generated output (code and JSON)
- Output files go only to the project's output dir, never into the target repo

**Definition of Done:**
- [x] Generates a code + JSON pair for each of 5 stand-in drafts (live test, v1; repeat on v2 below)
- [x] Entries are built from the base entry: copied sections identical except re-labelled names, per-variant changes only (tested)
- [x] Context never exceeds the token budget (tested)
- [x] Every `GeneratedTest` has complete traceability fields, incl. `template_entry_ref`
- [x] Output is formatted to the `style` rules (tested; stand-in files are a fixed point)
- [x] Live run on v2 (5 stand-in tickets; 5/5, first attempt)
- [x] Generated code follows the real framework's style (spot-checked by a human): checked against the real framework four times (v1, v2, v3, and v3 STND-106). The remaining semantic gaps go to the Phase 7 validators, and the final style check happens at integration with the real codebase (the human's decision, 2026-10-06)

**Open questions:** –

**Log:**
- 2026-10-05: Started (after the Phase 5 AST-references and reranker follow-ups).
- 2026-10-05: Built. `generate/context.py`: pieces in priority order (conventions doc and template test + its JSON entry are required; then the base test class and its in-repo bases, similar tests from retrieval as style examples, the page-object chains and page objects those tests use, other code hits); whole pieces only, a piece that doesn't fit is skipped; tokens estimated as ceil(chars / `context.chars_per_token`, default 3.0, which over-counts); `ContextBudgetError` if the required pieces alone don't fit. `prompts/generate_v1.md`: the LLM returns the module code and, per pytest id, only the unique entry parts (`seed` / `inputs` / `expected`) as JSON text. `models/generated.py`: `GenerationResponse` validates itself (code parses, has a test, literal parametrize values, computed pytest ids == entry keys, parts are JSON objects); failures go back to the LLM through the capped retry. `generate/generator.py`: entries assembled deterministically from the template entry (shared blocks such as `config` deep-copied in the template's key order; `priority` / `skip` overrides not inherited); marker values from the draft, with component/suite mapped to values the suite already uses (else the template's); target path `<template's folder>/test_<ticket>.py`; secret scrubbing of prompt, code, and JSON parts; full traceability (`ticket_id`, `draft_ref`, `template_entry_ref`, `retrieved_chunk_ids` = chunks actually in the context, `prompt_version`, provider/model, attempts, estimated context tokens, redactions). CLI `generate <drafts.json> --retrieval <retrieval.json> [--draft-id] [--conventions] [--out]` writes the code file, the JSON data file, and `generated.json` under the output dir and refuses an output dir inside the target repo. `standin/CONVENTIONS.md` (generic conventions doc). Config `generate.*` and `context.chars_per_token`.
- 2026-10-05: Verified offline. 21 new tests with the fake LLM: traceable pair, byte-identical `config` with the template's key order and no inherited overrides, prompt contents (conventions, template, markers, placeholder), retries with the error for id mismatch / non-literal parametrize / syntax error / no test / non-object parts, retry cap, output scrubbing (code and JSON), missing template, budget never exceeded at 3k–30k tokens with whole chunks, bigger budget includes more, CLI writes the pair outside the repo and leaves the stand-in unchanged. ruff, mypy strict (60 files), pytest 362 passed, 12 live deselected. **Pending:** the live run (`tests/test_generate_live.py`, 5 stand-in tickets, ~15–20 LLM calls; saves pairs to `output/generated/live/`) and the human style spot-check.
- 2026-10-05: Live run (`tests/test_generate_live.py`, run by Claude with the human's OK): 5/5 passed in 1m53s for STND-101, -102, -103, -104, -106 (draft -> retrieve -> generate, about 15 LLM calls; every generation accepted on the first attempt; context 4.4k-7.0k of 12k estimated tokens). Pairs saved to `output/generated/live/` for the human style check. Claude's own read: STND-103 and STND-101 follow the template closely (base class, markers, `self.nav...` chains, data via `self.inputs` / `self.expected`, backend checks via helpers). **Defect found in STND-104:** the code reads `self.data["seed_check"]`, but the entry has no `seed_check` key, so the test would fail with a KeyError (the model flagged it in its notes). No planned Phase 7 validator catches this; proposed addition: a validator that every `self.inputs[...]` / `self.expected[...]` / `self.data[...]` key used in the code exists in every entry.
- 2026-10-06: Human style review against the real framework → ten generic differences (see Phase 3b). Phase 6 stays 🟡: after Phase 3b, generation moves to `generate_v2` (base entry + per-variant changes per the 5-step rule, sections chosen by the LLM and copied deterministically, self-referencing names re-labeled, names without ticket numbers, entries written as an array with `id`), output is formatted to `style` (ruff for code, own JSON writer), and the live run and style check are repeated.
- 2026-10-06: Step C (`generate_v2`) built.
  - **Wire model:** the LLM returns `module_name`, the code, one entry *plan* per pytest id (`copy_sections` from the base entry, plus `changes` as set/delete on dotted paths), a `review_checklist`, and notes.
  - **Entry building (`generate/entries.py`):** deterministic, per the 5-step rule. It never copies `id` / `priority` / `skip`, and re-labels strings that embed the base test's name (`policy-orders-detail-cancel` → `policy-orders-detail-cancel-restock`).
  - **Self-checks, fed back through the capped retry:**
    - pytest ids are computed;
    - every test that reads data has entries, and every key it reads exists (Python `ast`; the STND-104 defect class);
    - copy sections and paths are valid;
    - names contain neither the ticket key nor its number.
  - **Formatting:** new `style/` module, config section `style`. Code: annotations stripped (tree-sitter), then ruff `--isolated` with only the configured values: imports sorted, unused imports dropped, formatted. The first-party roots default to the repo's top-level packages. JSON: our own writer, array or object layout.
  - **Output:** `GeneratedTest.data_entries` is now an array with `data_format`, `review_checklist` (config defaults + the LLM's items) and `entry_plans` (approved model change). The context shows the class scaffold and the base entry in the suite's JSON style. Prompt `generate_v2.md`. Config `data.access` / `reading_helpers` / `per_entry_keys`; `generate.unique_entry_keys` / `drop_template_keys` removed.
  - **Dependency:** `ruff` is now a runtime dependency (approved).
- 2026-10-06: Verified offline: `test_generate.py` rewritten (35 tests, incl. 13 retry cases) and the new `test_style.py` (10). The stand-in's test files are a fixed point of the formatter with the default config. ruff, mypy strict (64 files), pytest 402 passed, 12 live deselected. Observed: without the LLM, retrieval's first template for STND-104 is a sibling (`test_orders_list_filter_status[open]`), not `test_orders_detail_cancel`. The live run will show whether LLM-on retrieval picks better before any change.
- 2026-10-06: Live run on v2 (`tests/test_generate_live.py`, run by Claude): 5/5 passed, every generation accepted on the first attempt.
  - **First run:** all five models said the template's imports weren't shown, and guessed the decorator import path.
  - **Fix:** the indexer now records each module's top-level imports (`FileInfo.imports`, `INDEX_VERSION` 4), and the scaffold piece shows them.
  - **Rerun:** 5/5 passed in 2m16s, context 4.2k–7.7k of 12k estimated tokens. The imports are now copied, and unused ones are dropped by the formatter. The v1 outputs are kept in `output/generated/live-v1/`; the v2 pairs in `output/generated/live/` are ready for the human style check.
  - **Claude's read:** the class scaffold is copied, property assignments are used, no chaining, `self.check` / `validate_backend`, 3-space indent, array entries built from the base entry with the policy name re-labelled, and no ticket ids in names.
  - **Open points for the human:**
    1. Several plans leave out the repeated `settings` / `policy` blocks (STND-103 kept only `item_name` and `interactions`). The 5-step rule says to strip what the test doesn't use, but the real suite pastes these blocks into every entry. Which should win?
    2. STND-104's base entry is still a sibling (`test_orders_list_filter_status[open]`), not `test_orders_detail_cancel`. The output is fine, but the template choice could prefer tests that share the draft's page and action.
- 2026-10-06: Human style check of the v2 STND-104 pair: about 75–80% of the real shape.
  - **Better than v1:** array data, seed and expectation sections, 3-space indent, a `params` argument, properties, no chaining, the placeholder, and the docstring style.
  - **Remaining gaps:** the wrong roles for `targets` / `interactions`; noise in `settings` / `policy`; the request key `endpoint` instead of `path`; the identifier key name; the class setup and decorator vocabulary; the assertion object style; a validation helper that takes `params`; and the top-bar save/publish flow.
  - **Biggest gap:** the name says "restock", but no visible check verifies it.
  - **Proposed validator rules:** reject seed/expectation keys nobody reads or consumes; check that the assertions touch what the name claims.
  - **Outcome:** most gaps trace back to the stand-in, so it goes to v3 (Phase 3b), followed by a prompt update and another live run. Both rules are added to Phase 7. Answer to open point 1: seed only what the scenario reads or needs.

- 2026-10-06: Live run on stand-in v3 (`generate_v3`), run by Claude.
  - **First run:** 5/5 passed on the first attempt, but STND-102 and STND-103 took profiles tests as their base entry and landed in `tests/profiles/`. The draft's free-text component matched no marker value exactly, so the template ranking fell back to the retrieval score.
  - **Fix:** the template ranking now also uses the ticket's own components and the words in the draft's component (a new retrieval test covers it).
  - **Rerun:** 5/5 passed in 2m28s, first attempt each, context 7.8k–9.9k of 12k estimated tokens. All five use rules base entries and live in `tests/rules/`.
  - **Claude's read:** the scaffold is copied with `setup` and the `base_setup` options; the top-bar save/publish flow is right; UI-only tests (102, 103) stop before the top bar and have no `targets`; `assertEqual` is used in the suite's order; helpers are called with no arguments; one expectation section per entry; STND-104's name matches its check (only the remaining rules are published).
  - **Remaining defect:** STND-103 seeds and types the literal name `web-access` instead of `{test_id:N}` / `self.unique_name(N)`. This needs a Phase 7 rule: names of seeded objects must use the unique-name placeholder.
  - **Status:** the pairs in `output/generated/live-v3/` are ready for the human style check; v2 outputs are kept in `output/generated/live-v2/`.
- 2026-10-06: The live test now writes each run to `output/generated/live-<prompt version>/` (e.g. `live-v3/`), so the folder name says which version produced it (the human's request); earlier runs are in `live-v1/` and `live-v2/`.
- 2026-10-06: Human style check of the v3 STND-106 pair: the closest yet to a real UI-only test (right shape, purposeful seed, placeholders, properties, `assertEqual` without messages). Remaining errors are **semantic**:
  - the page counts only work with an unstated page size of 5;
  - the docstring claims "page 2 shows only allow rules", but only counts are checked;
  - `rule_count` is ambiguous (total vs. current page);
  - page 1 is never checked;
  - unused capability gates are seeded;
  - the name length isn't checked against a cap;
  - page contents depend on an unstated sort order.

  **Root cause:** the output copies the stand-in's own `test_rules_list_pagination` (the ticket's linked test, in context), which had every one of these flaws.

  **Decision (human):** no LLM reviewer step; strengthen the prompt and add deterministic heuristics (Phase 7).

  **Fixes:**
  - **App:** rules listed by name (ignoring case); `#page-size` shown; object names capped at 32 characters (`NAME_MAX_LENGTH`, enforced on seed and add).
  - **Page object:** `rule_count` → `total_count` (all matches); new `rule_actions`, `page_size`, `page_count`; docstring states which values are per page.
  - **Tests:** the pagination test checks page 1 (total, full page, only allow) and page 2 (number, filter kept, exact `page_2_names`, only allow); the filter test checks the shown actions.
  - **Data:** `expected_count` → `total_count`, `last_page_count` → `page_2_names`, capability gates trimmed to what each feature uses (defaults fill the rest).
  - **Conventions:** a "List pages" section, the docstring-claims rule, key naming, gates, and the name cap.
  - **Prompt `generate_v4`:** every stated outcome gets its own check (counts don't prove which items); check state before and after a move; no unstated constants; key names say what they measure; seeded names always use the placeholder and fit the cap; parametrize only when the steps are identical; trim unused sub-keys.
  - **Project tests:** all placeholder names fit the cap; sorting and the cap are enforced; page 1 and page 2 replayed against the app.

  Verified: ruff, mypy strict (64 files), pytest 433 passed, 12 live deselected; stand-in collects 36 tests.
- 2026-10-06: Live run on `generate_v4`, run by Claude with the human's OK: 5/5 passed in 4m11s, first attempt each, context 8.7k–10.7k of 12k estimated tokens. Pairs in `output/generated/live-v4/`.
  - **STND-106:** checks page 1 (page number, total, full page via `rules.page_size`, only allow) and page 2 (number, filter kept, exact `page_2_names`, only allow); only the `rules` gate is seeded. The review checklist and notes state that `page_2_names` assumes a page size of 5.
  - **STND-103:** the seeded and typed name is now the placeholder (`{test_id:24}` / `self.unique_name(24)`), not the literal `web-access`; it checks the exact error and that one rule with that name is listed.
  - **STND-102:** compares names after sorting both sides ("order isn't stated"), although the conventions now state the order. A minor point.
  - **STND-104:** checks counts in the UI and the published policy through `targets`; it doesn't use `page_size`.
  - **Caveat:** STND-106's linked test (the fixed pagination test) was in context again, so this run shows that the stand-in fix carries over, not that the prompt alone prevents the errors. Leave-one-out (Phase 8 idea) would test that.
- 2026-10-06: **Per-step models, and a Haiku trial for the retrieval steps** (the human's request, to keep LLM use small).
  - **Built:** config `llm.<provider>.step_models` (steps `draft`, `query_rewrite`, `retrieval_followup`, `generate`); an optional `LLMRequest.model` that all three providers honour (an additive model change); `model_name(settings, step)`. Retrieval eval reports now record the model per step, the total LLM calls, and the elapsed time.
  - **Trial:** Haiku 4.5 (`claude-haiku-4-5-20251001`) for query rewrite and follow-ups, against Sonnet 5.5, on the same day and code. Reports are in `output/reports/step-models/`. recall@10 / MRR:

    | Set | No LLM | Sonnet 5.5 | Haiku 4.5 |
    |---|---|---|---|
    | httpx (13 pairs) | – | 0.725 / 0.697, 94 s | 0.668 / 0.564, 368 s |
    | stand-in v3 (6 pairs) | 0.833 / 0.297 | 1.000 / 0.625, 43 s | 0.833 / 0.500, 116 s; rerun 1.000 / 0.519, 127 s |

    One rewrite call per ticket in every run (no follow-up rounds, no retries). On httpx, Haiku was worse or equal on every pair. One probe call each (STND-106 rewrite, CLI's own numbers): Haiku 15.6 s, 1,065 output tokens, $0.0074; Sonnet 5.7 s, 216 output tokens, $0.0062. The CLI's fixed prompt overhead dominates, so a cheaper per-token rate saves nothing here.
  - **Decision (human):** keep Sonnet for every step; `step_models` stays empty (the mechanism stays for later).
- 2026-10-06: **Closed** (the human's decision). Tuning the style further against the synthetic stand-in would fit the prompt to an invented codebase; what still varies (decorators, setup options, name cap, capability gates, save flows) is config and a conventions doc, written once against the real code at integration. The v4 pairs (`output/generated/live-v4/`) were not style-checked separately.

---

## Phase 7: Validators, repair loop, sandbox
**Status:** ✅ Done (2026-10-06)

**Goal:** Catch bad generated tests cheaply before a human sees them, and fix them automatically when possible.

**Inputs:** `GeneratedTest` pair (Phase 6), symbol catalog (Phase 4).

**Outputs:**
- Deterministic validators, each returning structured errors:
  - Syntax parses
  - Every referenced name exists in the catalog or is defined in the test, **including page-object property chains**
  - Imports resolve
  - JSON keys exactly match the pytest-generated ids (respecting stacked decorator order)
  - Every parametrize variant has a JSON entry, and no entry is orphaned
  - Required markers are present, with known values
  - The base test class is used
  - Naming conventions (configurable patterns)
  - Page-object usage: properties assigned/read, actions called; no fluent chaining
  - UI checks use the framework assertion object, not bare asserts; backend checks use the validation helper
  - Every data key the test reads (`params[...]`, `.get(...)`) exists in each of its entries; every test that reads data has an entry
  - Data file: array shape, entry `id` = collected id, formatting per `style`
  - Approved marker values (casing included)
  - Style rules (indent, line endings, final newline, import order, no annotations)
  - No ticket numbers in file, class, or test names
  - "Needs a real run" checklist attached to every generated test (refresh before re-read, save flow, capabilities, captured responses)
- Repair loop: validator errors → LLM fix → re-validate, capped
- Sandbox runner: `pytest --collect-only` in a container (Podman or Docker) as the primary execution check (imports resolve, ids match, no browser needed). Running tests is optional and later (API tests first).
- `validation_report` and `collect_report` attached to each `GeneratedTest`
- CLI: `ticket2test validate generated/ [--collect] [--run]`

**Constraints:**
- `repair.max_attempts` from config (default 3)
- Sandbox: **no network**, target repo mounted **read-only**, a writable temp dir only, `sandbox.timeout_seconds` enforced
- Generated code never executes on the host, including collection and this project's own tests
- If the container runtime isn't available, `--collect` / `--run` fail clearly. They never fall back to host execution.

**Definition of Done:**
- [x] Each validator has unit tests with passing and failing examples (`tests/test_validate.py`)
- [x] A test using a non-existent function or property chain is caught and reported
- [x] A JSON key mismatch caused by wrong stacked-decorator order is caught
- [x] Repair loop stops at the cap (tested with the fake LLM)
- [x] `pytest --collect-only` runs in the sandbox on a generated stand-in test, with no network and a timeout (tested)
- [x] Missing container runtime produces a clear error, not host execution

**Open questions:** –

**Log:**
- 2026-10-06: Started after Phase 6 closed. Human decisions: no LLM reviewer step (heuristics are deterministic warnings); permission to pull the public `python:3.12-slim` image and build the sandbox image into Podman's store (outside the repo).
- 2026-10-06: Built.
  - **Validators (`validate/`):** `code.py` resolves `self.` chains and locals bound to them (`rules = self.nav.rules.list`) through the catalog, with the kind of every step; `validator.py` runs the checks; `claims.py` is the claims-vs-checks heuristic; `report.py` has `Finding` (error / warning) and `ValidationReport`.
  - **Errors (block, feed the repair loop):** syntax; imports (stdlib, `validation.external_modules`, or names in the repo's modules); undefined names; base class; page-object chains (missing members, a property called, an action not called or assigned, chained calls); assertions (no bare `assert`, allowed methods only, every test checks something); required markers with approved values (case-sensitive; components from the catalog); naming regexes and no ticket numbers; style (LF, final newline, no annotations, ruff-formatted); ids vs. entries (orphans, duplicates, missing entries, recorded ids); data keys read exist, and every key is read or consumed (rule 1, never both expectation sections); the data file's JSON style; seeded and typed names use the placeholder; `{test_id:N}` + suffix and `unique_name(N)` within `validation.name_max_length` (32).
  - **Warnings (reviewer only):** claims vs. checks (outcome steps of the docstring, the draft's expected outcome per module, or the test name when there is no docstring; "only / remaining / every / all" clauses need an item-level check, not just a count); capability gates the component doesn't use (`validation.capability_gates`); paging with count checks but no page-size read.
  - **Repair (`validate/repair.py`, prompt `repair_v1`):** continues the generation conversation (previous reply as the assistant turn, then the errors and warnings); only errors trigger a round; at most `repair.max_attempts` (3); an unusable repair reply keeps the last valid version. `generate` (CLI) now runs generate → validate → repair; the report (with `repairs` and the per-round `history`) is stored in `generated.json`. `generate_test` was split into `prepare_generation` + `assemble` (same behavior).
  - **Sandbox (`sandbox/runner.py`, `sandbox/Containerfile`):** `podman`/`docker run --rm --network=none --read-only --tmpfs /tmp --cap-drop=ALL --security-opt no-new-privileges --pids-limit --memory`, the target repo `:ro` at `/repo`, a staging folder under `.scratch/sandbox/` at `/work` (removed afterwards); inside, the repo is copied, the generated pair placed at its repo path, and `pytest --collect-only` collects only the generated module; collected ids are compared with the generator's. Timeout kills the container (`rm -f`). Missing runtime or image is a `SandboxError`; never a host run. Image: public `python:3.12-slim` + pytest 9.1.1 + selenium 4.50.0 (pinned to `uv.lock`), non-root user.
  - **CLI:** `validate <dir> --repo <path> [--collect] [--run]` (`--run` not available yet) writes `validation_report` / `collect_report` into each `generated.json`; `sandbox [--build]`.
  - **Config:** new section `validation` (all values above); `repair.prompt_version`; `sandbox.image` / `memory` / `pids_limit` / `work_dir`. Pytest marker `sandbox` (deselected by default).
  - **Stand-in:** the tenants entries still pasted all four capability gates; trimmed to `rules`.
- 2026-10-06: Verified. ruff, mypy strict (70 files), pytest 473 passed, 14 deselected (12 live, 2 sandbox); `-m sandbox` 2 passed with Podman.
  - **Isolation probe** (same container flags): network blocked, `/repo` read-only, root file system read-only, only `/work` writable, uid 10001.
  - **Hand-written stand-in suite:** no errors; one warning (`test_rules_list_api_created`: the name claims "api created", the check only looks for the name in the list).
  - **Earlier outputs through the CLI with `--collect`:** `live-v4` 5/5 pass (one claims warning on STND-102: "whatever their capitalization"). `live-v3` 3/5: STND-103's literal `web-access` (seeded and typed), and STND-106's `rules.rule_count` (no longer exists) plus the two warnings from the third style check ("Page 2 shows only allow rules" checked only by counts; no page-size read). All ten collect in the sandbox, about 6–8 s each, including v3 STND-106: a missing property only fails at run time, so the catalog check catches what `--collect-only` can't.
  - **Not run:** a live generation with the repair loop (real LLM calls).

---

## Phase 8: Eval harness
**Status:** ✅ Done (2026-10-06)

**Goal:** Measure quality per stage, so we know what to improve and can prove value.

**Inputs:** `eval_data/`: public issue ↔ fix-PR pairs, stand-in ticket ↔ test pairs, and pairs mined from git history; the full pipeline.

**Outputs:**
- Eval data mining: a read-only git history reader finds commits where a ticket-id skip was removed, and records ticket ↔ test pairs (ticket-id pattern from config)
- Metrics:
  - **Retrieval:** recall@k, MRR (ground truth = files changed in the fix PR, or the test linked to the ticket)
  - **Faithfulness:** rate of invented names (incl. property chains); draft-matches-ticket via LLM-as-judge
  - **Execution (primary):** `pytest --collect-only` pass rate in the sandbox
  - **Execution (later, optional, API tests only):** fail-before-fix / pass-after-fix rate
  - **Cost:** tokens and wall-clock time per ticket
- Report as JSON + Markdown, saved per run with a timestamp and config snapshot
- CLI: `ticket2test eval --set eval_data/ --out reports/`

**Constraints:**
- LLM-as-judge results are labeled **"unvalidated"** until compared against human labels on a sample
- Eval runs are reproducible: same config + same data → comparable report. Claude-backed runs are not fully deterministic (no temperature control), so repeat runs and report variance.
- All code execution (incl. collection) goes through the Phase 7 sandbox

**Definition of Done:**
- [x] At least 30 eval pairs across the sources above, incl. at least one mined from git history (31 distinct; 2 mined)
- [x] One full baseline report generated and summarized in the log below
- [x] Re-running with the same config gives consistent retrieval metrics (deterministic runs identical, tested; the LLM steps vary by about ±0.05 recall between runs, see the Phase 5/6 logs)
- [x] Report clearly separates measured metrics from unvalidated judge metrics

**Open questions:**
- Which metric matters most to the QE team? Confirm before optimizing.
- Latency and pricing evals per stage: wanted later (the human, 2026-10-06). Calls and wall-clock time are recorded per ticket and per set already.

**Log:**
- 2026-10-06: Started. Human decisions: latency/pricing evals later; a lean baseline (retrieval with the LLM once, generation for 12 tickets) plus the LLM judge.
- 2026-10-06: Built.
  - **Pairs (31 distinct):** 6 more public `encode/httpx` bug issue ↔ merged fix-PR pairs (#3411, #3140, #3111, #2883, #2810, #2694; found from merged PR bodies that close an issue, feature requests skipped; 19 in total); 6 more fake stand-in tickets STND-107..112 for profiles, settings, tenants, the policy API, rule edit, and import (12 in total; export, manifest, and pair set); `eval_data/standin_mined.json` with 2 pairs mined from the scripted history.
  - **Mining:** `adapters/repo/git_history.py` (read-only: `log`, `diff-tree`, `show`; no write method), `eval/mining.py` (a commit that removes a skip citing a ticket id, as a test or class decorator or a JSON entry's `skip`, while the test still exists), CLI `mine`. Config `eval.max_commits` (5000).
  - **Generation eval (`eval/generation.py`):** per ticket: draft → retrieval → `generate_with_repair` → validators → sandbox collect; leave-one-out by default (`index_without` drops the linked test chunks; a check records whether the linked test stayed out of the context); drafts cached in `<cache_dir>/eval/drafts` (flagged per ticket; `--fresh-drafts`); generated pairs kept under the report folder.
  - **Judge (`eval/judge.py`, `prompts/judge_draft_v1.md`):** verdict, score, unsupported, missing; `--judge` only; its own UNVALIDATED section.
  - **Report (`eval/report.py`, `eval/run.py`):** pair sources, distinct pairs, mined-pair agreement, retrieval per set (mean [min–max] over `--runs`), generation metrics and a per-ticket table, judge section, config snapshot. CLI `eval --set <file|dir> --stage retrieval|generation|all [--runs] [--judge] [--no-collect] [--no-leave-one-out] [--fresh-drafts]`.
  - **Models:** `PairSet` gains `conventions_doc` and `generation`; `EvalPair` gains `source` (additive).
  - **Also:** `docs/porting-checklist.md` (what to fill in for a real environment; placeholders only).
- 2026-10-06: Verified. ruff, mypy strict (76 files), pytest 486 passed, 14 deselected. Deterministic eval twice over all sets: identical (httpx 0.571 / 0.415, stand-in 0.917 / 0.377, mined 0.500 / 0.100).
- 2026-10-06: **Baseline** (`output/reports/phase8/eval-20261006T102640.md`; Sonnet 5.5 via the Claude Code CLI; 81 LLM calls, about 14 minutes; sandbox: Podman).

  | Retrieval (LLM on, 1 run) | Pairs | recall@10 | MRR |
  |---|---|---|---|
  | httpx | 19 | 0.755 | 0.753 |
  | stand-in | 12 | 1.000 | 0.403 |
  | mined | 2 | 1.000 | 0.155 |

  | Generation (stand-in, leave-one-out) | Value |
  |---|---|
  | Tickets generated | 12/12 (11 UI, 1 API) |
  | Validators pass, first attempt / after repair | 1.000 / 1.000 (0 repairs) |
  | Invented names, first attempt | 0 |
  | `pytest --collect-only` in the sandbox | 12/12 |
  | Reviewer warnings per test | 0.33 |
  | LLM calls / time | 48 (4 per ticket incl. the judge) / 587 s, about 49 s per ticket |
  | LLM judge (UNVALIDATED) | 7 faithful, 5 partly; mean 0.89 |

  - **Leave-one-out held:** every ticket used a sibling as its template (e.g. STND-106 from `test_rules_list_filter_action[allow]`); 0 violations.
  - **Reading:** on the stand-in, every generation metric is at the ceiling, so it shows the pipeline works end to end but can't separate configurations. What it doesn't measure: test-level faithfulness. STND-110's test covers viewers only, while the ticket names viewers and editors.
  - **Judge calibration:** all 5 "partly" verdicts cite default metadata (`deployment_type: both`, priority, suite) as unsupported. The judge prompt should treat config defaults as neutral; not changed, since the judge is unvalidated until hand-labelled.
  - **Warnings:** 2 of the 4 were clause-splitter false positives (a parenthesised name list, and "deny, not allow"); fixed after the run (`clauses` keeps parentheses, double quotes, and a trailing negation together). The other two are fair reviewer prompts ("whatever their capitalization", "including the last one of the file").

---

## Phase 9: Rust support
**Status:** ⬜ Not started

**Goal:** Extend indexing and validation to Rust code.

**Inputs:** A mixed Python+Rust public repo (`pydantic/pydantic-core`).

**Outputs:**
- `tree-sitter-rust` support in the indexer and symbol catalog
- Cross-language awareness: Python tests that exercise Rust code via bindings are linked where detectable
- Rust-aware validators where applicable

**Constraints:**
- Python behavior from earlier phases must not regress (all existing tests and eval metrics hold)

**Definition of Done:**
- [ ] Mixed repo indexes successfully
- [ ] Symbol catalog includes Rust functions, structs, and impl methods
- [ ] Python eval metrics show no regression versus the Phase 8 baseline

**Open questions:**
- How are Rust functions exposed to Python in the target codebase? (Affects cross-language linking.)

**Log:** –

---

## Porting preparation (after Phase 8)
**Status:** ✅ Done (2026-10-07)

**Why:** the human asked what porting to the real codebase needs. Two generic gaps were closed first, so porting becomes "fill in the private config, rerun `check-suite` until clean".

**Log:**
- 2026-10-07: Built.
  - **`check-suite <repo> [--collect]` (`validate/suite.py`):** runs the validators over every existing test file (files matching the test globs that contain tests), groups errors by check with the config keys to look at, counts warnings only, lists files with non-literal parametrize, and with `--collect` compares the statically computed ids with `pytest --collect-only` of the whole suite in the sandbox (`collect_suite`). Report in JSON + Markdown; exit code 1 unless clean.
  - **Validator fix found by it:** names a package re-exports (`from framework.pages import Navigator`, defined in `framework/pages/nav.py`) were reported as missing. `validate_generated` now takes the repo's import statements per module (`module_imports(index)`); used by `generate`, `validate`, `check-suite`, and the eval.
  - **Configurable sandbox image:** `sandbox.base_image` and `sandbox.requirements` (default: packaged `sandbox/requirements.txt`, pytest + selenium pinned to `uv.lock`, checked by a test). The build stages the Containerfile + requirements in a temporary context under `.scratch/sandbox/`; the image runs as a numeric non-root user (no user tools needed in the base image).
  - **Credential isolation:** the first real rebuild failed: this machine's registry credential helper had an expired login, and Podman consulted it even for local images. Every runtime call now gets an empty credentials file / Docker config under the work dir (`sandbox.registry_auth: false`, the default), and runs use `--pull=never`. Rebuild and runs then worked without any login.
- 2026-10-07: **Integration brief** (`docs/integration-brief.md`), for an assistant (e.g. a small Claude model) that can read the real suite and connect it. It defines the interface: inputs it writes (private `company.yaml` overrides, `CONVENTIONS.md`, `sandbox-requirements.txt`, a Jira `tickets.json`, its own `integration-notes.md`), environment variables, and outputs it reads (`check-suite` JSON); every config key with how to find it in a codebase and the stand-in default; a calibration loop capped at 10 rounds with a check → config-key fix table; templates for the conventions doc and the report. Two gaps closed for it: the placeholder syntax is now config (`validation.placeholder_pattern`, `validation.unique_name_pattern`; were hard-coded `{test_id:N}`), and the `check-suite` JSON includes `ok`.
- 2026-10-07: Verified. ruff, mypy strict, pytest 496 passed, 14 deselected; `-m sandbox` 2 passed. `check-suite standin --collect`: clean, 5 test files, 36 static ids = 36 collected. `check-suite` on httpx (untuned, a differently shaped suite): 2,601 errors, mostly markers (none), assertions (bare `assert`), style (4-space indent, annotations), base class (none): the first run on a new suite shows which config sections to change.

## Stand-in v4 and reuse support (refinement while the real suite can't be connected)
**Status:** 🟡 In progress (steps 1–5 of 7 done; step 6 replaced by real-run results)

**Why:** the human described the real suite's scope (generic, no names): besides policy rules, tests for an **AI browsing agent** (prompt injection, API endpoints) and **file-policy enforcement** (document isolation and safe viewing; download policies block/allow/sanitize; malware scanning by signature and hash; DLP rules; encrypted files and password prompts; archive extraction and member inspection; converted vs. original downloads). Reuse dominates: a base class (driver and framework setup), page-object helpers, **tests calling tests**, and **decorator-generated class variants**. Decisions: keep LLM use minimal and prefer logic; mask prompt-injection payloads from our own LLM (not just wrap them); patch output (add a variant / a method to existing files) is approved.

**Plan:** 1 stand-in v4 → 2 inheritance and class variants in the indexer and validators → 3 payload masking → 4 reuse-first output (variant / method / new module, as a patch) → 5 logic-first items (template by test shape, variant coverage, auto-fixes before repair, class shell in code, conditional query rewrite, judge prompt, privacy safeguard) → 6 run generated API tests in the sandbox (pass on the fix, fail before) → 7 one LLM eval run (ask first).

**Log:**
- 2026-10-07: **Stand-in v4 built** (generic, invented, deterministic; no LLM).
  - **App:** `app/files.py` (files built from a JSON description; zip archives with stdlib `zipfile`; encrypted files behind a password hash; an invented malware signature, not a real antivirus test string; SHA-256 blocklist; DLP regex rules with block/log; nested-archive inspection with a depth limit; converted vs. original downloads; safe viewing with active content removed). `app/agent.py` (a rule-based browsing agent: reads a page, follows the goal, flags embedded instructions as `injection:<location>` with the guard on, follows them with it off; open bug STND-116: the guard misses page metadata). `app/state.py` (the fake external `site`, a download log, agent tasks, the agent guard setting, file-policy sections with defaults; enforcement uses the latest *published* policy). `app/pages_v4.py` + server routes (download center, verdict page with a password form, viewer, download-policy editor, agent console and settings) and API (`files/v1/policy`, `downloads/v1/download|log`, `agent/v1/tasks`, `settings/v1/agent` admin-only).
  - **Framework:** page objects `framework/pages/files.py` and `agent.py` (properties for values, methods for actions, multi-step helpers `download_file`, `view_file`, `run_task`, `set_type_action`); the navigator's `files` and `agent` areas; site seeding through the base class; the class-variant decorator `variants(attribute, *values)`.
  - **Tests (68 ids, 11 files):** a shared base `tests/files/checks.py::DownloadChecks` (setup, `expect_verdict` helper, an inherited test run by every subclass with its own entry); four file-policy classes inheriting it; a test calling another test (`test_files_archive_view_members`); class variants (`TestFilesViewerConverted` / `Original`); agent UI tests (5 injection locations, guard off, settings toggle) and agent API tests (task, unknown page, viewer/editor 403).
  - **Tickets and history:** STND-113..121 (STND-116 open; STND-117 fixed in a new history commit with a data skip); manifest, eval pairs (stand-in 21, mined 3; 40 distinct pairs in all).
  - **Project tests:** `tests/test_standin.py` follows inheritance and test-calls-test; entries are keyed per file (inherited tests share ids across files); every new expectation is replayed against the app in-process; the open bug STND-116 is checked to still show.
- 2026-10-07: **Reuse support in the pipeline.**
  - **Indexer:** a test class collects the tests it inherits from bases in any file (new chunks in the subclass's file, its data entries, markers from both classes; `Chunk.inherited_from`); class-variant decorators from config `index.class_variant_decorators` (values and naming rule); `Chunk.collected_classes` (the classes pytest collects the test under). Additive `Chunk` fields (flagged to the human), index format 5. Static ids now equal `pytest --collect-only` for inherited tests and variants.
  - **Validators (`validate/datause.py`):** inherited tests' ids count for generated and real classes; data reads follow `self.<method>()` calls into helpers and other tests, in the class and in repo bases (parsed from the indexed class code), so a test calling a test needs the called test's keys; "checks nothing" accepts checks reached through called methods; chains start from the class's own repo base (e.g. `DownloadChecks.expect_verdict`).
  - **Config:** `data.seed_sections` gains `site`; `validation.unique_name_sections` (where seeded names must be unique; the site is not); the name-length check measures only strings that start with the placeholder (names, not messages).
  - **check-suite on stand-in v4:** clean; `--collect` in the Podman sandbox: 68 static ids = 68 collected. It first reported `site` unread and literal DLP rule names (the stand-in then gave DLP rules unique names): the calibration loop working on our own config.
  - **Retrieval (deterministic):** stand-in 21 tickets recall@10 0.952 (STND-104 missed as before), MRR about 0.2; mined 3 pairs.
  - **Verified:** ruff, mypy strict (79 files), pytest 537 passed, 14 deselected; `-m sandbox` 2 passed.
- 2026-10-08: **Payload masking (step 3).** The human's choice: mask payloads from our own LLM rather than only wrapping them.
  - **Masker (`security/masking.py`):** instruction-like phrasing (config `security.masking.patterns`) and the values of configured data keys (`security.masking.keys`, stand-in: `hidden_text`, `comment`, `alt`, `meta`) become `[[PAYLOAD_n]]` tokens; the same payload keeps its token. Span rules: a short quoted string around the match (also escaped quotes inside JSON) is masked whole; inside long strings (a ticket description held in JSON) only the sentence is masked, so the ticket stays readable.
  - **Client (`llm/masking.py`):** `MaskingClient` masks every message of every request and adds the legend (prompt `masking_legend_v1`: what each token is, copy tokens exactly, never write payload text). It is the outermost wrapper (debug logs see masks); `create_llm_client` adds it unless `security.masking.enabled` is false.
  - **Restoring:** drafts and judge verdicts (`unmask_model`), generation (`unmask_generation`: code through Python's tokenizer, re-quoting string literals so quotes or backslashes in a payload can't break the code; JSON values re-escaped; notes and checklist as text). Data entries copy payloads from the base entry in code, never through the LLM.
  - **Validator (`payloads` check):** a leftover token in code or data is an error (unknown token, or in an f-string or comment); instruction-like text in generated output that is in neither the suite's data nor the draft is a reviewer warning.
  - **Checked:** for STND-116 the draft prompt keeps the whole ticket readable with only the quoted payload as a token; the restored draft step has the original.
  - **Verified:** ruff, mypy strict (81 files), pytest 549 passed, 14 deselected.
- 2026-10-08: **Reuse-first output (step 4).** All decisions are code; the LLM is called only to write a new method or module, or to plan a new case the draft doesn't spell out.
  - **Domains are folders** (the human: markers aren't domain-specific, folders are; real layout `<root>/<group>/<domain>`, no common root base class). `generate.domain_globs` (default `tests/*`) or explicit `generate.domains`. `generate/domain.py` sums retrieval scores per domain, adds a component bonus (0.25) and a label bonus (0.1), and flags close calls as uncertain (`reuse.domain_margin`). Stand-in: 20/21 tickets right, STND-109 flagged uncertain.
  - **Decision** (`generate/reuse.py`): an IDF-weighted F1 of the draft's words against each domain test's flow words (name, docstring, referenced names and chains, parametrize argument names, custom data keys). In order: **covered** (the draft names a parametrize value *with a word of its argument name*, e.g. `exe` of `file_type`, and no new concrete value; or all its values are in the data), **variant** (flow >= 0.6, its own test with one parametrize, same UI/API kind), **method** (class match >= 0.4, raised from 0.3), **module** (base class and scaffold from the domain's closest class of the same kind). Scenarios: exe -> covered `test_files_download_type_action[exe]`; new DLP pattern -> variant of `test_files_dlp_rule_enforced`; encrypted-archive members -> method in `TestFilesArchives`; print policy -> module.
  - **Patches** (`generate/patch.py`): a variant appends the value to the single literal parametrize list in its own style (quotes, one line or one per line, trailing comma) and inserts an entry cloned from the nearest case (per-entry `skip`/`priority` dropped) after the test's entries. The plan is code when each draft input names one data key; exact copies of the value elsewhere change with it (only in expectations when the new value already exists, e.g. a seeded file); a value others derive from (a pattern the content must match) goes to one small LLM call (`prompts/variant_v1.md`, `VariantPlan`, values must be valid JSON so a bad regex escape is retried). A method is generated with the target class as template, its new methods are spliced into the class (the class's indent and spacing; only imports the methods use), entries appended. Outputs: `patched/<path>` copies + `changes.patch` + `decision.json`; the target repo is never written. Validation runs on the whole patched file and reports only findings the unpatched file lacks.
  - **Pipeline** (`generate/pipeline.py`, CLI `generate --as auto|variant|method|module`, default auto): covered -> no LLM call; variant -> method -> module fallbacks recorded in the reasons (a module generated for a failed splice is kept, no second call). `validate` handles patch outputs; `--collect` in the sandbox: a code-planned variant (7 ids) and a method patch (7 ids) both collected exactly.
  - **Models (approved additions):** `GeneratedTest.reuse_kind`, `reuse_target`, `reuse_reasons`, `variant_plans`, `patches`; `attempts` may be 0 (a patch planned in code); `VariantPlan`, `VariantPlanResponse`, `PatchedFile`; LLM step `variant_plan`. `validation.base_class` became `validation.base_classes` (any of several roots).
  - **Verified:** ruff, mypy strict (85 files), pytest 582 passed, 14 deselected.
- 2026-10-08: **Logic-first items (step 5).** Each item moves work from the LLM into code, or measures that it can't.
  - **Judge prompt `judge_draft_v2`:** config-filled fields (markers, `deployment_type: both`, test kind) are neutral, never "unsupported" unless the ticket contradicts them (all 5 "partly" verdicts in the Phase 8 baseline came from these). Still unvalidated until hand-labelled.
  - **Conditional query rewrite: measured, not built.** On the 31 pairs with an LLM baseline, the rewrite helped 6 (httpx 3140, 2810, 2694, 1482, 1365; STND-104) and hurt 2 (httpx 2139, 1405). Before the rewrite, the helped ones look like the others (4–12 verified identifiers, 3–4 tests in the top 10, high top scores); the best simple rule (fewer than 3 tests in the top 10) would call the rewrite for 1 of the 6. So it stays on: one call per ticket buys most of the recall gain.
  - **Template by test shape (`retrieve/shape.py`):** shape = kind (UI when a chain starts at a page-object root) + action (`retrieval.shape_actions`: add / edit / delete words in the test name, else in the names it calls; for a draft, in its intent, else its steps). Templates rank by component, then kind, then action, then score; the reason says "same shape". Stand-in: 6 add, 5+1 edit, 4 delete, 25 other UI; 2 edit, 4 other API.
  - **Variant coverage (validator `variants`, error):** every draft variant needs one of its input values in the code (a string literal such as a parametrize value) or the data, so "viewers and editors" can't come back as viewers only.
  - **Fixes in code before repair:** data keys the test never reads (or an expectation section whose helper it never calls) are removed when entries are built, and one entry labelled with an id the code doesn't produce is re-keyed when exactly one test lacks its entry; both are noted in `generated.notes`. These used to cost an LLM retry each. Two called expectation helpers stay an error (code can't tell which is meant).
  - **Class shell in code:** a new module is rebuilt on the template class: its module imports, decorator stack (decorators of the same name keep the generated arguments, e.g. the component; new ones such as `cloud_only` are added), base class and setup/teardown; the generated test methods are spliced in with only the imports they use. Modules with other top-level code are left as written.
  - **Privacy safeguard (`security.private_terms`):** regexes set only in private config or the environment; `PrivacyClient` (outermost wrapper) redacts them from every request; validator `private` reports a term or a `[PRIVATE]` mark in output; CLI `privacy-scan` checks the files git would commit. Reports give the term's position, not its text. `masker_of` now finds the masking client under other wrappers.
  - **Verified:** ruff, mypy strict (88 files), pytest 600 passed, 14 deselected; `check-suite standin`: clean.
- 2026-10-08: **Step 6 changed: real-run results instead of sandbox execution.** The human: the real suite runs through its own pytest wrapper script on remote browsers, with console output only (a session link after a failure). Executing generated tests in our no-network sandbox can't reach that environment, so ticket2test reads the run's console log instead.
  - **Reader (`results/console.py`, no LLM):** pytest sections; verbose results whether the status ends the node-id line or (with `-s`) follows printed output on its own line; xdist lines; the warnings summary ignored (it repeats node ids); failure and setup-error blocks (`E` lines, error type); links by `results.link_pattern` attached to the block they're in or the running test. Class parts may be decorator-generated variants, so one generated test can have several results.
  - **Verdicts:** passed / test_problem (`results.test_problem_errors`) / check_failed (assertion: the bug or a wrong expectation) / error / not_run / unclear. CLI `results <log> <generated dir>` stores `run_report` in each `generated.json`, matched by file and by `new_test_ids` (the ids a patch added; new field).
  - **Calibration:** the human's real passed log (kept out of git) parses to 1 result, passed, with the variant class. Fixtures are synthetic logs in the same shape. **Open:** the failed-log layout and where the link line appears are a pytest-standard guess until a real failed log arrives.
  - **Verified:** ruff, mypy strict (90 files), pytest 613 passed, 14 deselected.
- 2026-10-08: **Step 7, eval run 1** (generation stage, stand-in 21 tickets, leave-one-out, judge `judge_draft_v2`, Sonnet 5.5 through the Claude desktop app's bundled CLI; 114 LLM calls, 29 min; report `output/reports/step7/eval-20261008T071249.*`). Before it, the generation eval was moved onto the reuse pipeline (it still called the module-only path).
  - **Result:** 17 generated, 4 "covered"; reuse 0 variant / 9 method / 8 module (4 fallbacks); validators pass 0.18 first attempt, 0.35 after repair; collect 12/17; invented names 2 (STND-112, repaired); judge mean 0.93 (19 faithful, 2 partly).
  - **What it found (all fixed, deterministic, no extra LLM calls):**
    1. *Inherited tests had no entry* (real; matters for the real suite's reuse). Every new file-policy class inherits `DownloadChecks` and its shared test, which needs one entry per class; nothing wrote it and the structured-output check rejected one. 5 tickets spent 3 unfixable repair rounds (11 calls each). Now entries for inherited tests are copied in code from the template class's entry, their ids are recorded, the check accepts them, and method patches append only the new methods' entries.
    2. *False "covered"* (real): 4 tickets "covered" by a sibling sharing a parametrize value (allow, deny, low) but missing the ticket's point (a reset, page 2, a second tenant). A false covered silently drops a ticket, so covered is now strict: the words must match on their own (`covered_min`); the parametrize bonus only ranks. Replay of all 21 decisions (cached drafts, no LLM): 0 covered, all method/module.
    3. *Collect parser dropped ids with spaces* (real): node ids are now read as the first block of `path.py::` lines.
    4. *Leave-one-out didn't fit patches* (eval artifact): the linked test was removed from the index but not the files, so 7 method patches showed false id mismatches and 3 clashed with the left-out name. The eval now cuts the test's code and entries from a copy of the repo (git-ignored cache) and indexes, patches and collects that copy; `check-suite` is clean on all 21 copies.
  - **Verified:** ruff, mypy strict (90 files), pytest 616 passed, 14 deselected. **Next:** eval run 2 with these fixes (ask first).
- 2026-10-08: **Scope decision (human): fail-before / pass-after is out of scope.** The project serves the QE team, who run tests against deployed builds, not against code before and after a fix. Checking a test against pre-fix and post-fix code stays a possible later improvement, not a goal; `ticket2test results` (reading the QE runner's log) covers what QE needs. CLAUDE.md's Phase 8 "Execution (later, optional, API tests only)" item is parked accordingly.
- 2026-10-08: **Scope (human): load and performance tests are out of scope** for now (revisit if that changes). A ticket that only describes behaviour under load gets questions and notes, not a load test.
- 2026-10-08: **Partial draft skeletons (human's request: compare both outputs on a real vague ticket).** For a ticket judged insufficient, one extra LLM call (`prompts/skeleton_v1.md`, `draft/skeleton.py`, `DraftResult.skeleton`) writes what the ticket supports with every unknown as a referenced question ([Q1] ...); the model rejects dangling or unused question references and any number not in the ticket (sent back, capped). Config `draft.skeleton: auto | always | never` (auto: insufficient only); never used for generation; skipped in the eval. Review Markdown gets a "Partial draft (for discussion, not generated)" section.
  - **Real run** on a synthetic copy of the human's redacted ticket (`tests/fixtures/jira/vague_oom.json`: one-line OOM report, a reproduction script, a suspected cause; 3 calls with `skeleton: always`): the normal draft step did **not** say insufficient: it drafted an API test (p0, confidence 55%) that runs the script and expects no OOM, with the gaps hidden (client count, memory limit, how OOM is observed, what "fixed" means). The skeleton listed those as 8 specific questions with no invented values and flagged the load-test nature. Open: trigger the skeleton for low-confidence drafts too (proposed, not built).
- 2026-10-08: **The LLM's self-rated `confidence` removed; a support checklist checked in code instead** (the human: a probabilistic model scoring its own output isn't trustworthy; use logic). Removed from the wire and stored draft models (old files with it still load; a reply that includes it is sent back), from config (`unknown_component_max_confidence`) and from CLAUDE.md; prompt `draft_v2` drops the rule. It never drove a decision (only shown, and capped for an unknown component). New `TestCaseDraft.support` (`draft/support.py`): explicit steps / expected / actual sections in the ticket, component named in the ticket, numbers not in the ticket, grounding (share of the draft's content words found in the ticket) and the words that aren't; shown as a table on the review page.
  - **Skeleton trigger is logic now:** `draft.skeleton: auto` fires when the ticket is judged insufficient or lacks an explicit steps or expected section. Stand-in: 0 of 21 tickets fire; the OOM ticket fires.
  - **Real run** (OOM ticket, `auto`, 2 calls): the checklist shows no explicit steps / expected / actual, component named, no invented numbers, 71% grounding, plus the draft's own words (monitoring, wait, stays ...); the skeleton gives 6 questions (what "fixed" means first) and the load-test note.
  - **Verified:** ruff, mypy strict (92 files), pytest 622 passed, 14 deselected. Note: eval drafts cached under `draft_v1` are not reused (new prompt version); eval run 2 re-drafts the 21 tickets.
- 2026-10-08: **Step 7, eval run 2** (same setup as run 1, with its fixes; drafts re-made with `draft_v2`; 83 LLM calls, 22 min; report `output/reports/step7-run2/eval-20261008T091732.*`). A first attempt crashed on STND-119 and lost its results: the secret scrubber redacted part of `password=self.params["password"]` in generated code, and the parse error aborted the run. Fixed: `scrub_code` scrubs only string literals and comments (plus literals assigned to or keyed by a secret-looking name); the eval records an unexpected error as that ticket's failure.
  - **Result:** 21/21 generated, 0 covered; reuse 0 variant / 18 method / 3 module, 0 fallbacks; validators pass 0.71 first attempt, 0.81 after repair (run 1: 0.18 / 0.35); collect 21/21 (run 1: 12/17); invented names 0; 6 tickets fixed in code; judge mean 0.94 (19 faithful, 2 partly).
  - **Found and fixed (no LLM):**
    1. *Unread-key stripping ignored inheritance* (introduced in step 5): keys read only by the base class's helper or shared test (`DownloadChecks`) were stripped, and the inherited test's entry was emptied; the validator then reported missing keys that repair couldn't keep. Stripping now follows reads like the validator (helpers, repo bases, inherited tests) and leaves unresolved tests alone. This caused 4 of the 5 failures (STND-113, 117, 119, 120).
    2. *Domain choice ignored the ticket's own component* (generate only had the draft and retrieval): replay of all 21 decisions put STND-104, 109, 110 in the wrong folder, while each ticket's component named the right one. Retrieval results now carry the ticket's components and labels; when they name exactly one domain, that is the domain; name matching is stemmed. Replay: 21/21 right.
  - **Verified:** ruff, mypy strict (92 files), pytest 632 passed, 14 deselected.
- 2026-10-09: **Stand-in v5: agent browser limit (a new scope area, the human's request).** A guardrail on how many agent browser sessions run at once, modelled on the human's generic description: per tenant; default 3; a capability set per tenant and read back through the capabilities API; at the limit a connection attempt gets HTTP 429 with body `Browser limit reached` before the WebSocket upgrade; a session close (disconnect) frees the slot; a changed limit applies to the next attempt and never cuts open sessions. Load tests stay out of scope; this is a functional limit.
  - **App:** numeric capability `browser_limit`; a real WebSocket endpoint `/ws/browser/<tenant>` (stdlib handshake; 429 before upgrade; the slot is freed before the close frame is answered, so close-then-reconnect never races); `GET/PUT /api/settings/v1/capabilities/<tenant>` (PUT admin only), `GET /api/agent/v1/sessions/<tenant>`; console "Open browser" with the message and a list with Close; a number field on the capabilities page.
  - **Framework:** `framework/browser_sessions.py` (stdlib WebSocket client: handshake check, masked close frame); `self.browsers` on the base class, closed after every test; page objects `open_browser()`, `close_browser(n)`, `open_browsers`, `browser_message`, `capabilities.browser_limit`; `BasePage.click_nth`.
  - **Tests (11 functions, 13 ids):** API class `TestAgentBrowserLimit` (refused at the limit, parametrized over limits 1 and 3; slot freed; per tenant; lowered limit keeps sessions; read back per tenant; non-admins refused), UI class `TestAgentBrowserConsole` (limit message; close frees a slot), and `test_settings_capabilities_browser_limit`. Tickets STND-122..127 (fixed), manifest, 6 new eval pairs (27 in the stand-in set). CONVENTIONS section.
  - **Checks:** replays of every expectation in-process; `tests/test_standin_sessions.py` drives the real handshake on 127.0.0.1 through a new opt-in `loopback` marker (the network guard allows literal loopback addresses only; a guard test proves anything else is still refused). `check-suite standin --collect`: clean, 79 static ids = 79 collected. Deterministic retrieval: recall@10 1.0 on all 6 new tickets (stand-in mean 0.963). The stand-in's UI share dropped to 79% (the area is API-heavy); the mix test's floor is now 0.75, with the reason in a comment.
  - **Verified:** ruff, mypy strict (92 files), pytest 650 passed, 14 deselected.
- 2026-10-09: **Live eval on the 6 browser-limit tickets** (STND-122..127; generation stage, leave-one-out, judge; 24 LLM calls, 4.8 min; report `output/reports/v5-limit/eval-20261009T075708.*`): 6/6 generated, validators pass on the first attempt 6/6 (0 repairs), sandbox collect 6/6, invented names 0, judge mean 0.95 (all faithful). The generated tests use the new framework pieces correctly (`self.browsers.open_many/connect`, 101/429 and the refusal message, capabilities PUT as the service user, the API-test message style).
  - **Found:** STND-122 and STND-126 became new modules that copied the scaffold of the class they belonged in: their class scores (0.39, 0.38) missed `method_min` 0.40 by a hair. Word scores can't separate this from an unrelated draft in the same folder (the print-policy scenario scores 0.32 vs 0.18, similar to 0.39 vs 0.25), but the class name can: `TestAgentBrowserLimit` is named after the draft's subject; `TestFilesDownloads` says nothing about printing.
  - **Fixed (logic):** a method also goes to a class named after the draft's subject (a name word, other than the domain's, that the draft uses) when its score is at least `reuse.method_named_min` (0.25). Name words that most of the domain's tests use don't count (`NAME_WORD_MAX_SHARE` 0.75: "download" is in 100% of file tests; "browser"/"limit" in 57% of agent tests); without that, STND-118 (DLP) would have gone to `TestFilesDownloads`. Replays: the 6 new tickets go to their named classes (STND-127 stays a module: no API class in its folder); the earlier 21 decisions are unchanged; the print-policy scenario stays a module. Capability gates: `browser_limit` for the agent and settings components (the eval's one reviewer warning).
  - **Variants:** still none live; with each ticket's own test left out, the parametrized refused test was the one removed for STND-122.
  - **Verified:** ruff, mypy strict (92 files), pytest 651 passed, 14 deselected.
- 2026-10-09: **The variant path, measured live for the first time** (the human's request). New synthetic ticket STND-128 ("a browser limit of 2 is not enforced"; linked to `test_agent_browser_limit_refused`, parametrized over [1, 3]), run with `--no-leave-one-out` so the test to extend stays in place; report `output/reports/v5-variant/eval-20261009T082319.*`, 4 LLM calls.
  - **Before the run, two real gaps fixed in `generate/patch.py`:** (1) parametrize lists of whole numbers are supported (written without quotes; the new value must be a whole number), and the new value comes from the draft input named like the argument (`browser_limit` = 2 for `limit`); (2) a number restated in an expectation section (an open count equal to the limit) follows the changed value; equal numbers in seed data are left alone (may be coincidence).
  - **Result:** decision "variant of test_agent_browser_limit_refused"; patch `[1, 3]` -> `[1, 3, 2]` plus an entry cloned from case 3 with `browser_limit` 2 and expected `open` 2; validators pass first attempt; sandbox collect ok. The case was planned by the LLM (`variant_v1`, 1 call): the primary draft had no variants (the limit was only in its preconditions), so code had no input to plan from, as designed.
  - **Also:** the eval no longer reports a leave-one-out violation when leave-one-out is off.
  - **Verified:** ruff, mypy strict (92 files), pytest 652 passed, 14 deselected.
- 2026-10-09: **Step 7, eval run 3** (the original 21 stand-in tickets, same setup as runs 1-2 with all fixes since; drafts cached from run 2; 65 LLM calls, 14.7 min; report `output/reports/step7-run3/eval-20261009T090053.*`). **Step 7 done.**

  | | Run 1 | Run 2 | Run 3 |
  |---|---|---|---|
  | Generated | 17 (4 false covered) | 21 | 21 |
  | Validators pass, first attempt / after repair | 0.18 / 0.35 | 0.71 / 0.81 | **0.90 / 1.00** |
  | Collect in the sandbox | 12/17 | 21/21 | 21/21 |
  | Invented names, first attempt | 2 | 0 | 2 (both repaired) |
  | Reuse: method / module | 9 / 8 | 18 / 3 | 18 / 3 |
  | LLM calls / time | 114 / 29 min | 83 / 22 min | 65 / 15 min |
  | Judge mean (unvalidated) | 0.93 | 0.94 | 0.94 |

  - The run-2 failures are gone: STND-113, 117, 119, 120 (inheritance stripping) pass; STND-104, 109, 110 land in their own folders and classes (`TestRules`, `TestTenantsSecondary`, `TestPolicyApi`).
  - **Left (judgment, not bugs):** STND-120 became a method in `TestFilesArchives` rather than `TestFilesViewer`: with its own test left out, `TestFilesViewer` holds only the inherited shared test, so nothing in it matches; the first attempt used the viewer class's variant attribute `delivery` and was repaired. STND-118 and STND-121 are new modules (scaffolds from `TestFilesDownloads` and `TestAgentBrowserLimit`) where a reviewer might prefer `TestFilesScanning` / `TestAgentApi`. Three reviewer warnings are docstring-claim heuristics.
- 2026-10-09: **Console-log reader calibrated on a real failed log** (the human's, kept in the git-ignored `.scratch/private/`; only its shape is used). It was a setup failure: the test host couldn't be resolved, so no browser started and no remote-browser link was printed. What it showed, and what changed in `results/console.py`:
  - block titles for long ids have one underscore each side (`_ ERROR at setup of Class.test _`), and `_ _ _` lines inside a traceback separate frames: titles now match `_+ title _+`, separators are skipped (the old `_{3,}` pattern found no block at all);
  - chained exceptions print several `E` lines (`socket.gaierror`, then `NewConnectionError`, ..., then `requests.exceptions.ConnectionError`): the error type and message come from the short-summary line when there is one, else from the **last** exception in the block; exception names no longer need to end in `Error` (`gaierror`);
  - new verdict **environment** when every failure is a connection/network error (`results.environment_errors`): the run couldn't reach the system, which says nothing about the test (rerun, nothing to repair).
  - The real failed log now reads: 1 result, `error`, `requests.exceptions.ConnectionError`, no link, verdict environment; the real passed log still reads passed. Synthetic fixture `tests/fixtures/runs/connection_error.log` in the same shape (invented names).
  - **Still open:** a real failure that reaches the browser (with its remote-browser link), to place the link line.
- 2026-10-09: **Decision (human): keep the stand-in's UI-share floor at 75%.**
- 2026-10-13: **First real test cases (private run).** The human supplied two real QE test-case specifications (redacted further and generalized at their request; kept only in the git-ignored `.scratch/private/`, with the private model of the pieces they need, the outputs, and the cache). Both went through the full pipeline against a private copy of the stand-in extended with generic equivalents: both became methods in the right class, passed every validator on the first attempt, collected in the sandbox, and were judged faithful to their specifications (8 LLM calls). One test followed its specification step for step but seeded data in a different structure from the rest of the suite, which no static check caught: it would load, then fail at its first step on a real run (confirmed by replaying it against the model).
  - **Fixed (general):** new validator `data_shape`: every value must have the shape (list, object, text, number, true/false) that the suite's data files use for the same key path; expectation sections are skipped (a response's shape depends on its endpoint). The stand-in and the private copy stay clean; re-run, the case failed the check on the first attempt, was fixed in one repair round, and then ran correctly against the model.
  - **Verified:** ruff, mypy strict (92 files), pytest 655 passed, 14 deselected.
- 2026-10-22: **Rule change (human): bounded agents inside the fixed workflow.** The backbone stays a fixed workflow; four bounded agents are allowed inside it, in this order: (1) investigation during retrieval, (2) missing-piece proposals, (3) repair, (4) log triage. Every agent uses only the project's own read-only tools (plus the validators and the sandbox collect), never runs tests against real systems (a human runs them), has step and token budgets from config, and everything it returns is checked by code. CLAUDE.md (Pipeline) updated.
- 2026-10-22: **Agent 1: the retrieval investigator** (`retrieve/investigator.py`, prompt `investigator_v1`). Opt-in (`retrieval.investigator.enabled`, default off); when on it replaces the follow-up rounds. Each turn the LLM sees the ticket, the first results, its earlier tool calls with their outputs, and what it has kept so far, and returns `InvestigatorStep` (thought, actions, keep, missing, done).
  - **Tools (read-only over the index):** `search` (BM25), `grep` (identifier, verified against the catalog), `open` (a chunk's code; for a test, its ids and data keys), `callers`, `tests_using`, `chain` (page-object members one level down), `data` (a test's entries). Every output is scrubbed and cut to `max_tool_output_chars`.
  - **Budgets:** `max_steps` turns (6), `max_actions_per_step` (4; extra actions are ignored, repeats aren't rerun), `max_transcript_chars` (older outputs are removed first, the calls stay listed), `max_kept` (12); bad JSON is retried within `llm.max_retries_on_bad_json`.
  - **Checked by code:** kept ids that don't exist are dropped and recorded (`dropped_ids`); kept chunks are fused into the pool with reason `investigator` and stay in the hits even below the top_k. The run is stored as `RetrievalResult.investigation` (turns, tool calls, kept, missing, how it stopped: done / budget / no_actions).
  - **Not yet:** a live comparison against the follow-up rounds (needs LLM calls; ask first); feeding `missing` into agent 2.
  - **Verified:** ruff, mypy strict (93 files), pytest 664 passed, 14 deselected.
- 2026-10-22: **Haiku 5.5 runs (the human's request), every LLM step on `claude-haiku-5-5`** (set by env var for the runs; config default stays Sonnet 5.5). Reports in `output/reports/haiku55/`.
  - **Retrieval, 28 stand-in pairs (linked test kept in the index):** no LLM 0.964 / MRR 0.251 (0 calls); rewrite only 0.982 / 0.312 (28 calls, 3 min); rewrite + follow-up rounds 0.929 / 0.295 (28 calls: no round ever triggered, so the gap to "rewrite only" is rewrite variance); **investigator 1.000 / 0.412** (194 calls, 30 min). The investigator invented no chunk ids (0 dropped) and kept every linked test, but 26 of 28 runs used all 6 turns.
  - **Its "missing" list (~60 claims) is not usable as is:** most are "not opened" notes or guesses at the app's root cause; some are wrong (`verify_targets` "not found" because grep refused a name with too many uses); a few are real (no UI member to add a blocklist hash, no toast locator outside the console message). Before agent 2 it needs a narrower format (missing members/helpers only) and a code check against the catalog. One claim echoed a rule from the CLI's user-level settings, not the suite: the CLI provider still picks up user configuration (reports are git-ignored).
  - **Fixed first:** the retrieval eval scored every hit, and investigator-kept hits can run past the top_k; scoring now stops at k, and each pair records its investigation.
  - **Generation, the 21 run-3 tickets (leave-one-out, fresh Haiku drafts, default retrieval, sandbox via podman; 86 calls, 26 min):** validators first attempt 0.952 / after repair 1.000 (Sonnet run 3: 0.905 / 1.000); invented names on the first attempt 2 (run 3: 2); collect 21/21; repair rounds 0.05; warnings per test 0.29 (0.24); reuse method/module 17/4 (18/3). Judge 0.894 by a Haiku judge (run 3's 0.94 was a Sonnet judge; not comparable). STND-102 became a new module: the Haiku draft's class match was 0.38, under `method_min` 0.40 (Sonnet's draft placed it as a method); the code itself follows the suite's patterns.
  - **Reading:** with the deterministic structure doing retrieval, reuse, copying and validation, Haiku 5.5 matches Sonnet 5.5 on every mechanical metric here; it was not faster through the CLI. The investigator is the one step where the model has to plan, and it is the costly part.
- 2026-10-22: **Cost in the eval (the human's request).** `llm/meter.py`: `UsageMeter` wraps the client in `run_eval` and adds up calls, tokens and the provider-reported cost (the Claude CLI's `total_cost_usd`, an API-price estimate whatever the billing plan). Reports show cost per retrieval run, per generation ticket and in total; "≥" marks a lower bound when some calls had no price, "n/a" when nothing was metered. Earlier reports have no cost.
  - **Verified:** ruff, mypy strict (94 files), pytest 668 passed, 14 deselected.
- 2026-10-23: **Part A: the suite map (`suitemap/`, command `map`), code only.** Agreed plan with the human: A) a shallow map from code, B) area guides written once by a strong model (Sonnet by default, Opus by config; a $50 ceiling, `--estimate`, `--budget`), C) measure on the stand-in, D) finding real missing pieces, E) optional Haiku rerun of the investigator, F) agent 2. Idea taken from how a security scanner maps a repo: structure from parsers, meaning from the LLM, built once and reused by a weaker model.
  - **Areas:** the generator's domains; tests outside them get an area for their own folder (only files directly in it).
  - **Per area:** test classes (bases, decorators, setup calls with keywords), test shapes, markers, page-object chains, page actions called, base-class helpers, functions the test files import or define, assertions, fixtures, data keys with their role (seed / expectation / per entry / read by the test), expectations (`<section>: <method> <path>`, all-digit path segments as `N`), brace placeholders, skips, one typical test per shape.
  - **Stamps:** each area lists the files it was built from with sha256 and a digest over them; `map.json` records the commit when the repo is a git checkout; a rerun reports the changed areas.
  - **Overview and coverage:** base classes, page areas, helpers shared by several areas, marker values; coverage = test-side code nothing in the repo references (page objects and members, base-class helpers, functions in modules test files import), pytest's own setup hooks excluded, product code not listed.
  - **Checked on two shapes:** the stand-in (7 areas, 55 tests; 6 unreferenced page members, each confirmed by grep) and public httpx (3 areas, 539 tests, no page objects or data files, under 4 s). httpx found two bugs fixed before commit: root-level tests had no area, and method calls (`client.get`) were counted as a repo function of the same name; functions now resolve through the test file's own imports and definitions.
  - **Verified:** ruff, mypy strict (98 files), pytest 679 passed, 14 deselected.
- 2026-10-23: **Part B: area guides (`guides/`, command `guides`).** A strong model writes one guide per area, once; the generator reads the ticket's area guide on every ticket.
  - **One call per area, no exploring:** code picks the material (area summary, typical tests with one data entry, class scaffold, page objects reached by the area's chains, base-class helper methods it calls) up to `guides.max_input_tokens` (20k); a piece that doesn't fit is skipped whole. Prompt `guide_v1` with a fixed outline (`GuideOutput`: summary, how to add a test, classes, page objects, helpers, data, examples, pitfalls).
  - **Model:** the new `guide` step (default the provider's model, Sonnet 5.5; Opus via `step_models`).
  - **Cost control:** `guides.max_budget_usd` 50 is a ceiling `--budget` can't pass (refused); before each call the worst case (estimated input + the full output cap at `guides.prices`) must fit in what is left, so a run never goes over; actual cost is the provider's reported cost, else tokens x prices; no price or an unknown cost stops the run; `max_areas_per_run`; `--estimate` makes no calls. Prices: Anthropic first-party API rates from the claude-api reference (cached 2026-10-06): Opus 5.5 $4/$20, Sonnet 5.5 $2/$10, Haiku 5.5 $0.10/$0.50 per million tokens.
  - **Checked by code:** refs (classes, page-object chains or members, helpers, example test ids) that aren't in the index are removed and listed; backticked names in the prose that match nothing are listed as unverified (they may be literal values).
  - **Cache and staleness:** a guide stores the area digest, sources, model, prompt version, what it was shown, usage and cost; same digest + prompt + model = up to date (skipped); `--force` rebuilds. In generation a guide whose source files changed is still used and labelled stale (`ReuseOutcome.guide`).
  - **Generation:** the guide goes into the context next to the conventions, capped at `guides.max_context_tokens` (1500) by dropping whole sections from the end.
  - **Stand-in estimate (Sonnet):** 7 areas, 2.5k-6.3k input tokens each, worst case $0.35 in total.
  - **For Part C:** guides built from the full repo describe the tests that leave-one-out removes; the eval must build its guides from a copy without the eval's linked tests, and point `guides.dir` at them (eval repo copies have other folder names).
  - **Verified:** ruff, mypy strict (105 files), pytest 694 passed, 14 deselected.
- 2026-10-23: **Part C, first attempt: both guide runs failed; two bugs fixed.** On the stand-in copy without the 21 eval tests (`.scratch/standin-noeval`, 34 own tests), Sonnet spent $1.30 (estimate $0.34) and Opus $2.42 against a $2.00 budget (estimate $0.68); every call failed validation, so no guide was written. (Costs are the Claude CLI's reported API-price estimates.)
  - **Schema bug (general):** `strict_schema` dropped JSON-Schema keywords (`title`, `examples`, `format`, `pattern`, ...) also when they were field names under `properties`, so `GuideOutput.examples` was never in the schema the model saw, and validation required it. Fixed; a comparison of all nine LLM output schemas before and after shows only `GuideOutput` changed, so earlier results are unaffected.
  - **Budget bug:** the worst case missed the Claude CLI's own input per call (6k-23k tokens), the output cap isn't enforced by the CLI (Opus ~5.3k tokens against 4k; its thinking counts as output), and the budget was checked once per area while JSON retries made up to three calls. Now `BudgetGuard` (`guides/budget.py`) checks the worst case before every call, retries included; per-call overhead (`call_overhead_tokens` 25000) and output (`output_allowance_tokens` 8000) are raised by what real calls use and saved in `calibration.json` next to the guides (never lowered below the configured values).
  - **Corrected estimates:** Sonnet $0.97, Opus $1.94 worst case for the 7 areas.
  - **Verified:** ruff, mypy strict (106 files), pytest 697 passed, 14 deselected.
- 2026-10-23: **Part C, measured: guides by Sonnet and Opus, used by Haiku.** Guides built from the stand-in copy without the 21 eval tests (no leakage); reports in `output/reports/partc/`, guides in `.scratch/guides-noeval-{sonnet,opus}/`.
  - **Guides (second attempt, after the fixes):** 7/7 areas each, all first try. Sonnet $0.31 (worst case $0.97), $0.03-0.07 and 15-32 s per area; Opus $0.70 (worst case $1.94), $0.06-0.15 and 20-37 s per area. Real calls used 6k-11k input tokens (a few thousand of CLI overhead, not the 25k planned) and 1.6k-3.6k output tokens. Part C spend in total: $3.73 (failed first attempt) + $1.01 (guides) + $0.47 (three eval runs) = $5.21 (the Claude CLI's API-price estimates).
  - **Check, calibrated on this run:** it first flagged nested data keys, request methods, decorator values and `unittest` assertions (none invented) and removed `self.check.assertEqual` three times; it now accepts names the repo's code uses, data keys at any depth and literal values from data and decorators. Across the 14 guides one mention stays flagged, correctly: `delete_test`, a vague name Sonnet made up. A guide noted a class helper missing from its material: the scaffold now carries the class's own non-test methods (for guides built from now on). The raw model output is stored so the check can be re-run.
  - **Haiku 5.5 generation on the 21 run-3 tickets** (leave-one-out, the same cached Haiku drafts in all three runs, so only the guide differs; one run each):

  | | No guides | Sonnet guides | Opus guides |
  |---|---|---|---|
  | Validators pass, first attempt / after repair | 0.952 / 1.000 | **1.000** / 1.000 | **1.000** / 1.000 |
  | Invented names, first attempt | 2 | **0** | **0** |
  | Repair rounds | 1 | 0 | 0 |
  | Collect in the sandbox | 21/21 | 21/21 | 21/21 |
  | Reviewer warnings (docstring-claim heuristic only) | 4 | 12 | 7 |
  | Placement method / module | 17 / 4 | 17 / 4 | 17 / 4 |
  | LLM calls / cost | 44 / $0.16 | 42 / $0.15 | 42 / $0.16 |

  - **Reading:** the gain is one ticket (STND-112, which needed a repair without a guide), on a baseline that was already high, from one run each: a direction, not proof. Invented names went to 0 with either guide. Per-ticket cost didn't change (the guide adds ~1.5k context tokens; Haiku is cheap), so a guide costs its one-time build only. The extra warnings come from longer numbered docstrings in guided tests (the guide's steps are restated and the claims heuristic can't match all of them), not from wrong checks. Opus guides did not beat Sonnet guides here, at twice the price; Sonnet stays the default.

## Global open questions (for the human)
- Which LLM provider/endpoint will the company environment require?
- Is there an existing conventions doc for tests at the company?
- ~~Are most company bug tests API-level or UI-level?~~ **Resolved 2026-10-05:** ~85–90% browser UI tests, a minority API, a few hybrid. Frontend/UI test generation is in scope.
- Which marker values (priority levels, suites, projects) does the target use? **Resolved 2026-10-05:** use generic placeholders in config for now (priorities `p0`–`p3`, suites `smoke`/`regression`, a generic project name); the human sets the real values later.
- What ticket-id format appears in skip reasons? **Resolved 2026-10-05:** the standard Jira pattern (uppercase project key, dash, number), configurable as a regex.
- Approval to bring this code into the company environment (IP, license, dependency review).

## Changelog
| Date | Phase | Change |
|---|---|---|
| – | – | File created |
| 2026-10-05 | 0 | Phase 0 skeleton built and verified; marked ✅ Done |
| 2026-10-05 | 1 | Phase 1 ticket normalizer built and verified; marked ✅ Done |
| 2026-10-05 | all | Scope update from target-suite patterns: test output is a code + JSON data pair; Chunk includes decorators/markers/JSON entries; symbol catalog adds page-object property chains; new data-consistency validators; config-block reuse; TestCaseDraft gains markers/test_kind/deployment_type; `pytest --collect-only` is the primary execution check; git-history mining for eval pairs; UI tests in scope. New Phase 3 (synthetic stand-in); former Phases 3–8 renumbered to 4–9. Phase 2 paused. |
| 2026-10-05 | all | Human approved the scope update, incl. the 3 hard-constraint wording changes and moving priority/component into `markers`. Answers: `selenium` in the stand-in; `http.server` for the fake app; host `--collect-only` only for the hand-written stand-in; httpx API drafts OK for Phase 2; generic placeholder marker values and a Jira-style ticket-id regex in config. Phase 2 resumed. |
| 2026-10-05 | all | New Hard Constraint 9: Claude Code works only inside this repo (no reading, searching, or writing elsewhere; temp files in git-ignored `.scratch/`). |
| 2026-10-05 | 2 | Phase 2 draft generation built and verified (offline checks, live run, human Markdown review); marked ✅ Done |
| 2026-10-05 | 3 | Stand-in built and verified; all DoD items pass except the human name review |
| 2026-10-05 | 3 | Human name review done; Phase 3 marked ✅ Done. Phase 4 started |
| 2026-10-05 | 4 | Indexer built and verified (stand-in + httpx, ids vs collect-only, search, catalog chains, cache); marked ✅ Done |
| 2026-10-05 | 5 | Retrieval built; deterministic recall@10 baseline httpx 0.591 / stand-in 0.667; marked ✅ Done (LLM-mode baseline pending a live run) |
| 2026-10-05 | 5 | Retrieval references moved to the syntax tree (`Chunk.refs`); LLM-on baseline measured: httpx 0.618, stand-in 1.000 recall@10 |
| 2026-10-05 | 5 | Deterministic feature-based reranker with per-file cap and minimum tests; LLM-on recall@10 httpx 0.772, stand-in 1.000; LLM-reranker plan recorded |
| 2026-10-05 | 6 | Code generation built and verified offline; live run and human style check pending |
| 2026-10-05 | 6 | Live generation run: 5/5 pairs; STND-104 reads a data key its entry lacks (proposed Phase 7 data-key validator) |
| 2026-10-05 | all | Priority marker values changed to lowercase `p0`–`p3` (human request) in config, the stand-in suite and its data, and tests. Earlier log entries keep the values as written then. |
| 2026-10-06 | – | Pushed the repo to github.com/DangNguyen254/ai-in-testing (human's request): merged GitHub's initial commit (LICENSE only) instead of force-pushing; kept the LICENSE holder DangNguyen254 |
| 2026-10-06 | all | Target patterns updated from the human's real-framework comparison (CLAUDE.md patterns, guardrails, data models, phases). New Phase 3b (stand-in v2); Phase 6 to be reworked after it; Phase 7 validator list extended |
| 2026-10-06 | – | Handoff section added (session moves to Claude Code desktop) |
| 2026-10-06 | 3b | Stand-in v3 built and verified (policy app with top bar, four test shapes, targets/interactions replayed, rule (1) checked on the stand-in); generate_v3 prompt and self-checks |
| 2026-10-06 | 6 | Third style check (STND-106): semantic gaps traced to the stand-in; stand-in patched (sorting, page size, name cap, `total_count`), `generate_v4`; no LLM reviewer step (human decision) |
| 2026-10-06 | 6 | Per-step models (`step_models`, `LLMRequest.model`); Haiku 4.5 trial for the retrieval steps was worse, slower, not cheaper; kept Sonnet (human decision) |
| 2026-10-06 | 6 | Closed (real-codebase style check deferred to integration; human decision) |
| 2026-10-06 | 7 | Validators (errors + reviewer warnings), repair loop, container sandbox (Podman verified); marked ✅ Done |
| 2026-10-06 | 8 | Eval harness: 31 pairs (+2 mined), mining, generation eval with leave-one-out and sandbox, judge, report; baseline run; marked ✅ Done |
| 2026-10-07 | – | Porting preparation: `check-suite` (calibration), configurable sandbox image (base image, requirements), registry-credential isolation, re-export fix |
| 2026-10-07 | – | Stand-in v4 (file policies, AI browsing agent, reuse patterns) and inheritance / class-variant support in indexer and validators |
| 2026-10-06 | 3b | Stand-in v2 built and verified (patterns checked by project tests; indexer reads array data and infers unannotated types; config `data`; `Chunk.data_format`); marked ✅ Done. v1 generator tests skipped until `generate_v2` |
