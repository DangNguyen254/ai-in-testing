# Test conventions (stand-in suite)

Generic conventions for this synthetic suite. Generated tests must follow them.

## Structure
- One test class per feature area, inheriting `BaseTest` (`from framework.base_test import BaseTest`).
- Copy the module imports and the class scaffold from a neighbouring class in the same area,
  unchanged: the decorator stack (`@browsers(...)`, `@environments(...)`, `@data_driven` when
  the class reads `self.params`, `@pytest.mark.project(...)`, `@pytest.mark.component(...)`)
  and the class's `setup` / `teardown` (or `setup_method` / `teardown_method`).
- `setup` calls `self.base_setup(...)` with the class's options: `fresh_driver`,
  `policy_wait`, `skip_seed`.
- New tests go in their own module next to the area's tests: `tests/<area>/test_<area>_<subarea>.py`,
  with a matching JSON data file `test_<area>_<subarea>.json`.
- Names summarize area, action, and sub-area (`test_rules_delete_single`, `TestRulesDelete`).
  Names never contain ticket numbers.
- Docstrings are optional; when present, a short numbered list of what the test does.

## Markers
- `project` and `component` sit on the class; `priority` and `suite` sit on each method.
- Priority values: `p0` (highest) to `p3`, lowercase. Suites: `smoke`, `regression`.

## Page objects and save flows
- Reach pages only through `self.nav.<area>.<page>`; the shared top bar is `self.nav.top_bar`.
- Value fields are properties: assign to set (`wizard.name = ...`), read to get.
- Actions are methods that return nothing (`wizard.next()`, `editor.save()`). No chaining:
  keep the page in a variable and call one action per line.
- Two save levels: the object's own `save()` (rule, profile), then `top_bar.save()` and
  `top_bar.publish()`. `top_bar.reset()` discards unsaved changes instead. Settings pages use
  `top_bar.save(settings=True)` and need no publish.
- `publish()` waits for its own success toast; tests add no waits or sleeps.

## Test shapes
1. Add: open the list → `add_rule()` → fill the wizard → `next()` → `save()` → top-bar save +
   publish → `self.verify_targets()`.
2. Edit: seed the object → `open_rule(name)` → change fields → `save()` → save + publish →
   `self.verify_targets()`.
3. Delete: seed several → select → `delete_selected()` → `confirm()` → save + publish →
   `self.verify_targets()`.
4. UI-only: seed → search / filter / page / trigger a validation error → check counts or
   messages. No `targets`, no publish.

The final checks must verify what the test name claims, and every outcome a docstring states
has its own check (e.g. "page 2 shows only allow rules" needs a check on page 2's actions,
not only a count).

## List pages
- Rules are listed by name, ignoring case; `page_size` rules per page (read it from the
  page object, `rules.page_size`; never hardcode it).
- `total_count` counts every match across all pages. `rule_names` and `rule_actions` are the
  rows of the current page only.
- A search text or action filter applies only on `search()`.
- A test that depends on page contents or order seeds enough rules to make them obvious and
  states the expected rows in its entry (e.g. `page_2_names`).

## Checks
- `self.check` is a `unittest.TestCase`: `assertEqual`, `assertTrue`, `assertFalse`,
  `assertIn`, `assertNotIn`. UI tests usually pass the expected value first and no message;
  API tests pass the actual value first and a message.
