# brain-core: knowledge architecture audit and blueprint

**Date:** 2026-11-21. **Revision:** 2, the second architectural review, written the same day. **Audited at:** commit `55038ca` (release 0.9.1), branch `claude/brain-core-architecture-audit-adfc3b`.
**Status:** this is a proposal. Neither revision changed any source, configuration, dependency or database, and no migration was run. The only code written is two throwaway prototypes in the session scratchpad, outside the repository (H.3, J.1, F.3).

Every statement carries a label:

| Label | Meaning |
|---|---|
| **[V]** | Verified in this repository: a file and line, or a command that was run |
| **[E]** | An external fact, checked against official docs or the project's own repository on 2026-11-21 (URL in section E) |
| **[M]** | A measurement the repository itself publishes (README, CHANGELOG, eval scripts). It was not re-run for this audit |
| **[T]** | Tested in a throwaway prototype outside the repository, on SQLite 3.53.1 under Python 3.12.13 and 3.14.6, with the project's pydantic 2.13.2 |
| **[P]** | A proposal |
| **[A]** | An assumption |
| **[Q]** | An open question that needs the owner or a measurement |

### What revision 2 changes

| Review issue | Resolution | Where |
|---|---|---|
| 1. Bitemporal consistency | *(Refined in 2.1, point A below.)* `recorded_at` moved to the evidence. In 2.1 the nullable text date became `stated_date`, and `recorded_at` became a ledger time that is never NULL. An undated line has no stated date, exactly as 0.9.0 decided. Added: `asserted_from`, the earliest dated evidence; `event_date` per evidence; `timeless` only when stated. An unknown start is never read as "always". `as_of` is three-valued: true, false or unknown | F.3, J.1, L.1 |
| 2. Claim identity and provenance | The id hashes only the assertion key: subject, predicate, **role** and typed object. No date, no source, no status. `claims.source_path` is removed. Evidence rows carry the provenance, one per supporting record. Each file reconciles only its own evidence, and a claim disappears only with its last evidence | F.3, G.2, L.1, ADR-011 |
| 3. Lifecycle and conflict | Lifecycle is `candidate`, `accepted` or `rejected`. `superseded` is no longer a lifecycle state: it is the end of a validity period. Conflicts get their own derived table. Origin and verification are never touched by conflict detection. Review decisions go into a log in the vault | F.3, J.2, L.1, ADR-012 |
| 4. Graph traversal | A bounded breadth-first walk with two indexed, bounded queries per expanded entity and the `LIMIT` applied **before** the validity filter. It has a hub cutoff, a visited set, claim de-duplication, a hard depth cap and a deterministic order. Prototype on a 10,000-neighbour hub: 363 edge rows read, about 1 ms. The first draft's query generated 320,005 rows (247 ms) | H.3, ADR-013 |
| 5. KAG distinction | The judge is a reranker and relevance check, not a reasoner. Six capabilities are separated, each marked native or needing a specialised engine | D.1, H.7, ADR-014 |
| 6. Revised sections | A, D, F, G, H, I, J, K, L, M, O, P, Q, R. B, C, E and N are unchanged | — |
| 7. Safety | M0 (measurement only) is the next and only implementation activity, and it runs on a copy of the agent folder | P |

### Revision 2.1: three clarifications after review

| Clarification | Resolution | Where |
|---|---|---|
| A. True transaction time | A date written in markdown can be backdated, so it is no longer called a recording time. `stated_date` is the date the text gives, nullable, and used for valid time only. `recorded_at` comes from brain-core's own clock: the moment `brain_remember` wrote the line, otherwise the first time the indexer saw it. It is kept in an append-only `record_ledger` that a rebuild never drops, and it can only err late, never early. `first_ingested_at` is kept beside it. `asserted_from` is renamed `asserted_from`, because it is a valid-time bound taken from the text | F.3, J.1, L.1, P (M1) |
| B. Evidence identity | An evidence row is one *occurrence*: its key is `(claim_id, source_path, line, rule)` with a store-qualified path. The same record text in two files gives two rows, so multi-source provenance cannot collapse | F.3, G.2, L.1 |
| C. Traversal truncation | The limits table and the pseudocode now match the prototype: `scan` per direction, `fan` per entity across both directions. Every cut sets `truncated`: extra seeds, a frontier over `max_frontier`, a full scan window, `fan` reached, a hub reached through a path, `max_edges` | H.3 |

---

## A. Executive summary

**What brain-core is.** **[V]** It is not a generic "Python backend over Obsidian" RAG app. It is a local, single-user memory server for Claude Code agents:

- one MCP server per agent (`brain serve`) with exactly five tools
- a markdown vault as the source of truth
- one SQLite file (`data/brain.db`) holding a rebuildable FTS5 index, optional local vectors, a relations table and an event journal
- optional extras: a shared on-demand embedding worker, a model judge, and a self-hosted Hindsight store over HTTP

It is about 9,900 lines of Python (`src/brain_core`). It has 571 passing tests, `ruff` is clean and `mypy --strict` is clean on 110 files. That was run for this audit: 3 tests skipped, two because they need local services that are not running here and one because it is Windows-only.

**Readiness.** High for an incremental path. Most of the architectures listed in the brief already exist in brain-core in a light, measured form:

| Brief asks for | brain-core today |
|---|---|
| Canonical markdown, indexes derived and rebuildable | Built **[V]**. `docs/VAULT_SCHEMA.md`; `stores/index.py:217` re-parses a file when its signature changes. The exception is relations (G1) |
| Hybrid retrieval with RRF | Built, optional **[V]**. Keyword, vector and date nets joined by rank (`recall.py:444`, c=10) |
| Reranking and a relevance check | Built, optional **[V]**. An LLM judge reads 50 candidates and says which answer the question. It can only point at records it was shown (`judge.py`). It does not reason over them (H.7) |
| Temporal retrieval | Partial **[V]**. Dates asked in words, a date net, supersession chains. Only one time axis |
| Contradiction and outdated detection | Partial **[V]**. A `⚠ Fact changed` banner for lexical changes, `supersedes` links, "current beats old" by rule (`recall.py:461`) |
| Corpus-wide synthesis (GraphRAG "global") | Analogue built **[V]**. Mental models: standing questions answered with a citation on every claim (`models.py`) |
| Persistent memory: working, episodic, semantic, procedural, reflective | All five exist as files and jobs (section I) **[V]** |
| Evaluation | Built **[V]**. Labelled gold questions, paired McNemar comparison (`tests/eval/run_gold.py`, `compare.py`) |
| Knowledge graph | Weak **[V]**. Free-text subject/predicate/object rows; no entity identity, no traversal, no provenance |
| Claims and evidence model | Missing as a first-class model **[V]** |
| Entity resolution, ontology | Missing **[V]** |
| Logical-form reasoning, symbolic and numeric execution (KAG) | Missing. Not covered by the judge (H.7) **[V]** |

**Headline recommendation [P].**

- Keep the vault canonical and SQLite as the only derived store.
- Add four things inside the existing shape:
  1. an entity registry stored as Obsidian notes, with UUIDv7 ids and `aliases`
  2. **claims derived from the vault:**
     - an assertion with a stable id
     - one evidence row per supporting record
     - validity periods computed from that evidence
     - a lifecycle (candidate, accepted, rejected)
     - conflicts kept apart from the lifecycle
  3. a **bounded** graph-expansion net added to recall's existing rank fusion
  4. an approval path for AI-extracted claims through the inbox that already exists, with review decisions kept in a log in the vault
- Do **not** put Neo4j, Qdrant, PostgreSQL, Redis, OpenSPG KAG or Microsoft GraphRAG into the product.
- Run Neo4j GraphRAG only as an offline benchmark projection, and promote it only if it beats the current recall on the held-out questions.
- Leave KAG out even of the bench while it is unmaintained (no release since June 2025 **[E]**). brain-core can build some of what KAG does natively, and H.7 says which parts still need a specialised engine.

**Why [V]/[M]/[E]/[T]:**

- **Scale.** About 3,200–5,400 records per vault. Exact cosine over all of them takes milliseconds. A bounded 2-hop walk from a hub with 10,000 neighbours reads 363 edge rows in about 1 ms **[T]**.
- **The product promise.** A one-minute lite install, one SQLite file, nothing in someone's cloud.
- **Evidence.** Hindsight already runs an entity graph, a temporal net, fusion of four searches and a cross-encoder reranker. On the reworded slice it found the same 50 of 75 questions as keywords plus search keys, at about 2 s a query against about 45 ms (README, "Does it work?"). The data does not yet show that a heavier engine pays off here.
- **Operations.** Neo4j alone needs a JVM service with 2–8 GB of RAM **[E]**.

**Next activity: M0 only [P].** Measure before building, on a **copy** of the agent folder:

1. a baseline of the current configurations
2. a person checks at least 100 eval labels (today every label was written by a model, README)
3. a census of the predicates and degrees in the relations table
4. performance measurements

Nothing in M0 changes the schema or adds a migration.

---

## B. Existing architecture audit

### B.1 Inventory [V]

