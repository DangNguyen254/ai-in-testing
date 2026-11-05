# Prompt: error analysis of a golden run, by Claude Code

Design step 2 (`docs/design-step-plan.md`): before anything is fixed, every generated test of a
golden run is read next to the test a person wrote for the same ticket, the first thing that is
wrong is written down, and those notes are grouped and counted. The biggest group is what gets
changed first.

This prompt has a Claude Code session do the reading. It fills the run's `open-coding.md` and
`c6.csv`, and writes `failure-modes.md`. Its C6 answers are a model's judgement: spot-check a
few against your own reading before relying on them (`golden-report --c6` merges them).

Paste it as is, after naming the run folder in the first line.

---

```text
RUN = /root/work/t2t-private/output/golden/<the run's folder>

You are reviewing the output of a tool that writes pytest tests from bug tickets. For each
ticket, a person already wrote the real test (the reference). The tool ran without seeing it,
several times per ticket. Your job is to read what the tool wrote next to the reference and say,
precisely and in plain words, what is wrong. You change no code and fix nothing; you write notes.
Read only, except the three files under "Write".

Find, and say back in one line before you start:
- RUN/report.json: every run (pair_id, run number, status, the scores, and "kept": the folder of
  the run's output, with its generated.json: the generated code, data entries, and notes).
- The golden pair set the run used: /root/work/t2t-private/golden.json (per pair: the ticket,
  the reference test as path::Class::method, its draft file).
- REPO = "repo_path" in golden.json: the suite, with the reference tests and their data files
  (read only).
- The draft of each ticket (its "draft_file"): the expected outcome the tool worked from.

For every ticket (pair):
1. Read the reference test and its data entry (the JSON file next to the test file, the entry
   whose id field equals the test id), and the draft's expected outcome.
2. Read run 1's generated test: only the new test method(s) (the ids in "new_test_ids" of
   generated.json, or all tests if there is no such list) and their new data entries.
3. Write the FIRST thing that is wrong, in one sentence of your own words, concrete enough that
   someone could act on it. Check in this order and stop at the first that fails:
   a. placement: is it in the reference's file and class? (a new file when the reference is a
      method in an existing class counts as wrong)
   b. the scenario: does it do what the ticket asks (same setup, same action), or something else?
   c. the checks: does it check the draft's expected outcome? which check is missing or wrong?
   d. the helpers: does it call the helpers the reference calls, or re-implement them, or call
      ones that don't fit?
   e. the data: which block or key the reference entry has that the new entry lacks, or which
      value is wrong or made up?
   f. anything else (style, waits, names) only if a-e are all fine.
   Then add, in a second short sentence, the most likely reason if the files show it (for
   example: "the context had the right class but the tool chose a new module"; "the template
   test it copied lacks that block"). Say "reason unclear" otherwise; don't guess.
4. Compare with runs 2 and 3 of the same ticket: same first failure, or different? Note it in a
   few words.
5. C6, for every generated run of the ticket: "yes" if its checks would catch it when the
   draft's expected outcome is not met, else "no". An implicit check (an action that fails when
   the outcome is wrong) counts as yes. A check of the wrong thing is no.

Then group: put the first failures into fewer than 10 failure modes (your own names, each a
short phrase), count tickets per mode, and order by count. For each mode, name the tickets in
it, the likely reasons you saw most often, and one sentence on what kind of change would address
it (not a fix, a direction).

Write:
- RUN/open-coding.md: fill each run's "first failure:" line for run 1 of every ticket (the
  sentence, then the reason), and for runs 2 and 3 write "same as r1" or the difference.
- RUN/c6.csv: the last column, "yes" or "no", for every generated run. Keep the other columns
  and the header exactly as they are.
- RUN/failure-modes.md: the modes, ordered by count, as described above.

Rules: read only, except those three files. Don't copy secrets, tokens or credentials into them.
When you report back in the chat, give the modes with their counts and the C6 totals only; no
names of classes, helpers, files, values or tickets from the suite.
```
