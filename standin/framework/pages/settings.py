"""Settings area: general settings and notification settings."""

from selenium.webdriver.common.by import By

from framework.pages.base_page import BasePage


class GeneralSettingsPage(BasePage):
   path = "/settings/general"

   TIMEZONE = (By.ID, "timezone")
   LANGUAGE = (By.ID, "language")
   SAVE = (By.ID, "save-general")

   @property
   def timezone(self):
      return self.value_of(self.TIMEZONE)

   @timezone.setter
   def timezone(self, value):
      self.select(self.TIMEZONE, value)

   @property
   def language(self):
      return self.value_of(self.LANGUAGE)

   @language.setter
   def language(self, value):
      self.select(self.LANGUAGE, value)

   def save(self):
      self.click(self.SAVE)


class NotificationSettingsPage(BasePage):
   path = "/settings/notifications"

   EMAIL = (By.ID, "email-toggle")
   DIGEST = (By.ID, "digest-toggle")
   SAVE = (By.ID, "save-notifications")

   @property
   def email_enabled(self):
      return self.find(self.EMAIL).is_selected()

   @email_enabled.setter
   def email_enabled(self, enabled):
      self.set_checkbox(self.EMAIL, enabled)

   @property
   def weekly_digest(self):
      return self.find(self.DIGEST).is_selected()

   @weekly_digest.setter
   def weekly_digest(self, enabled):
      self.set_checkbox(self.DIGEST, enabled)

   def save(self):
      self.click(self.SAVE)


class SettingsArea:
   def __init__(self, driver, base_url, timeout):
      self._args = (driver, base_url, timeout)

   @property
   def general(self):
      return GeneralSettingsPage(*self._args)

   @property
   def notifications(self):
      return NotificationSettingsPage(*self._args)
