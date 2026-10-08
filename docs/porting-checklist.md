# Porting checklist: from the stand-in to a real test suite

This repo was built against public data and the synthetic `standin/` suite. Everything that
depends on a real company environment sits behind adapters and config. This checklist lists
what to fill in, in the order it's usually needed. It contains no company data: every value
below is a placeholder to replace inside the company environment.

An AI assistant that can read the real suite can do sections 3–6 (the private config, the
conventions doc, the sandbox requirements, the calibration loop): give it
`docs/integration-brief.md`, which defines the files it writes, the reports it reads, and how to
find every value.

## 0. Approvals first

- [ ] Approval to bring this code into the company environment (IP, licence: MIT).
- [ ] Dependency review. Runtime: pydantic, pydantic-settings, typer, pyyaml, httpx,
      tree-sitter, tree-sitter-python, rank-bm25 (pulls in numpy), ruff, anthropic,
      google-genai. Flagged earlier: `certifi` (MPL-2.0, via httpx), `pathspec` (MPL-2.0, dev
      only), numpy's bundled licences (BSD / 0BSD / MIT / Zlib / CC0).
- [ ] Which LLM endpoint is allowed, and whether source code may be sent to it.

## 1. LLM provider (`llm`)

- [ ] `llm.provider`: `claude_code_cli`, `claude` (Anthropic API), or `gemini`. Another
      endpoint means a new `LLMClient` in `src/ticket2test/llm/` (the only place SDKs are
      imported) and an entry in `llm/factory.py`.
- [ ] The model per provider, and `step_models` if some steps should use another model.
- [ ] Keys only through environment variables (`.env` is git-ignored; `.env.example` holds
      placeholders).
- [ ] Prompt and response logging stays off unless `--debug-log` is given.

## 2. Tickets (`tickets`, `normalize`)

- [ ] Ticket source: the Jira adapter reads an exported JSON file today
      (`adapters/tickets/jira.py`). A live Jira API needs a new `TicketSource`.
- [ ] `tickets.jira.field_map`: custom fields for steps to reproduce, expected, and actual.
- [ ] `tickets.jira.browse_url` for ticket links.
- [ ] `eval.ticket_id_pattern`: the ticket-id format used in skip reasons.

## 3. The target test suite (`index`, `data`, `style`, `markers`)

- [ ] Repo path, read-only (the pipeline never writes to it).
- [ ] `index.chain_roots` (the page-object root, e.g. `nav`), test prefixes, data-file suffix,
      ignore patterns.
- [ ] `data.format`, `data.id_field`, `data.access` (how tests read their entry),
      `data.seed_sections`, `data.expectation_sections` (section → validation helper),
      `data.per_entry_keys`.
- [ ] `style.python` (indent, line length, quotes, annotations, first-party roots) and
      `style.json` (indent, separators). Check: the suite's own files should be a fixed point
      of the formatter.
- [ ] `markers`: the approved priorities, suites, project, and required markers (casing
      matters). Components come from the suite's own markers.

## 4. Generation (`generate`, `context`)

- [ ] `generate.conventions_doc`: the team's conventions, written against the real suite (see
      `standin/CONVENTIONS.md` for the shape: structure, markers, page objects and save flows,
      test shapes, checks, data, list pages, style).
- [ ] `generate.placeholder_token` (the unique-name placeholder and its length),
      `generate.deployment_decorators`, `generate.scaffold_methods`,
      `generate.review_checklist_defaults`.
- [ ] `context.max_tokens` for the chosen model.

## 5. Validation and sandbox (`validation`, `repair`, `sandbox`)

- [ ] `validation.base_classes` (every root base; there may be several), `assertion_object`, `assertion_methods`,
      `external_modules`, `naming` regexes, `unique_name_helper`.
- [ ] `validation.name_max_length` (the app's name limit), `name_keys`.
- [ ] `validation.capability_gates` (component → gates its features use),
      `capability_path`, `paging_actions`, `constant_properties`.
- [ ] `sandbox.runtime` (Docker or Podman), `sandbox.base_image` (an approved image with
      Python), `sandbox.requirements` (the suite's test-time requirements file, pinned), and
      `sandbox.registry_auth` (true only if the base image's registry needs a login). Then
      `ticket2test sandbox --build`.
- [ ] **Calibrate:** `ticket2test check-suite <repo> --collect`, fix the config keys it names,
      and rerun until it reports "clean". The suite's own tests are known-good, so every error
      is a config value that doesn't describe the suite; `--collect` also compares the
      statically computed test ids with a real collect in the sandbox.
- [ ] `repair.max_attempts`.

- [ ] `security.masking.keys` (data keys that hold prompt-injection payloads) and, if needed,
      extra `security.masking.patterns`. Masking is on by default: payloads are replaced by
      tokens before any text reaches the LLM and restored afterwards.

## 6. Eval (`eval_data/`)

- [ ] Mine ticket ↔ test pairs from the real repo's history: `ticket2test mine <repo> --out
      eval_data/<name>.json` (read-only; commits that remove a ticket-id skip).
- [ ] Mark one linked-test set with `"generation": true` and its `conventions_doc`.
- [ ] Run a deterministic baseline (`--no-llm`), then an LLM baseline; label a sample of the
      LLM-judge verdicts by hand before trusting them.
- [ ] Later: latency and pricing evals per stage (calls and wall-clock time are recorded
      already).

## 7. First real run

- [ ] One ticket end to end: `normalize` → `draft` → `retrieve` → `generate` →
      `validate --collect`, then a human style check against the real suite (deferred from
      Phase 6).
- [ ] Review the "needs a real run" checklist that every generated test carries.
