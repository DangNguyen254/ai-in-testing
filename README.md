# ticket2test

Turns a bug ticket into **structured draft test cases**, then into **runnable test code**, for a
human QE to review. Generic and company-agnostic: ticket source, codebase, LLM endpoint, and
conventions all sit behind adapters and config. Built and evaluated on public data only.

> Status: Phase 4 (indexer). `normalize`, `draft`, `index`, and `search` work; other subcommands are placeholders. See `PROJECT_STATUS.md`.

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
```

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

For the public stand-in used in tests: `git clone --depth 1 --branch 0.28.1
https://github.com/encode/httpx .scratch/repos/httpx` (tests that need it skip without it).

## Stand-in suite

`standin/` is a synthetic target suite (invented names only) that mirrors the target test
style: page objects, a base test class, markers, and a JSON data file per test file. See
`standin/README.md`. `uv run pytest` checks it with `pytest --collect-only` (no browser needed).

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

## Safety

- Generated tests are untrusted and run only inside a network-less container, never on the host.
- Target repos are read-only. The pipeline writes only to its own output directory.
- Full prompts/responses are logged only with `--debug-log`, to a git-ignored directory.

## License

MIT. See `LICENSE`.
