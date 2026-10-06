"""Inventory: creating, searching, editing, and deleting items."""

import pytest

from framework.base_test import BaseTest
from framework.decorators import browsers, data_driven, environments, retry


@browsers("chrome", "firefox")
@environments("cloud", "on_prem")
@data_driven
@pytest.mark.project("example-project")
@pytest.mark.component("inventory")
class TestInventoryItems(BaseTest):
   @pytest.mark.priority("p1")
   @pytest.mark.suite("smoke")
   @pytest.mark.parametrize("quantity", [1, 50])
   def test_inventory_item_create(self, quantity):
      editor = self.nav.inventory.item_editor
      editor.open()
      editor.name = self.params["item_name"]
      editor.quantity = str(quantity)
      editor.category = "hardware"
      editor.save()

      self.check.equal(self.nav.inventory.items.flash_message, "Item created", "flash message")
      self.validate_backend()

   @pytest.mark.priority("p2")
   @pytest.mark.suite("regression")
   @pytest.mark.parametrize("entry_mode", ["typed", "pasted"])
   @pytest.mark.parametrize("quantity", ["0", "-1"])
   def test_inventory_item_create_invalid_quantity(self, quantity, entry_mode):
      """1. Open the item editor. 2. Enter a quantity below 1. 3. Save and expect an error."""
      editor = self.nav.inventory.item_editor
      editor.open()
      editor.name = self.params["item_name"]
      if entry_mode == "pasted":
         editor.paste_quantity(quantity)
      else:
         editor.quantity = quantity
      editor.save()

      self.check.equal(editor.error_message, "Quantity must be at least 1", "form error")
      self.validate_backend()

   @pytest.mark.priority("p2")
   @pytest.mark.suite("regression")
   @pytest.mark.parametrize("category", ["software", "office"])
   def test_inventory_item_create_category_not_allowed(self, category):
      editor = self.nav.inventory.item_editor
      editor.open()
      editor.name = self.params["item_name"]
      editor.category = category
      editor.save()

      self.check.equal(
         editor.error_message, f"Category '{category}' is not allowed by policy", "form error"
      )
      self.validate_backend()

   @pytest.mark.priority("p2")
   @pytest.mark.suite("regression")
   def test_inventory_items_search_by_name(self):
      items = self.nav.inventory.items
      items.open()
      items.search_text = "desk"
      items.search()

      self.check.same_items(items.item_names, self.params["expected_items"], "search results")

   @pytest.mark.priority("p2")
   @pytest.mark.suite("regression")
   @retry(times=2)
   def test_inventory_item_edit_category(self):
      editor = self.nav.inventory.item_editor
      editor.open_existing(self.params["item_name"])
      editor.category = "office"
      editor.save()

      self.check.equal(self.nav.inventory.items.flash_message, "Item saved", "flash message")
      self.validate_backend()

   @pytest.mark.priority("p1")
   @pytest.mark.suite("regression")
   def test_inventory_item_delete(self):
      editor = self.nav.inventory.item_editor
      editor.open_existing(self.params["item_name"])
      editor.delete()

      self.check.equal(self.nav.inventory.items.flash_message, "Item deleted", "flash message")
      self.validate_backend()

   @pytest.mark.priority("p3")
   @pytest.mark.suite("regression")
   def test_inventory_items_list_empty(self):
      items = self.nav.inventory.items
      items.open()

      self.check.equal(items.item_names, [], "item list")

   @pytest.mark.priority("p1")
   @pytest.mark.suite("smoke")
   def test_inventory_items_api_list(self):
      self.validate_backend()
