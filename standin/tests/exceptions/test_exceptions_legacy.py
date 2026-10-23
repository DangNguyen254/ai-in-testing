"""Older exceptions tests in unittest style: setUp/tearDown and asserts on self. Cloud-only
through a deployment condition on the class (not the environments decorator)."""

import pytest

from framework.config import CONFIG
from framework.decorators import browsers
from framework.legacy_base import LegacyBrowserBase


@browsers("chrome", "firefox")
@pytest.mark.skipif(CONFIG.deployment != "cloud", reason="cloud-only test")
@pytest.mark.project("example-project")
@pytest.mark.component("exceptions")
class TestExceptionsLegacyList(LegacyBrowserBase):
   @pytest.mark.priority("p3")
   @pytest.mark.suite("regression")
   def test_exceptions_legacy_list_names(self):
      exceptions = self.nav.exceptions.list
      exceptions.open()
      self.assertEqual(self.params["expected_names"], exceptions.exception_names)

   @pytest.mark.priority("p3")
   @pytest.mark.suite("regression")
   def test_exceptions_legacy_list_targets(self):
      exceptions = self.nav.exceptions.list
      exceptions.open()
      self.assertIn(self.params["target"], exceptions.exception_targets)


@browsers("chrome", "firefox")
@pytest.mark.skipif(CONFIG.deployment != "cloud", reason="cloud-only test")
@pytest.mark.project("example-project")
@pytest.mark.component("exceptions")
class TestExceptionsLegacyEditor(LegacyBrowserBase):
   @pytest.mark.priority("p3")
   @pytest.mark.suite("regression")
   def test_exceptions_legacy_editor_scope(self):
      exceptions = self.nav.exceptions.list
      exceptions.open()
      exceptions.open_exception(self.params["name"])
      self.assertEqual("group", self.nav.exceptions.editor.scope)
