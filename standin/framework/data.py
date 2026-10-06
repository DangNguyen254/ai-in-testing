"""Per-test JSON data.

Every ``test_<area>.py`` has a ``test_<area>.json`` next to it: a top-level array of entries,
each with an ``id`` equal to the pytest test name including parametrize ids, e.g.
``test_inventory_item_create[1]``. With stacked parametrize decorators the bottom decorator's
value comes first. Tests that read no data may have no entry.

Framework keys: ``settings``, ``policy``, ``tenants``, ``targets`` (seed sections, applied by
the framework before the test), ``interactions`` (expected requests and responses, checked by
``validate_backend``), ``priority`` and ``skip`` (collection overrides). Any other key is a
custom key the test body reads.
"""

import json
from functools import cache

SEED_SECTIONS = ("settings", "policy", "tenants", "targets")


def data_file_for(test_file):
   return test_file.with_suffix(".json")


@cache
def load_entries(data_file):
   if not data_file.is_file():
      return {}
   entries = json.loads(data_file.read_text(encoding="utf-8"))
   return {entry["id"]: entry for entry in entries}


def entry_for(test_file, test_name):
   return load_entries(data_file_for(test_file)).get(test_name)
