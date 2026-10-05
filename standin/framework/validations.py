"""Reusable backend checks, mixed into BaseTest."""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

from framework.api_client import ApiClient


def wait_until(
    predicate: Callable[[], bool], timeout: float = 10.0, interval: float = 0.25
) -> None:
    """Explicit wait for backend state (the UI may update before the backend, or after)."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(interval)
    raise AssertionError(f"Condition not met within {timeout:.0f}s")


def assert_subset(actual: dict[str, Any], expected: dict[str, Any], where: str = "") -> None:
    """Every key in ``expected`` must equal the same key in ``actual`` (nested dicts too)."""
    for key, value in expected.items():
        path = f"{where}.{key}" if where else key
        assert key in actual, f"missing '{path}' in {actual}"
        if isinstance(value, dict) and isinstance(actual[key], dict):
            assert_subset(actual[key], value, path)
        else:
            assert actual[key] == value, f"'{path}': expected {value!r}, got {actual[key]!r}"


class ValidationMixin:
    api: ApiClient

    def assert_item(self, name: str, expected: dict[str, Any]) -> None:
        assert_subset(self.api.item(name), expected, f"item[{name}]")

    def assert_no_item(self, name: str) -> None:
        assert name not in {i["name"] for i in self.api.items()}, f"item {name} still exists"

    def assert_user(self, email: str, expected: dict[str, Any]) -> None:
        assert_subset(self.api.user(email), expected, f"user[{email}]")

    def assert_order_status(self, order_id: int, status: str) -> None:
        wait_until(lambda: self.api.order(order_id)["status"] == status)

    def assert_settings(self, expected: dict[str, Any]) -> None:
        assert_subset(self.api.settings(), expected, "settings")

    def assert_backend(self, expected: dict[str, Any]) -> None:
        """Check an entry's ``expected.backend`` block against the API."""
        for item in expected.get("items", []):
            self.assert_item(item["name"], item)
        for user in expected.get("users", []):
            self.assert_user(user["email"], user)
        if "settings" in expected:
            self.assert_settings(expected["settings"])
