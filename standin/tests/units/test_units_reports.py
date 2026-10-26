"""The oldest report checks (a legacy area): unittest style with bare asserts, the old report
page (same class name as the current one, another module), and the deployed runtime settings,
which are read when this module is imported."""

import pytest

from framework import runtime_config
from framework.decorators import browsers, environments
from framework.legacy_base import LegacyBrowserBase
from framework.legacy_pages.reports import ReportListPage


@browsers("chrome")
@environments("cloud", "on_prem")
@pytest.mark.project("example-project")
@pytest.mark.component("units")
class TestUnitsReports(LegacyBrowserBase):
   @pytest.mark.priority("p3")
   @pytest.mark.suite("regression")
   def test_units_reports_names(self):
      page = ReportListPage(self.driver)
      page.go(self.config.base_url)
      assert page.get_names() == self.params["names"]
      assert runtime_config.MODE in ("cloud", "on_prem")
