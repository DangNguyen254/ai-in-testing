"""Files area: the download center, the verdict page, safe viewing, and the download policy.

Multi-step helpers (``download_file``, ``view_file``, ``set_type_action``) are what tests
reuse; the single steps stay available for tests that check something in between.
"""

from urllib.parse import quote

from selenium.webdriver.common.by import By

from framework.pages.base_page import BasePage


class DownloadCenterPage(BasePage):
   path = "/files"

   NAMES = (By.CSS_SELECTOR, "#file-list .file-name")

   @property
   def file_names(self):
      return self.texts_of(self.NAMES)

   def download(self, name, mode="converted"):
      self.open(f"/files/{quote(name)}/download?mode={mode}")

   def view(self, name):
      self.open(f"/files/{quote(name)}/view")


class VerdictPage(BasePage):
   """The result of a download: decision, reason, findings, and the password form."""

   FILE = (By.ID, "verdict-file")
   DECISION = (By.ID, "verdict")
   MODE = (By.ID, "verdict-mode")
   REASON = (By.ID, "verdict-reason")
   FINDINGS = (By.CSS_SELECTOR, "#findings .finding")
   PASSWORD = (By.ID, "file-password")
   SUBMIT = (By.ID, "password-submit")

   @property
   def file_name(self):
      return self.text_of(self.FILE)

   @property
   def decision(self):
      return self.text_of(self.DECISION)

   @property
   def mode(self):
      return self.text_of(self.MODE)

   @property
   def reason(self):
      return self.text_of(self.REASON)

   @property
   def findings(self):
      return self.texts_of(self.FINDINGS)

   @property
   def password(self):
      return self.value_of(self.PASSWORD)

   @password.setter
   def password(self, value):
      self.type(self.PASSWORD, value)

   def submit_password(self):
      self.click(self.SUBMIT)


class ViewerPage(BasePage):
   FILE = (By.ID, "viewer-file")
   MODE = (By.ID, "viewer-mode")
   CONTENT = (By.ID, "viewer-content")
   DECISION = (By.ID, "verdict")

   @property
   def file_name(self):
      return self.text_of(self.FILE)

   @property
   def mode(self):
      return self.text_of(self.MODE)

   @property
   def content(self):
      return self.text_of(self.CONTENT)

   @property
   def decision(self):
      return self.text_of(self.DECISION)


class DownloadPolicyPage(BasePage):
   """Download policy editor: the object save writes the working copy; the top bar publishes."""

   path = "/settings/downloads"

   DEFAULT = (By.ID, "download-default")
   ENCRYPTED = (By.ID, "encrypted-files")
   ORIGINALS = (By.ID, "originals")
   SCANNING = (By.ID, "scanning-enabled")
   INSPECT = (By.ID, "archive-inspect")
   DEPTH = (By.ID, "archive-depth")
   SAVE = (By.ID, "policy-save")

   @property
   def default_action(self):
      return self.value_of(self.DEFAULT)

   @default_action.setter
   def default_action(self, value):
      self.select(self.DEFAULT, value)

   @property
   def encrypted_files(self):
      return self.value_of(self.ENCRYPTED)

   @encrypted_files.setter
   def encrypted_files(self, value):
      self.select(self.ENCRYPTED, value)

   @property
   def originals(self):
      return self.value_of(self.ORIGINALS)

   @originals.setter
   def originals(self, value):
      self.select(self.ORIGINALS, value)

   @property
   def scanning_enabled(self):
      return self.checked(self.SCANNING)

   @scanning_enabled.setter
   def scanning_enabled(self, value):
      self.set_checkbox(self.SCANNING, value)

   @property
   def archive_inspection(self):
      return self.checked(self.INSPECT)

   @archive_inspection.setter
   def archive_inspection(self, value):
      self.set_checkbox(self.INSPECT, value)

   @property
   def archive_depth(self):
      return int(self.value_of(self.DEPTH))

   @archive_depth.setter
   def archive_depth(self, value):
      self.type(self.DEPTH, str(value))

   def type_action(self, file_type):
      return self.value_of((By.ID, f"type-{file_type}"))

   def set_type_action(self, file_type, action):
      """Choose the action for one file type (allow, block, sanitize, default)."""
      self.select((By.ID, f"type-{file_type}"), action)

   def save(self):
      self.click(self.SAVE)


class FilesArea:
   def __init__(self, driver, base_url, timeout=10.0):
      self._args = (driver, base_url, timeout)

   @property
   def downloads(self):
      return DownloadCenterPage(*self._args)

   @property
   def verdict(self):
      return VerdictPage(*self._args)

   @property
   def viewer(self):
      return ViewerPage(*self._args)

   @property
   def policy(self):
      return DownloadPolicyPage(*self._args)

   def download_file(self, name, mode="converted", password=None):
      """Download a site file and, if asked for, enter its password. Leaves the verdict open."""
      self.downloads.download(name, mode)
      verdict = self.verdict
      if password is not None and verdict.decision == "password_required":
         verdict.password = password
         verdict.submit_password()

   def view_file(self, name):
      self.downloads.view(name)
