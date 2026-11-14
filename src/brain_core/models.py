"""Mental models: standing questions answered from the agent's own records, as cited markdown.

``brain models`` reads the records that bear on a question (bm25 hits plus the newest of the
kinds the model names), asks an LLM to answer from those records only, drops every claim that
does not cite one, and writes ``vault/models/<name>.md``. Nothing here is a source: a model is
a briefing, kept out of the search index, and each claim names the line it rests on.

A model is stale when a record it cited changed or went away, when a new record of a kind it
names arrives or a new record of any kind matches its question, or when the question itself
changed. An unrelated write does not touch it.
"""

from __future__ import annotations

import importlib
import json
import os
import re
import shutil
import subprocess
import tempfile
from collections.abc import Callable
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING, Any

from brain_core import recall
from brain_core.config import ModelItem
from brain_core.stores.vault import _SECRET, VaultStore
from brain_core.stores.vault import read_text as _read

if TYPE_CHECKING:
    from brain_core.agent import Agent

Runner = Callable[[str, str], str]  # (system, prompt) -> the model's text

NEW_RECORDS = 1  # one new record that matches the question may contradict a claim: stale
RECORD_CHARS = 600  # of each record shown to the model
BODY_CHARS = 2000  # of each model loaded at session start
API_MODEL = "claude-opus-5-5"
_FALLBACKS = ("claude-fable-5", "claude-opus-5", "claude-sonnet-5-5")  # take `fallbacks`
_CITE = re.compile(r"\[(\d+)\]")
# the files only: a SQLite row is a copy with a source nobody can open, and a row the vault no
# longer holds would read as "a cited record was removed" on the next check
_SEARCHED = ("vault", "notes")

SYSTEM = """You write a short standing briefing for an AI agent from its own memory records.

Rules:
- Use only the numbered records in the message. No outside knowledge, no guesses.
- Answer the question as bullets ("- "), under "## " headings if that helps. At most 250 words.
- End every bullet with the number of each record that supports it, like [3] or [3][17].
  A bullet with no supporting record is not allowed, with one exception: a final bullet that
  starts with "Unknown:" may say what the records do not answer.
- Decisions, corrections and the reasons behind them matter more than activity. Say what the
  records mean for how the agent should act, not a list of what happened.
- When records disagree, the newer date wins; say what changed and cite both. A record marked
  (superseded) is an old value: mention it only as history.
- Write dates as YYYY-MM-DD. Plain words, no preamble, no closing remark."""


class RunnerError(RuntimeError):
    """The LLM call failed or came back unusable. The model file on disk is left as it was."""


# ── runners ───────────────────────────────────────────────────────────────────


def run_claude(system: str, prompt: str, model: str | None = None, timeout: float = 600.0) -> str:
    """The user's own Claude Code login, isolated: no tools, no settings, no hooks, no MCP,
    no saved session, in an empty folder so no CLAUDE.md is read. ``timeout`` in seconds."""
    exe = shutil.which("claude")
    if not exe:
        raise RunnerError("`claude` is not on PATH; install Claude Code, or use models.runner: api")
    cmd = [exe, "-p", "--output-format", "json", "--tools", "", "--setting-sources", ""]
    cmd += ["--strict-mcp-config", "--no-session-persistence", "--disable-slash-commands"]
    cmd += ["--system-prompt", system] + (["--model", model] if model else [])
    # an API key in the environment would outrank the login and bill the API instead
    env = {k: v for k, v in os.environ.items() if k != "ANTHROPIC_API_KEY"}
    with tempfile.TemporaryDirectory() as cwd:
        try:
            p = subprocess.run(
                cmd, input=prompt, capture_output=True, text=True, cwd=cwd, env=env, timeout=timeout
            )
        except subprocess.TimeoutExpired as e:
            raise RunnerError(f"claude did not answer within {timeout:g} seconds") from e
    try:
        out = json.loads(p.stdout)
    except ValueError as e:
        raise RunnerError(f"claude exit {p.returncode}: {(p.stderr or p.stdout)[:200]}") from e
    if out.get("is_error") or not out.get("result"):
        raise RunnerError(f"claude: {str(out.get('result') or out.get('subtype'))[:200]}")
    return str(out["result"])


