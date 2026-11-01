---
type: reference
owner: fix
status: active
updated: 2026-11-02
---
# Facts

## System
- Hindsight is self-hosted: LaunchAgent io.vectorize.hindsight runs hindsight-api on 127.0.0.1:8888 with embedded Postgres (2026-11-01)
- The entity graph is a local Kuzu database driven by entity_graph.py; relationships only, no vector search (2026-04-11)
- Always-loaded context is CLAUDE.md plus .claude/rules, measured with wc -c divided by 4; baseline 18.7k tokens (2026-11-02)
- Nightly backup script hindsight_backup.sh runs at 03:30 and keeps 14 archives under ~/Backups/hindsight (2026-11-01)
- Two GitHub accounts are isolated with ssh aliases github-work and github-personal and a pre-push identity guard (2026-11-02)
- Knowledge lint runs nightly via knowledge_tracker.py --lint and writes knowledge_stale.txt for the daily brief (2026-11-02)

## Tools
- defuddle parses a web page to markdown: npx -y defuddle parse <url> --markdown (2026-11-02)
- yt-dlp lives at ~/.local/bin/yt-dlp and writes auto subtitles with --write-auto-sub --sub-lang en (2026-11-02)
- Laya 0.4.20 ships an MCP server laya-mcp-server with 10 tools and a Router that picks the checkpoint by script (2026-11-02)
- gitleaks runs as a pre-commit and pre-push hook; a blocked push means fix the file, never bypass (2026-10-29)

## Projects
- RideApp v1 MVP is ride booking for moto and 3-wheel cars with cash and GCash payment rails (2026-09-18)
- SignalCopy connects one broker terminal per user and copies signals from Telegram channels into MT5 (2026-10-21)
- Northwind is the umbrella client for RideApp, Velo and Blue (2026-08-21)
- The signal parser infers a stop loss when a signal omits it, using the entry and the first take profit (2026-10-15)

## Revenue
- North Star goal G-002 is 30K per month across IB commissions, client delivery and the store (2026-04-12)
- SignalCopy monetises through introducing-broker commissions, not subscriptions (2026-10-20)
