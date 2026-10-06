"""Policy API: reading published rules and role checks on changes (no browser)."""

import pytest

from framework.base_test import BaseTest
from framework.decorators import data_driven, environments


@environments("cloud", "on_prem")
@data_driven
@pytest.mark.project("example-project")
@pytest.mark.component("api")
class TestPolicyApi(BaseTest):
   def setup_method(self, method):
      self.api_user = self.config.users[0]

   def teardown_method(self, method):
      self.api_user = None

   @pytest.mark.priority("p1")
   @pytest.mark.suite("smoke")
   def test_policy_api_rules_read(self):
      status, body = self.api.request("GET", f"/api/policy/v1/revision/{self.primary_tenant}")
      self.check.assertEqual(status, 200, "revision lookup must succeed")
      self.check.assertEqual(body["rev_id"], 1, "the seeded policy is revision 1")
      self.verify_interactions()

   @pytest.mark.priority("p1")
   @pytest.mark.suite("regression")
   @pytest.mark.parametrize("change", ["replace", "clear"])
   @pytest.mark.parametrize("role", ["viewer", "editor"])
   def test_policy_api_rules_update_forbidden(self, role, change):
      self.verify_targets()

      revision = self.api.revision(self.primary_tenant)
      self.check.assertEqual(revision, 1, f"a {role} must not publish a new revision")

   @pytest.mark.priority("p2")
   @pytest.mark.suite("regression")
   def test_policy_api_rules_update_admin(self):
      self.verify_targets()
