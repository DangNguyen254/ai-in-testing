# Design step: where the work stopped (2026-11-05)

Branch `design-step`, last code commit `dbc2970`. Method (`docs/design-step-plan.md`): measure on
the golden set, do error analysis, then change one thing at a time behind a config switch and
judge it on golden runs. No per-run fixing.

The work moved machines after the old machine's podman VM hung during experiment 3c (it ran out
of memory). The three folders were backed up: the repo, the container's tool copy (`ai-prj`), and
the private folder (`t2t-private`: the golden set, frozen drafts, glossary, every report and kept
run). On the new machine the repo is mounted into the container (see
`docs/new-machine-prompt.md`).

## Baseline-0 (all 15 tickets, 3 runs each, rescored, C6 merged)

| Criterion | pass@1 | pass^k |
|---|---|---|
| C1 placement | 38% | 33% |
| C2 helpers | 11% | 0% |
| C3 data blocks | 36% | 33% |
| C4 no made-up values | 80% | 67% |
| C5 case count | 82% | 73% |
| C6 checks cover the outcome | 28% | 14% |
| C7 validators | 82% | 80% |
| C8 context recall | 62% | 53% |

133 LLM calls, $1.46. Its report is in the private folder's `output/golden/` (label
`baseline-0`); the first check on a new setup is to rescore it and get the same numbers.

Error analysis (by a Claude Code session with `docs/error-analysis-prompt.md`): placement was the
first failure on 10 tickets; steps or checks dropped on 3; an invented member the validator
didn't flag on 1 (seen in 6 more); no data template on 1 (g08). Placement sub-causes: deployment
gate excluded the class (g09, g13), the kind filter (g05, g08), class chosen by name/word match
(g04, g06, g07, g14, g15), retrieval miss (g01).

## Experiments so far (each a switch in `generate.reuse`, all now `true` in `config.yaml`)

| # | Switch | What it does | Result |
|---|---|---|---|
| 1 | `both_means_unspecified` | a draft's "both" (also its default) flags a deployment-gated class instead of excluding it | fired; not the cause on g13 |
| 1 | `kind_fallback` | no class of the draft's kind in the area: classes of any kind are considered | fired on g05, g08; not enough alone |
| 2 | `classes_from_domain` | every class in the area is scored for a new method, not only those of the 8 closest tests | g05/g13 were "not a candidate" before; now scored, but rank low (g05 21/22) |
| 3 | `template_class_wins` | the closest template's class takes the new method whatever its word-overlap score | g08: decided right, then a later step made it a module (see below) |

Off = baseline-0 behaviour for each. The report's Config block lists all four.

Diagnostics added on the way (no model cost):
- Each run records how placement was decided (`reuse_placement` in `generated.json`), and a C1
  miss in the runs table says why, without names: `area`, `excluded`, `not a candidate`,
  `rank r/n (its match vs the winner's)`, `decided right, output is … in another place`, plus
  where the template was (`template's class` / `template in another class` / `no template in
  the area`).

Bugs found and fixed in `dbc2970`:
- With experiment 1's switch, a gated class holding the closest template raised a KeyError: g09
  and g13 crashed in experiments 2 and 3 (they looked like connection failures).
- Regenerating with proposed members threw away the first pass's reasons, so g08's fallback
  (method → module) didn't say why.

Fixed on the new machine (2026-11-05; not committed, the copy has no git history):
- The catalog's class order (`SymbolCatalog.mro`) walked bases depth-first; it now uses
  Python's C3 order, so in a diamond (`D(B, C)`, both from `A`, only `C` overriding) a lookup
  finds `C`'s member, as Python does, not `A`'s. Where Python would refuse the order, the old
  walk is kept. Found by the research review. It can change member lookups in validation,
  placement and the C2 scorer, so it also lands in experiment 3c. The pre-fix file is kept in
  `.scratch/pre-c3/catalog.py`: if the baseline rescore differs from the table above, rescore
  again with it in place to tell a setup problem from this fix.

