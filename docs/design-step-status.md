# Design step: status

## Start here (2026-11-11)

How the work is done is in `CLAUDE.md` ("How the work is done now"). This file is the record:
the newest state is in this block, and the history below it is in the order it happened.

- **Yardstick: baseline-2** (15 × 2, label `baseline-2`): C1 53%, C2 17%, C3 40%, C4 83%,
  C5 87%, C7 97%, C8 63%. The same as baseline-1 within noise.
- **Placement (C1) is parked** at 9 of 15 on the recorded replay. Seven rules were tried and
  each traded one ticket for another. Misses: g01, g04, g05, g06, g07, g15. The cheap answer
  left is D6 (the QE names the nearest test).
- **Now: C2 (helpers called).** No miss is an inlined helper. Most are steps the template
  lacks, and half were never shown in use in the context. `generate.context_member_cards`
  was built for this and **measured no gain** (label `member-cards`: C2 20% against 17%, g12
  gained and g07 lost; everything else within noise). It stays off.
  The missed-helper count didn't drop either (54 against 51).
  `generate.step_plan` (D1's smallest form) measured **no gain** either (C2 17%, g01
  gained, g05 lost). Both stay off.
- **Next:** C3, D1 paused. Most C3 misses are whole sections the model left out with the
  base or a sibling holding them (see "C3: what the misses are"). `generate.seed_floor`
  (off) is built and waits for its run; its reach is small (g10, g12).
- **Open:** g06 fails to generate 2 times in 3 (the code doesn't parse from line 1);
  `.scratch/c2_misses.py` can't read the template's code in 13 runs; C8 tests names only (a
  stricter "shown in a call" variant is worth adding to the scorer); g12's glossary entry
  wants a person's look; a blind try on new tickets (3 to 5 with a framework, 1 or 2
  without).
- **On:** `knowledge.use_in_templates`, the joined-marker fix, the updated and reviewed
  glossary. **Off:** `knowledge.search_named_classes`, `generate.reuse.glossary_class_wins`,
  `generate.context_member_cards`, `generate.step_plan`, `generate.seed_floor`. **Removed:** `kind_as_preference`,
  `class_from_retrieval`, `dataless_hit_class`.
- Local commits are not pushed (origin is at `68e4545`); push only when the human says so.

## Where the work stopped on the old machine (2026-11-05)

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

**Fresh replay with the updated, reviewed glossary (2026-11-11): 9 of 15 placed right.**
- The glossary now reaches every ticket: a matched term names the reference class on 14 of 15
  (4 before the update).
- Placement didn't move with it (9; the markers switch on or off gives the same 9 now). Right:
  g02, g03, g08–g14. Misses: g01, g04, g05, g06, g07, g15.
- g01, g05, g06, g07: the glossary names the reference class and still none of its tests is
  retrieved. Cause, in `retrieve`: a named class is only lifted in the ranking, so its tests
  must already be found by the ticket's own words; the fallback search in the glossary's words
  runs only when no named place has any hit, so with several matched terms one term's hit
  keeps another term's class out. Built, off, not yet measured:
  `knowledge.search_named_classes` (each named class without a test among the results is
  searched itself: its `named_class_tests` closest tests join, for at most
  `named_classes_max` classes).
  `test_a_class_the_glossary_names_is_searched_when_the_tickets_words_miss_it`.
- g04 and g15: the glossary names both the reference class and the class that wins; unchanged.

**`search_named_classes` measured (free replay): 9 against 9, stays off.** It got one more
reference test retrieved (g05), none for g01, g06, g07 (their added tests rank below the top
10), and it pushed g12's reference tests down. No placement change.

