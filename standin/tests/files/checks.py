"""Shared base for file-policy test classes (not collected itself: no ``Test`` prefix).

Every file-policy class inherits ``DownloadChecks``: its ``setup``, the ``expect_verdict``
helper, and the ``test_files_download_verdict`` test, which runs once per subclass with that
subclass's data entry (download the entry's file, check the verdict and the download log).
"""

import pytest

from framework.base_test import BaseTest


class DownloadChecks(BaseTest):
   def setup(self):
      self.base_setup(fresh_driver=False)

   def expect_verdict(self, decision, reason=""):
      """Check the open verdict page: the decision and (if given) part of the reason."""
      verdict = self.nav.files.verdict
      self.check.assertEqual(decision, verdict.decision)
      if reason:
         self.check.assertIn(reason, verdict.reason)

   @pytest.mark.priority("p1")
   @pytest.mark.suite("regression")
   def test_files_download_verdict(self):
      """
      1. Download the entry's file (with its password, if any).
      2. The verdict and the download log match the published policy.
      """
      self.nav.files.download_file(
         self.params["file"], self.params.get("mode", "converted"), self.params.get("password")
      )
      self.expect_verdict(self.params["decision"], self.params.get("reason", ""))
      self.verify_targets()
