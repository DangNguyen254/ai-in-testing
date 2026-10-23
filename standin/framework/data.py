"""Per-test JSON data.

Every ``test_<area>.py`` has a ``test_<area>.json`` next to it: a top-level array of entries,
each with ``test_id`` equal to the pytest test name including parametrize ids, e.g.
``test_rules_add_basic[allow]``. With stacked parametrize decorators the bottom decorator's
value comes first. Tests that read no data may have no entry.

Two older layouts are supported too:
- a first entry without ``test_id`` holds defaults for every entry in the file; they are merged
  shallowly, one top-level key at a time (an entry's own key replaces the default whole);
- some modules keep one data file per test function, named after it (``test_<name>.json``
  next to the module); it wins over the module's file for that test.

Entry sections:
- seed: ``settings`` and ``policy`` (primary tenant), ``tenants`` (per-tenant blocks with
  ``tenant``, optional ``settings`` / ``policy`` / ``targets``; the first is the primary),
  ``site`` (files and pages on the fake external site, shared by all tenants);
- expectations: ``targets`` (read by ``verify_targets``) or ``interactions`` (read by
  ``verify_interactions``), never both;
- overrides: ``priority``, ``skip``;
- anything else is a custom key the test body reads.
"""

import json
from functools import cache

ID_FIELD = "test_id"
SEED_SECTIONS = ("settings", "policy")


def data_file_for(test_file, test_name=None):
   if test_name:
      own = test_file.with_name(test_name.split("[")[0] + ".json")
      if own.is_file():
         return own
   return test_file.with_suffix(".json")


@cache
def load_entries(data_file):
   if not data_file.is_file():
      return {}
   rows = json.loads(data_file.read_text(encoding="utf-8"))
   defaults = rows[0] if rows and ID_FIELD not in rows[0] else {}
   if defaults:
      rows = rows[1:]
   return {entry[ID_FIELD]: {**defaults, **entry} for entry in rows}


def entry_for(test_file, test_name):
   return load_entries(data_file_for(test_file, test_name)).get(test_name)


def seed_blocks(entry, primary_tenant):
   """Seed blocks per tenant: top-level sections go to the primary tenant."""
   top = {key: entry[key] for key in SEED_SECTIONS if key in entry}
   blocks = [
      {k: v for k, v in block.items() if k in ("tenant", *SEED_SECTIONS)}
      for block in entry.get("tenants", [])
   ]
   if top:
      if blocks and blocks[0]["tenant"] == primary_tenant:
         blocks[0] = {**top, **blocks[0]}
      else:
         blocks.insert(0, {"tenant": primary_tenant, **top})
   return blocks
