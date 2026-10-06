"""Rules: adding, editing, deleting, importing, and finding rules in the policy."""

from pathlib import Path

import pytest

from framework.base_test import BaseTest
from framework.decorators import browsers, data_driven, environments, retry, skip_browser

FILES = Path(__file__).parent / "files"


@browsers("chrome", "firefox")
@environments("cloud", "on_prem")
@data_driven
@pytest.mark.project("example-project")
@pytest.mark.component("rules")
class TestRules(BaseTest):
   def setup(self):
      self.base_setup(fresh_driver=False, policy_wait=True)

   @pytest.mark.priority("p0")
   @pytest.mark.suite("smoke")
   @pytest.mark.parametrize("action", ["allow", "deny"])
   def test_rules_add_basic(self, action):
      """
      1. Add a rule in the wizard.
      2. Save the rule, then save and publish the policy.
      3. The published policy has the rule with its action.
      """
      rules = self.nav.rules.list
      rules.open()
      rules.add_rule()

      wizard = self.nav.rules.wizard
      wizard.name = self.unique_name(24)
      wizard.action = action
      wizard.next()
      wizard.save()
      self.check.assertEqual("Rule added", rules.toast)

      top_bar = self.nav.top_bar
      top_bar.save()
      top_bar.publish()
      self.verify_targets()

   @pytest.mark.priority("p2")
   @pytest.mark.suite("regression")
   def test_rules_add_with_condition(self):
      rules = self.nav.rules.list
      rules.open()
      rules.add_rule()

      wizard = self.nav.rules.wizard
      wizard.name = self.unique_name(24)
      wizard.action = "log"
      wizard.description = "Log requests from the north region"
      wizard.next()
      wizard.condition_field = "region"
      wizard.condition_value = "north"
      wizard.save()

      top_bar = self.nav.top_bar
      top_bar.save()
      top_bar.publish()
      self.verify_targets()

   @pytest.mark.priority("p2")
   @pytest.mark.suite("regression")
   def test_rules_add_duplicate_name(self):
      """
      1. Add a rule with the name of an existing rule.
      2. The rule save is refused with an error.
      """
      rules = self.nav.rules.list
      rules.open()
      rules.add_rule()

      wizard = self.nav.rules.wizard
      name = self.unique_name(24)
      wizard.name = name
      wizard.next()
      wizard.save()

      self.check.assertEqual(f"A rule named '{name}' already exists", wizard.error_message)

   @pytest.mark.priority("p1")
   @pytest.mark.suite("regression")
   def test_rules_edit_action(self):
      rules = self.nav.rules.list
      rules.open_rule(self.unique_name(24))

      editor = self.nav.rules.editor
      self.check.assertEqual("allow", editor.action)
      editor.action = "deny"
      editor.save()
      self.check.assertEqual("Rule saved", rules.toast)

      top_bar = self.nav.top_bar
      top_bar.save()
      top_bar.publish()
      self.verify_targets()

   @pytest.mark.priority("p2")
   @pytest.mark.suite("regression")
   def test_rules_edit_disable(self):
      rules = self.nav.rules.list
      rules.open_rule(self.unique_name(24))

      editor = self.nav.rules.editor
      editor.enabled = False
      editor.save()

      top_bar = self.nav.top_bar
      top_bar.save()
      top_bar.publish()
      self.verify_targets()

   @pytest.mark.priority("p2")
   @pytest.mark.suite("regression")
   def test_rules_edit_reset(self):
      """
      1. Change a rule's action and save the rule.
      2. Reset in the top bar instead of publishing.
      3. The published policy still has the old action.
      """
      rules = self.nav.rules.list
      rules.open_rule(self.unique_name(24))

      editor = self.nav.rules.editor
      editor.action = "deny"
      editor.save()

      top_bar = self.nav.top_bar
      self.check.assertEqual("Unsaved changes", top_bar.status)
      top_bar.reset()
      self.check.assertEqual("Published revision 1", top_bar.status)
      self.verify_targets()

   @pytest.mark.priority("p1")
   @pytest.mark.suite("regression")
   def test_rules_delete_single(self):
      rules = self.nav.rules.list
      rules.open()
      rules.select_rule(self.params["delete_name"])
      rules.delete_selected()

      confirm = self.nav.rules.confirm
      self.check.assertEqual([self.params["delete_name"]], confirm.pending)
      confirm.confirm()

      top_bar = self.nav.top_bar
      top_bar.save()
      top_bar.publish()
      self.verify_targets()

   @pytest.mark.priority("p2")
   @pytest.mark.suite("regression")
   def test_rules_delete_several(self):
      rules = self.nav.rules.list
      rules.open()
      for name in self.params["delete_names"]:
         rules.select_rule(name)
      rules.delete_selected()
      self.nav.rules.confirm.confirm()

      top_bar = self.nav.top_bar
      top_bar.save()
      top_bar.publish()
      self.verify_targets()

   @pytest.mark.priority("p2")
   @pytest.mark.suite("regression")
   @pytest.mark.parametrize("match", ["exact", "partial", "mixed_case"])
   def test_rules_list_search(self, match):
      rules = self.nav.rules.list
      rules.open()
      rules.search_text = self.params["query"]
      rules.search()

      self.check.assertEqual(self.params["total_count"], rules.total_count)

   @pytest.mark.priority("p2")
   @pytest.mark.suite("regression")
   @pytest.mark.parametrize("action", ["allow", "deny"])
   def test_rules_list_filter_action(self, action):
      rules = self.nav.rules.list
      rules.open()
      rules.action_filter = action
      rules.search()

      self.check.assertEqual(self.params["total_count"], rules.total_count)
      self.check.assertEqual({action}, set(rules.rule_actions))

   @pytest.mark.priority("p3")
   @pytest.mark.suite("regression")
   @retry(times=2)
   def test_rules_list_pagination(self):
      """
      1. Filter the rule list by the allow action.
      2. Page 1 is full and shows only allow rules.
      3. Go to the next page.
      4. The filter is kept and page 2 shows the remaining allow rules.
      """
      rules = self.nav.rules.list
      rules.open()
      rules.action_filter = "allow"
      rules.search()

      self.check.assertEqual(self.params["total_count"], rules.total_count)
      self.check.assertEqual(rules.page_size, len(rules.rule_names))
      self.check.assertEqual({"allow"}, set(rules.rule_actions))

      rules.next_page()

      self.check.assertEqual(2, rules.page_number)
      self.check.assertEqual("allow", rules.action_filter)
      self.check.assertEqual(self.params["page_2_names"], rules.rule_names)
      self.check.assertEqual({"allow"}, set(rules.rule_actions))

   @pytest.mark.priority("p3")
   @pytest.mark.suite("regression")
   def test_rules_list_empty(self):
      rules = self.nav.rules.list
      rules.open()

      self.check.assertEqual(0, rules.total_count)

   @pytest.mark.priority("p2")
   @pytest.mark.suite("regression")
   def test_rules_save_blocked_disabled(self):
      rules = self.nav.rules.list
      rules.open_rule(self.unique_name(24))
      editor = self.nav.rules.editor
      editor.description = "Pending change"
      editor.save()

      self.settings.set_capabilities(rules=False)
      rules.refresh()
      self.check.assertFalse(self.nav.top_bar.save_enabled)

   @pytest.mark.priority("p2")
   @pytest.mark.suite("regression")
   @skip_browser("firefox", reason="large textarea values are slow to set in the driver")
   def test_rules_import_file(self):
      rules = self.nav.rules.list
      rules.open()
      rules.import_rules()

      importer = self.nav.rules.importer
      importer.load_file(FILES / "rules_import.json")
      importer.start_import()
      self.check.assertEqual("Imported 2 rules", rules.toast)

      top_bar = self.nav.top_bar
      top_bar.save()
      top_bar.publish()
      self.verify_targets()

   @pytest.mark.priority("p2")
   @pytest.mark.suite("regression")
   def test_rules_list_api_created(self):
      name = self.unique_name(24)
      self.policy.add_rule(name, "deny")

      rules = self.nav.rules.list
      rules.open()
      rules.search_text = name
      rules.search()
      self.check.assertIn(name, rules.rule_names)
