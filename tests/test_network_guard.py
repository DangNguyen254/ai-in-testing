from __future__ import annotations

import socket

import httpx
import pytest


def test_socket_connections_are_blocked_in_unit_tests() -> None:
    with pytest.raises(RuntimeError, match="Network access attempted"):
        socket.create_connection(("example.com", 80), timeout=1)


def test_real_http_client_cannot_reach_network() -> None:
    with pytest.raises((RuntimeError, httpx.HTTPError)):
        httpx.get("https://api.github.com", timeout=1)
