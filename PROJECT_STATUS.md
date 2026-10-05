# PROJECT_STATUS.md

Tracks progress, scope, and acceptance criteria for each phase. Read together with `CLAUDE.md`, whose hard constraints and guardrails apply to **every** phase.

**How to use this file (for Claude Code):**
- Before starting a phase, check that the previous phase is `✅ Done`.
- Update the phase's status, checklist, and log when you start, pause, or finish.
- A phase is `✅ Done` only when **every** Definition of Done (DoD) item is checked.
- Put anything unresolved under **Open questions** and stop for the human to answer.

**Status legend:** ⬜ Not started · 🟡 In progress · ⏸️ Blocked · ✅ Done

---

## Overview

| Phase | Name | Status | Depends on |
|---|---|---|---|
| 0 | Skeleton | ✅ | – |
| 1 | Ticket normalizer | ✅ | 0 |
| 2 | Draft generation | ⬜ | 1 |
| 3 | Indexer (Python) | ⬜ | 0 |
| 4 | Retrieval | ⬜ | 2, 3 |
| 5 | Code generation | ⬜ | 4 |
| 6 | Validators, repair, sandbox | ⬜ | 5 |
| 7 | Eval harness | ⬜ | 4 (minimal), 6 (full) |
| 8 | Rust support | ⬜ | 7 |

Phase 3 depends only on Phase 0, so it may be built in parallel with Phases 1–2 if useful.

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
- GitHub has no "components" field. `Ticket.components` stays empty for GitHub unless `tickets.github.component_label_prefixes` is configured (e.g. `["component:"]`). httpx labels like `proxies` or `http/2` are not treated as components. Phase 2's insufficient-info check must therefore not rely on `components` alone for GitHub tickets.

**Log:**
- 2026-10-05: Started. Fixtures: `encode/httpx` #2985 (no sections, no comments), #1482 (full template), #1498 (code steps, multi-paragraph expected/actual), #1234 (free-form, no sections), #914 (open, 43 comments, external links). Saved as raw `issue.json` + `comments.json` under `tests/fixtures/github/`.
- 2026-10-05: Built. `Ticket`/`Comment`/`SourceInfo` models (`Ticket` adds `comments_omitted`; `source` is `{system, ref, url}`). `GitHubIssueSource` (httpx; optional `GITHUB_TOKEN`; comment pagination capped by `tickets.github.max_comment_pages`; clear errors for rate limit with reset time/retry-after, 404/410, 401, PRs, network). `JiraExportSource` (local file only; single issue, `{"issues": [...]}`, or list). Normalizer: ADF and wiki markup → Markdown → plain text; HTML template comments and markup stripped; fenced code kept verbatim; steps/expected/actual from headings, bold lines, and `Label:` lines, ignoring code; links from prose URLs and `#123` refs (not code or inline code). Long threads keep first + latest comments up to `normalize.max_comments` (50); each comment capped at `normalize.max_comment_chars` (4000) on a line boundary. Optional Jira `field_map` for custom steps/expected/actual fields. CLI `normalize <ref> [--jira-export F] [--out F] [--raw-out F]`. New config sections `tickets.github`, `tickets.jira`, `normalize` (additive to the Phase 0 `Settings`).
- 2026-10-05: Verified. ruff check + format, mypy strict (28 files), pytest 147 passed (1 live deselected). Autouse fixture blocks sockets in all non-live tests (with its own test). Live test (`pytest -m live`) passed against the real API, and `ticket2test normalize https://github.com/encode/httpx/issues/1498` gives the same result as the fixture. Done.

---

## Phase 2: Draft generation
**Status:** ⬜ Not started

**Goal:** Turn a `Ticket` into structured `TestCaseDraft`(s) a QE can review before any code is written.

**Inputs:** `Ticket` (from Phase 1).

**Outputs:**
- `TestCaseDraft` model (fields per `CLAUDE.md`)
- First real `LLMClient` implementation (provider chosen via config)
- `prompts/draft_v1.md`
- `draft/` module with structured output, JSON validation, and retry-with-error
- Secret scrubber in `security/`, applied to all prompt input
- Markdown renderer for human review
- CLI: `ticket2test draft ticket.json --out drafts/`

