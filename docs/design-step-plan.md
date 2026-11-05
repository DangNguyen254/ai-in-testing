# Design step: why the trial loop drifted, and a plan to get out of it

*Written 2026-11-02, after reading `trial-findings.md`, `project-overview.md`, `project-report.md`
and `knowledge-plan.md`; updated the same day with a review of the structure-aware
(code-graph) research direction (§4a). Names nothing from the real suite.*

## 1. Diagnosis in one paragraph

The 31 problems are not 31 independent bugs. They come from four root causes, and only one of
them is "the model is weak". The loop drifted because **changes were judged by single,
nondeterministic runs**, so noise looked like regressions and lucky runs looked like fixes. Until
there is a fixed yardstick, every fix is a guess, and the pipeline keeps growing (more LLM steps,
more context, more warnings) without anyone knowing what helps.

## 2. The 31 problems, grouped by root cause

| Root cause | Problems | What it means |
|---|---|---|
| **R1. No measurement** | all; explicitly "still open" list | One run per change, judged by eye, on a provider with no temperature. Effect of a change is mixed up with run-to-run variance. |
| **R2. The model is asked to write what it can't know** | 12, 13, 17, 18, 19, 26 (and the "values only a person knows") | Which helper to call, what a helper already asserts, which data blocks belong together, real payloads. Free-text code generation lets the model fill these gaps by guessing, copying internals, or inventing data. |
| **R3. Weak signals turned into actions** | 21, 22, 24 (and 17 via 21) | Heuristic warnings with unknown precision start repair rounds. A false warning becomes a code change, and the change itself is a new source of variance (the inlining in 17 came from this). |
| **R4. Context crowded by always-on pieces** | 26, 27, 17 | Guides and large base entries are always in; the helper code and similar tests that would actually help get dropped. Helper *bodies* in context invite copying instead of calling. |
| Placement / draft rules | 1–11, 14–16, 20, 23 | Mostly real, local bugs. Fine to fix, but only with R1 in place so a fix is confirmed, not assumed. |
| Ops | 28–31 | Process issues; already worked around. Not design problems. |

Takeaway: R1 is the meta-problem that caused the whack-a-mole; R2 is the main quality ceiling; R3
and R4 are self-inflicted by the fixes.

## 3. What the research says (short)

- **Error analysis before fixes.** The standard practice for LLM products is: read 20–50 outputs,
  write a free-form note on each (open coding), group the notes into a small failure taxonomy
  (axial coding), count, and fix the most frequent category first. This is exactly the step the
  trial skipped; it picked "the last problem seen" instead of "the most common problem".
- **Measure reliability, not one run.** τ-bench's `pass^k` (does the task succeed in *all* k
  runs?) exposes inconsistency that a single run hides; strong agents scoring ~60% once fell
  below 25% at k=8. Your trial symptoms (an old problem "coming back") are what low `pass^k`
  looks like.
- **Generate, filter, discard; don't keep repairing.** Meta's TestGen-LLM treats every LLM output
  as a candidate and keeps only those passing progressively stricter filters (builds, passes
  reliably, adds value); 73% of what survived was accepted by engineers. Agentless (SWE-bench)
  does the same: several candidates, filter by tests, rerank, pick one, and beat agent systems at
  a tenth of the cost. Nondeterminism becomes useful when you sample and select.
- **Less, better context; fetch just in time.** Anthropic's context-engineering guidance: the
  smallest set of high-signal tokens, a few canonical examples over long rule lists, and
  retrieval on demand rather than pre-loading. Your own finding (a model that can open files
  beat a stronger model with a fixed excerpt) matches this.
- **Structure-aware repository understanding** (code graphs, GraphRAG, multi-level summaries,
  graph-querying agents such as CodexGraph, RepoMind, CatCoder). See §4a for how it maps onto
  this project. Short version: most of it is already built here; the useful part is new *kinds*
  of edges and a way to tell retrieval failures from generation failures.

## 4a. Where the structure-aware direction fits

