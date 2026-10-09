"""Settings area: capability gates (applied with the top bar's settings save option)."""

from selenium.webdriver.common.by import By

from framework.pages.base_page import BasePage


class CapabilitiesPage(BasePage):
   path = "/settings/capabilities"

   RULES = (By.ID, "cap-rules")
   PROFILES = (By.ID, "cap-profiles")
   BULK_DELETE = (By.ID, "cap-bulk_delete")
   IMPORT = (By.ID, "cap-import")
   BROWSER_LIMIT = (By.ID, "cap-browser_limit")

   @property
   def rules_enabled(self):
      return self.checked(self.RULES)

   @rules_enabled.setter
   def rules_enabled(self, value):
      self.set_checkbox(self.RULES, value)

   @property
   def profiles_enabled(self):
      return self.checked(self.PROFILES)

   @profiles_enabled.setter
   def profiles_enabled(self, value):
      self.set_checkbox(self.PROFILES, value)

   @property
   def bulk_delete_enabled(self):
      return self.checked(self.BULK_DELETE)

   @bulk_delete_enabled.setter
   def bulk_delete_enabled(self, value):
      self.set_checkbox(self.BULK_DELETE, value)

   @property
   def import_enabled(self):
      return self.checked(self.IMPORT)

   @import_enabled.setter
   def import_enabled(self, value):
      self.set_checkbox(self.IMPORT, value)

   @property
   def browser_limit(self):
      """Agent browser sessions the tenant may have open at once."""
      return int(self.value_of(self.BROWSER_LIMIT))

   @browser_limit.setter
   def browser_limit(self, value):
      self.type(self.BROWSER_LIMIT, str(value))


class SettingsArea:
   def __init__(self, driver, base_url, timeout):
      self._args = (driver, base_url, timeout)

   @property
   def capabilities(self):
      return CapabilitiesPage(*self._args)
