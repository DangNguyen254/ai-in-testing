# Prompt: an independent review of the glossary's proposed entries

For Haiku, in a **new session** that did not write the entries (so it has no stake in them).
`docs/glossary-gaps-prompt.md` writes entries as `proposed`; a person was meant to read them and
set the ones they agree with to `confirmed`. Where the person can't judge an entry (a part of the
suite they don't know), this prompt has a second session check it against the suite instead.

What changes with `confirmed`: a confirmed entry lifts its tests in the search ranking more than
a proposed one, so a wrong confirmed entry does more harm than a wrong proposed one. The review
is therefore strict: an entry is confirmed only when every field in it was checked again from
the suite, and anything unsupported is removed first.

A model's review is not a person's. Each entry it confirms is marked `reviewed: model <date>`,
so the two can be told apart later, and a person can still overrule it.

Paste the block as it is.

---

## Prompt (copy from here)

```text
You are reviewing a glossary for a tool called ticket2test. The tool turns tracker tickets into
tests for a real test suite, and it uses the glossary to translate a ticket's words (component
names, epic names, feature phrases) into the suite's words (folders, test classes, component
marker values, data keys and values, page-object chains).

Another session wrote or reworked the entries with `status: proposed`. You did not write them
and you owe them nothing. Your job is to check each proposed entry against the suite, field by
field, as if you expected it to be wrong, and to mark `confirmed` only what you verified
yourself. You add no new mappings: this is a check, not a second attempt.

Paths:
- PRIVATE = /root/work/t2t-private
- TOOL = /root/work/ai-prj (the tool; read only)
- REPO = /root/work/<repo> (the real suite; read only)
- MAP = PRIVATE/output/map/<repo folder>/ (the suite map: map.json, overview.md, and
  areas/<area>.md with each area's classes, markers, page-object chains, helpers and known
  data values)
- TICKETS = PRIVATE/tickets/ (tickets pasted by hand, one Markdown file each)
- GLOSSARY = PRIVATE/glossary.yaml

Rules:
- Read only in REPO, TOOL, MAP and TICKETS. Never run the suite's tests.
- Do NOT open PRIVATE/golden.json, any drafts file or folder in PRIVATE, or anything under
  PRIVATE/output except PRIVATE/output/map. They hold the expected answers for some tickets.
- Heavy commands one at a time. Don't run the indexer, the map, check-suite or any script that
  walks the whole repo. Searching and reading are fine.
- Write only GLOSSARY. Copy it to GLOSSARY.review.bak first.
- Don't trust an entry's `evidence` or `note`: open what it cites and read it. A citation that
  doesn't say what the entry claims counts as no evidence.
- Don't add folders, classes, markers, data, chains or new terms. You may only remove a field
  value that fails its check, change `status`, and write `note`, `checked` and `reviewed`.
- Entries with `status: confirmed` already: leave them exactly as they are.
- When in doubt, don't confirm. A proposed entry still works; a wrong confirmed one misleads.
- No secrets, hosts or people's names anywhere, including your chat reply.

For each entry with `status: proposed`, check every field it has:

1. folders. Each folder exists in REPO and holds tests of this feature. Open at least two
   test files in it (or the one, if there is only one) and read the test names and docstrings:
   do they exercise what the term names? If the folder holds several unrelated features and
   the entry has no classes or markers to narrow it, the folder alone is too broad: say so in
   `note` and do not confirm.

2. areas. Each area name exists in MAP and belongs to one of the entry's folders.

3. classes. For each path::ClassName: the file exists, the class is in it, and its tests
   exercise the feature. Read the class: its name, its test names, the page objects or
   helpers its tests use. A class that only touches the feature in passing fails. A class in
   which only a few methods are about the feature passes only if `note` already says so.

4. markers. For each value: open the classes of this entry (or, without classes, the test
   classes of its folders) and read their component marker decorator. The value must appear
   there, as the whole value or as one part of a joined value such as "a,b". A value that
   appears only on other features' classes fails.

5. data. For each key and value: the key path is in the area's known data values in MAP, and
   the value occurs under that key in a data file of the entry's folders.

6. chains. For each chain: its steps exist as page-object members in REPO, in that order,
   and the page they reach belongs to this feature.

7. The term itself.
   - component, epic, label: it occurs under that heading in at least one file in TICKETS, or
     in PRIVATE/tracker/components.txt or epics.txt.
   - phrase: search TICKETS for it. Read every ticket it occurs in. If any of them is about a
     different feature than the entry maps to, the phrase is too broad: do not confirm, and
     say so in `note`.
   - Does the ticket's use of the word match the suite feature the entry points at? Read one
     ticket that uses the term and compare what it describes with what the mapped tests do.
     Same word, different feature: fail.

Then decide, per entry:
- Every field passed: set `status: confirmed`.
- Some values failed, and what is left still passes on its own (for example two of three
  classes are right): remove the failed values, say in `note` what was removed and why, then
  set `status: confirmed`.
- What is left is empty, too broad, or the term itself failed check 7: leave `status:
  proposed` and say why in `note`. If nothing in the entry holds, leave it proposed with the
  note; don't delete it.
In every case set `checked` to today's date. On every entry you set to confirmed, add
`reviewed: "model <today's date>"`.

Also check the `unmapped` list: for each word, one search of MAP and REPO for an obvious home.
Don't map it; if you find one, add " (review: may have a home, see <path>)" to its `reason`.

Before finishing:
1. Set `updated` to today's date.
2. Check that GLOSSARY parses (from TOOL, after `source PRIVATE/env.sh`):
   uv run --frozen python -c "import yaml; d = yaml.safe_load(open('/root/work/t2t-private/glossary.yaml')); t = d['terms']; print(len(t), 'terms,', sum(x.get('status') == 'confirmed' for x in t), 'confirmed,', len(d.get('unmapped', [])), 'unmapped')"
   Fix and retry until it prints the counts, at most 5 times.
3. Reply with numbers only, no term, area, class, key or value names:
   - proposed entries reviewed;
   - confirmed as written; confirmed after removing values (and how many values were removed,
     by field: folders, classes, markers, data, chains);
   - left proposed, by reason: folder too broad, phrase too broad, term and feature differ,
     nothing held, other;
   - entries already confirmed and left alone;
   - unmapped words that may have a home.
4. Stop there. Don't run the tool.
```

---

## After the session

1. Look at the counts. Many values removed, or many entries left proposed, means the writing
   session over-reached: read a few of the notes before relying on the rest.
2. Entries you can judge yourself: your reading overrules the model's, either way.
3. Run the placement replay with `--fresh` (the glossary changed the search words).