def run_api(system: str, prompt: str, model: str | None = None, timeout: float = 600.0) -> str:
    """The Anthropic API with the official SDK (optional extra: ``brain-core-mcp[api]``).
    ``timeout`` in seconds, for each attempt: the SDK tries a failed request twice more."""
    try:
        anthropic: Any = importlib.import_module("anthropic")
    except ImportError as e:
        raise RunnerError(
            "models.runner: api needs the Anthropic SDK: "
            "uv tool install --force 'brain-core-mcp[api]' "
            "(or use your Claude Code login with models.runner: claude)"
        ) from e
    model = model or API_MODEL
    extra: dict[str, Any] = {}
    if model.startswith(_FALLBACKS):  # a declined request is re-run on a fallback model
        extra = {"betas": ["server-side-fallback-2026-07-01"], "fallbacks": "default"}
    try:
        r = (
            anthropic.Anthropic()
            .with_options(timeout=timeout)
            .beta.messages.create(
                model=model,
                max_tokens=16000,
                system=system,
                messages=[{"role": "user", "content": prompt}],
                **extra,
            )
        )
    except anthropic.AuthenticationError as e:
        raise RunnerError(
            "no valid Anthropic credential: set ANTHROPIC_API_KEY, or use your Claude Code login "
            "with models.runner: claude"
        ) from e
    except anthropic.RateLimitError as e:
        raise RunnerError("rate limited by the API; the next run will try again") from e
    except anthropic.APIStatusError as e:
        raise RunnerError(f"API error {e.status_code}: {str(e.message)[:160]}") from e
    except anthropic.APITimeoutError as e:  # a kind of connection error: named first
        raise RunnerError(f"the API did not answer within {timeout:g} seconds") from e
    except anthropic.APIConnectionError as e:
        raise RunnerError("could not reach the API") from e
    if r.stop_reason in ("refusal", "max_tokens"):
        raise RunnerError(f"the model stopped early: {r.stop_reason}")
    return "".join(b.text for b in r.content if b.type == "text")


def runner_for(agent: Agent) -> Runner:
    cfg = agent.config.models
    assert cfg is not None
    fn = run_api if cfg.runner == "api" else run_claude
    return lambda system, prompt: fn(system, prompt, cfg.model)


# ── what the model reads ──────────────────────────────────────────────────────


