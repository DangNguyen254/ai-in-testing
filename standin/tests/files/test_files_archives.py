"""Files: archive extraction and member inspection, and encrypted files."""

import pytest

from framework.decorators import browsers, data_driven, environments
from tests.files.checks import DownloadChecks


@browsers("chrome", "firefox")
@environments("cloud", "on_prem")
@data_driven
@pytest.mark.project("example-project")
@pytest.mark.component("files")
class TestFilesArchives(DownloadChecks):
   @pytest.mark.priority("p0")
   @pytest.mark.suite("regression")
   def test_files_archive_member_blocked(self):
      """
      1. Download an archive with malware in a nested archive member.
      2. The whole archive is blocked, naming the member.
      """
      self.nav.files.download_file(self.params["file"])
      self.expect_verdict("blocked", self.params["member"])
      self.verify_targets()

   @pytest.mark.priority("p2")
   @pytest.mark.suite("regression")
   def test_files_archive_too_deep(self):
      self.nav.files.download_file(self.params["file"])
      self.expect_verdict("blocked", "nested too deeply")
      self.verify_targets()

   @pytest.mark.priority("p2")
   @pytest.mark.suite("regression")
   def test_files_archive_view_members(self):
      """
      1. Run the shared download check for the entry's archive.
      2. The safe viewer lists the archive's members.
      """
      self.test_files_download_verdict()
      self.nav.files.view_file(self.params["file"])
      viewer = self.nav.files.viewer
      self.check.assertEqual("read-only", viewer.mode)
      self.check.assertEqual(self.params["members"], viewer.content.splitlines())

   @pytest.mark.priority("p1")
   @pytest.mark.suite("regression")
   def test_files_encrypted_password_prompt(self):
      """
      1. Download an encrypted file: the password is asked for.
      2. With the right password the converted copy is delivered.
      """
      files = self.nav.files
      files.download_file(self.params["file"])
      self.expect_verdict("password_required")
      verdict = files.verdict
      verdict.password = self.params["password"]
      verdict.submit_password()
      self.expect_verdict("converted")
      self.verify_targets()

   @pytest.mark.priority("p1")
   @pytest.mark.suite("regression")
   def test_files_encrypted_wrong_password(self):
      self.nav.files.download_file(self.params["file"], password=self.params["password"])
      self.expect_verdict("blocked", "wrong password")
      self.verify_targets()
