# CLAUDE.md: Ticket-to-Test Draft Agent

## What this project is
A pipeline that turns a bug ticket into **structured draft test cases**, then into **runnable test code plus its JSON test data**, for a human QE (Quality Engineer) to review.

This repo is a **generic, company-agnostic** build developed entirely on **public data** and **synthetic data created in this repo**. All company-specific parts (ticket source, codebase, LLM endpoint, team conventions) sit behind adapters and config, so the code can later be moved into a company environment without rewrites.

**Scope:** both **browser UI tests** (page objects driving a browser, then verifying backend state) and **API tests** are in scope. UI tests dominate the target style, so frontend/UI test generation is a first-class goal, not an add-on.

## Pipeline
```
Ticket source → normalize → draft test cases (structured) → [human review]
  → query rewrite → retrieve (BM25 + grep + AST expand; then ≤2 follow-up rounds, or the
      investigator agent when enabled)
  → build context → generate test code + JSON data entries
      (few-shot from similar tests; large config blocks copied from the nearest existing entry)
  → validate (deterministic + `pytest --collect-only` in the sandbox) → repair loop (capped)
  → [human review] → output (code file + data file) → [a human runs it] → read the run's log
```
The backbone is a **fixed workflow**: code decides the steps and their order. **Bounded agents** are allowed inside it, and only these four (updated 2026-10-22 by the human):
1. **Investigation** (retrieval): the AI explores the indexed suite with read-only tools until it judges it has enough context.
2. **Missing-piece proposals**: when a needed helper or page-object member doesn't exist, the AI proposes it as a separate patch for review. It may add new code, never change existing framework code.
3. **Repair**: the AI may run the deterministic validators and the sandbox collect and decide what to change, until they pass or the budget runs out. It may not remove checks the draft requires.
4. **Log triage**: the AI reads a real run's console log and decides repair / environment problem / flag for review.

Rules for every agent: its tools are the project's own functions (read-only over the index or a repo copy, plus the validators and the sandbox); it **never executes tests against real systems** (a human runs tests; the sandbox only collects, with no network); every loop has step and token budgets from config (Hard Constraint 6); and everything it returns is checked by code before it is used.

---

## HARD CONSTRAINTS (never violate, never work around)

1. **No private or company data.** Never add, fetch, hardcode, or reference any non-public codebase, ticket, name, URL, internal tool, or credential. Use only public repositories, public issue trackers, and synthetic data invented in this repo (generic names only, e.g. the `standin/` repo).
2. **No secrets in the repo.** API keys and tokens come only from environment variables. Commit `.env.example` with placeholder values only. `.env` must be listed in `.gitignore`.
3. **Never execute generated code on the host.** Generated tests are untrusted. Run them only inside a container (Podman or Docker) with no network access and no host mounts except a read-only copy of the target repo and a writable temp dir. This includes `pytest --collect-only`, which imports the generated module.
4. **Read-only on target repos.** The pipeline never modifies, commits to, or pushes to the target codebase. It writes only to its own output directory. Reading git history is allowed.
5. **No hardcoded vendor lock-in.** All LLM calls go through the `LLMClient` interface. No provider SDK may be imported outside `llm/`.
6. **No unbounded loops.** Every retry, repair, and search loop has an explicit max from config. No exceptions.
7. **License.** The repo is MIT-licensed. Only add dependencies with permissive licenses (MIT, BSD, Apache-2.0). Flag anything else before adding it.
8. **Do not log full prompts or full LLM responses by default.** They may contain source code. Logging these requires an explicit `--debug-log` flag and writes to a local, git-ignored directory.
9. **Claude Code works only inside this repo.** Claude Code must not read, search, list, write, or delete anything outside this repository's directory, including the home directory, system temp dirs, other projects, and its own scratchpad or memory directories. Temporary files go in the git-ignored `.scratch/` folder inside the repo. The only exceptions:
   - **Installed tools:** running the installed `uv`, Python, `git`, and the `claude` CLI is allowed; inspecting or changing their install locations is not.
   - **Caches and temp dirs are redirected into the repo:** pytest uses `--basetemp=.scratch/pytest`; uv uses `cache-dir = ".scratch/uv-cache"` (set in `pyproject.toml`); the `claude_code_cli` provider runs in `.scratch/claude-cli`.
   - **Public network fetches** (GitHub, PyPI, public docs) are allowed without asking, as long as everything fetched is saved into a git-ignored folder inside the repo. Any other network access needs the human's permission.
   - **Containers:** Docker/Podman containers are allowed as described in Hard Constraint 3.
   - Anything else outside the repo needs the human's explicit permission first, each time.
   - Notes Claude wants to keep across sessions go in the repo (e.g. `CLAUDE.md` or `.scratch/`), not in an external memory directory.

