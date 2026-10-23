"""Exceptions area: hosts the rules do not apply to.

A list page (search, scope filter, selection, bulk delete, and many read-only widgets checked
one by one) and an editor. Both share a component base with the widgets every exceptions page
shows. This module is large on purpose: real page-object modules run to thousands of lines.
"""

from urllib.parse import quote

from selenium.webdriver.common.by import By

from framework.pages.base_page import BasePage


class ExceptionsPageBase(BasePage):
   """Widgets on every exceptions page."""

   HELP = (By.ID, "exceptions-help")
   TITLE = (By.TAG_NAME, "h1")

   @property
   def help_text(self):
      return self.text_of(self.HELP)

   @property
   def page_title(self):
      return self.text_of(self.TITLE)


class ExceptionListPage(ExceptionsPageBase):
   path = "/exceptions"

   SEARCH_BOX = (By.ID, "exception-search")
   SCOPE_FILTER = (By.ID, "exception-scope-filter")
   SEARCH_BUTTON = (By.ID, "exception-search-button")
   COUNT = (By.ID, "exceptions-count")
   EMPTY = (By.ID, "exceptions-empty")
   ADD = (By.ID, "add-exception")
   EXPORT = (By.ID, "export-exceptions")
   DELETE = (By.ID, "delete-exceptions")
   ROWS = (By.CSS_SELECTOR, "#exceptions-table .exception-row")
   NAMES = (By.CSS_SELECTOR, "#exceptions-table .exception-name")
   TARGETS = (By.CSS_SELECTOR, "#exceptions-table .exception-target")
   SCOPES = (By.CSS_SELECTOR, "#exceptions-table .exception-scope")
   HEADER_NAME = (By.ID, "col-name")
   HEADER_TARGET = (By.ID, "col-target")
   HEADER_SCOPE = (By.ID, "col-scope")
   HEADER_ENABLED = (By.ID, "col-enabled")
   HEADER_EXPIRES = (By.ID, "col-expires")

   # --- values ---------------------------------------------------------------------------

   @property
   def search_text(self):
      return self.value_of(self.SEARCH_BOX)

   @search_text.setter
   def search_text(self, text):
      self.type(self.SEARCH_BOX, text)

   @property
   def scope_filter(self):
      return self.value_of(self.SCOPE_FILTER)

   @scope_filter.setter
   def scope_filter(self, scope):
      self.select(self.SCOPE_FILTER, scope)

   @property
   def exception_names(self):
      return self.texts_of(self.NAMES)

   @property
   def exception_targets(self):
      return self.texts_of(self.TARGETS)

   @property
   def exception_scopes(self):
      return self.texts_of(self.SCOPES)

   @property
   def count_text(self):
      return self.text_of(self.COUNT)

   @property
   def total_count(self):
      return int(self.count_text.split()[0])

   @property
   def empty_message(self):
      return self.text_of(self.EMPTY)

   # --- read-only widgets (checked one by one) ------------------------------------------

   @property
   def add_link_text(self):
      return self.text_of(self.ADD)

   @property
   def export_link_text(self):
      return self.text_of(self.EXPORT)

   @property
   def delete_button_text(self):
      return self.text_of(self.DELETE)

   @property
   def name_header(self):
      return self.text_of(self.HEADER_NAME)

   @property
   def target_header(self):
      return self.text_of(self.HEADER_TARGET)

   @property
   def scope_header(self):
      return self.text_of(self.HEADER_SCOPE)

   @property
   def enabled_header(self):
      return self.text_of(self.HEADER_ENABLED)

   @property
   def expires_header(self):
      return self.text_of(self.HEADER_EXPIRES)

   # --- per row --------------------------------------------------------------------------

   def _cell(self, name, css_class):
      for row in self.find_all(self.ROWS):
         if row.find_element(By.CLASS_NAME, "exception-name").text == name:
            return row.find_element(By.CLASS_NAME, css_class).text
      raise AssertionError(f"{name} is not in the exception list")

   def target_of(self, name):
      return self._cell(name, "exception-target")

   def scope_of(self, name):
      return self._cell(name, "exception-scope")

   def enabled_of(self, name):
      return self._cell(name, "exception-enabled") == "yes"

   def expires_of(self, name):
      return self._cell(name, "exception-expires")

   # --- actions --------------------------------------------------------------------------

   def search(self):
      self.click(self.SEARCH_BUTTON)

   def add_exception(self):
      self.click(self.ADD)

   def open_exception(self, name):
      self.open(f"/exceptions/{quote(name)}/edit")

   def select_exception(self, name):
      self.click((By.CSS_SELECTOR, f'.exception-select[value="{name}"]'))

   def delete_selected(self):
      self.click(self.DELETE)


class ExceptionEditorPage(ExceptionsPageBase):
   path = "/exceptions/new"

   NAME = (By.ID, "exception-name")
   TARGET = (By.ID, "exception-target")
   SCOPE = (By.ID, "exception-scope")
   ENABLED = (By.ID, "exception-enabled")
   EXPIRES = (By.ID, "exception-expires")
   CLEAR_EXPIRY = (By.ID, "exception-clear-expiry")
   SAVE = (By.ID, "exception-save")

   @property
   def name(self):
      return self.value_of(self.NAME)

   @name.setter
   def name(self, value):
      self.type(self.NAME, value)

   @property
   def target(self):
      return self.value_of(self.TARGET)

   @target.setter
   def target(self, value):
      self.type(self.TARGET, value)

   @property
   def scope(self):
      return self.value_of(self.SCOPE)

   @scope.setter
   def scope(self, value):
      self.select(self.SCOPE, value)

   @property
   def enabled(self):
      return self.checked(self.ENABLED)

   @enabled.setter
   def enabled(self, on):
      self.set_checkbox(self.ENABLED, on)

   @property
   def expires(self):
      return self.value_of(self.EXPIRES)

   @expires.setter
   def expires(self, value):
      self.type(self.EXPIRES, value)

   def save(self):
      self.click(self.SAVE)


class ExceptionsArea:
   def __init__(self, driver, base_url, timeout):
      self._args = (driver, base_url, timeout)

   @property
   def list(self):
      return ExceptionListPage(*self._args)

   @property
   def editor(self):
      return ExceptionEditorPage(*self._args)
