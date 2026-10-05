# CLAUDE.md: Ticket-to-Test Draft Agent

## What this project is
A pipeline that turns a bug ticket into **structured draft test cases**, then into **runnable test code plus its JSON test data**, for a human QE (Quality Engineer) to review.

This repo is a **generic, company-agnostic** build developed entirely on **public data** and **synthetic data created in this repo**. All company-specific parts (ticket source, codebase, LLM endpoint, team conventions) sit behind adapters and config, so the code can later be moved into a company environment without rewrites.

**Scope:** both **browser UI tests** (page objects driving a browser, then verifying backend state) and **API tests** are in scope. UI tests dominate the target style, so frontend/UI test generation is a first-class goal, not an add-on.

## Pipeline
```
Ticket source → normalize → draft test cases (structured) → [human review]
  → query rewrite → retrieve (BM25 + grep + AST expand, ≤2 follow-up rounds)
  → build context → generate test code + JSON data entries
      (few-shot from similar tests; large config blocks copied from the nearest existing entry)
  → validate (deterministic + `pytest --collect-only` in the sandbox) → repair loop (capped)
  → [human review] → output (code file + data file)
```
This is a **fixed workflow**, not an autonomous agent. LLM-driven tool use is allowed only in the follow-up retrieval step.

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

## GUARDRAILS (pipeline behavior)

- **Insufficient info is a valid output.** If a ticket lacks steps to reproduce or expected behavior, return `status: "insufficient_info"` with a list of what's missing. Never guess to fill the gaps.
- **Component inference.** The LLM infers the component from the ticket text, using labels as hints. If it cannot, it sets `component: "unknown"` and lowers `confidence`. An unknown component alone is never a reason for `insufficient_info`.
- **No invented names.** Generated code may reference only symbols that exist in the symbol catalog (built by AST) or that are defined within the generated test itself. This includes **page-object property chains** (e.g. `nav.<area>.<page>.<member>`): every attribute/property step must resolve through the catalog. Markers must use values known to the catalog or config. The validator enforces this.
- **Code and data stay consistent.** Every generated test comes with its JSON data entries. Entry keys must exactly match the pytest-generated test ids (stacked parametrize decorators: bottom decorator first), with one entry per variant. The validator enforces this, and `pytest --collect-only` in the sandbox confirms it.
- **Reuse, don't regenerate.** Large repeated config blocks in JSON entries are copied verbatim from the nearest similar existing entry. The LLM fills in only the unique parts (inputs, seed state, expected backend results). Unique names use the suite's placeholder token and name-generator helper, never hardcoded literals.
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
The generator and validators are built for suites shaped like this. The synthetic `standin/` repo reproduces these patterns with invented names.

- **Framework:** pytest with a custom layer on top. Tests are organized by feature area, one class/file per area, and tagged with markers for priority, project, component, and suite. Tests are selected by markers and run in parallel.
- **Test kinds:** most tests (~85–90%) are browser UI tests using a page-object hierarchy reached through property chains (`nav.<area>.<page>`), followed by checks on backend state. A minority are pure API tests; a few are hybrid.
- **Shared layer:** a base test class handles setup/teardown (driver, config, cleanup, failure artifacts). Tests reuse shared helpers, validation methods, mixins, and decorators (retry, per-browser skip).
- **Data files:** every test file has a matching JSON data file, keyed by the pytest-generated test id (including parametrize values). Stacked parametrize decorators set the id order (bottom decorator first). One JSON entry per variant.
- **Entry contents:** seed state, expected backend results, and test-specific inputs. Large config blocks repeat across entries. Unique names use a placeholder token plus a name-generator helper. An entry can override priority, or skip by ticket id.
- **Deployment types:** tests can be skipped by deployment type (cloud-only / on-prem-only).
- **Flakiness:** handled in code (retry decorators, explicit waits), not by quarantine.
- **Ticket links:** skip reasons reference ticket ids, so ticket ↔ test pairs can be mined from git history (for example, a skip removed in a fix commit).

## Tech stack
- Python 3.11+, managed with `uv`
- `pydantic` v2 for all data models and config
- `typer` for the CLI
- `httpx` for HTTP (GitHub API)
- `anthropic` and `google-genai` SDKs, imported only in `llm/`; the default provider shells out to the Claude Code CLI
- `tree-sitter` + `tree-sitter-python` (+ `tree-sitter-rust` in a later phase)
- `rank_bm25` for keyword search
- `pytest`, `ruff` (lint + format), `mypy` (strict on `src/`)

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
  generate/      # few-shot code generation + JSON entry assembly (copy config blocks, fill unique parts)
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
- **TestCaseDraft**: `intent`, `markers` (`priority`, `component`, `suite`), `test_kind` (`ui` | `api` | `hybrid`), `deployment_type` (`cloud` | `on_prem` | `both`), `preconditions[]`, `steps[]`, `expected_outcome`, `variants[]` (parametrized cases), `confidence`, `status` (`ok` | `insufficient_info`), `missing_info[]`
- **Chunk**: `id`, `file_path`, `symbol_name`, `kind` (test | function | class | page_object), `language`, `code`, `start_line`, `end_line`; for tests also `class_name`, `decorators[]` (in source order), `markers[]`, `parametrize[]` (stacked, in source order), `test_ids[]` (pytest-generated), `data_file`, `data_entries` (test id → JSON entry)
- **Symbol catalog**: functions, classes, methods, modules, fixtures, markers seen, and **page-object property chains** (each attribute/property step from a root such as `nav`, with the type it resolves to)
- **GeneratedTest**: a **pair**. `code`, `file_name`, `data_file_name`, `data_entries` (test id → entry), `template_entry_ref` (existing entry whose config blocks were copied), `draft_ref`, `retrieved_chunk_ids[]`, `prompt_version`, `validation_report`, `collect_report`

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

**Phase 4: Indexer (Python).** Parse with tree-sitter. Chunk unit = test function + its decorators/markers + its JSON entries; also chunk page objects, helpers, functions, and classes. Compute pytest ids statically (stacked parametrize, bottom first). Build the symbol catalog (incl. page-object property chains) and a BM25 index with identifier splitting (`snake_case` / `CamelCase` → words). Persist the index to disk.
*Done when:* indexing the stand-in and `httpx` works, chunks carry their JSON entries, and a search for a known function or page returns its tests in the top 5.

**Phase 5: Retrieval.** LLM query rewrite (ticket → likely code terms), then BM25 + grep, merged and de-duplicated, then AST expansion (callers, callees, related tests, page objects used), then capped follow-up rounds. Also returns the nearest similar JSON entries as templates.
*Done when:* retrieval recall@10 is measured on the eval set (see Phase 8; build a minimal version early if needed).

**Phase 6: Code generation.** Few-shot generation of the code + JSON pair, using the nearest retrieved tests as style templates, within the token budget. Large config blocks are copied from the nearest existing entry; the LLM fills only the unique parts.

**Phase 7: Validators, repair, and sandbox.** Validators: syntax parses; every referenced name and page-object property chain exists in the catalog; imports resolve; JSON keys exactly match the pytest-generated ids (stacked decorator order); every parametrize variant has a JSON entry; required markers present; base class used; naming conventions (configurable). The repair loop feeds validator errors back to the LLM, capped. The sandbox runs `pytest --collect-only` in a container (see Hard Constraint 3); executing tests is optional and later.

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