Experiment 3c (2026-11-09, one run each, $0.08): g09 and g13 placed right (C1 yes; both
missed in all 3 baseline runs); g08 failed: "no template test with a JSON data entry". Counts
by `.scratch/pair_facts.py`: g08's area keeps no data at all (44 test files, none with a data
file; the reference reads no data). Fixed, not yet measured: a class that keeps no data gives
a template without an entry; the new test reads no data and comes without a data file (the
validation sends back a test that reads data anyway); a method patch then changes only the
code. Tests: `tests/test_dataless.py` on the stand-in's `TestExceptionsWidgets`.
Rerun of g08 with the fix (`exp3c-dataless`, one run, $0.02): generated for the first time
with the switches on, placed right (C1 yes), C3/C4/C5/C7 pass; C2 0.75 with C8 helpers 0.75:
the one helper it missed was not in the context (retrieval).

## Confirm-placement (all 15 tickets, 2 runs each, all switches on, C3 and no-data fixes)

| Criterion | baseline-0 pass@1 | now pass@1 | now pass^k |
|---|---|---|---|
| C1 placement | 38% | **60%** | 60% |
| C2 helpers | 11% | 7% | 7% |
| C3 data blocks | 36% | 33% | 33% |
| C4 no made-up values | 80% | 87% | 87% |
| C5 case count | 82% | 93% | 93% |
| C7 validators | 82% | **67%** | 67% |
| C8 context recall | 62% | 57% | 53% |

97 LLM calls, $0.93 (label `confirm-placement`). pass^k is over 2 runs, baseline-0's over 3:
compare pass@1. Every ticket gave the same C1 in both runs.
- C1: placed right on 9 of 15 (g02, g03, g08–g14). New since baseline: g08, g09, g13, g14.
  The six misses: five are "template in another class" (g01, g04 by 0.31 vs 0.32, g05, g06,
  g15): with `template_class_wins` placement follows the template, so these are template choice
  (retrieval), not the class score. g07 is "not a candidate" even with `classes_from_domain`:
  not yet explained.
- C7 fell (g05, g06, g07, g09, g10 fail in both runs; read with `.scratch/c7_checks.py`, check
  ids and message kinds only):
  - g05, g06, g07 (all method patches into a class): one `ids` error from the first attempt to
    the last, "orphan entries" (g05, g07) and "recorded ids differ" (g06). Our bug: patch
    validation drops findings the unpatched file already had, matching them by message, and
    both messages listed all of the file's ids, which the patch changes. A stale entry already
    in the class's data file became the patch's own error. Fixed: one finding per stale entry,
    the recorded-ids message gives only the differences, and findings match by test too
    (`test_a_problem_the_file_already_had_is_not_reported_as_new`). Rerun `fix-patch-ids`
    (g05–g07 × 2, $0.16): C7 6/6 (was 0/6), 14 calls (no repairs wasted); C1 still no on all
    three (template choice, as expected).
  - g09, g10 (new modules): one "undefined name" left after 3 repairs. Read with
    `.scratch/undefined_names.py` (facts only): a CapWords name defined only in the template's
    own file, in the context, imported nowhere in the suite. Likely cause: `class_scaffold`
    copies the template's class line and imports, but a base class defined in that same file
    has no import to copy. Confirmed: in all four runs it is the base of the new class, a small
    class in the template's file that the template's own class inherits (in g10 its name has
    the test-class prefix, so importing it would collect it twice). Fixed: the scaffold brings
    such bases whole, before the class, and the class shell copies them in code
    (`test_a_base_class_defined_in_the_templates_file_comes_with_the_new_module`). Rerun
    `fix-local-base` (g09, g10 × 2, $0.17): C7 4/4 (was 0/4), C1 still yes; C2 0 with C8
    failing (helpers 0.50 / 0.80, g10 blocks 0.50): retrieval, as in the baseline analysis.
