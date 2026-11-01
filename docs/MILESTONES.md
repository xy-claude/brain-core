# Milestones

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
| 12 | `brain_session` start (brief, executive state, mental models, mission recall, inbox, recovery) / end (queue drain, HSAM close, critique, sync, marker) | ✅ |
| 13 | `brain_distill` capture (web/GitHub/YouTube/PDF/file/text → raw/) + `brain_status`; MCP surface is now the five `brain_*` tools only | ✅ |
| 14 | Eval set: 20 tune + 10 held-out recall (live 100% / 100%), 10 write scenarios, 20-task fixture vault in CI | ✅ |
| 15 | Dogfood on the reference agent, Obsidian MCP retired | ⬜ (started 2026-11-02) |
| 16 | Template pack: `brain init NAME --user --profile DIR` writes CLAUDE.md, 5 generic rules, 3 skills, bash guard hook, `.mcp.json`, vault skeleton | ✅ |
| 17 | Entity graph moved from Kuzu into a `relations` table in brain.db; `brain graph import` loads the legacy dump | ✅ |
| 18 | Cron engine: `brain daily` (brief, health line, Hindsight backup), `brain weekly` (archive sessions > 30d, refresh mental models), `brain cron install` (launchd) | ✅ |
| 19 | Installer: `install.sh` one-liner, `brain hindsight install` (launchd service, claude-code or customer provider), `brain doctor` on `brain_status` | ✅ (export/import lands after M17) |
