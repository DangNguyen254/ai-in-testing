# Prompt: fill the private `company.yaml` from `config-values.md`

Give the text below to a model session that can read the private folder and the real repo (the
same setup used for `docs/real-suite-conventions-prompt.md`). It turns the table in
`config-values.md` into ticket2test config overrides, keeps what `company.yaml` already holds,
and checks that the result loads. Adjust the three paths at the top if yours differ.

---

## Prompt (copy from here)

You are filling in the private config of a tool called ticket2test so that it describes a real
test suite. Three paths:

- PRIVATE = `/root/work/t2t-private` (the private folder: `config-values.md`, `company.yaml`)
- TOOL = `/root/work/ai-prj` (the tool; read only)
- REPO = `/root/work/<repo>` (the real test suite; read only)

### Rules
- Write only `PRIVATE/company.yaml`, and first copy it to `PRIVATE/company.yaml.bak`. Change
  nothing in TOOL or REPO.
- **Keep every key `company.yaml` already has, with its value** (paths, llm, index.ignore,
  index.max_file_bytes, index.test_paths, style.python.target_version, generate.domain_globs,
  generate.reuse.legacy_domains). Add new keys around them; merge into existing sections.
- Use only keys that exist in `TOOL/config.yaml`, spelled exactly as there, in the same
  nesting. `TOOL/config.yaml` also shows each key's format and meaning in its comments.
- Write a value only when `config-values.md` gives it or you confirm it in REPO. After every
  value, a comment with where it came from: `# config-values.md` or `# evidence: path:line`.
- If a value is "not found" or unclear, leave the key out (the default stays) and add a comment
  line `# TODO <key>: <what is missing>` at the end of the file.
- No secrets: no keys, tokens, passwords, hosts or people's names. Marker values, class names,
  helper names and folder names of the suite are fine (this file stays private).
- Exact casing for every marker value and name.

### Keys to fill (from `config-values.md` Part A)

| Key | What it holds |
|---|---|
| `markers.priorities` | priority values, highest first |
| `markers.suites` | suite values |
| `markers.project` | the main project value |
| `markers.required` | marker names every test (or its class or module) carries |
| `markers.value_separator` | the separator of joined values, without spaces (`", "` is written `","`); `""` if never joined |
| `data.format`, `data.id_field`, `data.access` | data file layout, the id key, how tests read their entry |
| `data.seed_sections`, `data.expectation_sections`, `data.per_entry_keys` | sections the framework applies, expectation section -> the helper that reads it (`self.<helper>`), keys handled per entry |
| `data.defaults_row`, `data.defaults_merge` | whether a defaults entry exists; `shallow`, `shallow_if_set` (an empty or false entry value keeps the default) or `deep` |
| `data.allowed_expectation_sets` | expectation sections an entry may carry together, e.g. `[[targets, interactions]]` |
| `style.python.indent_width`, `line_length`, `quote_style`, `strip_annotations` | the suite's formatter settings (most files) |
| `style.json.indent`, `key_separator`, `item_separator`, `final_newline` | data file formatting (most files) |
| `validation.base_classes` | the root base classes test classes inherit (several allowed) |
| `validation.assertion_object` | the assertion object as tests write it, e.g. `self.<name>` |
| `validation.assertion_methods` | the assert methods called on it |
| `validation.raw_driver_access` | expressions that reach the raw browser driver directly (not the framework's own wrappers) |
| `validation.path_string_helpers` | helpers that take a dotted page path string |
| `validation.naming.module`, `test_class`, `test_function` | full-match regexes the suite's names fit |
| `validation.name_keys`, `placeholder_pattern`, `unique_name_pattern`, `name_max_length` | seeded-name keys, any data placeholder (regex), the unique-name placeholder (regex, group 1 = max length), the name length limit |
| `validation.unique_name_helper` / `unique_name_helpers` | the helper returning the unique name in code; or base class name -> helper when bases differ |
| `validation.external_modules` | third-party top-level packages tests and framework import |
| `index.chain_roots` | the root attribute(s) page-object chains start from (`self.<root>....`) |
| `generate.reuse.frozen_classes` | classes new methods must never go into |
| `generate.deployment_decorators`, `generate.deployment_gate_patterns` | how a class is limited to cloud or on-prem (a decorator name, a whole decorator expression, or regexes) |
| `generate.placeholder_token` | the unique-name placeholder as written in new data, with a typical length |

Two defaults describe the tool's own practice suite and are wrong for a real one unless the
suite has the same thing. Set them explicitly:
- `validation.capability_gates`: component -> feature gates its tests seed; `{}` if the suite
  has nothing like it.
- `validation.paging_actions` and `validation.constant_properties`: page-object methods for
  paging and the page-size property; `[]` if none.

### Check before finishing
1. Run, from TOOL:
   `T2T_CONFIG=/root/work/t2t-private/company.yaml uv run --frozen python -c "from ticket2test.config import load_settings; load_settings(); print('config ok')"`
   (with the same `UV_PROJECT_ENVIRONMENT` and `UV_CACHE_DIR` as in `PRIVATE/env.sh`, or after
   `source /root/work/t2t-private/env.sh`)
   It must print `config ok`. If it prints an error, fix the key it names and run it again (at
   most 5 times).
2. Show a short summary: the keys you added, the keys you kept, and the TODO lines.
