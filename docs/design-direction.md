# Design direction: what was decided on 2026-11-16, why, and what to do next

*Written 2026-11-16 for whoever continues this work, a later session on another model
included. It holds the reasoning, not the numbers: every number is in
`docs/design-step-status.md`, the working rules are in `CLAUDE.md`. Read the status doc's
"Start here" first, then this. Names nothing from the real suite.*

If something here disagrees with a later entry in the status doc, the status doc is right:
this file is the thinking as of one day, and two runs were still going when it was written.

## 1. The goal, as the human stated it

A tool that writes tests in the suite's, the team's and the codebase's style, **also when
there is no similar test or area to copy from**. A completely new test must work.

This changes what counts as progress. Until this day the work measured how well the tool
reproduces a reference test when neighbours of that test are in the suite. That is the easier
job. A change that only helps when a neighbour exists is not progress toward the goal.

## 2. What the tool is today, in one sentence

A **template adapter**: code picks an area, a class, a template test and a base data entry by
word overlap, and the model edits that template in one shot. The validators, the catalog
check, the entry builder and the sandbox around it are sound and are the real value built so
far (validators pass on every generated run, invented names are near zero).

## 3. What the evidence says (each line is one measurement, see the status doc)

| Finding | From |
|---|---|
| A stronger model with the same context writes the same test | the Sonnet-generate run |
| Adding knowledge to the context changed nothing, five times: guides, glossary, member cards, a step plan, a stronger model | the trial and the design step |
| Seven placement rules each traded one ticket for another | the placement replays |
| Giving the right template fixes placement on four tickets, lifts helpers a little, leaves data blocks as they are | `right-template` |
| With the right template, half of what is still missed was in the output's own class, a quarter elsewhere in the suite, a fifth nowhere else | the miss scripts |
| About one item in ten of a reference test comes from outside the ticket and the suite; the class is clear from the ticket on 5 of 15 | the derivability audit |
| The drafts keep everything the ticket states | audit follow-up 1 |
| On ticket-stated steps the tool never skips: it takes another route (7 of 11) or a weaker one (4) | audit follow-up 2 |
| Most missed data blocks follow from the test doing less: no backend check, no data read | `c3_kinds.py`, `extent.py` |
| Without the class's tests the output is still valid and in style; the tool attaches to a sibling class; helpers hold, data blocks fall | `cold-class` |

Read together:

1. **The input is not the main limit** on helpers and data. Tickets limit placement only.
2. **The model is not the limit** either, given what it is shown.
3. **The loss is in how generation works**: the decisions that need understanding (where the
   test goes, which test it resembles, which member does a step) are made by word-overlap
   code before the model sees anything, and the model gets one fixed context and one shot
   with an instruction to follow the template.