**Constraints:**
- Temperature 0
- Max JSON retries from config (default 2); then fail with a clear error
- Must return `status: "insufficient_info"` with `missing_info[]` when the ticket lacks steps, expected behavior, or an identifiable component
- Each draft records its `prompt_version`
- One ticket may produce 1 primary draft (reproduce + verify fix) plus 0–3 edge-case drafts. No more.

**Definition of Done:**
- [ ] Runs end-to-end on the 5 fixture tickets (live test)
- [ ] A deliberately vague ticket returns `insufficient_info`
- [ ] Malformed LLM output triggers a retry and then a clean failure (tested with the fake LLM)
- [ ] Secret scrubber has unit tests for at least: API-key-like strings, bearer tokens, passwords in URLs
- [ ] Markdown output is readable by a non-engineer (checked by a human)

**Open questions:** –

**Log:** –

---

## Phase 3: Indexer (Python)
**Status:** ⬜ Not started

**Goal:** Make a codebase searchable by structure and keywords, and know which names really exist.

**Inputs:** A local path to a target repo (via `RepoSource`).

**Outputs:**
- tree-sitter Python parsing
- Chunks (`Chunk` model) by test function, including related fixtures and parametrize data; also chunks for non-test functions and classes
- Symbol catalog: every function, class, method, and module name, with file and line
- BM25 index with identifier splitting (`snake_case` / `CamelCase` → words)
- Index persisted to disk (git-ignored cache dir); rebuild only changed files when possible
- CLI: `ticket2test index <repo_path>` and `ticket2test search "<query>"`

**Constraints:**
- Read-only access to the target repo
- Never chunk mid-function
- Skip vendored, generated, and binary files (configurable ignore list)
- Must handle a repo of ~1,000 Python files in a reasonable time (target under 2 minutes)

**Definition of Done:**
- [ ] Indexing `httpx` completes and the cache reloads without re-parsing
- [ ] For 5 hand-picked known functions, a search returns their tests in the top 5
- [ ] Symbol catalog lookup confirms existence and non-existence correctly (tested)
- [ ] Identifier splitting has unit tests
- [ ] Parsing errors in a single file are logged and skipped, not fatal

**Open questions:** –

**Log:** –

---

## Phase 4: Retrieval
**Status:** ⬜ Not started

**Goal:** Given a ticket and draft, find the relevant code and the most similar existing tests.

**Inputs:** `Ticket`, `TestCaseDraft`, index and symbol catalog (Phase 3).

**Outputs:**
- `prompts/query_rewrite_v1.md`: ticket wording → likely code terms
- Retrieval pipeline: query rewrite → BM25 + grep → merge and de-duplicate → AST expansion (callers, callees, related tests) → ranked list
- Follow-up rounds: the LLM may request extra searches when results are thin
- Retrieval result records every chunk ID and why it was retrieved (bm25 / grep / expansion / follow-up)
- CLI: `ticket2test retrieve ticket.json --draft draft.json`
- **Minimal eval** (pulled forward from Phase 7): recall@k on a small set of issue ↔ fix-PR pairs

**Constraints:**
- `retrieval.top_k` and `retrieval.max_followup_rounds` from config (defaults 10 and 2)
- Follow-up rounds may only call the project's own search tools. No arbitrary shell or network.
- No embeddings in this phase

**Definition of Done:**
- [ ] At least 10 public `httpx` issue ↔ fix-PR pairs collected in `eval_data/` (IDs/URLs only)
- [ ] Recall@10 measured and recorded in the log below (no target yet; this is the baseline)
- [ ] Follow-up rounds provably stop at the configured cap (tested)
- [ ] Each retrieved chunk carries its retrieval reason

**Open questions:**
- After the baseline: is recall good enough, or do we need embeddings? Decide based on data.

**Log:** –

---

## Phase 5: Code generation
**Status:** ⬜ Not started

**Goal:** Generate runnable test code from a draft, in the style of the existing tests.

**Inputs:** `TestCaseDraft`, retrieval results (Phase 4), optional conventions doc (path from config).

**Outputs:**
- Context builder: ranks and trims chunks to fit `context.max_tokens`, putting similar tests first as few-shot examples
- `prompts/generate_v1.md`
- `GeneratedTest` with full traceability (ticket, draft, chunk IDs, prompt version)
- CLI: `ticket2test generate draft.json --retrieval retrieval.json --out generated/`

