"""Agent area: the browsing agent's console and its settings (the injection guard)."""

from selenium.webdriver.common.by import By

from framework.pages.base_page import BasePage


class AgentConsolePage(BasePage):
   path = "/agent"

   GOAL = (By.ID, "agent-goal")
   START = (By.ID, "agent-start")
   RUN = (By.ID, "agent-run")
   STATUS = (By.ID, "agent-status")
   ACTIONS = (By.CSS_SELECTOR, "#agent-actions .agent-action")
   FLAGS = (By.CSS_SELECTOR, "#agent-flags .agent-flag")
   OPEN_BROWSER = (By.ID, "agent-open-browser")
   BROWSERS = (By.CSS_SELECTOR, "#agent-browsers .agent-browser")
   CLOSE_BROWSER = (By.CSS_SELECTOR, "#agent-browsers .agent-browser-close")
   BROWSER_MESSAGE = (By.ID, "agent-browser-message")

   @property
   def goal(self):
      return self.value_of(self.GOAL)

   @goal.setter
   def goal(self, value):
      self.type(self.GOAL, value)

   @property
   def start_page(self):
      return self.value_of(self.START)

   @start_page.setter
   def start_page(self, path):
      self.select(self.START, path)

   @property
   def status(self):
      return self.text_of(self.STATUS)

   @property
   def actions(self):
      return self.texts_of(self.ACTIONS)

   @property
   def flags(self):
      return self.texts_of(self.FLAGS)

   def run(self):
      self.click(self.RUN)

   @property
   def open_browsers(self):
      """How many agent browser sessions the console lists as open."""
      return len(self.texts_of(self.BROWSERS))

   @property
   def browser_message(self):
      return self.text_of(self.BROWSER_MESSAGE)

   def open_browser(self):
      self.click(self.OPEN_BROWSER)

   def close_browser(self, number=1):
      """Close the console's n-th open browser session (1 = the oldest)."""
      self.click_nth(self.CLOSE_BROWSER, number)

   def run_task(self, goal, start_page):
      """Open the console, enter the task, and run it (the reusable multi-step helper)."""
      self.open()
      self.goal = goal
      self.start_page = start_page
      self.run()


class AgentSettingsPage(BasePage):
   path = "/settings/agent"

   GUARD = (By.ID, "injection-guard")
   APPLY = (By.ID, "agent-settings-save")

   @property
   def injection_guard(self):
      return self.checked(self.GUARD)

   @injection_guard.setter
   def injection_guard(self, enabled):
      self.set_checkbox(self.GUARD, enabled)

   def apply(self):
      self.click(self.APPLY)


class AgentArea:
   def __init__(self, driver, base_url, timeout=10.0):
      self._args = (driver, base_url, timeout)

   @property
   def console(self):
      return AgentConsolePage(*self._args)

   @property
   def settings(self):
      return AgentSettingsPage(*self._args)
