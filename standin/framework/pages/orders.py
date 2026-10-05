"""Orders area: order list, checkout, and order detail."""

from __future__ import annotations

from selenium.webdriver.common.by import By
from selenium.webdriver.remote.webdriver import WebDriver

from framework.pages.base_page import BasePage, Locator


class OrderListPage(BasePage):
    path = "/orders"

    STATUS_FILTER: Locator = (By.ID, "status-filter")
    APPLY: Locator = (By.ID, "apply-filter")
    STATUSES: Locator = (By.CSS_SELECTOR, "#orders-table .order-status")
    IDS: Locator = (By.CSS_SELECTOR, "#orders-table .order-id")

    def filter_by(self, status: str) -> OrderListPage:
        self.select(self.STATUS_FILTER, status)
        self.click(self.APPLY)
        return self

    def statuses(self) -> list[str]:
        return [cell.text for cell in self.find_all(self.STATUSES)]

    def order_ids(self) -> list[int]:
        return [int(cell.text) for cell in self.find_all(self.IDS)]


class CheckoutPage(BasePage):
    path = "/orders/new"

    ITEM: Locator = (By.ID, "checkout-item")
    QUANTITY: Locator = (By.ID, "checkout-quantity")
    PLACE: Locator = (By.ID, "place-order")

    def place_order(self, item: str, quantity: int) -> None:
        self.select(self.ITEM, item)
        self.type(self.QUANTITY, str(quantity))
        self.click(self.PLACE)


class OrderDetailPage(BasePage):
    STATUS: Locator = (By.ID, "order-status")
    CANCEL: Locator = (By.ID, "cancel-order")
    NOTE_TEXT: Locator = (By.ID, "note-text")
    ADD_NOTE: Locator = (By.ID, "add-note")
    NOTES: Locator = (By.CSS_SELECTOR, "#notes .note")

    def open_for(self, order_id: int) -> OrderDetailPage:
        return self.open(f"/orders/{order_id}")

    @property
    def status(self) -> str:
        return self.text_of(self.STATUS)

    @property
    def order_id(self) -> int:
        return int(self.driver.current_url.rstrip("/").split("/")[-1].split("?")[0])

    def cancel(self) -> None:
        self.click(self.CANCEL)

    def add_note(self, text: str) -> None:
        self.type(self.NOTE_TEXT, text)
        self.click(self.ADD_NOTE)

    def notes(self) -> list[str]:
        return [li.text for li in self.find_all(self.NOTES)]


class OrdersArea:
    def __init__(self, driver: WebDriver, base_url: str, timeout: float) -> None:
        self._args = (driver, base_url, timeout)

    @property
    def order_list(self) -> OrderListPage:
        return OrderListPage(*self._args)

    @property
    def checkout(self) -> CheckoutPage:
        return CheckoutPage(*self._args)

    @property
    def order_detail(self) -> OrderDetailPage:
        return OrderDetailPage(*self._args)
