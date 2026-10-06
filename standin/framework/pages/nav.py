"""Root of the page-object hierarchy: ``nav.<area>.<page>``."""

from framework.pages.inventory import InventoryArea
from framework.pages.orders import OrdersArea
from framework.pages.settings import SettingsArea
from framework.pages.users import UsersArea


class Navigator:
   def __init__(self, driver, base_url, timeout=10.0):
      self._args = (driver, base_url, timeout)

   @property
   def inventory(self):
      return InventoryArea(*self._args)

   @property
   def users(self):
      return UsersArea(*self._args)

   @property
   def orders(self):
      return OrdersArea(*self._args)

   @property
   def settings(self):
      return SettingsArea(*self._args)
