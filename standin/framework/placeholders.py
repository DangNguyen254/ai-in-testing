"""Placeholders in data entries, resolved before a test sees its entry.

- ``{tenant_id1}``, ``{tenant_id2}``, ...: the framework's tenants (1-based)
- ``{user_1}``, ``{user_2}``, ...: the framework's test users (1-based)
- ``{test_id:N}``: a unique name derived from the test id, at most N characters

Request paths use colon placeholders instead (``:tid``, ``:rev_id``); the validation helpers
fill those from the current tenant and its latest policy revision.
"""

import re
import uuid

from framework.config import CONFIG

BRACE = re.compile(r"\{(tenant_id|user_)(\d+)\}|\{test_id:(\d+)\}")
SUFFIX_LENGTH = 6


def unique_suffix():
   return uuid.uuid4().hex[:SUFFIX_LENGTH]


def unique_name(test_id, suffix, limit):
   """``test_rules_add_basic[allow]`` -> ``rules-add-basic-allow-1a2b3c``, cut to ``limit``."""
   stem = re.sub(r"[^a-z0-9]+", "-", test_id.removeprefix("test_").lower()).strip("-")
   room = max(1, limit - SUFFIX_LENGTH - 1)
   return f"{stem[:room].rstrip('-')}-{suffix}"


def resolve(value, test_id, suffix):
   """Replace every brace placeholder in strings inside ``value``."""
   if isinstance(value, str):
      return BRACE.sub(lambda m: _one(m, test_id, suffix), value)
   if isinstance(value, list):
      return [resolve(v, test_id, suffix) for v in value]
   if isinstance(value, dict):
      return {resolve(k, test_id, suffix): resolve(v, test_id, suffix) for k, v in value.items()}
   return value


def _one(match, test_id, suffix):
   kind, number, limit = match.groups()
   if limit is not None:
      return unique_name(test_id, suffix, int(limit))
   accounts = CONFIG.tenants if kind == "tenant_id" else CONFIG.users
   index = int(number) - 1
   if not 0 <= index < len(accounts):
      raise KeyError(f"no account for placeholder {match.group(0)}")
   return accounts[index]
