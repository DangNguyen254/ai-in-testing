"""Agent browser sessions over WebSocket (stdlib only): open, check the handshake, close.

A connection attempt returns a ``BrowserSession``: ``status`` 101 when the upgrade happened (the
session is open until ``close()``), otherwise the refusal's status and body (e.g. 429 and
``Browser limit reached``). Tests never need the frames themselves, only whether a session is
allowed and that closing it frees the slot.
"""

import base64
import hashlib
import os
import socket
from urllib.parse import urlsplit

_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"


class BrowserSession:
   def __init__(self, status, body="", sock=None):
      self.status = status
      self.body = body
      self._sock = sock

   @property
   def is_open(self):
      return self._sock is not None

   def close(self):
      """Send a close frame and disconnect (the server frees the session's slot)."""
      if self._sock is None:
         return
      try:
         self._sock.sendall(b"\x88\x80" + os.urandom(4))  # a masked close frame, no payload
         self._sock.recv(2)
      except OSError:
         pass
      finally:
         self._sock.close()
         self._sock = None


class BrowserSessions:
   """Opens sessions for a tenant and remembers them, so teardown can close what's left."""

   def __init__(self, base_url, timeout=10.0):
      parts = urlsplit(base_url)
      self.host = parts.hostname or "localhost"
      self.port = parts.port or 80
      self.timeout = timeout
      self.opened = []

   def connect(self, tenant, user=""):
      key = base64.b64encode(os.urandom(16)).decode()
      request = (
         f"GET /ws/browser/{tenant} HTTP/1.1\r\n"
         f"Host: {self.host}:{self.port}\r\n"
         "Upgrade: websocket\r\nConnection: Upgrade\r\n"
         f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n"
         f"X-User: {user}\r\n\r\n"
      )
      sock = socket.create_connection((self.host, self.port), timeout=self.timeout)
      sock.sendall(request.encode("ascii"))
      head, rest = _read_head(sock)
      status = int(head.split(" ", 2)[1])
      headers = _headers(head)
      if status == 101:
         expected = base64.b64encode(hashlib.sha1((key + _GUID).encode()).digest()).decode()
         if headers.get("sec-websocket-accept") != expected:
            sock.close()
            raise ConnectionError("WebSocket handshake: wrong Sec-WebSocket-Accept")
         session = BrowserSession(101, "", sock)
         self.opened.append(session)
         return session
      length = int(headers.get("content-length", "0"))
      while len(rest) < length:
         chunk = sock.recv(length - len(rest))
         if not chunk:
            break
         rest += chunk
      sock.close()
      return BrowserSession(status, rest.decode("utf-8", "replace"))

   def open_many(self, tenant, count, user=""):
      return [self.connect(tenant, user) for _ in range(count)]

   def close_all(self):
      for session in self.opened:
         session.close()
      self.opened = []


def _read_head(sock):
   data = b""
   while b"\r\n\r\n" not in data:
      chunk = sock.recv(1024)
      if not chunk:
         break
      data += chunk
   head, _, rest = data.partition(b"\r\n\r\n")
   return head.decode("iso-8859-1"), rest


def _headers(head):
   lines = head.split("\r\n")[1:]
   return {k.strip().lower(): v.strip() for k, _, v in (line.partition(":") for line in lines)}
