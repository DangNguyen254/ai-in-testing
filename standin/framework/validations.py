"""Backend validation helpers. Each reads its own expectation section from ``self.params``.

- ``verify_targets()``: ``targets`` items ``{method, path, payload?, status_code?, response}``
  (top level for the primary tenant, and inside each ``tenants`` block for that tenant)
- ``verify_interactions()``: ``interactions`` items
  ``{request: {method, path}, response: {status, body}}`` (primary tenant)

Responses are compared as a subset. Paths may contain ``:tid`` and ``:rev_id``, filled from
the tenant and its latest published revision.
"""

import time


class BackendMismatch(AssertionError):
   pass


def matches_subset(actual, expected, where="response"):
   """Every field in ``expected`` must equal the same field in ``actual``.

   Dicts compare key by key (extra keys in ``actual`` are fine); lists compare item by item
   by position (``actual`` may be longer); other values compare with ``==``.
   """
   if isinstance(expected, dict):
      if not isinstance(actual, dict):
         raise BackendMismatch(f"{where}: expected an object, got {actual!r}")
      for key, value in expected.items():
         if key not in actual:
            raise BackendMismatch(f"{where}.{key}: missing")
         matches_subset(actual[key], value, f"{where}.{key}")
   elif isinstance(expected, list):
      if not isinstance(actual, list) or len(actual) < len(expected):
         count = len(expected)
         raise BackendMismatch(f"{where}: expected at least {count} items, got {actual!r}")
      for index, value in enumerate(expected):
         matches_subset(actual[index], value, f"{where}[{index}]")
   elif actual != expected:
      raise BackendMismatch(f"{where}: expected {expected!r}, got {actual!r}")


def fill_path(path, tenant, rev_id):
   return path.replace(":tid", tenant).replace(":rev_id", str(rev_id))


class ValidationMixin:
   policy_wait = True
   api_user = None  # the user the requests run as; None: the framework's service account

   def verify_targets(self):
      checks = [(self.primary_tenant, item) for item in self.params.get("targets", [])]
      for block in self.params.get("tenants", []):
         checks += [(block["tenant"], item) for item in block.get("targets", [])]
      for number, (tenant, item) in enumerate(checks, start=1):
         self._check(
            f"target {number}",
            tenant,
            item["method"],
            item["path"],
            item.get("payload"),
            item.get("status_code", 200),
            item.get("response"),
         )

   def verify_interactions(self):
      for number, interaction in enumerate(self.params.get("interactions", []), start=1):
         request, response = interaction["request"], interaction["response"]
         self._check(
            f"interaction {number}",
            self.primary_tenant,
            request["method"],
            request["path"],
            request.get("body"),
            response.get("status", 200),
            response.get("body"),
         )

   def _check(self, label, tenant, method, path, payload, status, expected):
      user = self.api_user or self.config.service_user
      attempts = self.config.validation_attempts if self.policy_wait else 1
      for attempt in range(1, attempts + 1):
         filled = fill_path(path, tenant, self.api.revision(tenant))
         actual_status, body = self.api.request(method, filled, payload, user)
         try:
            where = f"{label} ({method} {filled})"
            if actual_status != status:
               raise BackendMismatch(f"{where}: status {actual_status}, expected {status}")
            if expected is not None:
               matches_subset(body, expected, f"{where} response")
            return
         except BackendMismatch:
            if attempt == attempts or method != "GET":
               raise
            time.sleep(0.5)
