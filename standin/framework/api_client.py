"""Minimal JSON API client (stdlib only). Returns the status with the body; never raises on
an HTTP error status, so validators can compare expected error statuses."""

import json
import urllib.error
import urllib.request


class ApiClient:
   def __init__(self, api_url, user=None, timeout=10.0):
      self.api_url = api_url.rstrip("/")
      self.user = user
      self.timeout = timeout

   def request(self, method, path, payload=None, user=None):
      """``path`` is relative to ``/api`` or starts with it. Returns ``(status, body)``."""
      relative = path.removeprefix("/api").lstrip("/")
      data = json.dumps(payload).encode("utf-8") if payload is not None else None
      headers = {"Content-Type": "application/json"}
      if user or self.user:
         headers["X-User"] = user or self.user
      req = urllib.request.Request(
         f"{self.api_url}/{relative}", data=data, method=method, headers=headers
      )
      try:
         with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            return resp.status, json.loads(resp.read() or b"null")
      except urllib.error.HTTPError as exc:
         return exc.code, json.loads(exc.read() or b"{}")

   # test setup

   def reset(self):
      self.request("POST", "_reset", {})

   def seed(self, blocks):
      """Apply per-tenant seed blocks (settings, policy)."""
      self.request("POST", "_seed", {"tenants": blocks})

   def revision(self, tenant):
      _, body = self.request("GET", f"policy/v1/revision/{tenant}")
      return body["rev_id"]
