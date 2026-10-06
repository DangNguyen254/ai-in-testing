"""HTTP server for the fake app (stdlib only). Run: python -m app.server --port 8080

HTML pages use stable element ids that the page objects in ``framework/pages`` rely on.
The JSON API under ``/api`` lets tests seed state (by data-entry section) and check backend
results (``interactions`` in the data files replay requests against it).
"""

import argparse
import json
import os
from html import escape
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, quote, unquote, urlsplit

from app.state import CATEGORIES, ORDER_STATUSES, ROLES, Store, ValidationError

STORE = Store()
DEPLOYMENT = os.environ.get("STANDIN_DEPLOYMENT", "cloud")
TIMEZONES = ("UTC", "Europe/Berlin", "America/New_York", "Asia/Tokyo")
LANGUAGES = ("en", "de", "fr")


def page(title, body, flash="", error=""):
   nav = " | ".join(
      f'<a id="nav-{area}" href="{href}">{label}</a>'
      for area, href, label in (
         ("inventory", "/inventory/items", "Inventory"),
         ("users", "/users", "Users"),
         ("orders", "/orders", "Orders"),
         ("settings", "/settings/general", "Settings"),
      )
   )
   flash_html = f'<div id="flash">{escape(flash)}</div>' if flash else ""
   error_html = f'<div id="form-error">{escape(error)}</div>' if error else ""
   return (
      f"<!doctype html><html><head><title>{escape(title)}</title></head><body>"
      f"<nav>{nav}</nav>{flash_html}<h1>{escape(title)}</h1>{error_html}{body}</body></html>"
   )


def options(values, selected):
   return "".join(
      f'<option value="{escape(v)}"{" selected" if v == selected else ""}>{escape(v)}</option>'
      for v in values
   )


# --- HTML pages ---------------------------------------------------------------------------


def items_page(query, flash):
   rows = "".join(
      f'<tr class="item-row"><td class="item-name">'
      f'<a href="/inventory/items/{quote(i["name"])}/edit">{escape(i["name"])}</a></td>'
      f'<td class="item-quantity">{i["quantity"]}</td>'
      f'<td class="item-category">{escape(i["category"])}</td></tr>'
      for i in STORE.search_items(query)
   )
   body = (
      f'<form method="get"><input id="search-box" name="q" value="{escape(query)}">'
      '<button id="search-button">Search</button></form>'
      '<a id="new-item" href="/inventory/items/new">New item</a>'
      f'<table id="items-table">{rows}</table>'
   )
   return page("Items", body, flash)


def item_form(item, error="", values=None):
   values = values or {}
   name = values.get("name", item["name"] if item else "")
   quantity = values.get("quantity", str(item["quantity"]) if item else "1")
   category = values.get("category", item["category"] if item else "general")
   action = f"/inventory/items/{quote(item['name'])}/edit" if item else "/inventory/items/new"
   readonly = " readonly" if item else ""
   delete = (
      f'<form method="post" action="/inventory/items/{quote(item["name"])}/delete">'
      '<button id="delete-item">Delete</button></form>'
      if item
      else ""
   )
   body = (
      f'<form id="item-form" method="post" action="{action}">'
      f'<input id="item-name" name="name" value="{escape(name)}"{readonly}>'
      f'<input id="item-quantity" name="quantity" value="{escape(quantity)}">'
      f'<select id="item-category" name="category">{options(CATEGORIES, category)}</select>'
      '<button id="save-item">Save</button></form>'
      f"{delete}"
   )
   return page("Edit item" if item else "New item", body, error=error)


def users_page(flash):
   rows = "".join(
      f'<tr class="user-row"><td class="user-email"><a href="/users/{quote(u["email"])}">'
      f'{escape(u["email"])}</a></td><td class="user-role">{u["role"]}</td>'
      f'<td class="user-status">{"active" if u["active"] else "inactive"}</td></tr>'
      for u in STORE.users.values()
   )
   banner = (
      '<div id="sso-banner">Single sign-on is managed by your identity provider</div>'
      if DEPLOYMENT == "cloud"
      else ""
   )
   body = (
      f'{banner}<a id="invite-user" href="/users/invite">Invite user</a>'
      f'<table id="users-table">{rows}</table>'
   )
   return page("Users", body, flash)


def invite_page(error=""):
   body = (
      '<form method="post" action="/users/invite"><input id="invite-email" name="email">'
      f'<select id="invite-role" name="role">{options(ROLES, "viewer")}</select>'
      '<button id="send-invite">Send invite</button></form>'
   )
   return page("Invite user", body, error=error)


