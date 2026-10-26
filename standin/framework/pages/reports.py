"""Reports area: the report list (search, export) and one report's view."""

from urllib.parse import quote

from selenium.webdriver.common.by import By

from framework.pages.base_page import BasePage


class ReportListPage(BasePage):
   path = "/reports"

   SEARCH_BOX = (By.ID, "report-search")
   SEARCH_BUTTON = (By.ID, "report-search-button")
   NAMES = (By.CSS_SELECTOR, "#reports-table .report-name")
   COUNT = (By.ID, "report-count")
   EXPORT = (By.ID, "report-export")

   @property
   def search_text(self):
      return self.value_of(self.SEARCH_BOX)

   @search_text.setter
   def search_text(self, text):
      self.type(self.SEARCH_BOX, text)

   @property
   def report_names(self):
      return self.texts_of(self.NAMES)

   @property
   def total_count(self):
      return int(self.text_of(self.COUNT))

   def search(self):
      self.click(self.SEARCH_BUTTON)

   def export(self):
      self.click(self.EXPORT)


class ReportViewPage(BasePage):
   path = "/reports/view"

   TITLE = (By.ID, "report-title")
   ROWS = (By.CSS_SELECTOR, "#report-rows .report-row")

   @property
   def title(self):
      return self.text_of(self.TITLE)

   @property
   def row_count(self):
      return len(self.find_all(self.ROWS))

   def open_report(self, name):
      self.open(f"/reports/{quote(name)}")


class ReportsArea:
   def __init__(self, driver, base_url, timeout):
      self._args = (driver, base_url, timeout)

   @property
   def list(self):
      return ReportListPage(*self._args)

   @property
   def view(self):
      return ReportViewPage(*self._args)
