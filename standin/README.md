# Stand-in target suite (synthetic)

A small, **invented** test suite that follows the target suite's patterns (see `CLAUDE.md` →
"Target test-suite patterns"), so the ticket2test indexer, generator, validators, and eval
can be built against the real shape without private data. All names are generic and made up;
hosts are `localhost` / `example.com`.

Version 2 (Phase 3b) follows the human's comparison with the real framework: class decorator
stack, property page objects, an assertion object, array data files with `id`, and
`interactions` as backend expectations.

## Layout

```
app/                 tiny fake web app (stdlib http.server): HTML pages + JSON API, in-memory
                     state with settings, a policy, users, items, and orders
framework/
  base_test.py       BaseTest: setup_method / teardown_method (API client, assertion object,
                     backend reset, lazy browser, failure artifacts)
  decorators.py      class stack: browsers, environments, data_driven;
                     methods: retry, skip_browser, cloud_only, on_prem_only
  check.py           Check: the assertion object for UI checks (self.check.equal, ...)
  validations.py     ValidationMixin.validate_backend: replays `interactions`, subset compare
  pages/             page objects, reached as nav.<area>.<page>; properties + action methods
  api_client.py      JSON API client (seed by section, reset, resources)
  names.py           {{unique}} placeholder + name generator
  data.py            per-test JSON data: an array of entries with `id` = pytest test name
  config.py          STANDIN_* environment settings
tests/<area>/        test_<area>.py + test_<area>.json (one class per area)
tests/conftest.py    load_params / params fixtures; priority overrides and ticket skips at
                     collection; failure artifacts
tickets/export.json  fake tickets (Jira export shape) for the bugs the tests cover
manifest.json        ground truth: test kind (ui / api / hybrid) and ticket -> tests
tools/build_history.py  builds a throwaway git history where ticket skips are removed by fixes
ruff.toml            the suite's style: 3-space indent, LF, sorted imports
```

## Patterns it reproduces

- **Class scaffold**: `@browsers`, `@environments`, `@data_driven`, `project` and `component`
  markers on every class; `priority` and `suite` on every test.
- **Data access**: `self.params` (via `@data_driven`) in most classes; a `params` argument in
  `TestOrders`. Tests index the dict; the framework applies the seed sections first.
- **Data files**: `[{"id": "test_inventory_item_create[1]", ...}]`. With stacked
  `parametrize`, the bottom decorator's value comes first:
  `test_inventory_item_create_invalid_quantity[0-typed]`. Tests without data have no entry.
- **Entries**: `settings` and a large `policy` block pasted into every entry of an area, the
  policy named after the test (`"policy-inventory-item-create"`); variants differ by one or two
  values; `interactions` list requests and the asserted response fields; custom keys such as
  `item_name`. An entry may set `"priority"` or `"skip": {"ticket", "reason"}`.
- **Test kinds**: 22 UI tests, 2 pure API tests, 1 hybrid.
- **Skips**: platform (`STANDIN_BROWSER`), deployment (`STANDIN_DEPLOYMENT`, default `cloud`),
  per-browser (`@skip_browser`), and by ticket id in a data entry.
- **Flakiness in code**: `@retry`, explicit waits in `BasePage`; no quarantine.

## Usage

```bash
cd standin
python -m pytest --collect-only -q        # no browser and no network needed
python -m app.server --port 8080          # run the fake app (for real UI runs)
python tools/build_history.py --force     # history in ../.scratch/standin-history
ruff format --check . && ruff check .     # style (uses ruff.toml here)
```

Running the tests for real needs the app running and a local Chrome or Firefox
(`STANDIN_BROWSER`). ticket2test itself only collects these tests; generated tests are
executed only inside its sandbox.
