# ticket2test: project report

*High-level report, October 2026. The detailed walk-through of every step is in
`docs/project-overview.md`.*

---

## 1. The problem

When a bug is reported, a QE engineer has to turn it into a regression test. In a large, mature
test suite that is mostly search and copy work, not invention:

- read the ticket and work out what to test;
- find the right feature area and the closest existing tests among thousands;
- copy the class scaffold, decorators and setup from a neighbouring test;
- write the steps with the suite's own page objects and helpers;
- build the JSON test data by copying the nearest existing entry and changing a value or two;
- make sure the test ids, markers, data keys and style all match the suite's conventions.

Each step is easy to get slightly wrong (a missing marker, a data key nobody reads, an invented
helper name), and every test goes through review anyway. **ticket2test does the first draft of
that work**: it reads a ticket and hands a person a ready-to-review test and its data, written in
the suite's style and reusing what the suite already has. A person always reviews the result and
runs it.

## 2. Goals and ground rules

| Goal | What it means in practice |
|---|---|
| Reuse before writing | A new test fits into the suite's inheritance and helpers: a new case, a new method in an existing class, or a new file scaffolded from the closest class. |
| Code first, AI only where needed | Every step that can be a rule is a rule. The model reads tickets and writes test steps; every answer it gives is checked by code before it is used. |
| Small, cheap model | Built for a Haiku-class model. Expensive calls are optional and capped. |
| Nothing private in, nothing private out | Built entirely on public code and an invented practice suite. Company-specific parts sit behind adapters and config, so the code moves into the company environment unchanged. |
| A human stays in charge | The tool never runs tests against real systems and never changes the real suite. It writes only to its own output folder. |

## 3. Inputs and outputs

**Inputs**

| Input | Notes |
|---|---|
| A ticket | From a tracker export, a GitHub issue, or a Markdown file filled in by hand (while the tracker's API can't be used). Steps and expected results may come from a pasted test plan. |
| The test suite | A local, read-only checkout (Python, pytest, a page-object layer, JSON data files). |
| Config | Describes the suite's shape: data files, markers, style, base classes, helpers. Defaults in the repo; the company's values in a private file. |
| Model access | One interface, several providers (CLI, API). Keys only from environment variables. |
| Optional | A short conventions document, a container runtime (for the "it loads" check), a real run's console log, evaluation pairs. |

