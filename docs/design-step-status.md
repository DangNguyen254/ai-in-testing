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

## Next steps, in order

1. **Run experiment 3c** (not run: the VM hung), about $0.10:
   `uv run ticket2test golden <private>/golden.json --pairs g08,g09,g13 --repeat 1 --label exp3c-template-class`
   - g08: if C1 says "decided right, output is module …", read its reasons (masked) for why the
     method patch wasn't possible (`method not possible: …`), and fix that.
   - g09: one of the two tickets where a new file is right; it must keep C1 with the switch on
     (g10 kept it in experiment 3).
2. If placement improves, **confirm on all 15 with `--repeat 2`** (every area with gated classes
   is affected). Compare with baseline-0.
3. g05: "template in another class": retrieval chose the wrong class; a retrieval problem, not
   placement. g10: right placement but C2 0.00 / C3 0.17 with C8 0.80/0.44: the context lacked the
   reference's helpers and data blocks (retrieval).
4. Later, from the baseline analysis: the validator hole for invented members; class choice by
   name match (D1/D6) if the switches don't cover it; dropped steps; g08's missing data template;
   g09's area choice.
5. If the word-overlap class match stays the weak spot: replace it with the retrieval ranking, or
   a bounded model choice among the area's classes (a new LLM step: ask the human first).

## Reading results without leaking names

Reasons and errors carry the private suite's names. When asking the human for them, give a
command that masks them (file paths, capitalised names, bracketed values, the `domain:` line),
and remind them to check before pasting. Never repeat a name that slips through.
