# Test conventions (stand-in suite)

Generic conventions for this synthetic suite. Generated tests must follow them.

## Structure
- One test class per feature area, inheriting `BaseTest` (`from framework.base_test import BaseTest`).
- Every class carries the standard decorator stack, copied unchanged from a neighbouring test
  in the same area, in this order:
  `@browsers(...)`, `@environments(...)`, `@data_driven` (when the class reads `self.params`),
  `@pytest.mark.project(...)`, `@pytest.mark.component(...)`.
- New tests go in their own module next to the area's tests: `tests/<area>/test_<area>_<subarea>.py`,
  with a matching JSON data file `test_<area>_<subarea>.json`.
- Names summarize area, action, and sub-area (`test_orders_detail_cancel`,
  `TestOrdersDetail`). Names never contain ticket numbers.
- Docstrings are optional; when present, a short numbered list of what the test does.

## Markers
- `project` and `component` sit on the class; `priority` and `suite` sit on each method.
- Priority values: `p0` (highest) to `p3`, lowercase. Suites: `smoke`, `regression`.

## Page objects
- Reach pages only through `self.nav.<area>.<page>`; never construct page objects directly.
- Value fields are properties: assign to set (`editor.quantity = "5"`), read to get.
- Actions are methods that return nothing (`editor.open()`, `editor.save()`). No chaining:
  keep the page in a variable and call one action per line.
- Never call the driver directly from a test. No `time.sleep`; pages wait explicitly.

## Checks
- UI checks use the assertion object: `self.check.equal(actual, expected, "what")`,
  `self.check.true(...)`, `self.check.contains(...)`, `self.check.same_items(...)`.
  No bare `assert`, and no extra negative check after an equality check.
- Backend checks use `self.validate_backend()` (or `self.validate_backend(params)`), which
  replays the entry's `interactions` and compares each response as a subset.

## Data
- The data file is a top-level JSON array. Each entry has `"id"` equal to the pytest test name
  incl. parametrize ids (stacked decorators: bottom decorator first). One entry per variant;
  tests that read no data have no entry.
- The entry arrives as a dict: `self.params` in `@data_driven` classes, or a `params` argument
  in classes without it (e.g. orders). Index it (`params["key"]`); no attribute access.
- Framework keys: `settings`, `policy`, `tenants`, `targets` (seed sections, applied before the
  test), `interactions` (backend expectations), `priority`, `skip`. Other keys are custom keys
  the test body reads (e.g. `item_name`, `count`).
- Build a new entry from the nearest existing entry: copy its `settings`/`policy` blocks
  verbatim, rename self-referencing values (`"policy-<test name>"`), then change only the
  unique parts.
- Unique names use the `{{unique}}` placeholder (e.g. `"item-{{unique}}"`).
- Simple UI inputs (a role, a timezone, a note text) stay in the test code unless several
  variants need different values.
- `interactions`: `{"request": {"method", "endpoint", "body"?}, "response": {"status", "body"?}}`;
  list only the response fields the test asserts.

## Style
- 3-space indent, LF line endings, final newline, alphabetical imports, no type annotations
  (`ruff format` / `ruff check` with `standin/ruff.toml`).
- JSON: indent 3, `"key":value` (no space after the colon), final newline.

## Deployment and flakiness
- Use `@cloud_only` / `@on_prem_only` from `framework.decorators` only when the behavior is
  deployment-specific.
- Use `@retry` only for steps known to be flaky; never to hide a real failure.
