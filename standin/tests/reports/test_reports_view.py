"""One report's view. This class builds the view page with its constructor instead of reaching
it through ``self.nav`` (an older habit the suite still has)."""

import pytest

from framework.base_test import BaseTest
from framework.decorators import browsers, data_driven, environments
from framework.pages.reports import ReportViewPage


@browsers("chrome", "firefox")
@environments("cloud", "on_prem")
@data_driven
@pytest.mark.project("example-project")
@pytest.mark.component("reports")
class TestReportsView(BaseTest):
   def setup(self):
      self.base_setup(fresh_driver=False, policy_wait=False)

   @pytest.mark.priority("p2")
   @pytest.mark.suite("regression")
   def test_reports_view_title(self):
      view = ReportViewPage(self.driver, self.config.base_url, self.config.default_timeout)
      view.open_report(self.params["report"])
      self.check.assertEqual(self.params["title"], view.title)

   @pytest.mark.priority("p3")
   @pytest.mark.suite("regression")
   def test_reports_view_rows(self):
      view = ReportViewPage(self.driver, self.config.base_url, self.config.default_timeout)
      view.open_report(self.params["report"])
      self.check.assertEqual(self.params["rows"], view.row_count)
