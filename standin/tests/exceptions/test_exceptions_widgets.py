"""Exceptions list widgets: one element per test, reached by a dotted page path (no data)."""

import pytest

from framework.decorators import browsers, environments
from tests.exceptions.exceptions_common import ExceptionsCommon


@browsers("chrome", "firefox")
@environments("cloud", "on_prem")
@pytest.mark.project("example-project")
@pytest.mark.component("exceptions")
class TestExceptionsWidgets(ExceptionsCommon):
   def setup(self):
      self.base_setup(fresh_driver=False, policy_wait=False)

   @pytest.mark.priority("p3")
   @pytest.mark.suite("regression")
   def test_exceptions_widget_help_text(self):
      exceptions = self.go_to("exceptions.list")
      self.check.assertEqual(
         "Exceptions list hosts the rules do not apply to.", exceptions.help_text
      )

   @pytest.mark.priority("p3")
   @pytest.mark.suite("regression")
   def test_exceptions_widget_page_title(self):
      exceptions = self.go_to("exceptions.list")
      self.check.assertEqual("Exceptions", exceptions.page_title)

   @pytest.mark.priority("p3")
   @pytest.mark.suite("regression")
   def test_exceptions_widget_add_link(self):
      exceptions = self.go_to("exceptions.list")
      self.check.assertEqual("Add exception", exceptions.add_link_text)

   @pytest.mark.priority("p3")
   @pytest.mark.suite("regression")
   def test_exceptions_widget_export_link(self):
      exceptions = self.go_to("exceptions.list")
      self.check.assertEqual("Export", exceptions.export_link_text)

   @pytest.mark.priority("p3")
   @pytest.mark.suite("regression")
   def test_exceptions_widget_delete_button(self):
      exceptions = self.go_to("exceptions.list")
      self.check.assertEqual("Delete selected", exceptions.delete_button_text)

   @pytest.mark.priority("p3")
   @pytest.mark.suite("regression")
   def test_exceptions_widget_name_header(self):
      exceptions = self.go_to("exceptions.list")
      self.check.assertEqual("Name", exceptions.name_header)

   @pytest.mark.priority("p3")
   @pytest.mark.suite("regression")
   def test_exceptions_widget_target_header(self):
      exceptions = self.go_to("exceptions.list")
      self.check.assertEqual("Target", exceptions.target_header)

   @pytest.mark.priority("p3")
   @pytest.mark.suite("regression")
   def test_exceptions_widget_scope_header(self):
      exceptions = self.go_to("exceptions.list")
      self.check.assertEqual("Scope", exceptions.scope_header)

   @pytest.mark.priority("p3")
   @pytest.mark.suite("regression")
   def test_exceptions_widget_enabled_header(self):
      exceptions = self.go_to("exceptions.list")
      self.check.assertEqual("Enabled", exceptions.enabled_header)

   @pytest.mark.priority("p3")
   @pytest.mark.suite("regression")
   def test_exceptions_widget_expires_header(self):
      exceptions = self.go_to("exceptions.list")
      self.check.assertEqual("Expires", exceptions.expires_header)

   @pytest.mark.priority("p3")
   @pytest.mark.suite("regression")
   def test_exceptions_widget_count_empty(self):
      exceptions = self.go_to("exceptions.list")
      self.check.assertEqual("0 exceptions", exceptions.count_text)

   @pytest.mark.priority("p3")
   @pytest.mark.suite("regression")
   def test_exceptions_widget_empty_message(self):
      exceptions = self.go_to("exceptions.list")
      self.check.assertEqual("No exceptions match.", exceptions.empty_message)
