"""Reading published policy sections (current version)."""


def exception_names(policy):
   return sorted(e["name"] for e in policy.get("exceptions", []))


def rule_names(policy):
   return sorted(r["name"] for r in policy.get("rules", []))
