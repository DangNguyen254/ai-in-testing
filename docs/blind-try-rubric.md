# The blind try: how it is judged

The last test of a change (`CLAUDE.md`, method point 10): tickets that have **no test yet**,
run through the tool as a QE would use it. There is no reference test, so C1, C2, C3, C5 and
C8 don't exist here. What is left is the code checks and a person's verdict, fixed in advance
so the reading can't follow the result.

Private: tickets, outputs and the filled sheet stay in `t2t-private`. Counts only come back.

## The two arms

| Arm | Tickets | What it tests |
|---|---|---|
| **With neighbours** | 3 to 5 tickets for a feature that already has tests (a class or sibling classes to lean on) | the everyday case |
| **None at all** | 1 to 3 tickets for a feature with no test in the suite | the goal's hard case |

For the second arm, note per ticket which of these is true, because the right output differs:
- **the framework is there** (the feature's page objects and helpers exist, no test does):
  a complete test is possible;
- **the framework is partly or not there**: a complete test is not possible. The right output
  is a test for what exists, plus the missing members named (a marked gap, or a proposed
  member as a separate patch). A complete-looking test here means something was invented or
  quietly replaced by the closest thing.

Choose the tickets before the tool is run on any of them, and don't swap one out after seeing
its output. One run per ticket, with the settings that are the default that day (recorded in
the run's config).

## What code says (no judgement)

| Check | Pass means |
|---|---|
| Generated | the tool returned a test (not a failed generation, not `insufficient_info` on a clear ticket) |
| Validators | no error from the deterministic validators (names exist, chains resolve, ids match entries, style) |
| Collect | `pytest --collect-only` in the sandbox loads it |
| Made-up values | no value that nothing supports (the C4 warning) |
| Gaps reported | how many missing pieces the tool named, and how many proposals it wrote |

## What the person says (one row per ticket)

Columns A to E and G of `docs/verdict-sheet.md`, unchanged (verdict, the first thing wrong,
where it is, would it run, does it test the ticket, style), so the blind try can be compared
with the golden verdicts. Column F (against a reference) doesn't apply. Three more:

| Col | Question | Answer |
|---|---|---|
| H | **Placement.** Is it where you would have put it? | `yes`, `acceptable` (another reasonable home), `no` |
| I | **Honest about what is missing.** Where the suite has no member for a step or check, did the tool say so (a gap, a proposal, a checklist line), or use the closest thing without saying? | `said`, `silent`, `nothing was missing` |
| J | **The checklist.** Are the "needs a real run" items the ones you would want to confirm? | `yes`, `partly`, `no` |

And, where possible, for one output per arm that got `keep` or `edit`: **run it** on a
deployed build, and record `passed`, `failed for a test reason`, `failed for the bug`, or
`environment`. Nothing else proves a generated test works.

## What counts as passing

Written now, so it isn't chosen after the fact:

- **With neighbours:** every output generated, validators and collect pass; at least half
  `keep` or `edit`; no `silent` in column I; column G `yes` or `mostly` on all.
- **None at all:** every output generated, validators and collect pass; column G `yes` or
  `mostly` on all (the style holds with nothing to copy); no `silent` in column I; and where
  the framework is not there, the missing members are named. `keep` is not required in this
  arm: `edit` with honest gaps is the target.
- A change that was confirmed on the held-out set but fails here is not kept as it is; what
  failed is written in the status doc, by column, without names.

## What comes back to the repo

```text
arm with neighbours (n=_): generated _, validators _, collect _, made-up values _
  A keep/edit/rewrite _/_/_ ; E yes/partly/no _/_/_ ; G yes/mostly/no _/_/_
  H yes/acceptable/no _/_/_ ; I said/silent/nothing _/_/_ ; J yes/partly/no _/_/_
arm none at all (n=_; framework there _, partly or not _): the same lines
real runs: _ passed, _ failed (test), _ failed (the bug), _ environment
```
