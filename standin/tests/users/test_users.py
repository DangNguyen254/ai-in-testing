"""Users: inviting users, changing roles, deactivating, and the sign-on banner."""

import pytest

from framework.base_test import BaseTest
from framework.decorators import browsers, cloud_only, data_driven, environments, on_prem_only


@browsers("chrome", "firefox")
@environments("cloud", "on_prem")
@data_driven
@pytest.mark.project("example-project")
@pytest.mark.component("users")
class TestUsers(BaseTest):
   @pytest.mark.priority("p0")
   @pytest.mark.suite("smoke")
   @pytest.mark.parametrize("role", ["viewer", "editor", "admin"])
   def test_users_invite_role(self, role):
      invite = self.nav.users.invite
      invite.open()
      invite.email = self.params["email"]
      invite.role = role
      invite.send()

      user_list = self.nav.users.user_list
      self.check.equal(user_list.flash_message, "Invitation sent", "flash message")
      self.check.equal(user_list.role_of(self.params["email"]), role, "listed role")
      self.validate_backend()

   @pytest.mark.priority("p1")
   @pytest.mark.suite("regression")
   def test_users_invite_duplicate_email(self):
      invite = self.nav.users.invite
      invite.open()
      invite.email = self.params["email"]
      invite.role = "editor"
      invite.send()

      self.check.equal(
         invite.error_message, f"{self.params['email']} has already been invited", "form error"
      )
      self.validate_backend()

   @pytest.mark.priority("p2")
   @pytest.mark.suite("regression")
   def test_users_profile_role_change(self):
      profile = self.nav.users.profile
      profile.open_for(self.params["email"])
      profile.role = "admin"
      profile.save_role()

      self.check.equal(profile.flash_message, "Role updated", "flash message")
      self.validate_backend()

   @pytest.mark.priority("p1")
   @pytest.mark.suite("regression")
   @on_prem_only
   def test_users_profile_deactivate(self):
      profile = self.nav.users.profile
      profile.open_for(self.params["email"])
      profile.deactivate()

      self.check.equal(profile.status, "inactive", "user status")
      self.validate_backend()

   @pytest.mark.priority("p3")
   @pytest.mark.suite("regression")
   @cloud_only
   def test_users_list_sso_banner(self):
      user_list = self.nav.users.user_list
      user_list.open()

      self.check.equal(
         user_list.sso_banner, "Single sign-on is managed by your identity provider", "banner"
      )
