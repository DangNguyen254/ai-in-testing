"""Orders: placing, cancelling, filtering, notes, and API-created orders."""

from __future__ import annotations

import pytest

from framework.api_client import ApiError
from framework.base_test import BaseTest
from framework.decorators import skip_browser


@pytest.mark.project("example-project")
@pytest.mark.component("orders")
class TestOrders(BaseTest):
    @pytest.mark.priority("p0")
    @pytest.mark.suite("smoke")
    def test_place_order(self) -> None:
        self.nav.orders.checkout.open().place_order(self.inputs["item"], self.inputs["quantity"])

        detail = self.nav.orders.order_detail
        assert detail.flash_message == "Order placed"
        assert detail.status == "open"
        self.assert_order_status(detail.order_id, "open")
        self.assert_backend(self.expected["backend"])

    @pytest.mark.priority("p1")
    @pytest.mark.suite("regression")
    def test_cancel_order(self) -> None:
        detail = self.nav.orders.order_detail.open_for(self.inputs["order_id"])
        detail.cancel()

        assert detail.status == "cancelled"
        self.assert_order_status(self.inputs["order_id"], "cancelled")
        self.assert_backend(self.expected["backend"])

    @pytest.mark.priority("p2")
    @pytest.mark.suite("regression")
    @pytest.mark.parametrize("status", ["open", "shipped", "cancelled"])
    def test_filter_orders_by_status(self, status: str) -> None:
        orders = self.nav.orders.order_list.open().filter_by(status)

        assert orders.statuses() == [status] * self.expected["count"]

    @pytest.mark.priority("p3")
    @pytest.mark.suite("regression")
    @skip_browser("firefox", reason="textarea input events are unreliable in the driver")
    def test_add_order_note(self) -> None:
        detail = self.nav.orders.order_detail.open_for(self.inputs["order_id"])
        detail.add_note(self.inputs["note"])

        assert detail.notes() == self.expected["notes"]

    @pytest.mark.priority("p1")
    @pytest.mark.suite("regression")
    def test_order_created_via_api_shows_in_ui(self) -> None:
        order = self.api.create_order(self.inputs["lines"])

        detail = self.nav.orders.order_detail.open_for(order["id"])
        assert detail.status == "open"
        detail.cancel()
        self.assert_order_status(order["id"], "cancelled")
        self.assert_backend(self.expected["backend"])

    @pytest.mark.priority("p2")
    @pytest.mark.suite("regression")
    def test_orders_api_rejects_unknown_item(self) -> None:
        with pytest.raises(ApiError) as error:
            self.api.create_order(self.inputs["lines"])

        assert error.value.status == self.expected["status"]
        assert error.value.message == self.expected["error"]
        assert self.api.orders() == []
