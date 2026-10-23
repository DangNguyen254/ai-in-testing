"""Shared bases for the exceptions area (not collected: the module has no test_ prefix).

``ExceptionsCommon`` holds the area's helpers; ``ExceptionsTests`` adds the setup most
exceptions classes use. Lineage: ExceptionsTests -> ExceptionsCommon -> BaseTest ->
ValidationMixin.
"""

from framework.base_test import BaseTest


class ExceptionsCommon(BaseTest):
   def open_exception(self, name):
      """Open an exception's editor from the list."""
      exceptions = self.nav.exceptions.list
      exceptions.open()
      exceptions.open_exception(name)
      return self.nav.exceptions.editor

   def _navigate_with_retry(self, path, attempts=3):
      """Open a page, retrying while the list is still loading (a third retry style)."""
      for attempt in range(attempts):
         page = self.go_to(path)
         if page.find_all(page.ROWS) or attempt == attempts - 1:
            return page
      return page


class ExceptionsTests(ExceptionsCommon):
   def setup(self):
      self.base_setup(fresh_driver=False, policy_wait=True)
