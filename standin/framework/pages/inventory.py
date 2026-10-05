"""Inventory area: item list and item editor."""

from __future__ import annotations

from urllib.parse import quote

from selenium.webdriver.common.by import By
from selenium.webdriver.remote.webdriver import WebDriver

from framework.pages.base_page import BasePage, Locator


class ItemsPage(BasePage):
    path = "/inventory/items"

    SEARCH_BOX: Locator = (By.ID, "search-box")
    SEARCH_BUTTON: Locator = (By.ID, "search-button")
    NEW_ITEM: Locator = (By.ID, "new-item")
    ITEM_NAMES: Locator = (By.CSS_SELECTOR, "#items-table .item-name")

    def search(self, text: str) -> ItemsPage:
        self.type(self.SEARCH_BOX, text)
        self.click(self.SEARCH_BUTTON)
        return self

    def item_names(self) -> list[str]:
        return [cell.text for cell in self.find_all(self.ITEM_NAMES)]

    def start_new_item(self) -> None:
        self.click(self.NEW_ITEM)


class ItemEditorPage(BasePage):
    path = "/inventory/items/new"

    NAME: Locator = (By.ID, "item-name")
    QUANTITY: Locator = (By.ID, "item-quantity")
    CATEGORY: Locator = (By.ID, "item-category")
    SAVE: Locator = (By.ID, "save-item")
    DELETE: Locator = (By.ID, "delete-item")

    def open_existing(self, name: str) -> ItemEditorPage:
        return self.open(f"/inventory/items/{quote(name)}/edit")

    def fill(
        self, name: str | None = None, quantity: str | None = None, category: str | None = None
    ) -> ItemEditorPage:
        if name is not None:
            self.type(self.NAME, name)
        if quantity is not None:
            self.type(self.QUANTITY, quantity)
        if category is not None:
            self.select(self.CATEGORY, category)
        return self

    def paste_quantity(self, quantity: str) -> ItemEditorPage:
        """Set the field through JavaScript, the way a paste bypasses key events."""
        element = self.find(self.QUANTITY)
        self.driver.execute_script("arguments[0].value = arguments[1];", element, quantity)
        return self

    def save(self) -> None:
        self.click(self.SAVE)

    def delete(self) -> None:
        self.click(self.DELETE)


class InventoryArea:
    def __init__(self, driver: WebDriver, base_url: str, timeout: float) -> None:
        self._args = (driver, base_url, timeout)

    @property
    def items(self) -> ItemsPage:
        return ItemsPage(*self._args)

    @property
    def item_editor(self) -> ItemEditorPage:
        return ItemEditorPage(*self._args)
