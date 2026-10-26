# Stand-in target suite (synthetic)

A small, **invented** test suite that follows the target suite's patterns (see `CLAUDE.md` →
"Target test-suite patterns"), so the ticket2test indexer, generator, validators, and eval
can be built against the real shape without private data. All names are generic and made up;
hosts are `localhost` / `example.com`.

Version 3 (Phase 3b) follows the human's second comparison with the real framework: an
editable per-tenant policy with a shared top bar, the four UI test shapes, per-class `setup`,
a `unittest.TestCase` assertion object, and `targets` / `interactions` expectations.

## The fake app

Each tenant has a **policy** (rules and profiles) and **settings** (capability gates, user
roles, API-token state). Object editors write a working copy ("Unsaved changes"); the top bar
saves it as the draft, publishes the draft as a new revision, or resets. The JSON API serves
published revisions at `/api/policy/v1/{policy,rules,profiles}/<tenant>/<rev_id>` and settings
at `/api/settings/v1/settings/<tenant>`; `PUT /api/policy/v1/rules/<tenant>` needs the admin role.

## Layout

```
app/                 the fake policy app (stdlib http.server): HTML pages + JSON API
framework/
  base_test.py       BaseTest: framework fixture (data entry, setup/teardown), base_setup
                     options (fresh_driver, policy_wait, skip_seed), login_as / logout,
                     unique_name, self.check (unittest.TestCase), managers
  decorators.py      class stack: browsers, environments, data_driven;
                     methods: retry, skip_browser, cloud_only, on_prem_only
  validations.py     verify_targets / verify_interactions: subset compare, :tid / :rev_id
  placeholders.py    {tenant_id1}, {user_1}, {test_id:N}
  managers.py        PolicyManager, SettingsManager (state without the UI)
  pages/             nav.top_bar, nav.rules.*, nav.profiles.*, nav.settings.capabilities
  api_client.py      JSON API client (returns status and body)
  data.py            per-test JSON data: an array of entries with test_id
  config.py          STANDIN_* environment settings, framework tenants and users
tests/<area>/        test_<area>.py + test_<area>.json (one class per area); rules/files/
tests/conftest.py    params fixture; priority overrides and ticket skips; failure artifacts
tickets/export.json  fake tickets (Jira export shape) for the bugs the tests cover
manifest.json        ground truth: test kind (ui / api / hybrid) and ticket -> tests
tools/build_history.py  builds a throwaway git history where ticket skips are removed by fixes
ruff.toml            the suite's style: 3-space indent, LF, sorted imports
```

## Patterns it reproduces

- **Test shapes:** add (wizard → object save → top-bar save + publish → `targets`), edit,
  delete (select → confirm), and UI-only (search, filter, pagination, validation errors);
  also reset instead of publish, a blocked save, and the settings save option.
- **Class scaffold:** `@browsers`, `@environments`, `@data_driven`, project and component
  markers; per-class `setup` calling `base_setup` with options; a class that logs in as a
  second tenant in `setup` and logs out in `teardown`; a runtime-style API class with
  `setup_method` / `teardown_method`.
- **Data access:** `self.params` in most classes; a `params` argument in `TestProfiles`.
- **Data files:** `[{"test_id": "test_rules_add_basic[allow]", ...}]`, seed in `settings` /
  `policy` / `tenants`, one expectation section per entry, a large policy block repeated
  across the list tests, custom keys only where variants differ. Tests without data have no
  entry.
- **Other state:** a UI helper (`_add_profile`), the policy and settings managers, and an
  import file (`tests/rules/files/rules_import.json`).
- **Test kinds:** 24 UI tests, 3 pure API tests (a permission test with PUT + 403), 1 hybrid.
- **Skips:** platform (`STANDIN_BROWSER`), deployment (`STANDIN_DEPLOYMENT`, default `cloud`),
  per-browser (`@skip_browser`), and by ticket id in a data entry.

- **v6 (real-suite shapes, exceptions area):** a large page-object module with a component
  base; area bases three to four levels deep; a unittest-style base (`setUp`, `self.assert*`);
  a defaults row (merged shallowly) and per-function data files; navigation by dotted page
  path (`go_to`); twelve one-element widget tests; a cloud-only class gated by `skipif`; a
  joined component marker (`exceptions,rules`); two classes in one module; near-duplicate
  helpers, a `_v1` module pair and three retry styles; a Python 2 leftover kept out of
  collection. Tickets STND-129..136 (dev) and STND-137..144 (held-out test set), including
  missing-piece and vague tickets.
- **v7 (older code in a mixed area, and a legacy area):** the reports area has a file in another
  style (4-space indent, single quotes) with a star import and a test that calls another test,
  a class that builds its page with the constructor, and a class that drives the browser
  directly. The units area is legacy: unittest style with bare asserts, an old page object with
  the same class name as the current one (`ReportListPage`), and a module that reads the
  deployed runtime settings at import (`framework.runtime_config`: it needs
  `STANDIN_RUNTIME_ROOT` and `runtime.ini` there; the sandbox uses the stub in
  `sandbox/stubs/`). Tickets STND-146, 147 (dev) and STND-148, 149 (held out).

## Usage

```bash
cd standin
STANDIN_RUNTIME_ROOT=<folder with runtime.ini> python -m pytest --collect-only -q
                                          # no browser and no network needed
python -m app.server --port 8080          # run the fake app (for real UI runs)
python tools/build_history.py --force     # history in ../.scratch/standin-history
ruff format --check . && ruff check .     # style (uses ruff.toml here)
```

Running the tests for real needs the app running and a local Chrome or Firefox
(`STANDIN_BROWSER`). ticket2test itself only collects these tests; generated tests are
executed only inside its sandbox.