def gather(agent: Agent, item: ModelItem, n: int) -> list[dict[str, str]]:
    """Up to ``n`` records for one question: the best bm25 matches, then the newest records of
    the kinds the model names. Each is ``{id, kind, date, source, text}``."""
    stores = [s for s in agent.stores if s.name in _SEARCHED]
    hits = recall.brain_recall(
        stores, f"{item.question} {item.search}", fmt="detailed", limit=n, max_tokens=25_000
    )["results"]
    out: dict[str, dict[str, str]] = {}
    for h in hits[: n if not item.kinds else n // 2]:
        if _hook(str(h["kind"]), str(h.get("domain", ""))):
            continue
        text = str(h["text"]) + (" (superseded)" if h.get("superseded") else "")
        out[str(h["id"])[:16]] = {
            "kind": str(h["kind"]),
            "date": str(h["date"]) or "undated",  # the writer must not date it by its file
            "source": str(h["source"]),
            "text": text,
        }
    vault = next((s for s in agent.stores if isinstance(s, VaultStore)), None)
    for kind in item.kinds if vault else []:
        for r in vault.read(kind, None, n):  # type: ignore[union-attr,arg-type]
            if len(out) >= n:
                break
            if _hook(r.kind, r.domain):
                continue
            src = f"{r.path}:{r.line}" if r.line else r.path
            when = "undated" if r.undated else r.date.isoformat()
            row = {"kind": r.kind, "date": when, "source": src, "text": r.text}
            out.setdefault(r.id[:16], row)
    # a record that looks like it holds a secret is never sent to a model
    return [{"id": i, **d} for i, d in out.items() if not _SECRET.search(d["text"])]


def _hook(kind: str, section: str) -> bool:
    """What the capture hook filed: the user's raw messages and links. A request is not a
    record of what was done, and a model that reads it lists finished work as pending."""
    return kind == "note" and section.endswith("(hook)")


def _short(source: str) -> str:
    """``facts.md:14``; a notes file outside the vault is named by its file, not its full path."""
    return source.rsplit("/", 1)[-1] if source.startswith(("/", "~")) else source


def _prompt(item: ModelItem, records: list[dict[str, str]]) -> str:
    lines = [
        f"[{i}] ({r['kind']}, {r['date']}, {_short(r['source'])}) "
        f"{' '.join(r['text'].split())[:RECORD_CHARS]}"
        for i, r in enumerate(records, 1)
    ]
    return "Records:\n" + "\n".join(lines) + f"\n\nQuestion: {item.question}"


def check(text: str, records: list[dict[str, str]]) -> tuple[str, list[str], int]:
    """Keep headings and the bullets that cite a real record; turn ``[3]`` into its source.
    Returns the body, the ids it cites, and how many bullets were dropped for citing nothing."""
    body: list[str] = []
    cited: dict[str, None] = {}
    dropped = 0
    for line in text.strip().splitlines():
        if not line.lstrip().startswith("- "):
            if line.startswith("#") or not line.strip():
                body.append(line.rstrip())
            continue  # prose outside bullets carries no citation: left out
        nums = [int(m) for m in _CITE.findall(line)]
        good = [k for k in nums if 1 <= k <= len(records)]
        if line.lstrip().startswith("- Unknown:") and not nums:
            body.append(line.rstrip())
        elif good and len(good) == len(nums):
            for k in good:
                cited[records[k - 1]["id"]] = None
            body.append(
                _CITE.sub(lambda m: f"[{_short(records[int(m[1]) - 1]['source'])}]", line.rstrip())
            )
        else:
            dropped += 1
    return "\n".join(body).strip(), list(cited), dropped


# ── files and staleness ───────────────────────────────────────────────────────


def _file(vault: VaultStore, name: str) -> Path:
    return vault.root / "models" / f"{name}.md"


def _side(agent: Agent, name: str) -> Path:
    return agent.data_dir / "models" / f"{name}.json"


def state(agent: Agent, item: ModelItem, records: list[dict[str, str]] | None = None) -> str:
    """``fresh``, ``missing``, or ``stale: why``."""
    vault = next((s for s in agent.stores if isinstance(s, VaultStore)), None)
    if vault is None or not _file(vault, item.name).exists():
        return "missing"
    try:
        side = json.loads(_read(_side(agent, item.name)))
    except ValueError:
        return "stale: no record of what it was built from"
    if side.get("question") != item.question:
        return "stale: the question changed"
    cfg = agent.config.models
    records = records if records is not None else gather(agent, item, cfg.records if cfg else 150)
    live = {str(r[0])[:16] for r in agent.db.fetchall("SELECT rid FROM records_fts")}
    gone = [c for c in side.get("cited", []) if c not in live]
    if gone:
        return f"stale: {len(gone)} cited record(s) changed or were removed"
    new = [r for r in records if r["id"] not in set(side.get("seen", []))]
    named = [r for r in new if r["kind"] in item.kinds]
    if named:  # one new decision is news for a model about decisions
        return f"stale: {len(named)} new {'/'.join(item.kinds)} record(s)"
    if len(new) >= NEW_RECORDS:
        return f"stale: {len(new)} new record(s) match the question"
    return "fresh"


def refresh(
    agent: Agent,
    names: list[str] | None = None,
    *,
    force: bool = False,
    run: Runner | None = None,
    today: date | None = None,
) -> dict[str, str]:
    """Rewrite the models that are missing or stale (all of them with ``force``). A model whose
    run fails keeps the file it had. Returns one line per model."""
    cfg, today = agent.config.models, today or date.today()
    vault = next((s for s in agent.stores if isinstance(s, VaultStore)), None)
    if cfg is None or vault is None:
        return {"note": "no `models:` in brain.yaml, or no vault"}
    out: dict[str, str] = {}
    for item in cfg.items:
        if names and item.name not in names:
            continue
        records = gather(agent, item, cfg.records)
        was = state(agent, item, records)
        if was == "fresh" and not force:
            out[item.name] = "fresh, left as it is"
            continue
        if not records:
            out[item.name] = "no records match the question yet"
            continue
        try:
            text = (run or runner_for(agent))(SYSTEM, _prompt(item, records))
        except RunnerError as e:
            out[item.name] = f"failed, old file kept: {e}"
            continue
        body, cited, dropped = check(text, records)
        kept = body.count("\n- ") + body.startswith("- ")
        if not cited or dropped > kept:
            out[item.name] = f"rejected, old file kept: {dropped} uncited claim(s), {kept} cited"
            continue
        path = _file(vault, item.name)
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            shutil.copy2(path, path.with_suffix(".prev.md"))  # one generation back, for a diff
        head = (
            f"---\ntype: model\nowner: {vault.owner}\nstatus: active\n"
            f"updated: {today.isoformat()}\nquestion: {json.dumps(item.question)}\n"
            f"records: {len(records)} read, {len(cited)} cited\n---\n"
            f"# {item.name.replace('-', ' ').capitalize()}\n\n"
            "_Written by `brain models` from the records cited. A briefing, not a source: "
            "open the cited line before relying on a claim._\n\n"
        )
        tmp = path.with_suffix(".tmp")
        tmp.write_text(head + body + "\n", encoding="utf-8")
        os.replace(tmp, path)
        side = _side(agent, item.name)
        side.parent.mkdir(parents=True, exist_ok=True)
        seen = [r["id"] for r in records]
        side.write_text(json.dumps({"question": item.question, "cited": cited, "seen": seen}))
        note = f", {dropped} uncited claim(s) dropped" if dropped else ""
        out[item.name] = f"written: {len(records)} records read, {len(cited)} cited{note}"
    return out


def status(agent: Agent) -> dict[str, str]:
    cfg = agent.config.models
    return {i.name: state(agent, i) for i in cfg.items} if cfg else {}


def load(agent: Agent) -> dict[str, str]:
    """What ``brain_session('start')`` hands the agent: each model's text with its state first."""
    cfg = agent.config.models
    vault = next((s for s in agent.stores if isinstance(s, VaultStore)), None)
    if cfg is None or vault is None:
        return {}
    out: dict[str, str] = {}
    for item in cfg.items:
        st = state(agent, item)
        if st == "missing":
            out[item.name] = "not written yet: run `brain models`"
            continue
        text = _read(_file(vault, item.name))
        body = text.split("\n---\n", 1)[-1].split("\n\n", 2)[-1].strip()
        cut = (
            f"\n…(cut at {BODY_CHARS} of {len(body)} characters; the rest is in "
            f"models/{item.name}.md)"
            if len(body) > BODY_CHARS
            else ""
        )
        out[item.name] = f"({st})\n{body[:BODY_CHARS]}{cut}"
    return out
