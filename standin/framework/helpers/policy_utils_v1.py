"""Reading published policy sections (old version, kept for older tests)."""


def get_exception_names(policy):
   return [e["name"] for e in policy.get("exceptions", [])]
