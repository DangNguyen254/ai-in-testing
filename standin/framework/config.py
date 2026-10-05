"""Suite configuration from environment variables (no network access at import time)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

Deployment = Literal["cloud", "on_prem"]


@dataclass(frozen=True)
class SuiteConfig:
    base_url: str
    browser: str
    headless: bool
    deployment: Deployment
    artifacts_dir: Path
    default_timeout: float

    @property
    def api_url(self) -> str:
        return f"{self.base_url.rstrip('/')}/api"

    @classmethod
    def from_env(cls) -> SuiteConfig:
        deployment = os.environ.get("STANDIN_DEPLOYMENT", "cloud")
        if deployment not in ("cloud", "on_prem"):
            raise ValueError(f"STANDIN_DEPLOYMENT must be 'cloud' or 'on_prem', not {deployment!r}")
        return cls(
            base_url=os.environ.get("STANDIN_BASE_URL", "http://localhost:8080"),
            browser=os.environ.get("STANDIN_BROWSER", "chrome").lower(),
            headless=os.environ.get("STANDIN_HEADLESS", "1") != "0",
            deployment=deployment,  # type: ignore[arg-type]
            artifacts_dir=Path(os.environ.get("STANDIN_ARTIFACTS", "artifacts")),
            default_timeout=float(os.environ.get("STANDIN_TIMEOUT", "10")),
        )


CONFIG = SuiteConfig.from_env()