def profile_page(email, flash, error=""):
   user = STORE.users[email]
   target = quote(email)
   body = (
      f'<span id="user-status">{"active" if user["active"] else "inactive"}</span>'
      f'<form method="post" action="/users/{target}/role">'
      f'<select id="role-select" name="role">{options(ROLES, user["role"])}</select>'
      '<button id="save-role">Save role</button></form>'
      f'<form method="post" action="/users/{target}/deactivate">'
      '<button id="deactivate-user">Deactivate</button></form>'
   )
   return page(email, body, flash, error)


def orders_page(status, flash):
   rows = "".join(
      f'<tr class="order-row"><td class="order-id"><a href="/orders/{o["id"]}">{o["id"]}</a></td>'
      f'<td class="order-status">{o["status"]}</td></tr>'
      for o in STORE.orders_with_status(status or None)
   )
   body = (
      '<form method="get"><select id="status-filter" name="status">'
      f'<option value="">all</option>{options(ORDER_STATUSES, status)}</select>'
      '<button id="apply-filter">Filter</button></form>'
      '<a id="new-order" href="/orders/new">New order</a>'
      f'<table id="orders-table">{rows}</table>'
   )
   return page("Orders", body, flash)


def checkout_page(error=""):
   names = tuple(STORE.items)
   first = names[0] if names else ""
   body = (
      '<form method="post" action="/orders/new">'
      f'<select id="checkout-item" name="item">{options(names, first)}</select>'
      '<input id="checkout-quantity" name="quantity" value="1">'
      '<button id="place-order">Place order</button></form>'
   )
   return page("New order", body, error=error)


def order_page(order_id, flash, error=""):
   order = STORE.orders[order_id]
   notes = "".join(f'<li class="note">{escape(n)}</li>' for n in order["notes"])
   body = (
      f'<span id="order-status">{order["status"]}</span>'
      f'<form method="post" action="/orders/{order_id}/cancel">'
      '<button id="cancel-order">Cancel order</button></form>'
      f'<form method="post" action="/orders/{order_id}/notes">'
      '<textarea id="note-text" name="text"></textarea><button id="add-note">Add note</button>'
      f'</form><ul id="notes">{notes}</ul>'
   )
   return page(f"Order {order_id}", body, flash, error)


def general_settings_page(flash):
   s = STORE.settings
   body = (
      '<form method="post" action="/settings/general">'
      f'<select id="timezone" name="timezone">{options(TIMEZONES, s["timezone"])}</select>'
      f'<select id="language" name="language">{options(LANGUAGES, s["language"])}</select>'
      '<button id="save-general">Save</button></form>'
      '<a id="notifications-tab" href="/settings/notifications">Notifications</a>'
   )
   return page("General settings", body, flash)


def notification_settings_page(flash):
   n = STORE.settings["notifications"]
   checked = {key: " checked" if n[key] else "" for key in ("email", "weekly_digest")}
   body = (
      '<form method="post" action="/settings/notifications">'
      f'<input type="checkbox" id="email-toggle" name="email"{checked["email"]}>'
      f'<input type="checkbox" id="digest-toggle" name="weekly_digest"{checked["weekly_digest"]}>'
      '<button id="save-notifications">Save</button></form>'
   )
   return page("Notification settings", body, flash)


# --- Request handling ---------------------------------------------------------------------


