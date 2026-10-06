"""Inventory area: item list and item editor."""

from urllib.parse import quote

from selenium.webdriver.common.by import By

from framework.pages.base_page import BasePage


class ItemsPage(BasePage):
   path = "/inventory/items"

   SEARCH_BOX = (By.ID, "search-box")
   SEARCH_BUTTON = (By.ID, "search-button")
   NEW_ITEM = (By.ID, "new-item")
   ITEM_NAMES = (By.CSS_SELECTOR, "#items-table .item-name")

   @property
   def search_text(self):
      return self.value_of(self.SEARCH_BOX)

   @search_text.setter
   def search_text(self, text):
      self.type(self.SEARCH_BOX, text)

   @property
   def item_names(self):
      return self.texts_of(self.ITEM_NAMES)

   def search(self):
      self.click(self.SEARCH_BUTTON)

   def new_item(self):
      self.click(self.NEW_ITEM)


class ItemEditorPage(BasePage):
   path = "/inventory/items/new"

   NAME = (By.ID, "item-name")
   QUANTITY = (By.ID, "item-quantity")
   CATEGORY = (By.ID, "item-category")
   SAVE = (By.ID, "save-item")
   DELETE = (By.ID, "delete-item")

   def open_existing(self, name):
      self.open(f"/inventory/items/{quote(name)}/edit")

   @property
   def name(self):
      return self.value_of(self.NAME)

   @name.setter
   def name(self, value):
      self.type(self.NAME, value)

   @property
   def quantity(self):
      return self.value_of(self.QUANTITY)

   @quantity.setter
   def quantity(self, value):
      self.type(self.QUANTITY, value)

   @property
   def category(self):
      return self.value_of(self.CATEGORY)

   @category.setter
   def category(self, value):
      self.select(self.CATEGORY, value)

   def paste_quantity(self, value):
      """Set the field through JavaScript, the way a paste bypasses key events."""
      element = self.find(self.QUANTITY)
      self.driver.execute_script("arguments[0].value = arguments[1];", element, value)

   def save(self):
      self.click(self.SAVE)

   def delete(self):
      self.click(self.DELETE)


class InventoryArea:
   def __init__(self, driver, base_url, timeout):
      self._args = (driver, base_url, timeout)

   @property
   def items(self):
      return ItemsPage(*self._args)

   @property
   def item_editor(self):
      return ItemEditorPage(*self._args)
