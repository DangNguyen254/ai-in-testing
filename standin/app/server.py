"""HTTP server for the fake policy app (stdlib only). Run: python -m app.server --port 8080

HTML pages use stable element ids that the page objects in ``framework/pages`` rely on. Every
page has the shared top bar (save / publish / reset). The session cookie holds the tenant and
user, set by ``/login?tenant=...&user=...``.

JSON API under ``/api`` (tests seed state and check backend results through it):
- ``GET /api/policy/v1/{policy,rules,profiles}/<tenant>/<rev_id>``: a published revision
- ``GET /api/policy/v1/revision/<tenant>``: the latest revision number
- ``PUT /api/policy/v1/rules/<tenant>``: replace the rules and publish (admin role only)
- ``GET /api/settings/v1/settings/<tenant>``; ``PUT /api/settings/v1/agent/<tenant>`` (admin)
- ``GET /api/settings/v1/capabilities/<tenant>``; ``PUT`` the same path (admin): each
  tenant's capabilities, incl. ``browser_limit`` (agent browser sessions open at once)
- ``GET /api/agent/v1/sessions/<tenant>``: the open agent browser sessions
- ``GET /api/files/v1/policy/<tenant>/<rev_id>``: the file policy of a published revision
- ``POST /api/downloads/v1/download/<tenant>`` ``{file, mode, password}``: a download verdict
- ``GET /api/downloads/v1/log/<tenant>``: the download log
- ``POST /api/agent/v1/tasks/<tenant>`` ``{goal, start_page}``; ``GET .../tasks/<tenant>[/<id>]``
- ``POST /api/_reset``, ``POST /api/_seed`` (test setup only; ``{"tenants": [...], "site": {...}}``)

File-policy and agent pages live in ``app/pages_v4.py``; the fake external site's pages are
served under ``/site``.

Agent browser sessions are WebSocket connections: ``GET /ws/browser/<tenant>`` with
``Upgrade: websocket``. At the tenant's ``browser_limit`` the attempt gets HTTP 429 with the
body ``Browser limit reached`` before any upgrade; otherwise 101, and the session stays open
until the client closes it (close frame or disconnect), which frees its slot.
"""

import argparse
import base64
import hashlib
import json
import threading
from html import escape
from http import HTTPStatus
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, quote, unquote, urlsplit

from app import agent, files, pages_v4
from app.state import (
   ACTIONS,
   LEVELS,
   NUMERIC_CAPABILITIES,
   PAGE_SIZE,
   LimitReached,
   PermissionDenied,
   Store,
   ValidationError,
)

STORE = Store()
WIZARDS = {}  # (tenant, user) -> rule fields from step 1 of the add wizard
SESSIONS_LOCK = threading.Lock()  # connection attempts may arrive at the same time
_WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"  # RFC 6455 handshake constant


def options(values, selected):
   return "".join(
      f'<option value="{escape(v)}"{" selected" if v == selected else ""}>{escape(v)}</option>'
      for v in values
   )


def page(tenant_id, title, body, here, toast="", error=""):
   tenant = STORE.tenant(tenant_id)
   caps = tenant.settings["capabilities"]
   links = [("rules", "/rules", "Rules")]
   if caps["profiles"]:
      links.append(("profiles", "/profiles", "Profiles"))
   links.append(("settings", "/settings/capabilities", "Settings"))
   links.append(("files", "/files", "Files"))
   links.append(("agent", "/agent", "Agent"))
   nav = " | ".join(f'<a id="nav-{key}" href="{href}">{label}</a>' for key, href, label in links)
   blocked = STORE.save_blocked(tenant_id)
   status = (
      "Unsaved changes" if tenant.has_unsaved_changes else f"Published revision {tenant.rev_id}"
   )
   hidden = f'<input type="hidden" name="next" value="{escape(here)}">'
   top_bar = (
      f'<div id="top-bar"><span id="topbar-status">{status}</span>'
      f'<form method="post" action="/topbar/save">{hidden}'
      f'<button id="topbar-save"{" disabled" if blocked else ""}>Save</button></form>'
      f'<form method="post" action="/topbar/publish">{hidden}'
      '<button id="topbar-publish">Publish</button></form>'
      f'<form method="post" action="/topbar/reset">{hidden}'
      '<button id="topbar-reset">Reset</button></form>'
      '<a id="logout" href="/logout">Log out</a></div>'
   )
   toast_html = f'<div id="toast">{escape(toast)}</div>' if toast else ""
   error_html = f'<div id="form-error">{escape(error)}</div>' if error else ""
   return (
      f"<!doctype html><html><head><title>{escape(title)}</title></head><body>"
      f'{top_bar}<nav>{nav}</nav><span id="tenant-name">{escape(tenant_id)}</span>'
      f"{toast_html}<h1>{escape(title)}</h1>{error_html}{body}</body></html>"
   )


