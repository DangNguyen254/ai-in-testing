# What we built: a plain-language overview

*ticket2test, as of October 2026*

## The idea in one paragraph

When a bug is reported, someone on the QE team has to work out how to test it. They read the ticket, find the right place in a large test suite, copy the setup from a similar test, write the new test and its test data, and make sure it runs. This project does the first draft of that work. It reads a bug ticket and, at the end, hands a person a ready-to-review test and its test data. A human always reviews the result. The tool never runs anything against real systems and never changes the real test suite by itself.

## Why it is built the way it is

Three wishes shaped almost every decision:

1. **Reuse before writing anything new.** The real suite is built on inheritance and reuse: shared base classes, shared helper actions, tests that call other tests, and test classes generated in several variants. A new test should fit into that world, not sit next to it as a copy.
2. **Use logic wherever possible, and AI only where it is really needed.** Every step that can be a clear rule is a rule. The AI model is used for things only language understanding can do, such as reading a ticket and writing test code. Its answers are always checked by code afterwards.
3. **Nothing private leaves the company, and nothing private enters this project.** The project was built entirely on public code and on an invented practice suite, so it can be moved into the company environment later without carrying anything sensitive in or out.

## What happens to a ticket, step by step

1. **Read the ticket.** It comes from Jira (or GitHub) and is turned into one tidy format: title, description, steps, expected result, actual result, labels, components.
2. **Draft the test cases.** The AI writes a short, human-readable plan: what to test, the steps, and what "fixed" should look like. If the ticket doesn't say enough, the tool says so instead of guessing (more on that below).
3. **Find the right place in the suite.** Search finds the tests, pages and helpers the ticket is about. The ticket's folder (its "domain") is chosen by rules: the reporter's own component field comes first, then where the best search hits live.
4. **Decide how to reuse.** Code decides between four outcomes:
   - *Already covered*: an existing test already does exactly this. Nothing is written. This rule is strict on purpose, because a wrong "covered" would silently drop a ticket.
   - *New case of an existing test*: the same steps with different data (for example, testing a limit of 2 where the test already checks 1 and 3). Only one value in the test and one new data entry are added.
   - *New test in an existing class*: the test is written and slotted into the class it belongs to, keeping that class's setup.
   - *New test file*: only when nothing suitable exists. It still copies its setup from the closest existing class.
5. **Write the code and its data.** The AI writes only the test steps. Everything around them is copied from the real suite by code: imports, decorators, the base class, setup and teardown, and the data entry copied from the nearest existing one.
6. **Check it, strictly.** Code checks that every page, button and helper the test uses actually exists, that the data matches the test, that the style matches the suite, that nothing private or secret slipped in, and more. Problems that code can fix, it fixes itself. The rest go back to the AI with the exact error, a limited number of times.
7. **Prove it loads.** The test is loaded by pytest inside a locked-down container with no network access, to confirm it really fits the suite.
8. **Hand it to a person.** The output is either a new file or a small patch to an existing file, plus a checklist of things only a real run can confirm. The real test suite is never modified by the tool.

## Under the hood: the pipeline in more detail

The steps above, with the techniques behind them. The whole thing is a **fixed workflow**: the same steps in the same order every time. It is not an "agent" that decides for itself what to do next.

```
ticket ─► normalize ─► draft ─► [person reviews]
                                     │
        ┌────────────────────────────┘
        ▼
  index of the test suite (built once, cached)
        │
        ▼
  retrieval: query words ─► BM25 search + grep ─► merge ─► AST expansion
             ─► rerank ─► (up to 2 follow-up searches) ─► templates
        │
        ▼
  domain + reuse decision (covered / new case / new method / new file)
        │
        ▼
  context (within a token budget) ─► AI writes the test ─► code assembles data,
  shell and style ─► validators ─► repair loop (capped) ─► sandbox collect
        │
        ▼
  output for review (new file, or a patch + diff) ─► [person reviews and runs it]
        │
        ▼
  the run's console log ─► verdict per test
```

### 1. Indexing the test suite

