# Real-suite trial: problems met, what was tried, what is still open

*Written 2026-11-02, at the end of the first trial on the real suite (2026-10-27 to 2026-11-02).
Work is paused here for a step back: research and design before more fixes.*

This file names nothing from the real suite. "The area" is the one feature area the trial
tickets belonged to; "the person's class" is the newer test class a team member wrote there;
"the older class" is an earlier class for the same feature.

## How the trial ran

- A handful of real tickets from one area, pasted by hand, run through `run` (draft, then
  `--continue`) inside the container, on the small model through the Claude Code CLI.
- After each run the generation log was read (with names removed), a problem was picked, a fix
  was built, tested on the stand-in, copied into the container, and the ticket was run again.
- Around 50 commits on the `trial-fixes` branch came out of this.

## Why it is paused

The loop above drifted:

- **Each fix answered the last run.** Every run surfaced a new problem, or an old one came back
  in another form. A fix that looked right for one run changed the next run in ways nobody
  measured.
- **No fixed yardstick.** There is no set of real tickets with a reference test and agreed
  criteria, run several times each. Single runs were compared by eye. The model provider has no
  temperature setting, so two runs of the same ticket already differ; one better run proves
  little.
- **More model calls, not more control.** Several fixes added LLM steps or calls (a coverage
  check, area guides, a framework guide, repair rounds started by warnings, proposals and
  regeneration). Each adds cost and variation, and none was shown to help.
- **Knowledge spent without a measured effect.** About $11 of guide generation, plus guides
  rewritten by Claude Code sessions, with no visible improvement in the generated tests.

So the status below is deliberately cautious: **nothing here is marked solved**. "Tried"
means a change was built and passes the project's own tests; whether it helps on real tickets
is unknown unless a run is cited, and one run is weak evidence.

## Problems met

Status words: **open** (nothing done), **tried** (built, not verified on real tickets),
**seen once** (one real run looked better afterwards), **mixed** (helped one thing, hurt
another), **worked around** (a process rule, not a fix).

### Where the test goes (area, class, reuse)

| # | Problem | What was tried | Status |
|---|---|---|---|
| 1 | The method went into the older class, though search ranked the person's class first. | The closest template test's class takes the method when the ticket names its folder (glossary or component); the closest template is looked for inside the area; search's top hit counts. | seen once; later runs still varied with the ticket's wording |
| 2 | "Already covered" never fires on real tickets: the word-match bar is far above what ticket wording reaches. | Optional pre-generation coverage check: one model call compares the draft with the closest tests' code and data (off by default). | tried; one run gave "partial" with plausible reasons |
| 3 | A new module built from an existing class lost that class's own helpers. | The scaffold copies the helpers setup and the new tests call. | tried |
| 4 | A test gated to one deployment could be chosen for a draft that runs on both. | Gated classes excluded unless they hold the closest template, with a note. | tried |

### The draft

| # | Problem | What was tried | Status |
|---|---|---|---|
| 5 | Priority wrong (every security feature drafted as top priority). | Priority guide from config; option to take priority from neighbouring tests. | tried |
| 6 | Component not from the suite's set. | Choices from glossary markers, else from the suite map's areas. | tried |
| 7 | Variants the ticket never asks for (one case split into two). | Prompt rule (draft v6) and a flag in the draft's support table. | tried; no run checked with v6 yet |
| 8 | A value misspelled in the ticket is copied into the data. | A warning when a value differs from a known suite value only in spelling; known values no longer cut off by the map's key cap. | seen once (the warning appeared) |
| 9 | How to answer a partial draft's open questions is unclear. | Explained: answer in the ticket file and draft again. | open (no revise command) |

### The data entry

| # | Problem | What was tried | Status |
|---|---|---|---|
| 10 | Sections every entry of the file carries were missing. | Copied by code (convention sections). | tried |
| 11 | A key a helper reads through a parameter's default was removed as unread, so the test would fail on the missing key. | The data-use analysis follows parameter defaults and passed key names. | seen once |
| 12 | Data no code reads (a payload made up for a check the test doesn't make). | Keys inside sections followed into helpers, unread ones removed and flagged; a warning for values nothing supports (not in the ticket, the template or the area's data). | tried; the real values (page payloads) can only come from a person |
| 13 | A whole policy block the scenario needs was missing: the template's entry didn't have it. | The base entry is the class entry whose values the draft names most; a "copy" change takes a block from another entry. | seen once (block present in the next run) |
| 14 | An expected backend result built in code instead of the entry's expectation section. | A warning. | tried |
| 15 | Two variants whose entries barely differ. | None. | open |

### The test code

