"""The shared top bar on every page: save, publish, reset."""

from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as ec

from framework.pages.base_page import BasePage

SETTINGS_SAVE = (By.ID, "settings-save")


class TopBar(BasePage):
   SAVE = (By.ID, "topbar-save")
   PUBLISH = (By.ID, "topbar-publish")
   RESET = (By.ID, "topbar-reset")
   STATUS = (By.ID, "topbar-status")

   @property
   def status(self):
      return self.text_of(self.STATUS)

   @property
   def save_enabled(self):
      return self.find(self.SAVE).is_enabled()

   def save(self, settings=False):
      """Save the policy draft. On settings pages, ``settings=True`` applies the settings
      form instead (settings take effect without a publish)."""
      self.click(SETTINGS_SAVE if settings else self.SAVE)

   def publish(self):
      """Publish the saved draft; waits for the success toast and the new revision status."""
      self.click(self.PUBLISH)
      self.wait().until(ec.text_to_be_present_in_element(self.STATUS, "Published revision"))
      self.wait().until(ec.text_to_be_present_in_element((By.ID, "toast"), "Published"))

   def reset(self):
      """Discard unsaved changes."""
      self.click(self.RESET)
