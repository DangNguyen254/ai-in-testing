"""Profiles: adding, editing, deleting, and finding profiles in the policy.

This class takes its data entry as a ``params`` argument, and creates some state through the
UI first with ``_add_profile``.
"""

import pytest

from framework.base_test import BaseTest
from framework.decorators import browsers, environments


@browsers("chrome", "firefox")
@environments("cloud", "on_prem")
@pytest.mark.project("example-project")
@pytest.mark.component("profiles")
class TestProfiles(BaseTest):
   def setup(self):
      self.base_setup(fresh_driver=True)

   def _add_profile(self, name, level):
      profiles = self.nav.profiles.list
      profiles.open()
      profiles.add_profile()
      editor = self.nav.profiles.editor
      editor.name = name
      editor.level = level
      editor.save()

   @pytest.mark.priority("p1")
   @pytest.mark.suite("smoke")
   def test_profiles_add_basic(self, params):
      profiles = self.nav.profiles.list
      profiles.open()
      profiles.add_profile()

      editor = self.nav.profiles.editor
      editor.name = self.unique_name(24)
      editor.level = "medium"
      editor.description = "Default profile for new teams"
      editor.save()
      self.check.assertEqual("Profile added", profiles.toast)

      top_bar = self.nav.top_bar
      top_bar.save()
      top_bar.publish()
      self.verify_targets()

   @pytest.mark.priority("p2")
   @pytest.mark.suite("regression")
   @pytest.mark.parametrize("level", ["low", "high"])
   def test_profiles_edit_level(self, params, level):
      profiles = self.nav.profiles.list
      profiles.open_profile(self.unique_name(24))

      editor = self.nav.profiles.editor
      editor.level = level
      editor.save()
      self.check.assertEqual(level, profiles.level_of(self.unique_name(24)))

      top_bar = self.nav.top_bar
      top_bar.save()
      top_bar.publish()
      self.verify_targets()

   @pytest.mark.priority("p2")
   @pytest.mark.suite("regression")
   def test_profiles_delete_created(self, params):
      """
      1. Add two profiles through the UI and publish them.
      2. Delete one, then save and publish.
      3. The published policy keeps only the other profile.
      """
      self._add_profile(params["keep_name"], "low")
      self._add_profile(params["delete_name"], "high")
      top_bar = self.nav.top_bar
      top_bar.save()
      top_bar.publish()

      profiles = self.nav.profiles.list
      profiles.open()
      profiles.delete_profile(params["delete_name"])
      self.check.assertNotIn(params["delete_name"], profiles.profile_names)

      top_bar.save()
      top_bar.publish()
      self.verify_targets()

   @pytest.mark.priority("p2")
   @pytest.mark.suite("regression")
   def test_profiles_edit_reset(self, params):
      profiles = self.nav.profiles.list
      profiles.open_profile(self.unique_name(24))

      editor = self.nav.profiles.editor
      editor.level = "high"
      editor.save()

      top_bar = self.nav.top_bar
      top_bar.reset()
      self.check.assertEqual("low", profiles.level_of(self.unique_name(24)))
      self.verify_targets()

   @pytest.mark.priority("p3")
   @pytest.mark.suite("regression")
   def test_profiles_list_search(self, params):
      profiles = self.nav.profiles.list
      profiles.open()
      profiles.search_text = "team"
      profiles.search()

      self.check.assertEqual(params["expected_names"], profiles.profile_names)

   @pytest.mark.priority("p3")
   @pytest.mark.suite("regression")
   def test_profiles_list_empty(self):
      profiles = self.nav.profiles.list
      profiles.open()

      self.check.assertEqual([], profiles.profile_names)
