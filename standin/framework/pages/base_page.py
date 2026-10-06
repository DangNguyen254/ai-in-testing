"""Shared page-object behavior: navigation and explicit waits (no implicit waits, no sleeps).

Page-object style: value fields are properties (assign to set, read to get); actions are plain
methods that return nothing. No fluent chaining.
"""

from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as ec
from selenium.webdriver.support.ui import Select, WebDriverWait

TOAST = (By.ID, "toast")
FORM_ERROR = (By.ID, "form-error")
NAV_LINKS = (By.CSS_SELECTOR, "nav a")


class BasePage:
   path = "/"

   def __init__(self, driver, base_url, timeout=10.0):
      self.driver = driver
      self.base_url = base_url.rstrip("/")
      self.timeout = timeout

   def open(self, path=None):
      self.driver.get(self.base_url + (path or self.path))

   def refresh(self):
      self.driver.refresh()

   def wait(self):
      return WebDriverWait(self.driver, self.timeout)

   def find(self, locator):
      return self.wait().until(ec.visibility_of_element_located(locator))

   def find_all(self, locator):
      return self.driver.find_elements(*locator)

   def click(self, locator):
      self.wait().until(ec.element_to_be_clickable(locator)).click()

   def type(self, locator, text):
      element = self.find(locator)
      element.clear()
      element.send_keys(text)

   def select(self, locator, value):
      Select(self.find(locator)).select_by_value(value)

   def value_of(self, locator):
      return str(self.find(locator).get_attribute("value"))

   def text_of(self, locator):
      return self.find(locator).text

   def texts_of(self, locator):
      return [element.text for element in self.find_all(locator)]

   def checked(self, locator):
      return self.find(locator).is_selected()

   def set_checkbox(self, locator, enabled):
      box = self.find(locator)
      if box.is_selected() != enabled:
         box.click()

   @property
   def toast(self):
      return self.text_of(TOAST)

   @property
   def error_message(self):
      return self.text_of(FORM_ERROR)

   @property
   def nav_links(self):
      return self.texts_of(NAV_LINKS)