**Outputs** (all in the tool's own output folder)

| Output | Notes |
|---|---|
| A test plan (draft) | Structured JSON plus Markdown for a person: intent, markers, test kind, steps, expected outcome, variants. |
| The test | A new test file with its JSON data, or a patch that adds a method or a case to an existing file. |
| A reviewer checklist | What only a real run can confirm, missing pieces, notes about neighbouring code. |
| Traceability | Which ticket, retrieved code, template entry, prompt version and model produced the test, and its validation report. |
| Or a clear stop | "Covered" (an existing test already does it), "out of scope" (a legacy area), or "insufficient info" (with questions for the reporter). |

## 4. The flow

Once per suite, and again when it changes:

```
test suite ──► index (syntax trees → chunks, symbol catalog, page-object chains, test ids)
           ──► check-suite (validators over the suite's own tests → config fixes)
           ──► (optional) suite map ──► (optional) area guides
```

Per ticket:

```
ticket ──► normalize ──► draft [AI] ──► enough info? ──no──► questions for the reporter
                                             │
                                            yes
                                             ▼
        [human reviews the draft] ──► query words [AI] ──► search (keywords + exact names)
──► expand through the code's structure ──► rerank ──► follow-up rounds or investigator [AI]
──► reuse decision (covered / out of scope / new case / new method / new file)
──► build context (templates, class, page objects, helpers, within a token budget)
──► generate test steps [AI] + scaffold, data entries and style by code
──► validators ──► repair loop [AI, capped] ──► (optional) sandbox collect
──► missing pieces ──► (optional) proposals [AI] ──► reviewer checklist
──► output ──► [a human reviews and runs the test] ──► (optional) read the run's log
```

`[AI]` marks the only steps that call a model. Everything else is code.

## 5. Structure

The code is organized by pipeline stage, with company-specific parts at the edges.

| Layer | Parts |
|---|---|
| Edges (swappable) | Ticket sources, the repo reader, model providers. Each behind an interface; provider SDKs are imported in one place only. |
| Understanding the suite | Indexer (tree-sitter parsing, chunks, symbol catalog, page-object chains, pytest id computation, keyword index), suite map, area guides. |
| Per-ticket pipeline | Normalize, draft, retrieve, reuse decision, generate, patch, style. |
| Checking | Validators, repair loop, sandbox collect, check-suite (calibration). |
| Safety | Secret scrubber, prompt-injection masking, private-term masking, budgets on every loop. |
| Measuring | Eval harness, mining of ticket ↔ test pairs, reports. |
| Practice suite | An invented web app, framework and tests (the "stand-in") that copy the real suite's patterns with generic names. |

## 6. Design

- **A fixed workflow with bounded agents.** Code decides the steps and their order. Four small
  agents are allowed inside it: investigation (exploring the suite), missing-piece proposals,
  repair, and log triage (planned). Each has read-only tools, step and size budgets, and output
  checked by code.
- **Structured answers only.** Every model answer is JSON checked against a schema. A bad answer
  goes back with the exact error, a limited number of times, then the step fails cleanly.
- **The model writes the least it can.** It writes the test steps and says which data sections
  to keep and which values change. Code copies the scaffold, builds the data entries from the
  nearest existing entry, computes the test ids, and applies the suite's style.
- **No invented names.** Every name in a generated test, including every page-object chain, must
  exist in the symbol catalog. A needed member that doesn't exist becomes a reported gap, and
  optionally a separate proposed patch, never a silent invention.
- **Validators are the contract.** About 27 deterministic checks define what a good test is.
  The same checks run over the real suite's own tests to calibrate the config.
- **Untrusted code stays contained.** Generated tests are only loaded (`pytest --collect-only`),
  inside a container with no network and a read-only copy of the suite.

## 7. Key decisions and why

| Decision | Why |
|---|---|
| Fixed workflow, not a free agent | Predictable cost, steps that can be tested one by one, and failures that are easy to explain. Agents only where exploration really helps. |
| Code builds the data entries | Real data files are copy-paste heavy. Copying deterministically from the nearest entry is more reliable than having a model write JSON. |
| Exact pytest id computation | Data entries are matched by test id; one wrong id means the test runs without its data. |
| A synthetic practice suite | It was the only way to develop on realistic patterns without private code. It was reworked several times (v2 to v7) as comparisons with the real framework showed new patterns. |
| Calibration against the real suite | The suite's own tests are known-good, so every validator error on them points at a config value or a tool blind spot. This turns "does it fit the real suite?" into a number that goes down. |
| Investigation through masked code shapes | A model session inside the company environment reads the real code and returns code skeletons with every name replaced by a role. The tool is fixed from those, so no private code leaves. |
| Legacy areas are out of scope | Old code that breaks the current rules shouldn't be copied. Those areas get "covered" checks only. |
| Local style for patches | A patch into an existing file follows that file's own indent and quotes; correctness rules still apply everywhere. |
| Pasted tickets | The tracker's API isn't approved yet; a fixed Markdown format feeds the same ticket model, so nothing downstream changes. |

## 8. Problems on the way

| Problem | What was done |
|---|---|
| The practice suite didn't match the real framework | Several rounds of comparison with the real suite (described in general terms only) led to stand-in versions v2 to v7: decorator stacks, property-style page objects, array data files, a shared top bar, per-tenant data, legacy areas. |
| Mixed old and new code in the real suite | Correctness rules hold everywhere; older code that breaks them is reported as a deviation per area, not as a config error. Legacy areas are skipped. |
| Real-suite patterns the tool couldn't see | Calibration found many: helpers called from setup or teardown or through fixtures, data files named after the test function, entries handed to helpers or copied before use, guarded reads, checks done by waiting on a condition, module-level assertion objects, retired tests with old data. Each became a general rule or config option. Validator errors on the suite's own tests fell by about 98%. |
| Running out of memory on a small VM | The index of a large suite took over 2.5 GB at peak and the container was killed. Measured section by section, then fixed: search tokens built only when searching, an incremental build reads only the old file records, and the index is written in sections. The peak fell to about 1.1 GB. |
| No tracker API access | Tickets are pasted into a fixed Markdown format. Linked documents (test plans, docs) can't be opened, so the relevant part is pasted into the ticket. |
| No container runtime in the work environment yet | The "it loads" check in the sandbox can't run there; collecting a generated test is a manual step for now. |
| Model runs aren't fully repeatable | Some providers expose no temperature setting, so results vary from run to run. Eval numbers from those runs are treated with caution. |
| Keeping private data out | Secret scrubbing and masking before every prompt, a private-term list, a privacy scan before every push, and shared findings written in general words only. |

## 9. Evaluation

**What is measured**

| Area | Metrics |
|---|---|
| Retrieval | recall@k and MRR, against the files changed in a fix or the test linked to a ticket. Each ticket's own test is hidden first (leave-one-out). |
| Faithfulness | Rate of invented names (including page-object chains); draft-matches-ticket by a model judge, marked unvalidated until checked against human labels. |
| Execution (primary) | Validator pass rate on the first attempt and after repair; `pytest --collect-only` pass rate in the sandbox. |
| Outcomes | Gaps reported, vague tickets recognized, legacy tickets kept out of scope. |
| Cost | Model calls, repair rounds and dollar cost per ticket. |
| Fit to the real suite | Validator errors on the suite's own tests (calibration), and peak memory. |

**Results so far** (synthetic practice suite):

- Main practice tickets: all generated, all pass every check after repair, all load in the
  sandbox, about 3 model calls per ticket.
- Held-out tickets in the real suite's shapes: all pass after repair, no invented names; the
  missing-piece and vague tickets were handled as intended, for a few cents per set.
- Missing-piece proposals: each gap got a correct one-line member, and the regenerated tests used
  it.
- Real suite: calibration only so far (about 98% fewer validator errors). Generation on real
  tickets is the next step, so real-suite quality numbers don't exist yet.

## 10. Where it stands

**Done**
- the full pipeline, from ticket to validated test and data;
- the four bounded agents, except log triage;
- the eval harness;
- the stand-in suite (v7);
- calibration against the real suite to a small remainder, mostly real leftovers in the suite
  (old data, retired tests);
- memory fixes;
- pasted tickets.

**Next**
- a trial on a few real tickets, pasted by hand: draft, review, generate, validate, then a
  person collects and runs the tests (started: structure comes out right; meaning doesn't yet);
- the suite's vocabulary and meaning (`docs/knowledge-plan.md`): known values extracted by code,
  a glossary from tracker words to suite words kept current by a model session that can read the
  private code, then area guides by a stronger model, measured after each layer.

**Known limits**
- a test can use a real member that is the wrong one and still pass every check;
- a missing member that needs a new page locator can't be proposed;
- members of pages built by constructors aren't type-checked;
- linked documents aren't read automatically.

**Later**
- revising a draft by instruction (a `revise` step: the person says what to change, the model
  applies it, code checks it); the same, later, for a generated test;
- log triage of real runs;
- reading the tracker through its API, and linked documents through their APIs, once approved;
- learning from review comments and real runs.
