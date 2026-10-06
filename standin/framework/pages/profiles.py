"""Profiles area: profile list (search, delete) and a single-page editor."""

from urllib.parse import quote

from selenium.webdriver.common.by import By

from framework.pages.base_page import BasePage


class ProfileListPage(BasePage):
   path = "/profiles"

   SEARCH_BOX = (By.ID, "profile-search")
   SEARCH_BUTTON = (By.ID, "profile-search-button")
   ADD = (By.ID, "add-profile")
   NAMES = (By.CSS_SELECTOR, "#profiles-table .profile-name")
   ROWS = (By.CSS_SELECTOR, "#profiles-table .profile-row")

   @property
   def search_text(self):
      return self.value_of(self.SEARCH_BOX)

   @search_text.setter
   def search_text(self, text):
      self.type(self.SEARCH_BOX, text)

   @property
   def profile_names(self):
      return self.texts_of(self.NAMES)

   def level_of(self, name):
      for row in self.find_all(self.ROWS):
         if row.find_element(By.CLASS_NAME, "profile-name").text == name:
            return row.find_element(By.CLASS_NAME, "profile-level").text
      raise AssertionError(f"{name} is not in the profile list")

   def search(self):
      self.click(self.SEARCH_BUTTON)

   def add_profile(self):
      self.click(self.ADD)

   def open_profile(self, name):
      self.open(f"/profiles/{quote(name)}/edit")

   def delete_profile(self, name):
      self.click((By.CSS_SELECTOR, f'.profile-delete[value="{name}"]'))


class ProfileEditorPage(BasePage):
   path = "/profiles/new"

   NAME = (By.ID, "profile-name")
   LEVEL = (By.ID, "profile-level")
   DESCRIPTION = (By.ID, "profile-description")
   SAVE = (By.ID, "profile-save")

   @property
   def name(self):
      return self.value_of(self.NAME)

   @name.setter
   def name(self, value):
      self.type(self.NAME, value)

   @property
   def level(self):
      return self.value_of(self.LEVEL)

   @level.setter
   def level(self, value):
      self.select(self.LEVEL, value)

   @property
   def description(self):
      return self.value_of(self.DESCRIPTION)

   @description.setter
   def description(self, value):
      self.type(self.DESCRIPTION, value)

   def save(self):
      self.click(self.SAVE)


class ProfilesArea:
   def __init__(self, driver, base_url, timeout):
      self._args = (driver, base_url, timeout)

   @property
   def list(self):
      return ProfileListPage(*self._args)

   @property
   def editor(self):
      return ProfileEditorPage(*self._args)