class Handler(BaseHTTPRequestHandler):
   server_version = "StandinApp/1.0"

   def log_message(self, format, *args):  # quiet by default
      pass

   # helpers

   def _send(self, status, body, content_type):
      data = body.encode("utf-8")
      self.send_response(status)
      self.send_header("Content-Type", f"{content_type}; charset=utf-8")
      self.send_header("Content-Length", str(len(data)))
      self.end_headers()
      self.wfile.write(data)

   def _html(self, body, status=HTTPStatus.OK):
      self._send(status, body, "text/html")

   def _json(self, payload, status=HTTPStatus.OK):
      self._send(status, json.dumps(payload), "application/json")

   def _redirect(self, location, flash=""):
      if flash:
         location += ("&" if "?" in location else "?") + "flash=" + quote(flash)
      self.send_response(HTTPStatus.SEE_OTHER)
      self.send_header("Location", location)
      self.end_headers()

   def _body(self):
      return self.rfile.read(int(self.headers.get("Content-Length") or 0))

   def _form(self):
      parsed = parse_qs(self._body().decode("utf-8"), keep_blank_values=True)
      return {k: v[-1] for k, v in parsed.items()}

   def _json_body(self):
      raw = self._body()
      return json.loads(raw) if raw else {}

   def _parts(self):
      url = urlsplit(self.path)
      query = {k: v[-1] for k, v in parse_qs(url.query).items()}
      return [unquote(p) for p in url.path.strip("/").split("/") if p], query

   # dispatch

   def do_GET(self):
      parts, query = self._parts()
      flash = query.get("flash", "")
      try:
         if parts[:1] == ["api"]:
            self._api("GET", parts[1:])
         elif not parts:
            self._redirect("/inventory/items")
         elif parts == ["inventory", "items"]:
            self._html(items_page(query.get("q", ""), flash))
         elif parts == ["inventory", "items", "new"]:
            self._html(item_form(None))
         elif len(parts) == 4 and parts[:2] == ["inventory", "items"] and parts[3] == "edit":
            self._html(item_form(STORE.items[parts[2]]))
         elif parts == ["users"]:
            self._html(users_page(flash))
         elif parts == ["users", "invite"]:
            self._html(invite_page())
         elif len(parts) == 2 and parts[0] == "users":
            self._html(profile_page(parts[1], flash))
         elif parts == ["orders"]:
            self._html(orders_page(query.get("status", ""), flash))
         elif parts == ["orders", "new"]:
            self._html(checkout_page())
         elif len(parts) == 2 and parts[0] == "orders":
            self._html(order_page(int(parts[1]), flash))
         elif parts == ["settings", "general"]:
            self._html(general_settings_page(flash))
         elif parts == ["settings", "notifications"]:
            self._html(notification_settings_page(flash))
         else:
            self._html(page("Not found", ""), HTTPStatus.NOT_FOUND)
      except (KeyError, ValueError):
         self._html(page("Not found", ""), HTTPStatus.NOT_FOUND)

   def do_POST(self):
      parts, _ = self._parts()
      if parts[:1] == ["api"]:
         self._api("POST", parts[1:])
         return
      form = self._form()
      try:
         self._post_form(parts, form)
      except ValidationError as exc:
         self._form_error(parts, form, str(exc))

   def do_PATCH(self):
      parts, _ = self._parts()
      self._api("PATCH", parts[1:]) if parts[:1] == ["api"] else self._json({}, 404)

   def do_PUT(self):
      parts, _ = self._parts()
      self._api("PUT", parts[1:]) if parts[:1] == ["api"] else self._json({}, 404)

   def do_DELETE(self):
      parts, _ = self._parts()
      self._api("DELETE", parts[1:]) if parts[:1] == ["api"] else self._json({}, 404)

   def _post_form(self, parts, form):
      if parts == ["inventory", "items", "new"]:
         quantity = _int(form.get("quantity", ""))
         STORE.create_item(form.get("name", ""), quantity, form.get("category", "general"))
         self._redirect("/inventory/items", "Item created")
      elif len(parts) == 4 and parts[:2] == ["inventory", "items"] and parts[3] == "edit":
         quantity = _int(form.get("quantity", ""))
         STORE.update_item(parts[2], quantity=quantity, category=form.get("category", ""))
         self._redirect("/inventory/items", "Item saved")
      elif len(parts) == 4 and parts[:2] == ["inventory", "items"] and parts[3] == "delete":
         STORE.delete_item(parts[2])
         self._redirect("/inventory/items", "Item deleted")
      elif parts == ["users", "invite"]:
         STORE.invite_user(form.get("email", ""), form.get("role", "viewer"))
         self._redirect("/users", "Invitation sent")
      elif len(parts) == 3 and parts[0] == "users" and parts[2] == "role":
         STORE.change_role(parts[1], form.get("role", ""))
         self._redirect(f"/users/{quote(parts[1])}", "Role updated")
      elif len(parts) == 3 and parts[0] == "users" and parts[2] == "deactivate":
         STORE.deactivate_user(parts[1])
         self._redirect(f"/users/{quote(parts[1])}", "User deactivated")
      elif parts == ["orders", "new"]:
         order = STORE.create_order(
            [{"item": form.get("item", ""), "quantity": _int(form.get("quantity", ""))}]
         )
         self._redirect(f"/orders/{order['id']}", "Order placed")
      elif len(parts) == 3 and parts[0] == "orders" and parts[2] == "cancel":
         STORE.cancel_order(int(parts[1]))
         self._redirect(f"/orders/{parts[1]}", "Order cancelled")
      elif len(parts) == 3 and parts[0] == "orders" and parts[2] == "notes":
         STORE.add_note(int(parts[1]), form.get("text", ""))
         self._redirect(f"/orders/{parts[1]}", "Note added")
      elif parts == ["settings", "general"]:
         STORE.update_settings({k: form[k] for k in ("timezone", "language") if k in form})
         self._redirect("/settings/general", "Settings saved")
      elif parts == ["settings", "notifications"]:
         notifications = {k: k in form for k in ("email", "weekly_digest")}
         STORE.update_settings({"notifications": notifications})
         self._redirect("/settings/notifications", "Settings saved")
      else:
         self._html(page("Not found", ""), HTTPStatus.NOT_FOUND)

   def _form_error(self, parts, form, error):
      status = HTTPStatus.UNPROCESSABLE_ENTITY
      if parts == ["inventory", "items", "new"]:
         self._html(item_form(None, error, form), status)
      elif parts[:2] == ["inventory", "items"] and len(parts) == 4:
         self._html(item_form(STORE.items.get(parts[2]), error, form), status)
      elif parts == ["users", "invite"]:
         self._html(invite_page(error), status)
      elif parts[:1] == ["users"] and len(parts) == 3:
         self._html(profile_page(parts[1], "", error), status)
      elif parts == ["orders", "new"]:
         self._html(checkout_page(error), status)
      elif parts[:1] == ["orders"] and len(parts) == 3:
         self._html(order_page(int(parts[1]), "", error), status)
      else:
         self._html(page("Error", "", error=error), status)

   # JSON API

   def _api(self, method, parts):
      try:
         payload = self._json_body() if method in ("POST", "PATCH", "PUT") else {}
         result = route_api(method, parts, payload)
      except ValidationError as exc:
         self._json({"error": str(exc)}, HTTPStatus.UNPROCESSABLE_ENTITY)
      except (KeyError, LookupError, ValueError):
         self._json({"error": "not found"}, HTTPStatus.NOT_FOUND)
      else:
         self._json(result)