| The direction proposes | Already in this project |
|---|---|
| Tree-sitter parsing, symbol nodes | The index: chunks and the symbol catalog |
| `EXTENDS`, `CALLS`, `IMPORTS`, fixture edges | Class hierarchy, callers/callees, import maps, setup/teardown/fixture reach |
| Lexical search + graph expansion | BM25 + grep + RRF, then the expand step |
| An agent with hierarchy/caller/callee tools | The investigator's tools |
| Multi-level summaries | Area and framework guides (tried; incomplete, partly wrong, no visible effect) |
| Verification feedback | 31 validators, repair loop, sandbox collect |

**Why it is not the main direction here:** the trial got the area and usually the class right.
The failures were in *meaning* (helpers copied instead of called, missing blocks, made-up
values), which happen after retrieval. It is also written for statically typed code; this suite
is Python, where constructor-built pages and property chains are exactly where static analysis
is weakest (already a known limit). Embeddings, a graph database and 50–200 hand-labelled
questions target no problem seen so far.

**What is taken from it:**

1. **New kinds of edges, not more of the same.** The graph records who calls what, not what code
   *means*. Add, all extracted by code:
   - `ASSERTS`: this helper asserts X (directly, by waiting on a condition, or by raising);
   - `READS_KEY`: it reads data keys K (the data-use analysis already computes this);
   - `DELEGATES_TO`: it hands work to framework object F, which asserts and returns events (#18);
   - `CO_OCCURS`: these data blocks always appear together in the class's entries (#13, #15).

   These feed D2 (contract cards).
2. **Score the context, not just the output** (criterion C8 below). It splits each failure into
   "retrieval missed it" and "the model had it and didn't use it", which decides whether to
   invest in retrieval/graph work or in D1/D2.
3. **Which relations matter, and how deep to expand** become ablations in Step 3.
4. **Tools versus fixed context** is answered by the Step 5 comparison.

## 4. The plan

### Step 1. Build the yardstick (before any further fix)

1. **Freeze a baseline**: tag the current `trial-fixes` commit as `baseline-0`.
2. **Golden set**: 10–15 real tickets, from 2–3 areas (not only the trial area), each with the
   test a person actually wrote. Hidden with `--hide` during the run.
3. **Criteria, binary, mostly code-graded** against the reference test:

   | # | Criterion | Graded by |
   |---|---|---|
   | C1 | Same file/class as the reference | code |
   | C2 | Helpers called ⊇ helpers the reference calls (no inlined internals) | code (call sets from the AST) |
   | C3 | Data entry has the blocks the reference entry has | code (key paths) |
   | C4 | No value unsupported by ticket / template / area data | code (existing warning) |
   | C5 | Number of variants = reference | code |
   | C6 | Checks cover the expected outcome | person, once per output (yes/no) |
   | C7 | Validators pass, collect passes | code (exists) |
   | C8 | **Context recall**: the context sent to the generator contained the helpers and data blocks the reference uses | code (compare the context's chunk ids and entry keys with C2/C3's sets) |

   Reading C8 with C2/C3: C8 fails → retrieval missed it (graph/retrieval work helps).
   C8 passes but C2/C3 fail → the model had it and didn't use it (D1/D2 help).

4. **Runs**: k = 3 per ticket (5 for the final comparison). Report per criterion: pass@1 and
   `pass^3`. Haiku cost is cents per run, so a full sweep is a few dollars.
5. **Harness additions**: a `--repeat k` option, a `compare-to-reference` scorer (C1–C5), and a
   context-recall scorer (C8) in `eval/generation.py`. Leave-one-out already exists.

### Step 2. Error analysis on what you already have

- Open-code the existing trial logs plus the baseline-0 golden runs: one sentence per output,
  first failure only.
- Group into fewer than 10 failure modes and count them. The table in §2 is a starting
  hypothesis, not the result.
- **Rule from now on:** one change per experiment, chosen from the top failure mode, kept only if
  it moves its criterion on the golden set without lowering another.

### Step 3. Ablate the trial additions (answers question 7)

Run the golden set with each of these switched off, one at a time, against baseline-0:
area/framework guides, glossary in draft and generation, coverage check, warning-started repair,
helper code in context, raised context budget. Anything without a measured gain is removed. This
probably makes the pipeline smaller and cheaper, and lowers variance.

Then, on retrieval (scored by C8): which expansion relations matter (callers, callees, hierarchy,
tests-using, page chains), and how deep (one hop, two hops). Only worth running if C8 shows
retrieval misses at all.

### Step 4. Design changes to test (each as a Step-2 experiment)

| Change | Targets | Idea |
|---|---|---|
| **D1. Helpers chosen, not written** | R2: 17, 18, 19 | Same move already made for data entries: the model returns a *plan* (ordered steps, each a helper/page-object member from a menu with its arguments); code writes the calls. Inlining becomes impossible by construction. Free-text code only for steps no member covers, and those are flagged. |
| **D2. Helper contract cards from code** | R2, R4: 13, 15, 18, 26, 27 | Per helper, from the new edges (§4a): signature, `READS_KEY`, `ASSERTS` (on what), what it returns, `DELEGATES_TO` (followed one level into the framework object). Per class, the `CO_OCCURS` block groups. A few lines each, shown instead of helper bodies. Replaces most of what the guides tried to say, deterministically and current. |
| **D3. Gaps, not guesses** | R2: 12, values only a person knows | Payloads, page text, users: written as explicit placeholders (`<FILL: …>`) plus a checklist line, never invented. Hand-over becomes "test + data with marked gaps" (question 1). |
| **D4. Warnings go to the reviewer, not to repair** | R3: 21, 22, 24 | Repair only on errors. Measure each warning's false-positive rate on `check-suite` (known-good tests); a warning earns the right to start repair only if it is rarely wrong there. |
| **D5. Sample and select** | R1 variance | Generate 3 candidates, keep the one with fewest validator findings (tie: closest to the template's helper set). Compare cost vs. one generation + repair rounds. |
| **D6. "Like test X, but…" input** | 1, 13 | Optional field in the pasted ticket: the QE names the nearest test. Fixes placement and base entry at almost no cost. |

### Step 5. One upper-bound comparison (answers question 5)

Give a Claude Code session the same golden tickets (ticket text + read access to the suite) and
score its output with the same criteria. If it is far ahead on C2/C3/C6, the gap is knowledge
access, and a bounded generation agent with the investigator's tools is worth designing. If not,
stay with the fixed pipeline plus D1–D3. This is also the test of the structure-aware
direction's last idea: an agent querying the graph versus one fixed context.

## 5. Order and stopping rule

1. Step 1 → 2 → 3 (about a week; no new features).
2. Read C8 against C2/C3: if failures are mostly "had it, didn't use it", go to D1/D2; if mostly
   "retrieval missed it", do the retrieval ablations and graph edges first.
3. Then D1–D4 in the order the failure counts say, one at a time.
3. Stop adding when the top failure mode is "values only a person knows" — that is the floor for
   any tool, and D3 already handles it honestly.

## Sources

- [Hamel Husain & Shreya Shankar, LLM Evals FAQ (error analysis, open/axial coding)](https://hamel.dev/blog/posts/evals-faq/)
- [Yao et al., τ-bench and the pass^k metric (ICLR 2025)](https://proceedings.iclr.cc/paper_files/paper/2025/hash/1b126cc38b8638e07bef37e7b2bb72bf-Abstract-Conference.html)
- [Alshahwan et al., Automated Unit Test Improvement using LLMs at Meta (TestGen-LLM, FSE 2024)](https://arxiv.org/abs/2402.09171v1)
- [Xia et al., Agentless: Demystifying LLM-based Software Engineering Agents](https://huggingface.co/papers/2407.01489)
- [Anthropic, Effective context engineering for AI agents](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents)
- Structure-aware direction (from the reviewed note): [knowledge-graph repository code generation](https://arxiv.org/html/2505.14394), [CodexGraph](https://arxiv.org/html/2408.03910), [RepoMind](https://dl.acm.org/doi/abs/10.1145/3794763.3794823), [CatCoder](https://dl.acm.org/doi/full/10.1145/3779217), [deterministic AST graphs and their limits](https://web3.arxiv.org/pdf/2601.08773)
