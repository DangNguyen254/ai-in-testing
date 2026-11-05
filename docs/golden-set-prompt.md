# Prompt: build the golden set with Claude Code

Design step 1 needs 10–15 real tickets, each with the test a person wrote for it
(`docs/golden-set.md`). This prompt has a Claude Code session inside the private environment
pick and check them, find near-twin tests to hide, draft each ticket once, and write the pair-set
file. A person then reviews the drafts and the choices before the first `golden` run.

Paste it as is: it finds its paths itself. It writes only in the private folder and changes
nothing in the suite.

---

```text
You are building an evaluation set for a tool that turns bug tickets into tests for a large
pytest suite. Each entry pairs a real ticket with the test a person actually wrote for it (the
reference). The tool will later be run on each ticket with the reference hidden and scored
against it, so a wrong pair makes every later score wrong. Be strict; fewer good pairs beat many
doubtful ones. Read only, except the files named under "Write".

Paths. Work them out first and say them back in one line:
- PRIVATE = /root/work/t2t-private
- TOOL = /root/work/ai-prj   (run the tool from here: `uv run ticket2test ...`; source
  PRIVATE/env.sh first)
- REPO = the "repo_root" in the one map.json under PRIVATE/output/map/ (the target suite; read
  only)
- TICKETS = the pasted-ticket folder: paths.tickets_dir in PRIVATE/company.yaml (each ticket is
  <ticket id>.md)
- CANDIDATES = PRIVATE/output/mined-pairs.json (ticket <-> test pairs mined from skips that cite
  a ticket id; a starting point, not truth)

1. Candidates. Read CANDIDATES. Add others you find: tests whose skip reason, docstring or
   comment cites a ticket id that has a pasted ticket in TICKETS, and tests added by a commit
   whose message cites one (git log in REPO, read only).

2. Check each candidate pair. Read the ticket (TICKETS/<id>.md) and the test (and its data
   entries: the JSON file next to the test file, entries matched by their id field). Keep a pair
   only if the test checks what the ticket describes (its steps and expected result), not just
   the same area. For each pair write one line of evidence: what in the test matches what in the
   ticket. The ticket's status doesn't matter (open, fixed or closed are all fine), and neither
   does a skip that cites the ticket: a test skipped because its bug is still open is a good
   reference (the person wrote its steps, data and checks). Reject a pair only when the ticket
   is vague (no steps or no expected result, or a triage, deployment or investigation item), the
   test was clearly written for a different behaviour, the test is obsolete (skipped for a reason
   unrelated to the ticket, such as a removed feature), or the test may have been produced by
   this tool (ask the person; don't guess).

3. Choose 10-15 pairs from 2-3 different areas (folders of the suite), not all from one. Prefer
   a mix: a new test in an existing class, a test with variants (parametrized), a test with a
   large data entry, a plain one. If fewer than 10 good pairs exist with pasted tickets, list the
   ticket ids that would complete the set (good tests whose ticket isn't pasted yet), so the
   person can paste them; don't invent ticket text.

4. Near-twins. For each chosen pair, find other tests or whole files the tool could copy the
   answer from: an older or newer class for the same feature, a test differing only in one value.
   List them; they go into "hide". Don't hide whole areas.

5. Drafts. For each chosen pair run, from TOOL:
       uv run ticket2test run <ticket id>
   (without --continue). It writes PRIVATE/output/drafts/<ticket id>.drafts.json. Don't edit the
   drafts; the person reviews them.

6. Write PRIVATE/golden.json, exactly in this shape (absolute paths):
   {
     "name": "golden",
     "repo_path": "<REPO>",
     "ticket_source": "paste",
     "tickets_dir": "<TICKETS>",
     "ground_truth": "tests",
     "generation": true,
     "pairs": [
       {
         "id": "g01",
         "ticket": "<ticket id, the .md file name without .md>",
         "tests": ["<path relative to REPO>::<Class>::<test method>"],
         "draft_file": "<PRIVATE>/output/drafts/<ticket id>.drafts.json",
         "hide": ["<path relative to REPO>.py or <path>::<Class>::<test>", "..."]
       }
     ]
   }
   "tests" lists only the reference test(s) the ticket produced; a parametrized test is one
   entry. Check every path exists in REPO.

7. Write PRIVATE/golden-review.md for the person: per pair, the ticket id, the area folder, the
   reference test, the one-line evidence, the hidden near-twins and why, and the draft file to
   review. Then the rejected candidates with the reason, and the tickets to paste if the set is
   short.

Write: only PRIVATE/golden.json, PRIVATE/golden-review.md, and the drafts the tool writes.
Never change REPO or anything in TOOL. Don't copy secrets, tokens or credentials into any file.
When you report back in the chat, give counts and reasons only (how many pairs, areas, rejected
and why); no names from the suite.
```
