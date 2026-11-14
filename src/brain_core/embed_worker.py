"""The embed worker: one per machine, started by the first agent that needs a vector.

    python -m brain_core.embed_worker

It holds the embedding model so that eight agents do not each hold a copy. It listens on a
socket only the user can open, answers one request at a time, stores nothing, and exits after
the idle time the last caller asked for. A lock file lets only one worker live. Nothing keeps
it running: when it is gone, the next call starts another.

Protocol, one request per connection: a JSON line ``{"model", "role", "texts", "idle"}`` in; a
JSON line ``{"ok": true, "dim": N}`` then N float32 per text out, or ``{"ok": false, "error"}``.
"""

from __future__ import annotations

import contextlib
import json
import os
import socket
import sys
from collections.abc import Sequence
from typing import Any

from brain_core.embed import FakeEmbedder, Role, home, read_line

# shortcut: text past this many tokens is not embedded; raise it if long notes start to matter
MAX_TOKENS = 512


class ModelBackend:
    """sentence-transformers, the reference library. One model in memory at a time."""

    def __init__(self) -> None:
        self.name = ""
        self.model: Any = None

    def embed(self, model: str, texts: Sequence[str], role: Role) -> list[bytes]:
        if model != self.name:
            import torch
            from sentence_transformers import SentenceTransformer

            self.model = None  # free the old one before loading the next
            device = "mps" if torch.backends.mps.is_available() else None
            try:
                # a model already on disk is loaded without asking the hub: a start needs no
                # network, and the weights stay the ones the stored vectors were made with
                self.model = SentenceTransformer(model, device=device, local_files_only=True)
            except Exception:  # not on disk yet, or a library older than the flag: fetch it
                self.model = SentenceTransformer(model, device=device)
            self.model.max_seq_length = MAX_TOKENS
            self.name = model
        # a model that ships a query instruction expects it on questions, never on documents
        prompt = "query" if role == "query" and "query" in (self.model.prompts or {}) else None
        vecs = self.model.encode(
            list(texts),
            prompt_name=prompt,
            batch_size=16,
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        return [v.astype("<f4").tobytes() for v in vecs]


class FakeBackend:
    def embed(self, model: str, texts: Sequence[str], role: Role) -> list[bytes]:
        return FakeEmbedder(model).embed(texts, role)


def serve() -> int:
    import fcntl  # Unix only; the client never starts a worker where sockets are missing

    root = home()
    root.mkdir(parents=True, exist_ok=True)
    lock = (root / "embed.lock").open("a+")  # "w" would wipe the live worker's pid
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return 0  # another worker holds the model; callers reach it through the socket
    lock.truncate(0)
    lock.write(str(os.getpid()))
    lock.flush()
    path = root / "embed.sock"
    with contextlib.suppress(FileNotFoundError):
        path.unlink()  # left by a worker that was killed
    backend: ModelBackend | FakeBackend = (
        FakeBackend() if os.environ.get("BRAIN_EMBED_FAKE") else ModelBackend()
    )
    idle = 300.0
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as srv:
        old = os.umask(0o177)  # the socket is born readable by the user alone
        try:
            srv.bind(str(path))
        finally:
            os.umask(old)
        srv.listen(16)
        try:
            while True:
                srv.settimeout(max(idle, 0.2))
                try:
                    conn, _ = srv.accept()
                except TimeoutError:
                    return 0
                with conn:
                    conn.settimeout(30)
                    try:
                        raw = read_line(conn)
                        if not raw:
                            continue  # a caller that only checked the worker is up
                        req = json.loads(raw)
                        idle = float(req.get("idle", idle))
                        vecs = backend.embed(str(req["model"]), req["texts"], req["role"])
                        dim = len(vecs[0]) // 4 if vecs else 0
                        conn.sendall(json.dumps({"ok": True, "dim": dim}).encode() + b"\n")
                        conn.sendall(b"".join(vecs))
                    except Exception as e:  # a bad request must not take the worker down
                        err = {"ok": False, "error": f"{type(e).__name__}: {str(e)[:300]}"}
                        with contextlib.suppress(OSError):
                            conn.sendall(json.dumps(err).encode() + b"\n")
        finally:
            with contextlib.suppress(FileNotFoundError):
                path.unlink()


if __name__ == "__main__":
    sys.exit(serve())
