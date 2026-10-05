"""Shared page-object behavior: navigation and explicit waits (no implicit waits, no sleeps)."""

from __future__ import annotations

from typing import TypeVar

from selenium.webdriver.common.by import By
from selenium.webdriver.remote.webdriver import WebDriver
from selenium.webdriver.remote.webelement import WebElement
from selenium.webdriver.support import expected_conditions as ec
from selenium.webdriver.support.ui import Select, WebDriverWait

Locator = tuple[str, str]
P = TypeVar("P", bound="BasePage")

FLASH: Locator = (By.ID, "flash")
FORM_ERROR: Locator = (By.ID, "form-error")


class BasePage:
    path = "/"

    def __init__(self, driver: WebDriver, base_url: str, timeout: float = 10.0) -> None:
        self.driver = driver
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def open(self: P, path: str | None = None) -> P:
        self.driver.get(self.base_url + (path or self.path))
        return self

    def wait(self) -> WebDriverWait[WebDriver]:
        return WebDriverWait(self.driver, self.timeout)

    def find(self, locator: Locator) -> WebElement:
        return self.wait().until(ec.visibility_of_element_located(locator))

    def find_all(self, locator: Locator) -> list[WebElement]:
        return self.driver.find_elements(*locator)

    def click(self, locator: Locator) -> None:
        self.wait().until(ec.element_to_be_clickable(locator)).click()

    def type(self, locator: Locator, text: str) -> None:
        element = self.find(locator)
        element.clear()
        element.send_keys(text)

    def select(self, locator: Locator, value: str) -> None:
        Select(self.find(locator)).select_by_value(value)

    def text_of(self, locator: Locator) -> str:
        return self.find(locator).text

    @property
    def flash_message(self) -> str:
        return self.text_of(FLASH)

    @property
    def error_message(self) -> str:
        return self.text_of(FORM_ERROR)