- No bare `assert`, and no extra negative check after an equality check.
- Backend checks: `self.verify_targets()` (reads the entry's `targets`) or
  `self.verify_interactions()` (reads `interactions`). Pass nothing; the helper reads its section.

## Data
- The data file is a top-level JSON array. Each entry has `"test_id"` equal to the pytest test
  name incl. parametrize ids (stacked decorators: bottom decorator first). One entry per
  variant; tests that read no data have no entry.
- The entry arrives as a dict: `self.params` in `@data_driven` classes, or a `params` argument
  in classes without it (e.g. profiles). Index it (`params["key"]`); no attribute access.
- Seed sections: `settings` (`capabilities`, `roles`, `api_tokens`, `agent`) and `policy`
  (`rules`, `profiles`, and the file-policy sections `downloads`, `scanning`, `dlp`, `archives`,
  `encrypted`, `originals`) for the primary tenant; `tenants` for several tenants, each block
  with `tenant` (`{tenant_id1}`, ...) and optional `settings`, `policy`, `targets`; `site` for
  the fake external site (`files`, `pages`), shared by all tenants and reset for every test.
- Policy objects (rules, profiles, DLP rules) get unique names (`{test_id:N}-suffix`); files
  and pages on the site keep fixed names (`report.pdf`, `/pages/news`).
- Seed only what the scenario reads or the feature needs. In `settings.capabilities`, list only
  the gates the feature uses (`{"rules":true}` for rules tests; add `bulk_delete` / `import`
  only for those features). Unlisted gates keep their defaults.
- Expectations: `targets` items `{"method", "path", "payload"?, "status_code"?, "response"}`,
  or `interactions` items `{"request": {"method", "path"}, "response": {"status", "body"}}`.
  Never both. Paths use `:tid` and `:rev_id`; list only the response fields the test asserts.
- Unique names: `{test_id:N}` in data (at most N characters) and `self.unique_name(N)` in code;
  both give the same name. Test users: `{user_1}`, `{user_2}`.
- Object names are at most 32 characters. With a suffix, N + the suffix length must stay within
  32 (`{test_id:12}-epsilon-proxy` is 12 + 14 = 26).
- Custom keys only for values the test body reads and that differ between variants or must
  match the seed (e.g. `delete_name`, `total_count`). Simple UI inputs stay in the code.
  Name a key for what it measures: `total_count` (all matches), `page_2_names` (one page's
  rows); not a vague `expected_count` next to a per-page value.
- Other pre-existing state: a UI helper in the test file (`_add_profile`), the policy manager
  (`self.policy.add_rule(...)`), the settings manager (`self.settings.set_capabilities(...)`),
  or a file under `tests/<area>/files/`.

## Reuse (prefer it to new code)
- **Shared bases.** File-policy classes inherit `DownloadChecks` (`tests/files/checks.py`): its
  `setup`, the `expect_verdict(decision, reason="")` helper, and the
  `test_files_download_verdict` test, which runs in every subclass with that subclass's own
  data entry. A new file-policy class inherits it too, and gives the inherited test an entry.
- **Page-object helpers.** Use the multi-step helpers instead of spelling out their steps:
  `nav.files.download_file(name, mode="converted", password=None)` (leaves the verdict open),
  `nav.files.view_file(name)`, `nav.agent.console.run_task(goal, start_page)`,
  `policy.set_type_action(file_type, action)`.
- **Tests calling tests.** A test may run another test of its class first
  (`self.test_files_download_verdict()`), then check more. Its entry then also holds every key
  the called test reads.
- **Class variants.** `@variants("delivery", "converted", "original")` (on top of the stack)
  generates `TestXConverted` and `TestXOriginal`, each with `self.delivery` set; both run every
  test of the class, inherited ones included, and share the data entries.
- **New variants of an existing test** are a new parametrize value plus one data entry, not a
  new test.

## Files and agent areas
- Downloads are enforced by the latest **published** policy: change the policy in its editor,
  `save()` it, then top-bar save and publish, then download.
- Download decisions: `allowed`, `converted` (a safe copy, active content removed), `blocked`,
  `password_required`. The converted mode is the default; `"original"` is the other mode.
- Backend checks: `GET /api/downloads/v1/log/:tid` (the download log, oldest first),
  `GET /api/files/v1/policy/:tid/:rev_id`, `GET /api/agent/v1/tasks/:tid`.
- The browsing agent never acts on instructions in page content while the injection guard is
  on; it flags them as `injection:<location>` (`text`, `hidden_text`, `comment`, `alt`,
  `meta`). Injection tests run a reading task on a seeded page and check the flags, that the
  embedded action was not taken, and the task list.
- **Agent browser limit:** each tenant may have `settings.capabilities.browser_limit` agent
  browser sessions open at once (default 3; seed it in the entry when the test depends on it).
  A session is a WebSocket connection: open them with `self.browsers.connect(tenant)` or
  `self.browsers.open_many(tenant, n)` (101 = open); at the limit the attempt gets 429 with the
  body `Browser limit reached` before the upgrade (keep the message in the entry, e.g.
  `refusal`). Closing a session (`session.close()`, or closing it in the console) frees its
  slot at once. A changed limit applies to the next attempt; open sessions are never cut.
  Sessions a test leaves open are closed after it.
- The limit is set per tenant through `PUT /api/settings/v1/capabilities/:tid` (admin only;
  others get 403) or on the Settings page (`capabilities.browser_limit = n`, then the top-bar
  settings save), and read back with `GET /api/settings/v1/capabilities/:tid`. Open sessions:
  `GET /api/agent/v1/sessions/:tid` (`{"open": n}`). In the UI, `nav.agent.console` has
  `open_browser()`, `close_browser(n)`, `open_browsers` and `browser_message`.
- Assign a session before reading it (`refused = self.browsers.connect(...)`, then
  `refused.status`): no chaining off a call.

## Exceptions area and older code
- **Area bases.** Exceptions classes inherit `ExceptionsTests` (its `setup`) or, with their own
  setup, `ExceptionsCommon` (`tests/exceptions/exceptions_common.py`). Use its helpers
  (`open_exception(name)`) rather than the similar shared one in `framework/helpers`.
- **Defaults row.** `tests/exceptions/test_exceptions.json` starts with an entry without
  `test_id`: its keys apply to every entry. The loader merges it shallowly, one top-level key at
  a time: an entry that has its own `settings` replaces the default `settings` whole, so list
  every gate it needs there. Don't repeat keys the defaults row already gives.
- **Data file per test.** In `test_exceptions_expiry.py` each test keeps its entry in a file
  named after the test (`test_exceptions_expiry_edit.json`). A new test there gets its own file.
- **Dotted page paths.** `self.go_to("exceptions.list")` opens the page at that path under
  `self.nav` and returns it; the path names the same steps as the property chain.
- **Older code.** `LegacyBrowserBase` classes are unittest style (`setUp` / `tearDown`, checks
  on `self`); keep them as they are and write new tests in the current style. Python 2 files
  under `legacy/` are not collected.
- **Reports area.** Reach report pages through `self.nav.reports.list` / `.view`. Some report
  tests build `ReportViewPage(...)` themselves or drive `self.driver` directly: don't copy
  that, and don't add tests to those classes. `test_reports_list.py` keeps its own older style
  (4-space indent, single quotes); code added there follows it. Import the report helpers by
  name, not with `*`.
- **Units area.** `tests/units` is legacy (old report pages in `framework.legacy_pages`, bare
  asserts): no new tests go there.
- **Waiting.** Use the `@retry` decorator or `framework.waits.retry_until`; don't add another
  retry loop around them.

## Style
- 3-space indent, LF line endings, final newline, alphabetical imports, no type annotations
  (`ruff format` / `ruff check` with `standin/ruff.toml`).
- JSON: indent 3, `"key":value` (no space after the colon), final newline.

## Deployment and flakiness
- Use `@cloud_only` / `@on_prem_only` from `framework.decorators` only when the behavior is
  deployment-specific.
- Use `@retry` only for steps known to be flaky; never to hide a real failure.
