"""Exceptions: add, edit, delete, list. The data file starts with a defaults row."""

import pytest

from framework.decorators import browsers, data_driven, environments
from tests.exceptions.exceptions_common import ExceptionsCommon, ExceptionsTests


@browsers("chrome", "firefox")
@environments("cloud", "on_prem")
@data_driven
@pytest.mark.project("example-project")
@pytest.mark.component("exceptions")
class TestExceptions(ExceptionsTests):
   @pytest.mark.priority("p1")
   @pytest.mark.suite("regression")
   @pytest.mark.parametrize("scope", ["all", "group"])
   def test_exceptions_add_basic(self, scope):
      exceptions = self.nav.exceptions.list
      exceptions.open()
      exceptions.add_exception()
      editor = self.nav.exceptions.editor
      editor.name = self.unique_name(24)
      editor.target = self.params["target"]
      editor.scope = scope
      editor.save()
      self.nav.top_bar.save()
      self.nav.top_bar.publish()
      self.verify_targets()

   @pytest.mark.priority("p2")
   @pytest.mark.suite("regression")
   def test_exceptions_add_with_expiry(self):
      exceptions = self.nav.exceptions.list
      exceptions.open()
      exceptions.add_exception()
      editor = self.nav.exceptions.editor
      editor.name = self.unique_name(24)
      editor.target = self.params["target"]
      editor.expires = self.params["expires"]
      editor.save()
      self.nav.top_bar.save()
      self.nav.top_bar.publish()
      self.verify_targets()

   @pytest.mark.priority("p2")
   @pytest.mark.suite("regression")
   def test_exceptions_add_missing_target(self):
      exceptions = self.nav.exceptions.list
      exceptions.open()
      exceptions.add_exception()
      editor = self.nav.exceptions.editor
      editor.name = self.unique_name(24)
      editor.save()
      self.check.assertIn("Target is required", editor.error_message)

   @pytest.mark.priority("p1")
   @pytest.mark.suite("regression")
   def test_exceptions_edit_target(self):
      editor = self.open_exception(self.unique_name(24))
      editor.target = self.params["new_target"]
      editor.save()
      self.nav.top_bar.save()
      self.nav.top_bar.publish()
      self.verify_targets()

   @pytest.mark.priority("p2")
   @pytest.mark.suite("regression")
   def test_exceptions_edit_disable(self):
      editor = self.open_exception(self.unique_name(24))
      editor.enabled = False
      editor.save()
      self.nav.top_bar.save()
      self.nav.top_bar.publish()
      self.verify_targets()

   @pytest.mark.priority("p2")
   @pytest.mark.suite("regression")
   def test_exceptions_delete_several(self):
      exceptions = self.nav.exceptions.list
      exceptions.open()
      for name in self.params["delete_names"]:
         exceptions.select_exception(name)
      exceptions.delete_selected()
      self.nav.top_bar.save()
      self.nav.top_bar.publish()
      self.verify_targets()

   @pytest.mark.priority("p3")
   @pytest.mark.suite("regression")
   @pytest.mark.parametrize("match", ["by_name", "by_target"])
   def test_exceptions_list_search(self, match):
      exceptions = self.nav.exceptions.list
      exceptions.open()
      exceptions.search_text = self.params["query"]
      exceptions.search()
      self.check.assertEqual(self.params["expected_names"], exceptions.exception_names)

   @pytest.mark.priority("p3")
   @pytest.mark.suite("regression")
   def test_exceptions_list_scope_filter(self):
      exceptions = self.nav.exceptions.list
      exceptions.open()
      exceptions.scope_filter = "group"
      exceptions.search()
      self.check.assertEqual(self.params["total_count"], exceptions.total_count)
      self.check.assertEqual({"group"}, set(exceptions.exception_scopes))

   @pytest.mark.priority("p3")
   @pytest.mark.suite("regression")
   def test_exceptions_list_empty(self):
      exceptions = self.nav.exceptions.list
      exceptions.open()
      self.check.assertEqual("No exceptions match.", exceptions.empty_message)


@browsers("chrome", "firefox")
@environments("cloud", "on_prem")
@data_driven
@pytest.mark.project("example-project")
@pytest.mark.component("exceptions,rules")
class TestExceptionsRules(ExceptionsCommon):
   def setup(self):
      self.base_setup(fresh_driver=True, policy_wait=True)

   @pytest.mark.priority("p2")
   @pytest.mark.suite("regression")
   def test_exceptions_rules_same_name_published(self):
      """
      1. Add a rule and an exception with the same name.
      2. Both are published: names are unique per list, not across lists.
      """
      name = self.unique_name(24)
      rules = self.nav.rules.list
      rules.open()
      rules.add_rule()
      wizard = self.nav.rules.wizard
      wizard.name = name
      wizard.next()
      wizard.save()
      exceptions = self.nav.exceptions.list
      exceptions.open()
      exceptions.add_exception()
      editor = self.nav.exceptions.editor
      editor.name = name
      editor.target = self.params["target"]
      editor.save()
      self.nav.top_bar.save()
      self.nav.top_bar.publish()
      self.verify_targets()
