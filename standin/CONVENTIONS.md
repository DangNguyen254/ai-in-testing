# Test conventions (stand-in suite)

Generic conventions for this synthetic suite. Generated tests must follow them.

## Structure
- One test class per feature area, inheriting `BaseTest` (`from framework.base_test import BaseTest`).
- New tests for a ticket go in their own module next to the area's tests: `tests/<area>/test_<ticket>.py`.
- Each test module has a JSON data file with the same name (`test_<ticket>.json`), one entry per
  pytest id.

## Markers
- Every test has `priority`, `project`, `component`, and `suite` markers. `project` and `component`
  may sit on the class; `priority` and `suite` sit on the method.
- Priority values: `p0` (highest) to `p3`. Suites: `smoke`, `regression`.

## Data
- Read data only through `self.inputs`, `self.expected`, and `self.data`. No literal test data in code.
- Unique names use the `{{unique}}` placeholder inside the JSON entry (e.g. `"item-{{unique}}"`).
- `seed` describes backend state created before the test; `expected.backend` describes backend
  state checked after it (via `self.assert_backend(...)`).

## Browser steps
- Reach pages only through `self.nav.<area>.<page>`; never construct page objects directly.
- Use page-object methods and properties; never call the driver directly from a test.
- No `time.sleep`; page objects and validation helpers already wait explicitly.

## Deployment and flakiness
- Use `@cloud_only` / `@on_prem_only` from `framework.decorators` only when the behavior is
  deployment-specific.
- Use `@retry` only for steps known to be flaky; never to hide a real failure.
