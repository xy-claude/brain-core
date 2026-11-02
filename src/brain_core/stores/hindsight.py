"""Self-hosted Hindsight adapter over its MCP streamable-HTTP endpoint.

No API key: the server runs on this machine (``hindsight-api``, LaunchAgent). Retain is
asynchronous on the server; ``write`` polls the operation so a failure is reported, never
assumed. Customers run the same server with their own LLM provider key.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from datetime import date
from typing import Any

from brain_core.stores.base import Kind, Record, WriteResult, record_id

CONTEXTS: dict[Kind, str] = {
    "fact": "fact-store",
    "pattern": "session-pattern",
    "decision": "session-decision",
    "correction": "user-feedback",
    "note": "hsam-conversation",
    "raw": "knowledge-distillation",
    "relation": "system-architecture",
    "knowledge": "knowledge-distillation",
}


class HindsightStore:
    name = "hindsight"
    ranked = True  # the server orders by query
    whole = True  # one recall covers every kind; kind comes back in the tags

    def __init__(self, url: str, bank: str, agent: str = "agent", *, timeout: float = 30.0) -> None:
        self.base = url.rstrip("/")
        self.mcp_url = f"{self.base}/mcp/{bank}/"
        self.bank, self.agent, self.timeout = bank, agent.lower(), timeout
        self._session: str | None = None
        self._n = 0

    # ── Store contract ──────────────────────────────────────────────────────

    def read(self, kind: Kind, query: str | None = None, limit: int = 50) -> list[Record]:
        res = self.call("recall", query=query or kind, budget="mid")
        out: list[Record] = []
        for item in res.get("results", []) if isinstance(res, dict) else []:
            tags = item.get("tags") or []
            k = next((t.split(":", 1)[1] for t in tags if t.startswith("type:")), kind)
            when = _date_of(item.get("occurred_start") or item.get("mentioned_at"))
            out.append(
                Record(
                    item.get("id", record_id(item.get("text", ""))),
                    k if k in CONTEXTS else kind,
                    item.get("text", ""),
                    when,
                    next((t.split(":", 1)[1] for t in tags if t.startswith("domain:")), ""),
                    f"hindsight://{self.bank}/{item.get('id', '')}",
                    0,
                    {"context": item.get("context") or "", "fact_type": item.get("fact_type", "")},
                )
            )
        return out[:limit]

    def write(
        self, kind: Kind, text: str, *, domain: str = "", when: date | None = None, **extra: str
    ) -> WriteResult:
        when = when or date.today()
        rid = record_id(text)
        tags = [f"agent:{self.agent}", f"type:{kind}", f"session:{when.isoformat()}"]
        if domain:
            tags.append(f"domain:{domain.lower()}")
        if extra.get("mission"):
            tags.append(f"mission:{extra['mission']}")
        try:
            res = self.call(
                "retain",
                content=text,
                context=extra.get("context", CONTEXTS[kind]),
                tags=tags,
                document_id=extra.get("document_id", f"session-{when.isoformat()}"),
                metadata={
                    "record_id": rid,
                    **{k: v for k, v in extra.items() if k in ("impact", "triggered_by", "source")},
                },
            )
        except (urllib.error.URLError, RuntimeError, TimeoutError) as e:
            return WriteResult(self.name, rid, "failed", str(e)[:200])
        op = res.get("operation_id") if isinstance(res, dict) else None
        if not op:
            return WriteResult(self.name, rid, "written", "synchronous")
        return self._wait(op, rid)

    def health(self) -> tuple[bool, str]:
        try:
            with urllib.request.urlopen(f"{self.base}/health", timeout=5) as r:
                body = json.loads(r.read().decode())
        except (urllib.error.URLError, TimeoutError, ValueError) as e:
            return (False, f"hindsight unreachable at {self.base}: {e}")
        ok = body.get("status") == "healthy"
        return (ok, f"{self.base} bank={self.bank} status={body.get('status')}")

    # ── MCP plumbing ────────────────────────────────────────────────────────

    def _wait(self, op: str, rid: str) -> WriteResult:
        deadline = time.monotonic() + self.timeout
        while time.monotonic() < deadline:
            st = self.call("get_operation", operation_id=op)
            status = st.get("status") if isinstance(st, dict) else None
            if status in ("completed", "succeeded"):
                return WriteResult(self.name, rid, "written", f"op {op}")
            if status in ("failed", "cancelled"):
                return WriteResult(self.name, rid, "failed", f"op {op}: {st.get('error', status)}")
            time.sleep(0.5)
        return WriteResult(
            self.name, rid, "pending", f"op {op} still running after {self.timeout}s"
        )

    def call(self, tool: str, **args: Any) -> Any:
        try:
            return self._call(tool, args)
        except urllib.error.HTTPError as e:
            if e.code not in (400, 404) or self._session is None:
                raise
            self._session = None  # the server restarted and forgot us: initialise again, once
            return self._call(tool, args)

    def _call(self, tool: str, args: dict[str, Any]) -> Any:
        if self._session is None:
            self._post(
                "initialize",
                {
                    "protocolVersion": "2025-03-26",
                    "capabilities": {},
                    "clientInfo": {"name": "brain-core", "version": "0.2"},
                },
            )
            self._post("notifications/initialized", {}, notify=True)
        res = self._post("tools/call", {"name": tool, "arguments": args})
        if res.get("isError"):
            raise RuntimeError(f"{tool}: {res}")
        text = "".join(c.get("text", "") for c in res.get("content", []))
        return json.loads(text) if text.lstrip().startswith(("{", "[")) else text

    def _post(self, method: str, params: dict[str, Any], notify: bool = False) -> dict[str, Any]:
        body: dict[str, Any] = {"jsonrpc": "2.0", "method": method, "params": params}
        if not notify:
            self._n += 1
            body["id"] = self._n
        req = urllib.request.Request(self.mcp_url, data=json.dumps(body).encode(), method="POST")
        req.add_header("Content-Type", "application/json")
        req.add_header("Accept", "application/json, text/event-stream")
        if self._session:
            req.add_header("Mcp-Session-Id", self._session)
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            self._session = resp.headers.get("Mcp-Session-Id", self._session) or "none"
            raw = resp.read().decode()
        if notify or not raw.strip():
            return {}
        if raw.lstrip().startswith("{"):
            msg = json.loads(raw)
        else:  # SSE: last data line carries the result
            data = [ln[5:].strip() for ln in raw.splitlines() if ln.startswith("data:")]
            msg = json.loads(data[-1])
        if "error" in msg:
            raise RuntimeError(f"{method}: {msg['error']}")
        result: dict[str, Any] = msg.get("result", {})
        return result


def _date_of(value: str | None) -> date:
    try:
        return date.fromisoformat((value or "")[:10])
    except ValueError:
        return date.today()
