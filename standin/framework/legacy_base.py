"""Older browser tests, unittest style.

pytest runs these as ``unittest.TestCase`` classes: ``setUp`` and ``tearDown`` (not ``setup``)
do the per-test work, and the checks assert on ``self``. The framework fixture still loads the
data entry first, so ``self.params`` is ready in ``setUp``.
"""

import unittest

from framework.base_test import BaseTest


class LegacyBrowserBase(BaseTest, unittest.TestCase):
   data_driven = True

   def setup(self):
      """The framework fixture's hook does nothing here: setUp does the work."""

   def setUp(self):
      self.base_setup(fresh_driver=False, policy_wait=True)

   def tearDown(self):
      self.logout()