## GUARDRAILS (pipeline behavior)

- **Insufficient info is a valid output.** If a ticket lacks steps to reproduce or expected behavior, return `status: "insufficient_info"` with a list of what's missing. Never guess to fill the gaps.
- **Component inference.** The LLM infers the component from the ticket text, using labels as hints. If it cannot, it sets `component: "unknown"`. An unknown component alone is never a reason for `insufficient_info`.
- **No invented names.** Generated code may reference only symbols that exist in the symbol catalog (built by AST) or that are defined within the generated test itself. This includes **page-object property chains** (e.g. `nav.<area>.<page>.<member>`): every attribute/property step must resolve through the catalog. Markers must use values known to the catalog or config. The validator enforces this.
- **Code and data stay consistent.** Every generated test that reads its data entry comes with JSON entries. Each entry's identifier field (config `data.id_field`) must exactly equal a pytest-generated test id (stacked parametrize decorators: bottom decorator first), with one entry per variant; every key the test body reads (`params[...]`, `params.get(...)`) must exist in its entries. Tests that read no data may have no entry. The validator enforces this, and `pytest --collect-only` in the sandbox confirms the ids.
- **Build entries from the nearest existing entry.** Real data files are copy-paste heavy: identical seed blocks across many entries, and variants that differ by one or two values. So: (1) pick the nearest existing entry as the base; (2) copy only the sections the new test depends on (seed sections, its expectation section); (3) strip everything the scenario doesn't read, assert, or need; (4) for variants, clone the base once per parametrize value and change only the varying field; (5) re-label names that embed the source test's name, and keep the entry count equal to the variant count. The LLM chooses the sections and the changes; the copying is deterministic. Unique names use the suite's placeholder (`{test_id:N}`). Every seed or expectation key must be read by the test or consumed by the framework or a helper the test calls.
- **Generated output follows the suite's style rules** (from config `style`: indent, line endings, final newline, import order, annotations, JSON formatting). A deterministic formatter applies them; the validator checks them instead of trusting neighbouring files.
- **Structured output only.** Every LLM step returns JSON validated by a Pydantic model. On a parse or validation failure, retry with the error message included (max retries from config), then fail cleanly.
- **Token budget.** Context building enforces a max token budget from config. Trim by relevance rank, never truncate mid-function.
- **Secret scrubbing.** Before anything is placed in a prompt, run a basic secret scanner (regexes for keys, tokens, passwords, connection strings) and redact matches. The same scrubber runs on generated output.
- **Determinism where possible.** Use temperature 0 for extraction and validation-related steps. Use seeds where the provider supports them. The Claude Code CLI exposes no temperature, and current Claude models reject non-default values, so Claude-backed runs are best-effort; treat eval numbers from them with caution.
- **Traceability.** Every generated test records which ticket, retrieved chunks (by ID), template JSON entry, and prompt version produced it.

## Default limits (in `config.yaml`, overridable)
| Setting | Default |
|---|---|
| `llm.max_retries_on_bad_json` | 2 |
| `retrieval.top_k` | 10 |
| `retrieval.max_followup_rounds` | 2 |
| `context.max_tokens` | 12000 |
| `repair.max_attempts` | 3 |
| `sandbox.timeout_seconds` | 120 |

---

