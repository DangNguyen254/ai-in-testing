"""Unique names for test data.

Data files never hardcode unique names. They use the placeholder token, and each test run
replaces it with one fresh suffix, so names stay unique across parallel runs.
"""

import uuid

PLACEHOLDER = "{{unique}}"


def unique_suffix():
   return uuid.uuid4().hex[:8]


def unique_name(prefix):
   return f"{prefix}-{unique_suffix()}"


def resolve_placeholders(value, suffix):
   """Replace every placeholder token in strings inside ``value`` with ``suffix``."""
   if isinstance(value, str):
      return value.replace(PLACEHOLDER, suffix)
   if isinstance(value, list):
      return [resolve_placeholders(v, suffix) for v in value]
   if isinstance(value, dict):
      return {k: resolve_placeholders(v, suffix) for k, v in value.items()}
   return value
