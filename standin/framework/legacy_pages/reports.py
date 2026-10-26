"""The old report list page: getters instead of properties, and its own driver handling.

It has the same class name as ``framework.pages.reports.ReportListPage``; which one a test gets
depends on what it imports.
"""

from selenium.webdriver.common.by import By


class ReportListPage:
   NAMES = (By.CSS_SELECTOR, ".report-name")

   def __init__(self, driver):
      self.driver = driver

   def go(self, base_url):
      self.driver.get(base_url.rstrip("/") + "/reports")

   def get_names(self):
      return [element.text for element in self.driver.find_elements(*self.NAMES)]