Before anything else, the tool reads the whole test suite once and builds an index, saved on disk. Next time, only changed files are re-read.

- **Parsing with tree-sitter.** Each Python file is turned into its **syntax tree** (AST, "abstract syntax tree"). That's the structure of the code (classes, functions, decorators, calls) rather than plain text. This is what lets the tool understand code instead of just matching words.
- **Chunks.** The code is cut into meaningful pieces: one per test (together with its decorators, markers and its JSON data entries), page object, helper, function or class.
- **Test ids worked out in advance.** The tool computes the exact names pytest will give each test, including parametrized cases, stacked decorators, inherited tests and class variants. In the practice suite, all 79 match what pytest really collects.
- **The symbol catalog.** A list of everything that exists: functions, classes, methods, fixtures, markers, and every page-object chain such as `nav.rules.list.search`. This is how the validators later know whether a name the AI used is real.
- **The BM25 index.** BM25 is a standard keyword-search method, the same family search engines use. It ranks code by how well its words match the query, giving rare words more weight than common ones. Code names are split into words first (`delete_selected` → "delete selected"), so ordinary language finds them.

### 2. Retrieval: finding the relevant code

- **Query words.** The ticket's own text, plus a short list of likely code words suggested by the AI (the "query rewrite"). Any code name the AI suggests is checked against the catalog, and invented ones are dropped.
- **BM25 + grep.** Keyword search over the ticket text and the suggested words, plus exact lookups ("grep") for code names the ticket mentions. Names that appear almost everywhere are skipped as too common.
- **Merging.** The result lists are combined with *reciprocal rank fusion*, a simple way to merge rankings that favours items near the top of several lists.
- **AST expansion.** From the best hits, the tool follows the code's structure: what a function calls, what calls it, which tests use it, and which page objects a test's chains lead to.
- **Reranking.** The final top results are re-scored and diversified, so one file doesn't fill the whole list.
- **Follow-up rounds (at most 2).** Only if the results look thin, the AI may ask for a few extra searches. It can use only the tool's own search functions, nothing else. This is the only place the AI chooses an action.
- **Templates.** The nearest existing tests that have data entries, preferring the same component, then the same test shape (UI or API; add, edit, delete or other).

### 3. Deciding how to reuse (all logic, no AI)

- **The domain.** The folder the ticket belongs to: the ticket's own component if it names one folder, otherwise where the search hits concentrate.
- **Comparing the draft with each test in that folder.** A weighted word match between the draft and each test's "flow" words: its name, docstring, the pages and helpers it uses, its parameters and data keys. Rare words count more.
- **Choosing one of the four outcomes** (covered, new case, new method, new file) by clear rules with fixed thresholds. Each decision records its reasons, so a reviewer can see why.

### 4. Writing the test

- **Context.** The chosen template tests, the class they live in, the page objects and helpers involved, and the team's conventions. All of it must fit a fixed size budget (measured in tokens, the units AI models read in). If it doesn't, the least relevant pieces are dropped whole, never cut mid-function.
- **Structured answers only.** The AI must answer in a fixed JSON format, which is checked against a schema (Pydantic). A malformed or inconsistent answer is sent back with the exact error, a limited number of times.
- **Data built by code.** The AI only says which sections of the nearest data entry to keep and which values to change. The copying, relabelling and placeholders are done by code.
- **Style by code.** A formatter (ruff) applies the suite's indentation, import order and other style rules.

### 5. Checking and repairing

- **Validators.** Twenty checks, all code:
  - **Names:** every name and page-object chain exists in the catalog; imports resolve.
  - **Test ids and data:** test ids match the data entries; every data key the test reads exists, and every key in the data is used.
  - **Suite conventions:** the right base class and markers; the suite's assertion style; no ticket numbers in names; the style rules.
  - **Content and safety:** the checks cover what the test's name promises; nothing private or secret slipped in.
- **Repair loop.** Remaining errors go back to the AI with the exact messages, at most 3 rounds.
- **Sandbox.** pytest loads the test (`--collect-only`) inside a Docker/Podman container with no network, a read-only copy of the suite and no access to the host.

