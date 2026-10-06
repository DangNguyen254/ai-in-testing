"""Base class for every stand-in test.

The framework fixture runs around each test: it loads the test's data entry (``self.params``,
placeholders resolved) for ``data_driven`` classes or tests that take ``params``, then calls
``self.setup()`` and afterwards ``self.teardown()``. Classes override ``setup`` to call
``base_setup`` with their options; runtime-style classes may also use ``setup_method`` /
``teardown_method``.
"""

import unittest
from pathlib import Path

import pytest

from framework.api_client import ApiClient
from framework.config import CONFIG
from framework.data import entry_for, seed_blocks
from framework.driver import create_driver
from framework.managers import PolicyManager, SettingsManager
from framework.pages import Navigator
from framework.placeholders import resolve, unique_name, unique_suffix
from framework.validations import ValidationMixin


class BaseTest(ValidationMixin):
   config = CONFIG
   data_driven = False
   _shared_driver = None

   @pytest.fixture(autouse=True)
   def _framework(self, request):
      self.test_id = request.node.name
      self._suffix = unique_suffix()
      self._driver = None
      self._fresh_driver = True
      self.params = {}
      if self.data_driven or "params" in request.fixturenames:
         entry = entry_for(Path(request.node.path), self.test_id) or {}
         self.params = resolve(entry, self.test_id, self._suffix)
      self.setup()
      yield
      self.teardown()
      if self._driver is not None and self._fresh_driver:
         self._driver.quit()
      self._driver = None

   # --- per-class hooks ------------------------------------------------------------------

   def setup(self):
      self.base_setup()

   def teardown(self):
      pass

   def base_setup(self, fresh_driver=True, policy_wait=True, skip_seed=False):
      """Reset the backend, apply the seed, and provide the page-object root and checks."""
      self._fresh_driver = fresh_driver
      self.policy_wait = policy_wait
      self.primary_tenant = self.config.tenants[0]
      self.user = self.config.users[0]
      self.api = ApiClient(self.config.api_url, timeout=self.config.default_timeout)
      self.api.reset()
      if not skip_seed:
         self.apply_seed()
      self.check = unittest.TestCase()  # the assertion object
      self.policy = PolicyManager(self.api, self.primary_tenant, self.config.service_user)
      self.settings = SettingsManager(self.api, self.primary_tenant)

   def apply_seed(self):
      service = {"roles": {self.config.service_user: "admin"}}
      blocks = [{"tenant": tenant, "settings": service} for tenant in self.config.tenants]
      self.api.seed(blocks + seed_blocks(self.params, self.primary_tenant))

   # --- browser --------------------------------------------------------------------------

   @property
   def driver(self):
      if self._driver is None:
         shared = type(self)._shared_driver
         if not self._fresh_driver and shared is not None:
            self._driver = shared
         else:
            self._driver = create_driver(self.config)
            if not self._fresh_driver:
               type(self)._shared_driver = self._driver
         self.login_as(self.primary_tenant, self.user)
      return self._driver

   @property
   def nav(self):
      return Navigator(self.driver, self.config.base_url, self.config.default_timeout)

   def login_as(self, tenant, user):
      self.driver.get(f"{self.config.base_url.rstrip('/')}/login?tenant={tenant}&user={user}")

   def logout(self):
      if self._driver is not None:
         self._driver.get(f"{self.config.base_url.rstrip('/')}/logout")

   @classmethod
   def teardown_class(cls):
      if cls._shared_driver is not None:
         cls._shared_driver.quit()
         cls._shared_driver = None

   # --- helpers --------------------------------------------------------------------------

   def unique_name(self, limit):
      """The same name the data placeholder ``{test_id:<limit>}`` resolves to."""
      return unique_name(self.test_id, self._suffix, limit)

   def save_failure_artifacts(self, test_name):
      if self._driver is None:
         return
      folder = self.config.artifacts_dir
      folder.mkdir(parents=True, exist_ok=True)
      safe = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in test_name)
      self._driver.save_screenshot(str(folder / f"{safe}.png"))
      (folder / f"{safe}.html").write_text(self._driver.page_source, encoding="utf-8")
