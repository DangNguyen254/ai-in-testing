"""In-memory backend state. Pure functions on a Store, so it is testable without a server."""

import copy
import itertools

CATEGORIES = ("general", "hardware", "software", "office")
ROLES = ("viewer", "editor", "admin")
ORDER_STATUSES = ("open", "shipped", "cancelled")
DEFAULT_SETTINGS = {
   "timezone": "UTC",
   "language": "en",
   "notifications": {"email": True, "weekly_digest": False},
}
DEFAULT_POLICY = {
   "name": "default",
   "max_order_quantity": 100,
   "allowed_categories": list(CATEGORIES),
   "rules": [],
}


class ValidationError(ValueError):
   """Invalid input; the message is shown to the user."""


class Store:
   def __init__(self):
      self.items = {}
      self.users = {}
      self.orders = {}
      self.reset()

   # --- seed / reset (the test framework's setup applies data-entry sections) ----------

   def reset(self):
      self.items.clear()
      self.users.clear()
      self.orders.clear()
      self.settings = copy.deepcopy(DEFAULT_SETTINGS)
      self.policy = copy.deepcopy(DEFAULT_POLICY)
      self._order_ids = itertools.count(1)

   def seed(self, sections):
      """Apply the seed sections of a data entry: settings, policy, tenants, targets."""
      if "settings" in sections:
         self.update_settings(sections["settings"])
      if "policy" in sections:
         self.set_policy(sections["policy"])
      for user in sections.get("tenants", {}).get("users", []):
         self.invite_user(user["email"], user.get("role", "viewer"))
         if not user.get("active", True):
            self.deactivate_user(user["email"])
      targets = sections.get("targets", {})
      for item in targets.get("items", []):
         self.create_item(item["name"], item.get("quantity", 1), item.get("category", "general"))
      for order in targets.get("orders", []):
         created = self.create_order(order["lines"])
         if order.get("status", "open") != "open":
            created["status"] = order["status"]

   # --- policy -----------------------------------------------------------------------------

   def set_policy(self, policy):
      merged = copy.deepcopy(DEFAULT_POLICY)
      merged.update(copy.deepcopy(policy))
      unknown = [c for c in merged["allowed_categories"] if c not in CATEGORIES]
      if unknown:
         raise ValidationError(f"Unknown categories in policy: {unknown}")
      self.policy = merged
      return self.policy

   # --- items ------------------------------------------------------------------------------

   def create_item(self, name, quantity, category="general"):
      name = name.strip()
      if not name:
         raise ValidationError("Name is required")
      if name in self.items:
         raise ValidationError(f"Item '{name}' already exists")
      if quantity < 1:
         raise ValidationError("Quantity must be at least 1")
      if category not in CATEGORIES:
         raise ValidationError(f"Unknown category '{category}'")
      if category not in self.policy["allowed_categories"]:
         raise ValidationError(f"Category '{category}' is not allowed by policy")
      item = {"name": name, "quantity": quantity, "category": category, "status": "active"}
      self.items[name] = item
      return item

   def update_item(self, name, **changes):
      item = self._item(name)
      if "category" in changes and changes["category"] not in CATEGORIES:
         raise ValidationError(f"Unknown category '{changes['category']}'")
      if "quantity" in changes and changes["quantity"] < 1:
         raise ValidationError("Quantity must be at least 1")
      item.update({k: v for k, v in changes.items() if k in ("quantity", "category")})
      return item

   def delete_item(self, name):
      self._item(name)
      del self.items[name]

   def search_items(self, text):
      needle = text.strip().lower()
      return [i for i in self.items.values() if needle in i["name"].lower()]

   def _item(self, name):
      if name not in self.items:
         raise ValidationError(f"Unknown item '{name}'")
      return self.items[name]

   # --- users ------------------------------------------------------------------------------

   def invite_user(self, email, role):
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

   def change_role(self, email, role):
      if role not in ROLES:
         raise ValidationError(f"Unknown role '{role}'")
      user = self._user(email)
      user["role"] = role
      return user

   def deactivate_user(self, email):
      user = self._user(email)
      user["active"] = False
      return user

   def _user(self, email):
      key = email.strip().lower()
      if key not in self.users:
         raise ValidationError(f"Unknown user '{email}'")
      return self.users[key]

   # --- orders -----------------------------------------------------------------------------

   def create_order(self, lines):
      if not lines:
         raise ValidationError("An order needs at least one line")
      for line in lines:
         item = self.items.get(line["item"])
         if item is None:
            raise ValidationError(f"Unknown item '{line['item']}'")
         if line["quantity"] > self.policy["max_order_quantity"]:
            raise ValidationError(
               f"Policy allows at most {self.policy['max_order_quantity']} per order"
            )
         if line["quantity"] > item["quantity"]:
            raise ValidationError(f"Not enough stock for '{line['item']}'")
      for line in lines:
         self.items[line["item"]]["quantity"] -= line["quantity"]
      order_id = next(self._order_ids)
      order = {"id": order_id, "lines": lines, "status": "open", "notes": []}
      self.orders[order_id] = order
      return order

   def cancel_order(self, order_id):
      order = self._order(order_id)
      if order["status"] == "shipped":
         raise ValidationError("Shipped orders can't be cancelled")
      if order["status"] == "open":
         for line in order["lines"]:
            if line["item"] in self.items:
               self.items[line["item"]]["quantity"] += line["quantity"]
      order["status"] = "cancelled"
      return order

   def add_note(self, order_id, text):
      if not text.strip():
         raise ValidationError("Note can't be empty")
      order = self._order(order_id)
      order["notes"].append(text.strip())
      return order

   def orders_with_status(self, status):
      return [o for o in self.orders.values() if status in (None, "", o["status"])]

   def _order(self, order_id):
      if order_id not in self.orders:
         raise ValidationError(f"Unknown order {order_id}")
      return self.orders[order_id]

   # --- settings ---------------------------------------------------------------------------

   def update_settings(self, changes):
      for key in ("timezone", "language"):
         if key in changes:
            self.settings[key] = changes[key]
      notifications = changes.get("notifications", {})
      if "email" in notifications:
         self.settings["notifications"]["email"] = bool(notifications["email"])
      # Known bug STND-105: the weekly digest choice is accepted but never saved.
      return self.settings