### 6. Measuring it (the evaluation harness)

- **Retrieval quality:** *recall@10* (was the right code among the top 10 results?) and *MRR* (how near the top was it?), on public bug tickets from an open-source project (httpx) and on the practice tickets.
- **Generation quality:** pass rates for the validators and the sandbox, invented names, repair rounds, and AI calls per ticket.
- **Leave-one-out:** during evaluation, each ticket's own test is cut out of a copy of the suite first, so the tool can't simply find the answer.
- **The judge:** an optional AI review of whether drafts match their tickets. It is marked "unverified" until people check a sample.
- **Mining git history:** ticket ↔ test pairs are found automatically from commits that remove a ticket's skip marker.

### 7. The AI layer

All AI calls go through one interface, so the model provider can be changed in configuration. Three providers are supported: the Claude Code command-line tool (the default), the Claude API, and Gemini. Every request passes through two protective wrappers before it leaves:
- the **privacy wrapper** blanks out listed private terms;
- the **masking wrapper** hides prompt-injection text behind placeholders.

Full prompts and answers are logged only when explicitly turned on, and then to an ignored local folder.

## How the project is organized

| Folder | What's in it |
|---|---|
| `src/ticket2test/adapters` | Connectors: reading tickets (GitHub, Jira exports) and reading the test suite and its git history (read-only) |
| `src/ticket2test/normalize` | Turning raw tickets (Jira markup, GitHub Markdown) into the tidy ticket format |
| `src/ticket2test/draft` | Drafting test cases, the partial draft for vague tickets, and the support checklist |
| `src/ticket2test/index` | Parsing (tree-sitter), chunks, the symbol catalog, test ids, inheritance and class variants, BM25 search |
| `src/ticket2test/retrieve` | Query words, search, merging, AST expansion, reranking, follow-ups, templates, test shapes |
| `src/ticket2test/generate` | Domain and reuse decisions, context building, code and data generation, patches for existing files |
| `src/ticket2test/style` | Formatting code and JSON to the suite's style |
| `src/ticket2test/validate` | All validators, the repair loop, and the config check against an existing suite |
| `src/ticket2test/sandbox` | The container that loads tests safely |
| `src/ticket2test/results` | Reading a real run's console log into verdicts |
| `src/ticket2test/eval` | The evaluation harness and its reports |
| `src/ticket2test/llm` | The AI interface, the providers, the privacy and masking wrappers |
| `src/ticket2test/security` | Secret removal, prompt-injection masking, private terms |
| `src/ticket2test/models` | The shapes of the data passed between steps (ticket, draft, chunk, generated test) |
| `prompts/` | Every instruction given to the AI, as numbered versions (e.g. `draft_v2`), never edited in place |
| `standin/` | The invented practice suite: app, framework, tests, data, tickets |
| `eval_data/` | Ticket ↔ test pairs used for measurement (ids and paths only) |
| `tests/` | The project's own ~650 automated tests |
| `docs/` | This overview, the integration brief, the porting checklist |
| `config.yaml` | Every setting and limit in one file; company values go in a private copy |

**Commands** (run as `ticket2test <command>`):

| Command | What it does |
|---|---|
| `normalize` | Read a ticket into the tidy format |
| `draft` | Draft test cases (JSON + a readable Markdown page) |
| `index`, `search` | Build the suite's index; search it |
| `retrieve` | Find the relevant code and template tests for a ticket |
| `generate` | Decide how to reuse, then write the test or patch |
| `validate` | Re-run the checks; with `--collect`, load the tests in the sandbox |
| `sandbox` | Show or build the sandbox container |
| `check-suite` | Check the configuration against an existing suite (its own tests should all pass) |
| `results` | Read a real run's console log into verdicts |
| `eval`, `mine` | Measure quality; find ticket ↔ test pairs in git history |
| `privacy-scan` | Check the files about to be committed for private terms |

## Making sure it can be trusted

