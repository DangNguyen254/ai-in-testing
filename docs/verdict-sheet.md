# Verdict sheet: a person's reading of 15 generated tests

Phase A, step 3 of the plan in `docs/design-step-status.md`. Every number so far comes from
code comparing the output with one reference test, or from a model's judgement. This is the
one input only a QE can give: would the test be kept, and does "the same step by another
member" pass review. How it is judged is fixed here, before anything is read, so the reading
doesn't drift with what is found.

Private: the filled sheet stays in the run's folder in `t2t-private`. Only the counts at the
end come back to this repo.

## What to read

Run 1 of each of the 15 tickets of the `seed-floor` run (the yardstick: today's defaults, no
diagnostic switch). If run 1 failed to generate, run 2. For each: the new test method and its
new data entries (in the run's `runs/<pair>/r1/` folder), next to the ticket. Look at the
reference test only after writing the verdict, for column F.

About ten minutes a ticket. Don't fix anything; write what you see.

## The sheet (one row per ticket)

| Col | Question | Answer |
|---|---|---|
| A | **Verdict.** If this arrived as a draft from a colleague, what would you do with it? | `keep` (run it as it is, or after a one-line change), `edit` (right idea, under about 15 minutes of fixing), `rewrite` (faster to start again) |
| B | **The first thing wrong**, in one line of your own words. Empty for a clean `keep`. | free text |
| C | **Where that first thing is.** | `place` (wrong file or class), `steps` (a step missing, wrong or in the wrong order), `member` (a real member, but not the one the team uses for this), `check` (doesn't verify what the ticket asks, or verifies something else), `data` (a block missing, wrong or made up), `style` (naming, structure, how the team writes it), `none` |
| D | **Would it run?** From reading only: would it get through its steps on a working build? | `yes`, `no`, `can't tell` |
| E | **Does it test the ticket?** If the behaviour the ticket describes were broken, would this test fail? | `yes`, `no`, `partly` |
| F | **After looking at the reference:** where the tool does a step through a different member than the reference, would that pass review? | `fine` (either is acceptable), `prefer` (works, but the team would ask for the reference's member), `wrong` (not equivalent), `n/a` (same members) |
| G | **Style.** Leaving correctness aside, does it read like the team's tests? | `yes`, `mostly`, `no` |

Rules while reading:
- Answer A to E and G **before** opening the reference test. F is the only column that uses it.
- One verdict per ticket; when torn between two, take the worse.
- `can't tell` is a valid answer. Don't guess a `yes`.
- Note in B anything the checklist the tool attached already warned about: a warned problem
  is a smaller one than a silent one.

## What comes back to the repo

Counts only, no names and no sentences from column B:

```text
A  keep / edit / rewrite            : _ / _ / _
C  place/steps/member/check/data/style/none : _/_/_/_/_/_/_
D  yes / no / can't tell            : _ / _ / _
E  yes / partly / no                : _ / _ / _
F  fine / prefer / wrong / n/a      : _ / _ / _ / _
G  yes / mostly / no                : _ / _ / _
per ticket: g01 A=_ C=_ E=_ F=_ ; g02 ... (ids and the letters only)
```

## How it will be read

Written before the result, like the predictions in the status doc:

- **A against C2 and C3.** If most `keep` and `edit` tickets fail C2, the criterion is
  stricter than what a QE needs and gets loosened (a call counts when it resolves to an
  accepted alternative) before anything is tuned against it.
- **F.** Mostly `fine`: C2 overstates the helper gap, as Haiku's audit suggested (7 of 11).
  Mostly `prefer`: the team has a preferred member per step, and the tool needs to know which
  (how often each member is used for that step across the suite). Mostly `wrong`: C2 is right
  as it is.
- **E.** The share of `no` and `partly` is the real size of the "does less" problem (no
  backend check, a check on something else), which the code criteria only see through missing
  data blocks.
- **C.** The most frequent place of the first problem is what a design change should aim at.
  It is read together with the two diagnostic runs, not instead of them.
- **G** is the goal's own question. It is asked again on the cold runs' outputs and in the
  blind try, so the three can be compared.