**Built, off, not yet measured: `generate.reuse.glossary_class_wins`.** The retrieval route
keeps running into the template step (tests must be found, rank high, and have data). The
glossary is a shorter route: when the confirmed terms a ticket matched name exactly one class
in the chosen area, that class holds the template and takes the method, whatever search ranked
first and whatever kind the draft guessed (flagged for the reviewer when the kind differs). A
class without data uses the no-data path. Several named classes, or a term nobody confirmed,
change nothing. `test_the_one_class_a_confirmed_glossary_term_names_takes_the_method`.
Expected from the facts: g06 and g07 (one named class each, not today's winner); g05 and g01
depend on how many classes their terms name in the area; g04 and g15 name two and won't move.

**`glossary_class_wins` measured (free replay): 9 against 9, stays off.** It gained g07 (the
only class the terms name; an API class under a UI draft) and lost g12: there the one class a
confirmed term names in the area is not the reference class. Where exactly one class is named
and the reference class still has tests (g07, g08, g11, g12, g13), the glossary is right on 4
of 5 and today's placement on 4 of 5: the rule is as good as the glossary's entry, no better.
g06 names two classes, g01's naming term is only proposed: unchanged. Worth a person's look:
g12's entry (is that class a second valid home, or a wrong entry?).

**Where placement stands (2026-11-11).** 9 of 15 on the recorded replies, after seven rules
tried: each one traded a ticket for another. With 15 tickets and one ticket of run-to-run
noise, placement can't be tuned further on this set. Kept from the work: the joined-marker fix,
`knowledge.use_in_templates` (on), the updated and reviewed glossary, checkpoints and
`--resume`, the kept retrievals, the replay with recorded replies. Off: `search_named_classes`,
`glossary_class_wins`.

Next: **baseline-2** (all 15 × 2, `--resume` if it stops). The replay only sees placement;
the new glossary also feeds the draft, search and the generation context, so C2, C3 and C8 may
have moved. Then the weakest criteria: C2 (20%) and C3 (33%), both far below C1 (60%).

### Baseline-2 (2026-11-11: all 15 × 2, updated and reviewed glossary, `use_in_templates` on)

| Criterion | baseline-1 pass@1 | baseline-2 pass@1 | baseline-2 pass^k |
|---|---|---|---|
| C1 placement | 60% | 53% | 47% |
| C2 helpers | 20% | 17% | 13% |
| C3 data blocks | 33% | 40% | 33% |
| C4 no made-up values | 83% | 83% | 80% |
| C5 case count | 87% | 87% | 80% |
| C7 validators | 100% | 97% | 93% |
| C8 context recall | 63% | 63% | 53% |

69 LLM calls, $0.70 (label `baseline-2`). **Nothing moved beyond noise**: one run is 3 points,
and every difference is one or two runs.
- One failed run, g06 r1: the model's code didn't parse on all 3 attempts. g06 r2 generated,
  so chance. It costs every criterion one run; `--resume` makes it again.
- C1: 16/30. The same 6 tickets miss in both runs (g01, g04, g05, g06, g07, g15). g11 and g14
  are right in one run and wrong in the other: the run-to-run retrieval noise the replay
  showed. The glossary work didn't lift placement in a full run, as the replays said.
- C2: 5/30 (g02 ×2, g05 ×2, g07 r2). Of the 24 misses, 16 had every reference helper in the
  context (C8 helpers 1.00): the model had them and didn't call them. Generation, not search.
- C3: 12/30. g05 now passes (was 0.00). Of the 17 misses, 11 had every block in the context
  (g02, g03 r2, g09, g11, g12, g13); 6 lacked some (g10, g14, g15). g11 is still at 0.00.
- C4 misses: g10, g15. C5 misses: g04 r1, g13.
- C8 misses: g08, g09 r2, g10, g12 r2, g14, g15. The same tickets as baseline-1.

`--resume` made g06 r1 again and it failed the same way ($0.73 in all), so g06 failed 2 of 3
generations: more than chance. Its parse error's message is printed by the script below.

First step on C2, free: `.scratch/c2_misses.py <golden.json> <report.json>` counts, per
missing helper and without names, whether it was in the context, whether the template calls
it, whether another test of the output's class calls it, whether the new test used another
member of the same page, whether it was inlined, and whether it is out of reach (a method of
the reference class, output in another class). It also counts how many of the new test's calls
its template makes. Reading: mostly "template doesn't call it" and "calls all in the template"
means the model copies the template's steps, which D1 (a step plan from a menu) targets;
"in the context, same page used" means it picked the wrong member, which D2 (contract cards)
targets; "out of reach" is placement, not generation.

**First run of the script (baseline-2, 24 runs missing C2, 51 missing helpers):**
- Inlined: 0 of 51. The trial's "helper body copied" failure isn't what C2 catches now.
- Out of reach (a reference-class method, output elsewhere): 10, all g14 r2 and g15.
  Placement, not generation.
- The template calls it: 8 of 51 (g03, g13, one each in g04 r1 and g09 r1). The other 43 are
  steps the template doesn't have. Where the template's calls could be read, the new test
  mostly repeats them (g03 3 of 3, g04 5 of 6, g13 5 of 8).
- Same page or class used, other member: 20. Page or class not touched at all: 31.
- 10 of the 24 runs miss by one helper (g01, g03, g07 r1, g08 r2, g11, g12).
- Name in the context: 43 of 51, but this is C8's test, and C8 only asks whether the word
  occurs anywhere in the context. A common member name passes even when it is another page's.
  So "had it, didn't use it" is weaker evidence than it looked.
- Not trusted yet: 11 runs show a template with 0 `self` calls, and several new tests make 1
  or 2. Either those tests work through calls C2 doesn't count (locals, constructors, module
  functions) or the template wasn't read.

