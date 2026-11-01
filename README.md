# brain-core

Cognitive primitives for AI agents — memory, decisions, reflection — as an installable Python package. Any agent gets a working brain by depending on this library; identity, domain, and state live in the consuming agent.

> **Status:** v0.1 library + 14-tool MCP (M0–8). v0.2 in progress: five `brain_*` tools over the agent's real stores — see [`docs/SPEC_v0.2.md`](docs/SPEC_v0.2.md) and [milestones](#milestones).

---

## Why this exists

Agent projects keep reinventing the same cognition layer — how do I remember things across sessions, how do I log decisions with reasoning, how do I reflect on what worked. `brain-core` extracts that substrate once and versions it, so new agents onboard by declaring a dependency instead of cloning a monorepo.

## Responsibility split

| brain-core owns | Consuming agent owns |
|--------------------|---------------------|
| Memory schema + operations | Identity (`CLAUDE.md`) |
| Decision classification + logging | Domain knowledge |
| Reflection primitives | `brain.yaml` config |
| Storage (SQLite) + migrations | `data/brain.db` (state) |
| MCP server wrapping the API | Any extra MCPs / skills |
| CLI (`init`, `serve`, `doctor`, `export`) | Custom domain logic |

**Invariant:** `brain_core` never imports from a consumer. Consumers import from `brain_core`.

## v0 capabilities (scope — not yet implemented)

1. **Memory** — structured facts/patterns, episodic event log, HSAM daily archives (SQLite + FTS5).
2. **Decisions** — classification (reversible × risk), confidence, reversal tracking.
3. **Reflection** — end-of-session synthesis. Library assembles structured context; runtime (e.g., Claude Code) does LLM synthesis. Zero metered API calls by default.

## Installation (preview)

Once capabilities ship:

```bash
pip install git+ssh://git@github.com/xy-claude/brain-core.git
```

During development:

```bash
uv sync --all-extras
```

## Development

```bash
uv sync --all-extras          # install deps into .venv
uv run ruff check src tests   # lint
uv run ruff format src tests  # format
uv run mypy                   # type-check (strict)
uv run pytest --cov           # tests with coverage
```

Pre-commit hooks available via `pre-commit install`.

## Security posture

brain-core is RAG-shaped (memory + retrieval + LLM reasoning). That shape has a documented attack surface — see [`docs/THREAT_MODEL.md`](docs/THREAT_MODEL.md) for the PoisonedRAG threat class, the ingestion-time gates the library provides, and the questions consumers must answer before shipping.

## Milestones

| # | Milestone | Status |
|---|-----------|:------:|
| 0 | Project chassis (tooling, CI, package skeleton) | ✅ |
| 1 | Storage layer (SQLite schema + migrations) | ✅ |
| 2 | Memory capability (structured + episodic + HSAM) | ✅ |
| 3 | Decisions capability | ✅ |
| 4 | Reflection capability | ✅ |
| 5 | Agent class + `brain.yaml` loader | ✅ |
| 6 | CLI (`init`, `doctor`, `export`) | ✅ |
| 7 | MCP server | ✅ |
| 8 | test-agent-1 end-to-end demo | ✅ |
| 9 | v0.2 store adapters: vault (markdown by kind), Hindsight (MCP HTTP), graph (CLI) — `docs/VAULT_SCHEMA.md` | ✅ |
| 10 | `brain_recall` merged across stores, concise/detailed, caps — 20/20 eval hits, ~1.7 s per query | ✅ |
| 11 | `brain_remember` write-through vault → sqlite → Hindsight → graph, per-layer status, dedup, `⚠ Fact changed` banner | ✅ |
| 12 | `brain_session` start/end | ⬜ |
| 13 | `brain_distill` capture + `brain_status` | ⬜ |
| 14 | Eval set (30 tasks), held-out ≥ 90% | ⬜ |
| 15 | Dogfood on XYCLAUDE, Obsidian MCP retired | ⬜ |

## License

MIT. See `LICENSE`.
