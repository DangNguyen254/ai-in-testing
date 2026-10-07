"""Files: safe viewing, for both delivery modes (class variants)."""

import pytest

from framework.decorators import browsers, data_driven, environments, variants
from tests.files.checks import DownloadChecks


@variants("delivery", "converted", "original")
@browsers("chrome", "firefox")
@environments("cloud", "on_prem")
@data_driven
@pytest.mark.project("example-project")
@pytest.mark.component("files")
class TestFilesViewer(DownloadChecks):
   delivery = "converted"

   @pytest.mark.priority("p1")
   @pytest.mark.suite("regression")
   def test_files_viewer_strips_active_content(self):
      """
      1. View a document with active content: it is read-only and the script is gone.
      2. Download it in this class's delivery mode: the verdict fits the mode.
      """
      files = self.nav.files
      files.view_file(self.params["file"])
      viewer = files.viewer
      self.check.assertEqual("read-only", viewer.mode)
      self.check.assertNotIn("<script", viewer.content)

      files.download_file(self.params["file"], self.delivery)
      self.expect_verdict(self.params["decisions"][self.delivery])
