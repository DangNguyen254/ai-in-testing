"""Users: inviting users, changing roles, deactivating, and the sign-on banner."""

from __future__ import annotations

import pytest

from framework.base_test import BaseTest
from framework.decorators import cloud_only, on_prem_only


@pytest.mark.project("example-project")
@pytest.mark.component("users")
class TestUsers(BaseTest):
    @pytest.mark.priority("p0")
    @pytest.mark.suite("smoke")
    @pytest.mark.parametrize("role", ["viewer", "editor", "admin"])
    def test_invite_user(self, role: str) -> None:
        self.nav.users.invite.open().invite(self.inputs["email"], role)

        user_list = self.nav.users.user_list
        assert user_list.flash_message == "Invitation sent"
        assert user_list.role_of(self.inputs["email"]) == role
        self.assert_backend(self.expected["backend"])

    @pytest.mark.priority("p1")
    @pytest.mark.suite("regression")
    def test_invite_user_rejects_duplicate_email(self) -> None:
        invite = self.nav.users.invite.open()
        invite.invite(self.inputs["email"], self.inputs["role"])

        assert invite.error_message == self.expected["error"]
        assert len(self.api.users()) == self.expected["user_count"]

    @pytest.mark.priority("p2")
    @pytest.mark.suite("regression")
    def test_change_user_role(self) -> None:
        profile = self.nav.users.profile.open_for(self.inputs["email"])
        profile.change_role(self.inputs["new_role"])

        assert profile.flash_message == "Role updated"
        self.assert_backend(self.expected["backend"])

    @pytest.mark.priority("p1")
    @pytest.mark.suite("regression")
    @on_prem_only
    def test_deactivate_user(self) -> None:
        profile = self.nav.users.profile.open_for(self.inputs["email"])
        profile.deactivate()

        assert profile.status == "inactive"
        self.assert_backend(self.expected["backend"])

    @pytest.mark.priority("p3")
    @pytest.mark.suite("regression")
    @cloud_only
    def test_sso_banner_on_user_list(self) -> None:
        banner = self.nav.users.user_list.open().sso_banner_text()

        assert banner == self.expected["banner"]