The script now also counts `shown` (a chunk in the context calls that member on that page),
`def` (its definition is in the context), `common` / `rare` (how many of the reference
class's other tests call it), and all calls next to `self` calls. That run decides: mostly
not shown and not defined means the generator never saw the member as a choice (a member
menu for the pages in play); shown but unused means it needs to know what the member does
(D2) or be made to map each step to a member (D1).

**Second run (the sharper counts), of the 51 missing helpers:**
- Shown in a call by some chunk in the context: 25. Not shown anywhere: 26. Its definition
  in the context: 2 (undercounted for base-class helpers, whose chunk is the class header).
- No other test of the reference class calls it (`rare`): 27, of which 14 are g09 and g10,
  whose reference class has no other test. At least half call it (`common`): 13, of which 7
  are out of reach (g14 r2, g15).
- The new tests are not thin: 3 to 19 calls in all each. C2 counts `self` calls only.
- Still open: 13 runs show a template with no calls at all, so the template's code wasn't
  read by the script there. "Follows the template" holds only where it was read.

Reading, corrected: about half of the misses were never an option the generator could see in
use, so "the model had it and didn't use it" (from C8) was too strong, and for C2 the context
is part of the problem. The context shows the calls the template and the similar tests make;
a step none of them has is at most a name in the chain list.

**Built, off by default: `generate.context_member_cards`** (`generate/members.py`, D2 in its
smallest form). One line per member the new test can call: the non-test methods of the
template's class and its in-repo bases, and the members of the pages the template, the
examples and the class's other tests reach. Each line has the call, whether it is an action
or a value, its parameters, its owner, the first sentence of its docstring, and "returns a
value" / "asserts" from its body. The draft's words rank them; `member_cards_max` (60) caps
them; a shared base page's members come once, last. The piece sits before the base classes
and examples, so the budget keeps it. No prompt change, no LLM call.
`test_member_cards_list_what_the_test_can_call_beyond_the_template`.
To measure: `T2T_GENERATE__CONTEXT_MEMBER_CARDS=true` on a golden run, against baseline-2
(C2 first; C7 and C4 must not fall). It can't reach the 10 out-of-reach misses or a member of
a page no test of the class touches.

**Measured (2026-11-11, label `member-cards`, 15 × 2, 71 calls, $0.61): no gain. The switch
stays off.**

| Criterion | baseline-2 pass@1 | member-cards pass@1 | member-cards pass^k |
|---|---|---|---|
| C1 placement | 53% | 53% | 47% |
| C2 helpers | 17% | 20% | 20% |
| C3 data blocks | 40% | 43% | 40% |
| C4 no made-up values | 83% | 90% | 80% |
| C5 case count | 87% | 87% | 87% |
| C7 validators | 97% | 97% | 93% |
| C8 context recall | 63% | 63% | 60% |

- Every difference is one or two runs. All 30 runs generated (g06 r1 too, this time).
- C2: 6/30 (g02 ×2, g05 ×2, g12 ×2) against 5/30. g12 gained both runs; g07 r2 passed in
  baseline-2 and both g07 runs are at 0.00 now. One ticket for another: not a gain.
- C8's helper recall didn't rise on the tickets that lacked a helper's name (g08 0.75, g09
  0.50, g10 0.80, g14 0.80). The cards' text is in the context C8 reads, so on those tickets
  the cards did not list the missing helper: it is outside the template class's lineage and
  the pages its tests reach, or past the cap of 60.
- On the other tickets the name was already in the context and the helper is still not
  called. So listing what can be called is not enough by itself.
- Not yet known: whether fewer helpers are missed per run (51 in baseline-2). The script
  counts it for free on this run's report.
- The count, read with the script: **54 helpers missed over 24 runs, against 51 over 24 in
  baseline-2** (which also had one failed run). No drop. Name in the context 46 of 54, shown
  in a call 26, inlined 0, out of reach 10, the template calls it 5, rare 31. The same
  picture as before the cards.
- So the generator doesn't pick a member because it is listed. The switch stays off; the
  code is kept only as the menu for D1 (each draft step mapped to a member before the code
  is written) and is removed if D1 doesn't use it.

