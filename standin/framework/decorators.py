"""The standard decorator stack and shared method decorators.

Class decorators: platform selection (``browsers``), environment gating (``environments``),
data loading (``data_driven``), class variants (``variants``). Method decorators: ``retry``,
``skip_browser``, ``cloud_only`` / ``on_prem_only``.
"""

import functools
import sys
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


def variants(attribute, *values):
   """Class variants: one generated test class per value, the value set as a class attribute.

   ``@variants("delivery", "converted", "original")`` on ``TestFilesViewer`` generates
   ``TestFilesViewerConverted`` and ``TestFilesViewerOriginal`` (each with ``delivery`` set) in the
   decorated class's module, and keeps the decorated class itself out of collection. The
   generated classes run the same test methods and share their data entries.
   """

   def decorate(cls):
      module = sys.modules[cls.__module__]
      for value in values:
         suffix = "".join(part.title() for part in value.split("_"))
         name = f"{cls.__name__}{suffix}"
         variant = type(name, (cls,), {attribute: value, "__test__": True})
         variant.__module__ = cls.__module__
         variant.__qualname__ = name
         setattr(module, name, variant)
      cls.__test__ = False
      return cls

   return decorate


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
