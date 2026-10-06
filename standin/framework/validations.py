"""Backend validation: replay the entry's ``interactions`` and compare responses as a subset."""

from framework.api_client import ApiError


class BackendMismatch(AssertionError):
   pass


def matches_subset(actual, expected, where="body"):
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


class ValidationMixin:
   def validate_backend(self, params=None):
      """Send each request in ``interactions`` and check the response status and body."""
      params = self.params if params is None else params
      for number, interaction in enumerate(params.get("interactions", []), start=1):
         request = interaction["request"]
         expected = interaction["response"]
         try:
            status, body = (
               200,
               self.api.request(request["method"], request["endpoint"], request.get("body")),
            )
         except ApiError as error:
            status, body = error.status, {"error": error.message}
         where = f"interaction {number} ({request['method']} {request['endpoint']})"
         if status != expected.get("status", 200):
            raise BackendMismatch(f"{where}: status {status}, expected {expected['status']}")
         if "body" in expected:
            matches_subset(body, expected["body"], f"{where} body")
