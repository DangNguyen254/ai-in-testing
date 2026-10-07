"""Files: download policies by file type, and converted vs. original downloads."""

import pytest

from framework.decorators import browsers, data_driven, environments
from tests.files.checks import DownloadChecks


@browsers("chrome", "firefox")
@environments("cloud", "on_prem")
@data_driven
@pytest.mark.project("example-project")
@pytest.mark.component("files")
class TestFilesDownloads(DownloadChecks):
   @pytest.mark.priority("p1")
   @pytest.mark.suite("smoke")
   @pytest.mark.parametrize("file_type", ["exe", "html", "pdf"])
   def test_files_download_type_action(self, file_type):
      self.nav.files.download_file(self.params["file"])
      self.expect_verdict(self.params["decision"])
      self.verify_targets()

   @pytest.mark.priority("p1")
   @pytest.mark.suite("regression")
   def test_files_download_original_blocked(self):
      """
      1. The policy allows only the converted copy.
      2. Downloading the original is blocked; the converted copy is still delivered.
      """
      files = self.nav.files
      files.download_file(self.params["file"], "original")
      self.expect_verdict("blocked", "only the converted copy")
      files.download_file(self.params["file"], "converted")
      self.expect_verdict("converted")
      self.verify_targets()

   @pytest.mark.priority("p2")
   @pytest.mark.suite("regression")
   def test_files_policy_block_type(self):
      """
      1. In the download policy, block docx files; save the policy, then save and publish.
      2. Downloading a docx file is blocked by the published policy.
      """
      policy = self.nav.files.policy
      policy.open()
      policy.set_type_action("docx", "block")
      policy.save()
      self.check.assertEqual("Download policy saved", policy.toast)

      top_bar = self.nav.top_bar
      top_bar.save()
      top_bar.publish()
      self.nav.files.download_file(self.params["file"])
      self.expect_verdict("blocked", "docx files are blocked")
      self.verify_targets()
