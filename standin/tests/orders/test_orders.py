"""Orders: placing, cancelling, filtering, notes, and API-created orders.

This class takes its data entry as a ``params`` argument instead of ``self.params``.
"""

import pytest

from framework.base_test import BaseTest
from framework.decorators import browsers, environments, skip_browser


@browsers("chrome", "firefox")
@environments("cloud", "on_prem")
@pytest.mark.project("example-project")
@pytest.mark.component("orders")
class TestOrders(BaseTest):
   @pytest.mark.priority("p0")
   @pytest.mark.suite("smoke")
   def test_orders_checkout_place(self, params):
      checkout = self.nav.orders.checkout
      checkout.open()
      checkout.item = params["item_name"]
      checkout.quantity = 3
      checkout.place_order()

      detail = self.nav.orders.order_detail
      self.check.equal(detail.flash_message, "Order placed", "flash message")
      self.check.equal(detail.status, "open", "order status")
      self.validate_backend(params)

   @pytest.mark.priority("p1")
   @pytest.mark.suite("regression")
   def test_orders_checkout_policy_limit(self, params):
      checkout = self.nav.orders.checkout
      checkout.open()
      checkout.item = params["item_name"]
      checkout.quantity = params["quantity"]
      checkout.place_order()

      self.check.equal(checkout.error_message, params["error"], "form error")
      self.validate_backend(params)

   @pytest.mark.priority("p1")
   @pytest.mark.suite("regression")
   def test_orders_detail_cancel(self, params):
      """1. Open a seeded open order. 2. Cancel it. 3. Stock is returned."""
      detail = self.nav.orders.order_detail
      detail.open_for(1)
      detail.cancel()

      self.check.equal(detail.status, "cancelled", "order status")
      self.validate_backend(params)

   @pytest.mark.priority("p2")
   @pytest.mark.suite("regression")
   @pytest.mark.parametrize("status", ["open", "shipped", "cancelled"])
   def test_orders_list_filter_status(self, params, status):
      orders = self.nav.orders.order_list
      orders.open()
      orders.status_filter = status
      orders.apply_filter()

      self.check.equal(orders.statuses, [status] * params["count"], "listed statuses")

   @pytest.mark.priority("p3")
   @pytest.mark.suite("regression")
   @skip_browser("firefox", reason="textarea input events are unreliable in the driver")
   def test_orders_detail_add_note(self, params):
      detail = self.nav.orders.order_detail
      detail.open_for(1)
      detail.note_text = "Customer asked for gift wrap"
      detail.add_note()

      self.check.equal(detail.notes, ["Customer asked for gift wrap"], "order notes")

   @pytest.mark.priority("p1")
   @pytest.mark.suite("regression")
   def test_orders_api_create_cancel_in_ui(self, params):
      order = self.api.create_order([{"item": params["item_name"], "quantity": 1}])

      detail = self.nav.orders.order_detail
      detail.open_for(order["id"])
      self.check.equal(detail.status, "open", "order status")
      detail.cancel()
      self.validate_backend(params)

   @pytest.mark.priority("p2")
   @pytest.mark.suite("regression")
   def test_orders_api_create_unknown_item(self, params):
      self.validate_backend(params)
