# What we built: a plain-language overview

*ticket2test, as of October 2026*

## The idea in one paragraph

When a bug is reported, someone on the QE team has to work out how to test it. They read the ticket, find the right place in a large test suite, copy the setup from a similar test, write the new test and its test data, and make sure it fits. This project does the first draft of that work. It reads a bug ticket and hands a person a ready-to-review test and its test data, written in the suite's own style and reusing its own classes, page objects and helpers. A human always reviews the result and runs it. The tool never runs anything against real systems and never changes the real test suite.

## Why it is built the way it is

Three wishes shaped almost every decision:

1. **Reuse before writing anything new.** The real suite is built on inheritance and reuse: shared base classes, helper actions, tests that call other tests, classes generated in several variants. A new test should fit into that world, not sit next to it as a copy.
2. **Logic wherever possible, AI only where it is really needed.** Every step that can be a clear rule is a rule. The AI is used for what only language understanding can do, such as reading a ticket and writing test steps, and every answer it gives is checked by code before it is used. The target model is a small, cheap one (Claude Haiku class).
3. **Nothing private leaves the company, and nothing private enters this project.** The project was built on public code and an invented practice suite (the "stand-in"), so it can move into the company environment without carrying anything sensitive in or out.

The backbone is a **fixed workflow**: the same steps in the same order every time. Inside it, four **bounded agents** are allowed, each with read-only tools, step and size budgets, and output checked by code: investigation (searching the suite), missing-piece proposals, repair, and log triage (planned).

---

## Inputs

