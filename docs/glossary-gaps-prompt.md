# Prompt: update the glossary after new tickets, and fill its gaps

For Haiku (a Claude Code session on the mentor's account, with access to the private folder, the
tool and the real repo). It replaces `docs/glossary-prompt.md` for updates: it does everything
that prompt does (collect the tracker's words from every pasted ticket, map each to the suite,
update without overwriting), and adds what the first glossary lacked:

- it rereads **every** ticket in the tickets folder, so tickets pasted after the glossary was
  built are covered;
- every term gets a **component marker check** and, where the evidence exists, the **classes**
  that test the feature, not only a folder;
- it adds **feature phrases** from ticket titles and descriptions, so a ticket whose component
  says little still matches a term;
- entries the first pass left empty (no folders, classes or markers) are worked through again.

When to use it: new tickets were pasted since the glossary was last built, or a placement
replay or golden run shows tickets whose tests weren't found, or whose matched terms carry no
markers, classes or folders.

What an entry does in the tool, so the session knows what is worth writing:
- A term matches a ticket when it equals one of the ticket's components, labels or its epic, or,
  for a `phrase` term, when the phrase occurs in the ticket's title or description.
- A matched term's `folders` and `classes` lift the tests there in the search ranking (more for
  `confirmed` entries than for `proposed` ones), and its class names, chains, markers and data
  values are added to the search words.
- A `classes` entry lifts the tests of that class's folder that share its component markers, so
  it is sharper than a folder alone in a folder that mixes several features.
- A term's `markers` are the choices the draft's component is picked from and, with
  `knowledge.use_in_templates`, count as the ticket's components when the template test is
  chosen. Many classes carry no component marker; for those only `classes` and `folders` help.

What it does not do: it does not make a class without data entries usable as the template.

**Keep the golden set honest.** The session must not read the golden set, its drafts, or any
run output: an entry written from the reference test would be the answer copied in, and the
scores would measure this session, not the tool. Entries come from the tickets' own words and
from evidence in the suite.

Before pasting: add the tracker's component and epic names you can export (names only, one per
line) to `tracker/components.txt` and `tracker/epics.txt` in the private folder. The more of
the tracker's vocabulary is there, the more the glossary covers beyond the pasted tickets.

---

## Prompt (copy from here)

