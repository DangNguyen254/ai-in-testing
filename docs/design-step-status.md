# Design step: status

## Start here (2026-11-16)

How the work is done is in `CLAUDE.md` ("How the work is done now", with the goal and method
points 8 to 10 added today). This file is the record: the newest state is in this block, and
the history below it is in the order it happened (today's entries are under "A new plan",
after the right-template result).

- **The goal (the human, 2026-11-16):** tests in the suite's, the team's and the codebase's
  style, also with no similar test or area to copy from. Today's generator adapts a template,
  so the no-template case is the measure that matters.
- **Yardsticks (15 x 2, Haiku API, today's defaults):**

  | Run | What is hidden | C2 mean recall | C3 mean recall | Validators, of generated |
  |---|---|---|---|---|
  | `seed-floor` (warm) | the reference | 0.47 | 0.77 | 30/30 |
  | `right-template` (diagnostic) | the reference; right template given | 0.56 | 0.75 | 27/27 |
  | `cold-class` | and the class's other tests | 0.38 | 0.65 | 26/26 |
  | `cold-area` | and every test file of the folder | 0.00 (see 2026-11-17: about half of the reference's calls can't be reached there) | 0.50 | 27/30 |
  | `right-steps` (diagnostic) | the reference; right template and the reference's calls given | 0.85 | 0.83 | 28/28 |

- **Where the loss is, from today's free checks and Haiku's audit:**
  - Placement is a template problem: the right template lifts C1 from 60% to 83%. The class is
    clear from the ticket and draft on 5 of 15. D6 (the QE names the nearest test) fits, for
    tickets that have a neighbour.
  - The tickets are not the limit on helpers and data: about one item in ten of a reference
    test comes from outside the ticket and the suite; the drafts keep what the ticket states.
  - With the right template, half of what is still missed was in the output's own class, a
    quarter elsewhere in the suite, a fifth nowhere else.
  - On ticket-stated steps the tool never skips: 7 of 11 "missed" helpers are another route
    Haiku judges equivalent (C2 overstates there), 4 are weaker. Whether another route passes
    review is the team's call.
  - The data side is a real loss, and mostly follows from the test doing less (no backend
    check, no data read); under the right template it is concentrated in g10 (no template),
    g13 and g11.
  - Without the class's tests the output is still valid; the tool attaches to a sibling class.
- **Done:** `cold-area`: every output went to another folder and helper recall is 0.00 on all
  30 runs (the tool adapts another area's test). `right-steps`: with the reference's calls
  given, helper recall goes from 0.56 to 0.85, so the writer is not the limit; the choice of
  members is. Both were read against predictions written before the runs.
- **Agent upper bound, with neighbours (2026-11-17):** helper recall 0.69 on six tickets, the
  tool 0.42 with the right template; better on four of six, as predicted. Data 0.77 against
  0.73: lookups find the calls, not the data.
- **Agent upper bound, no template (2026-11-17):** the agent makes 6 of the 12 reachable
  reference calls on six tickets, the tool 1 of 24; three of six tickets above 0 (predicted
  four). The first scoring (0.08) could not see a new class's calls; corrected below.
- **Phase B decided (2026-11-17):** build the planning step (the model chooses members by
  lookup, code checks, the writer writes from the plan), first slice behind
  `generate.planner.enabled`, branch `planner`. Its prediction is written below, before any
  code. The verdict on 15 outputs waits for the build. `generate.step_plan` and
  `generate.context_member_cards` are **removed** (measured, moved nothing).
- **Then (Phase A, nothing here tunes the tool):** the human's verdict on 15 outputs
  (`docs/verdict-sheet.md`); the agent upper bound on about five tickets
  (`docs/agent-upper-bound-prompt.md`). **Phase B:** one design direction, with its predicted
  effect written first. **Phase C:** build it behind a switch, golden warm and cold, the
  held-out set once, then the blind try (`docs/blind-try-rubric.md`).
- **Not to do:** more placement rules; rules fitted to single tickets (the class-habit floor
  was dropped for that); more context hints (guides, glossary, member cards, step plan and a
  stronger model all moved nothing).
- **Open:** runs that fail to generate (the code doesn't parse; 2 to 4 of 30 a run; needs one
  `--debug-log` run and a masked look); g01 overflows the context budget under a pinned
  template; the always-on context pieces were never ablated (plan step 3); C8 tests names
  only; `glossary_class_wins` waits for a person's look at g12's glossary entry.
- **On:** `knowledge.use_in_templates`, the joined-marker fix, the updated and reviewed
  glossary, `generate.seed_floor` (found and judged on the golden set: its real test is the
  held-out set). **Off:** `knowledge.search_named_classes`,
  `generate.reuse.glossary_class_wins`,
  `eval.oracle_template`, `eval.oracle_steps` (diagnostics, never on by default).
  **Removed:** `kind_as_preference`, `class_from_retrieval`, `dataless_hit_class`.
- The container's memory limit is 8 GiB since today; one golden run uses up to 4.9 GiB, so
  runs go one at a time. Pushed on 2026-11-13; today's commits are local until the next OK.

## Phase B (2026-11-17): the decision, and the prediction for the first build

**Decision (the human, 2026-11-17).** Build the planning step: the model chooses the members
by looking them up, code checks the plan, the writer writes from it. The person's verdict on
the 15 yardstick outputs is put off until this is built and measured (it goes to the human's
mentor, and outputs of the new build are the better thing to send). The three team questions
are being answered by the human now, provisionally. The agent rule in `CLAUDE.md` has a fifth
agent, Planning. `design-step` is merged into `main`; the work is on the branch `planner`.

**Why this, from the measurements only** (section 6 of `docs/design-direction.md`):
assumption 1 holds (`right-steps`: given the calls, helper recall 0.85) and assumption 2
holds as far as six tickets can say (the agent upper bound: 0.69 against the tool's 0.42,
four of six). Assumption 5 is mostly false (data can't be derived from calls), and the agent
runs agree (data 0.77 against 0.73).

**The first build is the smallest slice that puts assumption 2 inside the tool:**
- `generate.planner.enabled` (off by default). After the template and the draft are known,
  the model gets the draft as numbered lines and the investigation's read-only tools, within
  a turn budget, and returns rows: `call` or `check` (a member), or `gap` (what is missing).
- Code checks each row: the member exists (catalog), or it is marked `unknown` when the
  catalog can't type the chain (a third of the references' calls are like that, and the
  agent's whole lead was there), never rejected for that alone. Rows that fail go back, for a
  capped number of rounds on one shared budget.
- The plan reaches the writer the way `eval.oracle_steps` gives it the reference's calls (the
  path `right-steps` measured: 0.85 with nothing enforcing it). So this slice enforces
  nothing either: planned calls the test doesn't make are counted in the run's record and
  put on the reviewer's checklist. Enforcement through repair is added only if that count
  shows the writer dropping them.
- Counters in every run and in the golden report: turns and rounds used, how it stopped,
  near cap.
- **Not in this slice:** `seed` rows and anything else about data; a scaffold without a
  template; placement. The template path stays as it is underneath. Each is a later slice
  with its own prediction.

**Prediction, written before any code (15 x 2, Haiku API, against `seed-floor`):**

| Measure | Yardstick | Predicted with the planner on |
|---|---|---|
| C2 mean recall, warm | 0.47 | 0.58 or more |
| C2, the six agent tickets (g04 g05 g06 g10 g13 g15) | 0.40 | 0.55 or more (the agent: 0.69, with the place given) |
| C3 mean recall, warm | 0.77 | within 0.03: this slice does nothing for data |
| C1 | 60% | unchanged: placement is not touched |
| Validators, of generated | 30/30 | no worse than 28 |
| C2, `cold-class` | 0.38 | 0.45 or more |
| Runs that hit or nearly hit a cap | | under a third; over that, the tools or the plan format are wrong, not the cap |
| Model calls a run | about 4 | about 8 to 12 |

By the keep rule, per ticket: kept when the tickets with a helper miss improve in both runs
and none gets worse in both. If C2 stays within 0.05 of the yardstick while the plans
themselves hold the reference's calls (scored like the agent's outputs), the loss is in
handing the plan to the writer, not in planning. If the plans don't hold them, the tool's
lookups are weaker than a coding agent's, and the tools are what to fix. `cold-area` is not
part of this prediction: half of the reference's calls can't be reached there, and this slice
keeps the template.

**Built (2026-11-17, branch `planner`, off by default).** `generate/planner.py`,
`models/plan.py`, `prompts/planner_v1.md`, `generate.planner` in the config (8 turns over all
rounds, 2 rounds, a later round gets 2 turns, 4 lookups a turn; the tools and their output
caps are the investigator's). It runs after placement is decided, for a new method or a new
module, in the class the test goes into or is built like. A run's record has `plan` (how it
stopped, turns, rounds, rows by kind, unknown rows, lookups: counts only), `plan_near_cap`
and `plan_unmade`; the golden log prints the first; the plan itself is kept as `plan.json`
next to the generated test. A planner that fails is a note and the test is written as
without it. Tests: `tests/test_planner.py` (fake model, stand-in).

**First paid check (2026-11-17, `planner-check`, g06 and g13, one run each): the planner
runs inside its caps' mechanics, and plans badly.** Not a result on the prediction (two runs);
a check that the thing works before 30 runs are spent.

| | g06 | g13 |
|---|---|---|
| Stopped | turn budget, 8 of 8 turns, round 2 used | done, 5 of 8 turns, round 1 |
| Lookups | 23 | 13 |
| Rows | 3 seed, 6 gap, no call | 2 call, 2 seed, 3 gap |
| Members named and refused by the check | 4 (helpers of the class, one level) | 0 |
| ...that exist on the reference's class | 0 of 4: they were invented | |
| The reference's calls found | 0 of 4 | 2 of 6 |
| Planned in the reference's class | no (C1 failed) | yes |
| C2 (yardstick) | 0.25 (0.25) | 0.67 (0.75) |
| Planned, not in the test | 0 | 0 |

(`.scratch/plan_facts.py`, `.scratch/plan_class.py`: counts only.) The same model as a coding
agent, with the place given, found 4 of 4 and 4 of 6 on these two tickets.

What holds: the check refused every invented member and turned it into a gap, nothing was
guessed into the test, and the writer made every call it was given. What doesn't: the plans.
Three differences from the agent's sessions, none measured yet, so none is fixed yet:
1. **What it can keep in view.** The planner's tool outputs are cut at 3,000 characters each
   and the whole transcript at 24,000 (the investigator's caps, made for a cheap retrieval
   step); older outputs are dropped. With 23 lookups most of what it read was gone by the
   time it wrote rows. The agent read 6 to 17 files whole. A dropped-output counter is the
   free way to see this.
2. **The place.** g06 was planned in the wrong class (placement is wrong on 40% of the
   yardstick); the agent was given the right one. `eval.oracle_template` gives the planner
   the same condition.
3. **The prompt leans to gaps** ("a gap is a correct answer"): 5 of 16 rows are gaps the
   model chose itself.

Next, in this order: count dropped outputs (code, free); rerun the same two tickets with
the right template pinned, so the planner is read apart from placement and like the agent
(about a tenth of a run). The 15 x 2 run waits until the plans on these two are near the
agent's.

**The same two tickets with the right template pinned (2026-11-17, `planner-check-pinned`):
the place and the memory are not the cause.**

| | g06 | g13 |
|---|---|---|
| Planned in the reference's class | yes | yes |
| Stopped | turn budget, 8 of 8, round 2 used | done, 8 of 8 turns |
| Lookups; outputs cut; outputs dropped from view | 27; 1; 2 | 26; 5; 3 |
| Rows | 1 call, 1 check (unknown), 3 seed, 4 gap | 4 call, 2 seed, 2 gap |
| The reference's calls found | 0 of 4 | 2 of 6 |
| C2 (`right-template`'s mean for the ticket) | 0.00 (0.25) | 0.67 (0.75) |

- Guess "it forgets what it read": **no.** 2 and 3 outputs of 26 dropped.
- Guess "the wrong class": **no.** With the right class g06 still finds none.
- **The plan made g06 worse** (0.25 to 0.00): the writer followed it, gaps included, and
  left out what the template alone would have given. A thin plan is not neutral.
- What is left is what the planner can see. Its tools read the index: members by class,
  chains, outlines. Three of g06's four reference calls are ones the catalog can't resolve,
  which is exactly where the agent's lead was (above). They are visible in the code of the
  class's tests and helpers, read as text, and not in a member list. The agent read 6 files
  whole and found 4 of 4 with 11 lookups; the planner made 27 index lookups and found none.

So the index-tool planner is not the agent that was measured. The measured thing read files.
Next design decision (not built): the planner's lookups become reads of the repo copy as
text (a file or a range of it, a text search, a folder listing; read-only, capped, inside the
copy only, which the agent rules allow), with a view large enough to keep them, and a plan
that adds to the template's calls instead of replacing them when it has gaps.

**Planner, second version: it reads files (decided 2026-11-17, the human: "do it"). Written
before the code.**

What changes, and only this: the lookups. The loop, the plan's rows, the code check, the
counters and the switch stay.
- Three tools over the repo copy as text, replacing the index tools for the planner: `read`
  (a file or a line range), `grep` (a pattern across the copy), `list` (a folder). Read-only,
  no path outside the copy, nothing executed, outputs scrubbed and capped.
- Its own view: about 16,000 characters an output and 120,000 for the history (the
  investigator's 3,000 and 24,000 were made for a cheap retrieval step).
- It starts from the file of the class the test goes into and is told to read it first.
- A member the catalog can't type is kept as `unknown` only when a tool output showed its
  name; one that no output showed is sent back (`unseen`). So `unknown` is backed by what
  was read, which is the design's "cited evidence is in the tool log".
- The plan adds to the template: a gap row no longer tells the writer to leave the step out.

**Prediction (g06 and g13, one run each, right template pinned, as in the two checks above):**

| | g06 | g13 |
|---|---|---|
| The reference's calls in the plan (first version; the agent) | 3 of 4 or more (0; 4) | 4 of 6 or more (2; 4) |
| C2 of the written test (first version; without the planner) | 0.75 or more (0.00; 0.25) | 0.67 or more (0.67; 0.75) |
| Stops on a cap | at most one of the two | |

If the plans reach those numbers, the 15 x 2 run of the Phase B prediction follows. If they
don't, with the files readable and in view, a planner made of this project's own tools does
not reproduce the coding agent, and the next question is whether the step should call a real
coding agent (read-only, in the copy) instead. Cost: more than the first version, since whole
files are re-sent every turn; measured on these two runs before any larger one.

**The second version measured (2026-11-17, `planner-v2-pinned`): the prediction failed.**

| | g06 | g13 | Predicted |
|---|---|---|---|
| The reference's calls in the plan | 0 of 4 | 1 of 6 | 3 of 4, 4 of 6 |
| C2 of the written test | 0.00 | 0.67 | 0.75, 0.67 |
| Turns; lookups | 1 of 8; **0** | 4 of 8; 7 | |
| Rows | 3 seed, 6 gap | 2 call, 2 seed, 3 gap | |
| Stopped | no actions asked | done, round 2 used | |

With files readable and room to keep them, the model hardly looked: on g06 it asked for no
lookup at all and returned six gaps on its first turn; on g13 seven lookups in four turns.
The same model in a coding-agent session made 11 to 15 lookups on these tickets and found 4
of 4 and 4 of 6. So what differs is not the tools or the view (both versions had enough of
each to do better than nothing) but the loop: here the model is asked, once a turn, for a
JSON object with an `actions` list, through a one-shot call; there it works in the agent loop
it was trained for. Two versions, two failures, on the same two tickets: by the rule written
before this run, a planner made of this project's own tools does not reproduce the coding
agent. Changing the prompt again to make it look more would be the third change fitted to
these two tickets (method point 8).

What stands: the code check, the counters and the hand-over to the writer all work, and they
don't depend on who makes the plan. **Open for the human:** let the planning step call a real
coding agent (the Claude Code CLI the tool already uses as its model, with only its read,
search and list tools, confined to the copy, a turn cap, and the same plan JSON checked by
the same code). That changes the agent rule ("its tools are the project's own functions")
and works only with the CLI provider, so it is the human's decision.

**Decided by the human (2026-11-17): the planning step does not call a real coding agent.**
The reason: the project would then be no more than a validator a coding agent could call as
a skill. The tool's own steps must do the work. The planner stays in the code, off by
default, with both failed checks recorded above; what comes next is a rethink of the whole
design, stage by stage, before anything else is built.

**A free check for the rethink (2026-11-17, `.scratch/usage_ceiling.py`, no model): where
else the reference tests' calls can be found by syntax alone.** The idea being weighed: code
extracts, at index time, what each test calls in order (as written, no type resolution) and
what the framework defines, so the choice of members is made from counted usage instead of
by a model looking things up. Each of the 56 `self` calls of the 15 references, put in the
first place that has it:

| Where the same call is found | Calls | Share | Running total |
|---|---|---|---|
| Another test of the reference's class makes it, as written | 33 | 59% | 59% |
| A test of another class in the same folder | 10 | 18% | 77% |
| A test elsewhere in the suite | 1 | 2% | 79% |
| No test, but a function or method of that name is defined outside the tests (the framework) | 9 | 16% | 95% |
| Only a method of the reference's own class has the name | 3 | 5% | |
| Nowhere | 0 | | |

- A usage table of the class alone holds 59% of what the references call; with the folder
  77%. The tool's helper recall is 0.47, and it has those tests in reach: g04 and g13 have
  every reference call in their class's other tests (179 and 84 tests) and score 0.20 to 0.75.
  The knowledge is there; it isn't presented as "this step is done by this member".
- The framework's own definitions add 16 points that no test shows (the human's point: the
  table must cover the framework folder, not only the tests). That row matches by name only,
  among 24,542 names, so 95% is an upper bound; the first three rows are exact matches.
- Per ticket the class row is all or nothing: 8 tickets have most of their calls in the
  class, 6 have none there (their class has 0 to 2 other tests, or the call is the
  framework's). For those the folder and the framework are the only source.

**Usage table, steps 1 and 2 (2026-11-17).** Plan agreed with the human: (1) a usage table
in the index, by syntax, no model; (2) a free check of it on the golden set; (3) the picking
alone, one model call per ticket, scored against the reference's calls, prediction first;
(4) the picks to the writer and the 15 x 2 run; (5) cold sets, held-out, blind try.

Step 1 built: `index/usage.py` (each test's `self` calls in order as written; a class's or a
folder's calls counted, with usual position, an example and, when the catalog can type it,
the defining class; every function and method outside the test files, area helper modules
included). Built on demand from the index, 15 s on the real suite (6,534 tests, 34,724
definitions). Not used by the pipeline yet. Tests: `tests/test_usage.py`.

Step 2 (`.scratch/usage_table_check.py`, the reference and the pair's hidden tests left out):

| | Reference calls (of 56) |
|---|---|
| In the class's table | 41 (73%) |
| In the class's or the folder's | 48 (86%) |
| In the first 10 / 20 / 40 rows (class first, then folder) | 39 (70%) / 43 (77%) / 45 (80%) |

- 40 rows take 5,500 to 9,900 characters (about 2,000 to 3,300 tokens): it fits a prompt.
- **Correction:** the free check before this one said 59% for the class. It parsed some test
  chunks with a parser that fails on them and counted those tests as calling nothing; the
  table's parser handles them. 73% is the right figure.
- Out of reach of the rows: g07 and g12 (one call each, in neither class nor folder) and the
  two tickets whose class has no other test (g09, g10: 2 of 2 and 2 of 5 from the folder).

Next is step 3, the first paid step; its prediction is written before it runs.

**Usage table, step 3: the prediction, written before the run (2026-11-17).** One Haiku API
call per ticket (`generate/pick.py`, `prompts/pick_v1.md`): the draft's lines and the first
40 rows of the table (the class's calls, then its folder's), the reference and hidden tests
left out; the model picks rows per line by label. The class is the reference's (placement
given), so the fair comparison is `right-template` (placement given there too: C2 0.56), not
the yardstick's 0.47. Scored by `.scratch/pick_eval.py`, 15 x 2, no test written.

| Measure | Predicted |
|---|---|
| Picks' recall of the reference's calls, resolved like C2, mean | 0.65 or more (ceiling about 0.80) |
| Tickets where the picks beat `right-template`'s C2 (mean of two runs each) | 8 of 15 or more |
| Tickets where they are worse in both runs | 3 or fewer |

Reading: at 0.65 or more, picking from a counted table works where looking things up didn't,
and step 4 (the picks to the writer, 15 x 2) follows. Under 0.56, one call doesn't pick well
from a table either, and the choice goes to the QE (ticking rows, or naming the nearest
test). In between: read which lines were missed before deciding. Cost: 30 short calls.

**Usage table, step 3 measured (2026-11-17, `.scratch/pick_eval.py`, 15 x 2, Haiku API,
30 calls, 0.04 USD): the prediction failed on all three lines.**

| Measure | Predicted | Measured |
|---|---|---|
| Picks' recall of the reference's calls, mean | 0.65 or more | **0.42** (ceiling of the rows shown 0.75; `right-template` 0.57 on the same tickets) |
| Tickets better than `right-template` | 8 or more | **4** (g02, g04, g06, g15) |
| Tickets worse in both runs | 3 or fewer | **6** (g05, g07, g08, g11, g12, g13) |

The rest tie (g03, g14, and g09, g10 at 0 for both); g01 has no `right-template` score.
- The picks hold about half of what the rows hold (0.42 of 0.75). The rows are there; one
  call doesn't pick the right ones from them, as one call didn't from the member cards.
- Where the rows don't hold the call (g07, g12: ceiling 0), the tool scores 1.00 and the
  picks 0: the template had what the table doesn't.
- By the rule written before the run (under 0.56), one model call does not pick members
  well from a counted table either. Three ways of having the model choose members (the step
  plan from cards, the planner with lookups in two versions, picking from the table) have
  now each failed against simply adapting the right template.
- What stands: the usage table itself (it holds 75 to 80% of the right calls, and it is
  free), and the finding that the knowledge is in the suite. What fails is the choice by a
  model in one or a few calls. Per the rule, the choice goes to the QE next (ticking rows of
  the table, or naming the nearest test), unless the design review shows a reason the table
  or the picking is measured wrong. No prompt change is tried on these tickets (method
  point 8). The picking code stays, unused.

**Our validators on the real suite (2026-11-17, `check-suite` with the private config;
`.scratch/suite_counts.py`, counts only).** 171 test files, 17,775 tests: 60 files clean,
1,459 errors (assertions 424 in 55 files, data keys 533 in 40, ids 337 in 27, names 82 in 21,
data shape 49 in 20, page objects 24 in 8, base class 10 in 7); style deviates in 168 files.
This is where the calibration of 2026-10-27/28 ended, not a step back: it took the errors
from 69,977 to 1,409 and the clean files from 0 to 58, and stopped there. Two thirds of the
team's own files still fail at least one check the generated tests are repaired to pass.

**The fresh design (2026-11-17, `docs/fresh-design-prompt.md`, a session that read only the
real suite).** Its stages: index (code); read the ticket into a fixed schema, every field
quoted from the ticket (small model, checked by code); a sufficiency gate by code on required
slots; route the ticket to a test family by code, unsupported families stop (v1 covers about
58% of methods); anchors, the nearest siblings by structure, with a fallback for features
with no test (code); a plan, a small model choosing from a menu of existing page-object
members and copying quoted values; render the Python and JSON by code from the siblings'
templates; static gates (every chain resolves, ids, keys, markers, every literal traced to
the ticket, a neighbour or a registry); a review packet. Compared with ours:
- The same skeleton: index, draft, gate, anchors (our templates), validators, review. Its
  plan step is our step 3, a small model picking from a menu, which measured 0.42.
- Different: sufficiency decided by code on slots, not by the model; a test-family router
  that declines what it doesn't cover; the code rendered by code from siblings, the model
  only filling slots; literals traced as a gate (our C4 is a warning).
- Its own least-sure part is the expected-response data of a new feature, with a free
  experiment: hide about 50 entries that have 3 or more siblings, rebuild each from its
  nearest sibling changing only what the test's own steps set, and count exact reproductions
  (70% or more: code-only; under 40%: ask the ticket author for a sample response).

**The measure corrected (2026-11-17): equivalent routes judged, writes counted, and the
step-level truth.** Three things read together.

1. **Property writes barely matter to the score** (`c2w_recall`, re-scored on the kept runs):
   yardstick 0.47 -> 0.46, `right-template` 0.56 -> 0.54, `right-steps` 0.85 -> 0.80. The step
   truth agrees: 8 of 334 rows for draft lines are writes. The review's "C2 is blind to writes"
   is true and small here.
2. **Equivalent routes do matter** (`docs/equivalence-prompt.md`, 245 judged items, 164 by
   reading a body; `.scratch/equivalence_rescore.py`):

   | | Missed: equivalent / weaker / absent / unsure | Extra: needed / harmless / wrong | C2 -> with equivalents |
   |---|---|---|---|
   | yardstick (`seed-floor`) | 10 / 10 / 14 / 3 | 43 / 3 / 5 | **0.47 -> 0.62** (6 -> 9 runs at 1.0) |
   | `right-template` | 9 / 9 / 13 / 1 | 31 / 4 / 1 | **0.56 -> 0.67** |
   | picking (step 3) | 1 / 9 / 21 / 1 | 23 / 7 / 27 | about 0.42 -> 0.43 |

   About a quarter of the tool's "misses" are another acceptable route; most of its extra calls
   are needed. The picking's misses are real (1 equivalent of 32) and it adds 27 wrong calls:
   step 3's failure stands, and is worse than it looked.
3. **What a reference test is made of, line by line** (`docs/step-truth-prompt.md`, 119 draft
   lines of the 15 tickets, rows per line): call 77, write 8, setup 45, data 59, check 41,
   inside a helper 72, **none 32**. And **144 rows the reference does that no draft line asks
   for: 103 routine for the class, 41 specific.**
   - 32 of 119 draft lines (27%) are not done by the reference at all.
   - Most of a line's work is in setup, the data entry or inside a helper, not in a call in
     the test body (126 body rows of 334).
   - The reference's unasked rows outnumber the rows for draft lines that are calls, writes
     or checks (144 against 126), and 103 of them are the class's routine.

**Reading.** A test here is the class's routine (setup, data, routine calls, most of which no
ticket line asks for) plus a few specific steps the ticket drives. That is why adapting the
right template beats every method that builds the test from the draft's lines: the template
carries the routine; per-line choice cannot, because the routine is not in the lines. The
loss that remains is in two places: the right class (placement, C1 60%) and the few specific
steps. With the measure corrected, the yardstick is 0.62 and the right template 0.67, so
placement is worth about 0.05 and the specific steps the rest of the way to 1.0.

**Line by line against the step truth (2026-11-17, `.scratch/step_truth_score.py`, free).**
Every row of the truth, kept or not by the kept outputs. Strict: the same call (or resolved
to the same member, or judged equivalent). Loose: also a call of the same member name (the
truth often writes calls through a local, checks through the assertion object). Setup counts
as kept when the output is in the reference's class or names the setup member (lenient).
"Inside a helper" rows are not scored. Loose figures, strict in brackets:

| Rows | Yardstick | Right template | Right calls given |
|---|---|---|---|
| **Asked by a draft line** | **65%** (56) | 67% (59) | 75% (64) |
| ...setup / data | 96% / 75% | 100% / 83% | 100% / 87% |
| ...calls / writes | 58% / 56% | 59% / 40% | 71% / 63% |
| ...checks | **34%** (29) | 34% | 41% |
| **Routine for the class, no line asks** | **81%** (80) | 86% | 87% |
| ...setup / data / calls | 91% / 50% / 5 of 10 | 97% / 48% / 4 of 6 | 97% / 57% / 4 of 6 |
| **Specific, no line asks** | **35%** | 34% | 54% |
| ...calls / data | 1 of 24 / 7 of 32 | 0 of 23 / 6 of 30 | 8 of 24 / 13 of 32 |

**Reading.** The tool keeps the class's routine (81%, its setup 91%); the right template adds
little to it (86%). The loss is in the specific part: the checks a draft line asks for (34%),
the calls a line asks for (58%), and what the reference does specifically for this test that
no line names (1 of 24 calls, 7 of 32 data blocks). That decides step 2 of the plan: **2b,
help the writer with the lines the template doesn't already do, keep the template's routine**,
not 2a (placement). The checks stand out: given the reference's calls, they rise only to 41%,
because the given calls leave out the assertion object's calls, and what a check asserts is a
value, not a member.

**Validator audit (2026-11-17, `docs/validator-audit-prompt.md`; private report
`t2t-private/output/validator-audit.{json,md}`).** 10 errors sampled per check (91 in all),
each opened in the suite:

| Check | Rule wrong | Config | Tool gap | Team inconsistent | Real defect | Change |
|---|---|---|---|---|---|---|
| assertions | 1 | 2 | 2 | 2 | 3 | split |
| data_keys | 0 | 2 | 4 | 1 | 3 | split |
| ids | 0 | 0 | 5 | 0 | 5 | split |
| names | 0 | 0 | 8 | 0 | 2 | rule |
| data_shape | 0 | 8 | 0 | 2 | 0 | setting |
| page_objects | 0 | 0 | 6 | 0 | 4 | split |
| base_class (7) | 0 | 0 | 7 | 0 | 0 | rule |
| style | 4 | 0 | 0 | 6 | 0 | split |
| data_file | 0 | 4 | 0 | 6 | 0 | setting |
| raw_driver (1), page_locators (3) | 0 | 0 | 3 | 1 | 0 | |
| **all** | **5** | **16** | **35** | **18** | **17** | |

Ranked by how much they would make a generated test look less like the team's: data_file,
data_keys, style, ids, assertions, names, data_shape, page_objects, base_class,
page_locators.

- The rules are mostly right: 5 of 91 rejections are a rule the team doesn't follow. 17 are
  real defects in the suite the validators rightly catch.
- **The biggest share, 35 of 91, is the tool not understanding a pattern the team uses** (all
  base_class and 8 of 10 names errors). A generated test that uses such a pattern is rejected
  and repaired towards something the tool understands: the repair loop pushes away from the
  team exactly there. 16 more are settings in the private config.
- Follow-up (`docs/tool-gaps-prompt.md`): 15 distinct tool-gap patterns (ids 3, data_keys 3,
  one shared with ids, assertions 2, names 2, page_objects 2, base_class 2, page_locators 1),
  each with an invented example in `t2t-private/output/tool-gaps-public.md`; 5 settings to
  change in the private config (`validation.check_helpers`, `validation.assertion_methods`,
  `data.expectation_sections`, `data.allowed_expectation_sets`, `style.json.key_separator`).
  Correction to the audit: data_keys is tool gap 3 and real defect 4 (not 4 and 3).
- Next: the settings in the private config (the human or the suite-reading session, from the
  private report); the tool gaps described as general patterns with invented names, so they
  can be built into the stand-in and the validators fixed there (a follow-up prompt).

**Step 3 rerun with the picks saved and the misses classified (2026-11-17, 0.03 USD; picks
kept in `t2t-private/output/pick-eval`).** Same means (0.42, ceiling 0.75). Each reference call
of each run (112), hit or missed, by where it sits in the table:

| Kind of reference call | Hit | Missed |
|---|---|---|
| Not in the 40 rows shown | 0 | 22 |
| Class, glue (made by half the class's tests or more), at the start | 23 | 5 |
| Class, glue, in the middle | 9 | 3 |
| Class, glue, at the end | 10 | 8 |
| Class, specific (fewer than half), at the start / middle / end | 2 / 7 / 2 | 4 / 9 / 0 |
| Folder only | 1 | 7 |

Picked calls the reference doesn't make: 90 (three a run).

- **My explanation was wrong.** I said the picks miss the glue no draft line names. Glue is
  picked 42 times of 58 (72%); specific calls 11 of 24 (46%).
- The misses: 22 are not in the rows at all (the ceiling), 16 glue (half of them at the end,
  where checks sit), 13 specific, 7 from the folder only.
- Read with the review: the table and the score both see calls only, and the references are
  atypical. This doesn't decide anything until the measure is fixed.

**The design review (2026-11-17, `docs/design-review-prompt.md`, a Sonnet session that read
the tool, the real suite and the private folder; full report in
`t2t-private/output/design-review.md`, names-free reply relayed).** The suite copy it read
has no git history, so Q6 is judgement; Q5 was a subagent's reading, two claims re-checked.

What it says, and what it does to our readings:

1. **The yardstick is not typical.** 11 of the 15 reference tests were parked by a
   ticket-linked skip (about 3% of the suite is). Every golden number so far is measured on
   tests the team wrote and set aside, not on how it usually writes tests.
2. **The helper criterion sees only part of a test.** C2 counts `self` calls. It ignores
   property writes (page fields set by assignment: about two thirds of the biggest area's
   tests), the same-page check, values and equivalent routes. The usage table has the same
   blind spot. So C2, `right-steps`' 0.85, the planner checks and the picking's 0.42 all
   measure the calls only.
3. **Tests are not mostly helper calls.** Of 20 tests read: helper-led 4, page-led 8, mixed 8.
   Setup does a large share of the work in 9, and the data entry steers loops or branches in
   10. The picking prompt said the opposite ("a test is mostly a short sequence of calls, one
   per step"), and the agreed direction assumed it (the human's Q1 answer included).
4. **Placement: the file decides the feature, the folder the base class and data, the class
   is a scaffold variant** (200 files, 471 classes, 65 multi-class files). C1 asks for file
   and class; the class half may be stricter than the team's own unit.
5. **Data: building from the nearest entry holds.** Of 32 blocks in 10 entries, 16 are exact
   copies from the same file, 8 adapted from a same-file neighbour, 4 from another file, 4
   new, none from a helper. Five of the 15 references have no entry.
6. **Patterns in `CLAUDE.md`:** of 18 bullets, 6 hold and 12 hold partly; two parts are
   wrong (import order is almost never alphabetical; "never both `targets` and
   `interactions`" fails in about 3% of entries).
7. **Beliefs behind the tool's misses** (Q5): a test is an edit of a template that must carry
   an entry; only catalog names are allowed; every test must show a check; an "or" in the
   draft becomes two tests; placement by word overlap with no notion of an existing twin.

Its three checks (Q8): run the tool's validators on the real tests (`check-suite`); re-score
the kept runs with a corrected helper and data score; count how many tickets already map to
an existing test through a skip reason.

**Reading.** Method point 5 ("distrust your own measure") applies to the yardstick itself.
Points 1 and 2 mean the numbers that decided today's direction (the agent at 0.69, the
picking at 0.42, the planner's misses) were taken on atypical tests with a score that sees
only calls. They are not thrown away, but no design decision should rest on them until the
measure is fixed. Next, all free or nearly: (a) `check-suite` on the real suite, masked;
(b) C2 extended to property writes and re-scored on the kept runs with `golden-rescore`;
(c) the skip-reason count; (d) with the human, a golden set whose references are typical
tests, not parked ones.

**The three team questions (2026-11-17): the human's first answers, set aside until the
mentor has been asked.** Nothing is built on them yet.
- **Q1: no**, with this meaning: a test made of helper calls, one per step of the scenario
  ("open the page, add a rule, go to a page, do something, check its log"), is what is
  wanted. What is not acceptable is a test that spells out line by line how a page is opened
  or how to browse. So for a new area the helper comes first, in the team's style.
- **Q2: propose.** The tool writes the missing helper as a separate patch, in the test's own
  class, never in the framework. **When a helper close to what is needed already exists, the
  tool proposes a change to it that keeps the existing tests working** (the human's example:
  a new argument with a default, and a branch on it), not a near-copy beside it. Adding
  test B must not break or disturb test A. This widens agent 2, which today may only add
  code: the rule in `CLAUDE.md` ("may add new code, never change existing framework code")
  already allows it for test-side helpers, since they are not framework code, but the
  proposal check has to learn "an existing caller still gets the old behaviour" (every
  existing call stays valid: new parameters have defaults, the default path is unchanged).
- **Q3: guess, flagged**, and a guess must be a value that really exists in the suite, never
  an invented one.

**Cost.** Developed on the stand-in with the fake model, free. The first paid golden run is
asked for when the stand-in checks pass; about two to three times a plain run.

## The agent upper bound, with neighbours (2026-11-17): helper recall 0.69, the tool 0.42 with the right template

The same prompt on the six `g` ids (one Haiku session each, 30 lookups allowed, the place
given, only the reference hidden). Here every reference call is reachable and the class is in
the copy, so C2 means what it says (`.scratch/score_agent.py`). The tool's numbers are its
two runs of the same ticket under `right-template` (placement given there too).

| Pair | Why chosen | Agent C2 | Tool C2 | Agent C3 | Tool C3 | Lookups | Gaps named |
|---|---|---|---|---|---|---|---|
| g04 | the class shows the helper | 0.40 | 0.20 | 1.00 | 1.00 | 13 | 1 |
| g05 | control | 1.00 | 1.00 | 1.00 | 1.00 | 13 | 0 |
| g06 | the helper is elsewhere in the suite | 1.00 | 0.25 | 1.00 | 1.00 | 11 | 0 |
| g10 | no template | 0.40 | 0.00 | 0.17 | 0.11 | 15 | 3 |
| g13 | the backend check dropped | 0.67 | 0.75 | 0.43 | 0.29 | 11 | 1 |
| g15 | the tool takes another route | 0.67 | 0.33 | 1.00 | 1.00 | 14 | 2 |
| mean | | **0.69** | **0.42** | 0.77 | 0.73 | 13 | |

Against today's defaults (`seed-floor`) on the same six the tool has C2 0.40 and C3 0.71.

Against the prediction (2026-11-16): the agent beats the tool's helper recall on at least four
of six: **met, four of six** (g04, g06, g10, g15; g05 ties as the control; g13 is one call
lower).

The reading, with `right-steps` (given the calls, the generator writes them: 0.85):
- **The agent finds the calls**, with 11 to 15 lookups of the 30 allowed. By the table in
  `docs/agent-upper-bound-prompt.md` this is the first row: generation that chooses members by
  looking them up is worth building. It closes about half of the way from the tool (0.42) to
  the calls given (0.85).
- The data side barely moves (0.77 against 0.73). g10 and g13 stay low for both: lookups
  don't fix data, as the seed checks of 2026-11-16 said.
- **Where the gain sits** (`.scratch/agent_pages.py` on the same outputs): of the reference
  calls the index resolves to a class and member, the agent makes 7 of 12 and the tool 14 of
  24, the same share. The agent's lead is all in the calls the index can't resolve (compared
  as written): g06 4 of 4 against 1 of 4, g04 and g10 one more each. So the agent finds
  members the catalog doesn't know how to type. For the design this cuts both ways: lookups
  reach what the catalog misses, and a plan "checked by code" would have to mark exactly
  these rows `unknown`, not wrong.
- Limits: one session a ticket against a mean of two runs; six tickets chosen by kind of
  miss, not at random; the first prompt kept the draft out of reach (fixed after g05's first
  session; whether g05 was redone is not recorded, and the `a` runs may have been made from
  the ticket alone, which counts against the agent, not for it). A sign strong enough to decide Phase B on, not a number to quote.

## The agent upper bound, no template (2026-11-17): half of what can be reached, where the tool makes almost none

Six sessions on Haiku (a04 a05 a06 a10 a13 a15), one ticket each, 30 lookups allowed, the
place given, every test file of the reference's folder removed
(`docs/agent-upper-bound-prompt.md`). Scored first with `.scratch/score_agent.py`: helper
recall 0.08, data recall 0.40.

**That first reading was wrong, and so is part of `cold-area`'s.** C2 resolves the new test's
calls through its class. A class written new is not in the index, so nothing resolves and the
recall is 0 whatever the test calls. And most of what the reference calls is not in the copy
at all: its own class's helpers went with the folder. `.scratch/agent_pages.py` (checked on
the stand-in: a new class repeating the reference scores 8 of 8) resolves a new class through
the base it is written with, replaces the reference's own helpers by what they call, and
counts what is reachable in the copy:

| Pair | Reference calls, opened up | Reachable in the copy | Agent makes | Tool makes (2 runs) | Classes shared, agent | Classes shared, tool |
|---|---|---|---|---|---|---|
| a04 | 5 | 4 | 1 | 0, 0 | 1 of 2 | 1, 1 |
| a05 | 4 | 2 | 2 | 0, 0 | 2 of 2 | 0, 0 |
| a06 | 4 | 1 | 0 (no call at all; 2 gaps named) | 0, 0 | 0 of 1 | 0, 0 |
| a10 | 3 | 1 | 0 (no test function parsed; 2 gaps named) | 1, 0 | 0 of 1 | 1, 0 |
| a13 | 6 | 4 | 3 | 0, 0 | 2 of 2 | 1, 0 |
| a15 | 0 | 0 | nothing to measure (3 gaps named) | nothing to measure | | |
| all | 22 | 12 | **6 of 12** | **1 of 24** | 5 of 8 | 4 of 16 |

Data blocks (C3, unchanged measure): agent 0.40, the tool 0.64 on the same six.

Against the prediction (written 2026-11-16): helper recall above 0 on at least four of six:
**not met as written, three of six** (three of the five where anything is reachable). Data
not better than the tool's: **met**.

The reading:
- With lookups, the same model lands on the feature's own classes on three tickets and makes
  half of the reachable calls. The one-shot tool, adapting another area's test, makes 1 of 24.
  That is the difference the direction counts on, on a small sample (12 calls, one session
  each): a sign, not a result.
- **The no-template yardstick measures little.** Only 12 of 22 calls are reachable, and a15
  has none. `cold-area`'s "0.00 on all 30 runs" stays true of the tool (it writes in another
  folder, where its calls do resolve), but half of that zero could not have been anything
  else. With no template, code can count the reachable calls and the classes; whether the
  test is a good one needs a person (columns E and G of the verdict sheet on these outputs).
- Two of six outputs name gaps and write no usable test (a06, a10). By the direction's own
  rule a gap is a valid output, but code can't tell an honest gap from giving up.
- The data side is worse than the tool's, as predicted: there is no entry to copy.

Next: the same prompt with neighbours (the six `g` ids), where every reference call is
reachable and C2 means what it says; and a person's look at two of these six outputs.

## `cold-area` measured (2026-11-16): with the folder's tests gone, the tool adapts a test of another area

15 x 2, Haiku API, 100 calls, $1.16; every test file of the reference's folder removed (42
to 4,098 tests a ticket). All 30 generated. Stopped at 23 runs for the speed work and
resumed, so it holds runs from before and after the speed fixes (they don't change output).

| | C2 mean recall | C3 mean recall | Validators, of generated | Made-up values |
|---|---|---|---|---|
| `seed-floor` (warm) | 0.47 | 0.77 | 30/30 | 87% |
| `cold-class` | 0.38 | 0.65 | 26/26 | 80% |
| `cold-area` | **0.00** | 0.50 | 27/30 | 73% |

**Against the prediction written before the result:** validators "all pass": wrong, 27 of
30. Failed generations "4 to 7": wrong, none. Helpers "0.25 to 0.35": wrong, 0.00 on all 30
runs. Data blocks "0.45 to 0.60": right, 0.50. "The four big-folder tickets fall most":
mostly (g11, g12, g13 at 0.00 on data blocks; g04 stays at 1.00). "More modules than
methods": wrong, 22 methods and 8 modules.

- **Placement (`cold_placement.py`):** all 30 outputs are in **another folder**, 22 as a
  method in another area's class. The tool found the nearest remaining neighbour and adapted
  it, though it belongs to another feature.
- **The zero on helpers is real, not the scorer** (`c2_misses.py`): of 112 missed helpers, 34
  are the reference class's own (gone with its file) and 78 are page members; the new test
  touched the same page or class for only 10 of those 78, and a call of the member was shown
  in the context for 2. The new tests are built on other pages.
- **Only 24 of the 112 are used by any test left in the suite** (`reachable.py`). With the
  folder's tests removed, most of what the reference calls exists only in the framework's
  code, with no test showing its use. That is the no-template case exactly: the knowledge is
  in the framework and today's tool doesn't read it by itself.
- **Data blocks:** 131 missed in 20 runs; a whole seed section 44, expectations 38, custom
  keys 24; six runs have no entry where the reference has one. 105 of the 131 exist in some
  other entry of the suite.
- Read: valid code in the suite's style, for the wrong part of the product. A tool that
  needs a neighbour takes a wrong one when the right one is missing; it does not fall back
  to the framework. This is the baseline for the goal, and it supports the direction in
  `docs/design-direction.md` (compose from the framework) more strongly than anything
  measured before.

## `right-steps` measured (2026-11-16): given the members, the generator writes the test

15 x 2, Haiku API, 65 calls, $0.66. `eval.oracle_template` and `eval.oracle_steps` both on:
the right template, and the calls the reference makes listed in the context (names only, no
order, no arguments). Compared with `right-template`, so the one difference is that the
choice of members is given. 28 of 30 generated: g01 fails on the context budget in both runs
(as before); g02 r2 and g03 r2 timed out and were made again with `--resume`.

| | C1 | C2 pass, of generated | C2 mean recall | C3 pass, of generated | C3 mean recall | Validators, of generated |
|---|---|---|---|---|---|---|
| `right-template` | 83% | 8/27 | 0.56 | 14/27 | 0.75 | 27/27 |
| `right-steps` | 87% | **20/28** | **0.85** | 13/28 | **0.83** | 28/28 |

**Against the prediction written before the run:** "helpers rise to 0.85 or more if the
generator can use a given choice; under about 0.75 it doesn't make the calls even when told":
0.85: right. "Data blocks
rise a little, the expectation section following the check on g13": right (0.75 to 0.83; g13
from 0.29 to 0.86). "g01 fails on the budget again": right.

- **Helpers, per ticket against `right-template`:** better on g03, g04, g08, g09, g10, g13,
  g14, g15; the same on g05, g06, g07, g11, g12 (four of them already at 1.00); worse on
  none. g04 goes from 0.20 to 1.00, g15 from 0.67 and 0.00 to 1.00.
- **What still misses with the calls given:** g09 (0.50) and g10 (0.40, 0.20), where no test
  of the reference's class is left, so its own helpers aren't there to call; g06 (0.25, both
  runs, unchanged: three of its four calls are ones the catalog can't resolve); g14 (0.80).
- **Data blocks** follow the calls where a call implies them (g13, g15, g10 a little) and
  stay where they were otherwise (g12 0.60, g14, g11 one run at 0.00): the seed side is not
  moved by knowing the calls, as the entry check said (60% of an entry is seed).
- **Read: assumption 1 holds.** The writer is not the limit. Told which members a correct
  test calls, with nothing about order or arguments, the same model in the same one shot
  writes them on 20 of 28 runs against 8 of 27. The choice of members is the limit, and the
  remaining misses are members that don't exist where the test is written. So the planning
  step is the part to build, not a new writer; and data needs its own source.
- **Speed, first full run on the faster code, two runs of a ticket together:** 131 minutes
  for 30 runs (146 before). Little gain: a run's own time rose from a median of 216 s to
  367 s, so two calls at once are each slower (and two second runs timed out). The index and
  validation fixes hold; making runs together is not worth it on this account, and
  `eval.golden_parallel` stays at 1.

## Two free checks for the "compose from the framework" direction (2026-11-16)

`.scratch/framework_probe.py <golden.json>` on the warm golden set (`.scratch/framework-probe.log`),
no model call. Both were asked because `cold-area` showed the tool has no way from a draft to
the framework except through a test.

**1. What the reference tests call, and whether a search of the framework finds it.**
- The 15 reference tests make 56 `self` calls in all (1 to 7 each; this is all C2 counts).
  **The catalog resolves 36 of them to a class (64%)**; 20 stay unresolved (all 7 of g01, g07,
  most of g06 and g08): the known limit of static typing on this suite.
- Of the resolved ones most lead into the reference's **own class line** (helpers of the test
  class and its area base). Only **9 framework classes outside that line** are called, over
  7 tickets. So the references mostly work through helpers that live with the tests of the
  area, not through page objects called directly.
- Searching only page objects, classes and helper functions (362 + 3,561 + 36,246 chunks, no
  tests) with the draft's words: of those 9 classes, 4 rank in the top 5, 6 in the top 30,
  1 in the top 200, 2 not at all. A small sample; plain search finds about two in three.

**2. How much of a reference entry the test's calls could tell.** 93 key paths (two levels,
as C3 counts) over the 11 references that have an entry:

| Kind | Paths | Could a plan of calls say it is needed? |
|---|---|---|
| Seed section | 56 (60%) | no: the framework applies whatever is there; nothing in the calls names it |
| Expectation section | 29 (31%) | its presence, when a backend check is planned (the check is called through a helper in 22 of them); its content, no |
| Custom key read by a called helper | 7 | yes |
| Custom key the test reads itself | 1 | only if the plan says so |

Read, and what it changes in `docs/design-direction.md`:
- **Assumption 5 is mostly false as written.** "What the entry must hold follows from the
  calls" covers at most 40% of the paths, and the content of none. Seed data is the largest
  part and has to come from somewhere else: an entry elsewhere in the suite (105 of the 131
  blocks missed in `cold-area` exist in another entry), the draft's preconditions mapped to
  seed sections by the model, or a marked gap. The plan needs `seed` rows that name where
  each section comes from; code can't derive them.
- **A new area has no helper layer.** The references call their own class's helpers more
  than pages. With no test class in the area those helpers don't exist, so a composed test
  either calls the pages directly or the helpers are proposed too (agent 2's kind of output).
  Whether a test written straight on the pages is acceptable is a question for the team.
- **The plan's "every member exists" check has a hole of about a third** on this suite: a
  call the catalog can't resolve can be neither confirmed nor refused. It needs the
  validators' existing third verdict (unknown), shown to the reviewer, not an error.
- The entry point is not the main worry: where a class can be named at all, search over the
  framework finds it about two times in three with the draft's words alone.

**Two more free checks the same evening (`.scratch/seed_and_unresolved.py`,
`.scratch/seed-unresolved.log`).**

*Where seed data could come from.* The references hold 20 seed sections. Does another entry
of the suite hold the same thing?

| Compared as | In the reference's folder | Outside it |
|---|---|---|
| the same value | 9 | 3 |
| the same once text values are blanked | 16 | 4 |
| the same keys two levels down | 17 | 5 |

Every section's *name* exists outside the folder; its *shape* mostly doesn't. So the
neighbours supply about 80% of the seed data and the rest of the suite about 20 to 25%. For a
new area seed data can't be copied: it is specific to the feature, and has to be a marked gap
or a flagged guess (asked of the team as Q3 in `docs/verdict-sheet.md`). The earlier "105 of
131 missed blocks exist elsewhere" counted key paths, not whole sections, and was too kind.

*Why 20 of the references' 56 calls don't resolve to a class.*

| Kind | Calls |
|---|---|
| `self.<attribute>.<method>()`: the attribute resolves, but to a type that is not a class of the suite | 10 |
| a chain whose first step the class line doesn't have (the root attribute is not known to the catalog) | 8 |
| a first step of unknown type | 2 |

None is a deep chain breaking midway. Half are objects that come from outside the suite's
own classes; the other half are roots the catalog doesn't know on that class (all 7 calls of
g01). That second half looks like calibration (declare the attribute and its type in the
private config, as `index.chain_roots` does for the page root), not a limit of static
reading; worth one question to the session that can see the suite.

*The agent upper bound* is ready in two versions (`docs/agent-upper-bound-prompt.md`): with
neighbours and with the folder's tests removed, scored by `.scratch/score_agent.py`, with its
prediction written in the prompt file.

## Why golden runs were slow, and three fixes (2026-11-16)

The `cold-area` run was stopped by hand at 23 of 30 after five hours (its runs are kept; it
is resumable). The process was not waiting on the model: it used a full CPU core, and single
runs took 17, 41 and 53 minutes. Measured with `.scratch/stage_times.py` (the stages that
make no model call, run again on a kept run and timed; no cost):

| What | Before | After | Cause |
|---|---|---|---|
| Validating one patch into a class with about 840 tests | over 420 s (cut off; the run it came from took 53 min, with one validation per attempt and repair) | 69 s | the class's own members were collected by a walk of the whole class once per test in it; now once per class (`validate/validator.py`, `validate/datause.py`) |
| Indexing a ticket's copy (15 a run, plus the suite) | 97 s every time | 27 s when unchanged | the saved index's file section was found by the text of the next section's key, which also occurs inside the data when the suite's code uses that name, so the section was cut short and never reused; the sections now start with a mark that can't occur in the data (`index/indexer.py`). Every log line "Ignoring unreadable index" was this. |
| A ticket's two runs | one after the other | together, with `T2T_EVAL__GOLDEN_PARALLEL=2` (default 1) | they share the ticket's index and mostly wait on the model; each run has its own staging folder and the usage meter is safe to share (`eval/golden.py`, `llm/meter.py`) |

Each has a test that fails on the old code. None changes what is generated or how it is
scored, so the `cold-area` report holds runs from before and after them. Earlier reports
are unaffected. One golden run of 30 took about two and a half hours before (116 minutes in
the runs, about 30 preparing); the first full run on the new code will show the new time.
Still open on speed: a patch is validated as the whole patched file and the whole unpatched
file on every attempt (the unpatched half could be done once), and reading a class's
references takes 20 s on the largest file.

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
- **Measured (label `seed-floor`, 28 of 30 generated, 2 CLI timeouts (cause not known),
  $0.73): no gain. Off.** C3 40% (baseline-2 40%); recall rose where it reaches (g12 0.40 ->
  0.60, g10 r2 0.17 -> 0.33) but no ticket passed because of it. C4 80% (g06 ×2, g10 r2, g15
  r2), C7 93% (the two failed runs): within noise. To resume after A1.
- Resumed (both runs generated, $0.81 in all): C1 60%, C2 20%, C3 43%, C4 87%, C5 93%, C7
  100%, C8 63%. C3 is 13/30 against 12/30: one run, noise.
- **Re-judged by the keep rule (CLAUDE.md, method point 4): on by default since 2026-11-12.**
  C3 recall per ticket against baseline-2: better in g11, g12, g14 (not worse in either run),
  worse in none; mean recall 0.77, the highest of the five full runs (others 0.66-0.71).

### Earlier verdicts re-judged by the keep rule (2026-11-12)

Per ticket, a ticket counts as better (worse) when neither run is worse (better) and the sum
moved. The seed floor acts after the model's reply, so it can't change C2: its C2 column is
pure run-to-run noise, and it is large: **4 tickets better and 4 worse with nothing changed.**

| Switch | Judged on | Better | Worse | Verdict |
|---|---|---|---|---|
| `seed_floor` (C3) | full run | g11, g12, g14 | none | on |
| `context_member_cards` (C2) | full run | g12, g13 | g01, g04, g07 | off: inside the noise above; the missed-helper count didn't drop (54 vs 51) |
| `step_plan` (C2) | full run | g12, g13 | g04, g05, g07, g08 | off: same |
| `kind_as_preference` (C1) | replay, recorded replies | none | 3 tickets | removed: a firm loss |
| summed retrieval scores (`class_from_retrieval`) (C1) | replay | none | 2 tickets | removed: a firm loss |
| `dataless_hit_class` (C1) | replay | g04 | g11 | removed: a firm loss, in both forms |
| `search_named_classes` (C1) | replay | none | none (g12's reference ranked lower) | off: no effect |
| `glossary_class_wins` (C1) | replay | g07 | g12 | off, **but open**: g12's loss may be a wrong glossary entry. If a person finds the entry wrong (or that class a second valid home), it is a gain with no loss and goes on. |

The placement replays reuse recorded model replies, so there is no run-to-run noise in them:
their losses are real, and the old verdicts stand. Member cards and the step plan were judged
on full runs, where the per-ticket noise on C2 is as large as their effect; they are not shown
harmful, but not shown useful either, and the missed-helper counts (a more direct measure)
didn't move. They stay off; a fair re-test would take two more full runs each.

## A new plan (2026-11-12): fix the yardstick before more changes

Ten changes since baseline-1 (seven placement rules, the glossary, member cards, the step
plan) moved nothing beyond noise. Three things in how we measure and choose:
1. C2 and C3 ask for the one reference test exactly, and part of it looked new to the suite
   (31 of 54 missed helpers are called by no other test of its class; 32 of 88 missed blocks
   are in no entry of the class). A1 below shows that reading was wrong: most of it is used
   elsewhere in the suite.
2. C6 (is the draft useful to a QE) has never been filled, so every choice was made on proxies.
3. The upper bound (plan step 5: a stronger generator) was never run, so we don't know whether
   the ceiling is the model or the pipeline.

Plan: **A** fix the yardstick (free): A1 score C2/C3 against what was reachable, A2 recall
means next to pass rates, A3 the parse failures. **B** two diagnostic runs: B1 Sonnet API
generates (everything else unchanged), B2 the reference class's nearest test given as the
template (D6 as an oracle; needs a switch). **C** the human judges 15 outputs (keep / small
edit / rewrite). **D** then decide: D6, a stronger generation model if B1 shows the model matters, D3/D4 (gaps and
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

**A1 (`.scratch/reachable.py <report.json>`, on baseline-2): the ceiling is high, and my
reading in point 1 above was wrong.** "Reachable" here is broad: another test anywhere in the
suite the run saw calls the helper, or an entry anywhere has the key path.
- C2: 36 of the 51 missed helpers are reachable. Pass against the reachable part: 9/29
  (exact: 5/30).
- C3: 71 of the 79 missed blocks are reachable. Pass against the reachable part: 12/29, the
  same as exact.
- So "rare in the reference's class" did not mean "new to the suite": most of what the
  generator misses is used somewhere else in the suite. Only a small part is out of reach.
  The gap is real, not an artifact of the exact match. (Upper bound: being somewhere in
  thousands of tests is not the same as being findable.)

**A3:** all three parse failures (g06 ×2, g15 r2) are "syntax error near line 1" from the
tree-sitter check. Not modern syntax tree-sitter lacks (nested f-string quotes, `match`,
`type`, `except*` all parse). The model's raw reply isn't kept, so the cause (a fence, escaped
newlines, prose before the code) needs one `--debug-log` run of g06 and a masked look at the
code's first line. Open.

**B1 needs no yaml change:** `-e 'T2T_LLM__CLAUDE_CODE_CLI__STEP_MODELS={"generate":"claude-sonnet-5-5"}'`
moves only the generate step (and repair, which reuses its request) to Sonnet; every other
step stays on Haiku (`.scratch/models_per_step.py` prints the model per step).

**B1 measured (2026-11-13, label `sonnet-generate`, 15 × 2, 69 calls, $8.05): a stronger
model writing the code does not help.** Same settings as the `seed-floor` run (Haiku API
generating, $0.81); only the generate model differs (the report's config shows it). The run
was cut at 7 of 30 by a machine shutdown and finished with `--resume`; all 30 generated.

| | C1 | C2 | C3 | C4 | C5 | C7 | C8 | C2 mean recall | C3 mean recall |
|---|---|---|---|---|---|---|---|---|---|
| `seed-floor` (Haiku API) | 60% | 20% | 43% | 87% | 93% | 100% | 63% | 0.47 | 0.77 |
| `sonnet-generate` | 57% | 13% | 40% | 83% | 93% | 100% | 70% | 0.40 | 0.74 |

Per ticket, by the keep rule: on C2 no ticket is better in both runs and one is worse in
both (g06, 0.25 to 0.00); on C3 none is better in both and one is worse in both (g14, with
its placement also lost in one run). Nine tickets have the same C2 recall in both runs under
either model, and the tickets at 0.00 (g07, g09, g10, g15) stay at 0.00. So the misses are
not the generating model's weakness: with the same context, a stronger model leaves out the
same helpers and blocks. What the model is given (the template and the examples) decides
it. **A stronger model for generation is dropped**; it costs ten times as much for
nothing. (An earlier note here called this D5; in the plan D5 is sample-and-select, which this
run doesn't test, though nine tickets scoring the same in every run under both models
suggests picking among samples has little to choose from.) B2 (the reference class's nearest test given as the template) is the next
diagnostic. Both g06 runs generated here, so the parse failure (A3) didn't show under
Sonnet. Compared with `.scratch/cmp_logs.py <log A> <log B>` (from the two run logs).

**B2 built (2026-11-13): `eval.oracle_template`, off.** A diagnostic for golden runs only.
After search, the nearest remaining test of the reference's class goes first among the
templates (a test with data before one without, then the most words shared with the draft,
then the search score); with `template_class_wins` the class then follows it. A class with
no test left pins nothing, and each run's progress line says `template pinned: yes` or
`no test left in the class`. It doesn't force the area: where the area choice leaves the
reference's file out, placement can still miss, and the placement column will show it. It
measures what the right template alone gains on helpers called and data blocks present, which
is also what "the QE names the nearest test" (D6) could gain at most. Turned on for one run
with `-e T2T_EVAL__ORACLE_TEMPLATE=true`; compare against `seed-floor`. Not run yet.

**B2 measured (2026-11-16, label `right-template`, 15 × 2, Haiku API, 69 calls, $0.63): the
right template fixes placement, lifts helpers a little, and does nothing for data blocks.**
The run was cut at 21 of 30 by a machine shutdown and finished with `--resume`.

| | C1 | C2 | C3 | C4 | C5 | C7 | C8 | C2 mean recall | C3 mean recall |
|---|---|---|---|---|---|---|---|---|---|
| `seed-floor` | 60% | 20% | 43% | 87% | 93% | 100% | 63% | 0.47 | 0.77 |
| `right-template` | 83% | 27% | 47% | 83% | 83% | 90% | 63% | 0.56 | 0.75 |

- 27 of 30 generated. **g01 failed both runs on the context budget** (the pinned template
  makes the required context about 22,000 tokens against the 16,000 limit), and g11 r2
  failed; none on a model call. Failed runs count as misses in the pass rates, which is why
  C5 and C7 look lower. The template was pinned in 24 runs; g09 and g10 have no test left in
  the reference's class, so they ran as usual.
- **Placement:** g04, g05, g06, g15 now right in both runs (wrong in both before); g07 still
  "not a candidate" (the draft's kind filters its class out); g11 lost one run to the
  failure. 25 of the 27 generated runs are placed right.
- **Helpers called, per ticket:** better in both runs g07 (0.00 to 1.00); better in part g12,
  g15, g03; worse in both g04 (0.40 to 0.20, now in the right class); the rest the same.
  g09, g10 stay at 0.00 (not pinned), g06 at 0.25 and g14 at 0.60 with the right template.
- **Data blocks, per ticket:** g15 better in both (0.80 to 1.00), g14 worse in both (0.79 to
  0.71); g13 0.29, g12 0.60, g11 0.00 unchanged with the right template.

Read: naming the nearest test (D6) is worth about four tickets of placement, which no
placement rule reached, and a small gain on helpers. It is not the answer to the helper and
data-block misses: with the right class and its nearest test as the template, mean helper
recall is 0.56 and data-block recall is unchanged. Those misses are things the nearest test
doesn't have either (steps and sections the new test needs from elsewhere), which matches
the earlier finding that most missed helpers are steps the template lacks. D6 is worth
building for placement. Its cost to guard: a large named template can overflow the context
budget (g01), so the pinned path needs the template trimmed or the budget raised for it.

**What is still missed with the right template (2026-11-16, free: `c2_misses.py`,
`c3_misses.py`, `reachable.py` on the `right-template` report; masked logs in
`.scratch/rt-*.log`).** 27 generated runs, placed right in all the runs the scripts list.

| Where the missed item exists | Helpers (47, in 19 runs) | Data blocks (69, in 13 runs) |
|---|---|---|
| In the output's own class (the template calls it or another test does; the base entry or a sibling entry has it) | 20 (g02, g03, g04, g13, g15) | 41 |
| Only elsewhere in the suite | 13 (g06, g08, g09, g10, g14) | 20 (mostly g10) |
| Nowhere else in the suite | 14 | 8 (g14 6, g10 2) |

- Helpers: 10 of the 20 are called by the template itself. g02 r2 dropped all three its
  template calls and shares none of its calls with it. Inlined: 0.
- Blocks: a whole section absent for 50 of 69; the base entry had 31. g11 r1 has no entry and
  g13 has 2 paths, with the blocks in the base entry.
- Read: about half of what is missed was in the class the tool wrote into and was left out
  (generation); about a quarter is in the suite outside the class (the fixed context doesn't
  reach it); about a fifth is used by nothing else in the suite (the author's choice or
  added with the reference: no pipeline produces it, it should be a marked gap).
- Suspected cause for the blocks, not yet checked: `generate_v6` tells the model to leave out
  what the scenario doesn't read ("leave out everything else", "seed only what the scenario
  reads", "delete sub-keys"), a rule decided on the stand-in. If the real suite's entries
  commonly carry sections their test doesn't read, the rule is wrong for it. Free check: count
  entries with sections the test never reads. For the helpers no cause yet; whether the
  draft has a step for each dropped helper is in the derivability audit.

**The suspicion above checked on the kinds (2026-11-16, `c3_kinds.py` on the
`right-template` report, `.scratch/rt-c3-kinds.log`): mostly wrong.** Of the 69 missed
blocks:

| Kind | Count | Where | What it is |
|---|---|---|---|
| Expectation section absent | 22 | g10, g13 | the new test calls no backend check, so no section |
| Seed section absent | 13 | g10 r1, g11 r1 | the new test has no entry at all (it reads no data) |
| Custom key absent | 15 | g09, g10, g11, g13, g14 | a value the reference reads from data; the new test keeps it in code or doesn't use it |
| A key inside a kept seed section | 16 | g02, g09, g10 r2, g12, g14 | 6 removed by the model's own delete changes |
| A key inside a kept expectation | 3 | g02, g09 | |

So 50 of 69 follow from what the new test does (no data read, no backend check, values in
code), the same choice as the helpers, not from stripping. Only the 16 keys inside kept seed
sections fit the "leave out what isn't read" rule, and 6 of them are the model's deletes. The
suite-wide count of unread sections is not needed. A possible small switch, not built: no
delete changes inside a copied seed section (the seed floor for sub-keys).

**The derivability audit (2026-11-16, by Haiku with `docs/derivability-audit-prompt.md`,
against `seed-floor`; a model's judgement, not yet spot-checked by a person).** Where a
writer who had not seen the reference could have learned each thing it does; "missed" = the
tool lacked it in every generated `seed-floor` run.

| | ticket | draft only | class habit | findable in the suite | outside |
|---|---|---|---|---|---|
| Reference helpers (89) | 48 | 3 | 17 | 12 | 9 |
| Reference data blocks (97) | 48 | 3 | 30 | 10 | 6 |
| Missed helpers (24) | 11 | 1 | 4 | 3 | 5 |
| Missed data blocks (28) | 7 | 3 | 9 | 3 | 6 |

- The class is clear from the ticket and draft on 5 of 15 (g02, g09, g10, g12, g14). Haiku
  hesitated between "findable" and "outside" on 6 items.
- Only about one item in ten of a reference test comes from outside the ticket and the
  suite (9 of 89 helpers, 6 of 97 blocks), and it sits in few tickets (g10 has 10 of the 15,
  then g09, g14, g11). Those are missed almost always (11 of 15), as they must be.
- The rest is missed at about the same rate whatever its source: ticket 23% of helpers and
  15% of blocks, class habit 24% and 30%, findable 25% and 30%. Nearly half of the helpers
  missed every time (11 of 24) are for something the ticket states.
- Read: the tickets are not the main limit on helpers and data blocks; they are the limit on
  placement (10 of 15 don't say which class, which fits the right-template result: D6). With
  the scripts above, three counts now agree that most of the gap is the pipeline not using
  what the ticket and the class give it.
- A limit of the audit as written: the bins take the first that fits, so "ticket" doesn't say
  whether the frozen draft kept the item. Follow-up question for Haiku, at the end of the
  prompt file: of the missed items in the ticket bin, how many does the draft state.

**Follow-up answered (2026-11-16, Haiku): the drafts kept them.** Of the 11 helpers missed
every time that the ticket states, the draft states 9 and partly states 2; of the 7 blocks, 4
and 3. None is absent from the draft. So the draft step is not where these are lost: the
generator had the step in the draft and did not call the member that does it. (18 items, a
model's judgement.) Still open, and it decides whether this is a real omission or the
yardstick: did the new test do that step another way (an equivalent member), do it wrongly,
or not at all. Second follow-up at the end of the prompt file.

**Follow-up 2 answered (2026-11-16, Haiku): for the helpers, mostly another route, never
skipped.** What run 1's test did for the draft line of each of those 18 items:

| | same effect, another member or block | weaker | absent |
|---|---|---|---|
| Helpers (11) | 7 | 4 | 0 |
| Data blocks (7) | 1 | 4 | 2 |

- Helpers: no stated step is skipped. In 7 of 11 the test does it through a member Haiku
  judges equivalent, and C2 counts that as a miss. So on the steps a ticket states, C2
  overstates the gap; the real loss there is the 4 "weaker" ones. Whether "same effect,
  another member" is acceptable is the team's call (the goal is the suite's and the team's
  way, so the preferred helper may matter): a person's verdict, not Haiku's.
- Data blocks: 6 of 7 are weaker or absent. The data side is a real loss.
- Only the ticket-stated items were asked (18 of the 52 missed every time). The class-habit,
  findable and outside items are not covered.

**The goal, stated by the human (2026-11-16):** tests in the suite's, the team's and the
codebase's style, **also when there is no similar test or area to copy from** (a completely
new test). Against that goal the weakest tickets are the measure: g09 and g10 (no test left
in the reference's class) are at 0.00 on helpers in every run under both models and hold
most of the "outside" items. Today's generator adapts a template; with no template it has
nothing to lean on. Proposed, not built: a second yardstick on the same 15 tickets with the
reference's whole class (or folder) hidden, so every ticket is a "no template" case.

**The no-template yardstick, designed (2026-11-16; built as a script, not run yet).**
`.scratch/cold_set.py <golden.json> class|area <out.json>` writes a copy of the golden set
with more hidden, through the existing `hide` field (no change to `src/`); it prints counts
only. Checked on the stand-in with `.scratch/cold_set_smoke.py` (hide lists accepted, copies
index, no model call).

| Level | What is hidden besides the reference | What the tool still has | It measures |
|---|---|---|---|
| warm (today's golden set) | the pair's own `hide` | the class's other tests | copying a neighbour |
| `class` (ids k01...) | every other test of the reference's class (its helpers and setup stay) | sibling classes of the folder, the framework | a new class in a known area (g09 and g10's case, for all 15) |
| `area` (ids a01...) | that, and every test file of the reference's folder with its data files | other areas, the framework | a completely new area |

- New pair ids, because the leave-one-out copies are cached per pair id and the scripts that
  read a report open that copy: a cold run under the old ids would make the warm reports'
  scripts read cold copies.
- Scoring as it is: with the class emptied the scorer already expects a new file in the
  reference's folder (C1). At `area` level C1 only says whether the folder is still chosen.
  C2 will count the reference class's own helpers as missed (the new test is in another
  class): read C2 with `reachable.py`, and `c2_misses.py`'s `far` count, next to it.
- What to read first: C7 and C4 (is the output still valid and in the suite's style with no
  neighbour), then C2 and C3 mean recall against warm (0.47 and 0.77). g09 and g10 predict a
  large fall on C2. If it doesn't fall, the template does less than assumed.
- Cost: about $0.80 a level (15 x 2, Haiku API). `class` first.

**Where "the new test does less" comes from (2026-11-16, free: `.scratch/extent.py` on the
`right-template` report, `.scratch/rt-extent.log`).** For the 13 runs that miss C3: does the
new test make a backend check (a direct call of an expectation helper), does it have an
entry, and did its template and the output's class.

| Ticket | What the new test lacks | Its template | The output's class |
|---|---|---|---|
| g13 (both runs) | the backend check (4 expectation paths a run) | checks | 42 of 84 tests check |
| g11 r1 | any entry (4 seed paths, 1 custom) | has entries | 741 of 741 have one |
| g10 (both runs) | the backend check (7 a run); r1 also any entry (9 seed) | doesn't check, has an entry | no other test (a new class) |
| g09, g10 r2, g13, g14 | custom keys the reference reads | has custom keys only in g14 | |
| g02, g12 | only keys inside kept sections | | |

- Two plain drops by the model, each against its own template and class: g13's check and
  g11's entry. A floor from the class's habit would catch both (the class always has an
  entry; the template checks and half the class does).
- g10 is the no-template case, and it alone is 32 of the 69 missed blocks: nothing near it
  shows the check. C3's gap under the right template is mostly three tickets.
- The custom keys are the reference's own (the template has none in 5 of 7 runs): not
  something a neighbour shows.
- The `cold-class` run (label `cold-class`, started 2026-11-16, Haiku API) was going during
  this; the script reads the warm copies, the run the cold ones.

**`cold-class` measured (2026-11-16, 15 x 2, Haiku API, 69 calls, $0.77): the output stays
valid, helpers fall a little, data blocks fall more, and the tool never writes a new class.**
Every other test of the reference's class hidden (0 to 742 a ticket); same drafts and
settings as `seed-floor`. 26 of 30 generated (k03 r2 and k06 r2 didn't parse, k02 r1 failed
validation, k10 r1 a CLI timeout); failed runs count as misses in the pass rates.

| | C1 | C2 | C3 | C4 | C5 | C7 | C8 | C2 mean recall | C3 mean recall |
|---|---|---|---|---|---|---|---|---|---|
| `seed-floor` (warm) | 60% | 20% | 43% | 87% | 93% | 100% | 63% | 0.47 | 0.77 |
| `cold-class` | 10% | 13% | 37% | 80% | 73% | 87% | 40% | 0.38 | 0.65 |

- **Valid and in style without the class's tests:** all 26 generated runs pass the
  validators; made-up values only in k15.
- **Placement (`.scratch/cold_placement.py`):** all 26 in the reference's folder; 23 are a
  method in a sibling class (8 in the reference's file, 15 in another file of the folder), 3
  a new module (k09, k10, as in the warm runs). None used the emptied class. C1 says 10%
  because the scorer expects a new file; whether a method in a sibling class is acceptable is
  the team's call, so C1 is not a fair measure at this level. And it means this level is not
  "no template": the tool found another neighbour to lean on.
- **Helpers, per ticket against `seed-floor`:** the same on 7 (g04 to g07, g09, g10, g15),
  better on g01 and g12, worse in both runs on g13 and g14, worse in the one generated run on
  g02 and g03, slightly worse on g08 and g11. The controls hold (g09, g10: nothing more was
  hidden, same scores). For half the tickets the class's own tests added nothing to the
  helpers called.
- **Data blocks:** worse on g02, g03, g11, g12, g13, g14; the rest the same. The entry is
  built by code from the base entry, so losing the class's entries costs more here than on
  the helpers, which the model chooses.
- Read: a sibling class is enough for a valid test in the suite's style; the class's own
  tests are worth about 0.09 of helper recall and 0.12 of data-block recall. The real
  no-template measure is the `area` level (not run).

**`cold-class`, what is missed (2026-11-16, free: the four scripts, `.scratch/cc-*.log`).**
- Helpers: 57 missed in 22 runs, and **23 of them are the reference class's own helpers**
  (`far`): the new test sits in a sibling class and cannot call them. That is the distortion
  expected from this level, and it accounts for most of the fall from 0.47 to 0.38: against
  what was reachable, 10 of 26 runs pass (warm: 9 of 29). So with the class's tests gone the
  tool calls the framework's members about as well as before.
- Data blocks: 79 missed in 15 runs; a whole seed section 27, custom keys 20, a whole
  expectation 15. Five runs have no entry at all where the reference has one (two in the
  warm right-template run), with a template that has one in all five: the no-data test is
  chosen more often without the class's entries.

**How changes are guarded from here (the human's point, 2026-11-16: don't tune against the
result).** The golden set, warm or cold, is for measuring and diagnosing. No change is
derived from single tickets' misses (the class-habit floor proposed after `extent.py` was
dropped for that reason, and because it needs neighbours). Before a run that tests something,
its prediction is written here. A change is kept only after the held-out set agrees (the
human's tickets that still have a test, mostly one area; looked at once, yes or no), and the
blind try (tickets with no test yet, with and without neighbours) is the last test. The seed
floor was found and judged on the golden set, so it is on that footing too.

**Predictions, written before the results (2026-11-16).**
- `cold-area` (running; every test file of the reference's folder removed, 42 to 4,098 tests
  a ticket), against `cold-class`: all generated runs still pass the validators; more runs
  fail to generate (4 of 30 in `cold-class`; expect 4 to 7); helpers mean recall falls from
  0.38 to about 0.25 to 0.35; data blocks from 0.65 to about 0.45 to 0.60; the four tickets
  whose folder holds half the suite (g04, g11, g12, g13) fall most; more new modules than
  methods. If helpers stay near 0.38, neighbours in the folder matter as little as the
  class's own tests did.
- `right-steps` (next; `eval.oracle_template` and `eval.oracle_steps` both on, against
  `right-template`: helpers 0.56, data blocks 0.75): if the generator can use a given choice,
  helpers mean recall rises to 0.85 or more and data blocks rise a little (the expectation
  section follows the check on g13). Helpers under about 0.75 would mean it doesn't make the
  calls even when told which: the one-shot writing is the limit, not the choice. No rise in
  data blocks would mean the data side needs its own fix. g01 fails on the context budget
  again (14 tickets in practice).

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
