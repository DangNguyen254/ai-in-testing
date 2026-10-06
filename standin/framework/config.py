"""Suite configuration from environment variables (no network access at import time)."""

import os
from pathlib import Path

DEPLOYMENTS = ("cloud", "on_prem")


class SuiteConfig:
   def __init__(self, base_url, browser, headless, deployment, artifacts_dir, default_timeout):
      if deployment not in DEPLOYMENTS:
         raise ValueError(f"STANDIN_DEPLOYMENT must be 'cloud' or 'on_prem', not {deployment!r}")
      self.base_url = base_url
      self.browser = browser
      self.headless = headless
      self.deployment = deployment
      self.artifacts_dir = artifacts_dir
      self.default_timeout = default_timeout

   @property
   def api_url(self):
      return f"{self.base_url.rstrip('/')}/api"

   @classmethod
   def from_env(cls):
      return cls(
         base_url=os.environ.get("STANDIN_BASE_URL", "http://localhost:8080"),
         browser=os.environ.get("STANDIN_BROWSER", "chrome").lower(),
         headless=os.environ.get("STANDIN_HEADLESS", "1") != "0",
         deployment=os.environ.get("STANDIN_DEPLOYMENT", "cloud"),
         artifacts_dir=Path(os.environ.get("STANDIN_ARTIFACTS", "artifacts")),
         default_timeout=float(os.environ.get("STANDIN_TIMEOUT", "10")),
      )


CONFIG = SuiteConfig.from_env()
