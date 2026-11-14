"""Text to vectors, through one embed worker shared by every agent on the machine.

An agent's server holds no model. It sends text over a local socket to the worker
(:mod:`brain_core.embed_worker`), which loads the model once, answers, keeps nothing, and exits
when idle. The first caller starts it; a lock file allows only one. Anything that goes wrong here
raises :class:`EmbedUnavailable`, and recall falls back to the keyword index alone.

A vector travels and is stored as raw little-endian float32 bytes, so this module needs no numpy.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import socket
import struct
import subprocess
import sys
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Literal, Protocol

Role = Literal["query", "document"]


class EmbedUnavailable(RuntimeError):
    """No vector could be made: no worker, no model, a timeout. The caller carries on without."""


def home() -> Path:
    """Where the worker's socket, lock and log live. One per user, shared by every agent."""
    return Path(os.environ.get("BRAIN_EMBED_HOME", "~/.brain-core")).expanduser()


class Embedder(Protocol):
    model: str

    def embed(self, texts: Sequence[str], role: Role = "document") -> list[bytes]: ...

    def running(self) -> bool: ...


def _read_exact(conn: socket.socket, n: int) -> bytes:
    buf = bytearray()
    while len(buf) < n:
        chunk = conn.recv(min(1 << 20, n - len(buf)))
        if not chunk:
            raise EmbedUnavailable("the embed worker closed the connection")
        buf += chunk
    return bytes(buf)


def read_line(conn: socket.socket) -> bytes:
    buf = bytearray()
    while not buf.endswith(b"\n"):
        chunk = conn.recv(1)
        if not chunk:
            break
        buf += chunk
    return bytes(buf)


class WorkerEmbedder:
    """The client side. ``idle_minutes`` is how long the worker stays up after this call."""

    def __init__(
        self,
        model: str,
        idle_minutes: float = 5.0,
        timeout: float = 120.0,
        start_timeout: float = 20.0,
    ) -> None:
        self.model = model
        self.idle_minutes = idle_minutes
        self.timeout = timeout  # a first call loads the model, or downloads it
        self.start_timeout = start_timeout

    def _connect(self) -> socket.socket:
        if not hasattr(socket, "AF_UNIX"):
            raise EmbedUnavailable("the embed worker needs Unix sockets, which this system lacks")
        conn = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            conn.connect(str(home() / "embed.sock"))
        except OSError:
            conn.close()
            raise
        return conn

    def running(self) -> bool:
        try:
            self._connect().close()
        except (OSError, EmbedUnavailable):
            return False
        return True

    def _start(self) -> socket.socket:
        """Start the worker and wait for its socket. Losing the race to another agent is fine:
        the lock lets one worker live, and both callers connect to it."""
        home().mkdir(parents=True, exist_ok=True)
        with (home() / "embed.log").open("ab") as log:
            subprocess.Popen(
                [sys.executable, "-m", "brain_core.embed_worker"],
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=log,
                start_new_session=True,  # it outlives the agent that started it
            )
        deadline = time.monotonic() + self.start_timeout
        while time.monotonic() < deadline:
            try:
                return self._connect()
            except OSError:
                time.sleep(0.05)
        raise EmbedUnavailable(f"the embed worker did not start; see {home() / 'embed.log'}")

    def embed(self, texts: Sequence[str], role: Role = "document") -> list[bytes]:
        if not texts:
            return []
        try:
            try:
                conn = self._connect()
            except OSError:
                conn = self._start()
            with conn:
                conn.settimeout(self.timeout)
                req = {
                    "model": self.model,
                    "role": role,
                    "texts": list(texts),
                    "idle": self.idle_minutes * 60,
                }
                conn.sendall(json.dumps(req).encode() + b"\n")
                head: dict[str, Any] = json.loads(read_line(conn) or b"{}")
                if not head.get("ok"):
                    raise EmbedUnavailable(str(head.get("error", "no reply from the embed worker")))
                size = int(head["dim"]) * 4
                blob = _read_exact(conn, size * len(texts))
        except (OSError, ValueError) as e:
            raise EmbedUnavailable(f"{type(e).__name__}: {e}") from e
        return [blob[i * size : (i + 1) * size] for i in range(len(texts))]


class FakeEmbedder:
    """Deterministic vectors with no model, for tests: texts that share words land close."""

    def __init__(self, model: str = "fake", dim: int = 64) -> None:
        self.model = model
        self.dim = dim
        self.calls = 0

    def running(self) -> bool:
        return True

    def embed(self, texts: Sequence[str], role: Role = "document") -> list[bytes]:
        self.calls += 1
        out = []
        for text in texts:
            v = [0.0] * self.dim
            for word in text.lower().split():
                h = hashlib.sha256(word.strip(".,:;!?()'\"").encode()).digest()
                v[h[0] % self.dim] += 1.0 if h[1] % 2 else -1.0
            norm = math.sqrt(sum(x * x for x in v)) or 1.0
            out.append(struct.pack(f"<{self.dim}f", *(x / norm for x in v)))
        return out
