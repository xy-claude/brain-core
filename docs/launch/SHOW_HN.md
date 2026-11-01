# Show HN draft

**Title (80 chars max):**
Show HN: brain-core – a local memory for Claude Code agents, five tools, one install

**URL:** https://github.com/xy-claude/brain-core

**Text (first comment, posted by the author right after submitting):**

Every session with a coding agent starts from zero: the project, last week's decision, the thing it got wrong on Tuesday, all explained again. The memory add-ons I tried put my notes in someone's cloud, exposed 20 to 40 tools the agent could not choose between, and none showed an eval.

brain-core is one local MCP server with five tools: `brain_session` (start/end), `brain_recall`, `brain_remember`, `brain_distill`, `brain_status`. Memory is markdown files you can open in Obsidian or grep, plus SQLite with FTS, plus a self-hosted vector store (Hindsight, MIT) that the installer sets up for you. A changed fact gets a "⚠ Fact changed" banner with the old line kept, never deleted. Two cron jobs write the next morning's brief and back everything up.

It installs with one line on macOS or Linux (`curl … | bash -s -- --agent Atlas --user Alex`), or `uv tool install brain-core-mcp`. `brain init` writes the agent folder: CLAUDE.md, rules, skills, a bash guard hook, the vault.

Numbers: the eval runs in CI on a synthetic vault (20/20 recall), and on my own vault with seven months of sessions it scores 20/20 on the tuning set and 10/10 on a held-out set written before running. Recall is about 1.7 s per query; a start block is about 4 s and under 6k tokens. The generic rulebook costs 3k always-loaded tokens.

What it is not: not hosted, not multi-user, no UI beyond Hindsight's. Linux support is two days old. Hindsight is a 2 GB first install, which is the thing I would most like to make optional.

MIT. I built it as the brain for my own assistant and have been dogfooding since day one; happy to answer anything about the design, especially the "five tools, not forty" argument.
