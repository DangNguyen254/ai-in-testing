# Prompt: step-level ground truth for the golden tickets

Every method so far was scored by how many of the reference's calls the output makes, which
can't say which step of the draft went wrong, and it sees calls only (the design review,
2026-11-17: field writes, setup and data-driven branches are invisible to it). This asks a
session that reads the real suite to write, for each golden ticket and each line of its
draft, what the reference test really does for that line, in a file code can score against.

For a Claude Code session (Sonnet or Haiku) in the shared workspace. Paste everything between
the lines, unchanged.

---

```text
You are writing ground truth for a test-generation tool: for each of 15 tickets, what the
test a person really wrote does for each line of the draft the tool works from. Work
read-only, except for the two report files named below. Don't run anything, don't call a
model, don't open the network.

The workspace: ai-prj (the tool), the real test suite (the folder t2t-private/company.yaml
names as the repo; called <repo> below), and t2t-private.

Inputs, in t2t-private/golden.json: 15 pairs (g01 to g15), each with "tests" (the reference
test: path::Class::test) and "draft_file" (the reviewed draft: intent, preconditions, steps,
expected_outcome). Use the draft's "primary" entry. Label its lines exactly like this:
preconditions P1, P2, ... in order; steps S1, S2, ...; the expected outcome E.

For each pair, read the reference test, its data entry (the JSON file next to the test file;
the entry whose id field equals the test id), its class's setup and teardown, its base
classes' setup, and every helper it calls. Then, for every draft line, list what the
reference does for it, as rows:
- call: a call in the test body, as written ("self.nav.x.y.open", "self.verify_targets").
- write: a page field set by assignment, as written ("self.nav.x.editor.name").
- setup: done by setup, a fixture or a decorator, not the test body (name the method).
- data: comes from the data entry (the key path, two levels: "policy.rules").
- check: an assertion or validation call that verifies the line (as written).
- inside: done inside a helper the test calls (name the helper and the call inside it).
- none: the reference doesn't do this line at all.
A line may have several rows. Then list, separately, what the reference does that NO draft
line asks for (rows of the same kinds), and say for each whether it is routine for the class
(most of its tests do it) or specific to this test.

Rules:
- Rows as written in the code, with "self." kept for calls and writes.
- When a line is done by a helper, give the helper call as "call" and what it does inside as
  "inside" rows.
- Say "unclear" in the note when the draft line is too vague to map.

Write:
1. t2t-private/output/step-truth.json, exactly this shape:
   {"pairs": {"g01": {"lines": {"P1": [{"kind": "...", "what": "...", "note": "..."}], ...},
                      "unasked": [{"kind": "...", "what": "...", "routine": true}]}, ...}}
2. t2t-private/output/step-truth.md: the same, readable, with reasons.

Then reply in the chat with ONLY counts, no names of classes, helpers, files, keys, values,
tickets or features:
- per pair (g-number only): lines in the draft; rows by kind (call / write / setup / data /
  check / inside / none); unasked rows, routine and specific;
- totals over the 15;
- how many draft lines you marked unclear.
```

---

## When the reply comes

`.scratch/step_truth_score.py` (written when the file exists) scores the kept outputs, the
planner's plans and the picks line by line against it, including writes and setup, and
splits each method's misses by draft line kind. It also says how much of a reference is
reachable from the draft at all (the "unasked" rows).
