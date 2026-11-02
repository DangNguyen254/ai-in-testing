# Plan: giving the model the suite's vocabulary and meaning

*Status, 2026-11-02: A to E are built and were tried on the real suite. None of them showed a
measured improvement in generated tests; see "What happened" at the end and
`docs/trial-findings.md`. Work is paused for a research and design step.*

## Why

The first trials on the real suite showed where generated tests fall short. It is rarely the
structure: area, class, scaffold and suite rules come out right. It is **meaning**:

- **Words don't match.** A ticket says "archiving", the suite's data says `archive`; a feature
  has one name in the tracker and another as a folder or class. The draft then uses the
  tracker's words, and the generated data uses values the suite doesn't know.
- **Values are guessed.** Which URL, which payload field, which user: the model fills them
  without knowing what the suite's code does with each key.
- **Unwritten conventions are missed:** a default priority, sections every entry of an area
  needs, when variants are wanted.

Nobody on the team knows the mapping from tracker words to suite words for the whole codebase,
and it changes as features are added. So it has to be built from the code and kept current,
not written once by hand.

## Who does what

| Who | What | Why them |
|---|---|---|
| The tool's code | **Known values**: every value the suite uses, per data key and per marker; page-object names and chains; helper names, per area | Exact and complete; it is all in the index already. No model should spend effort on what code can count. |
| Haiku (a Claude Code session with access to the private repo) | **The glossary**: tracker words → suite words (area folder, classes, data keys, values), with evidence | It can read the private code and connect the two vocabularies, which neither the developer nor the team can do by hand for the whole suite. |
| API Sonnet (the tool's `guides` step on a stronger model) | **Area guides**: how each area's tests work, its flows (e.g. login and setup), what its helpers check, its conventions | Writing meaning needs the stronger model; one budgeted call per area. |

"API Haiku" and "API Sonnet" mean the models the tool itself calls, set per step in config
(`llm.<provider>.step_models`). The per-ticket steps stay on API Haiku; only the guides step uses
API Sonnet.

## Steps

**A. Known values (code). Built:** part of the suite map (`ticket2test map`). Per area,
`map.json` and `areas/<area>.md` hold the marker values, the page-object chains and actions, the
base-class helpers, and, new, the **known data values**: every data key path (nested as `a.b`,
list items as `a[]`) with its distinct short values and counts; keys whose values nearly all
differ (generated names, payloads) are marked free text instead of listed (limits in `map:`).
The values are kept out of the area summary the guide prompts use. Private output, under the
output folder.

**B. Glossary (Haiku).** The prompt is `docs/glossary-prompt.md` (it also defines the file
format the tool reads, `glossary.yaml` in the private folder). It has Haiku first collect the
tracker's words from the pasted tickets into `tracker/components.txt` and `tracker/epics.txt`
(people add more names later), then read the known-values file, folder,
class and test names, docstrings and comments, the suite's component documentation and
`pytest.ini`, and the tracker's own lists: the names of the project's components and epics,
copied from the tracker (names only). It writes a glossary file the tool reads; each entry maps a
tracker term to suite terms and cites its evidence. A person skims it rather than writing it.

**C. Use both (code).** *Search and area choice built:* with `knowledge.glossary` set, a ticket's
components, labels and epic (and phrase terms in its text) are matched against the glossary;
the matched terms' classes are searched by name, their chains, markers, keys and values join the
search, and their folders decide the area when they point at one (or nudge it among several).
Retrieval records the matched terms and folders. Ticket words the glossary doesn't know, and
mapped folders or classes the suite no longer has, go to `knowledge.unmapped_log` (default
`<glossary>-unmapped.txt`) for the next update. *Draft and generation built too:* the draft (prompt `draft_v4`) gets a
"suite vocabulary for this ticket" block: the matched terms with their folders, classes,
component markers and data values, plus the known values of their areas from the suite map; the
terms' component markers become the draft's component choices. The generation context lists the
known values, in the template's folder, of the keys its entry uses (from the index; free text and
keys with many values left out). Switches and limits: `knowledge.use_in_draft`,
`use_in_generation`, `map_dir`, `max_vocabulary_values`, `max_vocabulary_keys`.
- Draft: known values become the choices the draft picks from (actions, modes, verdicts,
  components); the glossary translates ticket words into suite words.
- Query rewrite and search: ticket words are expanded with their glossary terms.
- Generation context: the known values of the keys the entry uses.

**D. Measure.** The retrieval eval on the pasted mined tickets (same tickets before and after),
and a rerun of the trial tickets: whether URLs, payload fields, users and values come out right.

**E. Area guides (API Sonnet),** through `ticket2test guides` under its dollar cap, then measure
again the same way. Kept after D so each layer's effect can be seen on its own.

## Kept current, not defined once

The suite and the tracker change all the time, so neither the known values nor the glossary is a
one-off.

- **Known values** are derived, never edited: they are written again from the index whenever the
  index is updated (an incremental build), so there is no stale copy to maintain.
- **The glossary** is a living file:
  - each entry carries its evidence (`path:line` or the known-value it maps to), a status
    (`proposed` or `confirmed`) and the date it was last checked;
  - when a ticket uses a word the glossary doesn't have, or a mapped term no longer exists in the
    known values (renamed, removed), the tool records it in an "unmapped / stale" list instead
    of guessing;
  - a Haiku pass works through that list, the new names in the tracker's component and epic
    lists, and the entries whose evidence changed in the code. It updates the file in place,
    keeping confirmed entries unless their evidence is gone.
- **Area guides** are refreshed per area when the area's code changes enough (the guides step
  already records what each guide was built from).

Everything stays private: the known values, the glossary and the guides describe the private
suite and live in the private folder, never in this repo.

## What happened (2026-10-27 to 2026-11-02)

- **A, B, C** were built as planned. The draft prompt moved on to `draft_v6` (a priority guide
  from config; variants only for values the ticket names). The generation context also got the
  known values of the base entry's keys, uncapped for the paths the entry uses.
- **D.** The retrieval eval on the mined tickets showed no gain from the glossary (same hit rate
  at 10; the one miss is a ticket whose linked test doesn't match it). The trial reruns were
  judged by eye, one run at a time, so they don't count as a measurement.
- **E.** Area guides were built for the whole suite by a stronger model through the CLI, one call
  per area (about $11 over two runs; one area failed on a list limit, then fixed). Also built: a
  **framework guide** (`_framework`: base classes, shared helpers, fixtures, how data is loaded),
  read with every area's guide, and prompt revisions (`guide_v3`, `guide_framework_v2`) after a
  Claude Code session checked the guides against the code and found them incomplete and partly
  wrong. The reason: the guide step is one call over material picked by code; it can't open files
  or follow a helper to where it asserts. So a second path was added: **guides written by a
  Claude Code session** with its own tools (`docs/guide-authoring-prompt.md`), stored as
  `<area>.authored.json` and used ahead of the built guide, names checked when loaded. Neither
  kind of guide made a visible difference in the runs so far, and the guides take a large part
  of the context budget.

## Open, for later discussion

- **Input quality** beyond vocabulary: making the QE's test case the input instead of the ticket,
  a "like test X, but…" form, and turning the draft's questions into a short form to fill in.
- **A persistent code-knowledge layer** (method summaries, data-key meanings) as an extension of
  the glossary and guides, and the investigator agent working on top of it.
- **A comparison with a Claude Code session** given the same ticket and test-plan text, to see
  how far the tool's bounded steps are from a full interactive agent.
