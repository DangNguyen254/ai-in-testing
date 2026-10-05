"""Suite-wide hooks: data-entry overrides at collection, and results for failure artifacts."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from framework.data import entry_for


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Apply per-entry overrides from the JSON data file.

    - ``"priority": "p2"`` replaces the test's priority marker for that variant.
    - ``"skip": {"ticket": "KEY-123", "reason": "..."}`` skips the variant, citing the ticket.
    """
    for item in items:
        entry = entry_for(Path(item.path), item.name)
        if not entry:
            continue
        if "priority" in entry:
            item.own_markers[:] = [m for m in item.own_markers if m.name != "priority"]
            item.add_marker(pytest.mark.priority(entry["priority"]))
        skip = entry.get("skip")
        if skip:
            item.add_marker(pytest.mark.skip(reason=f"{skip['ticket']}: {skip['reason']}"))


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item: pytest.Item, call: pytest.CallInfo[None]) -> Iterator[None]:
    """Expose each phase's report as ``item.rep_setup`` / ``rep_call`` / ``rep_teardown``."""
    outcome = yield
    report = outcome.get_result()  # type: ignore[attr-defined]
    setattr(item, f"rep_{report.when}", report)
