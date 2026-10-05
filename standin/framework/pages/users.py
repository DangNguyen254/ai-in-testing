"""Users area: user list, invite form, and user profile."""

from __future__ import annotations

from urllib.parse import quote

from selenium.webdriver.common.by import By
from selenium.webdriver.remote.webdriver import WebDriver

from framework.pages.base_page import BasePage, Locator


class UserListPage(BasePage):
    path = "/users"

    INVITE: Locator = (By.ID, "invite-user")
    ROWS: Locator = (By.CSS_SELECTOR, "#users-table .user-row")
    BANNER: Locator = (By.ID, "sso-banner")

    def emails(self) -> list[str]:
        return [
            row.find_element(By.CLASS_NAME, "user-email").text for row in self.find_all(self.ROWS)
        ]

    def role_of(self, email: str) -> str:
        for row in self.find_all(self.ROWS):
            if row.find_element(By.CLASS_NAME, "user-email").text == email:
                return row.find_element(By.CLASS_NAME, "user-role").text
        raise AssertionError(f"{email} is not in the user list")

    def sso_banner_text(self) -> str:
        return self.text_of(self.BANNER)


class InviteUserPage(BasePage):
    path = "/users/invite"

    EMAIL: Locator = (By.ID, "invite-email")
    ROLE: Locator = (By.ID, "invite-role")
    SEND: Locator = (By.ID, "send-invite")

    def invite(self, email: str, role: str) -> None:
        self.type(self.EMAIL, email)
        self.select(self.ROLE, role)
        self.click(self.SEND)


class UserProfilePage(BasePage):
    ROLE: Locator = (By.ID, "role-select")
    SAVE_ROLE: Locator = (By.ID, "save-role")
    DEACTIVATE: Locator = (By.ID, "deactivate-user")
    STATUS: Locator = (By.ID, "user-status")

    def open_for(self, email: str) -> UserProfilePage:
        return self.open(f"/users/{quote(email)}")

    def change_role(self, role: str) -> None:
        self.select(self.ROLE, role)
        self.click(self.SAVE_ROLE)

    def deactivate(self) -> None:
        self.click(self.DEACTIVATE)

    @property
    def status(self) -> str:
        return self.text_of(self.STATUS)


class UsersArea:
    def __init__(self, driver: WebDriver, base_url: str, timeout: float) -> None:
        self._args = (driver, base_url, timeout)

    @property
    def user_list(self) -> UserListPage:
        return UserListPage(*self._args)

    @property
    def invite(self) -> InviteUserPage:
        return InviteUserPage(*self._args)

    @property
    def profile(self) -> UserProfilePage:
        return UserProfilePage(*self._args)
