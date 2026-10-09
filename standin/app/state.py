"""In-memory backend state: one policy per tenant, edited in the UI and published as revisions.

Each tenant has:
- ``settings``: capabilities (on/off gates, and ``browser_limit``: how many agent browser
  sessions the tenant may have open at once), user roles, API-token state;
- a policy (rules, profiles, and file-policy sections) in three layers: the **working copy**
  (object editors write here; "unsaved changes"), the **saved draft** (top-bar save), and the
  **published revisions** (top-bar publish; ``rev_id`` is the latest revision number);
- a download log, the browsing agent's tasks, and its open browser sessions (enforcement
  uses the latest *published* policy, never unsaved edits).

The store also holds the fake **external site** (``site``): files and pages the browser and
the agent can reach, seeded per test.

Pure functions on a Store, so it is testable without a server.
"""

import copy

from app import agent, files

ACTIONS = ("allow", "deny", "log")
LEVELS = ("low", "medium", "high")
ROLES = ("viewer", "editor", "admin")
DEFAULT_CAPABILITIES = {
   "rules": True,
   "profiles": True,
   "bulk_delete": False,
   "import": True,
   "browser_limit": 3,  # agent browser sessions open at once, per tenant
}
NUMERIC_CAPABILITIES = ("browser_limit",)
BROWSER_LIMIT_MESSAGE = "Browser limit reached"
EMPTY_POLICY = {"rules": [], "profiles": []}
PAGE_SIZE = 5
NAME_MAX_LENGTH = 32


class ValidationError(ValueError):
   """Invalid input; the message is shown to the user."""


class PermissionDenied(PermissionError):
   """The user's role does not allow the change."""


class LimitReached(RuntimeError):
   """The tenant already has ``browser_limit`` browser sessions open."""


class Tenant:
   def __init__(self, tenant_id):
      self.id = tenant_id
      self.settings = {
         "capabilities": dict(DEFAULT_CAPABILITIES),
         "roles": {},
         "api_tokens": {"enabled": False},
         "agent": {"injection_guard": True},
      }
      self.downloads = []  # the download log, newest last
      self.tasks = []  # the browsing agent's tasks, newest last
      self.sessions = {}  # open browser sessions: id -> {id, user}
      self.next_session = 1
      self.draft = copy.deepcopy(EMPTY_POLICY)
      self.working = None  # None: no unsaved changes
      self.revisions = [copy.deepcopy(EMPTY_POLICY)]  # revision 0

   @property
   def rev_id(self):
      return len(self.revisions) - 1

   @property
   def has_unsaved_changes(self):
      return self.working is not None

   def view(self):
      """What the UI shows: the working copy if there are unsaved changes, else the draft."""
      return self.working if self.working is not None else self.draft

   def edit(self):
      if self.working is None:
         self.working = copy.deepcopy(self.draft)
      return self.working


