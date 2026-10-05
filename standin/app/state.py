"""In-memory backend state. Pure functions on a Store, so it is testable without a server."""

from __future__ import annotations

import copy
import itertools
from dataclasses import dataclass, field
from typing import Any

CATEGORIES = ("general", "hardware", "software", "office")
ROLES = ("viewer", "editor", "admin")
ORDER_STATUSES = ("open", "shipped", "cancelled")
DEFAULT_SETTINGS: dict[str, Any] = {
    "timezone": "UTC",
    "language": "en",
    "notifications": {"email": True, "weekly_digest": False},
}


class ValidationError(ValueError):
    """Invalid input; the message is shown to the user."""


@dataclass
class Store:
    items: dict[str, dict[str, Any]] = field(default_factory=dict)
    users: dict[str, dict[str, Any]] = field(default_factory=dict)
    orders: dict[int, dict[str, Any]] = field(default_factory=dict)
    settings: dict[str, Any] = field(default_factory=lambda: copy.deepcopy(DEFAULT_SETTINGS))
    _order_ids: itertools.count[int] = field(default_factory=lambda: itertools.count(1))

    # --- seed / reset (used by tests through the API) -------------------------------------

    def reset(self) -> None:
        self.items.clear()
        self.users.clear()
        self.orders.clear()
        self.settings = copy.deepcopy(DEFAULT_SETTINGS)
        self._order_ids = itertools.count(1)

    def seed(self, state: dict[str, Any]) -> None:
        for item in state.get("items", []):
            self.create_item(item["name"], item.get("quantity", 1), item.get("category", "general"))
        for user in state.get("users", []):
            self.invite_user(user["email"], user.get("role", "viewer"))
            if not user.get("active", True):
                self.deactivate_user(user["email"])
        for order in state.get("orders", []):
            created = self.create_order(order["lines"])
            if order.get("status", "open") != "open":
                created["status"] = order["status"]
        if "settings" in state:
            self.update_settings(state["settings"])

    # --- items ------------------------------------------------------------------------------

    def create_item(self, name: str, quantity: int, category: str = "general") -> dict[str, Any]:
        name = name.strip()
        if not name:
            raise ValidationError("Name is required")
        if name in self.items:
            raise ValidationError(f"Item '{name}' already exists")
        if quantity < 1:
            raise ValidationError("Quantity must be at least 1")
        if category not in CATEGORIES:
            raise ValidationError(f"Unknown category '{category}'")
        item = {"name": name, "quantity": quantity, "category": category, "status": "active"}
        self.items[name] = item
        return item

    def update_item(self, name: str, **changes: Any) -> dict[str, Any]:
        item = self._item(name)
        if "category" in changes and changes["category"] not in CATEGORIES:
            raise ValidationError(f"Unknown category '{changes['category']}'")
        if "quantity" in changes and changes["quantity"] < 1:
            raise ValidationError("Quantity must be at least 1")
        item.update({k: v for k, v in changes.items() if k in ("quantity", "category")})
        return item

    def delete_item(self, name: str) -> None:
        self._item(name)
        del self.items[name]

    def search_items(self, text: str) -> list[dict[str, Any]]:
        needle = text.strip().lower()
        return [i for i in self.items.values() if needle in i["name"].lower()]

    def _item(self, name: str) -> dict[str, Any]:
        if name not in self.items:
            raise ValidationError(f"Unknown item '{name}'")
        return self.items[name]

    # --- users ------------------------------------------------------------------------------

    def invite_user(self, email: str, role: str) -> dict[str, Any]:
        email = email.strip().lower()
        if "@" not in email:
            raise ValidationError("Enter a valid email address")
        if email in self.users:
            raise ValidationError(f"{email} has already been invited")
        if role not in ROLES:
            raise ValidationError(f"Unknown role '{role}'")
        user = {"email": email, "role": role, "active": True}
        self.users[email] = user
        return user

    def change_role(self, email: str, role: str) -> dict[str, Any]:
        if role not in ROLES:
            raise ValidationError(f"Unknown role '{role}'")
        user = self._user(email)
        user["role"] = role
        return user

    def deactivate_user(self, email: str) -> dict[str, Any]:
        user = self._user(email)
        user["active"] = False
        return user

    def _user(self, email: str) -> dict[str, Any]:
        key = email.strip().lower()
        if key not in self.users:
            raise ValidationError(f"Unknown user '{email}'")
        return self.users[key]

    # --- orders -----------------------------------------------------------------------------

    def create_order(self, lines: list[dict[str, Any]]) -> dict[str, Any]:
        if not lines:
            raise ValidationError("An order needs at least one line")
        for line in lines:
            item = self.items.get(line["item"])
            if item is None:
                raise ValidationError(f"Unknown item '{line['item']}'")
            if line["quantity"] > item["quantity"]:
                raise ValidationError(f"Not enough stock for '{line['item']}'")
        for line in lines:
            self.items[line["item"]]["quantity"] -= line["quantity"]
        order_id = next(self._order_ids)
        order = {"id": order_id, "lines": lines, "status": "open", "notes": []}
        self.orders[order_id] = order
        return order

    def cancel_order(self, order_id: int) -> dict[str, Any]:
        order = self._order(order_id)
        if order["status"] == "shipped":
            raise ValidationError("Shipped orders can't be cancelled")
        if order["status"] == "open":
            for line in order["lines"]:
                if line["item"] in self.items:
                    self.items[line["item"]]["quantity"] += line["quantity"]
        order["status"] = "cancelled"
        return order

    def add_note(self, order_id: int, text: str) -> dict[str, Any]:
        if not text.strip():
            raise ValidationError("Note can't be empty")
        order = self._order(order_id)
        order["notes"].append(text.strip())
        return order

    def orders_with_status(self, status: str | None) -> list[dict[str, Any]]:
        return [o for o in self.orders.values() if status in (None, "", o["status"])]

    def _order(self, order_id: int) -> dict[str, Any]:
        if order_id not in self.orders:
            raise ValidationError(f"Unknown order {order_id}")
        return self.orders[order_id]

    # --- settings ---------------------------------------------------------------------------

    def update_settings(self, changes: dict[str, Any]) -> dict[str, Any]:
        for key in ("timezone", "language"):
            if key in changes:
                self.settings[key] = changes[key]
        notifications = changes.get("notifications", {})
        if "email" in notifications:
            self.settings["notifications"]["email"] = bool(notifications["email"])
        # Known bug STND-105: the weekly digest choice is accepted but never saved.
        return self.settings
