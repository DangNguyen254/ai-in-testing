"""Root of the page-object hierarchy: ``nav.<area>.<page>``, plus the shared ``nav.top_bar``."""

from framework.pages.agent import AgentArea
from framework.pages.exceptions import ExceptionsArea
from framework.pages.files import FilesArea
from framework.pages.profiles import ProfilesArea
from framework.pages.rules import RulesArea
from framework.pages.settings import SettingsArea
from framework.pages.top_bar import TopBar


class Navigator:
   def __init__(self, driver, base_url, timeout=10.0):
      self._args = (driver, base_url, timeout)

   @property
   def top_bar(self):
      return TopBar(*self._args)

   @property
   def rules(self):
      return RulesArea(*self._args)

   @property
   def profiles(self):
      return ProfilesArea(*self._args)

   @property
   def exceptions(self):
      return ExceptionsArea(*self._args)

   @property
   def settings(self):
      return SettingsArea(*self._args)

   @property
   def files(self):
      return FilesArea(*self._args)

   @property
   def agent(self):
      return AgentArea(*self._args)
