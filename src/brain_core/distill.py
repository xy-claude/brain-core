"""``brain_distill``: the capture half of ``/distill``.

URL, local file or pasted text → one immutable ``raw/YYYY-MM-DD-<slug>.md`` in the vault with
source, title, author, published, sha256 and word count in the frontmatter. Dedup on the
``source:`` line or the body hash happens in :class:`VaultStore`. Compiling the knowledge page
is LLM work and stays in the skill.
"""

from __future__ import annotations

import html
import json
import re
import shutil
import subprocess
import tempfile
import urllib.error
import urllib.request
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING, Any

from brain_core.stores.vault import VaultStore

if TYPE_CHECKING:
    from brain_core.agent import Agent

MIN_WORDS = 200  # below this a web capture is suspect (JS page, paywall)
_GITHUB = re.compile(r"^https?://github\.com/([^/]+)/([^/#?]+)/?$")
_YOUTUBE = re.compile(r"^https?://(?:www\.)?(?:youtube\.com/watch\?v=|youtu\.be/)([\w-]+)")
_TAG = re.compile(r"<[^>]+>")
_DROP = re.compile(r"<(script|style|nav|footer|header|noscript)[^>]*>.*?</\1>", re.S | re.I)
_TITLE = re.compile(r"<title[^>]*>(.*?)</title>", re.S | re.I)
_META = r'<meta[^>]+(?:name|property)=["\'](?:{})["\'][^>]+content=["\']([^"\']+)'
_AUTHOR = re.compile(_META.format("author|article:author"), re.I)
_DATE = re.compile(_META.format("article:published_time|date|datePublished"), re.I)
_VTT_TS = re.compile(r"^\d\d:\d\d:\d\d\.\d{3} --> .*$|^WEBVTT.*$|^\d+$|^NOTE.*$", re.M)
_VTT_TAGS = re.compile(r"<[^>]+>")


def brain_distill(
    agent: Agent,
    source: str,
    *,
    text: str | None = None,
    title: str | None = None,
    author: str | None = None,
    published: str | None = None,
) -> dict[str, Any]:
    vault = next((s for s in agent.stores if isinstance(s, VaultStore)), None)
    if vault is None:
        raise ValueError("brain_distill needs stores.vault in brain.yaml")
    source = source.strip()
    if not source:
        raise ValueError("source must be a URL, a file path, or a name for pasted text")
    meta: dict[str, str] = {
        "source": source,
        "title": title or "",
        "author": author or "",
        "published": published or "",
    }
    note = ""
    if text is not None:
        body = text
        meta["title"] = meta["title"] or source
    elif source.startswith(("http://", "https://")):
        body, got, note = _capture_url(source)
        meta = {**got, **{k: v for k, v in meta.items() if v}}
    else:
        path = Path(source).expanduser()
        if not path.exists():
            raise ValueError(f"no such file: {path}")
        if path.suffix.lower() == ".pdf":
            body, note = _pdf_stub(vault, path.read_bytes(), path.stem)
        else:
            body = path.read_text(encoding="utf-8", errors="replace")
        meta["title"] = meta["title"] or path.stem
    meta.setdefault("title", "")
    meta["title"] = meta["title"] or source[:80]
    body = body.strip()
    if not body:
        return {"status": "failed", "source": source, "note": note or "capture returned no text"}
    r = vault.write("raw", body, when=date.today(), **{k: v for k, v in meta.items() if v})
    out: dict[str, Any] = {
        "status": r.status,
        "path": r.detail,
        "sha256": r.id,
        "words": len(body.split()),
        **{k: meta.get(k, "") for k in ("source", "title", "author", "published")},
    }
    if r.status == "exists":
        out["note"] = "already captured (same source or same sha256); use the existing raw file"
    elif note:
        out["note"] = note
    elif out["words"] < MIN_WORDS and text is None:
        out["note"] = (
            f"only {out['words']} words; JS or paywalled page? "
            "capture it in the browser and pass text="
        )
    return out


# ── capture paths ─────────────────────────────────────────────────────────────


def _capture_url(url: str) -> tuple[str, dict[str, str], str]:
    if m := _GITHUB.match(url):
        return _github(m.group(1), m.group(2).removesuffix(".git"))
    if m := _YOUTUBE.match(url):
        return _youtube(url, m.group(1))
    if url.lower().split("?")[0].endswith(".pdf"):
        return (
            "",
            {"source": url, "title": url.rsplit("/", 1)[-1]},
            "PDF URL: download it and pass the file path",
        )
    body, meta = _defuddle(url)
    if body and len(body.split()) >= MIN_WORDS:
        return body, {"source": url, **meta}, ""
    raw = _http(url)
    meta2 = {
        "title": _first(_TITLE, raw),
        "author": _first(_AUTHOR, raw),
        "published": _first(_DATE, raw)[:10],
    }
    text = html.unescape(_TAG.sub(" ", _DROP.sub(" ", raw)))
    text = re.sub(r"[ \t]+", " ", re.sub(r"\n\s*\n+", "\n\n", text)).strip()
    if body and len(body.split()) >= len(text.split()):
        return body, {"source": url, **meta}, ""
    return (
        text,
        {"source": url, **{k: v for k, v in meta2.items() if v}},
        "defuddle unavailable or thin; stdlib fallback",
    )