| Input | What it is | Where it comes from | Needed? |
|---|---|---|---|
| **Ticket** | A bug report: id, title, description, steps to reproduce, expected and actual behaviour, components, labels, comments, links. | A Jira export (JSON in Jira's REST shape) or a GitHub issue. Custom Jira fields are mapped in config. | Yes |
| **Target repo** | A local, read-only checkout of the test suite (Python, pytest). Its git history is read only for evaluation. | The team's repository. | Yes |
| **Config** | Every setting and limit: how the suite is shaped (data files, markers, style, base classes, page-object root, domains), which checks apply, budgets, the LLM, the sandbox. | `config.yaml` (defaults), a private override file (`T2T_CONFIG`), environment variables (`T2T_<SECTION>__<KEY>`). Secrets only in environment variables. | Yes |
| **LLM access** | One model provider behind one interface: the Claude Code CLI (default), the Anthropic API, or Gemini. | The approved endpoint. | Yes |
| **Conventions doc** (opt) | The team's test-writing rules in Markdown, under ~1,800 words. Goes into every generation. | Written once per suite (`docs/real-suite-conventions-prompt.md` helps a model write it). | Recommended |
| **Container runtime** (opt) | Docker or Podman, plus an image with the suite's Python and the packages needed to import it; optional private stubs and settings for modules that do things at import time. | The machine running the tool; the image is built once. | For the "it loads" check |
| **Area guides** (opt) | One short guide per feature area, written once by a stronger model within a dollar cap, then reused by the small model. | `ticket2test guides`. | Optional |
| **A real run's console log** (opt) | The console output of the suite's own runner, after a person ran the generated test. | The person who ran it. | For run verdicts |
| **Eval pair sets** (opt) | Tickets with their known tests (or expected outcome), for measuring quality. | `eval_data/`, or mined from the repo by `ticket2test mine`. | Evaluation only |

## Outputs

Per ticket, everything goes to the tool's own output folder (`output/` by default), never into the target repo.

| Output | What it is |
|---|---|
| **Normalized ticket** (`tickets/<id>.json`) | The ticket in one tidy format. Missing fields stay empty; nothing is invented. |
| **Drafts** (`drafts/<id>.drafts.json` + `.md`) | The test plan: intent, markers, test kind (UI / API / hybrid), deployment type, preconditions, steps, expected outcome, variants, and facts checked by code about how well the ticket supports it. The Markdown is for a person to read. |
| **Retrieval** (`<id>.retrieval.json`) | The code and tests found for the ticket, each with why it was found, plus the template tests whose data can seed the new one, and (opt) the investigator's record. |
| **Decision** (`decision.json`) | How the ticket fits the suite: covered, out of scope, a new case of an existing test, a new method in an existing class, or a new test file, with the reasons and any fallback. |
| **The test** | Either a **new test file** and its JSON data file, or a **patch**: whole patched copies of the existing files (`patched/<path>`) plus `changes.patch`. |
| **Traceability** (`generated.json`) | Which ticket, draft, retrieved chunks, template entry, prompt version and model produced it; the validation report; the sandbox collect report; the **reviewer checklist** (what only a real run can confirm, gaps, notes about neighbouring code). |
| **Missing pieces** (`missing_pieces.json`) | Members or helpers the test needed that the suite lacks, each checked by code: missing, exists, close match (with the similar names), owner unknown, or not test-side code. |
| **Proposals** (opt) (`proposals.json`, `proposal_<member>.diff`) | For each gap on an existing page-object or helper class, the one proposed member as a separate patch, never applied. |
| **Run report** (opt) (in `generated.json`) | After a person runs the test: one result per class variant and case, error lines, session links, and a verdict. |

A ticket ends in exactly one of these states:
- **generated**: a new file, method or case, validated (and, with the sandbox, loaded);
- **covered**: an existing test already does exactly this, and its id is reported;
- **out of scope**: the ticket's area is legacy, so nothing is generated;
- **insufficient info**: the ticket doesn't say enough, so the result is a list of questions for the reporter and a partial draft;
- **failed**: an error that the report explains.

Suite-level outputs (built once, refreshed when the suite changes): the **index** (cached), the **check-suite report** (calibration), the **suite map**, the **area guides**, **eval reports**, and **mined ticket-test pairs**.

---

## The full flow, input to output (every option on)

`(opt)` marks steps that are switched on in config or by a command flag. `[LLM]` marks the steps that call the model; everything else is code. Today the steps run as separate commands (`normalize`, `draft`, `retrieve`, `generate`, `validate`, `results`); the eval harness runs them end to end.

### 0. Once per suite (and again when it changes)

1. **Index** (`ticket2test index`). Every Python file is parsed into its syntax tree (tree-sitter); files that aren't Python 3 are skipped and reported.
   - **Chunks:** one per test (with its decorators, markers, parametrize stack and JSON data entries), page object, helper, function and class.
   - **Test ids:** computed exactly as pytest names them (stacked parametrize, inherited tests, decorator-made class variants, defaults rows, per-function data files).
   - **Symbol catalog:** every class, member, fixture and marker value; every page-object chain from the root (`self.nav.<area>.<page>.<member>`); each module's imports and star imports, so a class name resolves to the right class even when two modules share it.
   - **Keyword index:** BM25. Only changed files are re-read next time.
2. **Calibrate** (`ticket2test check-suite`, `--collect`):
   - The suite's own tests run through every validator. Since they're known-good, each error points at a config value to fix; this repeats until clean.
   - Older code that breaks a correctness rule (driving the browser directly, page locators in tests, pages built by constructors, star imports) is listed per area as a **deviation**, not an error.
   - Legacy areas are skipped.
   - With `--collect`, the whole suite is collected in the sandbox and the computed test ids are compared with pytest's. Each module that fails to import is named, with its error.
3. **Suite map** (opt) (`ticket2test map`). Per-area summaries from the index, in code: classes, setup options, test shapes, page objects, helpers, data keys, typical tests.
4. **Area guides** (opt) `[LLM, stronger model, once]` (`ticket2test guides`). One call per area, with material picked by code, under a hard dollar cap. Names in the guide are checked against the index and removed if they don't exist.

### 1. Read the ticket

5. **Normalize** (`ticket2test normalize`). A Jira export or GitHub issue becomes the tidy ticket: steps, expected and actual are found by section headings or mapped custom fields, and long comment threads are trimmed. Nothing is guessed.

### 2. Plan the test

6. **Draft** `[LLM]` (`ticket2test draft`). The model writes the structured plan: intent, markers, test kind, deployment type, preconditions, steps, expected outcome, variants.
   - The answer must match a JSON schema. A bad answer goes back with the exact error, a limited number of times.
   - Code then checks how well the ticket supports the draft: explicit steps and expected result present, component named, no numbers the ticket doesn't contain. There is no model self-rating.
7. **Insufficient info?** If the ticket lacks steps or an expected result, the run stops here with a list of questions for the reporter. (opt) `[LLM]` it also writes a **partial draft**, with every unknown as a numbered question; code rejects any number in it that the ticket doesn't contain.
8. **[Human review of the draft.]**

### 3. Find the right place in the suite

9. **Query words** `[LLM]`. The ticket's own words plus code words the model suggests. Suggested names that aren't in the catalog are dropped.
10. **Search** (code): BM25 keyword search plus exact name lookups (grep), merged by reciprocal-rank fusion.
11. **Expand** (code): from the best hits, follow the code's structure: callers, callees, tests using a helper, pages a test's chains reach.
12. **Rerank** (code): re-score and diversify (at most 3 chunks per file, at least 2 tests).
13. **Follow up**, one of two ways:
    - **follow-up rounds** `[LLM]`: at most 2 rounds of extra searches with the tool's own search functions, only while results are thin; or
    - **(opt) investigator agent** `[LLM, bounded agent]`: the model explores the index with read-only tools until it has enough or its budget ends. Tools: search, grep, open, open one member, callers, tests using a name, page chains, class hierarchy, list a class's members, data, one data entry. Outputs are cheap first: large classes open as outlines, cut lists say how many more results exist and where. Code drops kept chunk ids that don't exist, and records the pieces it says are missing.
14. **Templates** (code): the nearest existing tests that have data entries, same component and same test shape (add, edit, delete, other) first.

### 4. Decide how to reuse (code only)

15. **Domain:** the feature-area folder the ticket belongs to, chosen in this order:
    1. the ticket's own component, if it names one folder;
    2. for a cross-area ticket, the area holding a class marked with all its components;
    3. otherwise, where the search hits concentrate.

    When this is uncertain, nothing existing is patched.
16. **Outcome**, by fixed thresholds on a weighted word match between the draft and each test in the domain:
    - **covered**: an existing test already has the draft's exact case. Stop, and report its test id.
    - (opt) **out of scope**: the domain is listed as legacy. Stop; only "covered" is decided there.
    - **new case** of a parametrized test;
    - **new method** in an existing class;
    - **new test file**, scaffolded from the closest class.

    New methods never go into frozen classes, into classes gated to a narrower deployment than the draft, or (for UI tests) into classes that don't use page objects. The class whose component marker matches the ticket is preferred. Every decision records its reasons.

### 5. Write the test

17. **Context** (code). The template tests, the target class, the page objects and helpers involved, the conventions doc, and (opt) the area's guide. It must fit a token budget; the least relevant pieces are dropped whole, never cut mid-function.
18. **Generate** `[LLM]`. The model writes only the test steps, and says which data sections to keep and which values change. Code does the rest:
    - **Scaffold:** imports, decorators, base class and setup/teardown are copied from the template class. A copied star import becomes an import of just the names used.
    - **Data entries:** built from the nearest existing entry, trimmed to what the test reads, cloned once per variant, relabelled with the computed test ids. Unique names use the suite's placeholder.
    - **Style:** applied by a formatter. (opt) It follows the local style: a new file takes its template's style.
    - **New case path:** the new parametrize value and its entry are planned in code when the draft's inputs name the data keys they change. Otherwise one small `[LLM]` call plans them.
19. **Patch** (code, for a new method or a new case). The new methods are spliced into the existing class, and (opt) take that file's own indent and quotes; no existing line is reformatted. New data entries are inserted as text in the data file's own JSON style. A patch that can't be built falls back: new case, then new method, then new file.

### 6. Check it

20. **Validators** (27 checks, all code). Some are errors that block the test; others are warnings for the reviewer.

    **Errors:**
    - **Names:** every name, import and page-object chain exists. A member of a page built by its constructor is allowed only where the class already builds that page, and is flagged.
    - **Suite rules:** base class; the suite's assertion style; markers and their approved values; naming, with no ticket numbers in names; no locator constants, raw browser driver or star imports in tests; setup hooks that actually run.
    - **Data:** test ids equal the data entry ids; every key the test reads exists; every seed or expectation key is read or consumed; seeded names unique and within the length cap; values in the shape the suite uses.
    - **Draft:** the draft's expected outcome and every variant are covered.
    - **Safety:** style; no private terms, secrets or leftover masked text.

    **Warnings:**
    - the checks don't touch what the test's name promises;
    - capability gates the feature doesn't use;
    - risky patterns: a test calling a test, shared state, broad `except`, values that break hooks, entries copied unchanged from their template.
21. **Repair loop** `[LLM, bounded]`. Errors go back with their exact messages, at most 3 rounds. Some problems are fixed in code without asking again (unread keys removed, a mislabelled entry relabelled). A patched file reports only findings the unpatched file didn't already have.
22. **Sandbox collect** (opt, `validate --collect`). pytest loads the test (`--collect-only`) inside a container: no network, read-only file system, no capabilities, only the repo (read-only) and a staging folder mounted. The collected ids must equal the computed ones.

### 7. What the suite lacks

23. **Gap report** (code). Names the new test needed that don't exist (in the final code, in any repair attempt, or among the investigator's hints) are checked against the catalog. Each real gap adds a reviewer note: the test may work around it.
24. **(opt) Missing-piece proposals** `[LLM, bounded agent]`. For each gap on an existing page-object or helper class, the model writes only the missing member. Code checks:
    - nothing existing changed (syntax-tree comparison);
    - the name and kind match the use (called means method, read means property);
    - only existing names are used, with no new imports;
    - the suite still loads with the patch in the sandbox.

    Findings go back at most twice. The result is a separate diff, never applied.
