# CLAUDE.md: Ticket-to-Test Draft Agent

## What this project is
A pipeline that turns a bug ticket into **structured draft test cases**, then into **runnable test code**, for a human QE (Quality Engineer) to review.

This repo is a **generic, company-agnostic** build developed entirely on **public data**. All company-specific parts (ticket source, codebase, LLM endpoint, team conventions) sit behind adapters and config, so the code can later be moved into a company environment without rewrites.

## Pipeline
```
Ticket source → normalize → draft test cases (structured) → [human review]
  → query rewrite → retrieve (BM25 + grep + AST expand, ≤2 follow-up rounds)
  → build context → generate test code (few-shot from similar tests)
  → validate (deterministic) → repair loop (capped) → [human review] → output
```
This is a **fixed workflow**, not an autonomous agent. LLM-driven tool use is allowed only in the follow-up retrieval step.

---

## HARD CONSTRAINTS (never violate, never work around)

1. **No private or company data.** Never add, fetch, hardcode, or reference any non-public codebase, ticket, name, URL, internal tool, or credential. Use only public repositories and public issue trackers.
2. **No secrets in the repo.** API keys and tokens come only from environment variables. Commit `.env.example` with placeholder values only. `.env` must be listed in `.gitignore`.
3. **Never execute generated code on the host.** Generated tests are untrusted. Run them only inside a container (Podman or Docker) with no network access and no host mounts except a read-only copy of the target repo and a writable temp dir.
4. **Read-only on target repos.** The pipeline never modifies, commits to, or pushes to the target codebase. It writes only to its own output directory.
5. **No hardcoded vendor lock-in.** All LLM calls go through the `LLMClient` interface. No provider SDK may be imported outside `llm/`.
6. **No unbounded loops.** Every retry, repair, and search loop has an explicit max from config. No exceptions.
7. **License.** The repo is MIT-licensed. Only add dependencies with permissive licenses (MIT, BSD, Apache-2.0). Flag anything else before adding it.
8. **Do not log full prompts or full LLM responses by default.** They may contain source code. Logging these requires an explicit `--debug-log` flag and writes to a local, git-ignored directory.

## GUARDRAILS (pipeline behavior)

- **Insufficient info is a valid output.** If a ticket lacks steps, expected behavior, or an identifiable component, return `status: "insufficient_info"` with a list of what's missing. Never guess to fill the gaps.
- **No invented names.** Generated code may reference only symbols that exist in the symbol catalog (built by AST) or that are defined within the generated test itself. The validator enforces this.
- **Structured output only.** Every LLM step returns JSON validated by a Pydantic model. On a parse or validation failure, retry with the error message included (max retries from config), then fail cleanly.
- **Token budget.** Context building enforces a max token budget from config. Trim by relevance rank, never truncate mid-function.
- **Secret scrubbing.** Before anything is placed in a prompt, run a basic secret scanner (regexes for keys, tokens, passwords, connection strings) and redact matches. The same scrubber runs on generated output.
- **Determinism where possible.** Use temperature 0 for extraction and validation-related steps. Use seeds where the provider supports them.
- **Traceability.** Every generated test records which ticket, retrieved chunks (by ID), and prompt version produced it.

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

## Tech stack
- Python 3.11+, managed with `uv`
- `pydantic` v2 for all data models and config
- `typer` for the CLI
- `httpx` for HTTP (GitHub API)
- `tree-sitter` + `tree-sitter-python` (+ `tree-sitter-rust` in a later phase)
- `rank_bm25` for keyword search
- `pytest`, `ruff` (lint + format), `mypy` (strict on `src/`)

## Repository layout
```
src/ticket2test/
  models/        # Pydantic models: Ticket, TestCaseDraft, Chunk, GeneratedTest, EvalResult
  adapters/
    tickets/     # TicketSource interface; github.py now; jira.py stub (reads exported JSON)
    repo/        # RepoSource interface; local_path.py
  llm/           # LLMClient interface + provider implementations (ONLY place SDKs are imported)
  normalize/     # raw ticket → Ticket (incl. rich-text → plain text)
  draft/         # Ticket → TestCaseDraft(s), prompts versioned in prompts/
  index/         # tree-sitter parsing, chunking, symbol catalog, BM25 index
  retrieve/      # query rewrite, BM25, grep, AST expansion, follow-up rounds
  generate/      # few-shot code generation
  validate/      # deterministic validators + repair loop
  sandbox/       # containerized test runner
  eval/          # eval harness and metrics
  security/      # secret scrubber
  cli.py
prompts/         # versioned prompt templates (e.g. draft_v1.md)
tests/           # unit tests for this project, with small fixture repos and tickets
eval_data/       # public issue ↔ fix-PR pairs (IDs and URLs only, fetched on demand)
config.yaml
.env.example
```

