# Prompt: a design review by a session that can read everything

For a Claude Code session (Sonnet) in the shared workspace, which holds this project
(`ai-prj`), the real suite (`<repo>`) and the private folder (`t2t-private`). The question is
not "is the code good" but **which of the design's beliefs about the real suite are wrong**:
the project was built on a stand-in made from descriptions of the suite, and every stage
assumes something about how the suite's tests are written, placed and fed with data.

Two outputs. A full report with names, kept private, for the human. A short reply with no
names, which the human relays to the design session.

Paste everything between the lines into a new session, unchanged.

---

```text
You are reviewing the design of a tool, against the real codebase it is built for. Work
read-only. The workspace holds three folders:

- ai-prj: the tool. It turns a ticket into a draft test case, then into a pytest test plus its
  JSON data entry, for a Quality Engineer to review. Read first: ai-prj/CLAUDE.md (what the
  tool is, the pipeline, and "Target test-suite patterns": what the design believes the suite
  looks like), ai-prj/docs/design-direction.md, and the "Start here" block and the newest
  sections of ai-prj/docs/design-step-status.md (what was measured and tried).
- the real test suite the tool is built for (the folder t2t-private/company.yaml points at as
  the repo; it is called <repo> below).
- t2t-private: the tool's private config, the golden set (golden.json: 15 tickets, each with
  its reference test, the test a person really wrote) and the tool's outputs
  (output/golden/<run>/runs/<ticket>/r1/ holds what the tool wrote for a ticket).

What the design team needs: where the tool's picture of the suite, and the choices built on
it, don't match the real suite. They have measured that the tool writes valid tests that call
the wrong helpers (it adapts the nearest existing test, and a word search finds tests well but
helpers badly), that it can write the right test when given the right calls, and that a usage
table (what each class's tests call, counted by code) holds most of the right calls. They want
to know what they have not seen.

Rules:
- Read only. Don't edit, create or delete anything in the three folders, except the one
  report file below. Don't run the tool, any test, or anything that calls a model or the
  network. Reading git history of <repo> is fine.
- For every finding, say how you know: how many files, tests or classes you looked at, and
  whether it is checked (you counted it) or a judgement (you read some and concluded).
- Prefer checking a claim on 20 tests over describing one.

The questions:

Q1. The patterns. For each bullet of "Target test-suite patterns" in ai-prj/CLAUDE.md: holds,
    partly, or wrong in <repo>; what is actually the case; how many places you checked.

Q2. How a test is built. Pick 20 tests across at least 5 folders. For each: are its steps
    mostly calls to helpers of its own class or area base, or to page objects directly? Where
    does the work happen: the test body, setup or fixtures, decorators, the data entry driving
    branches inside helpers? The usage table only sees self calls written in the test body:
    what would it miss, and how often?

Q3. Placement. How does the team decide which file and class a new test goes in (by feature,
    page, test shape, owner, history)? Is "the class" the right unit to choose, or is it the
    file, the folder, or a base class?

Q4. Data. Take 10 of the golden tickets' reference entries. Where did each block come from:
    copied from a neighbour in the same file, from another file, written new, or produced by a
    helper or setup? Is "build the entry from the nearest existing entry" how the team works?

Q5. The tool against the reference. For 6 golden tickets, compare what the tool wrote (in the
    newest output/golden/seed-floor-* run, r1) with the reference test. For each difference,
    what belief in the tool's design led to it? Use the tool's code (ai-prj/src) to check how
    the choice was made, not only the output.

Q6. A new area. In the git history of <repo>, find 2 or 3 test files that were the first in
    their area. What did that first commit contain: helpers or page objects written with the
    test, a base class, data? What would the tool have needed to write it?

Q7. The yardstick. Are the 15 reference tests typical of how the team writes tests? Do the
    golden criteria (ai-prj/docs/golden-set.md: C2 helpers called, C3 data blocks) measure what
    a reviewer on the team would care about? What would a reviewer reject that they don't see?

Q8. Open. What should the team check that this list doesn't ask? Name at most three, each as a
    check they could run, not an opinion.

Write the full answers, with names, files and examples, to
t2t-private/output/design-review.md (create the folder if needed). That file stays private.

Then reply in the chat with ONLY this, no names of classes, helpers, files, folders, keys,
values, tickets or features, and no quotes from the code:

Q1: per bullet, its number and holds/partly/wrong, one line each, in general words.
Q2: counts out of 20 (helper-led / page-led / mixed; where the work happens; what the usage
    table would miss and how often).
Q3: the unit of placement in one line, and the evidence count.
Q4: counts out of 10 per source of a block.
Q5: per ticket (by its g-number), the design belief behind the main difference, in general
    words.
Q6: counts: of the first tests found, how many came with new helpers, page objects, a base
    class, data.
Q7: yes/partly/no for "typical" and for "the criteria measure what matters", one line each.
Q8: the three checks, in general words.
```

---

## When the reply comes

Read it against the design, not for agreement. A "wrong" in Q1 or a belief in Q5 is a lead:
it becomes a free check on the golden set before it changes anything (method points 1, 2 and
8 of `CLAUDE.md`). The full report stays in `t2t-private`; only the names-free reply comes to
the design session.
