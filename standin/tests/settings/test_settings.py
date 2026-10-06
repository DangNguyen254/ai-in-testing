"""Settings: capability gates, applied with the top bar's settings save option."""

import pytest

from framework.base_test import BaseTest
from framework.decorators import browsers, data_driven, environments, on_prem_only


@browsers("chrome", "firefox")
@environments("cloud", "on_prem")
@data_driven
@pytest.mark.project("example-project")
@pytest.mark.component("settings")
class TestSettingsCapabilities(BaseTest):
   def setup(self):
      self.base_setup(fresh_driver=False, policy_wait=False)

   @pytest.mark.priority("p2")
   @pytest.mark.suite("regression")
   def test_settings_capabilities_enable_bulk(self):
      capabilities = self.nav.settings.capabilities
      capabilities.open()
      capabilities.bulk_delete_enabled = True
      self.nav.top_bar.save(settings=True)

      self.check.assertEqual("Settings applied", capabilities.toast)
      self.verify_targets()

   @pytest.mark.priority("p2")
   @pytest.mark.suite("regression")
   @on_prem_only
   def test_settings_capabilities_disable_profiles(self):
      """
      1. Turn off the profiles capability and apply the settings.
      2. The Profiles link is gone from the navigation.
      """
      capabilities = self.nav.settings.capabilities
      capabilities.open()
      capabilities.profiles_enabled = False
      self.nav.top_bar.save(settings=True)

      self.check.assertNotIn("Profiles", capabilities.nav_links)
      self.verify_targets()
