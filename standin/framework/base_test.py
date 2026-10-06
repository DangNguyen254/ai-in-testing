"""Base class for every stand-in test."""

from framework.api_client import ApiClient
from framework.check import Check
from framework.config import CONFIG
from framework.driver import create_driver
from framework.pages import Navigator
from framework.validations import ValidationMixin


class BaseTest(ValidationMixin):
   """Setup: API client, assertion object, clean backend. The ``data_driven`` decorator's
   fixture then loads the test's entry as ``self.params`` and applies its seed sections.
   Teardown: failure artifacts (see conftest), browser quit, backend reset.

   The browser starts only when a test touches ``self.driver`` or ``self.nav``, so pure API
   tests never launch one.
   """

   config = CONFIG
   data_driven = False

   def setup_method(self, method):
      self._driver = None
      self.params = {}
      self.check = Check()
      self.api = ApiClient(self.config.api_url, timeout=self.config.default_timeout)
      self.api.reset()

   def teardown_method(self, method):
      if self._driver is not None:
         self._driver.quit()
         self._driver = None
      self.api.reset()

   @property
   def driver(self):
      if self._driver is None:
         self._driver = create_driver(self.config)
      return self._driver

   @property
   def nav(self):
      return Navigator(self.driver, self.config.base_url, self.config.default_timeout)

   def save_failure_artifacts(self, test_name):
      if self._driver is None:
         return
      folder = self.config.artifacts_dir
      folder.mkdir(parents=True, exist_ok=True)
      safe = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in test_name)
      self._driver.save_screenshot(str(folder / f"{safe}.png"))
      (folder / f"{safe}.html").write_text(self._driver.page_source, encoding="utf-8")
