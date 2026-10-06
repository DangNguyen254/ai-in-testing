"""Per-test JSON data.

Every ``test_<area>.py`` has a ``test_<area>.json`` next to it: a top-level array of entries,
each with ``test_id`` equal to the pytest test name including parametrize ids, e.g.
``test_rules_add_basic[allow]``. With stacked parametrize decorators the bottom decorator's
value comes first. Tests that read no data may have no entry.

Entry sections:
- seed: ``settings`` and ``policy`` (primary tenant), ``tenants`` (per-tenant blocks with
  ``tenant``, optional ``settings`` / ``policy`` / ``targets``; the first is the primary);
- expectations: ``targets`` (read by ``verify_targets``) or ``interactions`` (read by
  ``verify_interactions``), never both;
- overrides: ``priority``, ``skip``;
- anything else is a custom key the test body reads.
"""

import json
from functools import cache

ID_FIELD = "test_id"
SEED_SECTIONS = ("settings", "policy")


def data_file_for(test_file):
   return test_file.with_suffix(".json")


@cache
def load_entries(data_file):
   if not data_file.is_file():
      return {}
   entries = json.loads(data_file.read_text(encoding="utf-8"))
   return {entry[ID_FIELD]: entry for entry in entries}


def entry_for(test_file, test_name):
   return load_entries(data_file_for(test_file)).get(test_name)


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
