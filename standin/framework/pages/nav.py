"""Root of the page-object hierarchy: ``nav.<area>.<page>``."""

from __future__ import annotations

from selenium.webdriver.remote.webdriver import WebDriver

from framework.pages.inventory import InventoryArea
from framework.pages.orders import OrdersArea
from framework.pages.settings import SettingsArea
from framework.pages.users import UsersArea


class Navigator:
    def __init__(self, driver: WebDriver, base_url: str, timeout: float = 10.0) -> None:
        self._args = (driver, base_url, timeout)

    @property
    def inventory(self) -> InventoryArea:
        return InventoryArea(*self._args)

    @property
    def users(self) -> UsersArea:
        return UsersArea(*self._args)

    @property
    def orders(self) -> OrdersArea:
        return OrdersArea(*self._args)

    @property
    def settings(self) -> SettingsArea:
        return SettingsArea(*self._args)