| # | Problem | What was tried | Status |
|---|---|---|---|
| 16 | Members of the main base class reported missing (only the first base class was searched). | All base classes searched. | seen once |
| 17 | The class's helpers were re-implemented inline, and checks a helper already makes were repeated. | Helper code put into the context (the class's own helpers and one level into base-class methods). | **mixed**: the next run copied the helpers' internals instead of calling them |
| 18 | A helper hands work to a framework object whose method already asserts and returns the events; the model doesn't see that and checks again. | None yet (proposed: follow calls on such objects into the context). | open |
| 19 | Outcomes not checked because no helper exists for them (a banner, page content delivered); workarounds instead. | The model lists what's missing (generate v5); gap check; owner of a noted member mapped to a real class; proposals on. | tried; proposals were produced but not reviewed or applied |
| 20 | The test description written as a string expression instead of a docstring. | None. | open |
| 21 | Code that drifts from the suite's way when a repair round asks for more checks. | Repair rounds started by some warnings (one at most), undone if they bring errors back. | **mixed**: a warning-started round led to the inlining in 17 |

### The checks the tool runs

| # | Problem | What was tried | Status |
|---|---|---|---|
| 22 | The claims check was too lenient (any value of a data item handed to a helper counted as checked) and too strict elsewhere. | Evidence limited to the keys the helper reads. | tried; its warnings still drive repair rounds of unknown value |
| 23 | A wrong checklist note on tests added to an existing class. | Removed for that case. | tried |
| 24 | Warnings are found by heuristics; a false one now costs a repair round. | None. | open |

### Knowledge given to the model

| # | Problem | What was tried | Status |
|---|---|---|---|
| 25 | Ticket words don't match the suite's. | Known values (code), glossary (written by Claude Code sessions), used in search, area choice, the draft and the generation context. | tried; retrieval eval showed no gain (same hit rate) |
| 26 | The model doesn't know what helpers do or which data blocks depend on each other. | Area guides by a stronger model in one call per area; a framework guide; prompt revisions; guides rewritten by Claude Code sessions with tools. | **no visible effect**; checks by Claude Code found the one-call guides incomplete and partly wrong |
| 27 | The context budget is mostly taken by pieces that are always included (large base entries, guides); optional pieces (similar tests, helper code) may be dropped. | Budget raised from 12k to 16k tokens. | open (not measured; no report of what was dropped) |

### Running the tool

| # | Problem | What was tried | Status |
|---|---|---|---|
| 28 | Copying a new version into the container during a run broke the run. | Copy only when nothing runs (a rule); the copy replaces the folder in place. | worked around |
| 29 | After a folder swap, the tool ran from the old copy without anyone noticing. | Swap removed; in-place copy. | worked around |
| 30 | Out of memory on the full index. | Index memory reduced (earlier in the trial). | seen in later runs |
| 31 | Private names repeated in conversation and close to committed text. | Rule: never repeat names or values from the real suite. | worked around |

## Still open, beyond the table

- **No measurement on real tickets.** Nothing above was compared across a fixed set of tickets
  with several runs each.
- **Nondeterminism.** The provider used has no temperature; run-to-run differences are mixed up
  with the effect of changes.
- **Values only a person knows** (page payloads, exact banner text, which user): the tool can
  flag them, not supply them.
- **Proposals** (missing helpers written by the model) were produced but never reviewed or run.
- **Hidden-test runs** (`--hide`, the person's class and the older class removed) were prepared,
  not yet run.
- **The suite's own tests as a baseline** (`check-suite`) were not rerun with the new warnings.

## Questions for the design phase

1. **What should the tool hand over?** A finished test, or a skeleton plus data entry with the
   parts that need knowledge (helper choice, checks) left as marked gaps for the person?
2. **What is the input?** The ticket, the QE's own test case text, or "like test X, but …"?
3. **How is quality judged?** Which criteria (right class, helpers called not copied, data
   complete, checks match the outcome, style), on which fixed set of real tickets with reference
   tests (hidden with `--hide`), with how many runs per ticket?
4. **Which knowledge does generation need, and where does it come from?** Facts code can
   extract (what a helper asserts, which blocks an entry needs), summaries a model writes, or
   notes a person writes once?
5. **Where are agents with tools worth it?** The guides showed that a model which can open files
   beats a stronger model shown a fixed excerpt. The pipeline allows four bounded agents with the
   project's own read-only tools; is a different split justified, and at what cost?
6. **What should be deterministic?** Data entries are already built by code from a plan; could
   helper choice and checks be planned the same way (the model picks, code writes)?
7. **Which of the trial changes to keep, change or remove** once the design is settled.