# --- HTML pages -----------------------------------------------------------------------------


def rules_page(tenant_id, query, toast):
   text, action = query.get("q", ""), query.get("action", "")
   page_number = int(query.get("page", "1") or 1)
   rules, total = STORE.list_rules(tenant_id, text, action, page_number)
   rows = "".join(
      f'<tr class="rule-row"><td><input type="checkbox" class="rule-select" form="delete-form" '
      f'name="selected" value="{escape(r["name"])}"></td>'
      f'<td class="rule-name"><a href="/rules/{quote(r["name"])}/edit">{escape(r["name"])}</a></td>'
      f'<td class="rule-action">{r["action"]}</td>'
      f'<td class="rule-enabled">{"on" if r["enabled"] else "off"}</td></tr>'
      for r in rules
   )
   pages = max(1, -(-total // PAGE_SIZE))
   keep = f"q={quote(text)}&action={quote(action)}"
   pager = (
      f'<span id="page-number">{page_number}</span>/<span id="page-count">{pages}</span>'
      f'<span id="page-size">{PAGE_SIZE}</span>'
   )
   if page_number < pages:
      pager += f'<a id="next-page" href="/rules?{keep}&page={page_number + 1}">Next</a>'
   if page_number > 1:
      pager += f'<a id="previous-page" href="/rules?{keep}&page={page_number - 1}">Previous</a>'
   body = (
      f'<form method="get"><input id="search-box" name="q" value="{escape(text)}">'
      '<select id="action-filter" name="action"><option value="">any</option>'
      f"{options(ACTIONS, action)}</select>"
      '<button id="search-button">Search</button></form>'
      '<a id="add-rule" href="/rules/new">Add rule</a> '
      '<a id="import-rules" href="/rules/import">Import</a>'
      '<form id="delete-form" method="post" action="/rules/delete">'
      '<button id="delete-selected">Delete selected</button></form>'
      f'<span id="rule-total">{total}</span>'
      f'<table id="rules-table">{rows}</table>{pager}'
   )
   return page(tenant_id, "Rules", body, "/rules", toast)


def wizard_step1(tenant_id, values=None, error=""):
   values = values or {}
   body = (
      '<form method="post" action="/rules/new/step1">'
      f'<input id="rule-name" name="name" value="{escape(values.get("name", ""))}">'
      f'<select id="rule-action" name="action">{options(ACTIONS, values.get("action", "allow"))}'
      "</select>"
      f'<input id="rule-description" name="description" '
      f'value="{escape(values.get("description", ""))}">'
      '<button id="wizard-next">Next</button></form>'
   )
   return page(tenant_id, "Add rule: details", body, "/rules/new", error=error)


def wizard_step2(tenant_id, error=""):
   body = (
      '<form method="post" action="/rules/new/save">'
      '<input id="condition-field" name="field"><input id="condition-value" name="value">'
      '<button id="rule-save">Save rule</button></form>'
   )
   return page(tenant_id, "Add rule: conditions", body, "/rules/new", error=error)


def rule_editor(tenant_id, name, error=""):
   rule = next(r for r in STORE.tenant(tenant_id).view()["rules"] if r["name"] == name)
   checked = " checked" if rule["enabled"] else ""
   body = (
      f'<form method="post" action="/rules/{quote(name)}/edit">'
      f'<span id="rule-name">{escape(name)}</span>'
      f'<select id="rule-action" name="action">{options(ACTIONS, rule["action"])}</select>'
      f'<input type="checkbox" id="rule-enabled" name="enabled"{checked}>'
      f'<input id="rule-description" name="description" value="{escape(rule["description"])}">'
      '<button id="rule-save">Save rule</button></form>'
   )
   return page(tenant_id, f"Rule {name}", body, f"/rules/{quote(name)}/edit", error=error)


def delete_confirm(tenant_id, names):
   items = "".join(f'<li class="pending-delete">{escape(n)}</li>' for n in names)
   hidden = "".join(f'<input type="hidden" name="selected" value="{escape(n)}">' for n in names)
   body = (
      f'<ul id="pending-deletes">{items}</ul><form method="post" action="/rules/delete/confirm">'
      f'{hidden}<button id="confirm-delete">Delete</button></form>'
      '<a id="cancel-delete" href="/rules">Cancel</a>'
   )
   return page(tenant_id, "Delete rules", body, "/rules")


def import_page(tenant_id, error=""):
   body = (
      '<form method="post" action="/rules/import">'
      '<textarea id="import-content" name="content"></textarea>'
      '<button id="import-button">Import</button></form>'
   )
   return page(tenant_id, "Import rules", body, "/rules/import", error=error)


def profiles_page(tenant_id, query, toast):
   text = query.get("q", "")
   rows = "".join(
      f'<tr class="profile-row"><td class="profile-name">'
      f'<a href="/profiles/{quote(p["name"])}/edit">{escape(p["name"])}</a></td>'
      f'<td class="profile-level">{p["level"]}</td>'
      f'<td><form method="post" action="/profiles/{quote(p["name"])}/delete">'
      f'<button class="profile-delete" value="{escape(p["name"])}">Delete</button></form></td></tr>'
      for p in STORE.search_profiles(tenant_id, text)
   )
   body = (
      f'<form method="get"><input id="profile-search" name="q" value="{escape(text)}">'
      '<button id="profile-search-button">Search</button></form>'
      '<a id="add-profile" href="/profiles/new">Add profile</a>'
      f'<table id="profiles-table">{rows}</table>'
   )
   return page(tenant_id, "Profiles", body, "/profiles", toast)


def profile_editor(tenant_id, name=None, error=""):
   profile = (
      next(p for p in STORE.tenant(tenant_id).view()["profiles"] if p["name"] == name)
      if name
      else {"name": "", "level": "low", "description": ""}
   )
   action = f"/profiles/{quote(name)}/edit" if name else "/profiles/new"
   readonly = " readonly" if name else ""
   body = (
      f'<form method="post" action="{action}">'
      f'<input id="profile-name" name="name" value="{escape(profile["name"])}"{readonly}>'
      f'<select id="profile-level" name="level">{options(LEVELS, profile["level"])}</select>'
      f'<input id="profile-description" name="description" '
      f'value="{escape(profile["description"])}">'
      '<button id="profile-save">Save profile</button></form>'
   )
   return page(tenant_id, f"Profile {name}" if name else "Add profile", body, action, error=error)


def capabilities_page(tenant_id, toast):
   caps = STORE.tenant(tenant_id).settings["capabilities"]
   boxes = "".join(
      f'<label><input type="checkbox" id="cap-{key}" name="{key}" form="settings-form"'
      f"{' checked' if on else ''}>{key}</label>"
      for key, on in caps.items()
      if key not in NUMERIC_CAPABILITIES
   )
   numbers = "".join(
      f'<label>{key} <input type="number" min="1" id="cap-{key}" name="{key}" '
      f'value="{caps[key]}" form="settings-form"></label>'
      for key in NUMERIC_CAPABILITIES
   )
   body = (
      f'<form id="settings-form" method="post" action="/settings/save">{boxes}{numbers}'
      '<button id="settings-save">Apply settings</button></form>'
   )
   return page(tenant_id, "Capabilities", body, "/settings/capabilities", toast)


# --- request handling -----------------------------------------------------------------------


class Handler(BaseHTTPRequestHandler):
   server_version = "StandinPolicyApp/3.0"

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

   def _redirect(self, location, toast="", cookie=None):
      if toast:
         location += ("&" if "?" in location else "?") + "toast=" + quote(toast)
      self.send_response(HTTPStatus.SEE_OTHER)
      self.send_header("Location", location)
      if cookie is not None:
         self.send_header("Set-Cookie", f"session={cookie}; Path=/")
      self.end_headers()

   def _body(self):
      return self.rfile.read(int(self.headers.get("Content-Length") or 0))

   def _form(self):
      parsed = parse_qs(self._body().decode("utf-8"), keep_blank_values=True)
      return {k: v[-1] for k, v in parsed.items()}, parsed.get("selected", [])

   def _parts(self):
      url = urlsplit(self.path)
      query = {k: v[-1] for k, v in parse_qs(url.query).items()}
      return [unquote(p) for p in url.path.strip("/").split("/") if p], query

   def _session(self):
      cookie = SimpleCookie(self.headers.get("Cookie", ""))
      if "session" not in cookie:
         return None, None
      tenant, _, user = unquote(cookie["session"].value).partition("|")
      return tenant or None, user or None

   def _sign_in(self, status=HTTPStatus.UNAUTHORIZED):
      self._html("<!doctype html><title>Sign in</title><h1>Sign in</h1>", status)

   # dispatch

   def do_GET(self):
      parts, query = self._parts()
      if parts[:1] == ["api"]:
         self._api("GET", parts[1:])
         return
      if parts[:2] == ["ws", "browser"] and len(parts) == 3:
         self._browser_session(parts[2])
         return
      if parts == ["login"]:
         session = quote(f"{query.get('tenant', '')}|{query.get('user', '')}")
         self._redirect("/rules", cookie=session)
         return
      if parts == ["logout"]:
         self._redirect("/", cookie="")
         return
      if parts[:1] == ["site"] and len(parts) > 1:
         path = "/" + "/".join(parts[1:])
         if path in STORE.site["pages"]:
            self._html(agent.render(STORE.site["pages"][path]))
         else:
            self._json({"error": "not found"}, HTTPStatus.NOT_FOUND)
         return
      tenant, _ = self._session()
      if tenant is None:
         self._sign_in()
         return
      toast = query.get("toast", "")
      try:
         self._get_page(tenant, parts, query, toast)
      except (KeyError, StopIteration, ValueError):
         self._html(page(tenant, "Not found", "", "/rules"), HTTPStatus.NOT_FOUND)

   def _get_page(self, tenant, parts, query, toast):
      if not parts or parts == ["rules"]:
         self._html(rules_page(tenant, query, toast))
      elif parts == ["rules", "new"]:
         self._html(wizard_step1(tenant))
      elif parts == ["rules", "import"]:
         self._html(import_page(tenant))
      elif len(parts) == 3 and parts[0] == "rules" and parts[2] == "edit":
         self._html(rule_editor(tenant, parts[1]))
      elif parts == ["profiles"]:
         self._html(profiles_page(tenant, query, toast))
      elif parts == ["profiles", "new"]:
         self._html(profile_editor(tenant))
      elif len(parts) == 3 and parts[0] == "profiles" and parts[2] == "edit":
         self._html(profile_editor(tenant, parts[1]))
      elif parts == ["settings", "capabilities"]:
         self._html(capabilities_page(tenant, toast))
      elif parts == ["files"]:
         self._v4(tenant, pages_v4.download_center(STORE, tenant), "/files", toast)
      elif len(parts) == 3 and parts[0] == "files" and parts[2] == "download":
         verdict = STORE.download(tenant, parts[1], query.get("mode", "converted"))
         self._v4(tenant, pages_v4.verdict_page(parts[1], verdict), "/files", toast)
      elif len(parts) == 3 and parts[0] == "files" and parts[2] == "view":
         result = STORE.view_file(tenant, parts[1])
         self._v4(tenant, pages_v4.viewer_page(parts[1], result), "/files", toast)
      elif parts == ["settings", "downloads"]:
         policy = STORE.file_policy(tenant)
         self._v4(tenant, pages_v4.download_policy_page(policy), "/settings/downloads", toast)
      elif parts == ["agent"]:
         sessions = STORE.sessions(tenant)["sessions"]
         title_body = pages_v4.agent_console(STORE.site["pages"], sessions=sessions)
         self._v4(tenant, title_body, "/agent", toast)
      elif parts == ["settings", "agent"]:
         settings = STORE.tenant(tenant).settings
         self._v4(tenant, pages_v4.agent_settings_page(settings), "/settings/agent", toast)
      else:
         raise KeyError(self.path)

   def _browser_session(self, tenant):
      """An agent browser session over WebSocket. At the tenant's limit: 429 before the upgrade.
      Otherwise 101; the session holds its slot until the client closes the connection."""
      key = self.headers.get("Sec-WebSocket-Key", "")
      if self.headers.get("Upgrade", "").lower() != "websocket" or not key:
         self._json({"error": "WebSocket upgrade required"}, HTTPStatus.BAD_REQUEST)
         return
      try:
         with SESSIONS_LOCK:
            session = STORE.open_session(tenant, self.headers.get("X-User", ""))
      except LimitReached as exc:
         self._send(HTTPStatus.TOO_MANY_REQUESTS, str(exc), "text/plain")
         return
      accept = base64.b64encode(hashlib.sha1((key + _WS_GUID).encode()).digest()).decode()
      self.send_response(HTTPStatus.SWITCHING_PROTOCOLS)
      self.send_header("Upgrade", "websocket")
      self.send_header("Connection", "Upgrade")
      self.send_header("Sec-WebSocket-Accept", accept)
      self.end_headers()
      self.wfile.flush()
      closed_by_client = False
      try:
         closed_by_client = _wait_for_close(self.rfile)
      finally:
         STORE.close_session(tenant, session["id"])  # the slot is free before the reply
         self.close_connection = True
      if closed_by_client:
         try:
            self.wfile.write(b"\x88\x00")  # answer the client's close frame
            self.wfile.flush()
         except OSError:
            pass

   def _v4(self, tenant, title_body, here, toast="", status=HTTPStatus.OK):
      title, body = title_body
      self._html(page(tenant, title, body, here, toast), status)

   def do_POST(self):
      parts, _ = self._parts()
      if parts[:1] == ["api"]:
         self._api("POST", parts[1:])
         return
      tenant, user = self._session()
      if tenant is None:
         self._sign_in()
         return
      form, selected = self._form()
      try:
         self._post_form(tenant, user, parts, form, selected)
      except ValidationError as exc:
         self._form_error(tenant, parts, form, str(exc))

   def do_PUT(self):
      parts, _ = self._parts()
      if parts[:1] == ["api"]:
         self._api("PUT", parts[1:])
      else:
         self._json({}, HTTPStatus.NOT_FOUND)

   def _post_form(self, tenant, user, parts, form, selected):
      back = form.get("next", "/rules")
      if parts == ["topbar", "save"]:
         STORE.save(tenant)
         self._redirect(back, "Changes saved")
      elif parts == ["topbar", "publish"]:
         rev_id = STORE.publish(tenant)
         self._redirect(back, f"Published revision {rev_id}")
      elif parts == ["topbar", "reset"]:
         STORE.discard(tenant)
         self._redirect(back, "Changes discarded")
      elif parts == ["rules", "new", "step1"]:
         if not form.get("name", "").strip():
            raise ValidationError("Name is required")
         WIZARDS[(tenant, user)] = {k: form.get(k, "") for k in ("name", "action", "description")}
         self._html(wizard_step2(tenant))
      elif parts == ["rules", "new", "save"]:
         rule = dict(WIZARDS.pop((tenant, user), {}))
         if form.get("field"):
            rule["conditions"] = [{"field": form["field"], "value": form.get("value", "")}]
         try:
            STORE.add_rule(tenant, rule)
         except ValidationError:
            WIZARDS[(tenant, user)] = {k: v for k, v in rule.items() if k != "conditions"}
            raise
         self._redirect("/rules", "Rule added")
      elif len(parts) == 3 and parts[0] == "rules" and parts[2] == "edit":
         changes = {
            "action": form.get("action", "allow"),
            "enabled": "enabled" in form,
            "description": form.get("description", ""),
         }
         STORE.update_rule(tenant, parts[1], changes)
         self._redirect("/rules", "Rule saved")
      elif parts == ["rules", "delete"]:
         if not selected:
            raise ValidationError("Select at least one rule")
         self._html(delete_confirm(tenant, selected))
      elif parts == ["rules", "delete", "confirm"]:
         STORE.delete_rules(tenant, selected)
         self._redirect("/rules", "Rules deleted")
      elif parts == ["rules", "import"]:
         try:
            rules = json.loads(form.get("content", "") or "[]")
         except json.JSONDecodeError:
            raise ValidationError("The file is not valid JSON") from None
         added = STORE.import_rules(tenant, rules)
         self._redirect("/rules", f"Imported {len(added)} rules")
      elif parts == ["profiles", "new"]:
         STORE.add_profile(tenant, {k: form.get(k, "") for k in ("name", "level", "description")})
         self._redirect("/profiles", "Profile added")
      elif len(parts) == 3 and parts[0] == "profiles" and parts[2] == "edit":
         changes = {k: form.get(k, "") for k in ("level", "description")}
         STORE.update_profile(tenant, parts[1], changes)
         self._redirect("/profiles", "Profile saved")
      elif len(parts) == 3 and parts[0] == "profiles" and parts[2] == "delete":
         STORE.delete_profile(tenant, parts[1])
         self._redirect("/profiles", "Profile deleted")
      elif parts == ["settings", "save"]:
         caps = STORE.tenant(tenant).settings["capabilities"]
         changes = {key: key in form for key in caps if key not in NUMERIC_CAPABILITIES}
         for key in NUMERIC_CAPABILITIES:
            try:
               changes[key] = int(form.get(key, ""))
            except ValueError:
               raise ValidationError(f"{key} must be a whole number of at least 1") from None
         STORE.update_capabilities(tenant, changes)
         self._redirect("/settings/capabilities", "Settings applied")
      elif len(parts) == 3 and parts[0] == "files" and parts[2] == "download":
         mode = form.get("mode", "converted")
         verdict = STORE.download(tenant, parts[1], mode, form.get("password", ""))
         self._v4(tenant, pages_v4.verdict_page(parts[1], verdict), "/files")
      elif parts == ["settings", "downloads"]:
         changes = pages_v4.file_policy_changes(form, STORE.file_policy(tenant))
         STORE.update_file_policy(tenant, changes)
         self._redirect("/settings/downloads", "Download policy saved")
      elif parts == ["agent", "run"]:
         task = STORE.run_agent(tenant, form.get("goal", ""), form.get("start_page", ""))
         sessions = STORE.sessions(tenant)["sessions"]
         self._v4(tenant, pages_v4.agent_console(STORE.site["pages"], task, sessions), "/agent")
      elif parts == ["agent", "browser"]:  # the console opens a browser session for the user
         _, user = self._session()
         try:
            with SESSIONS_LOCK:
               STORE.open_session(tenant, user or "")
         except LimitReached as exc:
            sessions = STORE.sessions(tenant)["sessions"]
            title_body = pages_v4.agent_console(STORE.site["pages"], None, sessions, str(exc))
            self._v4(tenant, title_body, "/agent", status=HTTPStatus.TOO_MANY_REQUESTS)
            return
         self._redirect("/agent", "Browser opened")
      elif len(parts) == 4 and parts[:2] == ["agent", "browser"] and parts[3] == "close":
         STORE.close_session(tenant, parts[2])
         self._redirect("/agent", "Browser closed")
      elif parts == ["settings", "agent"]:
         STORE.update_agent_settings(tenant, {"injection_guard": "injection_guard" in form})
         self._redirect("/settings/agent", "Agent settings applied")
      else:
         self._html(page(tenant, "Not found", "", "/rules"), HTTPStatus.NOT_FOUND)

   def _form_error(self, tenant, parts, form, error):
      status = HTTPStatus.UNPROCESSABLE_ENTITY
      if parts == ["rules", "new", "step1"]:
         self._html(wizard_step1(tenant, form, error), status)
      elif parts == ["rules", "new", "save"]:
         self._html(wizard_step2(tenant, error), status)
      elif len(parts) == 3 and parts[0] == "rules" and parts[2] == "edit":
         self._html(rule_editor(tenant, parts[1], error), status)
      elif parts == ["rules", "import"]:
         self._html(import_page(tenant, error), status)
      elif parts == ["profiles", "new"]:
         self._html(profile_editor(tenant, None, error), status)
      elif len(parts) == 3 and parts[0] == "profiles":
         self._html(profile_editor(tenant, parts[1], error), status)
      else:
         self._html(page(tenant, "Error", "", form.get("next", "/rules"), error=error), status)

   # JSON API

   def _api(self, method, parts):
      try:
         raw = self._body() if method in ("POST", "PUT") else b""
         payload = json.loads(raw) if raw else {}
         result = route_api(method, parts, payload, self.headers.get("X-User", ""))
      except PermissionDenied as exc:
         self._json({"error": str(exc)}, HTTPStatus.FORBIDDEN)
      except ValidationError as exc:
         self._json({"error": str(exc)}, HTTPStatus.UNPROCESSABLE_ENTITY)
      except (KeyError, LookupError, ValueError):
         self._json({"error": "not found"}, HTTPStatus.NOT_FOUND)
      else:
         self._json(result)


def _wait_for_close(rfile):
   """Read client frames until a close frame (True) or a disconnect (False)."""
   while True:
      head = rfile.read(2)
      if len(head) < 2:
         return False
      opcode, length = head[0] & 0x0F, head[1] & 0x7F
      if length == 126:
         length = int.from_bytes(rfile.read(2), "big")
      elif length == 127:
         length = int.from_bytes(rfile.read(8), "big")
      if head[1] & 0x80:  # client frames are masked: skip the 4-byte mask
         rfile.read(4)
      rfile.read(length)
      if opcode == 0x8:  # close
         return True


def route_api(method, parts, payload, user=""):
   """JSON API routing, separate from the handler so it can be tested without a server."""
   match method, parts:
      case "POST", ["_reset"]:
         STORE.reset()
         WIZARDS.clear()
         return {"ok": True}
      case "POST", ["_seed"]:
         STORE.seed(payload["tenants"])  # the data entry's seed sections, per tenant
         STORE.seed_site(payload.get("site") or {})
         return {"ok": True}
      case "GET", ["policy", "v1", "revision", tenant]:
         return {"rev_id": STORE.tenant(tenant).rev_id}
      case "GET", ["policy", "v1", "policy", tenant, rev_id]:
         return STORE.published(tenant, int(rev_id))
      case "GET", ["policy", "v1", ("rules" | "profiles") as section, tenant, rev_id]:
         return STORE.published(tenant, int(rev_id))[section]
      case "PUT", ["policy", "v1", "rules", tenant]:
         return {"rev_id": STORE.api_replace_rules(tenant, user, payload.get("rules", []))}
      case "GET", ["settings", "v1", "settings", tenant]:
         return STORE.tenant(tenant).settings
      case "GET", ["settings", "v1", "capabilities", tenant]:
         return STORE.tenant(tenant).settings["capabilities"]
      case "PUT", ["settings", "v1", "capabilities", tenant]:
         role = STORE.tenant(tenant).settings["roles"].get(user, "viewer")
         if role != "admin":
            raise PermissionDenied(f"Role '{role}' cannot change capabilities")
         return STORE.update_capabilities(tenant, payload)["capabilities"]
      case "GET", ["agent", "v1", "sessions", tenant]:
         return STORE.sessions(tenant)
      case "PUT", ["settings", "v1", "agent", tenant]:
         role = STORE.tenant(tenant).settings["roles"].get(user, "viewer")
         if role != "admin":
            raise PermissionDenied(f"Role '{role}' cannot change agent settings")
         return STORE.update_agent_settings(tenant, payload)
      case "GET", ["files", "v1", "policy", tenant, rev_id]:
         return files.file_policy(STORE.published(tenant, int(rev_id)))
      case "POST", ["downloads", "v1", "download", tenant]:
         return STORE.download(
            tenant, payload["file"], payload.get("mode", "converted"), payload.get("password")
         )
      case "GET", ["downloads", "v1", "log", tenant]:
         return STORE.tenant(tenant).downloads
      case "POST", ["agent", "v1", "tasks", tenant]:
         return STORE.run_agent(tenant, payload.get("goal", ""), payload.get("start_page", ""))
      case "GET", ["agent", "v1", "tasks", tenant]:
         return STORE.tenant(tenant).tasks
      case "GET", ["agent", "v1", "tasks", tenant, task_id]:
         return STORE.tenant(tenant).tasks[int(task_id) - 1]
   raise LookupError(f"{method} /api/{'/'.join(parts)}")


def main():
   parser = argparse.ArgumentParser(description="Run the stand-in fake policy app.")
   parser.add_argument("--host", default="127.0.0.1")
   parser.add_argument("--port", type=int, default=8080)
   args = parser.parse_args()
   server = ThreadingHTTPServer((args.host, args.port), Handler)
   print(f"Stand-in app on http://{args.host}:{args.port}")
   server.serve_forever()


if __name__ == "__main__":
   main()