def _defuddle(url: str) -> tuple[str, dict[str, str]]:
    if not shutil.which("npx"):
        return "", {}
    try:
        md = subprocess.run(
            ["npx", "-y", "defuddle", "parse", url, "--markdown"],
            capture_output=True,
            text=True,
            timeout=90,
        )
        if md.returncode != 0:
            return "", {}
        js = subprocess.run(
            ["npx", "-y", "defuddle", "parse", url, "--json"],
            capture_output=True,
            text=True,
            timeout=90,
        )
    except (subprocess.TimeoutExpired, OSError):
        return "", {}
    meta: dict[str, str] = {}
    try:
        j = json.loads(js.stdout) if js.returncode == 0 else {}
        meta = {k: str(j.get(k) or "") for k in ("title", "author", "published")}
        meta["published"] = meta["published"][:10]  # defuddle gives a full ISO stamp
    except ValueError:
        pass
    return md.stdout, {k: v for k, v in meta.items() if v}


def _github(owner: str, repo: str) -> tuple[str, dict[str, str], str]:
    readme = ""
    for branch in ("HEAD", "main", "master"):
        try:
            readme = _http(f"https://raw.githubusercontent.com/{owner}/{repo}/{branch}/README.md")
            break
        except urllib.error.URLError:
            continue
    meta = {
        "source": f"https://github.com/{owner}/{repo}",
        "title": f"{owner}/{repo} README",
        "author": owner,
    }
    note = ""
    try:
        info = json.loads(_http(f"https://api.github.com/repos/{owner}/{repo}"))
        meta["published"] = str(info.get("pushed_at", ""))[:10]
        lic = (info.get("license") or {}).get("spdx_id", "")
        readme = (
            f"<!-- stars: {info.get('stargazers_count')} · license: {lic} · "
            f"pushed: {meta['published']} -->\n\n" + readme
        )
    except (urllib.error.URLError, ValueError):
        note = "GitHub API unavailable; README captured without stars/license"
    return readme, meta, note


def _youtube(url: str, vid: str) -> tuple[str, dict[str, str], str]:
    if not shutil.which("yt-dlp"):
        return (
            "",
            {"source": url, "title": f"youtube {vid}"},
            "yt-dlp not on PATH; install it or pass text=",
        )
    with tempfile.TemporaryDirectory() as tmp:
        try:
            info = subprocess.run(
                [
                    "yt-dlp",
                    "--skip-download",
                    "--write-auto-sub",
                    "--sub-lang",
                    "en",
                    "--sub-format",
                    "vtt",
                    "--print",
                    "%(title)s\t%(uploader)s\t%(upload_date)s",
                    "-o",
                    f"{tmp}/%(id)s",
                    url,
                ],
                capture_output=True,
                text=True,
                timeout=180,
            )
        except (subprocess.TimeoutExpired, OSError) as e:
            return "", {"source": url, "title": f"youtube {vid}"}, f"yt-dlp failed: {e}"
        title, uploader, upd = [*info.stdout.strip().split("\t"), "", "", ""][:3]
        subs = sorted(Path(tmp).glob("*.vtt"))
        body = ""
        if subs:
            raw = _VTT_TAGS.sub(
                "", _VTT_TS.sub("", subs[0].read_text(encoding="utf-8", errors="replace"))
            )
            lines, seen = [], ""
            for ln in (x.strip() for x in raw.splitlines()):
                if ln and ln != seen:
                    lines.append(ln)
                    seen = ln
            body = "\n".join(lines)
    published = f"{upd[:4]}-{upd[4:6]}-{upd[6:8]}" if len(upd) == 8 else ""
    meta = {
        "source": url,
        "title": title or f"youtube {vid}",
        "author": uploader,
        "published": published,
    }
    return body, meta, "" if body else "no English subtitles found"


def _pdf_stub(vault: VaultStore, data: bytes, stem: str) -> tuple[str, str]:
    slug = re.sub(r"[^a-z0-9]+", "-", stem.lower()).strip("-")[:60]
    dest = vault.root / "raw" / f"{date.today().isoformat()}-{slug}.pdf"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)
    rel = dest.relative_to(vault.root)
    return (
        f"PDF saved at {rel} ({len(data)} bytes). Compile from the PDF with Read.",
        f"PDF bytes saved to {rel}; text extraction is the agent's job (Read)",
    )


def _http(url: str, timeout: float = 30) -> str:
    req = urllib.request.Request(
        url, headers={"User-Agent": "brain-core/0.2 (+https://github.com/xy-claude/brain-core)"}
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return str(r.read().decode("utf-8", errors="replace"))


def _first(rx: re.Pattern[str], s: str) -> str:
    m = rx.search(s)
    return html.unescape(m.group(1)).strip() if m else ""
