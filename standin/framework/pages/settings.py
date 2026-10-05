"""Settings area: general settings and notification settings."""

from __future__ import annotations

from selenium.webdriver.common.by import By
from selenium.webdriver.remote.webdriver import WebDriver

from framework.pages.base_page import BasePage, Locator


class GeneralSettingsPage(BasePage):
    path = "/settings/general"

    TIMEZONE: Locator = (By.ID, "timezone")
    LANGUAGE: Locator = (By.ID, "language")
    SAVE: Locator = (By.ID, "save-general")

    def set_timezone(self, timezone: str) -> GeneralSettingsPage:
        self.select(self.TIMEZONE, timezone)
        return self

    def set_language(self, language: str) -> GeneralSettingsPage:
        self.select(self.LANGUAGE, language)
        return self

    def save(self) -> None:
        self.click(self.SAVE)

    def selected_timezone(self) -> str:
        return str(self.find(self.TIMEZONE).get_attribute("value"))


class NotificationSettingsPage(BasePage):
    path = "/settings/notifications"

    EMAIL: Locator = (By.ID, "email-toggle")
    DIGEST: Locator = (By.ID, "digest-toggle")
    SAVE: Locator = (By.ID, "save-notifications")

    def set_email(self, enabled: bool) -> NotificationSettingsPage:
        self._set_checkbox(self.EMAIL, enabled)
        return self

    def set_weekly_digest(self, enabled: bool) -> NotificationSettingsPage:
        self._set_checkbox(self.DIGEST, enabled)
        return self

    def save(self) -> None:
        self.click(self.SAVE)

    def _set_checkbox(self, locator: tuple[str, str], enabled: bool) -> None:
        box = self.find(locator)
        if box.is_selected() != enabled:
            box.click()


class SettingsArea:
    def __init__(self, driver: WebDriver, base_url: str, timeout: float) -> None:
        self._args = (driver, base_url, timeout)

    @property
    def general(self) -> GeneralSettingsPage:
        return GeneralSettingsPage(*self._args)

    @property
    def notifications(self) -> NotificationSettingsPage:
        return NotificationSettingsPage(*self._args)