**Constraints:**
- Never truncate mid-function when trimming context
- The conventions doc, if configured, is always included in context
- Secret scrubber runs on both the prompt and the generated output
- Output files go only to the project's output dir, never into the target repo

**Definition of Done:**
- [ ] Generates a test file for each of 5 drafts (live test)
- [ ] Context never exceeds the token budget (tested)
- [ ] Every `GeneratedTest` has complete traceability fields
- [ ] Generated code follows the style of retrieved examples (spot-checked by a human)

**Open questions:** –

**Log:** –

---

## Phase 6: Validators, repair loop, sandbox
**Status:** ⬜ Not started

**Goal:** Catch bad generated code cheaply before a human sees it, and fix it automatically when possible.

**Inputs:** `GeneratedTest` (Phase 5), symbol catalog (Phase 3).

**Outputs:**
- Validators, each returning structured errors:
  - Syntax parses
  - Every referenced name exists in the catalog or is defined in the test
  - Imports resolve
  - Parametrize cases match their data
  - Naming conventions (configurable patterns)
- Repair loop: validator errors → LLM fix → re-validate, capped
- Sandbox runner: executes tests in a container (Podman or Docker)
- `validation_report` attached to each `GeneratedTest`
- CLI: `ticket2test validate generated/ [--run]`

**Constraints:**
- `repair.max_attempts` from config (default 3)
- Sandbox: **no network**, target repo mounted **read-only**, a writable temp dir only, `sandbox.timeout_seconds` enforced
- Generated code never executes on the host, including in this project's own tests
- If the container runtime isn't available, `--run` fails clearly. It never falls back to host execution.

**Definition of Done:**
- [ ] Each validator has unit tests with passing and failing examples
- [ ] A test calling a non-existent function is caught and reported
- [ ] Repair loop stops at the cap (tested with the fake LLM)
- [ ] Sandbox enforces no-network and timeout (tested)
- [ ] Missing container runtime produces a clear error, not host execution

**Open questions:** –

**Log:** –

---

## Phase 7: Eval harness
**Status:** ⬜ Not started

**Goal:** Measure quality per stage, so we know what to improve and can prove value.

**Inputs:** `eval_data/` issue ↔ fix-PR pairs (expand to 30+), the full pipeline.

**Outputs:**
- Metrics:
  - **Retrieval:** recall@k, MRR (ground truth = files changed in the fix PR)
  - **Faithfulness:** rate of invented names; draft-matches-ticket via LLM-as-judge
  - **End-to-end:** fail-before-fix / pass-after-fix rate (pre-fix and post-fix commits run in the sandbox)
  - **Cost:** tokens and wall-clock time per ticket
- Report as JSON + Markdown, saved per run with a timestamp and config snapshot
- CLI: `ticket2test eval --set eval_data/ --out reports/`

**Constraints:**
- LLM-as-judge results are labeled **"unvalidated"** until compared against human labels on a sample
- Eval runs are reproducible: same config + same data → comparable report
- All code execution goes through the Phase 6 sandbox

**Definition of Done:**
- [ ] At least 30 eval pairs
- [ ] One full baseline report generated and summarized in the log below
- [ ] Re-running with the same config gives consistent retrieval metrics
- [ ] Report clearly separates measured metrics from unvalidated judge metrics

**Open questions:**
- Which metric matters most to the QE team? Confirm before optimizing.

**Log:** –

---

## Phase 8: Rust support
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
- [ ] Python eval metrics show no regression versus the Phase 7 baseline

**Open questions:**
- How are Rust functions exposed to Python in the target codebase? (Affects cross-language linking.)

**Log:** –

---

## Global open questions (for the human)
- Which LLM provider/endpoint will the company environment require?
- Is there an existing conventions doc for tests at the company?
- Are most company bug tests API-level or UI-level? (Affects whether frontend support is needed.)
- Approval to bring this code into the company environment (IP, license, dependency review).

## Changelog
| Date | Phase | Change |
|---|---|---|
| – | – | File created |
| 2026-10-05 | 0 | Phase 0 skeleton built and verified; marked ✅ Done |
| 2026-10-05 | 1 | Phase 1 ticket normalizer built and verified; marked ✅ Done |
