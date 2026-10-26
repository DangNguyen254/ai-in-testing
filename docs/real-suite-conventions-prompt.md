# Prompt: write the real suite's conventions doc

Give the text below to a Haiku model running inside a checkout of the real test repo (for example Claude Code opened in that folder). It writes two files that stay in the company environment:

- `CONVENTIONS.md`: set it as `generate.conventions_doc` (or pass it with `--conventions`). It goes **word for word into the generator's context for every test**, so it must be short, specific and written as rules.
- `config-values.md`: the values to copy into `config.yaml` when the tool is set up there, plus the evidence for each rule. It is for you to read, not for the generator.

Unlike the earlier survey prompt, this one asks for **real names**: real classes, helpers, imports, marker values and paths. Nothing from it comes back to this project.

---

## Prompt (copy from here)

You are documenting the conventions of this test suite for an AI tool that writes new tests in it. The tool's generator reads your `CONVENTIONS.md` before writing every test, together with a few similar existing tests. A human reviews every generated test before anyone runs it.

### Ground rules
- **Read only.** Do not change, add, commit or delete anything in the repo except the two output files, which you create in the repo root. Do not install anything.
- **Never run tests**, the app, or anything that talks to a browser, a server or the network. Reading files, searching, and `git log` / `git show` are fine.
- **No secrets or personal data.** Do not copy passwords, tokens, keys, connection strings, internal hostnames or IP addresses, email addresses, or people's names. Write `<secret>`, `<host>` or `<user>` where one would go.
- **Use the real names.** Write the real class, module, helper, fixture, decorator and marker names, and the exact import lines. Do not generalize or invent examples: every name you write must exist in the repo, and every code sample must be copied from it or made only of its real names.
- **Rules come from evidence.** Before writing a rule, look at enough files to know it holds. Read at least 3 test files in each of the 8 largest areas, plus the base test class, the shared helpers, the data loader and 2 page objects. If the suite does something two ways, say which one new tests should use (the newer or more common one) and name the other so the tool recognizes it.
- Write rules as instructions ("Do X", "Never Y"), not as descriptions.

### File 1: `CONVENTIONS.md`

**Hard limit: 1,800 words** (the tool's context is small). Spend the words on rules a test writer could get wrong, not on what the code already makes obvious. Use these sections, in this order:

1. **Where new tests go.** The file and folder layout, how test modules and data files are named and paired, and when to add a method to an existing class versus writing a new module. The naming rules for modules, classes and methods, and the docstring habit.
2. **Class scaffold.** The base class(es) to inherit and when each is used. The exact import block a typical UI test file starts with. The standard decorator stack in source order, with what each decorator does (platform, environment / deployment gating, data loading, project / component markers). The usual `setup` / `teardown` or `setup_method` / `teardown_method` shapes, the base-setup options and when to use each. Include one real, complete class header plus `setup`, copied from a typical file.
3. **Markers.** Which markers sit on the class and which on each method. The exact approved values for priority, suite, project and component, with exact casing. How several values are joined in one marker, if they are.
4. **Page objects and navigation.** How tests reach pages (the root object and its property chains, or helpers that take a path string; name them). Value fields versus actions. Save flows: the object's own save, the shared top bar's save, publish and reset, settings pages. Which actions wait internally, so the test adds no waits.
5. **Test shapes.** For each common shape (add, edit, delete, UI-only, and any shape specific to this suite), the order of steps as one line, using the real method names. Then one complete real test of the most common shape, copied from the repo (pick a short one).
6. **Checks.** The assertion object and its methods, the argument order habit, and when a message is passed. The backend validation helpers, which data section each one reads, and how a test calls them. What the final checks must cover. What never to do (bare `assert`, redundant negative checks, and so on).
7. **Test data.** The data file format (top-level shape, the identifier field, how parametrized ids are written). How a test reads its entry (`self.params`, a `params` argument). The seed sections and the expectation sections and what goes in each. Placeholders in paths and in values (tenant, users, unique names and their length limit), and the helper that returns the same unique name in code. A defaults entry, if one exists, and how it merges. One short real entry, copied, with any secret replaced.
8. **Reuse before writing.** The shared helpers, fixtures and mixins new tests should call instead of re-implementing: one line each, `name(args)`: what it does. At most 25, the most used first.
9. **Environments and flakiness.** Deployment gating (cloud-only, on-prem-only and so on), capability or feature-flag setup, retries and explicit waits: how tests handle each.
10. **Never.** The mistakes an automated writer would make here, each as one "Never ..." line with the reason, for example raw driver calls in tests, locator constants used in tests, sleeps, hardcoded ids or names, ticket numbers in names, or editing framework code.
11. **Older code.** Areas or patterns that are legacy (another base class, Python 2 files, old-style tests): how to recognize them, and that new tests do not copy them.

### File 2: `config-values.md`

No word limit. Two parts.

**Part A: values for the tool's `config.yaml`.** Fill in this table from the repo. Write "not found" when something isn't there; do not guess.

| Setting | What to write |
|---|---|
| `markers.priorities` | the priority values, highest first |
| `markers.suites` | the suite values |
| `markers.project` | the project value(s) |
| component values | every component value seen, with exact casing |
| `markers.required` | the markers every test or class carries |
| `markers.value_separator` | how joined values are separated, or "" |
| `data.format` | top-level array of entries, or an object keyed by test id |
| `data.id_field` | the entry key holding the test id |
| `data.access` | how tests read their entry (`self.params`, `params`, ...) |
| `data.seed_sections` | the sections the framework applies before the test |
| `data.expectation_sections` | each expectation section and the helper that reads it |
| `data.per_entry_keys` | keys that belong to one entry only (priority, skip, ...) |
| defaults row | does a defaults entry exist; its id; how it merges |
| per-function data files | do some tests have their own data file; how they are named |
| `style.python` | indent width, line length, quote style, line endings, annotations used or not |
| `style.json` | indent, key and item separators, non-ASCII escaped or not |
| `validation.base_classes` | the base classes test classes inherit |
| `validation.assertion_object` | the assertion object as tests write it |
| `validation.raw_driver_access` | the ways a test could reach the raw browser driver |
| `validation.path_string_helpers` | helpers that take a dotted page path string |
| `validation.naming` | regexes for module, class and test method names |
| `validation.name_max_length` | the app's name length limit used with unique names |
| `validation.unique_name_helper` | the helper that returns the unique name in code |
| `validation.unique_name_pattern` | the unique-name placeholder as written in data |
| `validation.external_modules` | third-party modules tests import |
| `validation.capability_path` | where capability or feature gates live in the data, if anywhere |
| `generate.domain_globs` | the folder pattern of feature areas (for example `tests/*`) |
| `index.chain_roots` | the root names page-object chains start from |
| `generate.reuse.frozen_classes` | classes that new methods must never be added to |
| sandbox needs | Python version, requirements file(s), anything collection needs that isn't in the repo |

**Part B: evidence.** For each section of `CONVENTIONS.md`, list the 2 to 4 files (with line numbers) the rules came from. Then list anything you were unsure about, as questions for a human.

Before you finish, check `CONVENTIONS.md`: under 1,800 words; every name in it exists in the repo; no secrets, hosts, emails or people's names; every rule is an instruction.
