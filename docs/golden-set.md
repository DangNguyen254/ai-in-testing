# The golden set: how to build it, run it and read it

Design step 1 (`docs/design-step-plan.md`): a fixed set of real tickets, each with the test a person
wrote for it, run several times per configuration and scored against that test by code. Every
later change is judged on it: kept only if it moves its criterion without lowering another.

Everything here is private: the pair set, the tickets, the drafts and the reports live in the
private folder, never in this repo.

## 1. The pair set (one JSON file, private)

```json
{
  "name": "golden",
  "repo_path": "/path/to/the/target/repo",
  "ticket_source": "paste",
  "tickets_dir": "/path/to/the/pasted/tickets",
  "ground_truth": "tests",
  "generation": true,
  "pairs": [
    {
      "id": "g01",
      "ticket": "ABC-123",
      "tests": ["service/test/<area>/<file>.py::<Class>::<test_method>"],
      "draft_file": "/path/to/output/drafts/ABC-123.drafts.json",
      "hide": ["service/test/<area>/<older_file>.py"]
    }
  ]
}
```

- `repo_path`, `tickets_dir`, `draft_file`: absolute paths, or relative to the folder the
  command runs in.
- `ticket`: the pasted ticket's file name without `.md`, in `tickets_dir`.
- `tests`: the reference test(s), as `path::Class::method` with the path relative to the repo
  root (the form `target_file` has in `decision.json`). A parametrized test is one entry; its
  cases count for C5.
- `draft_file` (recommended): the reviewed draft from `run <ticket>` (without `--continue`).
  Every run of every configuration then starts from the same draft, so draft variation doesn't
  mix into the scores. Without it, the first run drafts and later runs reuse that draft from the
  cache.
- `hide` (optional): more tests or whole files to hide besides the reference, e.g. an older
  class for the same feature, so the tool can't copy a near-twin.

Aim for 10–15 tickets from 2–3 areas, not only one.

## 2. Run it

```bash
uv run ticket2test golden golden.json --repeat 3 --label baseline-0
```

- Each ticket runs `--repeat` times (capped by `eval.max_golden_repeat`), with its reference
  (and `hide`) removed from a copy of the repo. Nothing is written to the repo.
- `--collect` also loads each generated test in the sandbox (needs a container runtime).
- Output: `output/golden/<label>-<time>/` with `report.json`, `report.md`, `c6.csv`,
  `open-coding.md`, and `runs/<pair>/r<n>/` (each run's test, data and `generated.json`).

## 3. What is scored (per run)

| # | Criterion | How |
|---|---|---|
| C1 | Same file and class as the reference (a new file in its folder when no other test of its class is left) | code; a miss says why, without names: `area` (the chosen domain doesn't hold the reference file), `excluded` (its class was filtered out), `not a candidate` (no test of its class reached the class match), `rank r/n (its match vs the winner's)`, `moved` (decided right, a fallback moved it) |
| C2 | Makes every call the reference makes, compared by what a call resolves to (the page-object class and member, or the class defining a helper), so the same action reached through another chain or local counts; and copies no reference helper's inside calls | code; `c2_recall`, `missing_helpers`, `inlined` |
| C3 | Has every key path of the reference entry, two levels deep (`policy.<block>`, `targets[].<key>`) | code; `c3_recall`, `missing_blocks` |
| C4 | No value nothing supports (no made-up-value warning) | code |
| C5 | As many cases as the reference | code |
| C6 | The checks cover the expected outcome | **you**, in `c6.csv` |
| C7 | Validators pass (and collect, when run) | code |
| C8 | The generation context named the reference's helpers and data blocks | code, from the context report in `generated.json` |

The report gives each criterion's **pass@1** (share of all runs) and **pass^k** (share of tickets
whose k runs all pass).

Reading C8 with C2/C3: C8 fails → retrieval never showed the model what it needed. C8 passes but
C2/C3 fail → the model had it and didn't use it.

`generated.json` now also lists every context piece (`context_report`: title, tokens, kept or
dropped), so you can see what the budget was spent on.

After a scorer change, score a finished run again without rerunning it:
```bash
uv run ticket2test golden-rescore output/golden/<run>/report.json --set golden.json
```

## 4. Your part after a run

1. **C6:** open `c6.csv`, write `yes` or `no` per run (do the test's checks cover the ticket's
   expected outcome?), then:
   ```bash
   uv run ticket2test golden-report output/golden/<run>/report.json --c6 output/golden/<run>/c6.csv
   ```
2. **Open coding:** in `open-coding.md`, one line per run: the first thing that's wrong, in your
   own words. Afterwards group the lines into fewer than 10 failure modes and count them. That
   count, not the last run seen, decides what to change first.

## 5. Ablations (step 3)

One switch per run, everything else as in the baseline, same golden set and `--repeat`. Switches
are config values; set them for one run with environment variables (they override the config):

| Switch off | Variable |
|---|---|
| Area and framework guides | `T2T_GUIDES__USE_IN_GENERATION=false` |
| Glossary and known values in the draft | `T2T_KNOWLEDGE__USE_IN_DRAFT=false` |
| Known values in the generation context | `T2T_KNOWLEDGE__USE_IN_GENERATION=false` |
| Warning-started repair rounds | `T2T_REPAIR__WARNING_CHECKS='[]'` |
| Helper code in the context | `T2T_GENERATE__CONTEXT_HELPERS=false` |
| The class's other entries in the context | `T2T_GENERATE__CONTEXT_ENTRY_LIST=false` |
| Base entry chosen from the class's entries | `T2T_GENERATE__BASE_ENTRY_FROM_CLASS=false` |
| Raised context budget (back to 12k) | `T2T_CONTEXT__MAX_TOKENS=12000` |
| Coverage check (on, to test it) | `T2T_GENERATE__REUSE__COVERAGE_CHECK=true` |
| A draft's "both" treated as "must run on both" (excludes gated classes) | `T2T_GENERATE__REUSE__BOTH_MEANS_UNSPECIFIED=false` |
| No fallback to classes of the other kind (UI / API) | `T2T_GENERATE__REUSE__KIND_FALLBACK=false` |

Example:

```bash
T2T_GUIDES__USE_IN_GENERATION=false uv run ticket2test golden golden.json --repeat 3 --label no-guides
```

Each report records the switches it ran with (`## Config`), so two reports can be compared.
Drafts come from `draft_file`, so draft switches (the first two rows) only take effect for pairs
without one.

Reuse switches under test (each off = baseline-0): `generate.reuse.both_means_unspecified`, `generate.reuse.kind_fallback`, `generate.reuse.classes_from_domain` (every class of the area is scored for a new method, not only the closest tests' classes). A C1 miss also notes `template's class` when the reference's class held the closest template.
`generate.reuse.template_class_wins`: the closest template's class takes the new method whatever its class match (experiment 3). A C1 miss notes `template's class`, `template in another class` or `no template in the area`.