**Built, off by default: `generate.step_plan`** (`generate/plan.py`, prompt `step_plan_v1`;
D1 in its smallest form). One LLM call before generation, on the generate step's model: the
draft's lines (preconditions, steps, expected outcome; labels S1...) and the member cards
(labels M1..., the same ranked and capped list) go to the model, and it answers with labels
only, at most 3 members a line, none when no member clearly does the line. Code drops any
label that wasn't shown. The result is a context piece, "Step plan", with the chosen cards
under each step, placed where the cards go (before the base classes and examples). The
generator still writes the code; the generate prompt is unchanged. A plan that can't be read
means no plan, and its calls are counted. It works without `context_member_cards` (the cards
are its menu either way). `test_step_plan_puts_the_member_for_each_step_into_the_context`.
- Not in this version: code writing the calls from the plan, and a check that the generated
  test calls what was planned. Both wait for a run that shows the plan helps.
- It can't choose a member the cards don't list (g08, g09, g10, g14 above) and can't fix the
  10 out-of-reach misses.
- To measure: `T2T_GENERATE__STEP_PLAN=true` on a golden run, label `step-plan`, against
  baseline-2: C2 and the missed-helper count (51) first; C7 and C4 must not fall. About 30
  more Haiku API calls, so about $0.75.

**Measured (2026-11-12, label `step-plan`, 15 × 2, 108 calls, $0.87): no gain. Off.**

| Criterion | baseline-2 | member-cards | step-plan |
|---|---|---|---|
| C1 | 53% | 53% | 57% |
| C2 | 17% | 20% | 17% |
| C3 | 40% | 43% | 43% |
| C4 | 83% | 90% | 87% |
| C5 | 87% | 87% | 83% |
| C7 | 97% | 97% | 97% |
| C8 | 63% | 63% | 70% |

- C2: 5 of 30 again. g01 r2 gained; g05 lost both runs (it passed in baseline-2 and in
  member-cards). One ticket for another.
