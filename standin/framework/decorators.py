"""The standard decorator stack and shared method decorators.

Class decorators: platform selection (``browsers``), environment gating (``environments``),
data loading (``data_driven``). Method decorators: ``retry``, ``skip_browser``,
``cloud_only`` / ``on_prem_only``.
"""

import functools
import time

import pytest
from selenium.common.exceptions import StaleElementReferenceException, TimeoutException

from framework.config import CONFIG

RETRYABLE = (AssertionError, TimeoutException, StaleElementReferenceException)


def browsers(*names):
   """Platform selection: run the class only on these browsers."""
   return pytest.mark.skipif(CONFIG.browser not in names, reason=f"runs only on {', '.join(names)}")


def environments(*deployments):
   """Environment gating: run the class only on these deployment types."""
   return pytest.mark.skipif(
      CONFIG.deployment not in deployments, reason=f"runs only on {', '.join(deployments)}"
   )


def data_driven(cls):
   """Data loading: each test gets its matched data entry as ``self.params``."""
   cls.data_driven = True
   return cls


def retry(times=2, delay=1.0):
   """Re-run a flaky test body up to ``times`` extra times. Flakiness is handled in code."""

   def decorate(func):
      @functools.wraps(func)
      def wrapper(*args, **kwargs):
         for attempt in range(times + 1):
            try:
               return func(*args, **kwargs)
            except RETRYABLE:
               if attempt == times:
                  raise
               time.sleep(delay)
         return None

      return wrapper

   return decorate


def skip_browser(*names, reason):
   return pytest.mark.skipif(CONFIG.browser in names, reason=f"{CONFIG.browser}: {reason}")


cloud_only = pytest.mark.skipif(CONFIG.deployment != "cloud", reason="cloud-only test")
on_prem_only = pytest.mark.skipif(CONFIG.deployment != "on_prem", reason="on-prem-only test")
