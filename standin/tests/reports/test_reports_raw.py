"""Report list messages, checked by driving the browser directly (no page object)."""

import pytest
from selenium.webdriver.common.by import By

from framework.base_test import BaseTest
from framework.decorators import browsers, data_driven, environments


@browsers("chrome", "firefox")
@environments("cloud", "on_prem")
@data_driven
@pytest.mark.project("example-project")
@pytest.mark.component("reports")
class TestReportsRaw(BaseTest):
   def setup(self):
      self.base_setup(fresh_driver=False, policy_wait=False)

   @pytest.mark.priority("p3")
   @pytest.mark.suite("regression")
   def test_reports_raw_empty_message(self):
      self.driver.get(self.config.base_url.rstrip("/") + "/reports?q=none")
      message = self.driver.find_element(By.ID, "reports-empty").text
      self.check.assertEqual(self.params["message"], message)
