"""The stand-in's agent browser limit over real WebSocket connections (127.0.0.1 only).

The expectation replays in test_standin.py drive the store directly; this runs the app's HTTP
server in a thread and connects with the framework's own WebSocket client, so the handshake,
the 429 before the upgrade, and closing a socket to free a slot are checked for real.
"""

from __future__ import annotations

import importlib
import sys
import threading
from collections.abc import Iterator
from http.server import ThreadingHTTPServer
from types import ModuleType
from typing import Any

import pytest

from tests.conftest import REPO_ROOT

STANDIN = REPO_ROOT / "standin"
pytestmark = pytest.mark.loopback


@pytest.fixture
def app() -> Iterator[dict[str, Any]]:
    sys.path.insert(0, str(STANDIN))
    try:
        modules: dict[str, ModuleType] = {
            name: importlib.import_module(name)
            for name in ("app.server", "framework.api_client", "framework.browser_sessions")
        }
        server = modules["app.server"]
        httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        base = f"http://127.0.0.1:{httpd.server_address[1]}"
        api = modules["framework.api_client"].ApiClient(base + "/api", timeout=5)
        api.reset()
        api.seed(
            [
                {
                    "tenant": "tenant-a",
                    "settings": {
                        "roles": {"admin@example.com": "admin"},
                        "capabilities": {"browser_limit": 2},
                    },
                }
            ]
        )
        sessions = modules["framework.browser_sessions"].BrowserSessions(base, timeout=5)
        yield {"api": api, "sessions": sessions}
        sessions.close_all()
        httpd.shutdown()
        httpd.server_close()
    finally:
        sys.path.remove(str(STANDIN))


def _open(api: Any, tenant: str = "tenant-a") -> int:
    return int(api.request("GET", f"agent/v1/sessions/{tenant}")[1]["open"])


def test_the_limit_refuses_before_the_upgrade(app: dict[str, Any]) -> None:
    sessions, api = app["sessions"], app["api"]
    first, second = sessions.connect("tenant-a"), sessions.connect("tenant-a")
    assert (first.status, second.status) == (101, 101) and first.is_open
    refused = sessions.connect("tenant-a")
    assert (refused.status, refused.body, refused.is_open) == (429, "Browser limit reached", False)
    assert sessions.connect("tenant-b").status == 101  # the limit is per tenant
    assert _open(api) == 2


def test_closing_a_session_frees_its_slot_at_once(app: dict[str, Any]) -> None:
    sessions, api = app["sessions"], app["api"]
    first, _second = sessions.connect("tenant-a"), sessions.connect("tenant-a")
    first.close()  # the server frees the slot before answering the close frame
    assert _open(api) == 1
    assert sessions.connect("tenant-a").status == 101


def test_a_new_limit_applies_to_the_next_attempt_only(app: dict[str, Any]) -> None:
    sessions, api = app["sessions"], app["api"]
    opened = [sessions.connect("tenant-a"), sessions.connect("tenant-a")]
    path = "settings/v1/capabilities/tenant-a"
    assert api.request("PUT", path, {"browser_limit": 1}, "admin@example.com")[0] == 200
    assert _open(api) == 2 and all(s.is_open for s in opened)  # not cut
    assert sessions.connect("tenant-a").status == 429
    api.request("PUT", path, {"browser_limit": 3}, "admin@example.com")
    assert sessions.connect("tenant-a").status == 101


def test_only_admins_change_it_and_each_tenant_reads_its_own(app: dict[str, Any]) -> None:
    api = app["api"]
    status, body = api.request(
        "PUT", "settings/v1/capabilities/tenant-a", {"browser_limit": 9}, "someone@example.com"
    )
    assert status == 403 and "cannot change capabilities" in body["error"]
    assert api.request("GET", "settings/v1/capabilities/tenant-a")[1]["browser_limit"] == 2
    assert api.request("GET", "settings/v1/capabilities/tenant-b")[1]["browser_limit"] == 3
    status, _ = api.request(
        "PUT", "settings/v1/capabilities/tenant-a", {"browser_limit": 0}, "admin@example.com"
    )
    assert status == 422  # at least 1
