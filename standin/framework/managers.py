"""Policy and settings managers: change backend state directly, without the UI.

Tests call these at the top of a test when they need state the data entry doesn't seed.
"""


class PolicyManager:
   def __init__(self, api, tenant, user):
      self.api = api
      self.tenant = tenant
      self.user = user

   def rules(self):
      rev_id = self.api.revision(self.tenant)
      _, body = self.api.request("GET", f"policy/v1/rules/{self.tenant}/{rev_id}")
      return body

   def add_rule(self, name, action="allow", **fields):
      rules = [*self.rules(), {"name": name, "action": action, **fields}]
      status, body = self.api.request(
         "PUT", f"policy/v1/rules/{self.tenant}", {"rules": rules}, self.user
      )
      if status != 200:
         raise RuntimeError(f"adding rule {name!r} failed: {status} {body}")
      return body["rev_id"]


class SettingsManager:
   def __init__(self, api, tenant):
      self.api = api
      self.tenant = tenant

   def set_capabilities(self, **capabilities):
      self.api.seed([{"tenant": self.tenant, "settings": {"capabilities": capabilities}}])
