# Prompt: area guides written by Claude Code

The `guides` step writes each area guide in one call from code it is shown; it can't open files
or follow a helper to its asserts. A Claude Code session can. This prompt has Claude Code write
the guides for every area of the suite map, with its own tools, in the format the tool reads.

How it fits:

- Run it in Claude Code inside the environment that has the target suite (read-only), the
  suite map (`ticket2test map`) and the guides folder. Paste it as is: it finds the paths
  itself (from the map), so nothing names the target repo here.
- It writes `<area>.authored.json` per area into the guides folder, plus
  `_framework.authored.json` for the shared framework. At generation, an authored guide wins
  over the built one; its names are checked against the index when it is loaded (unknown ones
  are removed), and `guides` rebuilds never overwrite it.
- It resumes: an area whose authored file exists is skipped, so it can stop (usage limits, a
  long suite) and be started again with the same prompt. To redo an area, delete its file.
- It changes nothing in the suite.

---

```text
You are writing guides to an existing pytest test suite, one per area, for a smaller model
that writes new tests from tickets. That model reads the guide for the ticket's area (and the
framework guide) next to two or three similar tests, every time. Your guide must tell it what
those examples alone would not. You have tools: use them to read the actual code. Never guess.

Paths. Work them out first, then say them back in one line before you start:
- OUT = /root/work/t2t-private/output   (the tool's output folder)
- MAP = the one folder inside OUT/map/ (named after the target repo); if there are several,
  the one whose map.json "repo_root" is the repo the tickets are about
- AREAS = MAP/areas      (one <area>.md per area: read-only)
- OVERVIEW = MAP/overview.md   (read-only)
- REPO = the "repo_root" value in MAP/map.json   (the target repo: read-only)
- GUIDES = OUT/guides/<the same folder name as MAP>   (you write here, and only here)

Work list:
1. First the framework: write GUIDES/_framework.authored.json from OVERVIEW and the base test
   classes, shared helpers, fixtures and data loading under REPO.
2. Then every file in AREAS, in name order. The area's name is the file name without ".md".
   Write GUIDES/<area>.authored.json.
3. Skip any area whose GUIDES/<area>.authored.json already exists. Keep a log in
   GUIDES/authoring-progress.md: one line per area, "done", "skipped" or "failed: <why>".
4. If you can start sub-agents, give each area to its own sub-agent (one area per sub-agent,
   a few at a time) so your own context stays small; each writes its own file.

For one area:
a. Read AREAS/<area>.md: its folders, test files, classes, helpers, data keys, examples.
b. Read the test classes and two or three typical tests with their data entries (the JSON
   file next to each test file; entries are matched to tests by their id field).
c. For every helper the tests call (the class's own, including ones called only once, the
   base-class ones, setup/teardown and autouse fixtures that run on their own): open its
   definition and follow the calls it makes, as deep as needed, until you know what it checks.
d. For the data: compare several entries of different kinds of test. Find which blocks each
   kind of test needs, which values only work together with another block (for example a mode
   or action "default" that relies on a rule seeded elsewhere in the entry), and what each
   action or mode value means.
e. Write the JSON below. Verify every name you write exists (grep it).

The JSON (exactly these keys, nothing else; lists may be empty; stay within the limits):
{
  "summary": "what the area's tests check, 2-4 sentences (max 1200 chars)",
  "how_to_add": ["ordered steps for a typical new test here (max 12)"],
  "classes": [{"name": "<TestClass>", "use": "when a new test belongs in it (max 400 chars)"}],
  "page_objects": [{"name": "<chain such as nav.<area>.<page>.<member>, or Class.member>", "use": "..."}],
  "helpers": [{"name": "<helper>", "use": "..."}],
  "data": ["how entries look (max 12)"],
  "examples": [{"name": "<file>::<Class>.<test>", "use": "the shape it shows"}],
  "pitfalls": ["what is easy to get wrong (max 10)"]
}
Limits: classes 12, page_objects 25, helpers 30, examples 8; the most important first.

What each part must say:
- helpers: for each, what it takes; what it checks itself, in plain words: "asserts <what>",
  "waits for <what> and fails after <time>", "only waits" or "checks nothing" (including what
  the helpers it calls check); whether it returns a boolean that tests then use as the check
  (a failing call then can't fail the test); what it returns and what tests do with that; how
  it differs from a helper with the same or a similar name. Say plainly when a test must not
  check something again because the helper already does.
- data: every way the data reaches a test (a class-level fixture, an argument, a helper that
  reads it itself); the seed sections and which blocks each kind of test needs, with a test id
  whose entry has them (a new test copies its entry from the nearest one); the expectation
  section and the helper that reads it; the placeholders and what fills them; values whose
  meaning depends on another block, and that block; setup or teardown that depends on a block;
  what each action or mode value does.
- how_to_add: the class, the setup it relies on (the framework calls setup and teardown itself
  unless the code shows otherwise), the data entry to start from, the steps, the checks.
- pitfalls: only what the code supports: a check a helper already makes, a block a value needs,
  a helper that returns a boolean, a debug-only helper or setting marked for removal, a class
  restriction (platform, deployment), an order of calls.
- page_objects, classes, examples: names exactly as in the code; examples as
  <file path relative to the repo root>::<Class>.<test>.

The framework guide (_framework) uses the same keys: classes are the base test classes,
helpers the shared helpers and fixtures, data how entries are loaded, matched and read for
every area; examples stays empty.

Rules: read only; write only the JSON files and the progress log in GUIDES. Plain JSON, UTF-8,
no comments. No names of people. Don't copy secrets, tokens or credentials from the code or
data into the guide.
```
