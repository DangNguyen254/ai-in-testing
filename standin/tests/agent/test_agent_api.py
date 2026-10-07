"""Agent API: tasks through the API, and who may change the agent's settings."""

import pytest

from framework.base_test import BaseTest
from framework.decorators import data_driven, environments


@environments("cloud", "on_prem")
@data_driven
@pytest.mark.project("example-project")
@pytest.mark.component("agent")
class TestAgentApi(BaseTest):
   def setup_method(self, method):
      self.api_user = self.config.users[0]

   def teardown_method(self, method):
      self.api_user = None

   @pytest.mark.priority("p1")
   @pytest.mark.suite("regression")
   def test_agent_api_task_flags_injection(self):
      self.verify_interactions()

   @pytest.mark.priority("p2")
   @pytest.mark.suite("regression")
   def test_agent_api_unknown_page(self):
      self.verify_interactions()

   @pytest.mark.priority("p1")
   @pytest.mark.suite("regression")
   @pytest.mark.parametrize("role", ["viewer", "editor"])
   def test_agent_api_settings_forbidden(self, role):
      self.verify_targets()

      status, body = self.api.request("GET", f"settings/v1/settings/{self.primary_tenant}")
      self.check.assertEqual(status, 200, "settings must stay readable")
      self.check.assertTrue(body["agent"]["injection_guard"], f"a {role} must not turn it off")