- C2 stays the weakest: C8 passes but C2 fails on g01–g04, g06, g11, g13 ("had it, didn't use
  it": D1/D2's target). C8 misses (retrieval): g08, g09, g10, g12, g14, g15.

## Baseline-1 (2026-11-10: all 15 tickets, 2 runs each, every switch and fix in)

The new yardstick. Compare pass@1 (baseline-0 had 3 runs).

| Criterion | baseline-0 | confirm-placement | baseline-1 pass@1 | baseline-1 pass^k |
|---|---|---|---|---|
| C1 placement | 38% | 60% | 60% | 60% |
| C2 helpers | 11% | 7% | **20%** | 13% |
| C3 data blocks | 36% | 33% | 33% | 33% |
| C4 no made-up values | 80% | 87% | 83% | 80% |
| C5 case count | 82% | 93% | 87% | 87% |
| C7 validators | 82% | 67% | **100%** | 100% |
| C8 context recall | 62% | 57% | 63% | 60% |

70 LLM calls, $0.59 (label `baseline-1`; confirm-placement took 97 calls, $0.93).
- C7: 30/30. Both fixes (patch ids, local base classes) hold on every ticket, and no calls
  go to repairs that can't succeed.
- C1: unchanged and deterministic. The same 9 tickets are placed right, and the same 6
  misses have the same ranks: g07 is "not a candidate", and g01, g04, g05, g06 and g15 are
  "template in another class". This matches the 2026-11-09 read under step 3 below.
- C2: 6/30 (g01 r1, g02 ×2, g05 ×2, g11 r2). It is still the weakest. Where C8 passes and C2
  fails (g01 r2, g03, g04, g06, g11 r1, g13), the model had the helper and didn't use it.
- C3: 10 of 15 fail, and on 7 of them C8's blocks are 1.00 (g02, g03, g05, g09, g11, g12,
  g13). The data blocks were in the context, but the entry left them out. g05 and g11 are at
  0.00, so their entry has none of the reference's paths. That is not yet explained.
- C5 misses: g04 and g13 (both runs). C4 misses: g06 r1, g10, g15.
- C8 misses (retrieval): g08, g09, g10, g12 r1, g14, g15. The same set as before.

## Next steps, in order (2026-11-09, end of day; all pushed up to 68e4545)

1. **baseline-1**: done (above).

**Placement replay (2026-11-10)**: one retrieval per ticket (16 model calls), then the
placement decision in code under six settings. Tickets placed right, of 15:

