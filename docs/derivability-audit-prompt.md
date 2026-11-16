# Prompt: can the reference tests be derived from their tickets? By Claude Code

A free check for the design step (`docs/design-step-status.md`). C2 and C3 score the tool
against the one test a person wrote. Nothing so far says how much of that test a tool could
know: what the ticket states, what the class's other tests show, what is somewhere in the
suite, and what only a QE knows. This audit counts it, per ticket.

How to read the reply:
- Most missed items are **outside** (bin 5): the tool is scored on knowledge it is never
  given. The fix is the input and the hand-over (the QE names the nearest test, marked gaps),
  not the pipeline.
- Most missed items are **findable** (bin 4): the suite has the answer and the fixed context
  doesn't reach it. A model that can look things up while generating is worth designing.
- Most missed items are in bins 1 to 3: the tool had what it needed and still left it out.
  The fault is in how generation uses its context.

The answers are a model's judgement: bins 4 and 5 are the soft ones. Spot-check two tickets
against your own reading before relying on the counts.

Paste it as is, after naming the run folder in the first line (the yardstick run,
`seed-floor`). It makes no model calls through the tool and changes nothing.

---

```text
RUN = /root/work/t2t-private/output/golden/<the seed-floor run's folder>

You are auditing a benchmark, not a tool. A tool writes pytest tests from tickets. For 15
tickets a person already wrote the real test (the reference), and the tool is scored on how
much of the reference it reproduces. Your job is to say, for each thing the reference test
does, where a writer who had NOT seen the reference could have learned it. You change no code
and fix nothing. Read only, except the one file under "Write".

Find, and say back in one line before you start:
- The golden pair set: /root/work/t2t-private/golden.json. Per pair: its id, "ticket" (the
  pasted ticket, <ticket>.md in "tickets_dir"), "tests" (the reference test as
  path::Class::method), "draft_file" (the reviewed draft the tool worked from), and "hide"
  (other tests or files the tool could not see).
- REPO = "repo_path" in golden.json: the suite (read only).
- RUN/report.json: every run with its pair id, run number, status and scores. The scores hold
  "missing_helpers" and "missing_blocks": what that run lacked from the reference.

For every pair:

1. Read the ticket and the draft (preconditions, steps, expected outcome). Then read the
   reference test and its data entry (the JSON file next to the test file, the entry whose id
   field equals the test id; for a parametrized test, the first case).

2. List the reference's ITEMS:
   - helpers: every distinct call the test body makes on the suite's own code: a page-object
     action or property reached from self, a helper of its class or a base class, a module
     function of the suite. Not Python built-ins, not the assertion methods themselves.
   - blocks: every key path of the data entry two levels deep (top-level key, and the keys
     directly under it; for a list of objects, the keys of its objects). Leave out the id
     field.

3. Put each item in exactly ONE bin, the first that fits:
   1 TICKET: the ticket's text states the action, state or value this item is there for.
   2 DRAFT: the ticket doesn't, but a line of the draft does.
   3 CLASS HABIT: neither states it, but at least half of the OTHER tests of the reference's
     class do the same thing (same call, or same block in their entries). Don't count the
     reference test or anything in the pair's "hide" list. If the class has no other test,
     this bin stays empty.
   4 FINDABLE: none of the above, but the suite shows it to someone who looks: you can point
     to a specific test, entry or page object, outside the reference test and outside the
     "hide" list, that makes it clear this item belongs to this scenario (for example another
     test of the same feature does it for the same purpose, or the page the ticket is about
     offers exactly this member). You must be able to name that evidence to yourself. A member
     that merely exists somewhere is not enough.
   5 OUTSIDE: nothing in the ticket, the draft or the rest of the suite leads to it. It comes
     from knowing the product or from a choice the test's author made (which user, which
     payload, an extra precondition, an extra check).
   When unsure between 4 and 5, choose 5.

4. Mark each item as MISSED when it is in "missing_helpers" or "missing_blocks" of EVERY
   generated run of that pair in RUN/report.json (match by meaning: the report writes a call
   as the class and member it resolves to, and a block as its key path). A pair whose runs
   all failed has no missed items; say so.

5. One more yes/no per pair: reading only the ticket and the draft, is it clear WHICH existing
   class the new test belongs in?

Write RUN/derivability.md: per pair, the items with their bin, the evidence for bins 3 and 4,
and the missed mark. This file stays private and may use the suite's names.

Report back in the chat with numbers only, in exactly this shape, and nothing else:

  pair | helpers by bin 1/2/3/4/5 | blocks by bin 1/2/3/4/5 | missed helpers by bin 1/2/3/4/5 | missed blocks by bin 1/2/3/4/5 | class clear (yes/no)
  g01  | 2/1/3/0/1 | 1/0/4/1/2 | 0/0/1/0/1 | 0/0/0/1/2 | yes
  ...
  total | ... | ... | ... | ... | <count of yes>

Then one line: on how many items you hesitated between bins 4 and 5.

Rules: read only, except RUN/derivability.md. In the chat: pair ids and numbers only. No
names of classes, helpers, files, keys, values, tickets or features from the suite, and no
sentences describing what a test does.
```