class Store:
   def __init__(self):
      self.tenants = {}
      self.site = {"files": {}, "pages": {}}

   # --- seed / reset (the test framework's setup applies data-entry sections) ----------

   def reset(self):
      self.tenants.clear()
      self.site = {"files": {}, "pages": {}}

   def seed_site(self, site):
      """Add files and pages to the fake external site (by name and by path)."""
      for spec in site.get("files", []):
         files.build(spec)  # fails early on a bad description
         self.site["files"][spec["name"]] = copy.deepcopy(spec)
      for page in site.get("pages", []):
         self.site["pages"][page["path"]] = copy.deepcopy(page)

   def tenant(self, tenant_id):
      if tenant_id not in self.tenants:
         self.tenants[tenant_id] = Tenant(tenant_id)
      return self.tenants[tenant_id]

   def seed(self, blocks):
      """Apply per-tenant seed blocks: ``[{"tenant": id, "settings": {...}, "policy": {...}}]``.

      A seeded policy becomes the saved draft and is published as revision 1.
      """
      for block in blocks:
         tenant = self.tenant(block["tenant"])
         settings = block.get("settings", {})
         tenant.settings["capabilities"].update(settings.get("capabilities", {}))
         tenant.settings["roles"].update(settings.get("roles", {}))
         tenant.settings["api_tokens"].update(settings.get("api_tokens", {}))
         tenant.settings["agent"].update(settings.get("agent", {}))
         if "policy" in block:
            policy = copy.deepcopy(EMPTY_POLICY)
            policy.update(copy.deepcopy(block["policy"]))
            policy["rules"] = [_rule(r) for r in policy["rules"]]
            policy["profiles"] = [_profile(p) for p in policy["profiles"]]
            tenant.draft = policy
            tenant.working = None
            tenant.revisions.append(copy.deepcopy(policy))

   # --- rules (object editors write the working copy) -----------------------------------

   def add_rule(self, tenant_id, rule):
      tenant = self._editable(tenant_id, "rules")
      rule = _rule(rule)
      if not rule["name"].strip():
         raise ValidationError("Name is required")
      if any(r["name"] == rule["name"] for r in tenant.view()["rules"]):
         raise ValidationError(f"A rule named '{rule['name']}' already exists")
      tenant.edit()["rules"].append(rule)
      return rule

   def update_rule(self, tenant_id, name, changes):
      tenant = self._editable(tenant_id, "rules")
      rule = _find(tenant.edit()["rules"], name, "rule")
      if "action" in changes and changes["action"] not in ACTIONS:
         raise ValidationError(f"Unknown action '{changes['action']}'")
      for key in ("action", "enabled", "description", "conditions"):
         if key in changes:
            rule[key] = copy.deepcopy(changes[key])
      return rule

   def delete_rules(self, tenant_id, names):
      tenant = self._editable(tenant_id, "rules")
      if len(names) > 1 and not tenant.settings["capabilities"]["bulk_delete"]:
         raise ValidationError("Deleting several rules at once is not enabled")
      rules = tenant.edit()["rules"]
      for name in names:
         rules.remove(_find(rules, name, "rule"))

   def import_rules(self, tenant_id, rules):
      if not self.tenant(tenant_id).settings["capabilities"]["import"]:
         raise ValidationError("Import is not enabled")
      return [self.add_rule(tenant_id, rule) for rule in rules]

   def list_rules(self, tenant_id, text="", action="", page=1):
      """One page of rules matching the search text and action filter, plus the total.

      Rules are listed by name, ignoring case, so page contents are predictable.
      """
      needle = text.strip().lower()
      matching = sorted(
         (
            r
            for r in self.tenant(tenant_id).view()["rules"]
            if needle in r["name"].lower() and action in ("", r["action"])
         ),
         key=lambda r: (r["name"].lower(), r["name"]),
      )
      start = (max(page, 1) - 1) * PAGE_SIZE
      return matching[start : start + PAGE_SIZE], len(matching)

   # --- profiles -------------------------------------------------------------------------

   def add_profile(self, tenant_id, profile):
      tenant = self._editable(tenant_id, "profiles")
      profile = _profile(profile)
      if not profile["name"].strip():
         raise ValidationError("Name is required")
      if any(p["name"] == profile["name"] for p in tenant.view()["profiles"]):
         raise ValidationError(f"A profile named '{profile['name']}' already exists")
      tenant.edit()["profiles"].append(profile)
      return profile

   def update_profile(self, tenant_id, name, changes):
      tenant = self._editable(tenant_id, "profiles")
      if "level" in changes and changes["level"] not in LEVELS:
         raise ValidationError(f"Unknown level '{changes['level']}'")
      profile = _find(tenant.edit()["profiles"], name, "profile")
      for key in ("level", "description"):
         if key in changes:
            profile[key] = changes[key]
      # Known bug STND-105: the change is also written to the saved draft, so a reset keeps it.
      _find(tenant.draft["profiles"], name, "profile").update(copy.deepcopy(profile))
      return profile

   def delete_profile(self, tenant_id, name):
      profiles = self._editable(tenant_id, "profiles").edit()["profiles"]
      profiles.remove(_find(profiles, name, "profile"))

   def search_profiles(self, tenant_id, text=""):
      needle = text.strip().lower()
      return [p for p in self.tenant(tenant_id).view()["profiles"] if needle in p["name"].lower()]

   # --- top bar --------------------------------------------------------------------------

   def save_blocked(self, tenant_id):
      """Why the top-bar save is disabled, or None."""
      tenant = self.tenant(tenant_id)
      if not tenant.has_unsaved_changes:
         return "Nothing to save"
      if not tenant.settings["capabilities"]["rules"]:
         return "Editing rules is not enabled"
      return None

   def save(self, tenant_id):
      tenant = self.tenant(tenant_id)
      reason = self.save_blocked(tenant_id)
      if reason:
         raise ValidationError(reason)
      tenant.draft = tenant.working
      tenant.working = None

   def publish(self, tenant_id):
      tenant = self.tenant(tenant_id)
      if tenant.has_unsaved_changes:
         raise ValidationError("Save your changes before publishing")
      tenant.revisions.append(copy.deepcopy(tenant.draft))
      return tenant.rev_id

   def discard(self, tenant_id):
      """Top-bar reset: drop unsaved changes."""
      self.tenant(tenant_id).working = None

   # --- settings -------------------------------------------------------------------------

   def update_capabilities(self, tenant_id, capabilities):
      caps = self.tenant(tenant_id).settings["capabilities"]
      unknown = [k for k in capabilities if k not in caps]
      if unknown:
         raise ValidationError(f"Unknown capabilities: {unknown}")
      for key, value in capabilities.items():
         if key in NUMERIC_CAPABILITIES:
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
               raise ValidationError(f"{key} must be a whole number of at least 1")
            caps[key] = value
         else:
            caps[key] = bool(value)
      return self.tenant(tenant_id).settings

   # --- agent browser sessions ----------------------------------------------------------

   def open_session(self, tenant_id, user=""):
      """A new browser session, unless the tenant is at its ``browser_limit``. The limit is
      read at every attempt, so a changed limit applies to the next attempt; sessions already
      open are never closed by it."""
      tenant = self.tenant(tenant_id)
      if len(tenant.sessions) >= tenant.settings["capabilities"]["browser_limit"]:
         raise LimitReached(BROWSER_LIMIT_MESSAGE)
      session = {"id": tenant.next_session, "user": user}
      tenant.sessions[session["id"]] = session
      tenant.next_session += 1
      return dict(session)

   def close_session(self, tenant_id, session_id):
      """The session's connection closed: its slot is free for the next attempt."""
      self.tenant(tenant_id).sessions.pop(int(session_id), None)

   def sessions(self, tenant_id):
      open_now = sorted(self.tenant(tenant_id).sessions.values(), key=lambda s: s["id"])
      return {"open": len(open_now), "sessions": [dict(s) for s in open_now]}

   def update_agent_settings(self, tenant_id, changes):
      agent_settings = self.tenant(tenant_id).settings["agent"]
      unknown = [k for k in changes if k not in agent_settings]
      if unknown:
         raise ValidationError(f"Unknown agent settings: {unknown}")
      agent_settings.update({k: bool(v) for k, v in changes.items()})
      return self.tenant(tenant_id).settings

   # --- file policies (the editor writes the working copy) -------------------------------

   def file_policy(self, tenant_id):
      """The file policy the UI shows (working copy or draft), with defaults filled in."""
      return files.file_policy(self.tenant(tenant_id).view())

   def update_file_policy(self, tenant_id, changes):
      """Change file-policy sections in the working copy (top-bar save and publish follow)."""
      working = self.tenant(tenant_id).edit()
      unknown = [k for k in changes if k not in files.DEFAULT_FILE_POLICY]
      if unknown:
         raise ValidationError(f"Unknown file-policy sections: {unknown}")
      for key, value in changes.items():
         working[key] = copy.deepcopy(value)
      return files.file_policy(working)

   def download(self, tenant_id, name, mode="converted", password=None):
      """Enforce the latest published policy on a site file; the verdict is logged."""
      tenant = self.tenant(tenant_id)
      spec = self.site["files"].get(name)
      if spec is None:
         raise KeyError(name)
      published = tenant.revisions[-1]
      verdict = files.evaluate(published, name, files.build(spec), mode, password)
      tenant.downloads.append(verdict)
      return verdict

   def view_file(self, tenant_id, name, password=None):
      spec = self.site["files"].get(name)
      if spec is None:
         raise KeyError(name)
      published = self.tenant(tenant_id).revisions[-1]
      return files.view(published, name, files.build(spec), password)

   # --- the browsing agent -----------------------------------------------------------------

   def run_agent(self, tenant_id, goal, start_page):
      """Run a task; ``download`` actions go through the file pipeline and the log."""
      tenant = self.tenant(tenant_id)
      try:
         result = agent.run(
            self.site["pages"], goal, start_page, tenant.settings["agent"]["injection_guard"]
         )
      except agent.AgentError as exc:
         raise ValidationError(str(exc)) from None
      for action in result["actions"]:
         verb, _, target = action.partition(" ")
         if verb == "download" and target in self.site["files"]:
            self.download(tenant_id, target)
      task = {"id": len(tenant.tasks) + 1, "goal": goal, "start_page": start_page, **result}
      tenant.tasks.append(task)
      return task

   # --- API writes (role-checked; save and publish in one step) --------------------------

   def api_replace_rules(self, tenant_id, user, rules):
      tenant = self.tenant(tenant_id)
      role = tenant.settings["roles"].get(user, "viewer")
      if role != "admin":
         raise PermissionDenied(f"Role '{role}' cannot change rules")
      tenant.draft = copy.deepcopy(tenant.draft)
      tenant.draft["rules"] = [_rule(r) for r in rules]
      tenant.working = None
      return self.publish(tenant_id)

   def published(self, tenant_id, rev_id):
      tenant = self.tenant(tenant_id)
      if not 0 <= rev_id <= tenant.rev_id:
         raise KeyError(rev_id)
      return tenant.revisions[rev_id]

   # --- helpers --------------------------------------------------------------------------

   def _editable(self, tenant_id, capability):
      tenant = self.tenant(tenant_id)
      if not tenant.settings["capabilities"][capability]:
         raise ValidationError(f"Editing {capability} is not enabled")
      return tenant


def _rule(rule):
   action = rule.get("action", "allow")
   if action not in ACTIONS:
      raise ValidationError(f"Unknown action '{action}'")
   return {
      "name": _name(rule),
      "action": action,
      "enabled": bool(rule.get("enabled", True)),
      "description": str(rule.get("description", "")),
      "conditions": copy.deepcopy(rule.get("conditions", [])),
   }


def _profile(profile):
   level = profile.get("level", "low")
   if level not in LEVELS:
      raise ValidationError(f"Unknown level '{level}'")
   return {
      "name": _name(profile),
      "level": level,
      "description": str(profile.get("description", "")),
   }


def _find(objects, name, kind):
   for obj in objects:
      if obj["name"] == name:
         return obj
   raise ValidationError(f"Unknown {kind} '{name}'")


def _name(obj):
   name = str(obj.get("name", ""))
   if len(name) > NAME_MAX_LENGTH:
      raise ValidationError(f"Name is longer than {NAME_MAX_LENGTH} characters")
   return name