| Setting | Right | Against base |
|---|---|---|
| base (baseline-1's rules) | 8 | g11 is a miss here and was right in baseline-1: retrieval varies run to run |
| kind as a preference | 5 | lost g09, g10 (a method where a new file was right), g12; gained none |
| class by summed retrieval scores | 6 | lost g08, g12; gained none |
| both | 4 | |
| class of search's best test | 9 | gained g04; lost none |
| best test, with kind as a preference | 7 | lost g09, g10 |

- Kind as a preference and the summed scores were removed from the code: both lost tickets
  and gained none.
- g07 is not a placement problem: no test of its reference class is retrieved, and the class
  keeps no data. It moves to the recall group (g01, g05, g06, g07).
- g04 is the one ticket a placement rule fixes: search ranks a test of the reference class
  first, but 1 of its 179 tests has data, so it couldn't be the template.
- g15 and g11: the reference class's tests are retrieved but rank last (g15: 2/2). No rule
  over retrieval scores fixes that; it is ranking inside retrieval.

**Built, not yet measured**: `generate.reuse.dataless_hit_class` (off in `config.yaml`). When
search's best test in the area has no data entry, its class is the template's class. When it
has data, the template ranking (component, shape, score) already weighed it and stands, so
this is narrower than "class of search's best test" above and can't change a ticket where the
best test has data. On the stand-in nothing else changes with it on. Check with the replay
(16 small calls; it prints base against the rule, and whether the best test has data):

```bash
podman exec -e T2T_CONFIG=/root/work/t2t-private/company.yaml t2t uv run python .scratch/placement_replay.py /root/work/t2t-private/golden.json
```

If g04 turns YES and nothing else moves: default it on, then baseline-2.

Second replay (15 calls): base 9, with the rule 9. g04 gained, g11 lost: there, search's best
test has no data and is in another class, and the rule moved the method away from the
reference class the template ranking had picked. The rule stays off.

Tightened (built, off, not yet measured): the rule now also needs the best test's class to
keep almost no data (`dataless_class_max_share: 0.1` of its tests at most; g04's class: 1 of
179). Whether it spares g11 depends on how much data that other class keeps, which the replay
now prints ("its class: n tests, m with data"). Run the same replay command again (15 small
calls). g04 YES with g11 unchanged: default it on. g11 still lost: drop the switch.
2. **g07, "not a candidate"** (free): placement scores only classes whose tests are of the
   draft's kind, and a test counts as UI only when a `self.<chain>` starts at a chain root
   (`index.chain_roots`). Suspect: the reference class's tests are classified as the other
   kind (they reach pages another way), and `kind_fallback` doesn't fire because the area has
   classes of the draft's kind. (An empty class is ruled out: it would read "not a new file
   next to it".) Check: `uv run python .scratch/class_kinds.py <golden.json> <report.json> g07`.
   If confirmed: classify a test as UI when it reaches a page object by any chain (the
   catalog already resolves them), or score every class and let kind only break ties.
3. **Template in another class** (g01, g04, g05, g06, g15): with `template_class_wins` the class
   follows the template, and the template is the first test with data ranked by (same
   component marker, same shape, retrieval score) whose class is in the area. First check, per
   run: were the reference class's tests in the context at all, and does the chosen template
   share its component marker and kind:
   `uv run python .scratch/template_facts.py <golden.json> <report.json> g01 g04 g05 g06 g15`.
   - not in the context: a recall problem (query, glossary entries for these features);
   - in the context but ranked below a sibling: options, cheapest first:
     a. rank classes, not single tests: sum the retrieval scores of each class's tests in the
        area and take the template from the best class (deterministic, a switch);
     b. glossary entries that name the feature's class (a human edit; `backed` already lets
        the template's class win when the ticket names its feature);
     c. a bounded model choice among the top few classes (a new LLM step: ask the human).
   **Read (2026-11-09, on confirm-placement's runs):**
   - g07: the reference class is an API class (23 tests, all API, none reaching a page
     object another way); the draft said UI in both runs. Kind is a hard filter and the area
     has UI classes (13 of 44), so `kind_fallback` doesn't fire. Cause: the filter trusts the
     draft's guess. Fix: kind as a preference (other-kind classes scored, with a factor).
   - Recall (the reference class's tests never in the context): g01 (template from another
     file and component), g05 (same file, other component), g06 (its only remaining test has
     no data, so it can't be a template anyway). Retrieval work, not placement.
   - Ranking (in the context, lost): g04 (reference class at context positions 2–3, but 1 of
     its 179 tests has data; templates need data, so a data-keeping class in the same file
     wins), g15 (positions 5–7 of 7; the template from another file and component). Fix:
     choose the class from its tests' retrieval ranks (option a), then its template, with
     the no-data path when the class keeps little data.
4. **C2 "had it, didn't use it"** (g01–g04, g06, g11, g13): D1/D2 (step plan, contract cards).
5. Later: the validator hole for invented members; dropped steps; C8 retrieval misses (g08,
   g09, g10, g12, g14, g15).

## Running in the container

The `t2t` container was created before `company.yaml` existed, so it has no `T2T_CONFIG`.
Pass the config on every exec, for example:

```bash
podman exec -e T2T_CONFIG=/root/work/t2t-private/company.yaml t2t uv run ticket2test golden /root/work/t2t-private/golden.json --repeat 2 --label <label>
```

The `t2t-private` folder name isn't secret; only its contents and the real suite's names are.

A golden run saves its report after every run (2026-11-10). If it stops, or you stop it with
Ctrl+C to continue the next day, run the same command with `--resume` and the run's folder:

```bash
podman exec -e T2T_CONFIG=/root/work/t2t-private/company.yaml t2t uv run ticket2test golden /root/work/t2t-private/golden.json --repeat 2 --resume /root/work/t2t-private/output/golden/<label>-<time>
```

The command prints this folder when it starts. The config must be the same as when the run
began. Runs that failed on a model call (a lost connection) are made again; the others are kept.
Each run's folder now also keeps `retrieval.json`, so placement can be replayed with no model
calls.

## Reading results without leaking names

Reasons and errors carry the private suite's names. When asking the human for them, give a
command that masks them (file paths, capitalised names, bracketed values, the `domain:` line),
and remind them to check before pasting. Never repeat a name that slips through.
