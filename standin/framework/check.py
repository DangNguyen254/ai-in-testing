"""The framework's test-case assertion object for UI checks (``self.check``)."""


class CheckFailed(AssertionError):
   pass


class Check:
   """Named UI checks with readable failure messages. Use instead of bare ``assert``."""

   def equal(self, actual, expected, what):
      if actual != expected:
         raise CheckFailed(f"{what}: expected {expected!r}, got {actual!r}")

   def true(self, condition, what):
      if not condition:
         raise CheckFailed(f"{what}: expected true")

   def contains(self, container, item, what):
      if item not in container:
         raise CheckFailed(f"{what}: {item!r} not in {container!r}")

   def same_items(self, actual, expected, what):
      if sorted(actual) != sorted(expected):
         raise CheckFailed(f"{what}: expected {sorted(expected)!r}, got {sorted(actual)!r}")