4. **Helper choice already comes from the framework, not the neighbour** (it survives the
   class's tests being hidden). **Data is what the neighbour really supplies.**

## 4. Decisions made, and the reason for each

| # | Decision | Why |
|---|---|---|
| 1 | The no-template case is the measure that matters | the goal (section 1) |
| 2 | **Don't tune against the result.** The golden set is for measuring and diagnosing. No change is derived from single tickets' misses and scored on the same tickets | that is how seven placement rules went; the human raised it again when a class-habit floor was proposed from two tickets |
| 3 | Write the prediction before the run | so a result can't be explained into fitting afterwards |
| 4 | Three kinds of tickets, three uses: golden (warm and cold) to diagnose; the held-out set (the human's tickets that have a test, mostly one area) to confirm, looked at once; the blind try (tickets with no test yet, with and without neighbours) as the last test | each set stays useful only for its use; a held-out set that is opened for diagnosis becomes a second golden set |
| 5 | Prefer diagnostics that give a stage the right answer over rules that patch a miss | `right-template` settled in one run what seven rules couldn't, and fitted nothing |
| 6 | No more context hints, no more placement rules, no stronger generation model | each was measured and moved nothing |
| 7 | The class-habit floor (the new test must have an entry or a backend check when its class's tests do) was **dropped** | it was fitted to two tickets, and it needs neighbours, so it does nothing for the goal |
| 8 | The seed floor stays on so the yardstick doesn't shift, but counts as unproven | it was found and judged on the golden set; its test is the held-out set |
| 9 | D6 (the QE names the nearest test) is justified for placement | it came from a diagnostic, not a fitted rule; it does nothing without a neighbour, so it is a convenience, not the direction |
| 10 | The direction for generation is **compose from the framework, don't adapt a neighbour** (section 5) | findings 3 and 4 above, and the goal |
| 11 | The investigator stays off, not alongside the planning step; its tools are reused | two exploring loops per ticket, and the first one's output is something the second can fetch |

## 5. The direction: compose, don't adapt

Not built. Agreed in discussion as the direction to follow; it rests on the assumptions in
section 6, two of which were being measured when this was written.

Generation becomes small steps, each checked by code, with the framework as the source:

| Step | Who | What | Checked by code |
|---|---|---|---|
| 1. Scaffold | code | the class shell, imports, setup: from the named nearest test if the QE gave one, else a neighbour, else the suite's most common shell for that kind of test | mostly exists |
| 2. Plan | the model, with lookups | for each draft line, the member that does it, in order; where nothing fits, a marked gap | every member exists (catalog); every draft line has a call, a check, a seed or a gap; kinds match; cited evidence is in the tool log |
| 3. Data needs | code | from the planned calls: the keys those members read, and an expectation section when a backend check is planned | derived, not guessed |
| 4. Write | the model | code from the plan | the test calls every planned member, else repair |
| 5. Validate | code | as today | as today |

**The planning step (step 2) in detail.**
- Input: the reviewed draft as numbered lines (preconditions, steps, expected outcome), the
  scaffold, and any similar tests the cheap fixed search found as starting points.
- Tools, read-only over the index (the investigator's, which exist): list a class's or page's
  members; open one member; which tests use a member and what they call around it; read a
  test's data entry; search. No shell, no file access outside the index, no execution.
- Output: a plan, not code. One row per draft line: `call` (member), `check` (member),
  `seed` (data, no call) or `gap` (what is missing, and the closest thing that exists, named
  as not equivalent). Each row carries a short note of what was read that led to the choice.
- It is the same kind of loop as a coding agent, with the limits made by code instead of by a
  prompt: fixed tools, nothing writable, a budget, one structured output.
- Two nested loops, both capped from config. **Turns** (inner): the model asks for lookups or
  returns the plan. **Rounds** (outer): code checks the plan and sends back the rows that
  fail. One budget shared across rounds, not a fresh one each: the first round gets the full
  turn budget, later rounds a small one (they only fix named rows), with a total cap over all.
- After the round cap: a row naming a member that doesn't exist becomes a gap (and is the
  input the missing-piece proposals take); a draft line with no row becomes a gap marked "not
  planned" on the reviewer's checklist; a plan that is unusable as a whole stops the run with
  a clear status and no test is written.
- **Counters, recorded for every run and shown in the golden report**: turns used of the
  budget; rounds used of the cap; how it stopped (`done`, `turn budget`, `round cap`);
  **near cap** (within one turn or one round of a limit); which kind of row was sent back;
  actions per turn and how many outputs were cut for size. Two rules written in advance: if
  more than about a third of runs hit or nearly hit a cap, the fix is in the tools or the plan
  format, not a higher cap; a run that stops on a cap is never scored as if it finished.

**Why this is not the step plan that already failed.** That one chose from 60 cards ranked by
word overlap around the template, nothing checked that the generated test called what was
planned, and it covered actions only. This one can read the framework, is enforced in step 4,
covers checks and data, and treats a gap as a valid result. Today's prompt says "use the
closest existing call"; that rule is where wrong-member substitutions come from and it goes.

**What stays:** indexing and the catalog, validators, repair, sandbox, entries assembled by
code, proposals for missing members. **What goes or shrinks:** the template as skeleton, the
placement heuristics, guides and glossary in the generation context unless an ablation shows
they help, the "closest call" rule.

**Known costs and risks.** More model calls per ticket (a worst case near 14 against 4 today;
the investigator cost about 2.5 times a plain run on the stand-in). The planning step is a
bounded agent at generation time: close to agent 1 moved after the draft and returning a plan,
but the human approves the change to the four-agent rule before it is built. Data for a new
area is the hard part: with no base entry there is nowhere to copy seed values from, so expect
marked gaps there. It is weeks of work, built beside the current path and compared.

## 6. The assumptions, and what to do when each turns out true or false

| # | Assumption | Tested by | If true | If false |
|---|---|---|---|---|
| 1 | Given the right members, the generator writes a correct test. **Measured the same night: holds** (helper recall 0.56 to 0.85, 20 of 28 runs pass against 8 of 27; what still misses are members that don't exist where the test is written) | `right-steps` (`eval.oracle_template` + `eval.oracle_steps`, against `right-template`) | step 4 works as designed; the effort goes into step 2 | the writing itself is the limit: redesign step 4 first (smaller writing steps, code writing the calls from the plan), before any planner |
| 2 | A model that can look things up finds the right members. **Measured 2026-11-17: holds on six tickets** (helper recall 0.69 against the tool's 0.42 with neighbours, better on four of six; with no template 6 of 12 reachable calls against 1 of 24) | the agent upper bound (`docs/agent-upper-bound-prompt.md`) | build the planning step | the knowledge isn't findable in the suite: the input must carry the steps (the QE's own test case as input), with marked gaps |
| 3 | "Right member" means the team's usual one, not any that works | the verdict sheet, column F | the planner needs usage counts per member as evidence | C2 overstates the helper gap: loosen it, and put the effort into checks and data |
| 4 | Style holds without a neighbour | `cold-area`; `cold-class` says yes at class level | the scaffold step only needs a suite-wide default | style itself needs a source: suite-wide conventions derived by code, before anything else |
| 5 | What an entry must hold can be derived from the calls the test makes | **measured the same day, mostly false** (`.scratch/framework_probe.py`): 60% of a reference entry's paths are seed sections no call names, 31% an expectation section whose presence (not content) follows from a planned check, 9% custom keys | step 3 works without a neighbour | **this is the case:** the plan needs `seed` rows that say where each section comes from (an entry elsewhere in the suite, the draft's preconditions, or a marked gap); code derives only the expectation's presence and helper-read keys |

The predictions for `cold-area` and `right-steps` were written in the status doc before their
results. Read the results against those, not against a story made afterwards.

**Added the same evening, from `cold-area` and two free checks (see the status doc):**
- With a folder's tests removed, every output went to another folder and helper recall was
  0.00: the tool adapts a wrong neighbour instead of falling back to the framework. Only 24
  of the 112 helpers it missed are used by any test left: the knowledge is in the framework's
  code alone. This is the baseline for the goal.
- Placement has no "none of these fits" outcome. A new area needs one.
- The reference tests mostly call helpers of their own class line, not pages directly, so a
  new area has no helper layer to call: the composed test calls pages directly or the helpers
  are proposed as well.
- The catalog resolves about two thirds of the references' calls; the plan's existence check
  needs an "unknown" verdict for the rest.

## 7. What to do next, in order

**Phase A, finish measuring (nothing here tunes the tool):**
1. Read `cold-area` against its prediction. Run the free scripts on its report.
2. Run `right-steps` (one golden run at a time: the container's limit is 8 GiB and a run
   uses up to 4.9). Read it against its prediction.
3. The human fills `docs/verdict-sheet.md` for 15 outputs.
4. The agent upper bound on six tickets, in a **new** session that has never read the
   reference tests. Write `.scratch/score_agent.py` when the outputs exist.
5. Still open from the original plan: ablate the always-on context pieces (guides, glossary
   in generation, helper code). One ticket overflows the context budget under a pinned
   template, which points at them.

**Phase B, one design decision (made 2026-11-17: build the planning step; the decision, the
first slice and its prediction are in the status doc, "Phase B").** Use the table in section 6. Write the decision and its
predicted effect in the status doc before building.

**Phase C, build and confirm.** Behind a switch, off by default, developed on the stand-in.
Then the golden set warm and cold against the written prediction; then the held-out set once,
also cold; then the blind try, judged by `docs/blind-try-rubric.md`.

Ask the human before: any paid run (say about how much), any change to the agent rule or a
hard constraint, a new dependency, a push.

## 8. Mistakes made on this day, so they aren't repeated

- **Proposing a rule from two tickets** (the class-habit floor). The human caught it.
- **A suspicion stated as a likely cause**: that the prompt's "leave out what isn't read" rule
  explained the missing data blocks. A free script showed it covers under a quarter of them.
  Check with a free script before naming a cause.
- **Wrong statements about what exists**: "the draft is written from the ticket alone" (it
  also gets a vocabulary block); "a test without data should be allowed as a template" (that
  rule had been tried twice and removed). Read the status doc's history before proposing.
- **Reading a score without its distortion**: `cold-class` helper recall fell mostly because
  the reference class's own helpers are out of reach from a sibling class. Ask what a
  criterion can and cannot see at a new level before reading it.
- **A memory figure taken mid-run**, not at the peak, nearly led to two runs at once.
- **A private key name reached a saved log** through a failed run's error message. Mask error
  messages too, and check a log before quoting it.

## 9. Open questions

First answers 2026-11-17, set aside until the human's mentor has been asked (the status doc,
"Phase B"): helpers first and proposed by the tool; seed data with no source is a flagged
guess made of values that exist. The rule on touching an existing helper is open.

- Whether "another route with the same effect" passes review (the verdict sheet).
- Why two to four runs of thirty fail to generate (the code doesn't parse); needs one
  `--debug-log` run and a masked look.
- Whether `area` level is cold enough: it removes test files directly in the reference's
  folder; subfolders and non-test helper modules stay.
- How the planner should treat granularity: one draft line that needs three calls, one helper
  that covers three lines.
- Whether the held-out set, being mostly one area, can confirm anything about other areas
  (it can show overfitting; running it cold partly makes up for the narrowness).

## 10. The day in short (for someone who knows only the project's aim)

- **Aim:** an AI tool that turns a ticket into a test written the way the team writes tests,
  even when no similar test exists to copy.
- **Problem going in:** about ten changes over two weeks had moved no measure, and it was
  unclear whether the fault was the tickets, the model or the design.
- **How it was approached:** instead of trying another fix, each stage was given the right
  answer in turn, or had something taken away, to see what was left. No fix was fitted to
  individual cases.
- **Found:** the tickets are mostly fine (they only fail to say where a test belongs); a
  stronger model doesn't help; the knowledge the tool needs is mostly present and not used.
- **Found:** today's tool works by editing a similar existing test. It stays valid and in
  style without one, but it does less: fewer checks, less test data.
- **Found:** part of the measured gap is the yardstick: the tool often does a step in a
  different valid way, and the score counts that as a miss. A person's review is needed to
  settle how much.
- **Decided:** stop adding hints and special-case rules. Measure against the no-example case,
  write predictions before runs, and confirm any change on tickets never looked at.
- **Direction agreed:** rebuild generation so the tool plans a test from the framework's own
  building blocks, looking things up as it goes, with every choice checked by code and
  missing pieces marked honestly instead of guessed.
- **Still running at the end of the day:** two measurements that decide whether that
  direction holds; a review sheet and a final-test rubric were prepared for the human.
