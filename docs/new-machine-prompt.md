# Prompt: first session on the new machine

Paste everything below the line into the first Claude Code session, started in the repo folder on
the new machine.

---

This project moved to a new machine (Ubuntu). Before any work, get oriented and get the setup
working; don't change code until the setup check passes.

**1. Read, in this order:** `CLAUDE.md`, `docs/design-step-status.md` (where the work stopped:
the baseline, the experiments, the next steps), `docs/design-step-plan.md`, `docs/golden-set.md`,
`docs/commands.md`. Skim `docs/trial-findings.md`. We are on branch `design-step`.

**2. The setup, and what's different from the old machine:**
- The tool runs inside a podman container against a private test suite. The private folder (the
  golden set, its frozen drafts, the glossary, all reports and kept runs) was restored from a
  backup to `/root/work/t2t-private` inside the container. Ask me for the container's name.
- The old machine copied the repo into the container (`scripts/to_container.py`). On this
  machine the repo is **mounted** into the container instead. Set that up with me:
  - Propose the `podman` mount and run options, and wait for my OK before creating or changing
    a container.
  - Mount the repo read-only, so nothing in the container can change it. The things that need
    to be writable go to container paths: the venv (`UV_PROJECT_ENVIRONMENT`), uv's cache
    (`UV_CACHE_DIR`), and the tool's caches and outputs (`T2T_PATHS__...` overrides; check
    `config.yaml` `paths` for which ones write). Check that nothing else writes into the repo.
  - With a live mount, an edit on the host changes the code a running job imports. **Never edit
    `src/` while a run is going in the container.** If edits during runs become necessary,
    mount a separate git worktree at a fixed commit for the container instead, and say so.
- **The venv check is your job:** inside the container, confirm the venv points at the mounted
  repo (not an old path), that `uv run ticket2test --help` works, and that the code the
  container imports is the host's current commit (`git log -1` on the host vs. the mounted
  copy).

**3. Check that it works, without model calls:** rescore the baseline report against the golden
set (`golden-rescore`, see `docs/commands.md`). Its numbers should match the baseline in
`docs/design-step-status.md`. If they don't, stop and tell me what differs.

**4. Then:** tell me in a few lines where the work stands and what the next step is, per
`docs/design-step-status.md`. Wait for my go before any run that calls a model.

**Rules that matter most here (all in `CLAUDE.md` or the status note):**
- Never write or say the private suite's names, keys, or values: not in the repo, not in chat,
  not in commit messages. Reports I paste may carry some; don't repeat them.
- Ask before any run that costs money; heavy jobs one at a time; ask before touching the
  container while something runs in it.
- Never `git push` without my explicit OK. No co-author or "Generated with" lines.
- Stay inside the repo (Hard Constraint 9). Temporary files go in `.scratch/`.
