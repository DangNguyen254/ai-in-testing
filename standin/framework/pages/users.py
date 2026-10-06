"""Users area: user list, invite form, and user profile."""

from urllib.parse import quote

from selenium.webdriver.common.by import By

from framework.pages.base_page import BasePage


class UserListPage(BasePage):
   path = "/users"

   INVITE = (By.ID, "invite-user")
   ROWS = (By.CSS_SELECTOR, "#users-table .user-row")
   EMAILS = (By.CSS_SELECTOR, "#users-table .user-email")
   BANNER = (By.ID, "sso-banner")

   @property
   def emails(self):
      return self.texts_of(self.EMAILS)

   @property
   def sso_banner(self):
      return self.text_of(self.BANNER)

   def role_of(self, email):
      for row in self.find_all(self.ROWS):
         if row.find_element(By.CLASS_NAME, "user-email").text == email:
            return row.find_element(By.CLASS_NAME, "user-role").text
      raise AssertionError(f"{email} is not in the user list")

   def invite_user(self):
      self.click(self.INVITE)


class InviteUserPage(BasePage):
   path = "/users/invite"

   EMAIL = (By.ID, "invite-email")
   ROLE = (By.ID, "invite-role")
   SEND = (By.ID, "send-invite")

   @property
   def email(self):
      return self.value_of(self.EMAIL)

   @email.setter
   def email(self, value):
      self.type(self.EMAIL, value)

   @property
   def role(self):
      return self.value_of(self.ROLE)

   @role.setter
   def role(self, value):
      self.select(self.ROLE, value)

   def send(self):
      self.click(self.SEND)


class UserProfilePage(BasePage):
   ROLE = (By.ID, "role-select")
   SAVE_ROLE = (By.ID, "save-role")
   DEACTIVATE = (By.ID, "deactivate-user")
   STATUS = (By.ID, "user-status")

   def open_for(self, email):
      self.open(f"/users/{quote(email)}")

   @property
   def role(self):
      return self.value_of(self.ROLE)

   @role.setter
   def role(self, value):
      self.select(self.ROLE, value)

   @property
   def status(self):
      return self.text_of(self.STATUS)

   def save_role(self):
      self.click(self.SAVE_ROLE)

   def deactivate(self):
      self.click(self.DEACTIVATE)


class UsersArea:
   def __init__(self, driver, base_url, timeout):
      self._args = (driver, base_url, timeout)

   @property
   def user_list(self):
      return UserListPage(*self._args)

   @property
   def invite(self):
      return InviteUserPage(*self._args)

   @property
   def profile(self):
      return UserProfilePage(*self._args)
