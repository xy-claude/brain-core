# How brain-core compares

Honest table, as of 12 November 2026 (brain-core 0.5.1), from each project's own README and docs. Corrections welcome by PR.

| | brain-core | claude-mem | mem0 OpenMemory MCP | plain CLAUDE.md |
|---|---|---|---|---|
| Runs | local | local | local (Docker: Qdrant + API + UI) or hosted | local |
| MCP tools | 5 | 4–5 | 3–4 (add, search, list, delete) | none |
| Storage you can open and edit | markdown vault; SQLite is a rebuildable index of it | SQLite + web viewer | Qdrant vectors + Postgres | one markdown file |
| Search | keyword index (SQLite FTS5, bm25) over every record, plus search keys saved with each memory; about 45 ms | SQLite FTS5 plus Chroma vectors | vector search in Qdrant | none: the whole file is loaded |
| How memories get written | the agent calls `brain_remember`, every layer reports its status | hooks capture sessions automatically, AI compresses them | the agent calls `add_memories` | you edit the file |
| Changed facts | `⚠ Fact changed` banner, old line kept and ranked below the new one | new observation | overwritten or added | you edit the file |
| A search that finds nothing good | the reply says `weak_match`; the agent retries and teaches the memory the question | not documented | not documented | n/a |
| Session start/end | one tool call each, cron-written daily brief | automatic context injection | none | none |
| Source capture (URLs, PDFs, repos) | `brain_distill` into an immutable `raw/` folder | no | no | no |
| Scaffolds the agent (rules, skills, hooks) | `brain init`, 32 files | no (plugin only) | no | no |
| Vector search | optional: Hindsight (self-hosted, MIT); can be kept for writes and left out of recall | Chroma | Qdrant | none |
| Works for agents other than Claude Code | yes, Python library + MCP | Claude Code plugin | any MCP client | Claude Code |
| Published eval | a regression set in CI, and 143 hand-labelled questions on a real vault with the misses reported (README) | no | no | no |
| First install | one line; about a minute with `--lite`, about 2 GB more with Hindsight | `/plugin install` inside Claude Code | `make up` with Docker | none |
| License | MIT | MIT | Apache-2.0 | n/a |

Where the others win: claude-mem needs nothing from the agent, it captures by hook, and it has a web viewer and more than a hundred thousand stars of road-testing; brain-core is new and little used. Neither brain-core nor the others has a score on a public memory benchmark run by a neutral party. OpenMemory shares one memory across every MCP client on the machine. CLAUDE.md costs nothing.

Where brain-core wins: the memory is files you own and can edit, every write says which layer took it, a changed value is visible instead of silent, sources are captured before they are summarised, the agent folder comes with rules and hooks, every search result names its file and date, a weak match is reported as weak, and recall is measured against labelled answers, misses included.

Pick claude-mem if you want zero-effort capture inside Claude Code and do not need to read the memory yourself. Pick brain-core if you want to see, grep, and version what the agent remembers, and run the same brain outside Claude Code.

Sources: claude-mem README (github.com/thedotmack/claude-mem), read 2026-11-02 and again 2026-11-12 for its search stack and star count; Mem0 OpenMemory docs (docs.mem0.ai/openmemory), read 2026-11-02. "Not documented" means the project's docs do not say, not that it cannot.
