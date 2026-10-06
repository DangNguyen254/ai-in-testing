"""Tenants: a secondary tenant edits its own policy without touching the primary's."""

import pytest

from framework.base_test import BaseTest
from framework.decorators import browsers, cloud_only, data_driven, environments


@browsers("chrome", "firefox")
@environments("cloud", "on_prem")
@data_driven
@pytest.mark.project("example-project")
@pytest.mark.component("tenants")
class TestTenantsSecondary(BaseTest):
   def setup(self):
      self.base_setup()
      self.login_as(self.config.tenants[1], self.config.users[1])
      self.nav.rules.list.open()

   def teardown(self):
      self.logout()

   @pytest.mark.priority("p1")
   @pytest.mark.suite("regression")
   @cloud_only
   def test_tenants_secondary_rules_add(self):
      """
      1. As the secondary tenant, add a rule and publish.
      2. The secondary tenant's policy has the rule; the primary's is unchanged.
      """
      rules = self.nav.rules.list
      rules.add_rule()

      wizard = self.nav.rules.wizard
      wizard.name = self.unique_name(24)
      wizard.action = "deny"
      wizard.next()
      wizard.save()

      top_bar = self.nav.top_bar
      top_bar.save()
      top_bar.publish()
      self.verify_targets()

   @pytest.mark.priority("p2")
   @pytest.mark.suite("regression")
   @cloud_only
   def test_tenants_secondary_rules_list(self):
      rules = self.nav.rules.list

      self.check.assertEqual(self.params["expected_names"], rules.rule_names)
