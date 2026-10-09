"""Agent console: opening agent browser sessions from the UI, within the tenant's limit."""

import pytest

from framework.base_test import BaseTest
from framework.decorators import browsers, data_driven, environments


@browsers("chrome", "firefox")
@environments("cloud", "on_prem")
@data_driven
@pytest.mark.project("example-project")
@pytest.mark.component("agent")
class TestAgentBrowserConsole(BaseTest):
   def setup(self):
      self.base_setup(fresh_driver=False)

   @pytest.mark.priority("p1")
   @pytest.mark.suite("regression")
   def test_agent_console_browser_limit_message(self):
      """
      1. Open browsers from the console until the tenant's limit is reached.
      2. One more shows the limit message, and no extra browser is listed.
      """
      console = self.nav.agent.console
      console.open()
      for _ in range(self.params["limit"]):
         console.open_browser()
      console.open_browser()

      self.check.assertEqual(self.params["refusal"], console.browser_message)
      self.check.assertEqual(self.params["limit"], console.open_browsers)
      self.verify_targets()

   @pytest.mark.priority("p2")
   @pytest.mark.suite("regression")
   def test_agent_console_browser_close_frees_slot(self):
      """
      1. Open a browser at a limit of one, then close it from the console.
      2. A new browser opens.
      """
      console = self.nav.agent.console
      console.open()
      console.open_browser()
      console.close_browser(1)
      console.open_browser()

      self.check.assertEqual("Browser opened", console.toast)
      self.check.assertEqual(1, console.open_browsers)
      self.verify_targets()