25. **(opt) Generate again with the proposals.** The accepted members are added to an in-memory copy of the catalog and to the context, and the test is generated again. The new test replaces the first only if it validates and uses them; its checklist then says which patch to apply first.

### 8. Hand it over

26. **Reviewer checklist** (code). The standard "needs a real run" items:
    - expected responses aren't from a real capture;
    - whether a page needs a refresh;
    - which save flow it uses.

    Plus the model's own notes, the gap or apply-this-patch notes, and (when neighbouring tests in the file break a correctness rule the new test follows) a note to confirm it reaches the same state.
27. **Output written** to the output folder (see Outputs). **[A person reviews the test and runs it with the suite's own runner.]**

### 9. After a real run

28. **(opt) Read the run's console log** (`ticket2test results`, code). One result per class variant and case, the error lines, session links, and a verdict:
    - **passed**;
    - **environment**: the system couldn't be reached;
    - **test problem**: the test itself is wrong;
    - **check failed**: the bug was caught, or the expectation is wrong; the run's link shows which;
    - **error**, **not run**, or **unclear**.
29. **Log triage agent** `[LLM, bounded agent]`: *planned.* It would read the log and the test, then decide between a repair, an environment problem, or flagging for review. Any repair would have to pass the validators and the sandbox again.

### 10. Measuring it (opt)

30. **Eval harness** (`ticket2test eval`):
    - **Retrieval:** recall@k and MRR.
    - **Generation:** the validator pass rate on the first attempt and after repair, the invented-name rate, the sandbox collect pass rate, repair rounds, LLM calls and dollar cost.
    - **Expected outcomes:** gap reported, vague ticket recognized, legacy ticket out of scope.

    Each ticket's own test is hidden from the suite first (leave-one-out). The optional judge `[LLM]` compares the draft with the ticket and stays marked unvalidated.
31. **Mining** (`ticket2test mine`). Ticket-test pairs come from commits that remove a skip citing a ticket id, or (`--from-skips`) from skips in the current tree when there's no history.

### Around every LLM call

- **Private terms** are blanked first.
- **Prompt-injection text** in tickets and test data is masked behind placeholders and restored by code afterwards.
- **Secrets** are scrubbed from everything sent and everything returned.
- Every answer is **structured JSON** checked against a schema, with a limited number of retries.
- Every loop has a **budget** from config.
- Full prompts are **logged** only with `--debug-log`, to an ignored folder.

---

## Where the AI is used, and where it isn't

| Step | AI | Checked by code how |
|---|---|---|
| Draft (and partial draft) | Yes | Schema, support facts, numbers the ticket doesn't contain |
| Query words, follow-up searches | Yes | Unknown names dropped; only the tool's own search functions |
| Investigator (opt) | Yes, bounded agent | Read-only tools, budgets, kept ids checked, hints checked against the catalog |
| Writing the test steps | Yes | 27 validators, sandbox collect |
| Planning a new case (only when code can't) | Yes | Same validators |
| Repair | Yes, bounded loop | Same validators; at most 3 rounds |
| Area guides (opt, once) | Yes, stronger model | Names checked against the index; dollar cap |
| Missing-piece proposals (opt) | Yes, bounded agent | Nothing existing changed, names exist, the suite still loads |
| Judge (eval only, opt) | Yes | Marked unvalidated |
| Everything else (index, search, reuse decision, scaffold, data entries, style, patches, gaps, checklist, run verdicts) | No | — |

## How the project is organized

| Folder | What's in it |
|---|---|
| `src/ticket2test/adapters` | Reading tickets (GitHub, Jira exports) and the suite and its git history (read-only) |
| `src/ticket2test/normalize` | Raw tickets into the tidy format |
| `src/ticket2test/draft` | Drafts, partial drafts for vague tickets, support facts |
| `src/ticket2test/index` | Parsing, chunks, the symbol catalog (chains, import maps), test ids, data-file rules, BM25 |
| `src/ticket2test/retrieve` | Query words, search, merging, expansion, reranking, follow-ups, the investigator, templates |
| `src/ticket2test/suitemap`, `guides` | The suite map (code) and the area guides (one strong-model call per area) |
| `src/ticket2test/generate` | Domain and reuse decisions, context, generation, data entries, patches, the end-to-end pipeline |
| `src/ticket2test/gaps`, `proposals` | Missing pieces, and proposed members as separate patches |
| `src/ticket2test/style` | Formatting code and JSON, in the configured or the file's own style |
| `src/ticket2test/validate` | The validators, the repair loop, check-suite |
| `src/ticket2test/sandbox` | The container that loads tests, and the stub plugin for import-time side effects |
| `src/ticket2test/results` | Reading a real run's console log into verdicts |
| `src/ticket2test/eval` | The eval harness, mining, reports |
| `src/ticket2test/llm`, `security` | The AI interface and providers; privacy, masking and secret scrubbing |
| `prompts/` | Every instruction given to the AI, as numbered versions, never edited in place |
| `standin/` | The invented practice suite: app, framework, tests, data, tickets |
| `eval_data/` | Ticket-test pairs used for measurement |
| `tests/` | The project's own automated tests (about 830) |
| `docs/` | This overview, the integration brief and fit check, the porting checklist, the conventions prompt |

## How well it works today (on the practice suite)

- **Main practice tickets** (21, each ticket's own test hidden): all generated, all pass every check after repair, all load in the sandbox, about 3 AI calls per ticket.
- **Real-suite shapes** (stand-in v6, Haiku 5.5, held-out tickets): 7/7 pass after repair and load, 0 invented names. The missing-piece ticket's gap was reported, and the vague ticket was recognized. About $0.07 for the set.
- **Missing-piece proposals** (3 gap tickets): each got a correct one-line member, every check passed, and the regenerated tests used it.
- **Older and legacy code** (stand-in v7, Haiku 5.5): the mixed-area tickets became tests in the right class, in the file's own style; the legacy tickets were reported out of scope. Dev and held-out both passed, for a few cents.

These are synthetic results. Real-suite numbers don't exist yet.

## What's still open

- **Connecting to the real suite:**
  - **Team inputs:** the Python and pytest versions, one requirements list, the legacy areas, the LLM endpoint, a ticket export.
  - **Then:** calibration with `check-suite`, and the first real tickets. The integration brief and the fit check in this folder guide it.
- **Known limits:**
  - a test can use a real member that's the wrong one and still pass every check;
  - a missing member that needs a new selector can't be proposed;
  - members of pages built by constructors aren't type-checked.
- **Later:** the log triage agent; notes that learn from reviews and real runs; type inference (an LSP or SCIP backend) if real data shows it's worth a new dependency.
