"""Settings: timezone, language, and notification preferences."""

import pytest

from framework.base_test import BaseTest
from framework.decorators import browsers, data_driven, environments


@browsers("chrome", "firefox")
@environments("cloud", "on_prem")
@data_driven
@pytest.mark.project("example-project")
@pytest.mark.component("settings")
class TestSettings(BaseTest):
   @pytest.mark.priority("p2")
   @pytest.mark.suite("regression")
   @pytest.mark.parametrize("timezone", ["UTC", "Europe/Berlin"])
   def test_settings_general_timezone_change(self, timezone):
      general = self.nav.settings.general
      general.open()
      general.timezone = timezone
      general.save()

      self.check.equal(general.flash_message, "Settings saved", "flash message")
      self.validate_backend()

   @pytest.mark.priority("p3")
   @pytest.mark.suite("regression")
   def test_settings_general_language_change(self):
      general = self.nav.settings.general
      general.open()
      general.language = "de"
      general.save()

      self.validate_backend()

   @pytest.mark.priority("p1")
   @pytest.mark.suite("smoke")
   def test_settings_general_timezone_reload(self):
      """1. Save a timezone. 2. Reload the page. 3. The saved timezone is still selected."""
      general = self.nav.settings.general
      general.open()
      general.timezone = "America/New_York"
      general.save()
      general.refresh()

      self.check.equal(general.timezone, "America/New_York", "selected timezone")
      self.validate_backend()

   @pytest.mark.priority("p2")
   @pytest.mark.suite("regression")
   def test_settings_notifications_email_disable(self):
      notifications = self.nav.settings.notifications
      notifications.open()
      notifications.email_enabled = False
      notifications.save()

      self.check.equal(notifications.flash_message, "Settings saved", "flash message")
      self.validate_backend()

   @pytest.mark.priority("p3")
   @pytest.mark.suite("regression")
   def test_settings_notifications_digest_enable(self):
      notifications = self.nav.settings.notifications
      notifications.open()
      notifications.weekly_digest = True
      notifications.save()

      self.validate_backend()
