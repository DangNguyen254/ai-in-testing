# Plan: giving the model the suite's vocabulary and meaning

*Status: planned, October 2026. Nothing here is built yet; this is the agreed order of work.*

## Why

The first trials on the real suite showed where generated tests fall short. It is rarely the
structure: area, class, scaffold and suite rules come out right. It is **meaning**:

- **Words don't match.** A ticket says "isolation", the suite's data says `isolate`; a feature
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

**B. Glossary (Haiku).** A prompt in `docs/` has Haiku read the known-values file, folder,
class and test names, docstrings and comments, the suite's component documentation and
`pytest.ini`, and the tracker's own lists: the names of the project's components and epics,
copied from the tracker (names only). It writes a glossary file the tool reads; each entry maps a
tracker term to suite terms and cites its evidence. A person skims it rather than writing it.

**C. Use both (code).**
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

## Open, for later discussion

- **Input quality** beyond vocabulary: making the QE's test case the input instead of the ticket,
  a "like test X, but…" form, and turning the draft's questions into a short form to fill in.
- **A persistent code-knowledge layer** (method summaries, data-key meanings) as an extension of
  the glossary and guides, and the investigator agent working on top of it.
- **A comparison with a Claude Code session** given the same ticket and test-plan text, to see
  how far the tool's bounded steps are from a full interactive agent.