- **No company data in the project.** All development used public code and an invented "stand-in" suite with made-up names. Real names, hosts and logs shared during the work stayed in a private, ignored folder and never reached the public repository. Every push was checked for them first.
- **Hostile text in tickets can't steer the AI.** Tickets about an AI browsing agent naturally contain text like "ignore previous instructions". Such text is hidden behind placeholders before the AI sees it, and put back afterwards by code.
- **Secrets are removed** from everything sent to the AI and from everything it writes. This step is careful not to break the code it cleans.
- **Private terms**, such as company or product names, can be listed in a private setting. They are blanked out before anything reaches the AI, flagged if they ever appear in output, and checked for before each commit.
- **Generated code never runs on the machine itself.** It only runs inside the sealed container.
- **Every loop has a limit.** Retries, repairs and searches all stop after a fixed number of rounds.

## Less AI, more logic

The AI is used for five things: drafting from the ticket, suggesting search words, writing the test steps, occasionally planning a new data case, and an optional "judge" that reviews drafts during evaluation. Everything else is rules. Some examples of moving work from the AI to logic:

- **No AI "confidence score".** The AI used to rate its own drafts. We removed that, because a model scoring itself isn't evidence. Instead each draft shows facts checked by code. Does the ticket have explicit steps? An expected result? Did the draft add numbers or words the ticket never mentioned?
- **Fixes in code before asking the AI again.** Unused data keys are removed, a mislabelled data entry is relabelled, and missing data for inherited tests is copied. Each of these used to cost an extra AI round.
- **Templates by test shape.** Add, edit, delete and view-only tests are recognized from names and actions, so a delete ticket is shown delete tests as examples.

## When a ticket is too vague

Some tickets are one line, such as "the service runs out of memory under load". The tool doesn't invent the missing details. Instead it produces two things:

- **A list of what's missing**, as specific questions for the reporter. What should happen when the limit is reached? How many clients? How is the failure observed?
- **A partial draft**: the test as far as the ticket supports it, with every unknown marked as a numbered question. Code rejects any number in it that the ticket doesn't contain.

## Learning from real runs

The real suite runs tests through its own script on remote browsers. The tool doesn't run those. Instead it reads the script's console log after a person runs the generated test, and records a plain verdict for each test:

- **passed**;
- **environment**: the run couldn't reach the system, so it says nothing about the test;
- **test problem**: the test itself is wrong;
- **check failed**: either the bug was caught or the expectation is wrong; the run's link shows which.

The reader was calibrated on real passed and failed logs, using their shape only.

## The practice suite

Because the real suite can't be used here, we built a small invented one that behaves like it. It has a fake web app with policies, rules, files, an AI browsing agent and its injection guard, and a per-tenant limit on how many agent browser sessions may be open at once. It also has page objects, shared base classes, class variants, about 80 tests, their data files, and 28 invented bug tickets. Each time the real suite's patterns were described to us (generically), the practice suite was updated to match.

## How well it works today

On the 21 main practice tickets, with each ticket's own test hidden so the tool can't copy the answer, three measured runs showed steady progress:

| | First run | Second run | Third run |
|---|---|---|---|
| Tests generated | 17 of 21 | 21 of 21 | 21 of 21 |
| Pass all checks after repair | 35% | 81% | **100%** |
| Load correctly in the sandbox | 12 of 17 | 21 of 21 | **21 of 21** |
| AI calls per ticket (average) | about 5.4 | about 4 | **about 3** |

On the six newer browser-limit tickets, all six were generated, passed every check on the first try, and loaded correctly. The "new case of an existing test" path was also tested live: the tool added a limit of 2 to a test that checked 1 and 3, with a matching data entry.

Each evaluation run uncovered real problems, and every one was fixed and covered by an automated test. The project has about 650 automated tests of its own.

## What's still open

- **Connecting to the real suite.** That happens inside the company environment, guided by the integration brief and porting checklist in this folder. It needs the team's settings, conventions and approvals.
- **One more real log:** a failure that reaches the browser, to show where the remote-browser link appears.
- **Human labels for the AI judge.** Its scores are marked as unverified until people have checked a sample of them.
- **Later ideas:** measuring speed and cost per ticket, and support for Rust code.
