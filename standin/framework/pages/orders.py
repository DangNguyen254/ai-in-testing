"""Orders area: order list, checkout, and order detail."""

from selenium.webdriver.common.by import By

from framework.pages.base_page import BasePage


class OrderListPage(BasePage):
   path = "/orders"

   STATUS_FILTER = (By.ID, "status-filter")
   APPLY = (By.ID, "apply-filter")
   STATUSES = (By.CSS_SELECTOR, "#orders-table .order-status")
   IDS = (By.CSS_SELECTOR, "#orders-table .order-id")

   @property
   def status_filter(self):
      return self.value_of(self.STATUS_FILTER)

   @status_filter.setter
   def status_filter(self, status):
      self.select(self.STATUS_FILTER, status)

   @property
   def statuses(self):
      return self.texts_of(self.STATUSES)

   @property
   def order_ids(self):
      return [int(text) for text in self.texts_of(self.IDS)]

   def apply_filter(self):
      self.click(self.APPLY)


class CheckoutPage(BasePage):
   path = "/orders/new"

   ITEM = (By.ID, "checkout-item")
   QUANTITY = (By.ID, "checkout-quantity")
   PLACE = (By.ID, "place-order")

   @property
   def item(self):
      return self.value_of(self.ITEM)

   @item.setter
   def item(self, name):
      self.select(self.ITEM, name)

   @property
   def quantity(self):
      return self.value_of(self.QUANTITY)

   @quantity.setter
   def quantity(self, value):
      self.type(self.QUANTITY, str(value))

   def place_order(self):
      self.click(self.PLACE)


class OrderDetailPage(BasePage):
   STATUS = (By.ID, "order-status")
   CANCEL = (By.ID, "cancel-order")
   NOTE_TEXT = (By.ID, "note-text")
   ADD_NOTE = (By.ID, "add-note")
   NOTES = (By.CSS_SELECTOR, "#notes .note")

   def open_for(self, order_id):
      self.open(f"/orders/{order_id}")

   @property
   def status(self):
      return self.text_of(self.STATUS)

   @property
   def order_id(self):
      return int(self.driver.current_url.rstrip("/").split("/")[-1].split("?")[0])

   @property
   def note_text(self):
      return self.value_of(self.NOTE_TEXT)

   @note_text.setter
   def note_text(self, text):
      self.type(self.NOTE_TEXT, text)

   @property
   def notes(self):
      return self.texts_of(self.NOTES)

   def cancel(self):
      self.click(self.CANCEL)

   def add_note(self):
      self.click(self.ADD_NOTE)


class OrdersArea:
   def __init__(self, driver, base_url, timeout):
      self._args = (driver, base_url, timeout)

   @property
   def order_list(self):
      return OrderListPage(*self._args)

   @property
   def checkout(self):
      return CheckoutPage(*self._args)

   @property
   def order_detail(self):
      return OrderDetailPage(*self._args)
