# The workbench container (Linux, repo mounted)

The tool runs in a podman container that sees three folders: this repo (read-only), the target
suite (read-only) and the private folder (writable). Everything else the tool writes goes to a
state volume, so the image can be replaced without losing anything but a `uv sync`.
The three folders are siblings on the host.

## 1. Build the image (once, and again to change it)

```bash
podman build -t test-runner-py3 -f scripts/runner/Containerfile scripts/runner
```

It pulls public images (`python:3.12-slim`, uv's) and installs git, uv and the claude CLI.

## 2. Create the container

Set the two suite values first (they are private: type them, don't commit them anywhere):
`SUITE` is the suite's folder name on the host; `SUITE_IN` is where the private pair set
expects it in the container (`repo_path` in `golden.json`, e.g. `/root/work/<name>`).

```bash
WORK=~/NMD/Source/work
SUITE=...      # the suite's folder on the host, under $WORK
SUITE_IN=...   # repo_path from the private golden.json
test -d "$WORK/$SUITE" || echo "no such folder: fix SUITE before running"
podman run -d --init --name t2t --memory 6g --memory-swap 6g \
  -v "$WORK/ai-prj:/root/work/ai-prj:ro" \
  -v "$WORK/$SUITE:$SUITE_IN:ro" \
  -v "$WORK/t2t-private:/root/work/t2t-private" \
  -v t2t-state:/root/work/t2t-state \
  -v t2t-claude:/root/work/claude-config \
  -e CLAUDE_CONFIG_DIR=/root/work/claude-config \
  -e T2T_CONFIG=/root/work/t2t-private/company.yaml \
  -e UV_PROJECT_ENVIRONMENT=/root/work/t2t-state/venv \
  -e UV_CACHE_DIR=/root/work/t2t-state/uv-cache \
  -e UV_PYTHON_INSTALL_DIR=/root/work/t2t-state/python \
  -e UV_PYTHON_PREFERENCE=only-managed \
  -e UV_PYTHON=3.12 \
  -e UV_FROZEN=1 \
  -e PYTHONPYCACHEPREFIX=/root/work/t2t-state/pycache \
  -e T2T_PATHS__CACHE_DIR=/root/work/t2t-state/t2t_cache \
  -e T2T_LLM__CLAUDE_CODE_CLI__WORKDIR=/root/work/t2t-state/claude-cli \
  -e T2T_SANDBOX__WORK_DIR=/root/work/t2t-state/sandbox \
  test-runner-py3
```

- RAM is capped at 6 GB, swap included (`--memory-swap` equal to `--memory`): a job that needs
  more is stopped inside the container instead of slowing the host. The index peaked at about
  1.1 GB on the real suite after the memory fixes.
- The repo is read-only: anything that tries to write into it fails loudly.
- Mount paths are the old container's (`/root/work/...`): the private folder's pair set,
  drafts and reports name them.
- `T2T_*` variables override every config file, the private one too. Output folders
  (`paths.output_dir`, `paths.debug_log_dir`) are left to the private config; check that it
  points them into the private folder, not into the repo.
- uv keeps its own Python in the state volume (`UV_PYTHON_*`), so the venv doesn't depend on
  the image's Python; the claude CLI keeps its login in the `t2t-claude` volume.
- `UV_PYTHON=3.12`: without it uv takes the newest Python it can download (3.15 on the first
  try), which the project was never tested on.

## 3. First use

```bash
podman exec -it t2t claude                    # log in once (the account the runs bill to)
podman exec t2t uv sync                       # the venv, in the state volume
podman exec t2t uv run ticket2test --help
```

Never edit `src/` while a run is going in the container: the mount is live.

## Checks inside the container (tool only)

```bash
podman exec t2t uv run pytest tests/<file>.py --basetemp=/root/work/t2t-state/pytest -p no:cacheprovider
podman exec t2t uv run ruff check --no-cache .
podman exec t2t uv run mypy --cache-dir /root/work/t2t-state/mypy src
```

## Changing the image

Build the new image, then `podman rm -f t2t` and run step 2 with the new image name. The
volumes and folders stay; run `uv sync` again.
