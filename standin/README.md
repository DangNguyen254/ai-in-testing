# Stand-in target suite (synthetic)

A small, **invented** test suite that follows the target suite's patterns (see `CLAUDE.md` →
"Target test-suite patterns"), so the ticket2test indexer, generator, validators, and eval
can be built against the real shape without private data. All names are generic and made up;
hosts are `localhost` / `example.com`.

## Layout

```
app/                 tiny fake web app (stdlib http.server): HTML pages + JSON API, in-memory state
framework/
  base_test.py       BaseTest: setup/teardown (data entry, backend reset + seed, lazy browser,
                     failure artifacts, cleanup)
  pages/             page objects, reached as nav.<area>.<page> (inventory, users, orders, settings)
  api_client.py      JSON API client (seed, reset, backend checks)
  validations.py     ValidationMixin (backend assertions) and wait_until
  decorators.py      retry, skip_browser, cloud_only, on_prem_only
  names.py           {{unique}} placeholder + name generator
  data.py            per-test JSON data, keyed by pytest-generated test name
  config.py          STANDIN_* environment settings
tests/<area>/        test_<area>.py + test_<area>.json (one class per area)
tests/conftest.py    applies per-entry priority overrides and ticket skips at collection
tickets/export.json  fake tickets (Jira export shape) for the bugs the tests cover
manifest.json        ground truth: test kind (ui / api / hybrid) and ticket -> tests
tools/build_history.py  builds a throwaway git history where ticket skips are removed by fixes
```

## Patterns it reproduces

- **Markers** on every test: `priority` (p0–p3), `project`, `component`, `suite` (smoke / regression).
- **Data files**: each `test_<area>.py` has `test_<area>.json`. Keys are the pytest test names
  including parametrize ids, e.g. `test_create_item[1]`. With stacked `parametrize`, the bottom
  decorator's value comes first: `test_create_item_rejects_invalid_quantity[0-typed]`.
- **Entries** hold `config` (a large block repeated across entries), `seed` (backend state),
  `inputs`, and `expected` (incl. backend results). Unique names use `{{unique}}`, replaced once
  per run. An entry may set `"priority"` (override) or `"skip": {"ticket", "reason"}`.
- **Test kinds**: 19 UI tests (page objects, then backend checks), 2 pure API tests, 1 hybrid.
- **Deployment skips**: `@cloud_only` / `@on_prem_only` (`STANDIN_DEPLOYMENT`, default `cloud`).
- **Flakiness in code**: `@retry`, explicit waits in `BasePage`; no quarantine.

## Usage

```bash
cd standin
python -m pytest --collect-only -q        # no browser and no network needed
python -m app.server --port 8080          # run the fake app (for real UI runs)
python tools/build_history.py --force     # history in ../.scratch/standin-history
```

Running the tests for real needs the app running and a local Chrome or Firefox
(`STANDIN_BROWSER`). ticket2test itself only collects these tests; generated tests are
executed only inside its sandbox.
