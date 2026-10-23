"""Waiting helpers (a second retry style next to the ``retry`` decorator)."""

import time


def retry_until(condition, timeout=10.0, interval=0.5):
   """Call ``condition`` until it returns something truthy or ``timeout`` seconds pass."""
   deadline = time.monotonic() + timeout
   while True:
      result = condition()
      if result or time.monotonic() >= deadline:
         return result
      time.sleep(interval)
