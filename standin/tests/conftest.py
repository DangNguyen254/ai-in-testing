"""Suite-wide fixtures and hooks.

Data loading: the base class's framework fixture loads a test's JSON entry (matched by
``test_id`` = the pytest test name) with placeholders resolved, for ``data_driven`` classes
(as ``self.params``) and for tests that take the ``params`` argument (below).

Collection: an entry's ``priority`` replaces the test's priority marker, and its ``skip``
skips that variant, citing the ticket. Reports: each phase's report is kept on the item, and
a failed UI test saves a screenshot and the page source.
"""

from pathlib import Path

import pytest

from framework.data import entry_for


@pytest.fixture
def params(request):
   """The test's data entry as an argument (loaded by the framework fixture)."""
   return request.instance.params


def pytest_collection_modifyitems(items):
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
def pytest_runtest_makereport(item, call):
   outcome = yield
   report = outcome.get_result()
   setattr(item, f"rep_{report.when}", report)
   if report.when == "call" and report.failed and item.instance is not None:
      item.instance.save_failure_artifacts(item.name)
