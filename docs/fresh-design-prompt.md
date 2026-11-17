# Prompt: a fresh design, from a session that knows only the real suite

The design review (`docs/design-review-prompt.md`) asks a session that reads our design what
is wrong with it; its answer is anchored on our choices. This asks a different session, one
that **never reads this project**, how it would build the tool, knowing only the real suite.
Its design is then compared with ours, stage by stage.

Run it in a **new** session, opened on the real suite's folder, not the one doing the review.
It must not open `ai-prj` or `t2t-private`. Two outputs: a full answer with names, kept
private, and a names-free reply to relay.

Paste everything between the lines, unchanged.

---

```text
Investigate and understand this repository: a pytest test suite with a custom framework on
top, data-driven (each test file has a JSON data file).

Then: you are given a project to build an agent tool that drafts tests for this repository
from tickets. The input is a Jira ticket. Tickets are of every kind: bugs, but also stories,
tasks and test plans for new features; many lack information. The output is a test pair, the
Python test and its JSON data entry, for a Quality Engineer to review before it is run.
How would you do it? Design the architecture: the stages, what each stage reads, what decides
each choice, where a model is used and where code is, and how you would know it works.

Constraints of the project you would have to respect:
- The tool may read this repository but never change it, and never runs tests against real
  systems (a person runs them). A model call is allowed, but the tool must also work with a
  small, cheap model for most steps.
- A ticket with too little information must give "not enough information, here is what is
  missing", never a guess.
- The new test must fit how the team writes tests here: its style, its helpers, its data.
  This must hold also for a feature that has no test yet.

Rules:
- Do not open, list or search these folders: ai-prj, t2t-private, or anything outside this
  repository. Read only; don't edit or run anything.
- Ground every design choice in this repository: say what you saw and on how many files,
  tests or classes ("tests here do X: 34 of 40 checked"). Separate what you counted from what
  you judge.
- Before the design, write what a new test here is made of, as you found it: where a test's
  steps come from, how a class and its helpers relate, where its data comes from, what makes
  it hard to write a new one without copying a neighbour.
- Say which part of your design you are least sure of, and the cheapest experiment that would
  tell you whether it works.

Write the full answer, with names and examples, to t2t-private/output/fresh-design.md
(the only place outside this repository you may touch, and only to write this file; create
the folder if needed).

Then reply in the chat with ONLY this, no names of classes, helpers, files, folders, keys,
values, tickets or features, and no quotes from the code:
1. What a new test here is made of: five lines at most, with the counts.
2. Your stages, one line each: what it does, model or code, what it reads.
3. The one or two choices you think matter most, and why, in general words.
4. What you are least sure of, and the experiment that would settle it.
```

---

## When the reply comes

Compare it with our pipeline stage by stage (`CLAUDE.md`, "Pipeline", and
`docs/design-direction.md`): which stages match, which differ, and for each difference what
the fresh design's grounding says. A difference is a lead to check on the golden set before
it changes anything, like the review's findings.