- C8's rise is not a gain: the plan's text is in the context C8 reads, so it adds names.
- g15 r2 failed (the code didn't parse, 3 attempts), as g06 did before.
- Reading: neither listing the members nor having a model pick one per step makes the
  generator call them.
- Missed helpers (script): 54 over 24 runs (baseline-2 51, member-cards 54). The new tests
  make more `self` calls (123 against 91 in member-cards) and follow the template less (25
  against 29), and use another member of the right page more often (26 against 20). So the
  plan changes what is called, but not into the reference's helpers: more calls, not the
  right ones.
- D1 is paused (the human's call); C3 is next.

### C3: what the misses are (2026-11-12, free, on the `step-plan` report)

`.scratch/c3_misses.py <golden.json> <report.json>` counts, per reference block (key path two
levels deep, as C3 scores it) the new entries lack: whether the base entry has it, whether
the model kept its section (`copy_sections`), whether a "removed unread" note names it,
whether another entry of the template's class has it, whether its whole section is absent,
and whether the new code mentions the key. `.scratch/c3_noentry.py` says, for runs with no
new entry, how many entries and plans there are.

16 runs miss C3 (13 pass, 1 failed): 88 missing paths.
- **Whole section absent: 70 of 88.** Rarely a key inside a kept section.
- **The base entry had it: 48. Another entry of the class had it: 56.** Neither: 32 (g10 20,
  g14 9 of which 6 out of reach, g15 2 out of reach).
- **No entry at all, 26 paths (g09 ×2, g11 ×2):** the model returned no entry plan (0
  plans), though the template has data and a base entry was chosen. g11 is a new method in
  an existing class. The new test then reads no data, which the rules allow, so nothing
  stops it.
- **Sections not kept, about 13 (g12, g13):** entries exist, but the model kept none or few
  of the base's sections (g13: 2 entries, 2 paths in all).
- **Section kept, a key in it missing: g02, g03, part of g10.** The stripper's notes never
  name them (0), so either the model's `delete` changes took them or the notes aren't in
  `generated.notes`. Not settled.
- The new code mentions the missing key in 7 of 88.

Reading: C3 is mostly the model choosing to carry less data than the reference (no entry,
or sections dropped), with the blocks right there in the base or a sibling. Not retrieval.
Candidate change, one switch: when the template's class keeps data and the model returns no
entry for the new test, or drops a seed section every entry of the class has, code puts the
base's section back (the framework consumes seed sections, so they aren't "unread"). To check
first, free: which sections the 13 dropped ones are (seed or expectation), and whether the
`delete` changes explain g02/g03.

**The kinds (`.scratch/c3_kinds.py <report.json>`, no index, counts only), of the 88:**

| | whole section missing | a key inside a kept section |
|---|---|---|
| seed (`settings`, `policy`, `tenants`, ...) | 38 (g09, g10, g11, g12) | 7 (g02, g03, g12) |
| expectation (`targets`, `interactions`) | 14 (g09, g13) | 11 (g10, g14, g15) |
| other (keys the test body reads) | 18 (g09-g14) | 0 |

- The model's plan left the section out of `copy_sections` for 73 of 88.
- g02 and g03 are settled: the model's own `delete` changes removed those keys (5 of 5).
  The stripper removed nothing.
- So a seed-section floor reaches at most 38 paths, and passes a ticket only where nothing
  else is missing: likely g12 alone (g09 also lacks an expectation and custom keys, g11 a
  custom key, g10 has blocks no entry holds). C3 recall would rise more than its pass rate.
- An expectation section can't be put back by code unless the test calls its helper, and the
  custom keys only matter if the code reads them. Both are the model's choice of what the test
  does, the same as C2.

**Built, off by default: `generate.seed_floor`** (`generator.seed_floor`). After an entry is
built from the model's plan, code adds every seed section (`data.seed_sections`) the base entry
has and the new entry lacks, relabelled like a copied section, with a note. Seed sections are
applied by the framework, so the stripper never removes them.
`test_seed_floor_keeps_the_base_seed_sections_the_model_left_out`.
- A first version also gave an entry to a test the model left without one. That can't
  happen: the response check already refuses a test that reads data and has no entry. So
  g09 and g11's new tests read no data at all, and the floor doesn't reach them (26 paths).
  Removed.
- Reach: the seed sections dropped from existing entries, about 12 paths (g10, g12). Expected
  gain: C3 recall on g10 and g12; a pass likely on g12 only. Watch C4 (a copied section
  carries the base's values) and C7.
- To measure: `T2T_GENERATE__SEED_FLOOR=true`, label `seed-floor`, against baseline-2.

## A new plan (2026-11-12): fix the yardstick before more changes

Ten changes since baseline-1 (seven placement rules, the glossary, member cards, the step
plan) moved nothing beyond noise. Three things in how we measure and choose:
1. C2 and C3 ask for the one reference test exactly, and part of it is new to the suite
   (31 of 54 missed helpers are called by no other test of its class; 32 of 88 missed blocks
   are in no entry of the class). That part no generator can reach.
2. C6 (is the draft useful to a QE) has never been filled, so every choice was made on proxies.
3. The upper bound (plan step 5: a stronger generator) was never run, so we don't know whether
   the ceiling is the model or the pipeline.

Plan: **A** fix the yardstick (free): A1 score C2/C3 against what was reachable, A2 recall
means next to pass rates, A3 the parse failures. **B** two diagnostic runs: B1 Sonnet API
generates (everything else unchanged), B2 the reference class's nearest test given as the
template (D6 as an oracle; needs a switch). **C** the human judges 15 outputs (keep / small
edit / rewrite). **D** then decide: D6, D5 if B1 shows the model matters, D3/D4 (gaps and
warnings to the reviewer); D1 in full parked; member cards and the step plan removed unless
reused; no more placement rules.

**A2 (`.scratch/reachable.py <report.json> --means-only`):** the recall means are as flat as
the pass rates, so nothing moved under the 1.0 bar either.

| Report | C2 pass | C2 mean recall | C3 pass | C3 mean recall |
|---|---|---|---|---|
| baseline-1 | 6/30 | 0.45 | 10/30 | 0.66 |
| baseline-2 | 5/30 | 0.47 | 12/30 | 0.71 |
| member-cards | 6/30 | 0.49 | 13/30 | 0.70 |
| step-plan | 5/30 | 0.48 | 13/30 | 0.67 |

**A3:** all three parse failures (g06 ×2, g15 r2) are "syntax error near line 1" from the
tree-sitter check. Not modern syntax tree-sitter lacks (nested f-string quotes, `match`,
`type`, `except*` all parse). The model's raw reply isn't kept, so the cause (a fence, escaped
newlines, prose before the code) needs one `--debug-log` run of g06 and a masked look at the
code's first line. Open.

**B1 needs no yaml change:** `-e 'T2T_LLM__CLAUDE_CODE_CLI__STEP_MODELS={"generate":"claude-sonnet-5-5"}'`
moves only the generate step (and repair, which reuses its request) to Sonnet; every other
step stays on Haiku (`.scratch/models_per_step.py` prints the model per step).

Read: search is not the bottleneck for C3. Two thirds of their misses happen with the
helper or block already in the context. Next is step 4 below (what the generator does with
what it has), not more retrieval or placement rules.

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
