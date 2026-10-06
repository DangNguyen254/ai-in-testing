"""Minimal JSON API client for seeding and checking backend state (stdlib only)."""

import json
import urllib.error
import urllib.request
from urllib.parse import quote


class ApiError(RuntimeError):
   def __init__(self, status, message):
      super().__init__(f"HTTP {status}: {message}")
      self.status = status
      self.message = message


class ApiClient:
   def __init__(self, api_url, timeout=10.0):
      self.api_url = api_url.rstrip("/")
      self.timeout = timeout

   def request(self, method, path, payload=None):
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

   def reset(self):
      self.request("POST", "_reset", {})

   def seed(self, sections):
      """Apply a data entry's seed sections (settings, policy, tenants, targets)."""
      self.request("POST", "_seed", sections)

   # resources

   def items(self):
      result = self.request("GET", "items")
      return result

   def item(self, name):
      result = self.request("GET", f"items/{quote(name)}")
      return result

   def users(self):
      result = self.request("GET", "users")
      return result

   def user(self, email):
      result = self.request("GET", f"users/{quote(email)}")
      return result

   def orders(self):
      result = self.request("GET", "orders")
      return result

   def order(self, order_id):
      result = self.request("GET", f"orders/{order_id}")
      return result

   def create_order(self, lines):
      result = self.request("POST", "orders", {"lines": lines})
      return result

   def settings(self):
      result = self.request("GET", "settings")
      return result

   def policy(self):
      result = self.request("GET", "policy")
      return result
