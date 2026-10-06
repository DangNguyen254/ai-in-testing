"""Suite-wide fixtures and hooks.

Data loading: a test's JSON entry (matched by ``id`` = the pytest test name) arrives as a dict,
with placeholders resolved and its seed sections already applied to the backend:

- ``load_params``: used by the ``data_driven`` class decorator; sets ``self.params``.
- ``params``: the same entry as a test argument, for classes that take it that way.

Collection: an entry's ``priority`` replaces the test's priority marker, and its ``skip``
skips that variant, citing the ticket. Reports: each phase's report is kept on the item, and
a failed UI test saves a screenshot and the page source.
"""

from pathlib import Path

import pytest

from framework.data import SEED_SECTIONS, entry_for
from framework.names import resolve_placeholders, unique_suffix


def _matched_entry(request):
   entry = entry_for(Path(request.node.path), request.node.name) or {}
   entry = resolve_placeholders(entry, unique_suffix())
   sections = {key: entry[key] for key in SEED_SECTIONS if key in entry}
   if sections:
      request.instance.api.seed(sections)
   return entry


@pytest.fixture
def load_params(request):
   request.instance.params = _matched_entry(request)


@pytest.fixture
def params(request):
   entry = _matched_entry(request)
   request.instance.params = entry
   return entry


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