```text
You are updating a glossary for a tool called ticket2test. The tool turns tracker tickets into
tests for a real test suite. Tickets use the tracker's words (component names, epic names,
feature words); the suite uses its own (area folders, test classes, component marker values,
data keys and their values). The glossary maps the first onto the second, with evidence, so the
tool can translate a ticket's words into the suite's.

A glossary already exists. It was built when fewer tickets had been pasted, and many of its
entries carry little: a folder only, or nothing. Your job is to bring it up to date with every
ticket that is there now, and to make each entry as specific as the evidence allows.

Paths:
- PRIVATE = /root/work/t2t-private
- TOOL = /root/work/ai-prj (the tool; read only)
- REPO = /root/work/<repo> (the real suite; read only)
- MAP = PRIVATE/output/map/<repo folder>/ (the suite map: map.json, overview.md, and
  areas/<area>.md with each area's classes, markers, page-object chains, helpers and known
  data values)
- TICKETS = PRIVATE/tickets/ (tickets pasted by hand, one Markdown file each)
- TRACKER = PRIVATE/tracker/ (components.txt, epics.txt: tracker names, one per line)
- GLOSSARY = PRIVATE/glossary.yaml
- UNMAPPED = PRIVATE/glossary-unmapped.txt, if it exists (ticket words the tool met and the
  glossary didn't know, and mapped names the suite no longer has)

Rules:
- Read only in REPO, TOOL and MAP. Never run the suite's tests.
- Do NOT open PRIVATE/golden.json, any drafts file or folder in PRIVATE, or anything under
  PRIVATE/output except PRIVATE/output/map. They hold the expected answers for some of these
  tickets. Work only from the ticket files, the tracker files, the map and the suite.
- Heavy commands one at a time. Don't run the indexer, the map, check-suite or any script that
  walks the whole repo; the map is already built. Searching and reading are fine. A background
  job gets a single monitor, and nothing else heavy starts until it ends.
- Write only TRACKER/components.txt, TRACKER/epics.txt and GLOSSARY. Copy GLOSSARY to
  GLOSSARY.bak first.
- Never guess. Every mapping cites evidence: path:line in REPO, or the map's area and key. If
  you can't find evidence for a word, list it under `unmapped` with the reason.
- Use the suite's spelling exactly as it appears in REPO or MAP (area names, class names,
  marker values, key paths, values).
- No secrets, hosts or people's names anywhere, including your chat reply.

Step 1. The tracker's words, from every ticket.
Read every file in TICKETS, including the ones the glossary has seen before. From each, collect:
  a. the routing words: the values under "## Components", "## Epic" and "## Labels" (and the
     aliases "## Component", "## Epic link", "## Label"). Add the new ones to
     TRACKER/components.txt and TRACKER/epics.txt: one name per line, kept sorted, no
     duplicates, nothing removed. Labels that name a feature go into components.txt; skip
     labels like a ticket type or status.
  b. the feature phrases: the two to five words or short phrases in the title and description
     that name the product feature or the screen being tested (a feature's name, a page's
     name, a setting's name). Not generic words (save, error, user, page, test, list).
Also read UNMAPPED if it exists: its words are candidates too.

Step 2. Sort every word and phrase against the glossary as it is now:
  - not there at all: map it (step 3);
  - there, but the entry has no folders, classes or markers, or only a folder that holds
    several features (check in MAP how many areas and classes the folder has): map it again
    (step 3);
  - there under `unmapped`: try again (step 3), and move it up if evidence now exists;
  - there with classes, or with a folder that holds one feature, and markers checked: only
    confirm its evidence still exists in REPO or MAP.

Step 3. Find the feature in the suite.
Search MAP first (area names, class names, component marker values, page-object chains, known
data values), then confirm in REPO (folder and class names, test names, docstrings, comments,
the page-object classes its tests use, the suite's own component documentation and pytest.ini).
You are looking for the test class or classes whose tests exercise that feature. Evidence is a
class name, test names, a docstring, a page object or a data key that plainly names the
feature, not a single word in passing. For each term, fill what the evidence supports:
  - folders: the repo folder(s) the feature's tests live in. When the map splits one folder
    into several areas, give the folder, not one of its areas;
  - areas: area names from MAP, when the term covers only some areas of a folder;
  - classes (path::ClassName): the classes that test it. Several: list each (at most five; if
    more, give the folder and say so in `note`). Only a few methods in a large class about
    something else: give that class and say so in `note`;
  - markers: ALWAYS check this. Look at the component marker on each class you named (a class
    decorator; a joined value such as "a,b" counts as each of its parts) and list the values.
    When the tracker's word and the suite's marker value are spelled differently, this is the
    entry's most useful field. When the classes carry no component marker, write "no component
    marker on its classes" in `note`, so the next reader knows it was checked;
  - data: a key path from an area's known data values and the values that mean this term
    (e.g. a tracker word for an action -> the action value the data uses);
  - chains: page-object chains (nav.<area>.<page>) for its pages.
Nothing in the suite tests it: put the word under `unmapped` with that reason. This is a useful
result; don't stretch a mapping to avoid it.

Step 4. Write the entries.
  - A routing word: its own entry (kind component, epic or label).
  - A feature phrase: a `phrase` entry. Write the phrase as it appears in tickets, short enough
    to recur in other tickets about the same feature (two or three words is typical), and
    specific enough not to match unrelated tickets. Check that with a search over TICKETS: if
    the phrase occurs in tickets about other features, make it more specific or drop it.
  - New and reworked entries: status proposed. Set `checked` to today's date on every entry
    you looked at, and list the evidence you relied on.
  - Update, don't overwrite: keep every entry. An entry with status confirmed keeps its status
    when you only add fields the evidence supports; if its own evidence is gone from REPO or
    MAP (renamed or removed), set it back to proposed and say why in `note`. Never set
    confirmed yourself.

The glossary file's shape (YAML; the tool reads exactly this):

    version: 1
    updated: <today>
    terms:
      - term: "<the tracker's word or the phrase, as written>"
        kind: component            # component | epic | label | phrase
        status: proposed           # proposed (written by you) | confirmed (a person checked it)
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
        reason: one short line (e.g. "no folder, class or value mentions it")

Leave out the optional fields that don't apply.

Before finishing:
1. Set `updated` to today's date.
2. Check that GLOSSARY parses (from TOOL, after `source PRIVATE/env.sh`):
   uv run --frozen python -c "import yaml; d = yaml.safe_load(open('/root/work/t2t-private/glossary.yaml')); print(len(d['terms']), 'terms,', len(d.get('unmapped', [])), 'unmapped')"
   Fix and retry until it prints the counts, at most 5 times.
3. Reply with a short summary in numbers only, no term, area, class, key or value names:
   - tickets read, and how many of them were new to the glossary;
   - terms before and after; by kind (component, epic, label, phrase);
   - terms with folders, with classes, with markers, with none of the three; terms whose
     classes carry no component marker;
   - entries reworked, entries moved up from unmapped, unmapped now and the common reasons;
   - phrases dropped as too broad;
   - how many named classes have no data entries at all (check the data file next to the
     class's test file).
4. Stop there. Don't run the tool.
```

---

## After the session

1. Read the new and reworked entries in `glossary.yaml` yourself (they are `proposed`). Set the
   ones you agree with to `status: confirmed`: confirmed entries lift search more than proposed
   ones.
2. Run the placement replay again with `--fresh` (the recorded replies were made with the old
   glossary's search words) and compare with the last one.
