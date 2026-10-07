"""Files: malware scanning (signature and hash blocklist) and DLP rules."""

import pytest

from framework.decorators import browsers, data_driven, environments
from tests.files.checks import DownloadChecks


@browsers("chrome", "firefox")
@environments("cloud", "on_prem")
@data_driven
@pytest.mark.project("example-project")
@pytest.mark.component("files")
class TestFilesScanning(DownloadChecks):
   @pytest.mark.priority("p0")
   @pytest.mark.suite("smoke")
   def test_files_scan_hash_blocked(self):
      self.nav.files.download_file(self.params["file"])
      self.expect_verdict("blocked", "blocked hash")
      self.verify_targets()

   @pytest.mark.priority("p2")
   @pytest.mark.suite("regression")
   def test_files_scan_disabled_allows(self):
      self.nav.files.download_file(self.params["file"])
      self.expect_verdict("converted")
      self.verify_targets()

   @pytest.mark.priority("p1")
   @pytest.mark.suite("regression")
   @pytest.mark.parametrize("rule_action", ["block", "log"])
   def test_files_dlp_rule_enforced(self, rule_action):
      """
      1. A DLP rule matches the file's content.
      2. A blocking rule blocks the download; a log-only rule delivers it with a finding.
      """
      self.nav.files.download_file(self.params["file"])
      verdict = self.nav.files.verdict
      self.check.assertEqual(self.params["decision"], verdict.decision)
      self.check.assertEqual(self.params["findings"], verdict.findings)
      self.verify_targets()
