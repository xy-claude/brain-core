# How brain-core compares

Honest table, as of November 2026, from each project's own README and docs. Corrections welcome by PR.

| | brain-core | claude-mem | mem0 OpenMemory MCP | plain CLAUDE.md |
|---|---|---|---|---|
| Runs | local | local | local (Docker: Qdrant + API + UI) or hosted | local |
| MCP tools | 5 | 4–5 | 3–4 (add, search, list, delete) | none |
| Storage you can open and edit | markdown vault + SQLite | SQLite + web viewer | Qdrant vectors + Postgres | one markdown file |
| How memories get written | the agent calls `brain_remember`, every layer reports its status | hooks capture sessions automatically, AI compresses them | the agent calls `add_memories` | you edit the file |
| Changed facts | `⚠ Fact changed` banner, old line kept | new observation | overwritten or added | you edit the file |
| Session start/end | one tool call each, cron-written daily brief | automatic context injection | none | none |
| Source capture (URLs, PDFs, repos) | `brain_distill` into an immutable `raw/` folder | no | no | no |
| Scaffolds the agent (rules, skills, hooks) | `brain init`, 31 files | no (plugin only) | no | no |
| Vector search | Hindsight (self-hosted, MIT), required | none built in | Qdrant | none |
| Works for agents other than Claude Code | yes, Python library + MCP | Claude Code plugin | any MCP client | Claude Code |
| Published eval | yes, in CI, held-out numbers in README | no | no | no |
| First install | one line; ~2 GB for Hindsight | `/plugin install` inside Claude Code | `make up` with Docker | none |
| License | MIT | MIT | Apache-2.0 | n/a |

Where the others win: claude-mem needs nothing from the agent, it captures by hook, and it has a web viewer and seventy thousand stars of road-testing. OpenMemory shares one memory across every MCP client on the machine. CLAUDE.md costs nothing.

Where brain-core wins: the memory is files you own and can edit, every write says which layer took it, a changed value is visible instead of silent, sources are captured before they are summarised, the agent folder comes with rules and hooks, and the recall is measured.

Pick claude-mem if you want zero-effort capture inside Claude Code and do not need to read the memory yourself. Pick brain-core if you want to see, grep, and version what the agent remembers, and run the same brain outside Claude Code.

Sources: claude-mem README (github.com/thedotmack/claude-mem), Mem0 OpenMemory docs (docs.mem0.ai/openmemory), both read 2026-11-02.
