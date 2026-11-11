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

**The data rule, tried twice and removed.** "When search's best test has no data, its class
is the template's class" gained g04 and lost g11 (replay 2: base 9, rule 9). Tightened to
"and its class keeps almost no data", it did the same (replay 3: base 8, rule 8): g11's other
class is as dataless as g04's (110 tests, 0 with data, against 179 with 1). Nothing about data
separates the two, so the switch is gone and placement is baseline-1's again.

What the three replays showed:
- Base placed 8, 9 and 8 of 15 right with no change to the code: g11 and g14 flip with the
  retrieval. A placement change worth one ticket can't be told from this noise in a single
  run.
- Every remaining C1 miss is retrieval: the reference class's tests are not retrieved (g01,
  g05, g06, g07) or rank below another class's (g04, g11, g15).
- So baseline-1 stays the yardstick; no baseline-2 for placement. Next is the retrieval
  diagnosis: per miss, where the reference's tests drop out (never found, cut by the top-k or
  the per-file cap, or reranked down), and a retrieval-only score to judge changes on.

**g04 and g15, next facts (2026-11-10).** The replay script now also prints how the template
ranking sees search's best test, the winning template and the reference class's best retrieved
test (component match, kind, action, data, rank), and once, how much of the suite sits in
classes that keep no or almost no data. It saves each retrieval under
`t2t-private/output/placement-replay/`, so only the first run makes model calls and later runs
see the same retrieval (`--fresh` retrieves again). Same command as above.
- g04: if its best test matches component and shape as well as the winning template, and g11's
  doesn't, let tests without data compete in the template ranking. If a large share of the
  suite is in dataless classes, this is worth doing whatever g11 shows.
- g15: if the winning template matched the wanted component and the reference's tests didn't,
  the component points elsewhere (draft or glossary); if neither matched, it is ranking.
- Glossary route: `docs/glossary-gaps-prompt.md`, for Haiku. An entry lifts a class's tests in
  search, so it can help g15 and the tickets whose tests aren't retrieved. It can't make a
  class without data the template's class, so it doesn't fix g04 (or g06, g07) alone.

**Replay facts (2026-11-10, on saved retrievals).**
- 39% of the suite's tests are in classes that can't supply a template: 215 of 428 classes
  have no data entry (24% of the tests), 4 more have almost none (15%).
- g04 and g11 are mirror images: in g04 search's best test is right and the action-matching
  template is wrong; in g11 the reverse. No ordering of component, action, score and data
  fixes one without breaking the other. No rule for g04.
- The reference class matched the wanted component on 1 ticket of 13. Three causes:
  - **our bug (fixed, not yet measured)**: the template ranking compared a joined marker
    ("a,b") whole; the rest of the tool splits it. g02, g03, g14, g15: all their reference
    tests match once split. `test_a_joined_component_marker_matches_by_each_of_its_values`.
  - vocabulary: g04, g12, g13 have a single-valued marker that isn't the ticket's or the
    draft's component. In g12 and g13 the component matches another class and pulls the
    template there. For Haiku: `docs/glossary-gaps-prompt.md` (the `markers` field).
  - no marker at all on the reference class: g01, g05, g06, g07, g08. Component can't help.
- Next: the replay with `--fresh` (15 small calls; the saved retrievals hold the old
  templates), to see what the fix does to g15 and that g02, g03, g14 stay.

**Fresh replay after the joined-marker fix (2026-11-10): base 8.** g02, g03, g14 and g15's
reference tests now match the component. No ticket changed because of it: in g14 and g15 a
sibling class matches the same component and wins on action and score. g13 came back and g14
went, as before with no code change: a fresh retrieval is too noisy to credit one ticket to a
change.

What the glossary says for the same tickets:
- g04, g12, g13: a matched, confirmed term has the reference class's marker, and the template
  ranking didn't use it (it takes the ticket's and the draft's words only). Built, off, not yet
  measured: `knowledge.use_in_templates`, the matched terms' markers count as the ticket's
  components (`test_a_matched_terms_marker_counts_as_the_tickets_component_for_the_template`).
  The same marker is also on the class that wins today, so it may tie rather than decide.
- g02, g03, g14, g15: a matched, confirmed term names the reference class itself. Open: does
  a term also name the sibling that wins in g14 and g15? If not, "a class a confirmed term
  names is the template's class" would settle them.
- g01, g05, g07: a term matched, with no markers, classes or folders. g06, g08, g09, g10: none
  matched. These are the glossary's gaps (`docs/glossary-gaps-prompt.md`).

**Recorded replay (2026-11-10, both columns on the same recorded replies): base 8, with
`knowledge.use_in_templates` 9.** g13 gained (a new module became a method in the reference
class), none lost. g04 and g12 unchanged: the glossary's marker is also on the class that wins
there, so it ties. In g15 the glossary names both the reference class and the sibling that
wins, so "a class the glossary names wins" can't separate them: not built. The switch is on by
default since 2026-11-11.

Glossary updated by Haiku (2026-11-11). Its entries are `proposed`. Many are outside what the
human can judge, so a new Haiku session reviews them: `docs/glossary-review-prompt.md` (every
field checked again from the suite, unsupported values removed, confirmed entries marked
`reviewed: model <date>`). Then the replay with `--fresh`, then baseline-2 (with `--resume`
available).

The glossary is thin (about 12 terms, many without markers or classes): it was built before
most of the golden tickets were pasted. `docs/glossary-gaps-prompt.md` is now a full update
prompt for Haiku: every ticket reread, a marker check and classes for every term, feature
phrases, empty entries reworked, the golden set off limits. After it: confirm the entries you
agree with, then the replay with `--fresh`.

The replay now records the model's replies per ticket and gives them back in order, so after
one recording run (15 small calls) every later run is free and sees the same replies: only the
code or a setting differs. It compares the settings in its `VARIANTS` (today: base, and
`knowledge.use_in_templates` on).

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
