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
- Seed sections: `settings` (`capabilities`, `roles`, `api_tokens`) and `policy` (`rules`,
  `profiles`) for the primary tenant; `tenants` for several tenants, each block with
  `tenant` (`{tenant_id1}`, ...) and optional `settings`, `policy`, `targets`.
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

## Style
- 3-space indent, LF line endings, final newline, alphabetical imports, no type annotations
  (`ruff format` / `ruff check` with `standin/ruff.toml`).
- JSON: indent 3, `"key":value` (no space after the colon), final newline.

## Deployment and flakiness
- Use `@cloud_only` / `@on_prem_only` from `framework.decorators` only when the behavior is
  deployment-specific.
- Use `@retry` only for steps known to be flaky; never to hide a real failure.
