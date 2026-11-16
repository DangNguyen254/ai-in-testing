# Prompt: the agent upper bound, by a fresh Claude Code session

Phase A, step 4 of the plan in `docs/design-step-status.md` (step 5 of
`docs/design-step-plan.md`, never run). The tool gives its model one fixed context and one
shot. This asks what the same model writes for the same ticket when it can **look things up**
in the suite. Scored with the same criteria, it brackets any generation design from above:

| With `right-steps` | And this | Then |
|---|---|---|
| given the calls, the generator writes the test | the agent finds the calls | generation that chooses members by looking them up is worth building |
| given the calls, the generator writes the test | the agent doesn't find them | the knowledge isn't findable; the input must carry it |
| given the calls, the generator still doesn't | either | one-shot writing is the limit, whatever the choice |

## Before pasting

- **A new session.** Never the one that did the derivability audit or the error analysis: those
  read the reference tests. One session per ticket is cleanest; one session for all six is
  acceptable if it never opens the real suite folder.
- **The same model as the tool's generate step** (Haiku), so the only difference is the tools.
- **The copies must exist and be current.** Each ticket's copy of the suite without its
  reference is at `/root/work/t2t-state/t2t_cache/eval/loo/<pair id>` after a warm golden run
  (the `right-steps` run rebuilds them; a cold run uses other ids and leaves them alone).
- **Six tickets, chosen before any output is read**, one per kind of miss seen under the right
  template: g04 (the class shows the helper), g06 (it is elsewhere in the suite), g10 (no
  template), g13 (the backend check dropped), g15 (the tool takes another route), and g05 as a
  control the tool already gets right.
- Placement is given (the file and class), so this measures the choice of steps and data, not
  where the test goes.
- Scoring: `.scratch/score_agent.py` (to be written when the outputs exist) turns each output
  file into the tool's own result shape and scores it with `eval/reference.py`, so C2, C3, C4
  and C7 mean the same as in the golden reports.

Paste it once per ticket, with the pair id in the first line.

---

```text
PAIR = <g04 | g05 | g06 | g10 | g13 | g15>

You are writing one automated test for an existing pytest suite, from a ticket. A Quality
Engineer will review it. Work the way a careful new team member would: read how this suite
tests things, then write a test that fits it.

Where things are:
- SUITE = /root/work/t2t-state/t2t_cache/eval/loo/PAIR : a copy of the suite. Read only.
  This is the ONLY copy of the suite you may open. Never open any other folder under
  /root/work that holds the suite, and never search outside SUITE: the other copy contains the
  answer.
- /root/work/t2t-private/golden.json : find the pair whose "id" is PAIR. Take from it ONLY:
  "ticket" (the ticket is <tickets_dir>/<ticket>.md), "draft_file" (the reviewed test-case
  draft: intent, preconditions, steps, expected outcome), and from "tests" ONLY the file path
  and the class name (the parts before the second "::"). Do not use the method name after it.
- Do not open anything under /root/work/t2t-private/output.

The task:
1. Read the ticket and the draft.
2. The new test goes in the file and class you took from "tests". If that class has no test
   left in SUITE, write a new test file next to it, with a class built like its neighbours.
3. Explore SUITE until you know how to write it: the class and its base classes, its setup,
   the page objects and helpers its tests use, how tests of this kind check the backend, and
   what their data entries hold (the JSON file next to a test file; the entry whose id field
   equals the test id). Budget: at most 30 tool calls (file reads and searches together).
   Stop exploring when you have enough.
4. Write the test and its data entry or entries, in the suite's own way:
   - use only classes, methods, properties, helpers and fixtures that exist in SUITE; if a
     step or check needs a member that doesn't exist, don't invent it and don't replace it
     with the closest one: list it under "missing";
   - do every step the draft states and check every outcome it states;
   - build the data entry the way the class's other entries are built.

Write exactly one file, /root/work/t2t-private/output/agent-bound/PAIR.json (create the
folder), with this shape and nothing else:

{
  "pair": "PAIR",
  "target_file": "<path of the test file, relative to SUITE>",
  "class_name": "<the class the test is in>",
  "new_file": false,
  "code": "<the new test method(s) only, as they would appear in the class; or the whole new
           module when new_file is true>",
  "data_entries": [ { "<the id field>": "<the pytest id>", "...": "..." } ],
  "missing": [ { "owner": "<class or page>", "name": "<member>", "needed_for": "<draft line>" } ],
  "tool_calls": <how many reads and searches you made>,
  "files_opened": <how many distinct files>
}

Rules: read only, except that one file. Don't run any test, and don't run the ticket2test
tool. In the chat, reply with exactly one line and nothing else:
  PAIR: done, <tool_calls> tool call(s), <files_opened> file(s), <number of entries> entr(ies), <number of missing> missing
No names of classes, helpers, files, keys, values, tickets or features, and no description of
the test.
```