## Core data models (starting point; refine as needed)
- **Ticket**: `id`, `title`, `description`, `steps_to_reproduce`, `expected`, `actual`, `components`, `labels`, `comments`, `links`, `source`
- **TestCaseDraft**: `intent`, `priority`, `component`, `preconditions[]`, `steps[]`, `expected_outcome`, `variants[]` (parametrized cases), `confidence`, `status` (`ok` | `insufficient_info`), `missing_info[]`
- **Chunk**: `id`, `file_path`, `symbol_name`, `kind` (test | function | class), `language`, `code`, `start_line`, `end_line`
- **GeneratedTest**: `code`, `file_name`, `draft_ref`, `retrieved_chunk_ids[]`, `prompt_version`, `validation_report`

---

## Build phases
Complete each phase fully, with passing tests, before starting the next. At the end of each phase, stop and summarize what was built, how to run it, and any open questions.

**Phase 0: Skeleton.** Project setup, config loading, interfaces (`TicketSource`, `RepoSource`, `LLMClient`), CLI stub, CI-ready `ruff`/`mypy`/`pytest`, MIT license, `.gitignore`, `.env.example`, README quick start.
*Done when:* `uv run ticket2test --help` works and all checks pass.

**Phase 1: Ticket normalizer.** GitHub Issues adapter, plus a Jira adapter stub that reads an exported JSON file. Normalize both into `Ticket`.
*Done when:* 5 real public issues normalize correctly (fixture-tested).

**Phase 2: Draft generation.** Prompt + Pydantic schema → `TestCaseDraft`, with JSON retry and the insufficient-info path. Output both JSON and readable Markdown for review.
*Done when:* runs on 5 tickets, and a deliberately vague ticket returns `insufficient_info`.

**Phase 3: Indexer (Python).** Parse with tree-sitter, chunk by test function (include its fixtures and parametrize data), build the symbol catalog, and build a BM25 index with identifier splitting (`snake_case` / `CamelCase` → words). Persist the index to disk.
*Done when:* indexing the stand-in repo works, and a search for a known function returns its tests in the top 5.

**Phase 4: Retrieval.** LLM query rewrite (ticket → likely code terms), then BM25 + grep, merged and de-duplicated, then AST expansion (callers, callees, related tests), then capped follow-up rounds.
*Done when:* retrieval recall@10 is measured on the eval set (see Phase 7; build a minimal version early if needed).

**Phase 5: Code generation.** Few-shot generation using the nearest retrieved tests as style templates, within the token budget.

**Phase 6: Validators and repair.** Validators: syntax parses; every referenced name exists in the catalog; imports resolve; parametrize cases match data; naming conventions (configurable). The repair loop feeds validator errors back to the LLM, capped. Sandbox runner executes tests in a container (see Hard Constraint 3).

**Phase 7: Eval harness.** For public issue ↔ fix-PR pairs, measure:
- Retrieval: recall@k and MRR against the files changed in the fix
- Faithfulness: rate of invented names; draft-matches-ticket via LLM-as-judge (flag as unvalidated until checked against human labels)
- End-to-end: test **fails before the fix and passes after** (check out the pre-fix and post-fix commits in the sandbox)
- Output a summary report (JSON + Markdown).

**Phase 8 (later): Rust support.** Add `tree-sitter-rust` to the indexer and validators. Test on a mixed Python+Rust public repo.

## Public stand-in repos
- Primary: `encode/httpx` (Python, pytest, active issues with linked PRs)
- Mixed Python+Rust (Phase 8): `pydantic/pydantic-core`

---

## Working rules for Claude Code
- Ask before adding a dependency, changing a data model already used by a completed phase, or changing any hard constraint.
- Write unit tests alongside code. Mock the LLM in unit tests and never call a real API in `pytest` by default (mark live tests with `@pytest.mark.live`).
- Keep prompts in `prompts/` as versioned files, never inline in code.
- Prefer simple and explicit over clever. No framework (LangChain, etc.) unless explicitly approved.
- Type-hint everything in `src/`.
- If a task seems to require private data, real company systems, or bypassing a constraint, stop and ask.
- **Git:** Claude may run `git init` and `git commit` locally. Never `git push` without explicit permission from the human. Never add Claude / Claude Code as a co-author in commits (no `Co-Authored-By: Claude ...` trailer) and no "Generated with Claude Code" lines in commit messages or PR descriptions.