## Target test-suite patterns (generic)
The generator and validators are built for suites shaped like this. The synthetic `standin/` repo reproduces these patterns with invented names. (Updated 2026-10-06 from the human's comparisons with the real framework and their answers; real names and values withheld, the stand-in uses invented equivalents.)

- **Framework:** pytest with a custom layer on top. Tests are organized by feature area, one class/file per area, selected by markers and run in parallel.
- **Test kinds:** most tests (~85–90%) are browser UI tests using a page-object hierarchy reached through property chains (`nav.<area>.<page>`), followed by checks on backend state. A minority are pure API tests; a few are hybrid.
- **Domain shape:** the UI edits a per-tenant **policy** (lists of objects such as rules, exceptions, custom objects, profiles) and **settings** (capability gates, roles, token state). Changes are saved at two levels: the object's own editor save, then a shared **top bar** save and publish (or reset). Publish creates a new policy revision and waits internally for its success toast. Pure UI tests (search, filter, pagination, validation errors) often stop before the top bar.
- **Typical UI test shapes:** (1) **add**: minimal seed → add wizard (fill fields, `next()`) → object save → top-bar save + publish → `targets` shows the new object; (2) **edit**: seed an object → open it by name → change fields → object save → save + publish → `targets` shows the change; (3) **delete**: seed several → select/delete → confirm → save + publish → `targets` shows the remainder; (4) **UI-only**: seed → search/filter/paginate/trigger a validation error → assert counts or messages, no `targets`, often no publish. Variants: asserting that save is blocked, reset instead of publish, settings pages with their own save option. Add is the most common.
- **Class scaffold:** every test class inherits the framework's base class and carries a standard decorator stack: platform selection, environment gating (incl. cloud-only / on-prem-only), data loading, and project/component markers. Most classes define their own `setup` that calls the shared base setup with per-class options (fresh driver or not, policy wait, skip seeding); some log in as another tenant and navigate in `setup` and log out in `teardown`; runtime-style classes use `setup_method` / `teardown_method`. The base setup applies the seed, starts the driver, and provides the page-object root and the assertion object. New tests copy the scaffold (imports, decorators, setup/teardown) from a neighbouring class in the same area.
- **Page objects:** value fields are properties (assign to set, read to get); actions (open, next, save, confirm, ...) are plain methods. No fluent chaining. The top bar is one shared page object off the root.
- **Assertions:** the assertion object is a `unittest.TestCase` instance: `assertEqual`, `assertTrue`, `assertFalse`, `assertIn`, `assertNotIn`, with an optional message as the third positional argument (API tests use messages, UI tests mostly don't). Argument order is not consistent across the suite; nothing may depend on it. Backend checks go through a validation helper that reads the entry's expectation section itself (the test passes nothing). No redundant negative assertions after an equality check. The final checks must verify what the test name claims.
- **Data files:** every test file has a matching JSON data file: a top-level **array** of entries, each with an explicit identifier field (a plain string key, configurable; stand-in: `test_id`) equal to the pytest id (incl. the parametrize suffix; stacked decorators bottom-first). Tests that read no data may have no entry.
- **Data access:** the matched entry arrives as a dict, through a class-level data fixture (`self.params`, the common case) or a `params` argument. Tests index it (`params["key"]`, `params.get("key", default)`, nested keys); no attribute access.
- **Entry contents:** seed sections `settings` and `policy`, and `tenants` (a list of per-tenant blocks: a tenant placeholder plus optional `settings`, `policy`, and `targets`; the first is the primary tenant); one expectation section, `targets` or `interactions`; per-entry `priority` / `skip`; plus custom keys the test body reads. Seed only what the scenario reads or the feature needs; a large policy block is normally the object the UI action works on. Other pre-existing state may come from a UI helper in the same file, a policy/settings manager called at the top of the test, or external files (imports), whose content the expectations must match.
- **Expectations:** `targets` is a list of `{method, path, payload?, status_code? (default 200), response}`; `interactions` is a list of `{request: {method, path}, response: {status, body}}`. Each is read by its own validation helper, and the helper the test calls decides which one the entry has; an entry never has both. Responses are compared as a subset, so list only asserted fields. Typically one GET of a policy or settings endpoint; permission tests use a PUT with a `payload` and an error status. `targets` may be empty or absent when there is no backend check. UI-level expectations belong in the test code.
- **Placeholders:** paths use colon placeholders (`:tid`, `:rev_id`) filled by the framework from the current tenant and policy revision. Data values use brace placeholders resolved before the test runs: tenants (`{tenant_id1}`), framework-provided users (`{user_1}`), and unique names derived from the test id with a length limit (`{test_id:N}`); a base-class helper returns the same unique name for use in code.
- **Repetition:** identical seed blocks are pasted into every variant; variants differ by one or two values. No templating or includes.
- **Markers:** priority, project, component, and suite, with values from approved sets only (casing included).
- **Style:** a fixed indent width, LF line endings, a final newline, alphabetical imports, no type annotations; JSON via a formatter with its own indent and key spacing. Names summarize area, action, and sub-area, and never contain ticket numbers. Docstrings optional (sometimes a short numbered list of what the test does).
- **Flakiness:** handled in code (retry decorators, explicit waits inside page objects), not by quarantine.
- **Ticket links:** skip reasons reference ticket ids, so ticket ↔ test pairs can be mined from git history (for example, a skip removed in a fix commit).
- **Needs a real run:** whether a page needs a refresh before re-reading a field, which save flow it uses (object save, top-bar save/publish/reset, settings save option), whether a capability must be enabled, and whether expected responses match a real capture can't be known statically; generated output always lists these for the reviewer.

## Tech stack
- Python 3.11+, managed with `uv`
- `pydantic` v2 for all data models and config
- `typer` for the CLI
- `httpx` for HTTP (GitHub API)
- `anthropic` and `google-genai` SDKs, imported only in `llm/`; the default provider shells out to the Claude Code CLI
- `tree-sitter` + `tree-sitter-python` (+ `tree-sitter-rust` in a later phase)
- `rank_bm25` for keyword search
- `pytest`, `ruff` (lint + format; also a runtime dependency that formats generated test code to the target suite's style), `mypy` (strict on `src/`)

## Repository layout
```
src/ticket2test/
  models/        # Pydantic models: Ticket, TestCaseDraft, Chunk, GeneratedTest, EvalResult
  adapters/
    tickets/     # TicketSource interface; github.py now; jira.py stub (reads exported JSON)
    repo/        # RepoSource interface; local_path.py; read-only git history reader (eval mining)
  llm/           # LLMClient interface + provider implementations (ONLY place SDKs are imported)
  normalize/     # raw ticket → Ticket (incl. rich-text → plain text)
  draft/         # Ticket → TestCaseDraft(s), prompts versioned in prompts/
  index/         # tree-sitter parsing, chunking (test + markers + JSON entries), symbol catalog
                 # (incl. page-object property chains), pytest-id computation, BM25 index
  retrieve/      # query rewrite, BM25, grep, AST expansion, follow-up rounds
  suitemap/      # suite map: per-area summaries of the target suite from the index (no LLM)
  guides/        # area guides: one strong-model call per area, budgeted; read by the generator
  gaps/          # missing pieces: candidates from generated code and hints, checked by code
  proposals/     # agent 2: a proposed member per gap, checked by code, kept as a patch (opt-in)
  generate/      # few-shot code generation + JSON entry assembly (base entry, per-variant changes)
  style/         # deterministic formatting of generated code and JSON to the suite's style rules
  validate/      # deterministic validators + repair loop
  sandbox/       # containerized runner (`pytest --collect-only`; optional test execution)
  eval/          # eval harness and metrics
  security/      # secret scrubber
  cli.py
standin/         # SYNTHETIC target repo: tiny fake web app, page objects, base test class,
                 # tests + matching JSON data files (invented, generic names only)
prompts/         # versioned prompt templates (e.g. draft_v1.md)
tests/           # unit tests for this project, with small fixture repos and tickets
eval_data/       # public issue ↔ fix-PR pairs and mined ticket ↔ test pairs (IDs/URLs/paths only)
config.yaml
.env.example
```

## Core data models (starting point; refine as needed)
- **Ticket**: `id`, `title`, `description`, `steps_to_reproduce`, `expected`, `actual`, `components`, `labels`, `comments`, `links`, `source`
- **TestCaseDraft**: `intent`, `markers` (`priority`, `component`, `suite`), `test_kind` (`ui` | `api` | `hybrid`), `deployment_type` (`cloud` | `on_prem` | `both`), `preconditions[]`, `steps[]`, `expected_outcome`, `variants[]` (parametrized cases), `support` (checked in code: explicit sections, component named, invented numbers, grounding; no model self-rating), `status` (`ok` | `insufficient_info`), `missing_info[]`
- **Chunk**: `id`, `file_path`, `symbol_name`, `kind` (test | function | class | page_object), `language`, `code`, `start_line`, `end_line`; for tests also `class_name`, `decorators[]` (in source order), `markers[]`, `parametrize[]` (stacked, in source order), `test_ids[]` (pytest-generated), `data_file`, `data_entries` (test id → JSON entry; read from the suite's data-file format, e.g. an array of entries with `id`)
- **Symbol catalog**: functions, classes, methods, modules, fixtures, markers seen, and **page-object property chains** (each attribute/property step from a root such as `nav`, with the type it resolves to)
- **GeneratedTest**: a **pair**. `code`, `file_name`, `data_file_name`, `data_entries` (written in the suite's data-file format, e.g. an array with `id`), `template_entry_ref` (the base entry), `draft_ref`, `retrieved_chunk_ids[]`, `prompt_version`, `validation_report`, `collect_report`, `review_checklist` ("needs a real run" items)

---

## Build phases
Complete each phase fully, with passing tests, before starting the next. At the end of each phase, stop and summarize what was built, how to run it, and any open questions.

**Phase 0: Skeleton.** Project setup, config loading, interfaces (`TicketSource`, `RepoSource`, `LLMClient`), CLI stub, CI-ready `ruff`/`mypy`/`pytest`, MIT license, `.gitignore`, `.env.example`, README quick start.
*Done when:* `uv run ticket2test --help` works and all checks pass.

**Phase 1: Ticket normalizer.** GitHub Issues adapter, plus a Jira adapter stub that reads an exported JSON file. Normalize both into `Ticket`.
*Done when:* 5 real public issues normalize correctly (fixture-tested).

**Phase 2: Draft generation.** Prompt + Pydantic schema → `TestCaseDraft` (incl. markers, test kind, deployment type), with JSON retry and the insufficient-info path. Output both JSON and readable Markdown for review.
*Done when:* runs on 5 tickets, and a deliberately vague ticket returns `insufficient_info`.

**Phase 3: Synthetic stand-in repo.** Build `standin/`: a tiny fake web app, a generic page-object hierarchy, a base test class, shared helpers/decorators, and tests with matching JSON data files that follow the target patterns above. Includes fake tickets and a scripted git history (a ticket-id skip removed by a fix) for eval mining.
*Done when:* `pytest --collect-only` on the stand-in succeeds with no browser and no network, and every JSON key matches a collected test id.

**Phase 3b: Stand-in v2/v3.** Rework `standin/` to the updated patterns above. v2: class scaffold with decorator stack, property-style page objects without chaining, array data files, tests without entries, the style rules, names without ticket numbers. v3: an editable per-tenant policy app with a shared top bar (object save, top-bar save/publish/reset, revisions), the four test shapes, per-class `setup` with options, a `unittest.TestCase` assertion object, `targets` / `interactions` with their own validation helpers, `tenants` blocks, colon path and brace data placeholders, `test_id` identifiers.
*Done when:* the stand-in follows every updated pattern (checked by tests), collects with no browser and no network, and every entry `id` matches a collected test id.

**Phase 4: Indexer (Python).** Parse with tree-sitter. Chunk unit = test function + its decorators/markers + its JSON entries; also chunk page objects, helpers, functions, and classes. Compute pytest ids statically (stacked parametrize, bottom first). Build the symbol catalog (incl. page-object property chains) and a BM25 index with identifier splitting (`snake_case` / `CamelCase` → words). Persist the index to disk.
*Done when:* indexing the stand-in and `httpx` works, chunks carry their JSON entries, and a search for a known function or page returns its tests in the top 5.

**Phase 5: Retrieval.** LLM query rewrite (ticket → likely code terms), then BM25 + grep, merged and de-duplicated, then AST expansion (callers, callees, related tests, page objects used), then capped follow-up rounds. Also returns the nearest similar JSON entries as templates.
*Done when:* retrieval recall@10 is measured on the eval set (see Phase 8; build a minimal version early if needed).

**Phase 6: Code generation.** Few-shot generation of the code + JSON pair, using the nearest retrieved tests as style templates, within the token budget. Entries are built from the nearest existing entry (see the guardrail), and the output is formatted to the suite's style rules.

**Phase 7: Validators, repair, and sandbox.** Validators: syntax parses; every referenced name and page-object property chain exists in the catalog; imports resolve; JSON keys exactly match the pytest-generated ids (stacked decorator order); every parametrize variant has a JSON entry; required markers present; base class used; naming conventions (configurable); page-object properties assigned/read and actions called (no chaining); the framework assertion object instead of bare asserts; every data key the test reads exists in its entries, and every test that reads data has an entry; JSON shape and formatting; approved marker values; the style rules; no ticket numbers in names; every seed or expectation key is read by the test or consumed by the framework or a helper it calls (e.g. `targets` only when its validation helper is called; never both `targets` and `interactions`); the checks touch what the test name and docstring claim, with counts alone not accepted when the outcome names which items are shown (a heuristic that flags for the reviewer); seeded names use the unique-name placeholder and fit the name cap; no capability gates the feature doesn't use. The repair loop feeds validator errors back to the LLM, capped. The sandbox runs `pytest --collect-only` in a container (see Hard Constraint 3); executing tests is optional and later.

**Phase 8: Eval harness.** For public issue ↔ fix-PR pairs and mined ticket ↔ test pairs, measure:
- Retrieval: recall@k and MRR against the files changed in the fix (or the test linked to the ticket)
- Faithfulness: rate of invented names (incl. property chains); draft-matches-ticket via LLM-as-judge (flag as unvalidated until checked against human labels)
- Execution (primary): `pytest --collect-only` pass rate in the sandbox (imports resolve, ids match, no browser needed)
- Execution (later, optional, API tests only): test **fails before the fix and passes after**
- Output a summary report (JSON + Markdown).

**Phase 9 (later): Rust support.** Add `tree-sitter-rust` to the indexer and validators. Test on a mixed Python+Rust public repo.

## Stand-in repos
- **Synthetic (primary for generation and validation):** `standin/` in this repo. It follows the target test-suite patterns, uses invented generic names only, and is used for Phases 3–8.
- **Public (retrieval learning):** `encode/httpx` (Python, pytest, active issues with linked PRs)
- **Mixed Python+Rust (Phase 9):** `pydantic/pydantic-core`

---

## Working rules for Claude Code
- Ask before adding a dependency, changing a data model already used by a completed phase, or changing any hard constraint.
- Write unit tests alongside code. Mock the LLM in unit tests and never call a real API in `pytest` by default (mark live tests with `@pytest.mark.live`).
- Keep prompts in `prompts/` as versioned files, never inline in code.
- Prefer simple and explicit over clever. No framework (LangChain, etc.) unless explicitly approved.
- Type-hint everything in `src/`.
- If a task seems to require private data, real company systems, or bypassing a constraint, stop and ask.
- The `standin/` repo must use only generic, invented names: no real company, product, URL, or internal tool names. Use `example.com` / `localhost` for hosts.
- **Git:** Claude may run `git init` and `git commit` locally. Never `git push` without explicit permission from the human. Never add Claude / Claude Code as a co-author in commits (no `Co-Authored-By: Claude ...` trailer) and no "Generated with Claude Code" lines in commit messages or PR descriptions.
