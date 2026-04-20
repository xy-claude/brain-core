# central-brain

Cognitive primitives for AI agents — memory, decisions, reflection — as an installable Python package. Any agent gets a working brain by depending on this library; identity, domain, and state live in the consuming agent.

> **Status:** v0.0.1 chassis. No public API yet. See [milestones](#milestones) for what's landing in v0.1.

---

## Why this exists

Agent projects keep reinventing the same cognition layer — how do I remember things across sessions, how do I log decisions with reasoning, how do I reflect on what worked. `central-brain` extracts that substrate once and versions it, so new agents onboard by declaring a dependency instead of cloning a monorepo.

## Responsibility split

| central-brain owns | Consuming agent owns |
|--------------------|---------------------|
| Memory schema + operations | Identity (`CLAUDE.md`) |
| Decision classification + logging | Domain knowledge |
| Reflection primitives | `brain.yaml` config |
| Storage (SQLite) + migrations | `data/brain.db` (state) |
| MCP server wrapping the API | Any extra MCPs / skills |
| CLI (`init`, `serve`, `doctor`, `export`) | Custom domain logic |

**Invariant:** `central_brain` never imports from a consumer. Consumers import from `central_brain`.

## v0 capabilities (scope — not yet implemented)

1. **Memory** — structured facts/patterns, episodic event log, HSAM daily archives (SQLite + FTS5).
2. **Decisions** — classification (reversible × risk), confidence, reversal tracking.
3. **Reflection** — end-of-session synthesis. Library assembles structured context; runtime (e.g., Claude Code) does LLM synthesis. Zero metered API calls by default.

## Installation (preview)

Once capabilities ship:

```bash
pip install git+ssh://git@github.com/xy-claude/central-brain.git
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

## Milestones

| # | Milestone | Status |
|---|-----------|:------:|
| 0 | Project chassis (tooling, CI, package skeleton) | **in progress** |
| 1 | Storage layer (SQLite schema + migrations) | — |
| 2 | Memory capability | — |
| 3 | Decisions capability | — |
| 4 | Reflection capability | — |
| 5 | Agent class + `brain.yaml` loader | — |
| 6 | CLI (`init`, `doctor`, `export`) | — |
| 7 | MCP server | — |
| 8 | test-agent-1 end-to-end demo | — |

## License

MIT. See `LICENSE`.