| Item | Finding |
|---|---|
| Package | `brain-core-mcp` 0.9.1; Python `>=3.12,<3.15`; build with hatchling; lockfile `uv.lock` |
| Runtime deps | `mcp>=1.0,<2` (FastMCP 1.x), `pydantic>=2.9`, `pyyaml`, `typer`, `pywin32` (Windows only) |
| Optional extras | `api` = `anthropic` (judge, mental models); `vectors` = `sentence-transformers`, `numpy` |
| Entry points | `brain` / `brain-core-mcp` → `cli/main.py` (typer; 17 commands, including `serve`, `index`, `models`, `graph`, `daily`, `weekly`, `doctor`) |
| Library | `brain_core.Agent` (`agent.py`): the facade every entry point goes through |
| Storage | `storage/db.py`: WAL, `foreign_keys=ON`, `synchronous=NORMAL`, autocommit plus an explicit `transaction()`. Migrations 001–006 (`storage/migrations/`) |
| Tests | 421 test functions across unit, integration and eval; 571 test cases pass in 13.5 s. CI on Ubuntu and Windows; wheel smoke test over stdio |
| Deployment | `install.sh` / `install.ps1`; launchd, systemd `--user` or Task Scheduler jobs; `Dockerfile` only so a registry can introspect the stdio server. **No docker-compose, no HTTP API, no message queue** |
| Absent (checked) | No graph DB, no vector DB server, no Postgres (except inside Hindsight's own embedded pg0), no Redis, no file watcher daemon |

### B.2 Runtime topology [V]

```
 Claude Code (the LLM: reasons, answers, cites)          Claude desktop app (same 5 tools, no hooks)
   │ hooks: SessionStart→`brain brief`  Stop/PreCompact→`brain capture`
   │        PostToolUseFailure(Bash)→`brain recall --hook`  PreToolUse(Bash)→block-dangerous-bash.sh
   │ MCP stdio (.mcp.json: brain serve .)
   ▼
 brain serve  ──  mcp/server.py: 5 tools, annotations, metrics row per call (server.py:310)
   │
   ▼
 Agent (agent.py) ── stores list built from brain.yaml (agent.py:132)
   ├─ SqliteStore      facts table (v0.1 copy; answers only for rows no vault file held)
   ├─ VaultStore       vault/*.md read/write by kind; RecordIndex (FTS5) synced on read
   ├─ HindsightStore   optional, MCP-over-HTTP to 127.0.0.1:8888 (retain/recall/reflect)
   ├─ GraphStore       relations table (always on)
   ├─ TranscriptStore  optional, read-only FTS over ~/.claude/projects/<cwd>/*.jsonl
   ├─ NotesStore / ArchiveStore  optional read-only markdown folders
   ├─ VectorIndex      optional, record_vectors BLOBs, exact cosine (numpy)
   │     └─ WorkerEmbedder ── unix socket ── embed_worker (one per machine, exits when idle)
   └─ judge Runner     optional: Anthropic API or the user's Claude Code login
 cron: `brain daily` (brief, health, Hindsight backup, update check)  `brain weekly` (archive, models, rule drafts, reflection)
```

### B.3 Module map [V]

| Module | Lines | Responsibility |
|---|---:|---|
| `agent.py` | 476 | Facade. Builds the stores, wraps recall (miss logging, degraded notes, judge paging), the write path, sessions |
| `recall.py` | 578 | The retrieval orchestrator: scope routing, scoring, dedup, nets, RRF, identifier pin, supersession, judge, miss detection, token cap |
| `remember.py` | 179 | The write path: secret refusal, duplicate and contradiction check, fixed layer order, per-layer status |
| `stores/vault.py` | 809 | Vault parser and writer, secret patterns and masking, `record_meta.md`, locks, atomic writes |
| `stores/index.py` | 392 | FTS5 record index: incremental sync, bm25 search, cover, dates in words, identifier lookup |
| `stores/vectors.py` | 193 | Vector cache table, fill and search |
| `stores/graph.py` | 110 | Relations table: `LIKE` filtering, insert, legacy import |
| `stores/hindsight.py` | 187 | MCP HTTP client for Hindsight |
| `stores/transcripts.py`, `notes.py`, `sqlite.py` | 376 | Read-only stores and the v0.1 fact table |
| `session.py` | 437 | `brain_session` start block and end writes |
| `cron.py` | 852 | Daily and weekly jobs, consolidation, rule drafts, reflection, scheduler install on three operating systems |
| `models.py`, `judge.py` | 476 | LLM runners (api or claude), mental models, judge |
| `embed.py`, `embed_worker.py` | 325 | Socket client and shared worker |
| `capture.py`, `lessons.py`, `distill.py` | 561 | Hooks (capture, checkpoint, lessons) and source capture |
| `status.py`, `traits.py` | 977 | Health, knowledge lint, the twelve-trait evidence scores |
| `memory/structured.py`, `memory/episodic.py` | 312 | v0.1 fact table primitives and the event journal |

### B.4 Workflows traced from entry point to storage [V]

**1. Receiving a request.** Claude Code calls a tool over stdio. `mcp/server.py` validates the parameters with pydantic `Field` descriptions and calls the matching `Agent` method inside `_timed`, which writes one `metrics` row: runtime, response tokens, error (`server.py:310–323`). brain-core has no other ingress. The hooks call the CLI, and the CLI opens the same `Agent`.

**2. Understanding the query** (`recall.py`). There is no LLM query rewriting. It is deterministic:

- It works out which kinds and stores to ask from `scope`.
- It cuts the question to 1,000 characters (`:45`) and tokenises it (stopwords dropped, a naive singular).
- It pulls out **exact identifiers**: tokens with a digit or `_ . / #` (`identifiers()`).
- It turns **dates written in words** into ISO dates (`index.py: iso_dates`, `days_asked`: "yesterday", "last Tuesday", "November 1st").

**3. Retrieving knowledge.**

- Each store is read: indexed stores by bm25 query, filter-only stores whole.
- Each hit is scored `0.75·relevance + 0.25·recency`, where recency has a 90-day scale (`:241`). The record index puts every markdown store on one shared bm25 scale.
- Duplicates are dropped by id and by normalised text.
- Lines a `Fact changed` banner quotes have their score halved. Transcript and archive hits are weighted 0.7 (`:301`).
- With vectors on, a **vector net** runs (the best 150 by cosine). A **date net** adds the records of any day the question names (`:349`).
- The lists are fused by **RRF with c=10**. This was measured: 188 of 255 at c=10 against 181 at c=60 (`:85`).
- Records holding an exact identifier from the question are pinned first (`_pin`, `:514`).
- A replaced record never stands above its replacement (`_current`, `:461`).

**4. Building context.**

- The optional **judge** reads the best 50 records, wrapped in a `<records>` block they cannot close, and returns the numbers of the ones that answer.
- Recall decides whether the question was answered from the rarity-weighted share of question words in the leading keyword hits (`index.cover`, threshold 0.5), or from the judge's verdict. The reply then carries `weak_match`, `not_in_memory` or `thin_recall`, each with steering text.
- The reply is capped at 6k tokens and masked for secrets on the way out.
- Session context is assembled separately:
  - `brain_session('start')`: brief, executive state, mental models, 3 recall hits for each of the top 2 missions, inbox count, crash recovery flag (`session.py`)
  - the SessionStart hook: at most 3,000 tokens of the brief
  - `capture.checkpoint`: after a compaction, the user's last asks, edited files and last reply

**5. Calling LLMs.** The main LLM is Claude Code itself; brain-core is a tool server and generates no answers. brain-core calls a model in only three places, all opt-in:

- the judge (`recall.judge: model`)
- mental models (`brain models`)
- Hindsight's own retain and reflect

The runners are `models.run_api` (Anthropic SDK) and `models.run_claude` (an isolated `claude` subprocess). This is already a small LLM-provider abstraction: `Runner = Callable[[str, str], str]`.

**6. Storing information** (`remember.py`).

- Text holding a credential is refused before any store sees it.
- For facts and patterns, the closest existing line is found:
  - Jaccard ≥ 0.8 is a duplicate and is skipped.
  - Jaccard ≥ 0.5 with different numbers, or ≥ 0.8 with a new word, is a changed value. The new line gets a banner, the old line stays, and `supersedes` goes into `record_meta.md`.
- The layers are written in a fixed order: vault → sqlite → hindsight → graph. Each layer reports its status, and a failed layer is never swallowed.
- Vault writes are atomic (temp file plus `os.replace`) under one lock per vault, kept outside the vault.

**7. Maintaining memory** (`cron.py`).

- `brain daily`: brief, health line, traits, Hindsight backup, PyPI update check.
- `brain weekly`:
  - archives session files older than 30 days into monthly folders with a summary
  - refreshes mental models
  - drafts a rule once a theme has 3 unpromoted corrections
  - appends a Hindsight reflection to `knowledge/_reflections.md` as **unverified**; that file is kept out of the index

**8. Agent workflows.** The behaviour lives in templates (`templates/agent/`):

- five rule files: identity, doctrine, authority, memory, system
- three skills
- hooks
- the memory protocol in `04-memory.md`: start and end the session, write every 3–5 exchanges, cite every claim

There is no planner or agent loop inside brain-core. Planning is Claude Code's job.

**9. Updating knowledge sources.**

- `brain_distill` captures a URL, repo, video, PDF or text into immutable `raw/YYYY-MM-DD-<slug>.md`, with its sha256.
- The agent compiles `knowledge/<topic>.md`, which is indexed one record per `##` section (`vault.py:752`).
- Hand edits to any vault file are picked up on the next search: the file's mtime and size signature changes (`index.py:217`, `FORMAT = 3`).

### B.5 Obsidian and markdown support [V]

| Feature | Status | Evidence |
|---|---|---|
| Markdown files by kind | Yes. Facts and patterns as bullets under `## Domain`, decisions and corrections as entries, session notes, raw, knowledge | `VAULT_SCHEMA.md`, `vault.py:157–175` |
| YAML frontmatter | Partial. Only flat top-level `key: value` lines; YAML lists (`aliases:`, `tags:` as a block or inline list) are not parsed | `vault.py:799` |
| Headings | Yes. Knowledge pages become one record per `##` section; `####`–`######` end an entry | `vault.py:752` |
| Tables, paragraphs | Yes in session files (one record per block) | `VAULT_SCHEMA.md` "What the reader takes" |
| Fenced code blocks | Not handled specially. A `## ` line inside a fence would start a new section | no fence handling in `vault.py` |
| Wikilinks `[[…]]` | **Only linted** in `knowledge/_index.md`; not indexed, not a graph edge | `status.py:28` |
| Tags `#tag` | Not parsed | — |
| `aliases` frontmatter | Not parsed | — |
| Other markdown folders | Yes, read-only, through `stores.notes` and `stores.archive` (read like knowledge pages) | `stores/notes.py` |
| Revisions | Append-only lines, `.prev.md` for state files, `Fact changed` banners. No revision table; any git history of the vault is the user's own **[Q]** | `session.py: _put` |
| Incremental sync | Yes. Per-file `FORMAT:mtime_ns:size` signature; a deleted file loses its rows; a missing or empty vault is an error, never "empty" | `index.py:217`, `vault.py:260` |
| Moves and renames | Treated as delete plus add. Fact and pattern ids are content hashes, so they survive a move. Knowledge record ids are `sha256(path#heading)`, so a rename gives new ids: keys, vectors and `supersedes` links keyed to the old ids no longer match | `vault.py:796` |

**Verdict.** The integration is a schema-aware reader of brain-core's own vault layout, not a general Obsidian parser. That suits the model where the canonical files come first, and the parts that are missing are small parser additions: links, tags, aliases and fences.

---

## C. Gap analysis

### C.1 Missing or partial capabilities

| # | Gap | Evidence | Impact |
|---|---|---|---|
| G1 | **Relations are not in the vault.** `kind='relation'` is refused by the vault ("not a vault kind") and by SQLite, and is written only to the `relations` table, plus Hindsight as plain text. Deleting `brain.db` loses every relation. That breaks the rule the README states: "The SQLite index is a cache: delete it and it is rebuilt from the files" | `vault.py:496–501`, `sqlite.py`, `remember.py:22` | **High.** The graph is the one memory kind that cannot be rebuilt |
| G2 | **Entities have no identity.** A relation is three free strings, so "Neo4j", "neo4j" and "Neo4j 5" are three nodes. No type, no alias, no merge | `002_relations.sql` | High: no graph reasoning is possible |
| G3 | **The graph is not used for retrieval.** `GraphStore.read` matches any word with `LIKE`, returns rows unranked, and recall scores them by token overlap. There is no traversal and no link from a relation to the record it came from | `graph.py:32–59` | High for relationship and multi-hop questions |
| G4 | **No claim or evidence model.** Provenance is the record's `path:line` (good), plus an optional `source` in `record_meta.md`. There is no status, confidence, origin or verification on a relation or fact | `THREAT_MODEL.md` gate 2 "partly built" | High for the brief's requirement 4.4 |
| G5 | **One time axis.** `Record.date` is the line's own written date (or none). There is no valid time apart from recorded time. A record's end of validity is implied by `supersedes` but never stored | `base.py:Record` | Medium: "when was it true" and "when did we learn it" are conflated |
| G6 | **Contradictions are only detected lexically.** A changed number, or a near-identical line with a new word. "We use Neo4j" against "We replaced Neo4j with Kuzu" is not caught (low Jaccard) | `remember.py:23–24, 65–68` | Medium |
| G7 | **Obsidian structure is unused**: wikilinks, tags and `aliases` lists (see B.5) | `vault.py:799` | Medium. This is the cheapest graph source there is, and it is ignored |
| G8 | **Memory candidates are not gated.** The capture hook files every user message under *Said (hook)* in the day's session file, which is indexed and searchable at full weight. A `provisional` flag is planned but not built | `capture.py:29`, `THREAT_MODEL.md` gate 1 | Medium: noise, and a poisoning surface |
| G9 | **Eval labels are not human-checked.** All 446 labels were written or checked by a model of the same family as the judge | README "Does it work?" | **High, and it applies to every decision in this plan** |
| G10 | **Multi-hop is thin and small.** Held out: 8 → 14 of 17 with vectors and the judge. 17 questions cannot separate two candidate engines | README | Medium |
| G11 | **Notes and archive record ids embed the absolute folder path.** `NotesStore` passes the full path to `knowledge_records`, which hashes `path#heading` into the id. Moving or renaming a notes or archive folder, or the home folder, re-keys every record in it: 2,805 of the live agent's 6,016 records. That detaches their search keys (`record_meta.md` is keyed by id), their vectors and any `supersedes` link. Found in M0, when a copy of the eval snapshot lost 64 of its gold records **[V]** | `notes.py:29`, `vault.py:796`; `docs/M0_BASELINE.md` | Medium. It matters for claim evidence (G.2), which must not churn when a folder moves |

### C.2 Duplication, coupling, technical debt [V]

1. **Dead schema.**
   - The `decisions`, `reflections` and `hsam_days` tables (001) are never read or written by `src/`; this was checked with grep for `FROM|INTO|UPDATE|JOIN`.
   - Decisions live in `decisions_log.md`, reflections in `knowledge/_reflections.md`.
   - Only `metrics` and `events` from 001 are used.
2. **A stale docstring.** `mcp/server.py:8` points to `brain_core.mcp.tools`, which does not exist.
3. **Two fact stores.** The `facts` table plus the vault. 0.9.0 resolved this deliberately: the vault is the truth, and the table answers only for rows marked `sole` (`recall.py` module docstring). It is a working compromise, not a defect, but it is v0.1 weight the new layers should not build on.
4. **`recall.py` is concentrated.** Scoring, three nets, pinning, supersession, judging, miss detection and the token cap sit in one 578-line function with its helpers. A fourth net added in place raises the coupling further, so extract a small net interface when it lands (H.5).
5. **Two identity schemes, used on purpose.** A record id is the content hash, the idempotency key everywhere (vectors, keys, `supersedes` take the 16-character prefix). A knowledge id is the hash of path plus heading. Both are right for idempotency and wrong for **entity** identity. Keep them and add entity ids beside them; do not replace them (ADR-004).
6. **A one-way adapter.** `HindsightStore` keeps no mapping back from Hindsight ids to vault records, apart from the `record_id` in its metadata. That is fine while Hindsight stays an optional second net.

### C.3 Security and reliability review

| Topic | Today [V] | Gap / proposal [P] |
|---|---|---|
| Credential handling | Refused on write; masked at index time and in every reply; `brain doctor --remask`; extensive format list | Keep. Every new extraction or projection path must call `has_secret` and `redact` (it is a trust boundary) |
| Database access control | Local files only; MCP over stdio; the embed socket is user-only | Hindsight's MCP is **unauthenticated by default [E]**. brain-core binds it to 127.0.0.1; document that, and check it in `brain doctor` |
| Vault protection | Atomic writes, a lock outside the vault, append-only, a missing vault is an error | Add a `brain doctor` warning when the vault is not under git **[Q]** |
| Prompt injection through retrieved text | The judge sees records in a `<records>` block and is told they are data. The recall description says the same. Reflections are kept out of the index | Extraction prompts get the same framing. Extracted output is **structured JSON only**, validated by pydantic, and every entity name must occur verbatim in the source record (a grounding check). The extractor never writes the vault |
| Untrusted extracted knowledge | Not applicable yet (nothing is extracted) | Extracted claims are `candidate`. They are promoted only through the inbox, and recall down-weights them like transcript lines (0.7) |
| Autonomous tool use | A bash guard hook; an authority rule; MCP annotations (`destructiveHint` on session) | No new tools (ADR-009). Projections and extraction are CLI-only, run by a person or cron |
| Audit logging | Event journal (`brain_remember`, `recall_miss`, `recall_repair`, `recall_degraded`); a `metrics` row per tool call | Add `claim_promoted`, `claim_rejected`, `entity_merged` events |
| Sync failures and retries | Per-layer status; the Hindsight queue file drained at session end; iCloud `EDEADLK` retried | No outbox needed while everything derived lives in one SQLite file (ADR-003) |
| Backups and index rebuild | The index and vectors rebuild from the vault; Hindsight is backed up daily. **Relations do not rebuild (G1)** | Fix G1 first. Afterwards, deleting `brain.db` must lose nothing but the journal and metrics |
| Approval for important mutations | Decisions and corrections are written by the agent under the authority rule; `inbox_staged.md` is a staging queue ("Staged Extractions") that the user commits or reviews | Route every entity merge and every extracted claim through this inbox |
| Sensitive information | `THREAT_MODEL.md` lists what leaves the machine for each feature | Add a row for LLM extraction (off by default) and one for each bench projection |

---

## D. Recommended target architecture

### D.1 Diagram [P]

```
 INTELLIGENCE LAYER (unchanged: Claude Code + rules + skills)
   agent-driven reasoning: plans, decomposes, calls brain_recall again, writes the answer and
   cites the sources brain_recall returned. Unstructured: no plan object, no solver (H.7)
                          │  MCP stdio — still exactly 5 tools (ADR-009)
                          ▼
 ┌──────────────────── brain serve / Agent ────────────────────────────────────────────────┐
 │ KNOWLEDGE ORCHESTRATOR = recall.py (+ session.py for working memory)                     │
 │  signals (no LLM): identifiers · days asked · entity aliases hit · cue words · as_of     │
 │   ├─ keyword net    FTS5 bm25 + search keys                      (always)                │
 │   ├─ vector net     record_vectors, exact cosine                 (stores.vectors)        │
 │   ├─ date net       records of the days named                    (a day in the question) │
 │   ├─ graph net  NEW bounded BFS over accepted claims, as_of on claim_periods (H.3)       │
 │   └─ external net   Hindsight recall              (bench only: Neo4j GraphRAG)           │
 │   ▼                                                                                      │
 │  RRF join (c=10) → exact-identifier pin → current-over-superseded (relative to as_of)    │
 │   → judge (optional: rerank + "does this answer?"; not a reasoner)                       │
 │   → results: source, validity at as_of, path, disputed_with; plus a structured `claims`  │
 │     block the agent can count and compare (H.7)                                          │
 │ WRITE PATH: brain_remember → secret gate → ontology check → vault (canonical)            │
 │   → the file's derived rows in one SQLite transaction (G.2) → Hindsight (optional)       │
 │ MAINTENANCE (cron): brief · consolidate · models · open conflicts in the brief NEW ·     │
 │   candidate extraction batch (NEW, optional, LLM) → inbox → claim_reviews.md             │
 └──────────────────────────────────────────────────────────────────────────────────────────┘
                          │
   KNOWLEDGE LAYER: one file, data/brain.db (a rebuildable cache of everything below it)
     per-file raw rows : records_fts · mentions · claim_evidence · record_times · record_links
                         · claim_reviews
     computed from them: claims · claim_periods · claim_conflicts · entities.degree
     other             : record_vectors · entities · aliases · events (journal) · metrics
                          │  rebuilt by `brain index --rebuild` from:
   CANONICAL KNOWLEDGE: vault/
     facts.md patterns.md decisions_log.md corrections.md sessions/ knowledge/ raw/
     record_meta.md (keys, source, supersedes; NEW: valid, until, event)
     relations.md NEW · entities/*.md NEW · claim_reviews.md NEW · inbox_staged.md (candidates)
                          │
   KNOWLEDGE SOURCES: the agent's writes · hooks (capture) · brain_distill · notes/archive
     folders · Claude Code transcripts
```

**Mapped onto the brief's conceptual model (its section 15).**

| Brief's layer | In brain-core |
|---|---|
| Vector RAG | The vector net |
| Graph RAG | The bounded graph net |
| KAG reasoning | **Not present, and not replaced by the judge.** brain-core retrieves, reranks and checks relevance; the agent reasons without structure. What KAG adds is logical-form planning executed by a solver with symbolic and numeric operators, and brain-core does not have it. H.7 separates what can be built natively from what needs a specialised engine |
| Qdrant, Neo4j, PostgreSQL | One SQLite file |

### D.2 Data flows [P]

1. **Write.** The agent calls `brain_remember(kind='relation', subject, predicate, object, role?)`.
   - The secret gate runs.
   - Subject and object are resolved to entities (exact alias match). An unknown name becomes a *candidate entity* in the inbox, and the relation is still written, against the raw name.
   - The predicate is checked against `ontology.yaml`.
   - The vault line is appended to `relations.md`.
   - The file's derived rows are rebuilt in one transaction (G.2), and Hindsight retains the text.
2. **Rebuild.** `brain index --rebuild` drops every derived table and re-derives the whole vault in a fixed order:
   1. entity notes
   2. every file's raw rows: records, mentions, evidence, record times and links, reviews
   3. everything computed from them: claims, periods, lifecycle, conflicts, degrees

   The same vault always gives identical tables, and a test proves it (G.2).
3. **Recall.** See section H.
4. **Extraction (optional).** `brain extract --since 7d` runs the LLM over new records. Its JSON is validated and grounding-checked, then written as **candidate lines in `inbox_staged.md`**, a vault file, so a rebuild keeps them.
   - When the user approves one, it becomes a `relations.md` line with `origin: extracted` and the approval date.
   - When the user rejects one, a `reject` line goes into `claim_reviews.md`, so the same claim is not proposed again.
5. **Consolidation.** The existing weekly archive, plus open conflicts listed in the daily brief: accepted claims on a *functional* predicate with one subject and role, different objects, and overlapping known validity.

---

## E. Technology selection

### E.1 Verdict per technology

| Technology | Brief's role | Verdict | Reason |
|---|---|---|---|
| Python | Backend | **Keep** | It already is |
| Obsidian / markdown | Canonical | **Keep**, and use more of it (links, tags, aliases) | Already canonical; Obsidian's own `aliases` and wikilinks give entity identity and graph edges for free |
| SQLite (FTS5, JSON1) | (not in the brief) | **The only derived store** | Already in place. At 5k records exact vector search takes milliseconds, and a bounded 2-hop walk reads 363 edge rows in about 1 ms even from a hub with 10,000 neighbours **[T]** (H.3). One transaction covers every index, so no outbox is needed. Zero operations |
| Neo4j | Knowledge graph | **Reject for the product; bench only** | A JVM service: 2 GB minimum for cloud, 8 GB for on-prem production **[E]**. A second source of truth. Breaks the lite install. Its strengths (graph algorithms, Cypher, very large graphs) are not needed at this scale |
| Qdrant | Vector and hybrid | **Reject** | Vectors already live in SQLite with exact cosine. Hybrid search and RRF already exist. Reconsider above about 200k records, or for several machines sharing one memory |
| PostgreSQL | Metadata, claims, jobs, audit | **Reject for the product** | Single user, one process per agent, WAL SQLite. Postgres already runs inside Hindsight (pg0) for those who opt in **[E]**; a second one adds nothing. Reconsider only for a hosted multi-user product, which the README rules out |
| Redis | Task coordination | **Reject** | There is no job queue to coordinate: cron jobs, an on-demand embed worker, and a lock per vault |
| sqlite-vec | (alternative) | **Not needed** | Pre-v1 **[E]**. macOS system Python cannot load SQLite extensions **[E]**. The numpy BLOB search already works |
| Hindsight | (existing, optional) | **Keep optional; it is the real "graph + temporal" engine already integrated** | It extracts entities, links facts by entity, time, meaning and cause, keeps event time and learned time, fuses four searches with RRF (k=60) and reranks with a cross-encoder **[E]**. Measured: it found the same 50 of 75 reworded questions as keywords at about 40× the latency **[M]** |
| Neo4j GraphRAG (`neo4j-graphrag`) | Graph retrieval | **Bench adapter only** | Needs Neo4j ≥ 5.18.1 **[E]**. Its retrievers (VectorCypher, HybridCypher, Text2Cypher, Tools) are good patterns to copy into SQLite, not a dependency to take on. The KG builder is still "experimental" **[E]** |
| OpenSPG KAG | Knowledge construction and reasoning | **Do not integrate; not even a bench while it is dormant** | No release since June 2025; a four-container Java stack; no Anthropic client (E.2) |
| Microsoft GraphRAG | Corpus-wide reasoning | **Do not adopt** | See E.2 |

### E.2 KAG, Neo4j GraphRAG and Microsoft GraphRAG compared

These three are not interchangeable: they are a reasoning framework, a retrieval library and an offline indexing pipeline. Hindsight is included because brain-core already runs it.

| | OpenSPG KAG | Neo4j GraphRAG (`neo4j-graphrag`) | Microsoft GraphRAG | Hindsight (already integrated) |
|---|---|---|---|---|
| What it is | A knowledge construction pipeline (kg-builder) and a logical-form solver (kg-solver) with planners, a math executor and a Cypher executor; "mutual indexing" links graph nodes and text chunks | A Python library of retrievers over a Neo4j database, plus an experimental KG builder (`SimpleKGPipeline`) | An offline pipeline: LLM entity/relation extraction → Leiden communities → community reports; local, global, DRIFT and basic search | A memory server: LLM retain (facts and entities), four-way recall, reflect, mental models |
| Latest / activity | v0.8.0, 2025-06-28; OpenSPG server v0.8, 2025-06-29, no commits since. Last real KAG commit 2026-01-28. An issue (#752, June 2026) asking whether it is maintained has had no answer | 1.24.0, 2026-11-10; releases every 2–4 weeks | 3.3.0, 2026-10-08; the README says "largely in maintenance mode" | v1.2.3, 2026-11-19 |
| Python (brain-core: 3.12–3.14) | Recommends 3.10; `pyodps==0.12.2` has wheels only up to cp312; `mcp==1.6.0` pinned | 3.10–3.14 (the spaCy extra not on 3.14) | `>=3.11,<3.14`: **no 3.14** | Its own service, `>=3.11` |
| Services needed | openspg-server (Java, `-Xms2g -Xmx8g`) + MySQL + Neo4j (APOC) + MinIO; images `:latest` from an Aliyun registry. Developer mode still needs the server. An in-memory graph mode exists for its benchmarks | Neo4j ≥ 5.18.1 (APOC for the KG builder); a JVM; 2 GB minimum for cloud, 8 GB for on-prem production | None (parquet + LanceDB files); heavy Python deps (spaCy, pandas, pyarrow, graspologic, Azure SDKs); `litellm` pinned exactly | Postgres + pgvector (embedded pg0 in dev); 1.5–2 GB RAM |
| Anthropic models | No native client (OpenAI-compatible, Azure, Ollama, vLLM only) | `AnthropicLLM` native; no Anthropic embedder | Through LiteLLM (not named in the docs); needs JSON-schema structured output and a separate embedding provider | Yes (default `claude-haiku-5-5`) |
| Embeddings | Required | Required for the vector retrievers | Required | Local default (bge-small) |
| Changes to the corpus | Rebuild through the builder; schema pushed with `knext schema commit` | Your own writer and `MERGE` | `graphrag update` decides the delta by **document title only**: an edited document is skipped, deletions are computed but never applied, and new communities are appended without re-clustering | Re-retaining a `document_id` replaces it; delete is per document |
| Own representation of knowledge | Yes (SPG schema, its own KB) | Yes (a Neo4j graph) | Yes (parquet tables) | Yes (its own bank) |
| Reported results | v0.7 F1 with Qwen2.5-72B: MuSiQue 0.520, HotpotQA 0.748, 2Wiki 0.770 (HippoRAGv2: 0.404, 0.694, 0.618). "Lightweight build" uses 89% fewer build tokens for 1–3 points less | Not a benchmark claim; a toolkit | Documented strengths: global questions over a whole corpus. Indexing "can be an expensive operation"; extraction is ~75% of the cost | On this project's vault: no gain over keywords + keys on reworded questions, ~2 s per query **[M]** |
| License | Apache-2.0 | Apache-2.0 | MIT | MIT |
| Verdict for brain-core | **Do not integrate, and do not bench while it is dormant.** Borrow three ideas: entity↔chunk mutual indexing (this plan's `mentions` + `claim_evidence`), question decomposition (the calling agent does it, without a planner or solver: H.7), a deterministic math step (only if numeric questions show up as misses) | **Bench only (M6)**, through `HybridCypherRetriever` / `VectorCypherRetriever` over a rebuilt projection. Borrow the "retriever as tool" pattern (this plan's `Net`) and the lexical-graph shape | **Do not adopt.** Its incremental update cannot follow an edited vault, and it excludes Python 3.14. Global questions are served by mental models; a native community-summary job over links and tags is possible later if global questions show up as misses | **Keep optional.** It is the integrated graph + temporal engine; M6 re-measures it on the new slices |

All the **[E]** facts in the table above were checked on 2026-11-21 against these sources:

- KAG: https://github.com/OpenSPG/KAG/releases, https://github.com/OpenSPG/KAG/commits/master, https://github.com/OpenSPG/KAG/issues/752, https://github.com/OpenSPG/KAG/blob/master/requirements.txt, https://github.com/OpenSPG/openspg/blob/master/dev/release/docker-compose-west.yml, https://github.com/OpenSPG/KAG/releases/tag/v0.7, https://arxiv.org/abs/2409.13731
- Neo4j GraphRAG: https://pypi.org/pypi/neo4j-graphrag/json, https://neo4j.com/docs/neo4j-graphrag-python/current/, https://neo4j.com/docs/neo4j-graphrag-python/current/user_guide_rag.html, https://neo4j.com/docs/neo4j-graphrag-python/current/user_guide_kg_builder.html, https://neo4j.com/docs/operations-manual/current/installation/requirements/, https://neo4j.com/docs/cypher-manual/current/indexes/semantic-indexes/vector-indexes/
- Microsoft GraphRAG: https://github.com/microsoft/graphrag/blob/main/README.md, https://pypi.org/project/graphrag/, https://microsoft.github.io/graphrag/index/methods/, https://microsoft.github.io/graphrag/query/overview/, https://github.com/microsoft/graphrag/blob/main/packages/graphrag/graphrag/index/update/incremental_index.py, https://microsoft.github.io/graphrag/config/models/
- Hindsight: https://hindsight.vectorize.io/developer/retrieval, https://hindsight.vectorize.io/developer/retain, https://hindsight.vectorize.io/developer/storage, https://hindsight.vectorize.io/developer/mcp-server, https://hindsight.vectorize.io/developer/installation
- sqlite-vec: https://github.com/asg017/sqlite-vec, https://alexgarcia.xyz/sqlite-vec/python.html

Not checked, and inferred only:

- KAG's RAM in total (roughly 6–14 GB, from its configured heap limits)
- whether KAG runs without its server
- whether Microsoft GraphRAG works with Claude through LiteLLM
- Neo4j Community's license (GPLv3, from memory)

### E.3 Recommendation

1. **Initial production retrieval engine:** brain-core's own recall (keyword + optional vector + date), extended with the graph net in SQLite. It is the only option measured on this data. Every alternative must beat it on held-out questions.
2. **KAG:** if it ever runs, it runs separately, as a read-only projection rebuilt from the vault, and never writes back. But not now:
   - it has had no release since June 2025 and its maintenance question is unanswered
   - it needs a Java + MySQL + Neo4j + MinIO stack
   - it has no Anthropic client
   - it pins a 2025-era Python stack that clashes with brain-core's own `mcp` dependency

   Take its ideas (E.2), not its code. Revisit only if it becomes active again **and** multi-hop or numeric questions are the largest miss class after M4.
3. **Microsoft GraphRAG:** it adds little here. Corpus-wide questions are already served by mental models, which cite every claim and refresh when a cited record changes. GraphRAG's community reports cost an LLM pass over the corpus and go stale on a corpus that changes daily (E.2).
4. **How the three could coexist:** each is a **projection** of one canonical model (the vault, plus the entity and claim tables derived from it), produced by an exporter and reached through one `Net` interface. None of them owns knowledge; deleting any of them loses nothing.
5. **Preventing incompatible representations:** one ontology file (`ontology.yaml`), one id scheme (entity UUIDv7, record content hash, claim assertion hash), and exporters that only map. An engine's own extraction output may enter brain-core only as `candidate` claims through the inbox.
6. **Measuring accuracy and cost:** section O. Paired question-by-question comparison on the held-out set, with latency, tokens and build cost recorded for every system.

### E.4 Deployment topology and versions [P]

- **Product.** Unchanged. `uv tool install brain-core-mcp`, launchd / systemd `--user` / Task Scheduler. Optional Hindsight on 127.0.0.1:8888 and an on-demand embed worker. New dependencies for the core plan: **none**. UUIDv7 is in the standard library on Python 3.14 only (checked: 3.12 and 3.13 lack `uuid.uuid7`), so ship a 10-line fallback for 3.12–3.13 (RFC 9562 layout). SQLite 3.53.1 ships with all three local Pythons **[V]**; FTS5, JSON1 and recursive CTEs are all available.
- **Bench, outside the wheel.** A `bench/` folder with a `docker-compose.yml` for Neo4j 5.x Community (+ APOC core, needed by the KG builder **[E]**). `neo4j-graphrag` pinned at 1.24.x **[E]**. Never a dependency of `brain-core-mcp`.

---

## F. Canonical knowledge model

### F.1 Two kinds of identity [P]

| | Record (evidence) | Entity (a thing the evidence is about) | Claim (an assertion about entities) |
|---|---|---|---|
| Examples | a fact line, a decision entry, a knowledge section, a session note | Brain-Core, SQLite, Neo4j, the user, mission M-001 | Brain-Core USES(graph-database) Neo4j |
| Id | **Unchanged:** sha256 of the normalised text (knowledge: of `path#heading`) | **New:** UUIDv7, written once into the entity note's frontmatter | **New:** sha256 of the assertion key (F.3). No date, no source |
| Why | Idempotent writes, dedup, vectors and keys are all keyed by it today | It must survive a rename, a merge and edits to its description | Many records may support one claim; dates and status change while the assertion stays the same |
| Lives in | its vault file | `vault/entities/<Name>.md` (Obsidian note) | derived from records; review decisions in `claim_reviews.md` |

An entity note, the canonical form, human-readable and native to Obsidian:

```markdown
---
type: entity
id: 019a8b3e-7c2d-7f41-9a10-3b5e2d8c4f11
entity_type: technology
ontology: 1
aliases: [Neo4j, neo4j, Neo4j 5, neo4j-community]
category: graph-database
created: 2026-11-21
---
# Neo4j

Graph database. See [[Brain-Core]] decisions.
```

Obsidian resolves `[[neo4j]]` through `aliases` by itself, so the same file serves the human (graph view, backlinks) and the index. The parser must learn YAML lists in frontmatter for this (G7).

### F.2 Ontology v1, fitted to the data the vault holds [P]

The vault records the user, their projects, the systems those run on, the technology chosen, missions, decisions and corrections (`VAULT_SCHEMA.md`, the eval fixture vault: ride app, payment rails, Hindsight service ports, Claude Code versions). The brief's starting list is adjusted to that:

| Brief's type | v1 | Why |
|---|---|---|
| Person | **Person** | The user and collaborators (`user_profile.md`) |
| Organization | **Organization** | Companies, clients, vendors |
| Project | **Project** | Products and repositories |
| Technology | **Technology** | A library, service product, language, model or tool (Neo4j as a product) |
| — | **Component** (added) | A deployed thing of ours (the Hindsight service on :8888, a cron job). Facts about ports and paths need a subject that is not the product |
| Concept | **Concept** | Patterns, techniques (LLM-wiki, RRF) |
| Task | **Mission** (renamed) | It exists already: `goals/missions/<ID>.md` with `mission_id`, `status`, `priority` |
| Decision | record kind `decision` | A decision is evidence with fields (Decision / Reason / Classification / Confidence); it is a record, linked to entities by claims |
| Event | record kinds `note`, `decision`; journal `events`; `event_date` on evidence | Episodes are dated records; no extra node type |
| Document | record kinds `raw`, `knowledge` | Already records with paths |
| Experience | record kinds `correction`, `note` | Same |
| Claim | **the claim model** (F.3) | An assertion *about* entities, not an entity |
| Memory | `Record` | Every record is a memory |

Relationships v1. A small closed set; anything else is stored as `RELATED_TO` with its raw predicate kept, so nothing is lost:

| Predicate | Domain → range | Functional?* | Replaces from the brief |
|---|---|---|---|
| `USES` | Project, Component → Technology, Component | per `role` | USES |
| `DEPENDS_ON` | Project, Component → Project, Component, Technology | no | DEPENDS_ON |
| `PART_OF` | Component → Project; Project → Organization; Mission → Project | yes | CONTAINS (inverse) |
| `WORKS_ON` | Person → Project, Mission | no | INVOLVES |
| `MEMBER_OF` | Person → Organization | no | — |
| `OWNS` | Person, Organization → Project, Component | no | CREATED |
| `ALTERNATIVE_TO` | Technology ↔ Technology | no | — |
| `LISTENS_ON`, `VERSION`, … (literal-valued) | Component, Technology → literal (`port`, `version`, `url`, `int`, `date`, `text`) | yes | — |
| `SELECTS` / `REJECTS` | decision record → Technology, Concept, Component | — | SELECTS, DECIDED |
| `APPLIES_TO` | decision, correction, pattern record → Project, Component, Mission | — | APPLIES_TO, AFFECTS |
| `MENTIONS` | record → entity (deterministic: wikilink, alias, tag) | — | DESCRIBES |
| `SUPERSEDES` | record → record (`record_links`) | yes | SUPERSEDES |
| `DERIVED_FROM` | knowledge record → raw record | no | LEARNED_FROM |
| `RELATED_TO` | any → any (fallback; raw predicate kept) | no | RELATES_TO |

\*Functional means at most one current object per subject (and per `role` where the predicate takes one). Only functional predicates can conflict. "Brain-Core USES(language) Python" and "Brain-Core USES(index) SQLite" coexist. "Brain-Core USES(graph-database) Neo4j" and "Brain-Core USES(graph-database) Kuzu" with overlapping known validity produce a **conflict** (J.2). Both claims keep their lifecycle, origin and verification.

**`role` is part of what a functional predicate means**, so it is part of the claim's identity (F.3). Without it, "uses Neo4j as the graph database" and "uses Neo4j as a cache" would be one claim. The role vocabulary for `USES` is open text in v1, normalised (lowercase, hyphens), and listed by the M0 census **[Q]**.

**[Q]** The predicates already in users' `relations` tables are unknown to this audit; it did not open the owner's database. M0's census counts them, so the mapping table gets fixed from real data before v1 is frozen.

### F.3 Claim model (pydantic) [P][T]

The code below is the shape the prototype checked (`claim_model.py` in the session scratchpad). The checks:

- the role changes the id; dates and sources do not
- a claim survives deletion of one of its two source files
- an unknown start evaluates to `unknown`, not `true`
- a retraction keeps origin and verification
- a re-assertion after an end opens a second period of the same claim
- validators reject an accepted claim that is unverified, and a timeless claim that has dates

```python
class Lifecycle(StrEnum):          # review state of the assertion, nothing else (J.2)
    CANDIDATE = "candidate"        # proposed by extraction or inference, not reviewed
    ACCEPTED = "accepted"          # stated, approved, or derived from records written on purpose
    REJECTED = "rejected"          # refused at review, or retracted after acceptance

class Origin(StrEnum):             # how ONE evidence row came to be
    USER = "user"; AGENT = "agent"; MARKUP = "markup"; EXTRACTED = "extracted"
    INFERRED = "inferred"; REFLECTION = "reflection"; EXTERNAL = "external"

class Verification(StrEnum):       # how strongly a claim is vouched for; strongest evidence wins
    STATED = "stated"              # a relation written on purpose (relations.md, brain_remember)
    APPROVED = "approved"          # an extracted or inferred candidate a person approved
    DERIVED = "derived"            # a deterministic rule over records written on purpose
    UNVERIFIED = "unverified"      # extracted / inferred / reflection / external, not reviewed

class ClaimKey(BaseModel, frozen=True):
    """What is asserted. The id hashes this and nothing else."""
    subject: str                   # entity UUID, after merged_into is followed
    predicate: str                 # ontology name, after `renames:`
    role: str = ""                 # qualifies a functional predicate
    object_entity: str | None = None
    object_literal: str | None = None
    datatype: Literal["text", "int", "version", "port", "url", "date"] | None = None
    # validator: exactly one object; a literal needs a datatype

    def id(self) -> str:
        obj = ["e", self.object_entity] if self.object_entity else \
              [f"l:{self.datatype}", " ".join(str(self.object_literal).split())]
        raw = json.dumps(["claim/1", self.subject, self.predicate, self.role, *obj])
        return hashlib.sha256(raw.encode()).hexdigest()[:32]

class Evidence(BaseModel, frozen=True):
    """One record supporting one claim. All provenance lives here."""
    record_id: str                 # records_fts.rid (content hash)
    source_path: str               # store-qualified file ("vault:decisions_log.md", "notes:/abs/x.md")
    line: int = 0                  # with source_path and rule: the occurrence, the row's identity
    stated_date: date | None       # the date the text gives (bullet suffix, heading); None = undated
                                   # line (0.9.0 meaning). Valid-time evidence only: it can be backdated
    recorded_at: datetime          # transaction time, from brain-core's clock (record_ledger), never
                                   # from the text: the write, else the first ingest (J.1)
    recorded_by: Literal["write", "ingest", "git"]   # which clock gave recorded_at
    event_date: date | None = None # the day of the event the record describes, when stated
    valid_from: date | None = None # a start the record states (meta `valid:`, a decision's date)
    valid_to: date | None = None   # an end it states (meta `until:`), exclusive
    timeless: bool = False         # meta `valid: always`; never inferred
    origin: Origin
    verification: Verification
    confidence: Literal["high", "medium", "low"] | None = None
    quote: str                     # 1..300 chars; must occur in the record (grounding check)
    rule: str                      # "relations.md/1", "decision-field/1", "extract:<model>/<date>"
    # validators: timeless takes no dates; valid_to > valid_from
    @property
    def occurrence(self) -> tuple[str, str, int, str]:      # the evidence row's identity (B)
        return (self.record_id, self.source_path, self.line, self.rule)

class Period(BaseModel, frozen=True):
    valid_from: date | None        # a stated start; None = unknown, NEVER "since always"
    valid_to: date | None          # exclusive end; None = no known end
    asserted_from: date | None     # earliest stated_date asserting it in this period (valid time, from text)
    timeless: bool = False
    def at(self, d: date, today: date) -> Literal["true", "false", "unknown"]: ...  # J.1

class Conflict(BaseModel, frozen=True):
    other: str                     # the conflicting claim's id
    kind: Literal["functional_overlap"]
    overlap_from: date | None
    overlap_to: date | None
    acknowledged: bool = False     # `ack` in claim_reviews.md: both true, by the user's word

class Claim(BaseModel):
    id: str                        # == key.id()
    key: ClaimKey
    lifecycle: Lifecycle           # from verification + claim_reviews.md (G.2)
    verification: Verification     # strongest over evidence
    origins: frozenset[Origin]     # every evidence row's origin, kept through conflicts
    evidence: list[Evidence]       # min 1: a claim with no evidence does not exist
    periods: list[Period]          # min 1; sorted; never overlapping
    conflicts: list[Conflict] = []
    retracted_at: date | None = None
    # validators: id == key.id(); ACCEPTED requires verification != UNVERIFIED;
    #             no two evidence rows with the same occurrence;
    #             retracted_at requires REJECTED
    @property
    def disputed(self) -> bool: return any(not c.acknowledged for c in self.conflicts)
```

The brief's categories, on this model:

| Category | Representation |
|---|---|
| Verified fact | `accepted` with verification `stated` or `approved` |
| User-provided | an evidence row with `origin=user` |
| AI-extracted | `origin=extracted`: `candidate` / `unverified` until approved |
| AI assumption | `origin=inferred`: never accepted without approval |
| Proposed decision | a pending decision in `executive_state.md`; claims from the extraction inbox are `candidate` |
| Approved decision | a `decisions_log.md` entry; its claims are `accepted` / `derived` |
| Outdated | still `accepted`, its last period has a `valid_to` (J.2) |
| Contradictory | a conflict row; `disputed` is true while it is not acknowledged |

### F.4 Worked example (the brief's Neo4j case) [P][T]

Vault, canonical:

```markdown
## 2026-11-21 — Graph database for Brain-Core
**Decision:** Use [[Neo4j]] as the Brain-Core graph database.
**Reason:** Cypher, mature GraphRAG library.
**Classification:** reversible × high-risk
**Confidence:** medium

## 2026-12-10 — Graph database for Brain-Core (2)
**Decision:** Replace [[Neo4j]] with [[Kuzu]] as the graph database.
**Reason:** Neo4j needs a JVM service; the lite install must stay one file.
**Classification:** reversible × high-risk
**Confidence:** high
```

plus a line the agent wrote the next day in `relations.md`:

```markdown
- [[Brain-Core]] —[USES: graph-database]→ [[Neo4j]] (2026-11-22)
```

The second decision is linked to the first by the existing repeated-title rule, which records `supersedes` (`vault.py`, `_insert_entry`). The derived state on 2026-12-12:

```json
[
  {"id": "3f9c…", "key": {"subject": "<Brain-Core>", "predicate": "USES", "role": "graph-database",
                          "object_entity": "<Neo4j>"},
   "lifecycle": "accepted", "verification": "stated", "origins": ["markup", "agent"],
   "periods": [{"valid_from": "2026-11-21", "valid_to": "2026-12-10", "asserted_from": "2026-11-21"}],
   "evidence": [
     {"record_id": "9f2c…", "source_path": "vault:decisions_log.md", "line": 12, "stated_date": "2026-11-21",
      "recorded_at": "2026-11-21T09:14:02Z", "recorded_by": "write", "event_date": "2026-11-21", "valid_from": "2026-11-21", "origin": "markup", "verification": "derived",
      "quote": "Use [[Neo4j]] as the Brain-Core graph database.", "rule": "decision-field/1"},
     {"record_id": "1b7e…", "source_path": "vault:relations.md", "line": 3, "stated_date": "2026-11-22",
      "recorded_at": "2026-11-22T17:40:51Z", "recorded_by": "write", "origin": "agent", "verification": "stated",
      "quote": "[[Brain-Core]] —[USES: graph-database]→ [[Neo4j]]", "rule": "relations.md/1"}],
   "conflicts": []},
  {"id": "c41a…", "key": {"subject": "<Brain-Core>", "predicate": "USES", "role": "graph-database",
                          "object_entity": "<Kuzu>"},
   "lifecycle": "accepted", "verification": "derived", "origins": ["markup"],
   "periods": [{"valid_from": "2026-12-10", "valid_to": null, "asserted_from": "2026-12-10"}],
   "evidence": [{"record_id": "a71d…", "source_path": "vault:decisions_log.md", "line": 4,
                 "stated_date": "2026-12-10", "recorded_at": "2026-12-10T08:02:37Z", "recorded_by": "write",
                 "event_date": "2026-12-10", "valid_from": "2026-12-10",
                 "origin": "markup", "verification": "derived",
                 "quote": "Replace [[Neo4j]] with [[Kuzu]] as the graph database.", "rule": "decision-field/1"}],
   "conflicts": []}
]
```

The Neo4j claim's period ends on 2026-12-10 because the record that supersedes its decision evidence (`record_links`) does not assert it. The two periods do not overlap, so there is no conflict. If someone later deletes the first decision entry, the Neo4j claim survives on its `relations.md` evidence. Its period becomes `valid_from: null, asserted_from: 2026-11-22`, so "what did we use in June?" now answers *unknown* rather than *Neo4j* **[T]**.

The questions on 2026-12-12:

| Question | Answered from |
|---|---|
| Originally selected | the earliest period over the claims of (Brain-Core, USES, graph-database) |
| Why it changed | the **Reason** field of the superseding record |
| When it changed | the end of that period and the superseding record's `event_date` |
| Which decisions were affected | records whose claims `APPLIES_TO` or `MENTIONS` Neo4j with a period overlapping [2026-11-21, 2026-12-10) |

### F.5 Entity resolution, duplicates, merging [P]

1. **Normalise.** NFKC, casefold, collapse whitespace, strip surrounding punctuation and a trailing version (`Neo4j 5.18` → `neo4j`, with the version kept as a `VERSION` literal claim when it matters).
2. **Exact.** Look up the alias table. One hit resolves it.
3. **Ambiguous.** Two or more hits (e.g. "Atlas" the agent and "Atlas" the database): resolve by the entity type the predicate's domain or range expects. Still ambiguous: a candidate in the inbox, and the evidence row keeps the raw name until it resolves.
4. **Near.** Same type and token Jaccard ≥ 0.8, or edit distance ≤ 2 on names of 6 characters or more: a **merge suggestion** in the inbox. It is **never automatic**. Hindsight's docs admit that fuzzy merging over-merges **[E]**.
5. **Merge.**
   - The surviving note gains the loser's aliases; the loser's note gets `merged_into: <uuid>` and stays. Ids are never reused.
   - Claim keys are computed on survivor ids (`merged_into` is followed), so a merge re-keys the affected claims.
   - `claim_reviews.md` lines carry their full key as well as the id, so reviews follow the merge (G.2).
   - Log an `entity_merged` event.
6. **Validation.** A claim whose subject or object type violates the predicate's domain or range is downgraded to `RELATED_TO` (the raw predicate kept) and flagged in `brain_status`. It is never silently dropped.
7. **Ontology versioning.**
   - `ontology.yaml` ships in the package with `version: 1`, the types, the predicates, domain and range, the functional flags and a `renames:` map. An entity note records `ontology: N`.
   - A version bump is a rebuild of the derived tables (like `FORMAT` today) and never rewrites a vault file.
   - A predicate rename re-keys the claims it touches, the same way a merge does.

---

## G. Knowledge ingestion design

### G.1 Requirements against what exists

| # | Requirement | Today [V] | Proposal [P] |
|---|---|---|---|
| 1 | Obsidian file watching | Not present. The index syncs **on every search** by file signature, so it is always fresh at query time | **Do not add a watcher.** A daemon would break the lite install and add nothing to freshness. M0 measures the cost of a no-change sync on the real vault |
| 2 | Scheduled reconciliation | `brain daily` runs every day; `brain index` fills vectors | `brain index --check`: rebuild into a temporary database and diff it against the live derived tables (G.2 invariant); should be zero |
| 3 | Content hashing | Record ids are content hashes; raw sources carry sha256; files are re-read on an mtime and size change | Keep. Claim ids hash the assertion key (F.3) |
| 4 | Document revisions | Append-only, banners, `.prev.md`; the git history of the vault if the user keeps one | Validity periods, stated dates and ledger recording times on evidence (J.1). Optional git commits of the vault after `brain_session('end')` **[Q]** |
| 5 | Incremental chunk processing | Per file; a file is replaced as a whole inside one transaction (`index.py:217`) | Same unit for every raw derived row (G.2) |
| 6 | Section-aware chunking | Facts: one bullet. Decisions and corrections: one entry. Knowledge: one `##` section. Session files: one block | Keep. Add fence awareness so a `## ` inside fenced code is not a heading. Raw sources are indexed by their title alone, with their frontmatter kept on the record (`vault.py:334–345`), so a raw body is not searchable: the compiled knowledge page is what recall finds **[V]**. Leave it that way unless the eval shows misses that only a raw body could answer |
| 7 | Entity extraction | None | Deterministic first: wikilinks, `#tags` and alias matches give `MENTIONS`. LLM extraction is optional, a batch run, and goes to the inbox |
| 8 | Relationship extraction | Explicit `kind='relation'` only | Deterministic: `relations.md` lines; decision fields (`SELECTS` from a wikilink in **Decision:**); `record_meta.md` `supersedes`. LLM: optional, as above |
| 9 | Claim extraction | None | As 7 and 8: each rule emits `(ClaimKey, Evidence)` pairs with a verbatim quote |
| 10 | Entity resolution | None | Section F.5 |
| 11 | Duplicate detection | Jaccard 0.8 on facts and patterns; title rule on decisions and corrections | Claim ids are assertion hashes, so a second record of the same assertion is a second evidence row, not a second claim |
| 12 | Source provenance | `path:line` on every result; optional `source` | Every evidence row carries `origin`, `rule`, `source_path`, `line` and a quote (THREAT_MODEL gate 2 becomes "built" for claims) |
| 13 | Graph indexing | Relations rows | Entities, aliases, mentions, evidence and computed claims in SQLite, from the vault |
| 14 | Vector indexing | `record_vectors`, filled lazily (16 per recall or save, everything at `brain index`) | Keep. Entity notes become records too, so "Neo4j" finds its note |
| 15 | Errors and retries | An unreadable file is skipped and named in health; a missing vault is an error; the Hindsight queue | A file that fails to derive keeps its old raw rows (the signature is not updated), exactly like today's index |
| 16 | Deleted and moved files | Delete: rows dropped. Move: delete plus add | Delete: the file's evidence rows go, and each claim it touched is recomputed; a claim with other evidence survives. Move: delete plus add of the same records; claim ids do not depend on paths, so the claims stay |

### G.2 Claim derivation and reconciliation [P][T]

This replaces the first revision's `claims.source_path`. One file can support many claims and one claim can rest on many files, so ownership by file only works for rows that come **from** exactly one file.

**Two kinds of derived rows.**

| Kind | Tables | Rule |
|---|---|---|
| **Raw rows**, each read from exactly one vault file and carrying its `source_path` | `records_fts` (exists), `mentions`, `claim_evidence`, `record_times` (`valid` / `until` / `event` / `valid: always` from `record_meta.md`), `record_links` (`supersedes` from `record_meta.md`), `claim_reviews` (from `claim_reviews.md`) | Rebuilt per file, in the transaction that re-indexes that file |
| **Computed rows** | `claims`, `claim_periods`, `claim_conflicts`, `entities.degree` | A pure function of the raw rows, `ontology.yaml` and today's date (for "current" only). Never edited, only recomputed |

**Per changed file F, in one transaction:**

```
dirty := claims with evidence from F                                   (before the change)
       ∪ claims with evidence on records named by F's record_times / record_links rows
       ∪ claims named by F's claim_reviews rows
delete F's raw rows; derive F's raw rows again
dirty ∪= the same three sets after the change
recompute(dirty):
    claim rows:    upsert every key in dirty that has ≥ 1 evidence row; delete the others
                   (with their periods and conflicts)
    for each claim: periods from its evidence + record_times + record_links (J.1);
                    verification, origins, confidence from its evidence;
                    lifecycle from verification + claim_reviews (J.2); rank (H.3)
    conflicts:     for every (subject, predicate, role) group touched by dirty, all pairs
                   in the group, not only the dirty ones
    degree:        every entity a dirty claim names
update F's signature in index_files       (last: a crash before it means F is derived again)
```

**Properties.**

1. **Multi-source survival.** An evidence row is an *occurrence*, keyed `(claim_id, source_path, line, rule)`, so the same record text in two files is two rows. That case exists today: the index can hold one record id under two stores (`vectors.py:_records` de-duplicates for that reason) **[V]**. Deleting or editing F removes only F's evidence. A claim with evidence elsewhere keeps its id and is recomputed with what is left: fewer origins, possibly a weaker verification, possibly a later `asserted_from` **[T]**.
2. **Cross-file effects are explicit.** `record_meta.md` and `claim_reviews.md` change other files' claims only through the dirty set above. Entity notes change name resolution, so they are synced first in every pass. A changed alias marks dirty every evidence row whose raw subject or object name matches it; the evidence keeps the raw names for exactly this.
3. **Re-keying.** A merge or a predicate rename changes some claim keys. The affected evidence rows are re-derived, and the reviews follow because each `claim_reviews.md` line stores its key, not only the id: `- 2026-12-12 | reject | 3f9c… | <subject> USES(cache) <object> | reason`.
4. **Idempotence and the invariant.** Deriving a file twice changes nothing. For any sequence of file edits, the incremental state equals a full rebuild. M3 tests this with `hypothesis` (already a dev dependency): random edit, delete and move sequences on a fixture vault. `brain index --check` runs the same comparison on the real vault.
5. **No outbox.** All of the above lives in `brain.db`, so one transaction per file is atomic, and the file signature is the retry marker. The one external write, Hindsight, keeps its per-layer status and its queue file, which already works as an outbox.

### G.3 The pipeline, mapped onto the brief's diagram

```
change detection   = index_files signature (exists)
parser             = VaultStore._records + knowledge_records (exists) + links/tags/aliases/fences (new)
normalisation      = normalize(), redact() (exists)
chunking           = per kind, as G.1 row 6 (exists)
extraction         = deterministic rules → (ClaimKey, Evidence) (new); LLM batch → inbox candidates (new, optional)
resolution         = alias table + inbox (new)
schema validation  = pydantic ClaimKey/Evidence + ontology.yaml (new)
indexing           = one SQLite transaction per file: raw rows, then recompute(dirty) (G.2)
index validation   = brain index --check (rebuild-and-diff), brain doctor counts (new / extend)
```

If a projection to Neo4j is ever kept live (not proposed), it gets `projection_outbox(claim_id, version, target, done_at)` with idempotent `MERGE` upserts. Until then projections are full rebuilds (L.5).

---

## H. Retrieval and reasoning design

### H.1 What already exists and stays [V]

Recall is already a retrieval orchestrator; it does not need replacing:

- routing by scope
- parallel nets fused by rank
- exact-identifier pinning
- a supersession rule
- an optional LLM judge, which reranks and says whether the candidates answer
- abstention (`weak_match`, `not_in_memory`)
- capped, cited output

The brain-core design intentionally leaves **answer generation to the calling agent**, under a citation rule (`04-memory.md`: "Confabulated recall is worse than admitted amnesia"). The brief's pipeline ending in "LLM answer generation" is the agent's turn, not a brain-core module.

### H.2 Query understanding and planning, without an LLM [P]

The latency budget is about 45 ms for keywords, about 150 ms with vectors and about 4 s with the judge **[M]**. An LLM router would double the judge path's cost to choose between nets that cost milliseconds. So the planner is deterministic signals switching nets on:

| Signal (existing / new) | Turns on |
|---|---|
| always | keyword net |
| `stores.vectors` set | vector net |
| a day in the question (`days_asked`, exists) | date net |
| an identifier (exists) | exact pin |
| **an entity alias** found in the question (longest n-gram match against `aliases`, like `identifiers()`) | **graph net** |
| **a cue word for time**: originally, first, before, used to, changed, since, until, why did we, history | **history mode**: ended periods and `unknown` claims kept and marked, chains returned whole |
| `as_of` parameter (new, optional) | validity at that day (J.1) for claims and for the supersession rule |

### H.3 The graph net: bounded traversal [P][T]

**Why the first revision's query was wrong.** It was one recursive CTE with `LIMIT :cap` at the end. SQLite generates every row of the walk before the outer `GROUP BY … LIMIT` applies, so the cap bounded the output, not the work. On a prototype graph with a hub of 10,000 neighbours, each with 30 more, a 2-hop walk from the hub generated **320,005 rows in 247 ms** before returning 50 **[T]**. Per-entity limits cannot go inside a recursive CTE either: SQLite forbids aggregate and window functions in the recursive step.

**The revised walk.** Breadth-first in Python, with two small indexed queries per expanded entity:

| Rule | Value (defaults; M0 sets them from the degree census) |
|---|---|
| Seeds | entities linked from the question, at most `max_seeds = 5`, in order of mention |
| Depth | `max_hops = 2` by default, hard cap 3 (asserted) |
| Per entity and direction (work) | read at most `scan = 80` index rows in `(rank, id)` order, **then** apply the validity filter |
| Per entity (output) | keep at most `fan = 20` edges **across both directions**, merged in one `(rank, id, direction)` order, skipping claims already listed |
| Hub | `degree > hub_degree = 200`: expanded only as a seed. Reached through a path, it is a terminal: listed, never expanded |
| Per hop | at most `max_frontier = 50` entities expanded, in discovery order |
| Total | at most `max_edges = 200` edges, then stop |
| Cycles | a visited set: each entity is expanded once, at its least depth; and a claim reached from its other end is listed once |
| Order | `rank` (an open period first, then predicate priority from `ontology.yaml`), then claim id: the same vault always gives the same walk |
| Truncation | each of these sets `truncated` and names where it happened:<br>• seeds beyond `max_seeds`<br>• a frontier larger than `max_frontier`<br>• a scan window that came back full<br>• `fan` reached with rows left<br>• a hub reached through a path (also listed in `hubs`)<br>• `max_edges` reached<br>Recall reports "graph expansion truncated at <entity>", never silence |

Bounds: at most `max_edges` edges; at most `2·scan·(max_seeds + max_frontier)` edge rows read; at most `5·(max_seeds + max_frontier)` queries, each touching at most `scan` index entries. That is the degree check, then per direction the edge query and a bounded count that tells whether the scan window was full. Here that is 200 edges, 8,800 rows and 275 queries, all independent of the hub's degree.

**The query, one direction** (the other uses `idx_claims_in` and returns `c.subject`):

```sql
SELECT * FROM (
  SELECT c.object_entity AS dst, c.id AS id, c.predicate, 1 AS forward, c.rank
    FROM claims c                                  -- idx_claims_out (subject, lifecycle, rank, id)
   WHERE c.subject = :src AND c.lifecycle = 'accepted' AND c.object_entity IS NOT NULL
   ORDER BY c.rank, c.id
   LIMIT :scan) AS c                               -- work bound: at most :scan index entries
 WHERE :history = 1 OR EXISTS (                    -- TRUE at :d (as_of, else today), J.1
   SELECT 1 FROM claim_periods p WHERE p.claim_id = c.id AND (
        p.timeless = 1
     OR ((p.valid_to IS NULL OR p.valid_to > :d) AND (
            coalesce(p.valid_from, p.asserted_from) <= :d
         OR (:d = :today AND coalesce(p.valid_from, p.asserted_from) IS NULL)))))
 ORDER BY c.rank, c.id;
```

`:d` is the `as_of` day, or today when none is given, so a walk without `as_of` still drops ended claims. History mode (`:history = 1`) takes every accepted claim, and Python marks each one TRUE, UNKNOWN or FALSE with `Period.at`. The prototype ran this query without the `:history` term.

The walk, as prototyped:

```python
def walk(db, seeds, lim, d, today) -> tuple[list[Edge], Stats]:
    asked = list(dict.fromkeys(seeds))
    seeds = asked[: lim.max_seeds]
    stats.truncated = len(asked) > lim.max_seeds                    # extra seeds: reported
    depth = {s: 0 for s in seeds}
    frontier, edges, seen = list(seeds), [], set()
    for hop in range(1, lim.max_hops + 1):                         # max_hops <= 3, asserted
        nxt = []
        stats.truncated |= len(frontier) > lim.max_frontier         # a cut frontier: reported
        for node in frontier[: lim.max_frontier]:
            if degree(node) > lim.hub_degree and depth[node] > 0:  # hub reached on a path
                stats.hubs.append(node); stats.truncated = True; continue
            out, full_out = out_edges(node)                        # each: <= scan rows, and whether
            inc, full_in = in_edges(node)                          # its scan window came back full
            stats.truncated |= full_out or full_in
            rows = sorted(out + inc, key=lambda r: (r.rank, r.id, r.forward))   # fan is across both
            kept = 0
            for r in rows:
                if r.id in seen: continue                          # one claim, listed once
                if kept == lim.fan: stats.truncated = True; break
                kept += 1; seen.add(r.id); edges.append(Edge(hop, node, r))
                if r.dst not in depth: depth[r.dst] = hop; nxt.append(r.dst)   # visited set
                if len(edges) >= lim.max_edges: stats.truncated = True; return edges, stats
        frontier = nxt
    return edges, stats
```

**Measured [T]** on 310,004 claims (the hub, 10,000 × 30 below it, and a cycle A→B→C→A where A also touches the hub):

| Case | Result |
|---|---|
| Seed = the hub, 2 hops | 200 edges (cap), 363 edge rows read, 55 queries, about 1 ms, `truncated` |
| Seed = A, next to the hub | 4 edges, 7 rows, 16 queries, 0.1 ms, `truncated` (the hub). The hub is listed as a terminal; none of its 10,000 neighbours appear; the cycle ends with each claim once |
| `as_of` 2026-01-15 from the hub | 20 edges, all hop 1. The hop-2 claims are only known from February, so they are `unknown` then and not asserted |
| A date that rejects all 10,000 hub claims | about 2,000 SQLite VM steps with the `LIMIT` inside, against about 180,000 with the filter inside the `LIMIT` (the first draft's shape) |
| Query plans | `SEARCH c USING INDEX idx_claims_out (subject=? AND lifecycle=?)`, and `idx_claims_in` likewise; no table scan, no temporary sort |

**A pitfall the prototype caught.** A *partial* index (`WHERE lifecycle <> 'rejected'`) is not used for a query that says `lifecycle = 'accepted'`: SQLite does not prove the one implies the other, and it silently scans the table (140 ms instead of 0.7 ms) **[T]**. Hence the plain composite indexes in L.1, and a query-plan assertion in the test.

**The cost of the work bound.** Valid edges beyond an entity's first `scan` index rows are missed for a historical `as_of` on a hub. Open periods sort first, so the current case is unaffected. The miss is reported as `truncated`, never silent.

**The test to add in M4** (`tests/unit/test_graph_walk.py`; the prototype is its first draft):

- Build the hub graph above; it builds in under 1 s.
- Assert edges ≤ `max_edges`, edge rows read ≤ `2·scan·(seeds+frontier)`, queries ≤ `5·(seeds+frontier)`.
- A hub reached through a path is not expanded, and it sets `truncated`. Every other cut sets it too: extra seeds, an oversized frontier, a full scan window, `fan`, `max_edges`.
- The cycle terminates, with each claim once.
- Two runs are identical.
- `as_of` excludes `unknown` claims.
- `EXPLAIN QUERY PLAN` names `idx_claims_out` / `idx_claims_in` with no `TEMP B-TREE`.
- The nothing-valid case costs under 1/20 of the filter-first query's VM steps, counted with `set_progress_handler`. VM steps and row counts are used rather than milliseconds, so the test is not flaky in CI.

**Into recall.** The walked claims' evidence records, plus the records that `MENTIONS` a seed, form `nets["graph"]`: ordered by hop, then by the record's keyword score. They join `_join` exactly as `nets["date"]` does today (`recall.py:349`). `found_by` gains `graph`, and the result carries `path: "Brain-Core —USES(graph-database)→ Kuzu"`. The walked claims also go out in a structured `claims` block (M.1).

### H.4 Temporal retrieval [P]

- `as_of: D` evaluates claims with J.1. TRUE claims are asserted. UNKNOWN claims appear only in history mode, marked `validity: "unknown"` with the reason ("first stated 2026-11-22; start not stated"). FALSE claims appear only in history mode, as `before` or `ended`.
- Text records are never filtered by `as_of`: a record about another time can still be the answer ("why did we change?"). Two things change: records that evidence TRUE claims gain a graph-net place, and the supersession rule becomes relative to D. An old record stays above its replacement when the replacement's period, or its recorded date if it has no period, starts after D.
- History mode returns a supersession chain in order (old → new), each record marked `superseded` as today, with the successor's **Reason** included.
- Without `as_of`, everything is exactly as 0.9.1 behaves, plus the graph net.

### H.5 Python interfaces [P]

Extract only what the fourth net needs. These are protocols over the existing tuple shape `Hit = (Record, store, score)`:

```python
Hit = tuple[Record, str, float]
InScope = Callable[[Record, str], bool]

class Signals(Protocol):                 # computed once per recall, no I/O after this
    identifiers: list[str]
    days: list[str]
    entities: list[str]                  # entity UUIDs linked from the question
    history: bool
    as_of: date | None

class Net(Protocol):
    name: str                            # "keyword" | "vector" | "date" | "graph" | "hindsight"
    def wanted(self, query: str, signals: Signals) -> bool: ...
    def search(self, query: str, signals: Signals, candidates: int, in_scope: InScope) -> list[Hit]: ...

class Projection(Protocol):              # bench only: Neo4j
    target: str
    def export(self, entities: Iterable[Entity], claims: Iterable[Claim], records: Iterable[Record]) -> None: ...
```

`recall.brain_recall` keeps its signature and its post-processing (pin, current, judge, cover, cap). Only the place where `nets` is built becomes `{n.name: n.search(...) for n in nets if n.wanted(...)}`. Database detail stays behind each `Net`. The orchestrator never sees SQL, Cypher or HTTP.

### H.6 KAG and GraphRAG in this design [P]

- **Neo4j GraphRAG** is reached only through a bench `Net` that queries its projection. It is compared in `run_gold.py` like any other configuration.
- **KAG** is not integrated (E.3). Two of its ideas are already in this design: `mentions` plus `claim_evidence` are a node↔chunk mutual index; typed literal claims make simple numeric questions computable. Its planner and solver are not replaced by anything here; H.7 says what that leaves out.
- **Global questions** ("what keeps going wrong?", "what are the priorities?") go to mental models, which already exist, cite every bullet, and are kept out of recall by design. The agent reads them at session start. A new model item is a line in `brain.yaml`, not new code.

### H.7 Reasoning capabilities: what the judge is, what KAG adds [P]

The first revision said KAG reasoning was "covered by the judge plus the agent". That was wrong. The judge is a ranking and relevance step: it reads up to 50 records and returns the numbers of those that answer, or says none does (`judge.py`). It does not chain facts, execute operators or compute anything.

| Capability | What it means | brain-core today [V] | Can be native in brain-core [P] | Still needs a specialised reasoning engine |
|---|---|---|---|---|
| **Retrieval and reranking** | find candidate records and order them | keyword, vector and date nets; RRF; identifier pin; supersession rule; the judge as an optional LLM reranker | the graph net; `as_of` | — |
| **Evidence validation** | check that what is returned actually supports the claim or answer | partial: the judge says whether candidates answer the question (`answered` / `partial` / `not_in_memory`) and can only cite records it was shown. It does not check that a claim is entailed by its record, nor that the agent's final answer cites correctly | the grounding check (the evidence quote occurs verbatim in its record); provenance and verification on every claim; citation precision measured in the eval (O.4) | entailment checking at scale (an NLI model): not needed now |
| **Agent-driven reasoning** | an LLM decomposes, calls tools again, combines | Claude Code does it, without structure: no plan object, no guaranteed coverage, no trace but the transcript | better steps for it: steering text (`weak_match`, `thin_recall`, `truncated`), structured `claims` blocks, history mode | — |
| **Logical-form-guided reasoning** | the question becomes an explicit plan of typed operators (retrieve, filter, deduce, compute) with variables bound between steps, run by a solver | none | a small fixed set of deterministic lookups the agent can rely on: state at a date, a decision's chain, a path between two entities, every claim of a predicate for an entity. **The agent still writes the plan** | a planner that turns questions into logical forms, plus a solver that runs arbitrary forms (KAG's kg-solver with its static and iterative planners **[E]**) |
| **Symbolic execution** | deterministic evaluation over structured facts: joins, transitive closure, interval logic, rule inference | none (the supersession chain walk is the nearest) | SQL over claims: bounded transitive closure (DEPENDS_ON\*), interval overlap, inverse relations, domain and range checks, each result citing its claims | general rule inference (Datalog or OWL-style reasoning), user-defined rules, consistency proofs over the whole graph |
| **Numerical reasoning** | arithmetic, counting, comparison over values | none; the agent reads numbers out of text | typed literal claims (`port`, `version`, `int`, `date`) make count, min, max, compare and date difference exact in SQL, or left to the agent over the `claims` block | free-form numeric problems spread over many documents (KAG's math executor, LLM-generated expressions **[E]**) |

**Revisit KAG, or any solver, only when both hold:**

1. after M4, the O.2 `logical` and `numeric` slices are the largest remaining miss class
2. the project is maintained again

Until then the agent plus deterministic lookups is the design, and its limits are measured, not assumed away.

---

## I. Persistent memory design

### I.1 The five categories already exist [V]

| Category | Where it lives today | Lifecycle today | Gap / proposal [P] |
|---|---|---|---|
| Working | `executive_state.md` (objective, missions, pending decisions), `goals/`, `inbox_staged.md`, the session start block, `capture.checkpoint` after compaction | Rewritten by `brain_session('end')`, the old file kept as `.prev.md` | Open conflicts and waiting candidates shown at session start |
| Episodic | `sessions/YYYY-MM-DD.md` (HSAM sections), the `events` journal, the transcript index, monthly archives | Daily file → archived after 30 days with a summary (`cron.consolidate`) | Mark hook-captured lines (*Said (hook)*) `provisional` and weight them 0.7, like transcripts (G8) |
| Semantic | `facts.md`, `knowledge/`, `decisions_log.md`, relations | Append-only, banners, `supersedes` | Entities and claims (F); relations into the vault (G1) |
| Procedural | `procedures/`, `.claude/rules/`, skills, `patterns.md` | Rule drafts after 3 corrections on one theme (`cron.rule_drafts`, `DRAFT_AFTER = 3`) | None structural; claims can link a pattern `APPLIES_TO` a project |
| Reflective | `corrections.md` (error / correction / rule / theme / promoted), `session_critique.md`, `knowledge/_reflections.md` (unverified, not indexed), traits | The optional lessons hook (`brain lessons`, UserPromptSubmit); themes; promotion | Enforce THREAT_MODEL gate 3: a reflection's claims must cite parent claims, and otherwise stay `candidate` with origin `reflection` |

### I.2 Lifecycle and policies [P]

| Stage | Policy |
|---|---|
| Capture | Explicit `brain_remember` (stated) and the hook floor (provisional). **No message becomes semantic memory by being said**; the hook writes only episodic notes |
| Classify | `kind` at write time (exists); claims by ontology |
| Extract | Optional batch → candidate lines in the inbox |
| Validate | Secret gate (exists), pydantic + ontology, grounding quote |
| Deduplicate | Jaccard and title rules (exist); claim ids are assertion hashes; alias table |
| Detect conflicts | Lexical banner (exists); functional-predicate overlap → a `claim_conflicts` row. Lifecycle, origin and verification are not changed (J.2) |
| Consolidate | Weekly archive and mental models (exist) |
| Expire | Working memory is overwritten each session (exists). Episodic files are archived, never deleted. Semantic claims never expire: their periods end. Candidates are never auto-rejected; the daily brief shows how many wait and the oldest age |
| Retrieve | Section H |
| Update | Never in place: a new line plus `supersedes` (exists), or a stated `until:`; the claim's period ends |
| Provenance | Origin, rule, source and quote on every evidence row; `path:line` on every record |
| Version history | Append-only files, `.prev.md`, periods, `claim_reviews.md`; optional vault git commits **[Q]** |

---

## J. Temporal and decision intelligence

### J.1 Time fields and `as_of` semantics [P][T]

**The fields.** This resolves the first revision's mismatch, where the pydantic model required `recorded_at` and the SQL allowed NULL. It also resolves review point A: a date written in markdown can be backdated, so it cannot be a transaction time.

**The rule.** Valid time comes from the text; transaction time comes from clocks.

- **The date the text gives** is `stated_date`. It is nullable, because 0.9.0 deliberately stopped giving undated lines their file's date (CHANGELOG 0.9.0, `vault.py:398`).
- **When the vault held the record** is `recorded_at`, and it is never NULL once a record is ingested.

| Field | Belongs to | Meaning | Source in the vault | NULL means |
|---|---|---|---|---|
| `stated_date` | evidence | the date the text gives the record. What the writer claims, so it can be backdated by a hand edit; **valid-time evidence only** | bullet suffix `(YYYY-MM-DD)`; an entry heading date; a session file's day | the line carries no date (`undated`) |
| `recorded_at` | evidence (from `record_ledger`) | **transaction time**: when the record's exact text entered the vault, by brain-core's clock | `written_at` when `brain_remember` wrote it; otherwise the earliest of `first_ingested_at` and, if the vault is a git repository and the owner opts in, the commit that first holds the line **[Q]** | never NULL once ingested |
| `first_ingested_at` | `record_ledger` | when brain-core's indexer first saw this exact text, whoever wrote it | the sync that first parses it | — |
| `event_date` | evidence | the day of the event the record describes, when it differs or matters | a decision's or correction's heading date; `event: YYYY-MM-DD` in `record_meta.md` ("yesterday we migrated" must be stated, never guessed) | not stated |
| `valid_from` | evidence (stated), period (derived: the earliest stated in the period) | the first day the assertion holds in the world, inclusive | `valid: YYYY-MM-DD` in `record_meta.md`; for claims derived from a decision, its date (rule `decision-field/1`, **[Q]** in R) | **unknown**, never "since always" |
| `valid_to` | evidence (stated), period (derived) | the first day it no longer holds, exclusive | `until: YYYY-MM-DD`; or the start of the record that supersedes it (`record_links`) when that record does not assert it | no known end |
| `asserted_from` | period (derived) | the earliest `stated_date` among the evidence asserting it in this period: a record says it held on that day. A valid-time bound from the text, not a transaction time | computed | no dated evidence at all |
| `timeless` | evidence, period | holds at every date: a definition. **Only when stated** (`valid: always`) and never inferred from a missing start | `record_meta.md` | — |

Vault dates (`stated_date`, `valid_from`, `valid_to`, `event_date`) are whole days, ISO format, with no time zone, as everywhere in the vault. A month-only date ("since June 2026") is rejected in v1 with a message, rather than invented as the 1st **[Q]**. Ledger times are UTC timestamps, compared by local day.

**The ledger (M1).**

```sql
record_ledger(item TEXT PRIMARY KEY,    -- sha256 of the exact text: a record, a record_meta line or a review line
              written_at TEXT,          -- set when brain_remember wrote it
              first_ingested_at TEXT NOT NULL,
              first_path TEXT NOT NULL)
```

- It is **append-only**: insert-or-ignore, never updated except to fill a missing `written_at`.
- It is **not a derived table**: `brain index --rebuild` never drops it, so recording times survive rebuilds.
- It is lost only if `brain.db` itself is deleted. Re-ingesting then stamps today, which is **late, never early**, so brain-core can understate what it knew but never overstate it. `brain daily` can copy the ledger beside the existing backups **[Q]**.
- It is keyed by the exact text. An edited line is new text with a new recording time, which is correct: the vault did not hold that wording before.
- A knowledge section keeps its id across edits (`path#heading`), but its ledger key is its text hash, so it gets one ledger entry per version.
- Recording history starts the day the ledger ships. Everything already in the vault gets that first sync as its `first_ingested_at`. That is why the ledger lands in M1, well before claims need it.

**Period construction** (per claim, deterministic, prototyped):

1. Sort the evidence that has an effective start (`valid_from`, else `stated_date`) by that start, then by record id.
2. A period opens at the first such evidence.
3. An end (a stated `valid_to`, or a superseding record's start) closes the open period.
4. Later evidence after an end opens the next period of the **same claim**. A re-assertion gets no new id.
5. Undated evidence joins the period that is open at the end.
6. Any timeless evidence makes the claim timeless.

**`as_of` semantics: validity of a period on day D, with "today" = T:**

| # | Condition, in order | Result |
|---|---|---|
| 1 | `timeless` | TRUE |
| 2 | `valid_to` is set and D ≥ `valid_to` | FALSE (the end is exclusive) |
| 3 | start := `valid_from` ?? `asserted_from`; start is NULL (only undated evidence) | TRUE if D = T (an undated standing fact is current, as 0.9.0 ranks it); otherwise UNKNOWN |
| 4 | D ≥ start | TRUE |
| 5 | D < start and `valid_from` is NULL | **UNKNOWN**: before the first day any record says it held, and no start was stated. It may or may not have held |
| 6 | D < start and `valid_from` is set | FALSE (before a stated start, including a decision made now that takes effect later) |

A claim is TRUE on D if any of its periods is TRUE; else UNKNOWN if any is UNKNOWN; else FALSE. Only `accepted` claims are evaluated. A `candidate` appears only in history mode and the inbox; a `rejected` claim never appears.

The SQL predicate in H.3 returns exactly the TRUE cases. The prototype checks it against the Python function on 11 cases, including:

- the exclusive end
- a stated future start
- a fact learned after it ended (start unknown, `asserted_from` after `valid_to`: UNKNOWN before the end, FALSE after)
- an undated line (current now, UNKNOWN in the past)
- a timeless definition

**Transaction-time questions (`known_at`), defined now, exposed later.** "What did we believe on K?" evaluates the same rules, but only over:

- evidence whose `recorded_at ≤ K`
- links whose `record_meta.md` line has `recorded_at ≤ K` (the line's ledger time, not the dates written in it)
- review lines whose ledger `recorded_at ≤ K` (the date written on a review line is stated, so it is not trusted either)

All three use ledger times, never stated dates, so a backdated note cannot make brain-core appear to have known something earlier. An undated line is included from the day it was recorded. Before the ledger existed, `known_at` answers only from the first ingest, and the reply says so. Whether to expose it in `brain_recall` or only in the CLI and eval is open (R).

### J.2 Claim lifecycle, conflict state and the decision lifecycle [P][T]

**The four states the first revision proposed, evaluated:**

| State | Verdict | Why |
|---|---|---|
| `candidate` | **Keep** | Extracted, inferred, reflection or external claims that no person has approved. Ranked down, flagged, never auto-promoted |
| `accepted` | **Keep** | Stated on purpose, approved, or derived by a deterministic rule from records written on purpose |
| `rejected` | **Keep, with two causes recorded**: refused at review (`reject`), or found wrong after acceptance (`retract`, with `retracted_at`). Evidence and history stay; `known_at` before the retraction still sees it accepted | A rejection must survive rebuilds, so it is canonical: a line in `claim_reviews.md` |
| `superseded` | **Remove from the lifecycle.** It is temporal: a period ended | A superseded claim was still accepted, still verified, and true for its period. As a lifecycle state it would erase that, and it could not represent a claim that ends and later becomes true again |
| `disputed` (first revision) | **Remove from the lifecycle**; it is conflict state | Detecting a conflict must not change what the claim is; it adds a relation between two claims |

**Lifecycle derivation:**

1. `rejected` if the latest `reject` / `retract` / `restore` line for the claim in `claim_reviews.md` is `reject` or `retract`.
2. Otherwise, `accepted` if its verification is `stated`, `approved` or `derived`.
3. Otherwise, `candidate`.

Approval needs no review line: the agent moves the candidate to `relations.md` with `origin: extracted` and `approved: <date>`, so its evidence is `approved`.

**Conflict state (separate, computed).** It is computed for each functional `(subject, predicate, role)` group, over every pair of non-rejected claims with different objects.

- **Overlap.** Each claim's known interval is [`valid_from` ?? `asserted_from`, `valid_to`).
- **An unknown start is never stretched backwards.** Conflicts are found only over what is known, so "both current" counts as overlap but "both unknown in 2025" does not.
- A row in `claim_conflicts`: `(claim_a, claim_b, kind = 'functional_overlap', overlap_from, overlap_to, acknowledged)`.
- `disputed` = an unacknowledged row between two `accepted` claims. A candidate that would conflict is shown in its inbox entry instead.

Resolution is always an explicit act in the vault, and detection never edits a claim:

| Act | Effect |
|---|---|
| A temporal fix: add `until:`, or a `supersedes` link | The periods stop overlapping and the row disappears on recompute |
| A lifecycle fix: `reject` or `retract` one claim | It leaves the set |
| An acknowledgement: `ack \| other=<id>` | Both are true; the row stays, marked `acknowledged`. A role refinement is usually the better fix |

Through all of these, each claim keeps its own origins, verification, evidence and periods. Recall shows `disputed_with` with both claims' sources and verification.

**The decision lifecycle** (records, unchanged from the first revision):

```
proposed (executive_state.md → Pending Decisions)
   │ user decides
   ▼
made (decisions_log.md entry; claims SELECTS / REJECTS / APPLIES_TO derived from its [[links]])
   │ a later decision with the same title (exists: "(2)" + supersedes), or extra supersedes=<id>
   ▼
superseded (the successor's Reason answers "why"; its date ends the old claims' periods)
                                                             reversed (successor says Reverse:)
```

### J.3 Storage [P]

- **SQLite:** the evidence holds the stated times, `claim_periods` the computed ones, `claim_conflicts` the conflict state, and `claim_reviews` the review lines (L.1). Decisions stay records.
- **Neo4j (bench projection only):**
  - claims are reified as nodes: `(:Entity)-[:SUBJECT_OF]->(:Claim {predicate, role, lifecycle, verification, origins})-[:OBJECT]->(:Entity)`
  - periods hang off them: `(:Claim)-[:VALID_DURING]->(:Period {valid_from, valid_to, asserted_from, timeless})`
  - evidence: `(:Claim)-[:SUPPORTED_BY {origin, rule, quote}]->(:Record)`
  - conflicts: `(:Claim)-[:CONFLICTS_WITH {overlap_from, overlap_to, acknowledged}]->(:Claim)`
  - a convenience edge for Cypher readability: `(:Entity)-[:USES {claim_id, role}]->(:Entity)`

### J.4 Questions the design answers (they become eval questions, section O) [P]

| Question | How |
|---|---|
| "What graph database did we originally choose?" | The earliest period in the (Brain-Core, USES, graph-database) group |
| "Why did we change it?" | The superseding record's Reason |
| "When?" | The end of that period, and the successor's `event_date` |
| "What did Brain-Core use on 2026-12-01?" | `as_of`: TRUE claims only |
| "What did we use in June?" (nothing dated then) | `unknown`, with "first stated on …": never an assertion |
| "Which decisions did the switch affect?" | Claims overlapping the old interval that mention the old object |
| "What changed this month?" | Evidence with `recorded_at` (ledger) in the range; `stated_date` in the range answers "what is dated this month" |
| "What did we believe on 2026-12-05?" | `known_at` (J.1), once exposed |

## K. Repository architecture

### K.1 Do not adopt the brief's idealised tree [P]

| Brief's module | Why not |
|---|---|
| `intelligence/agent.py`, `planner.py`, `tools.py` | Duplicate Claude Code's job |
| `llm.py` | Duplicates `models.run_api` / `run_claude` |
| `api/` | Has no caller (MCP is the API) |
| `workers/` | Duplicates `cron.py` and `embed_worker.py` |

The existing layout already separates the concerns the brief lists:

| Concern | Where |
|---|---|
| Domain models | `stores/base.py`, `config.py` |
| Adapters | `stores/*` |
| Orchestration | `recall.py`, `remember.py`, `session.py` |
| LLM providers | `models.py` runners |
| Jobs | `cron.py` |

### K.2 Proposed changes [P]

```
src/brain_core/
├── ontology.yaml                 NEW  types, predicates, domain/range, functional, role, priority, renames, version
├── knowledge/                    NEW  (small: the claim layer only)
│   ├── __init__.py
│   ├── model.py                  NEW  ClaimKey, Evidence, Period, Conflict, Claim, Lifecycle, Origin, Verification (F.3)
│   ├── ontology.py               NEW  load + validate ontology.yaml; map a predicate; check domain/range
│   ├── entities.py               NEW  entity notes ↔ entities/aliases; resolve(); merge suggestions
│   ├── links.py                  NEW  wikilinks, #tags, alias matches → mentions (deterministic)
│   ├── derive.py                 NEW  per-file rules → (ClaimKey, Evidence); record_meta → record_times/record_links;
│   │                                  claim_reviews.md → claim_reviews
│   ├── reconcile.py              NEW  dirty set → claims, periods, lifecycle, conflicts, degree (G.2)
│   ├── temporal.py               NEW  period construction; Period.at; the SQL validity predicate (J.1)
│   ├── extract.py                NEW  optional LLM batch → inbox candidate lines (uses models.Runner)
│   └── projections.py            NEW  bench exporter (neo4j); not imported by the server
├── nets.py                       NEW  KeywordNet, VectorNet, DateNet (moved out of recall.py), GraphNet + walk() (H.3)
├── recall.py                     EXTEND  nets built through the Net protocol; as_of; history mode; claims block
├── remember.py                   EXTEND  relations also to the vault; ontology check; valid/until/event
├── stores/vault.py               EXTEND  relations.md; entities/; claim_reviews.md; frontmatter lists; code fences;
│                                         record_meta fields valid/until/event
├── stores/index.py               EXTEND  per-file sync also writes the raw claim rows and calls reconcile (G.2)
├── stores/graph.py               EXTEND  reads claims; keeps import_dump; relations table → read-only legacy
├── status.py                     EXTEND  claims by lifecycle and verification, open conflicts, waiting candidates,
│                                         hubs, alias collisions
├── cron.py                       EXTEND  open conflicts and waiting candidates in the daily brief
├── cli/main.py                   EXTEND  brain entities, brain extract, brain graph migrate|export,
│                                         brain index --check/--rebuild
├── storage/migrations/007_ledger.sql     NEW  (M1) record_ledger: transaction times, not derived
├── storage/migrations/008_entities.sql   NEW  (M2) entities, aliases, mentions
├── storage/migrations/009_claims.sql     NEW  (M3) claims, claim_evidence, record_times, record_links,
│                                              claim_periods, claim_conflicts, claim_reviews
└── mcp/server.py                 EXTEND  parameter additions only (M.1); fix the stale docstring
tests/eval/census.py              NEW  (M0) read-only predicate, degree and vault census
```

### K.3 Retain, refactor, extend

| Retain unchanged | Refactor | Extend |
|---|---|---|
| `config.py` (pydantic, extra=forbid) | `recall.py`: move the three nets behind `Net` with no behaviour change, proven by the current tests plus a `run_gold` diff of zero | `vault.py`, `index.py`, `graph.py`, `remember.py`, `status.py`, `cron.py`, `cli/main.py` |
| `storage/db.py`, `migrator.py` | `graph.py`: from free strings to claims | `templates/agent/vault/`: add `relations.md`, `entities/`, `claim_reviews.md` |
| `judge.py`, `models.py` (the runner abstraction) | | `04-memory.md`: relation, role and entity guidance |
| `embed.py`, `embed_worker.py`, `vectors.py` | | `THREAT_MODEL.md`: extraction and projection rows |
| `session.py`, `capture.py`, `lessons.py`, `distill.py`, `transcripts.py`, `notes.py` | | `VAULT_SCHEMA.md`: three new files, three new meta fields |
| The five-tool MCP surface | | |

Delete (after M1): the unused `decisions`, `reflections` and `hsam_days` tables. M1 makes `brain doctor` count their rows; a later migration drops them once no install reports any **[Q: any v0.1 user data?]**.

---

## L. Database design

### L.1 SQLite migrations `007_ledger.sql` (M1), `008_entities.sql` (M2) and `009_claims.sql` (M3) [P][T]

Every table below except `record_ledger` is derived. Dropping all the derived ones loses nothing: `brain index --rebuild` fills them again from the vault (G.2). `record_ledger` is a journal of brain-core's own clock, kept like `events`. The traversal columns and indexes were run in the prototype (H.3).

```sql
-- 007_ledger.sql (M1) -----------------------------------------------------------------------
-- NOT derived: never dropped by `brain index --rebuild` (J.1)
CREATE TABLE IF NOT EXISTS record_ledger (
    item              TEXT PRIMARY KEY,           -- sha256 of the exact text (record, meta line, review line)
    written_at        TEXT,                       -- UTC; set when brain_remember wrote it
    first_ingested_at TEXT NOT NULL,              -- UTC; the first sync that parsed it
    first_path        TEXT NOT NULL               -- store-qualified
) WITHOUT ROWID;

-- 008_entities.sql (M2) ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS entities (
    id          TEXT PRIMARY KEY,                 -- UUIDv7 from the note's frontmatter
    type        TEXT NOT NULL,                    -- ontology type
    name        TEXT NOT NULL,                    -- the note's H1 / file stem
    path        TEXT NOT NULL UNIQUE,             -- entities/<file>.md
    merged_into TEXT REFERENCES entities(id),
    ontology    INTEGER NOT NULL DEFAULT 1,
    degree      INTEGER NOT NULL DEFAULT 0        -- computed: non-rejected claims naming it (hub test)
);
CREATE TABLE IF NOT EXISTS aliases (
    alias     TEXT NOT NULL,                      -- normalised (NFKC, casefold)
    entity_id TEXT NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
    PRIMARY KEY (alias, entity_id)
);
CREATE TABLE IF NOT EXISTS mentions (             -- raw: one vault file each
    record_id   TEXT NOT NULL,                    -- records_fts.rid
    entity_id   TEXT NOT NULL,
    how         TEXT NOT NULL CHECK (how IN ('wikilink', 'alias', 'tag', 'extracted')),
    source_path TEXT NOT NULL,
    PRIMARY KEY (record_id, entity_id, how)
);
CREATE INDEX IF NOT EXISTS idx_mentions_entity ON mentions(entity_id);
CREATE INDEX IF NOT EXISTS idx_mentions_source ON mentions(source_path);

-- 009_claims.sql (M3) -----------------------------------------------------------------------
-- computed: one row per assertion that has at least one evidence row
CREATE TABLE IF NOT EXISTS claims (
    id             TEXT PRIMARY KEY,              -- ClaimKey.id(): no date, no source, no status
    subject        TEXT NOT NULL,                 -- entity id (survivor of any merge)
    predicate      TEXT NOT NULL,
    role           TEXT NOT NULL DEFAULT '',      -- part of the key for functional predicates
    object_entity  TEXT,
    object_literal TEXT,
    datatype       TEXT CHECK (datatype IN ('text','int','version','port','url','date')),
    lifecycle      TEXT NOT NULL CHECK (lifecycle IN ('candidate','accepted','rejected')),
    verification   TEXT NOT NULL CHECK (verification IN ('stated','approved','derived','unverified')),
    confidence     TEXT CHECK (confidence IN ('high','medium','low')),
    retracted_at   TEXT,
    rank           INTEGER NOT NULL,              -- traversal order: open period first, then predicate priority
    CHECK ((object_entity IS NULL) <> (object_literal IS NULL)),
    CHECK ((object_literal IS NULL) = (datatype IS NULL)),
    CHECK (retracted_at IS NULL OR lifecycle = 'rejected')
);
-- NOT partial indexes: SQLite does not use `WHERE lifecycle <> 'rejected'` for a query on
-- lifecycle = 'accepted' and silently scans the table (H.3)
CREATE INDEX IF NOT EXISTS idx_claims_out ON claims(subject, lifecycle, rank, id);
CREATE INDEX IF NOT EXISTS idx_claims_in  ON claims(object_entity, lifecycle, rank, id);
CREATE INDEX IF NOT EXISTS idx_claims_key ON claims(subject, predicate, role);   -- conflict groups

-- raw: one row per (claim, supporting record); all provenance lives here
CREATE TABLE IF NOT EXISTS claim_evidence (
    claim_id     TEXT NOT NULL,                   -- no FK: claims are computed from this, not the reverse
    record_id    TEXT NOT NULL,                   -- records_fts.rid
    source_path  TEXT NOT NULL,                   -- store-qualified: 'vault:decisions_log.md', 'notes:/abs/x.md'
    line         INTEGER NOT NULL DEFAULT 0,
    subject_name TEXT NOT NULL,                   -- the raw names, so an alias change can re-resolve
    object_name  TEXT,
    stated_date  TEXT,                            -- the date the text gives; NULL = undated line
    recorded_at  TEXT NOT NULL,                   -- ledger time (J.1), UTC timestamp, never from the text
    recorded_by  TEXT NOT NULL CHECK (recorded_by IN ('write','ingest','git')),
    event_date   TEXT,
    origin       TEXT NOT NULL CHECK (origin IN ('user','agent','markup','extracted','inferred','reflection','external')),
    verification TEXT NOT NULL CHECK (verification IN ('stated','approved','derived','unverified')),
    confidence   TEXT CHECK (confidence IN ('high','medium','low')),
    quote        TEXT NOT NULL,
    rule         TEXT NOT NULL,                   -- deriver and version, or extractor model and date
    -- one row per occurrence: the same record text in two files is two rows (review point B)
    PRIMARY KEY (claim_id, source_path, line, rule)
) WITHOUT ROWID;
CREATE INDEX IF NOT EXISTS idx_evidence_source ON claim_evidence(source_path);
CREATE INDEX IF NOT EXISTS idx_evidence_record ON claim_evidence(record_id);

-- raw, from record_meta.md: stated times of a record, and supersedes links
CREATE TABLE IF NOT EXISTS record_times (
    rid        TEXT PRIMARY KEY,                  -- 16-character record id prefix, as record_meta uses
    valid_from TEXT, valid_to TEXT, event_date TEXT,
    timeless   INTEGER NOT NULL DEFAULT 0,
    CHECK (timeless = 0 OR (valid_from IS NULL AND valid_to IS NULL))
);
CREATE TABLE IF NOT EXISTS record_links (
    new_rid TEXT NOT NULL, old_rid TEXT NOT NULL,  -- new supersedes old
    PRIMARY KEY (new_rid, old_rid)
) WITHOUT ROWID;
CREATE INDEX IF NOT EXISTS idx_links_old ON record_links(old_rid);

-- computed: validity periods (J.1)
CREATE TABLE IF NOT EXISTS claim_periods (
    claim_id   TEXT NOT NULL,
    seq        INTEGER NOT NULL,
    valid_from TEXT,                              -- NULL = start unknown (never "always")
    valid_to   TEXT,                              -- exclusive; NULL = no known end
    asserted_from TEXT,                           -- earliest stated_date in the period (valid time)
    timeless   INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (claim_id, seq)
) WITHOUT ROWID;

-- computed: conflict state, apart from the lifecycle (J.2)
CREATE TABLE IF NOT EXISTS claim_conflicts (
    claim_a      TEXT NOT NULL,
    claim_b      TEXT NOT NULL,
    kind         TEXT NOT NULL CHECK (kind IN ('functional_overlap')),
    overlap_from TEXT,
    overlap_to   TEXT,
    acknowledged INTEGER NOT NULL DEFAULT 0,      -- from an `ack` line in claim_reviews.md
    PRIMARY KEY (claim_a, claim_b),
    CHECK (claim_a < claim_b)
) WITHOUT ROWID;
CREATE INDEX IF NOT EXISTS idx_conflicts_b ON claim_conflicts(claim_b);

-- raw, from claim_reviews.md: what a person decided, in order
CREATE TABLE IF NOT EXISTS claim_reviews (
    claim_id    TEXT NOT NULL,                    -- recomputed from the line's stored key on rebuild
    seq         INTEGER NOT NULL,                 -- line order in the file
    action      TEXT NOT NULL CHECK (action IN ('reject','retract','restore','ack')),
    on_date     TEXT NOT NULL,
    other_claim TEXT,                             -- for ack
    reason      TEXT,
    PRIMARY KEY (claim_id, seq)
) WITHOUT ROWID;
```

The ownership of each raw table is held by its `source_path`, or by the one file it comes from:

| Table | Owned by |
|---|---|
| `mentions`, `claim_evidence` | the `source_path` on each row |
| `record_times`, `record_links` | `record_meta.md` |
| `claim_reviews` | `claim_reviews.md` |

There is no `claims.source_path`. `relations` (002) stays readable for `brain graph import` and for agents that have not rebuilt; after M3, `GraphStore` reads `claims`.

### L.2 Neo4j, bench projection only [P]

- Labels:
  - `:Entity:<Type>` with `{id, name, aliases}`
  - `:Record:<Kind>` with `{id, path, line, stated_date, recorded_at, text}`
  - `:Claim` with `{id, predicate, role, lifecycle, verification, origins}`
  - `:Period` with `{valid_from, valid_to, asserted_from, timeless}`
- Edges: `SUBJECT_OF`, `OBJECT`, `VALID_DURING`, `SUPPORTED_BY {origin, rule, quote}`, `CONFLICTS_WITH`, `MENTIONS`, `SUPERSEDES`, plus convenience typed edges between entities.
- Constraints: `CREATE CONSTRAINT FOR (n:Entity) REQUIRE n.id IS UNIQUE`, the same for `:Record` and `:Claim`.
- A full-text index on `Record.text`, and a vector index on `Record.embedding` (LIST property on Community **[E]**), so `HybridCypherRetriever` can run.
- Loaded with idempotent `MERGE` from `brain graph export --format neo4j`. Rebuilt, never synced.

### L.3 Qdrant (not proposed) [P]

If records ever pass about 200k, or memory is shared across machines:

- one collection, `brain_records`, with a named dense vector (the model's dimension, cosine) and an optional sparse vector
- payload `{record_id, kind, store, path, date, undated, entity_ids[], superseded}`
- payload indexes on `kind`, `date`, `entity_ids`

`VectorIndex` would become a second implementation of the same small interface. Nothing else changes.

### L.4 PostgreSQL (not proposed) [P]

For a hosted multi-user future only: the same tables, with `daterange` validity and an `EXCLUDE USING gist` constraint for functional predicates, plus row-level security per user. That is out of scope by the README ("not a hosted service and not a team product").

### L.5 Synchronisation strategy [P]

- **Vault → SQLite:** per-file reconciliation of raw rows, then recompute of the dirty set, in one transaction per file (G.2); `brain index --check` verifies incremental equals rebuild.
- **SQLite → Hindsight:** write-through with per-layer status plus the queue (exists).
- **→ projections:** a full rebuild on demand.

There is no two-way sync anywhere. Only the vault is ever edited by a person.

---

## M. API design

### M.1 MCP surface: still five tools (ADR-009) [P]

| Tool | Change |
|---|---|
| `brain_remember` | `kind='relation'` also writes `vault/relations.md` and takes an optional `role`. New optional `valid` (an ISO date, or `always`), `until` and `event` (ISO dates) for any kind, kept in `record_meta.md`; a month-only date is refused with a message. New `kind='entity'` (`name`, `entity_type`, `aliases`) creates or extends an entity note; an alias already held by another entity returns `conflict` with both, and writes nothing. The ontology check returns `mapped_to: RELATED_TO` when a predicate is unknown |
| `brain_recall` | New optional `as_of` (ISO date). Results may carry `path` (graph hits), `validity` (`true`, or `unknown` in history mode) and `disputed_with`. When the graph net runs, a structured `claims` block lists each walked claim: key, validity at `as_of`, verification, origins, sources, and `truncated` when a cap was hit. `found_by` gains `graph`. `scope` gains `entity:<name>` (records about one entity) |
| `brain_status` | Adds `entities`; claims by lifecycle and by verification; `open_conflicts`; `candidates_waiting` and the oldest age; `hubs` (degree above `hub_degree`); `alias_collisions`; `relations_not_in_vault` (migration progress) |
| `brain_session('start')` | Lists open conflicts beside pending decisions |
| `brain_distill` | Unchanged |

`known_at` (J.1) is not added to the tool in this plan; it is an open decision (R).

### M.2 CLI (person or cron only) [P]

| Command | Does |
|---|---|
| `python tests/eval/census.py --config …` | M0, read-only: predicates, roles, degrees, vault counts |
| `brain graph migrate` | Writes existing `relations` rows into `vault/relations.md` (M1; idempotent) |
| `brain entities [--suggest-merges]` | Lists entities and unresolved names; merge suggestions go to the inbox |
| `brain extract [--since 7d] [--dry-run]` | Optional LLM candidates to the inbox |
| `brain index --check \| --rebuild` | Rebuild-and-diff drift report, or a full rebuild |
| `brain graph export --format neo4j --out DIR` | Bench projection |

### M.3 No HTTP API [P]

MCP over stdio is the API, and there is no remote caller. A read-only HTTP wrapper around `Agent` is about 50 lines when a real caller appears. Until then it would only be an unauthenticated port on the laptop (the same risk Hindsight's MCP carries **[E]**).

---

## N. Deployment architecture

| | Today [V] | Proposed [P] |
|---|---|---|
| Local development | `uv sync --all-extras --all-groups`; `ruff check`, `ruff format --check`, `mypy`, `pytest` (CI: Ubuntu 24.04, Windows 2025) | Same, plus `pytest -m knowledge` for the new layer, and `run_gold.py` before and after each milestone |
| User install ("production") | `install.sh` / `install.ps1` / `uv tool install`; lite (vault + SQLite) or full (+ Hindsight service, ~2 GB); cron through launchd, systemd `--user`, crontab or Task Scheduler | **Unchanged.** The new layer needs no service and no extra. LLM extraction reuses the existing `api` / `claude` runners and is off by default |
| Optional services | Hindsight (127.0.0.1:8888), embed worker (socket, exits when idle) | Unchanged |
| Bench | — | `bench/docker-compose.yml` (Neo4j 5.x Community + APOC), kept out of the wheel and out of CI by default; a manual workflow |
| Docker | Registry introspection only | Unchanged |

---

## O. Testing and evaluation

### O.1 What exists [V]

- `tests/eval/run_gold.py`: labelled record ids; slices reworded, real, same, identifier, multi, update, temporal, absent; `--depth`; `--today`; three error counts (false answer, false refusal, missed with no warning).
- `tests/eval/compare.py`: paired fixed/broken counts with an exact McNemar p-value.
- `tests/eval/from_repairs.py`: real misses the agent repaired become eval questions.
- CI: 28 fixture recall tasks run three times each (pass^3), 11 write scenarios, a growth test.
- The owner's real questions stay under `local/`, which CI checks is untracked.

### O.2 New slices (about 20 questions each, then grown from real misses) [P]

| Slice | Example question | Gold |
|---|---|---|
| semantic | "how do we keep the brief short?" | the record id(s) |
| entity | "what do we know about Hindsight?" | the entity note plus its top 3 records |
| relation | "what does the ride app use for payments?" | the record evidencing `USES` |
| multi-hop | "which of our services depend on something we decided to replace?" | every evidence record on the path |
| temporal-as-of | "what was the Claude Code CLI pinned to on 2026-10-20?" | the record valid on that day; the newer one must **not** lead |
| as-of-unknown | a date before a fact was first recorded, with no stated start | the reply must say `unknown`, never assert it |
| decision-history | "why did we stop using Kuzu?" / "what did we choose first?" | the successor's Reason / the earliest period |
| conflict | a question over two accepted, overlapping claims | the reply must carry `disputed_with` |
| memory (episodic) | "what did we do last Tuesday?" | the session records of that date (exists as temporal) |
| global | "what mistakes keep recurring?" | judged on the mental model: share of bullets citing gold records (citation precision) |
| citation | any answerable question, in an agent run | the share of cited `source`s that are gold or support the answer |
| logical | "which services depend, directly or not, on something with no owner?" | the full set; measures the H.7 gap |
| numeric | "how many days passed between choosing and replacing the graph database?" | the number; measures the H.7 gap |

### O.3 Systems compared [P]

| Id | System | Config |
|---|---|---|
| S0 | brain-core 0.9.1 default | keywords + search keys |
| S1 | "traditional RAG" | vector net alone (measured once: 89 of 143 **[M]**) |
| S2 | hybrid | S0 + vectors (RRF) |
| S3 | hybrid + judge | S2 + `recall.judge: model` |
| S4 | **S3 + graph net** | the candidate this plan builds |
| S5 | Hindsight recall | `scope='hindsight'` |
| S6 | Neo4j GraphRAG | `HybridCypherRetriever` over the L.2 projection |
| S7 | KAG | **Not run** while the project is dormant (E.2); the slot is kept so a revival can be measured the same way |

### O.4 Metrics [P]

- **Retrieval.** Recall@1/5/10/50 (found@10 exists), MRR (first place exists in the README figures), nDCG@10 (graded: gold = 2, supporting = 1), precision@10 on multi-gold questions.
- **Errors.** False answer, false refusal, missed with no warning (exist). Add **false assertion under `as_of`**: an `unknown` presented as true.
- **Evidence.** Citation precision and recall in agent answers. Faithfulness by an LLM grader, **with a person auditing a 20% sample**.
- **Extraction.** Entity and relation precision and recall against a 100-record set a person labelled; temporal accuracy on the as-of slices.
- **Graph.** The share of walks that hit `truncated`; edge rows read per walk (p50, p95, max). Hubs by degree, from the census.
- **Cost.** p50/p95 latency per recall; tokens per recall; no-change sync time; full rebuild time; index build time and tokens; RAM and disk resident; services to run.

### O.5 Process and success criteria [P]

1. **Before anything else (M0):** a person checks ≥ 100 labels, stratified by slice, and the new slices' gold. Report how often labels change; the size of that number decides how far any earlier result can be trusted.
2. Keep the existing split discipline: tune on dev, open held-out once per stage, compare pairwise with `compare.py`.
3. **Ship gate for any retrieval change:**
   - held-out found@10 must not fall, and new slices must gain with McNemar p < 0.05, or with fixed ≥ 3 × broken where n is too small
   - **zero** broken in the update and identifier slices, and zero false assertions under `as_of`
   - p95 under 100 ms with keywords only, under 250 ms with the graph net added
   - the judge path no slower than today
   - no new required service
4. **Targets for the program:**

   | Measure | Target |
   |---|---|
   | multi-hop slice size | ≥ 40 questions first |
   | relation found@10 | ≥ 80% |
   | as-of accuracy | ≥ 90%, and 100% `unknown` on as-of-unknown |
   | changed value shown first | ≥ 35 of 37 (34 today, in the README's 3-of-37 terms) |
   | missed with no warning | ≤ 6% (36 of 389 = 9.3% with the judge today) |
   | `same` and `identifier` slices | no regression |
5. S6 is judged by the same gate, **plus** its operating cost: it must beat S4 on held-out by a margin worth a JVM service, which the owner sets in advance **[Q]**.

---

## P. Implementation roadmap

Each milestone ships on its own and changes nothing by default unless it says so. Every one ends with `ruff`, `mypy --strict`, `pytest` and a `run_gold.py` comparison against the previous milestone.

### M0: Measure (the next and only activity now)

- **Objective:** a trustworthy baseline and the numbers the design's defaults depend on.
- **Safety:**
  - Run everything on a **copy** of the agent folder (vault plus `data/brain.db`) in a scratch directory. `Agent.from_config` runs pending migrations on open (`agent.py`), and every search refreshes the index cache, so the live database is never opened.
  - No migration file is added and no schema changes.
  - The owner's questions and results stay under `local/`, which is untracked and checked by CI.
- **Files:**
  - `tests/eval/census.py`: new, read-only (it opens the copy's `brain.db` with `mode=ro`)
  - `tests/eval/run_gold.py`: adds p50/p95 latency and tokens per recall
  - question files under `local/`
- **Dependencies:** none.
- **Tasks:**
  1. **Baseline.** Run S0–S3 on the current slices with `--today` pinned; keep the per-question result JSON for `compare.py`.
  2. **Human-reviewed labels.** A person reviews ≥ 100 questions, stratified by slice. For each, the reviewer sees the question, the gold record(s) and the top 10, and marks the gold *right*, *wrong*, *incomplete* or the question *ambiguous*. Corrections go into a versioned label file. Report the change rate per slice. Draft the new slices (O.2), model-drafted and person-checked.
  3. **Predicate census.** From `relations`:
     - predicate counts, and case and spelling variants (an estimate of the entity-resolution work)
     - distinct subjects and objects
     - the degree distribution (max, p99, the top 20 nodes), which sets `hub_degree`, `fan` and `scan`
     - candidate roles for `USES`-like predicates
     - from the vault: decisions whose fields hold wikilinks (how many claims `decision-field/1` would derive), and the share of undated facts and patterns (how often `as_of` will answer `unknown`)
  4. **Performance.**
     - no-change sync time, full re-parse time and recall p50/p95 for S0–S3
     - `brain.db` size; records by kind; transcript rows
     - the rows in the v0.1 tables
     - a timing of the H.3 prototype against the census's real degree distribution
- **Deliverable:** `docs/M0_BASELINE.md` with the numbers and the label review, plus the defaults it recommends (`hub_degree`, `fan`, `scan`, the functional predicates and roles).
- **Acceptance:**
  - every number above is measured
  - the label change rate is reported
  - the owner signs off the defaults and the R decisions that M0 data settles
- **Risks:** labelling effort, which needs the owner's time. The census shows the vault's private structure, so the M0 doc reports counts, not names, unless the owner says otherwise.
- **Depends on:** —

### M1: Relations become canonical, the ledger starts, and hygiene (fixes G1)

- **Objective:** deleting `brain.db` loses no memory, and brain-core starts keeping true recording times.
- **Files:** `stores/vault.py` (`relations.md`), `remember.py` (`written_at`), `stores/index.py` (`first_ingested_at`), `stores/graph.py`, `cli/main.py` (`brain graph migrate`, the v0.1 row count in `brain doctor`), `mcp/server.py` (the docstring), `007_ledger.sql`, the template `relations.md`, `VAULT_SCHEMA.md`.
- **Tasks:**
  - Vault write and parse: `- [[S]] —[p: role]→ [[O]] (date)`.
  - A one-time idempotent migration from the table.
  - The index rebuilds the table from the file.
  - `record_ledger`: insert-or-ignore on every write and every first parse; never touched by a rebuild.
  - Fix the stale docstring.
- **Acceptance:**
  - A test deletes `brain.db`, runs `brain index`, and every relation is back; the existing write scenarios pass.
  - A test backdates a hand-written line: its `recorded_at` is the ingest time, not the written date.
  - `brain index --rebuild` keeps every ledger row.
- **Risks:** wikilink brackets change the record id. Hash `S —[p]→ O` without brackets, as today.
- **Depends on:** M0.

### M2: Obsidian structure and the entity registry

- **Objective:** identity for things.
- **Files:** `knowledge/model.py` (entities), `ontology.py`, `entities.py`, `links.py`, `ontology.yaml`, `stores/vault.py` (frontmatter lists, fences, `entities/`), `stores/index.py` (mentions in sync), `008_entities.sql`.
- **Dependencies:** a UUIDv7 fallback for 3.12 and 3.13 (stdlib on 3.14 **[V]**).
- **Tasks:**
  - Parse wikilinks, `#tags` and `aliases`.
  - Add `brain_remember(kind='entity')`.
  - Turn the census's subjects and objects into proposed entities in the inbox.
  - Report alias collisions.
- **Acceptance:**
  - Rename an entity note and rebuild: same id.
  - The mentions of a fixture vault match a hand list.
  - Vault parse time grows by less than 20%.
- **Risks:**
  - Over-eager alias matching. Aliases of 3 characters or fewer match only as wikilinks.
  - Unsafe frontmatter parsing. `yaml.safe_load` on the block, with today's line parser as the fallback.
- **Depends on:** M1.

### M3: Claims, evidence, time, lifecycle and conflicts

- **Objective:** an evidence-backed, bitemporal claim layer that reconciles per file.
- **Files:** `knowledge/model.py`, `derive.py`, `reconcile.py`, `temporal.py`, `009_claims.sql`, `stores/vault.py` (`claim_reviews.md`, meta fields), `remember.py` (`valid` / `until` / `event`), `stores/index.py`, `status.py`, `cron.py`.
- **Tasks:**
  - The F.3 models and the derivation rules `relations.md/1`, `decision-field/1` and `supersedes`.
  - The G.2 reconciliation and the J.1 periods.
  - The J.2 lifecycle and conflicts.
  - `brain index --check` / `--rebuild`.
  - The provisional weight for hook notes (G8); `origin` mandatory on evidence (THREAT_MODEL gate 2).
- **Tests:**
  - **T1** the F.4 example end to end: periods, no conflict, every J.4 question.
  - **T2** delete one of two source files: the claim survives with fewer origins.
  - **T3** an unknown start is `unknown` before `asserted_from` and never TRUE.
  - **T4** a re-assertion after an end opens a second period, same id.
  - **T5** a rejection and a retraction survive a rebuild; a retraction keeps origins and verification.
  - **T6** two accepted functional claims overlap → one conflict row, lifecycles unchanged; `ack` keeps the row, marked; `until:` removes it.
  - **T7** a merge and a predicate rename re-key claims, and their reviews follow.
  - **T8** a `hypothesis` property: incremental equals rebuild for random edit, delete and move sequences.
  - **T9** two rebuilds give identical tables.
  - **T10** the same fact text in the vault and in a notes folder gives two evidence rows; deleting the notes file leaves one (review point B).
  - **T11** `known_at` never uses a stated date: a backdated line is invisible before its ledger time (review point A).
- **Acceptance:** T1–T9 pass; `brain index --check` is clean on the M0 copy of the real vault.
- **Risks:** decision fields without wikilinks yield no claims. Measured in M0 task 3; `04-memory.md` guides the agent to link entities.
- **Depends on:** M2.

### M4: Graph net in recall

- **Objective:** relationship, multi-hop and as-of questions answered by structure.
- **Files:** `nets.py` (refactor first, no behaviour change), `recall.py`, `mcp/server.py` (`as_of`, `entity:` scope, the `claims` block).
- **Tasks:**
  - Extract `Net`, proven by a `run_gold` diff of zero.
  - `GraphNet` with the H.3 walk, history mode, `as_of`, and the supersession rule relative to `as_of` (H.4).
  - The H.3 test, `tests/unit/test_graph_walk.py`: the hub, the cycle, the bounds, determinism, `as_of`, the query plans, the VM-step bound.
- **Acceptance:** the O.5 ship gate on the relation, multi-hop, as-of, as-of-unknown and decision-history slices; the H.3 test passes; `truncated` in fewer than 5% of walks on the real vault, or the M0 defaults are revised.
- **Risks:**
  - The graph net pushes exact keyword hits down. The pin rule runs after the join, as today.
  - A historical `as_of` on hubs is truncated by design. Reported, and measured (O.4).
- **Depends on:** M3.

### M5: Candidate extraction (optional, off by default)

- **Objective:** a graph that grows past what the agent writes by hand.
- **Files:** `knowledge/extract.py`, `cli/main.py` (`brain extract`), the inbox candidate line format, `THREAT_MODEL.md`.
- **Dependencies:** the existing `api` extra or the `claude` runner.
- **Tasks:**
  - A structured-output prompt using the `<records>` framing.
  - Pydantic validation and the verbatim-quote grounding check.
  - Suppress keys already `reject`ed in `claim_reviews.md`.
  - Inbox lines; approval writes `relations.md`.
  - Record the tokens spent on each run.
- **Acceptance:**
  - Entity and relation precision ≥ 0.85 on the 100-record set a person labelled.
  - Zero writes outside the inbox without approval (a test).
  - The cost per 1,000 records is reported.
- **Risks:** inbox fatigue. Mitigation: batch, rank by confidence, cap N per day.
- **Depends on:** M3.

### M6: Bench projection (experiment)

- **Objective:** decide on Neo4j GraphRAG with data, and re-measure Hindsight on the new slices.
- **Files:** `knowledge/projections.py`, `bench/` (compose, adapter, README), `run_gold.py --system`.
- **Dependencies (bench only):** `neo4j`, `neo4j-graphrag==1.24.*`.
- **Tasks:** export; an adapter as a `Net`; run S5 and S6; write up an ADR.
- **Acceptance:** a results table with quality, latency and cost; an ADR accepted or rejected.
- **Risks:**
  - Time sink. Time-box it to one week.
  - Version churn (`neo4j-graphrag` ships every 2–4 weeks **[E]**). Pin the version.
- **Depends on:** M4.

### M7: Claim-level contradiction at write time, and reflection gates

- **Objective:** close THREAT_MODEL gates 1–3; semantic conflict detection when a claim is written.
- **Files:** `remember.py`, `knowledge/reconcile.py`, `cron.py` (reflection with parent ids), `THREAT_MODEL.md`.
- **Tasks:**
  - Check a new relation against the current claims on its functional predicate and role at write time, so the reply carries `contradiction` the way a changed fact line does.
  - Reflection claims cite parent claims, or they stay `candidate`.
- **Acceptance:** the conflict slice passes; the gates are marked "built".
- **Depends on:** M3; M5 helps.

---

## Q. Architecture decision records

**ADR-001: Markdown stays canonical; one SQLite file is the only derived store.**
- *Context:* single user, about 5k records, a one-minute lite install, files the user edits by hand.
- *Alternatives:* Neo4j + Qdrant + Postgres as the brief proposes; Hindsight as the primary store.
- *Decision:* vault canonical, `brain.db` derived and rebuildable.
- *Trade-off:* no graph algorithms library and no ANN index. Neither is needed below about 200k records [A].
- *Revisit when:* records exceed 200k, or several machines share one memory.

**ADR-002: No Neo4j, Qdrant, PostgreSQL or Redis in the product.**
- *Reason:*
  - each adds a service the lite install cannot carry (Neo4j: JVM, 2–8 GB **[E]**)
  - each is a second store to keep consistent
  - the measured gain of the integrated graph and temporal engine (Hindsight) was nil on reworded questions **[M]**
- *Revisit with:* evidence from M6.

**ADR-003: Reconciliation instead of an outbox.**
- *Reason:* the derived tables share one database, so one transaction per file is atomic. The file signature, written last, is the retry marker. The only external store (Hindsight) already reports per layer and has a queue.
- *Trade-off:* a live external projection would need an outbox. None is proposed.

**ADR-004: Entities get UUIDv7 ids in Obsidian notes; records keep content-hash ids.**
- *Reason:* entity identity must survive renames and merges, while record ids are idempotency keys every layer depends on. Obsidian `aliases` give human-editable resolution, and wikilinks show in the graph view.
- *Alternative:* a central `entities.md` registry (fewer files, but invisible to Obsidian's link resolution).

**ADR-005 (revised): Claims are computed from the vault; extracted claims need approval; reviews are canonical.**
- *Reason:* LLM extraction is not reproducible, so what is kept must be written down. Candidates are lines in the inbox, approval is a line in `relations.md`, and rejections, retractions and acknowledgements are lines in `claim_reviews.md`. A rebuild therefore reproduces every lifecycle decision.
- *Trade-off:* a slower-growing graph; review effort; one more vault file.

**ADR-006 (revised in 2.1): Two time axes from two sources; three-valued validity; an unknown start is unknown.**
- *Reason:* valid time comes from the text, and transaction time from clocks:
  - The line's own date (`stated_date`), `supersedes`, and optional `valid` / `until` / `event` fields give valid time without migrating any vault file.
  - The append-only ledger gives transaction time, which a backdated note cannot move earlier.
  - Treating a missing start as "since always" would assert facts for periods nobody recorded.
  - `stated_date` stays nullable because 0.9.0 deliberately stopped inventing dates for undated lines.
- *Consequence:* `as_of` can answer `unknown`, and the eval checks it never turns that into an assertion.

**ADR-007: Graph expansion is a net in the existing rank fusion, not a separate engine.**
- *Reason:* RRF by rank already joins nets whose scores are not comparable, and the identifier pin and the current-over-old rule then apply to graph hits for free.
- *Alternative:* a GraphRAG engine with its own answer step. Rejected: it duplicates the judge and the agent.

**ADR-008: GraphRAG engines are bench projections only; KAG and Microsoft GraphRAG are not integrated.**
- *Reason:* each has its own construction pipeline and its own representation, so running one live means two truths. As projections they can be compared and thrown away. KAG is dormant and needs a Java/MySQL/Neo4j/MinIO stack. Microsoft GraphRAG is in maintenance mode, excludes Python 3.14, and its `update` skips edited and deleted documents **[E]**.

**ADR-009: The MCP surface stays five tools.**
- *Reason:* the project's own design constraint (SPEC §2, §7 "lean guard"): an agent picks better among few consolidated tools. New capability arrives as parameters and kinds.

**ADR-010: Every retrieval change passes the eval gate, on labels a person has checked.**
- *Reason:* the history in the README shows ties and regressions that a total hides (113 against 110 was 7 fixed and 4 broken). Model-written labels judged by the same model family are not enough to choose an engine.

**ADR-011 (new): A claim's identity is its assertion key; provenance is per evidence row.**
- *Decision:* `id = sha256(["claim/1", subject, predicate, role, object_type, object])[:32]`, on survivor entity ids and current predicate names. No dates, sources, status, confidence or wording.
- *Reason:* a claim supported by several records must outlive any one of them; a start date learned later must not change the claim; a re-assertion after an end is the same claim with a second period; the role changes what a functional predicate means.
- *Alternatives rejected:*
  - including `valid_from` (identity churn when a start becomes known; no repeated periods)
  - including the source (one claim per document; deleting a document deletes the claim)
- *Cost:* merges and renames re-key claims. Handled by storing the full key in `claim_reviews.md`.

**ADR-012 (new): Lifecycle, validity and conflict are three separate things.**
- *Decision:*
  - lifecycle ∈ {candidate, accepted, rejected}, from verification and reviews
  - validity = periods, from evidence and links
  - conflict = rows between claims, computed
- *Reason:* "superseded" and "disputed" describe time and relations, not review state. Folding them into one status erases what a claim was (accepted, verified) the moment something happens to it.
- *Consequence:* recall can say "accepted, stated, true until 2026-12-10, disputed by X", with each part from its own source.

**ADR-013 (new): Graph traversal is a bounded breadth-first walk with per-entity indexed queries, not a recursive CTE.**
- *Reason:* SQLite cannot limit per entity inside a recursive step (no aggregate or window functions there), and a `LIMIT` after the CTE bounds output, not work. Measured: 320,005 rows and 247 ms from a hub, against 363 edge rows and about 1 ms for the walk **[T]**. The `LIMIT` must sit before the validity filter (about 2,000 against 180,000 VM steps on a nothing-valid hub), and the indexes must not be partial (140 ms table scan) **[T]**.
- *Trade-off:* a historical `as_of` on a hub can miss valid edges past the scan window. Reported as `truncated`, and measured.

**ADR-014 (new): brain-core does retrieval, evidence checks and bounded symbolic lookups; logical-form solving stays out.**
- *Reason:* the judge is a reranker and relevance check, and the agent's reasoning is unstructured. Deterministic SQL over typed claims covers paths, intervals, chains and simple numbers.
- *Still needs a specialised engine:* a planner that produces logical forms, a general solver, rule inference, and multi-document numeric problem solving.
- *Revisit when:* the O.2 `logical` and `numeric` slices become the largest miss class after M4, and a maintained engine exists.

---

## R. Final recommendations

**Implement first: M0, and only M0.**
- baseline S0–S3
- a person checks ≥ 100 labels
- the predicate, role and degree census
- the performance numbers

All of it runs on a copy of the agent folder, with no migration and no schema change.

**Then, in order:** M1 (relations into the vault: a correctness fix of the "rebuildable from files" promise), M2, M3, M4. M5–M7 are optional and gated by the eval.

**Leave unchanged:**
- the five-tool MCP surface
- the vault formats and record ids
- the write order and per-layer status
- the secret gate
- RRF c=10, the identifier pin and the current-over-old rule (relative to `as_of` only when it is given)
- the judge as the optional reranker
- mental models as the global-synthesis layer
- the lite install
- Hindsight as an optional store
- the cron jobs

**Refactor:**
- `recall.py` nets behind a `Net` protocol, with zero behaviour change, at the moment the graph net lands
- `GraphStore` from free strings to claims
- the frontmatter parser to read YAML lists
- drop the dead v0.1 tables after counting their rows
- fix the stale docstring

**Postpone:**
- LLM extraction (M5), until the deterministic graph is measured
- the bench projection (M6)
- `known_at` in the tool
- any HTTP API
- indexing raw source bodies (today only their titles are searchable)
- vault git automation

**Avoid:**
- Neo4j, Qdrant, PostgreSQL or Redis as product dependencies
- an LLM query router
- a file-watcher daemon
- auto-merging entities
- auto-accepting extracted claims
- reading an unknown start as "always"
- a recursive CTE with a trailing `LIMIT` for traversal
- partial indexes on `lifecycle`
- a second canonical store of any kind (an engine's own KB included)
- restructuring the package into the brief's idealised `intelligence/ knowledge/ api/ workers/` tree

**M0 results.** `docs/M0_BASELINE.md` holds the measurements. It settles R items 3, 5, 8, 10, 11, 12 and 15 for this install, and adds gap G11. Its recommendations for M1 wait for the owner.

**Unresolved decisions [Q]:**

| # | Decision | Default proposed | Settled by |
|---|---|---|---|
| 1 | Is a decision's date the `valid_from` of the claims it makes, or is their start unknown? | The decision's date (rule `decision-field/1`), overridable with `valid:` | Owner |
| 2 | Are `derived` claims (deterministic rules over records written on purpose) accepted without review? | Yes, with verification `derived` visible | Owner |
| 3 | Partial dates (month or year only) | Refused in v1 | Owner, after M0's count of how often they occur |
| 4 | Expose `known_at` in `brain_recall`, or only in the CLI and eval? | CLI and eval only | Owner, after M4 |
| 5 | `hub_degree`, `fan`, `scan`, `max_frontier` | 200 / 20 / 80 / 50 | M0 degree census |
| 6 | Which predicates are functional, and the `USES` role vocabulary | `PART_OF`, literal-valued predicates, `USES` per role | M0 predicate census + owner |
| 7 | "Never true" statements: a `denies` stance, or a retraction in the review log? | A retraction; "no longer" is an end | Owner |
| 8 | The literal datatype set | text, int, version, port, url, date | M0 census |
| 9 | The review log as its own file (`claim_reviews.md`) or a section of `record_meta.md` | Its own file | Owner |
| 10 | Which predicates are real in today's `relations` tables | — | M0 census |
| 11 | Is the owner's vault under git? It changes how revisions are reported | — | Owner |
| 12 | Do any v0.1 users have rows in `decisions`, `reflections` or `hsam_days`? | — | M1 count |
| 13 | What margin would justify a JVM service (O.5 item 5)? | — | Owner, before M6 |
| 14 | Who checks the labels, and how much time do they have? It sets the pace of M0 | — | Owner |
| 15 | How long does a no-change sync take on the owner's vault? It confirms "no watcher" | — | M0 |
