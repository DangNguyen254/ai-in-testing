# Prompt: judge the "missed" and "extra" calls (a corrected helper score)

The helper criterion (C2) counts a reference call as missed whenever the output doesn't make
that exact call, even when it does the same step another way, and it never looks at calls the
output makes that the reference doesn't. An audit on 2026-11-16 judged 7 of 11 such misses
equivalent. This asks a session that reads the real suite to judge every one, in a file code
can read, so the kept runs can be re-scored with equivalent routes counted.

For a Claude Code session (Sonnet or Haiku) in the shared workspace. Paste everything between
the lines, unchanged.

---

```text
You are judging a test-generation tool's outputs against the tests people really wrote. Work
read-only, except for the two report files named below. Don't run anything, don't call a
model, don't open the network.

The workspace: ai-prj (the tool), the real test suite (the folder t2t-private/company.yaml
names as the repo; called <repo> below), and t2t-private (the golden set and the outputs).

Inputs, in t2t-private:
- golden.json: 15 pairs (g01 to g15). Each names its reference test ("tests": path::Class::test)
  and its reviewed draft ("draft_file").
- Two golden runs, each a report.json with a "runs" list (pair_id, run, result, scores) and,
  per run, the kept output at the path in "kept" (generated.json holds the new test's code):
  output/golden/seed-floor-20261112T065503/report.json (the tool as it is)
  output/golden/right-template-20261113T091511/report.json (the tool given the right template)
  In each run, scores.missing_helpers lists the reference calls the output doesn't make, as
  "Class.member" (what the call resolves to) or as written when the tool couldn't resolve it.
- output/pick-eval/<pair>-r<n>.json: another method's choices: "picked" (draft line -> calls,
  as written without "self.") and "reference" (the reference's calls, as written).

For every pair, read the reference test (and its class, base classes and the helpers it calls
in <repo>), the draft, and then:

A. MISSED. For each reference call listed as missing in either report (or absent from
   "picked" in pick-eval), judge whether the output does that step another way:
   - equivalent: the output reaches the same result by another call or calls; a reviewer on
     the team would accept it. Name the call(s) it uses instead.
   - weaker: it does the step, but checks or does less (another page, no backend check, a
     partial setup).
   - absent: the output doesn't do the step at all.
   - unsure: you can't tell without running it.
B. EXTRA. For each call the output makes (or picks) that the reference doesn't, judge:
   - needed: the draft asks for it and the reference does it another way or in setup.
   - harmless: unnecessary but not wrong.
   - wrong: it does something the draft doesn't ask for, or would break the test.
   Judge each distinct call once per pair and source, not once per run.

Rules:
- Ground every verdict in code you read: the helper's body, the page member, what setup does.
- When the same pair has the same miss in several runs, judge it once and list the runs.

Write two files:
1. t2t-private/output/equivalence.json, exactly this shape, so code can re-score:
   {"verdicts": [
     {"source": "seed-floor" | "right-template" | "pick-eval", "pair": "g04", "runs": [1, 2],
      "kind": "missed" | "extra", "call": "<the call as listed in the input>",
      "verdict": "equivalent" | "weaker" | "absent" | "unsure" | "needed" | "harmless" | "wrong",
      "instead": "<for equivalent: the output's call(s), as written; else empty>"}
   ]}
2. t2t-private/output/equivalence.md: the same with your reasons, names and code allowed.

Then reply in the chat with ONLY counts, no names of classes, helpers, files, keys, values,
tickets or features:
- per source: missed items equivalent / weaker / absent / unsure; extra items needed /
  harmless / wrong;
- per pair (g-number only): the same counts on one line;
- how many items took reading a helper's body to decide.
```

---

## When the reply comes

`.scratch/equivalence_rescore.py` (written when the file exists) re-scores the two reports
and the picks with `equivalent` counted as made, and prints both helper scores side by side.
The verdicts are a model's reading: they correct the measure's blind spot, they don't replace
a person's verdict.
