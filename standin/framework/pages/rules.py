"""Rules area: rule list (search, filter, pagination, delete), add wizard, editor, import."""

from pathlib import Path
from urllib.parse import quote

from selenium.webdriver.common.by import By

from framework.pages.base_page import BasePage


class RuleListPage(BasePage):
   """Rules listed by name (ignoring case), ``page_size`` per page.

   ``total_count`` counts every match across all pages; ``rule_names`` and ``rule_actions``
   are the rows of the current page. A search text or action filter applies on ``search()``.
   """

   path = "/rules"

   SEARCH_BOX = (By.ID, "search-box")
   ACTION_FILTER = (By.ID, "action-filter")
   SEARCH_BUTTON = (By.ID, "search-button")
   ADD_RULE = (By.ID, "add-rule")
   IMPORT = (By.ID, "import-rules")
   DELETE_SELECTED = (By.ID, "delete-selected")
   NAMES = (By.CSS_SELECTOR, "#rules-table .rule-name")
   ACTIONS = (By.CSS_SELECTOR, "#rules-table .rule-action")
   TOTAL = (By.ID, "rule-total")
   PAGE_NUMBER = (By.ID, "page-number")
   PAGE_COUNT = (By.ID, "page-count")
   PAGE_SIZE = (By.ID, "page-size")
   NEXT_PAGE = (By.ID, "next-page")

   @property
   def search_text(self):
      return self.value_of(self.SEARCH_BOX)

   @search_text.setter
   def search_text(self, text):
      self.type(self.SEARCH_BOX, text)

   @property
   def action_filter(self):
      return self.value_of(self.ACTION_FILTER)

   @action_filter.setter
   def action_filter(self, action):
      self.select(self.ACTION_FILTER, action)

   @property
   def rule_names(self):
      return self.texts_of(self.NAMES)

   @property
   def rule_actions(self):
      return self.texts_of(self.ACTIONS)

   @property
   def total_count(self):
      return int(self.text_of(self.TOTAL))

   @property
   def page_number(self):
      return int(self.text_of(self.PAGE_NUMBER))

   @property
   def page_count(self):
      return int(self.text_of(self.PAGE_COUNT))

   @property
   def page_size(self):
      return int(self.text_of(self.PAGE_SIZE))

   def search(self):
      self.click(self.SEARCH_BUTTON)

   def next_page(self):
      self.click(self.NEXT_PAGE)

   def add_rule(self):
      self.click(self.ADD_RULE)

   def import_rules(self):
      self.click(self.IMPORT)

   def open_rule(self, name):
      self.open(f"/rules/{quote(name)}/edit")

   def select_rule(self, name):
      self.click((By.CSS_SELECTOR, f'.rule-select[value="{name}"]'))

   def delete_selected(self):
      self.click(self.DELETE_SELECTED)


class RuleWizardPage(BasePage):
   """Add wizard: step 1 (details) -> ``next()`` -> step 2 (conditions) -> ``save()``."""

   path = "/rules/new"

   NAME = (By.ID, "rule-name")
   ACTION = (By.ID, "rule-action")
   DESCRIPTION = (By.ID, "rule-description")
   CONDITION_FIELD = (By.ID, "condition-field")
   CONDITION_VALUE = (By.ID, "condition-value")
   NEXT = (By.ID, "wizard-next")
   SAVE = (By.ID, "rule-save")

   @property
   def name(self):
      return self.value_of(self.NAME)

   @name.setter
   def name(self, value):
      self.type(self.NAME, value)

   @property
   def action(self):
      return self.value_of(self.ACTION)

   @action.setter
   def action(self, value):
      self.select(self.ACTION, value)

   @property
   def description(self):
      return self.value_of(self.DESCRIPTION)

   @description.setter
   def description(self, value):
      self.type(self.DESCRIPTION, value)

   @property
   def condition_field(self):
      return self.value_of(self.CONDITION_FIELD)

   @condition_field.setter
   def condition_field(self, value):
      self.type(self.CONDITION_FIELD, value)

   @property
   def condition_value(self):
      return self.value_of(self.CONDITION_VALUE)

   @condition_value.setter
   def condition_value(self, value):
      self.type(self.CONDITION_VALUE, value)

   def next(self):
      self.click(self.NEXT)

   def save(self):
      """Save the rule into the policy (the top-bar save and publish come after)."""
      self.click(self.SAVE)


class RuleEditorPage(BasePage):
   ACTION = (By.ID, "rule-action")
   ENABLED = (By.ID, "rule-enabled")
   DESCRIPTION = (By.ID, "rule-description")
   SAVE = (By.ID, "rule-save")

   @property
   def action(self):
      return self.value_of(self.ACTION)

   @action.setter
   def action(self, value):
      self.select(self.ACTION, value)

   @property
   def enabled(self):
      return self.checked(self.ENABLED)

   @enabled.setter
   def enabled(self, value):
      self.set_checkbox(self.ENABLED, value)

   @property
   def description(self):
      return self.value_of(self.DESCRIPTION)

   @description.setter
   def description(self, value):
      self.type(self.DESCRIPTION, value)

   def save(self):
      self.click(self.SAVE)


class DeleteConfirmPage(BasePage):
   PENDING = (By.CSS_SELECTOR, "#pending-deletes .pending-delete")
   CONFIRM = (By.ID, "confirm-delete")
   CANCEL = (By.ID, "cancel-delete")

   @property
   def pending(self):
      return self.texts_of(self.PENDING)

   def confirm(self):
      self.click(self.CONFIRM)

   def cancel(self):
      self.click(self.CANCEL)


class ImportPage(BasePage):
   path = "/rules/import"

   CONTENT = (By.ID, "import-content")
   IMPORT = (By.ID, "import-button")

   @property
   def content(self):
      return self.value_of(self.CONTENT)

   @content.setter
   def content(self, text):
      element = self.find(self.CONTENT)
      self.driver.execute_script("arguments[0].value = arguments[1];", element, text)

   def load_file(self, path):
      """Put a rules file (JSON list of rules) into the import form."""
      self.content = Path(path).read_text(encoding="utf-8")

   def start_import(self):
      self.click(self.IMPORT)


class RulesArea:
   def __init__(self, driver, base_url, timeout):
      self._args = (driver, base_url, timeout)

   @property
   def list(self):
      return RuleListPage(*self._args)

   @property
   def wizard(self):
      return RuleWizardPage(*self._args)

   @property
   def editor(self):
      return RuleEditorPage(*self._args)

   @property
   def confirm(self):
      return DeleteConfirmPage(*self._args)

   @property
   def importer(self):
      return ImportPage(*self._args)
