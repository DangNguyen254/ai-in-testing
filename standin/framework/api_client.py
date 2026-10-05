"""Minimal JSON API client for seeding and checking backend state (stdlib only)."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any
from urllib.parse import quote


class ApiError(RuntimeError):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(f"HTTP {status}: {message}")
        self.status = status
        self.message = message


class ApiClient:
    def __init__(self, api_url: str, timeout: float = 10.0) -> None:
        self.api_url = api_url.rstrip("/")
        self.timeout = timeout

    def request(self, method: str, path: str, payload: Any = None) -> Any:
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        req = urllib.request.Request(
            f"{self.api_url}/{path.lstrip('/')}",
            data=data,
            method=method,
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return json.loads(resp.read() or b"null")
        except urllib.error.HTTPError as exc:
            body = json.loads(exc.read() or b"{}")
            raise ApiError(exc.code, body.get("error", "")) from exc

    # state

    def reset(self) -> None:
        self.request("POST", "_reset", {})

    def seed(self, state: dict[str, Any]) -> None:
        self.request("POST", "_seed", state)

    # resources

    def items(self) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = self.request("GET", "items")
        return result

    def item(self, name: str) -> dict[str, Any]:
        result: dict[str, Any] = self.request("GET", f"items/{quote(name)}")
        return result

    def users(self) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = self.request("GET", "users")
        return result

    def user(self, email: str) -> dict[str, Any]:
        result: dict[str, Any] = self.request("GET", f"users/{quote(email)}")
        return result

    def orders(self) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = self.request("GET", "orders")
        return result

    def order(self, order_id: int) -> dict[str, Any]:
        result: dict[str, Any] = self.request("GET", f"orders/{order_id}")
        return result

    def create_order(self, lines: list[dict[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = self.request("POST", "orders", {"lines": lines})
        return result

    def settings(self) -> dict[str, Any]:
        result: dict[str, Any] = self.request("GET", "settings")
        return result
