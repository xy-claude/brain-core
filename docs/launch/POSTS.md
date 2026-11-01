# Launch posts (drafts; posted by the author from their own accounts)

## r/ClaudeAI

**Title:** I gave my Claude Code agent a memory that survives sessions: one local MCP, five tools, markdown you own (MIT)

Tired of re-explaining the project every session, I built brain-core: a local MCP server with five tools (`brain_session`, `brain_recall`, `brain_remember`, `brain_distill`, `brain_status`). Memory is markdown files plus SQLite plus a self-hosted vector store; a changed fact gets a "⚠ Fact changed" banner and the old line stays. One-line install on macOS/Linux, `brain init` writes the whole agent folder (CLAUDE.md, rules, skills, hooks). Eval runs in CI; on my own 7-month vault it recalls 10/10 on a held-out set.

GIF of a real session in the README. Repo: https://github.com/xy-claude/brain-core

Honest limits: Hindsight (the vector store) is a 2 GB install; Linux path is new. Feedback on the "five tools instead of forty" design is what I want most.

## r/LocalLLaMA

**Title:** brain-core: local, file-based memory for coding agents with a published eval (no cloud, MIT)

Same body as above, with the first sentence swapped for: "Everything stays on your machine: markdown vault, SQLite, embedded Postgres + CPU embeddings via the MIT Hindsight server."

## X / Twitter (thread, 3 posts)

1/ Your coding agent forgets everything between sessions. I built brain-core to fix that: one local MCP, five tools, memory as markdown you can grep. One-line install. MIT.
[GIF]
https://github.com/xy-claude/brain-core

2/ Why five tools, not forty: an agent facing 40 endpoints picks the wrong one or three. brain_recall is one query across every store, deduplicated, capped at 6k tokens. brain_remember writes vault → SQLite → vector store and reports each layer, so a dead store is never silent.

3/ It is tested like software: eval in CI, 10/10 on a held-out set from my own 7 months of sessions. Changed facts keep the old line with a ⚠ banner. Nothing is ever deleted. Issues and PRs welcome.

## Anthropic Discord (#showcase or #mcp)

brain-core: a memory MCP for Claude Code. Five tools, local only, markdown vault, eval in CI, one-line install. Would love feedback from people running long-lived agents: https://github.com/xy-claude/brain-core

## Awesome-list PR lines

- awesome-mcp-servers (Memory section): `- [xy-claude/brain-core](https://github.com/xy-claude/brain-core) 🐍 🏠 🍎 🐧 - Five-tool memory for coding agents: markdown vault, SQLite FTS, self-hosted vector store, eval in CI, one-line install.`
- awesome-claude-code (Tooling / MCP): `- [brain-core](https://github.com/xy-claude/brain-core) — Local memory that survives sessions: brain_session/recall/remember/distill/status, markdown you own, cron-written daily brief.`

## MCP registry entry (server.json fields)

- name: `io.github.xy-claude/brain-core`
- description: Local memory for Claude Code agents: five tools over a markdown vault, SQLite and a self-hosted vector store.
- packages: pypi `brain-core-mcp`, command `brain serve <agent-dir>`