def route_api(method, parts, payload):
   """JSON API routing, separate from the handler so it can be tested without a server."""
   match method, parts:
      case "POST", ["_reset"]:
         STORE.reset()
         return {"ok": True}
      case "POST", ["_seed"]:
         STORE.seed(payload)  # the data entry's seed sections
         return {"ok": True}
      case "GET", ["items"]:
         return list(STORE.items.values())
      case "POST", ["items"]:
         return STORE.create_item(
            payload["name"], int(payload.get("quantity", 1)), payload.get("category", "general")
         )
      case "GET", ["items", name]:
         return STORE.items[name]
      case "PATCH", ["items", name]:
         return STORE.update_item(name, **payload)
      case "DELETE", ["items", name]:
         STORE.delete_item(name)
         return {"ok": True}
      case "GET", ["users"]:
         return list(STORE.users.values())
      case "POST", ["users"]:
         return STORE.invite_user(payload["email"], payload.get("role", "viewer"))
      case "GET", ["users", email]:
         return STORE.users[email.lower()]
      case "PATCH", ["users", email]:
         if payload.get("active") is False:
            STORE.deactivate_user(email)
         if "role" in payload:
            STORE.change_role(email, payload["role"])
         return STORE.users[email.lower()]
      case "GET", ["orders"]:
         return list(STORE.orders.values())
      case "POST", ["orders"]:
         return STORE.create_order(payload["lines"])
      case "GET", ["orders", order_id]:
         return STORE.orders[int(order_id)]
      case "POST", ["orders", order_id, "cancel"]:
         return STORE.cancel_order(int(order_id))
      case "GET", ["settings"]:
         return STORE.settings
      case "PUT", ["settings"]:
         return STORE.update_settings(payload)
      case "GET", ["policy"]:
         return STORE.policy
      case "PUT", ["policy"]:
         return STORE.set_policy(payload)
   raise LookupError(f"{method} /api/{'/'.join(parts)}")


def _int(value):
   try:
      return int(value)
   except ValueError:
      raise ValidationError("Quantity must be a whole number") from None


def main():
   parser = argparse.ArgumentParser(description="Run the stand-in fake web app.")
   parser.add_argument("--host", default="127.0.0.1")
   parser.add_argument("--port", type=int, default=8080)
   args = parser.parse_args()
   server = ThreadingHTTPServer((args.host, args.port), Handler)
   print(f"Stand-in app on http://{args.host}:{args.port}")
   server.serve_forever()


if __name__ == "__main__":
   main()
