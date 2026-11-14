"""The shared embed worker: one per machine, started on demand, replaced when it dies."""

from __future__ import annotations

import contextlib
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
from collections.abc import Iterator
from pathlib import Path

import pytest

from brain_core.embed import EmbedUnavailable, FakeEmbedder, WorkerEmbedder

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="the worker needs Unix sockets")


@pytest.fixture
def embed_home(monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    # a Unix socket path is capped near 100 bytes, and pytest's tmp_path is longer than that
    root = Path(tempfile.mkdtemp(prefix="be", dir="/tmp"))
    monkeypatch.setenv("BRAIN_EMBED_HOME", str(root))
    monkeypatch.setenv("BRAIN_EMBED_FAKE", "1")
    yield root
    pid = _pid(root)
    if pid:
        with contextlib.suppress(ProcessLookupError):
            os.kill(pid, signal.SIGKILL)
    shutil.rmtree(root, ignore_errors=True)


def _pid(root: Path) -> int:
    try:
        return int((root / "embed.lock").read_text() or 0)
    except (FileNotFoundError, ValueError):
        return 0


def test_worker_starts_on_first_call_and_answers(embed_home: Path) -> None:
    e = WorkerEmbedder("fake", idle_minutes=1)
    assert not e.running()
    vecs = e.embed(["the port is 8888", "something else"], "document")
    assert vecs == FakeEmbedder("fake").embed(["the port is 8888", "something else"])
    assert e.running() and e.embed([]) == []
    assert oct((embed_home / "embed.sock").stat().st_mode & 0o777) == "0o600"


def test_two_agents_at_once_share_one_worker(embed_home: Path) -> None:
    out: list[list[bytes]] = []
    threads = [
        threading.Thread(target=lambda: out.append(WorkerEmbedder("fake", 1).embed(["same text"])))
        for _ in range(4)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(out) == 4 and all(o == out[0] for o in out)
    first = _pid(embed_home)
    # a worker started while one lives gives way at once and leaves the first in place
    extra = subprocess.run([sys.executable, "-m", "brain_core.embed_worker"], timeout=20)
    assert extra.returncode == 0
    assert _pid(embed_home) == first and WorkerEmbedder("fake", 1).running()


def test_killed_worker_is_replaced_by_the_next_call(embed_home: Path) -> None:
    e = WorkerEmbedder("fake", idle_minutes=1)
    e.embed(["one"])
    first = _pid(embed_home)
    os.kill(first, signal.SIGKILL)
    time.sleep(0.2)
    assert e.embed(["one"]) == FakeEmbedder("fake").embed(["one"])
    assert _pid(embed_home) not in (0, first)


def test_worker_exits_when_idle(embed_home: Path) -> None:
    e = WorkerEmbedder("fake", idle_minutes=0)
    e.embed(["one"])
    deadline = time.monotonic() + 5
    # the socket file goes when the worker does (its pid would still answer as a zombie here)
    while (embed_home / "embed.sock").exists() and time.monotonic() < deadline:
        time.sleep(0.1)
    assert not (embed_home / "embed.sock").exists(), "the worker outlived its idle time"
    assert not e.running()


def test_no_worker_means_unavailable_not_a_crash(
    embed_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: None)  # the worker never comes up
    with pytest.raises(EmbedUnavailable):
        WorkerEmbedder("fake", start_timeout=0.3).embed(["one"])
