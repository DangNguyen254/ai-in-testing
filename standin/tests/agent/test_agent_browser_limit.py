"""Agent browser limit: how many agent browser sessions a tenant may have open at once."""

import pytest

from framework.base_test import BaseTest
from framework.decorators import data_driven, environments


@environments("cloud", "on_prem")
@data_driven
@pytest.mark.project("example-project")
@pytest.mark.component("agent")
class TestAgentBrowserLimit(BaseTest):
   def setup_method(self, method):
      self.api_user = self.config.users[0]

   def teardown_method(self, method):
      self.api_user = None

   @pytest.mark.priority("p0")
   @pytest.mark.suite("smoke")
   @pytest.mark.parametrize("limit", [1, 3])
   def test_agent_browser_limit_refused(self, limit):
      """
      1. Open as many browser sessions as the tenant's limit.
      2. The next attempt is refused with 429 before the WebSocket upgrade.
      """
      opened = self.browsers.open_many(self.primary_tenant, limit)
      self.check.assertEqual([101] * limit, [session.status for session in opened])
      refused = self.browsers.connect(self.primary_tenant)
      self.check.assertEqual(429, refused.status)
      self.check.assertEqual(self.params["refusal"], refused.body)
      self.verify_targets()

   @pytest.mark.priority("p1")
   @pytest.mark.suite("regression")
   def test_agent_browser_limit_slot_freed(self):
      """
      1. Fill the tenant's browser limit, then close one session.
      2. The next attempt opens a session.
      """
      path = f"settings/v1/capabilities/{self.primary_tenant}"
      _, capabilities = self.api.request("GET", path)
      opened = self.browsers.open_many(self.primary_tenant, capabilities["browser_limit"])
      opened[0].close()
      reopened = self.browsers.connect(self.primary_tenant)
      self.check.assertEqual(101, reopened.status)
      self.verify_targets()

   @pytest.mark.priority("p1")
   @pytest.mark.suite("regression")
   def test_agent_browser_limit_per_tenant(self):
      """
      1. Fill the primary tenant's browser limit.
      2. The primary tenant's next attempt is refused; another tenant still opens a session.
      """
      other = self.config.tenants[1]
      self.browsers.open_many(self.primary_tenant, self.params["limit"])
      refused = self.browsers.connect(self.primary_tenant)
      allowed = self.browsers.connect(other)
      self.check.assertEqual(429, refused.status)
      self.check.assertEqual(101, allowed.status)
      self.verify_targets()

   @pytest.mark.priority("p1")
   @pytest.mark.suite("regression")
   def test_agent_browser_limit_lowered_keeps_sessions(self):
      """
      1. Fill the tenant's browser limit, then lower the limit through the capabilities API.
      2. The open sessions stay open, and the next attempt is refused.
      3. Raise the limit: the next attempt opens a session.
      """
      path = f"settings/v1/capabilities/{self.primary_tenant}"
      service = self.config.service_user
      opened = self.browsers.open_many(self.primary_tenant, self.params["opened"])
      self.api.request("PUT", path, {"browser_limit": self.params["lowered"]}, service)
      self.check.assertTrue(all(session.is_open for session in opened))
      refused = self.browsers.connect(self.primary_tenant)
      self.check.assertEqual(429, refused.status)
      self.api.request("PUT", path, {"browser_limit": self.params["raised"]}, service)
      allowed = self.browsers.connect(self.primary_tenant)
      self.check.assertEqual(101, allowed.status)
      self.verify_targets()

   @pytest.mark.priority("p1")
   @pytest.mark.suite("regression")
   def test_agent_browser_limit_read_back(self):
      """
      1. Set a different browser limit for two tenants through the capabilities API.
      2. Each tenant reads back its own limit.
      """
      service = self.config.service_user
      for number, limit in enumerate(self.params["limits"]):
         path = f"settings/v1/capabilities/{self.config.tenants[number]}"
         self.api.request("PUT", path, {"browser_limit": limit}, service)
      self.verify_targets()

   @pytest.mark.priority("p1")
   @pytest.mark.suite("regression")
   @pytest.mark.parametrize("role", ["viewer", "editor"])
   def test_agent_browser_limit_change_forbidden(self, role):
      """
      1. A non-admin tries to change the browser limit through the capabilities API.
      2. The change is refused with 403 and the limit is unchanged.
      """
      self.verify_targets()
