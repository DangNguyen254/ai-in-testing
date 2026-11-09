# Prompt: survey one area of the real suite (for Haiku)

Give the text below the line to a Claude Code session that can read the real suite. Fill in
`<AREA>` with the folder you want to know about (a path in the suite). The answer comes back
in general terms, so it can be pasted into a ticket2test session.

---

You are reading a test suite (pytest, with its own framework on top) to explain one area of it
to a developer who must not see its code or names. Read only: change, create or run nothing.

**1. Get oriented (short; no report on this part).** Look at the suite's layout, its pytest
configuration, the framework's base test classes, how tests reach pages (page objects) or APIs,
and how tests load their data. Look at two or three areas that keep JSON data files beside
their tests, so you know the usual shape.

**2. Then study the area `<AREA>`.** Read enough of it to be sure a pattern is general (at least
five test files, plus the base classes and helpers they use). Answer:

1. What kind of feature does this area test, in a sentence or two, in generic words?
2. Roughly how many test files, classes and tests? Are they UI tests (page objects), API tests,
   or both?
3. Its tests keep no JSON data file. Where do their inputs and expected values come from
   instead: written in the test, parametrize lists, constants or helpers in other modules,
   fixtures, other files (which format), the environment, or something else? Give the share
   of each if there is more than one way.
4. How does a typical test go, step by step (setup, actions, checks, cleanup)? Describe one
   typical test as a numbered list, in generic words.
5. How are results checked: an assertion object, plain asserts, helpers that check by
   themselves, backend or API calls?
6. What base classes, decorators, markers and setup do its classes use, compared with the areas
   that keep data files? Anything this area does differently?
7. If a new test were added here for a new ticket, what would it need to copy or know that a
   tool reading only this area could miss?

**How to answer:**
- General terms only: no names of classes, functions, files, folders, markers, hosts, users,
  products or values from the suite. Say "a helper that opens the page", "an API client", "a
  constant module", not their names.
- Counts and shapes are fine ("about 40 files", "each test has two parametrize lists").
- If you can't tell, say "unknown" and what you looked for.
- Keep it under about 400 words.
