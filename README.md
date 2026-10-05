# ticket2test

Turns a bug ticket into **structured draft test cases**, then into **runnable test code**, for a
human QE to review. Generic and company-agnostic: ticket source, codebase, LLM endpoint, and
conventions all sit behind adapters and config. Built and evaluated on public data only.

> Status: Phase 0 (skeleton). Subcommands are placeholders. See `PROJECT_STATUS.md`.

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

## Configuration

Settings live in `config.yaml`. Any value can be overridden with an env var
`T2T_<SECTION>__<KEY>`:

```bash
T2T_RETRIEVAL__TOP_K=5 uv run ticket2test ...
```

Use `--config path.yaml` or `T2T_CONFIG=path.yaml` to point at another file.

Secrets (API tokens) are **never** in `config.yaml`. Copy `.env.example` to `.env` (git-ignored),
fill it in, and load it with `uv run --env-file .env ticket2test ...`.

## Tests

- `uv run pytest` runs unit tests only. The LLM is always mocked (`FakeLLMClient`).
- Tests that hit real services are marked `@pytest.mark.live` and run only with
  `uv run pytest -m live`.

## Safety

- Generated tests are untrusted and run only inside a network-less container, never on the host.
- Target repos are read-only. The pipeline writes only to its own output directory.
- Full prompts/responses are logged only with `--debug-log`, to a git-ignored directory.

## License

MIT. See `LICENSE`.
