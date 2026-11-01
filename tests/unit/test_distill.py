"""brain_distill capture: text, local file, URL paths (network stubbed), dedup, thin pages."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from brain_core import Agent
from brain_core import distill as d


def make(tmp_path: Path) -> Agent:
    vault = tmp_path / "vault"
    vault.mkdir()
    cfg = tmp_path / "brain.yaml"
    cfg.write_text(textwrap.dedent(f"name: T\nstores:\n  vault: {vault}\n"))
    return Agent.from_config(cfg)


def test_text_and_file_capture_with_dedup(tmp_path: Path) -> None:
    with make(tmp_path) as a:
        out = a.brain_distill("Ada's pasted notes", text="alpha beta " * 150, author="Ada")
        assert out["status"] == "written" and out["path"].startswith("raw/") and out["words"] == 300
        raw = tmp_path / "vault" / out["path"]
        head = raw.read_text().split("---")[1]
        assert (
            "source: Ada's pasted notes" in head
            and "author: Ada" in head
            and "compiled_into: []" in head
        )
        again = a.brain_distill("Ada's pasted notes", text="alpha beta " * 150)
        assert again["status"] == "exists" and "already captured" in again["note"]
        f = tmp_path / "paper.md"
        f.write_text("# Paper\n\nshort body")
        out = a.brain_distill(str(f))
        assert out["status"] == "written" and out["title"] == "paper" and "words" in out["note"]
        with pytest.raises(ValueError, match="no such file"):
            a.brain_distill(str(tmp_path / "nope.md"))


def test_web_capture_uses_defuddle_then_stdlib(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(d, "_defuddle", lambda url: ("", {}))
    html = (
        "<html><head><title>Tools &amp; Agents</title>"
        '<meta name="author" content="Anthropic">'
        '<meta property="article:published_time" content="2025-09-11T00:00:00Z">'
        "</head><body><nav>skip me</nav><p>"
        + "word " * 250
        + "</p><script>x()</script></body></html>"
    )
    monkeypatch.setattr(d, "_http", lambda url, timeout=30: html)
    with make(tmp_path) as a:
        out = a.brain_distill("https://example.com/post")
        assert out["status"] == "written"
        assert (
            out["title"] == "Tools & Agents"
            and out["author"] == "Anthropic"
            and out["published"] == "2025-09-11"
        )
        body = (tmp_path / "vault" / out["path"]).read_text()
        assert "skip me" not in body and "x()" not in body and out["words"] >= 250
        assert out["note"].startswith("defuddle unavailable")


def test_github_and_youtube_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_http(url: str, timeout: float = 30) -> str:
        if "raw.githubusercontent" in url:
            return "# laya\n\n" + "readme " * 210
        return (
            '{"stargazers_count": 34800, "license": {"spdx_id": "Apache-2.0"},'
            ' "pushed_at": "2026-11-01T10:00:00Z"}'
        )

    monkeypatch.setattr(d, "_http", fake_http)
    monkeypatch.setattr("brain_core.distill.shutil.which", lambda name: None)
    with make(tmp_path) as a:
        out = a.brain_distill("https://github.com/NandhaKishorM/laya")
        assert out["status"] == "written" and out["title"] == "NandhaKishorM/laya README"
        assert out["published"] == "2026-11-01"
        assert (
            "stars: 34800 · license: Apache-2.0" in (tmp_path / "vault" / out["path"]).read_text()
        )
        yt = a.brain_distill("https://youtu.be/dQw4w9WgXcQ")
        assert yt["status"] == "failed" and "yt-dlp" in yt["note"]


def test_pdf_bytes_are_saved_next_to_a_stub(tmp_path: Path) -> None:
    pdf = tmp_path / "spec.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake")
    with make(tmp_path) as a:
        out = a.brain_distill(str(pdf))
        assert out["status"] == "written" and "PDF bytes saved" in out["note"]
        assert any(p.suffix == ".pdf" for p in (tmp_path / "vault" / "raw").iterdir())
