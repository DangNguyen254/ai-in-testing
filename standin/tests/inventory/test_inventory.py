"""Inventory: creating, searching, editing, and deleting items."""

from __future__ import annotations

import pytest

from framework.base_test import BaseTest
from framework.decorators import retry


@pytest.mark.project("example-project")
@pytest.mark.component("inventory")
class TestInventory(BaseTest):
    @pytest.mark.priority("P1")
    @pytest.mark.suite("smoke")
    @pytest.mark.parametrize("quantity", [1, 50])
    def test_create_item(self, quantity: int) -> None:
        item = self.inputs
        editor = self.nav.inventory.item_editor.open()
        editor.fill(name=item["name"], quantity=str(quantity), category=item["category"])
        editor.save()

        assert self.nav.inventory.items.flash_message == "Item created"
        self.assert_backend(self.expected["backend"])

    @pytest.mark.priority("P2")
    @pytest.mark.suite("regression")
    @pytest.mark.parametrize("entry_mode", ["typed", "pasted"])
    @pytest.mark.parametrize("quantity", ["0", "-1"])
    def test_create_item_rejects_invalid_quantity(self, quantity: str, entry_mode: str) -> None:
        editor = self.nav.inventory.item_editor.open()
        editor.fill(name=self.inputs["name"], category=self.inputs["category"])
        if entry_mode == "pasted":
            editor.paste_quantity(quantity)
        else:
            editor.fill(quantity=quantity)
        editor.save()

        assert editor.error_message == self.expected["error"]
        self.assert_no_item(self.inputs["name"])

    @pytest.mark.priority("P2")
    @pytest.mark.suite("regression")
    def test_search_items_by_name(self) -> None:
        items = self.nav.inventory.items.open().search(self.inputs["query"])

        assert sorted(items.item_names()) == sorted(self.expected["visible_items"])

    @pytest.mark.priority("P2")
    @pytest.mark.suite("regression")
    @retry(times=2)
    def test_edit_item_category(self) -> None:
        editor = self.nav.inventory.item_editor.open_existing(self.inputs["name"])
        editor.fill(category=self.inputs["category"])
        editor.save()

        assert self.nav.inventory.items.flash_message == "Item saved"
        self.assert_backend(self.expected["backend"])

    @pytest.mark.priority("P1")
    @pytest.mark.suite("regression")
    def test_delete_item(self) -> None:
        self.nav.inventory.item_editor.open_existing(self.inputs["name"]).delete()

        assert self.nav.inventory.items.flash_message == "Item deleted"
        self.assert_no_item(self.inputs["name"])

    @pytest.mark.priority("P1")
    @pytest.mark.suite("smoke")
    def test_items_api_lists_seeded_items(self) -> None:
        names = sorted(item["name"] for item in self.api.items())

        assert names == sorted(self.expected["item_names"])
