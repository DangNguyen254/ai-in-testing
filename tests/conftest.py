from __future__ import annotations

import json
import os
import socket
from pathlib import Path
from typing import Any

import pytest

from ticket2test.adapters.tickets.base import RawTicket

REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURES = Path(__file__).resolve().parent / "fixtures"
GITHUB_FIXTURE_ISSUES = (2985, 1482, 1498, 1234, 914)


@pytest.fixture(autouse=True)
def _isolate_env(
    request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Keep unit tests independent of the developer's shell env and working directory.

    Live and sandbox tests are exempt: they need the real environment (e.g. the CLI path or
    the container runtime from `uv run --env-file .env`) and run from the repo root.
    """
    if request.node.get_closest_marker("live") or request.node.get_closest_marker("sandbox"):
        return
    for key in list(os.environ):
        if key.startswith("T2T_") or key == "GITHUB_TOKEN":
            monkeypatch.delenv(key)
    monkeypatch.chdir(tmp_path)


@pytest.fixture(autouse=True)
def _block_network(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> None:
    """Unit tests must never touch the network. Only @pytest.mark.live tests may."""
    if request.node.get_closest_marker("live"):
        return
    loopback = request.node.get_closest_marker("loopback") is not None
    connect, create, lookup = socket.socket.connect, socket.create_connection, socket.getaddrinfo

    def refuse(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("Network access attempted in a non-live test")

    def local_connect(sock: socket.socket, address: Any) -> Any:
        if loopback and _is_loopback(address):
            return connect(sock, address)
        return refuse()

    def local_create(address: Any, *args: Any, **kwargs: Any) -> Any:
        if loopback and _is_loopback(address):
            return create(address, *args, **kwargs)
        return refuse()

    monkeypatch.setattr(socket.socket, "connect", local_connect)
    monkeypatch.setattr(socket.socket, "connect_ex", refuse)
    monkeypatch.setattr(socket, "create_connection", local_create)

    def local_lookup(host: Any, *args: Any, **kwargs: Any) -> Any:
        if loopback and _is_loopback((host,)):
            return lookup(host, *args, **kwargs)
        return refuse()

    monkeypatch.setattr(socket, "getaddrinfo", local_lookup)


def _is_loopback(address: Any) -> bool:
    """A literal loopback address (no name lookup): only the stand-in app on this machine."""
    return isinstance(address, tuple) and address[0] in ("127.0.0.1", "::1")


def load_github_fixture(number: int) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    folder = FIXTURES / "github" / f"encode_httpx_{number}"
    issue = json.loads((folder / "issue.json").read_text(encoding="utf-8"))
    comments = json.loads((folder / "comments.json").read_text(encoding="utf-8"))
    return issue, comments


def github_raw(number: int) -> RawTicket:
    issue, comments = load_github_fixture(number)
    return RawTicket(
        source="github",
        ref=f"encode/httpx#{number}",
        payload={"issue": issue, "comments": comments, "comments_complete": True},
    )
