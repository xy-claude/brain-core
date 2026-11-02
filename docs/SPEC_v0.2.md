# brain-core v0.2 — the local brain MCP

**Status:** approved 2026-11-02; M9–M19 shipped the same week.
**Goal:** one local MCP that is the whole front door to an agent's memory, dogfooded on the reference agent (the author's own assistant) until it runs every session, then packaged the way Hindsight was self-hosted: local, no bill, no login.
**Design constraints:** Anthropic, "Writing effective tools for AI agents" (2025-09). Few consolidated workflow tools, namespaced, concise by default, capped responses with steering text, names not UUIDs, descriptions written for a newcomer, an eval before v1.

## 1. What v0.1 has and what is wrong with it

v0.1 (milestones 0–8, 155 tests) exposes 14 MCP tools that mirror the Python API one-to-one: `remember`, `recall`, `supersede`, `log_event`, `recent_events`, `append_today`, `decide`, `reverse`, `complete`, `list_decisions`, `gather_context`, `save_reflection`, `template_summary`, `current_session`. Storage is SQLite + FTS5 only. It knows nothing about the three stores a real agent already has (markdown vault, Hindsight, entity graph), so the reference agent could not use it without duplicating memory.

That is the "wrap every endpoint" shape. An agent facing 14 brain tools plus 15 Obsidian tools plus 36 Hindsight tools picks the wrong one, or picks three and merges by hand.

## 2. The five tools (the only MCP surface in v0.2)

Namespace `brain_`. The 14 v0.1 tools stay as the Python API; the MCP stops exposing them.

| Tool | Does | Replaces |
|---|---|---|
| `brain_recall(query, scope="all", format="concise", limit=10)` | One query across structured facts (SQLite/FTS5), Hindsight (HTTP), vault markdown (ripgrep over `agents/<NAME>/`), entity graph. Dedups by content hash, ranks by recency × relevance, returns `name`, `kind`, `date`, `source_path`, `text`. `detailed` adds ids and raw scores for chained calls. | Hindsight `recall`, Obsidian `search_notes`, `entity_graph.py search` |
| `brain_remember(text, kind, source, tags=[], mission=None)` | Write-through in fixed order: vault file (facts/decisions/patterns/daily by `kind`) → SQLite → Hindsight retain → graph edge if `kind=relation`. Dedup (hash + fuzzy) and contradiction check inside. Returns per-layer status; never silent on a failed layer. | `write_note`/`patch_note`, Hindsight `retain`, `entity_graph.py add`, the dedup and contradiction rules agents must remember to run |
| `brain_session(phase, session_id=None)` | `start`: returns one concise block — daily brief, executive state summary, 2 mental models, recall of active missions, inbox count, auto-recovery flag. `end`: runs the 6-step close (queue drain, HSAM finalise, missions, critique stub, cross-agent sync, recovery marker) from the agent's writes this session and returns what it wrote. | 4-step START (~10 tool calls) and 6-step END (~12 calls) protocols in `AGENTS/CLAUDE.md` |
| `brain_distill(source, agent=None)` | Capture half of `/distill`: URL / path / text → immutable `raw/YYYY-MM-DD-<slug>.md` with url/author/published/sha256, dedup on `source:` line or hash. Returns the raw path and metadata. The agent still compiles the page (that is LLM work, not tool work). | Step 1 of the `/distill` skill |
| `brain_status()` | Health in one call: MCP backends reachable (Hindsight, vault path, DB), knowledge lint counts, always-loaded context tokens, last session close marker, pending decisions count. | `/agent-check`, `knowledge_tracker.py --lint`, the brain-report health table |

Every response is capped (default 6k tokens, hard max 25k) and, when truncated, ends with a steering line ("narrow `scope` or raise `limit`"). Errors say what to change ("`kind` must be one of fact|decision|pattern|relation|note"). Identifiers are names and paths; numeric ids only in `format="detailed"`.

## 3. Backends and config

`brain.yaml` gains an optional `stores:` block. Absent stores are skipped, never faked.

```yaml
name: ATLAS
stores:
  sqlite: data/brain.db                      # always on (v0.1)
  vault: ./vault                             # markdown folder; files by kind
  hindsight:
    url: http://127.0.0.1:8888               # self-hosted; MCP path /mcp/<bank>/
    bank: atlas-brain
  graph:
    script: ~/Agents/scripts/entity_graph.py   # legacy Kuzu graph via its CLI
    python: ~/Agents/venv/bin/python3
```

Hindsight is talked to over its MCP streamable-HTTP endpoint (a small client that does initialize → tools/call). No vectorize.io, no token. Customers install `hindsight-api` with their own Anthropic key for the LLM provider; the `claude-code` provider is personal-use only under Anthropic's terms and is not part of the install story.

## 4. Eval before v1

`tests/eval/` with 30 tasks pulled from the reference agent's session archives, each a prompt, the expected recall hits (by `source_path`), and the expected writes. A verifier that tolerates phrasing. Metrics per task: hits, tool calls, tokens returned, errors. Run on a held-out 10 after tuning on 20. Nothing ships to v1 below 90% on the held-out set.

## 5. Dogfood plan (the proof)

1. Both MCPs loaded in the reference agent's `.mcp.json` for two weeks (`brain` beside `obsidian-vault` and `hindsight`). Schemas are deferred, so the context cost is near zero.
2. The reference agent uses only `brain_*` for memory; the old tools stay as fallback. A fact written through `brain_remember` must appear in the vault file, the SQLite row, and Hindsight, and `brain_status` must say so.
3. After a month of clean logs: `obsidian-vault` leaves the reference agent's `.mcp.json`; its sibling agents follow one at a time.
4. Then package: `uv tool install brain-core`, `brain-core init` writes `brain.yaml` and registers the MCP, `brain-core doctor` is `brain_status` from the shell.

## 6. Milestones

| # | Milestone | Done when |
|---|---|---|
| 9 | Store adapters: vault (markdown by kind), Hindsight (MCP HTTP client), graph (subprocess) | unit tests per adapter with a fake backend; `brain_status` reports each |
| 10 | `brain_recall` merged + dedup + caps + concise/detailed | 20 eval tasks ≥ 90% hits |
| 11 | `brain_remember` write-through with per-layer status, dedup, contradiction banner | a failed layer is reported, never swallowed; test with Hindsight down |
| 12 | `brain_session` start/end | one call reproduces today's START block and END writes on a real session of the reference agent |
| 13 | `brain_distill` capture + `brain_status` | `/distill` Step 1 calls it; `/agent-check` calls `brain_status` |
| 14 | Eval set complete, held-out ≥ 90% | `tests/eval/` in CI |
| 15 | Dogfood: 2 weeks side-by-side, then Obsidian MCP removed from the reference agent | `.mcp.json` diff + a month of `brain_status` logs |

Not in v0.2: multi-agent mesh, hosted mode, UI, knowledge compile (stays an LLM skill), anything that adds a server beyond Hindsight.

## 7. Lean guard

v0.2 must *reduce* the reference agent's tool surface (51 → 5 for memory) and leave always-loaded context unchanged (18.7k tokens on 2026-11-02; protocol text in `AGENTS/CLAUDE.md` shrinks once `brain_session` carries it). Any milestone that grows either number stops and reports.
