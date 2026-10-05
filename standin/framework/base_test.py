"""Base class for every stand-in test: setup/teardown, data entry, API client, lazy browser."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from selenium.webdriver.remote.webdriver import WebDriver

from framework.api_client import ApiClient
from framework.config import CONFIG, SuiteConfig
from framework.data import entry_for
from framework.driver import create_driver
from framework.names import resolve_placeholders, unique_suffix
from framework.pages import Navigator
from framework.validations import ValidationMixin


class BaseTest(ValidationMixin):
    """Setup: load the test's data entry, reset and seed the backend.
    Teardown: save failure artifacts, quit the browser, reset the backend.

    The browser starts only when a test touches ``self.driver`` or ``self.nav``, so pure API
    tests never launch one.
    """

    config: SuiteConfig = CONFIG
    data: dict[str, Any]
    unique: str

    @pytest.fixture(autouse=True)
    def _base_setup(self, request: pytest.FixtureRequest) -> Iterator[None]:
        self._driver: WebDriver | None = None
        self.unique = unique_suffix()
        entry = entry_for(Path(request.node.path), request.node.name)
        if entry is None:
            pytest.fail(f"No data entry '{request.node.name}' for {request.node.path}")
        self.data = resolve_placeholders(entry, self.unique)
        self.api = ApiClient(self.config.api_url, timeout=self.config.default_timeout)
        self.api.reset()
        self.api.seed(self.data.get("seed", {}))

        yield

        report = getattr(request.node, "rep_call", None)
        if report is not None and report.failed and self._driver is not None:
            self._save_failure_artifacts(request.node.name)
        if self._driver is not None:
            self._driver.quit()
        self.api.reset()

    @property
    def driver(self) -> WebDriver:
        if self._driver is None:
            self._driver = create_driver(self.config)
        return self._driver

    @property
    def nav(self) -> Navigator:
        return Navigator(self.driver, self.config.base_url, self.config.default_timeout)

    @property
    def inputs(self) -> dict[str, Any]:
        return dict(self.data.get("inputs", {}))

    @property
    def expected(self) -> dict[str, Any]:
        return dict(self.data.get("expected", {}))

    def _save_failure_artifacts(self, test_name: str) -> None:
        assert self._driver is not None
        folder = self.config.artifacts_dir
        folder.mkdir(parents=True, exist_ok=True)
        safe = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in test_name)
        self._driver.save_screenshot(str(folder / f"{safe}.png"))
        (folder / f"{safe}.html").write_text(self._driver.page_source, encoding="utf-8")
