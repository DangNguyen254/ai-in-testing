# Prompt: fill the glossary's gaps for tickets whose tests weren't found

For Haiku (a Claude Code session on the mentor's account, with access to the private folder, the
tool and the real repo). It is the targeted form of `docs/glossary-prompt.md`: that one maps the
tracker's whole vocabulary; this one takes a short list of tickets where search did not find the
right tests, and adds or sharpens only the entries those tickets need.

When to use it: a placement replay or a golden run shows that, for some tickets, no test of the
right class was retrieved, or its tests ranked below another class's.

What an entry does in the tool, so the session knows what is worth writing:
- A term matches a ticket when it equals one of the ticket's components, labels or its epic, or,
  for a `phrase` term, when the phrase occurs in the ticket's title or description.
- A matched term's `folders` and `classes` lift the tests there in the search ranking (more for
  `confirmed` entries than for `proposed` ones), and its class names, chains, markers and data
  values are added to the search words.
- A `classes` entry lifts the tests of that class's folder that share its component markers, so
  it is sharper than a folder alone in a folder that mixes several features.

What it does not do: it does not make a class without data entries usable as the template.
For a ticket whose right class keeps no data, an entry helps search but may not change where
the test is placed.

**Keep the golden set honest.** The session must not read the golden set, its drafts, or any
run output: an entry written from the reference test would be the answer copied in, and the
scores would measure this session, not the tool. Entries come from the ticket's own words and
from evidence in the suite.

Before pasting: put the ticket file names in the first line (the files in the tickets folder,
not the golden ids).

---

## Prompt (copy from here)

```text
TICKETS_TO_CHECK = <ticket file names, comma-separated, e.g. ABC-123.md, ABC-456.md>

You are improving a glossary for a tool called ticket2test. The tool turns tracker tickets into
tests for a real test suite, and it uses the glossary to translate a ticket's words (component
names, epic names, feature words) into the suite's words (folders, test classes, component
marker values, data keys and values). For the tickets listed above, the tool's search did not
find the tests of the right feature. Your job is to find out which of each ticket's words the
glossary doesn't translate, or translates too broadly, and to add or sharpen those entries,
with evidence from the suite.

Paths:
- PRIVATE = /root/work/t2t-private
- TOOL = /root/work/ai-prj (the tool; read only)
- REPO = /root/work/<repo> (the real suite; read only)
- MAP = PRIVATE/output/map/<repo folder>/ (the suite map: map.json, overview.md, and
  areas/<area>.md with each area's classes, markers, page-object chains, helpers and known
  data values)
- TICKETS = PRIVATE/tickets/ (one Markdown file per ticket)
- GLOSSARY = PRIVATE/glossary.yaml
- UNMAPPED = PRIVATE/glossary-unmapped.txt, if it exists (ticket words the tool met and the
  glossary didn't know)

Rules:
- Read only in REPO, TOOL and MAP. Never run the suite's tests.
- Do NOT open PRIVATE/golden.json, any drafts file or folder in PRIVATE, or anything under
  PRIVATE/output except PRIVATE/output/map. They hold the expected answers for these tickets.
  Work only from the ticket files, the map and the suite.
- Heavy commands one at a time. Don't run the indexer, the map, check-suite or any script that
  walks the whole repo; the map is already built. Searching and reading are fine.
- Write only GLOSSARY. Copy it to GLOSSARY.bak first.
- Never guess. Every mapping cites evidence: path:line in REPO, or the map's area and key. If
  you can't find evidence for a word, leave it out, or list it under `unmapped` with the reason.
- Use the suite's spelling exactly as it appears in REPO or MAP.
- Keep every existing entry. Change an existing entry only to add fields or to correct one the
  evidence contradicts; never set `status: confirmed` yourself, and leave confirmed entries'
  status as it is.
- No secrets, hosts or people's names anywhere, including your chat reply.

For each ticket in TICKETS_TO_CHECK:

1. Its words. Read the ticket file. List:
   a. its routing words: the values under "## Components", "## Epic", "## Labels" (and the
      aliases "## Component", "## Epic link", "## Label");
   b. its feature phrases: the two to five words or short phrases in the title and description
      that name the product feature or the screen being tested (a feature's name, a page's
      name, a setting's name). Not generic words (save, error, user, page, test, list).

2. What the glossary does with them. For each word and phrase from step 1, look in GLOSSARY:
   - not there at all;
   - there, but mapped only to a folder that holds several features (check in MAP how many
     areas and classes the folder has);
   - there, and already mapped to classes or to a folder with one feature: nothing to do.

3. Find the feature in the suite. For each word or phrase in the first two groups, search MAP
   first (area names, class names, component marker values, page-object chains, known data
   values), then confirm in REPO (folder and class names, test names, docstrings, the
   page-object classes its tests use). You are looking for the test class or classes whose
   tests exercise that feature. Evidence is a class name, test names, a docstring, a page
   object or a data key that plainly names the feature, not a single word in passing.
   - Several classes test it: list each of them (at most five; if more, give the folder and say
     so in `note`).
   - Tests for it exist only as a few methods in a large class about something else: give that
     class and say so in `note`.
   - Nothing in the suite tests it: put the word under `unmapped` with that reason. This is a
     useful result; don't stretch a mapping to avoid it.

4. Write the entries.
   - A routing word: add `classes` (and `markers`, `chains`, `data` where the evidence gives
     them) to its entry, or create the entry (kind component, epic or label).
   - A feature phrase: add a `phrase` entry. Write the phrase as it appears in tickets, short
     enough to recur in other tickets about the same feature (two or three words is typical),
     and specific enough not to match unrelated tickets. Check that with a search over TICKETS:
     if the phrase occurs in tickets about other features, make it more specific or drop it.
   - status: proposed; checked: today's date; evidence: the lines you relied on.

The glossary file's shape (YAML; the tool reads exactly this):

    version: 1
    updated: <today>
    terms:
      - term: "<the tracker's word or the phrase, as written>"
        kind: component            # component | epic | label | phrase
        status: proposed
        checked: <today>
        folders: [<repo folder>]              # optional
        areas: [<area name from MAP>]         # optional
        classes: [<path>::<ClassName>]        # optional
        markers: [<component marker value>]   # optional
        data:                                 # optional
          - key: <key path from the known data values>
            values: [<value>, <value>]
        chains: [nav.<area>.<page>]           # optional
        note: one short line on why
        evidence: ["<path>:<line>", "map: <area>, key <key path>"]
    unmapped:
      - term: "<word>"
        kind: phrase
        reason: one short line

Before finishing:
1. Set `updated` to today's date.
2. Check that GLOSSARY parses (from TOOL, after `source PRIVATE/env.sh`):
   uv run --frozen python -c "import yaml; d = yaml.safe_load(open('/root/work/t2t-private/glossary.yaml')); print(len(d['terms']), 'terms,', len(d.get('unmapped', [])), 'unmapped')"
   Fix and retry until it prints the counts, at most 5 times.
3. Reply with a table, one row per ticket, numbers only and no names: routing words (already
   sharp / sharpened / new / unmapped), feature phrases (added / dropped as too broad /
   unmapped), classes named in total, and whether any named class has tests without data
   entries only (yes/no; check a class's data file next to its test file). Then one line: how
   many entries the glossary had before and has now.
4. Stop there. Don't run the tool.
```

---

## After the session

1. Read the new entries in `glossary.yaml` yourself (they are `proposed`). Set the ones you agree
   with to `status: confirmed`: confirmed entries lift search more than proposed ones.
2. Run the placement replay again with `--fresh` (the saved retrievals were made with the old
   glossary) and compare with the last one.
