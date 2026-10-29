# Prompt: build and update the tracker-to-suite glossary

Step B of `docs/knowledge-plan.md`. Give the text below to a model session that can read the
private folder, the tool and the real repo (the same setup as for `docs/company-yaml-prompt.md`).
The same prompt builds the glossary the first time and updates it later: the glossary is a living
file, kept current as tickets, the tracker and the suite change.

---

## Prompt (copy from here)

You are building a glossary for a tool called ticket2test. The tool turns tracker tickets into
tests for a real test suite. Tickets use the tracker's words (component names, epic names,
feature words); the suite uses its own (area folders, test classes, data keys and their values).
Your job is to map the first onto the second, with evidence, so the tool can translate a ticket's
words into the suite's.

Paths:
- PRIVATE = `/root/work/t2t-private`
- TOOL = `/root/work/ai-prj` (the tool; read only)
- REPO = `/root/work/<repo>` (the real suite; read only)
- MAP = `PRIVATE/output/map/<repo folder>/` (the suite map: `map.json`, `overview.md`, and
  `areas/<area>.md` with each area's classes, markers, page-object chains, helpers and, at the end,
  its known data values)
- TICKETS = `PRIVATE/tickets/` (tickets pasted by hand, one Markdown file each)
- TRACKER = `PRIVATE/tracker/` (`components.txt`, `epics.txt`: tracker names, one per line)
- GLOSSARY = `PRIVATE/glossary.yaml`

### Rules
- Read only in REPO, TOOL and MAP. Never run the suite's tests.
- **Heavy commands one at a time.** Don't run the indexer, check-suite, the map or any script
  that walks the whole repo; the map is already built. Searching and reading are fine. A
  background job gets a single monitor, and nothing else heavy starts until it ends.
- Write only `TRACKER/components.txt`, `TRACKER/epics.txt` and `GLOSSARY`. If GLOSSARY exists,
  copy it to `GLOSSARY.bak` first.
- **Never guess.** Every mapping cites evidence: `path:line` in REPO, or the map's area and key.
  If you can't find evidence, put the term under `unmapped` with the reason.
- Use the suite's spelling exactly as it appears in REPO or MAP (area names, class names, key
  paths, values).
- No secrets, hosts or people's names anywhere, including your chat reply.

### Steps

**1. The tracker's words.** From every file in TICKETS, collect the values under `## Components`,
`## Epic` and `## Labels` (and their aliases: `## Component`, `## Epic link`, `## Label`). Add the
new ones to `TRACKER/components.txt` and `TRACKER/epics.txt`: one name per line, kept sorted,
no duplicates, nothing removed (a person adds more later from other tickets). Labels that name
a feature go into `components.txt`; skip labels like a ticket type or status. Also note feature
words that recur in ticket titles (for example a product feature's name) as `phrase` terms for
step 2.

**2. Map each term.** For every name in the two TRACKER files and every phrase from step 1, find
what it corresponds to in the suite. Start from MAP (area names, class names, component marker
values, page-object chains, known data values), then confirm in REPO (folder and class names,
docstrings, comments, the suite's own component documentation and `pytest.ini`). A term can map
to any of:
- **folders**: the repo folders the feature's tests live in. A feature often has one folder
  that the map splits into several areas (one per test module, when the folder is large): then
  give the folder, not one of its areas;
- **areas**: area names from MAP, when the term covers only some of them (or a folder's areas
  differ in a way that matters, e.g. one per platform);
- **classes** (`path::ClassName`) that test it;
- **component marker values** the suite uses for it;
- **data keys and values**: a key path from an area's known data values and the values that
  mean this term (e.g. a tracker word for an action → the action value the data uses);
- **page-object chains** (`nav.<area>.<page>`) for its pages.

Map only what the evidence supports; a term may have just a folder, or just one value.

**3. Update, don't overwrite** (when GLOSSARY already exists):
- keep every entry with `status: confirmed` unless its evidence is gone from REPO or MAP (renamed
  or removed); then set it back to `proposed` and say why in `note`;
- recheck `proposed` entries and update them;
- add the new terms;
- work through the `unmapped` list again: move a term up when evidence now exists;
- set `checked` to today's date on every entry you looked at.

### The glossary file

YAML, exactly this shape (the tool reads it):

```yaml
version: 1
updated: 2026-10-29
terms:
  - term: "Isolation"               # the tracker's word, as written
    kind: component                 # component | epic | label | phrase
    status: proposed                # proposed (written by you) | confirmed (a person checked it)
    checked: 2026-10-29
    folders: [<repo folder>]        # optional: the feature's folder(s), as in the repo
    areas: [<area name from MAP>]   # optional: when only some areas of a folder are meant
    classes: [<path>::<ClassName>]  # optional
    markers: [<component marker value>]          # optional
    data:                                        # optional
      - key: <key path from the known data values>
        values: [<value>, <value>]
    chains: [nav.<area>.<page>]                  # optional
    note: one short line on why
    evidence: ["<path>:<line>", "map: <area>, key <key path>"]
unmapped:
  - term: "<tracker word>"
    kind: epic
    reason: one short line (e.g. "no folder, class or value mentions it")
```

Leave out the optional fields that don't apply. Only you write `proposed`; never set `confirmed`
yourself.

### Before finishing
1. Check that GLOSSARY parses as YAML (from TOOL, after `source PRIVATE/env.sh`):
   `uv run --frozen python -c "import yaml; d = yaml.safe_load(open('PRIVATE/glossary.yaml')); print(len(d['terms']), 'terms,', len(d.get('unmapped', [])), 'unmapped')"`
   (with the real path for PRIVATE). Fix and retry until it prints the counts, at most 5 times.
2. Reply with a short summary in general words: how many terms the TRACKER files hold now, how
   many were mapped (and to what kinds: folders, areas, classes, values), how many are unmapped and the
   common reasons. No term, area, class, key or value names in the reply.
3. Stop there.
