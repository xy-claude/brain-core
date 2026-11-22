# brain-core: knowledge architecture audit and blueprint

**Date:** 2026-11-21. **Revision:** 2.3: the second architectural review (2), corrected after three reviews (2.1, 2.2 on 2026-11-21; 2.3 on 2026-11-22). **Audited at:** commit `55038ca` (release 0.9.1), branch `claude/brain-core-architecture-audit-adfc3b`.
**Status:** this is a proposal. Neither revision changed any source, configuration, dependency or database, and no migration was run. The only code written is throwaway prototypes in the session scratchpad, outside the repository (see the 2.2 validation table), and a read-only census script for M0 (`tests/eval/census.py`).

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

*Partly superseded by 2.2 below: the text-hash ledger became an occurrence ledger, and `asserted_from` became the computed `true_from`.*

| Clarification | Resolution | Where |
|---|---|---|
| A. True transaction time | A date written in markdown can be backdated, so it is no longer called a recording time. `stated_date` is the date the text gives, nullable, and used for valid time only. `recorded_at` comes from brain-core's own clock: the moment `brain_remember` wrote the line, otherwise the first time the indexer saw it. It is kept in an append-only `record_ledger` that a rebuild never drops, and it can only err late, never early. `first_ingested_at` is kept beside it. `asserted_from` is renamed `asserted_from`, because it is a valid-time bound taken from the text | F.3, J.1, L.1, P (M1) |
| B. Evidence identity | An evidence row is one *occurrence*: its key is `(claim_id, source_path, line, rule)` with a store-qualified path. The same record text in two files gives two rows, so multi-source provenance cannot collapse | F.3, G.2, L.1 |
| C. Traversal truncation | The limits table and the pseudocode now match the prototype: `scan` per direction, `fan` per entity across both directions. Every cut sets `truncated`: extra seeds, a frontier over `max_frontier`, a full scan window, `fan` reached, a hub reached through a path, `max_edges` | H.3 |

---

### Revision 2.2: corrections after technical review (P0/P1)

Revision 2.2 was drafted after an independent review of 2.1 and finalized after a second review with P0/P1 findings. It is documentation and validation only:

- no M1–M7 work
- no change to the live agent, its database or the vault
- no migration on live data
- no model or package download
- no outside LLM call
- nothing committed

The full technical change log (problem, root cause, correction, modules, schema, compatibility, validation, remaining risks) and the validation report are in **`docs/AUDIT_2_2_VALIDATION.md`**.

| Issue | Correction | Status | Where |
|---|---|---|---|
| **P0-01** Evidence model ↔ schema | One field set in `Evidence` and `claim_evidence`, dates resolved per occurrence and stored on the row; foreign keys where safe, with the reasons where not; a checker runs this document's own code and SQL | **Resolved, tested** | F.3, G.2, L.1 |
| **P0-02** Transaction-time identity | Five identities (content, source, occurrence, version, claim) plus redirects; strategies compared; a copy never inherits a time; an unambiguous move does | **Resolved, tested** | F.3, J.1 |
| **P0-03** Durability | Options A–D compared; history lives in **`data/journal.db`**, a file of its own, written first, idempotently; behaviour defined for rebuild, deletion, corruption, restores and a move to another computer | **Resolved, tested** (backup scheduling proposed) | L.5, G.4 |
| **P1-01** G11 path-dependent ids | Store-relative source ids; a migration with `was:` lines, vector remap and label translation. On isolated copies, the migrated ids reproduce M0 **question for question** (S0 295 = 295, S2 346 = 346) | **Resolved, tested**; re-baseline after M1b (R item 19) | C.1, M1b |
| **P1-02** Temporal semantics | Votes per evidence row, three-valued; the review's twelve cases plus E1–E13 determined and asserted; `as_of` and `known_at` defined, separately and together | **Resolved, tested** | J.1 |
| **P1-03** Merges and claim identity | `identity_redirects` for every kind; reviews kept as written, ordered by ledger time; disagreements and orphaned acks reported; a merge undone by a rebuild | **Resolved, tested** (alias re-resolution proposed) | F.5 |
| Graph retrieval | Truncation reported as reasons, `depth` included; on 292 random graphs every omission inside the depth was reported; bounded equals exhaustive on the real graph from all 75 entities | **Validated** | H.3 |
| M0 evaluation | Scores provisional; the human review is pending (an AI-assisted pre-review is kept apart); 182 questions are affected by path-dependent ids; the frozen snapshot measured without 588 search-key lines | **Not complete** | M0, `docs/M0_BASELINE.md` |

**Recommendation: NOT READY FOR M1.** The design is ready, but M0 is not: no person has reviewed the labels yet. M1 also needs the owner's decisions (R). *(Superseded on 2026-11-22: READY FOR M1, see R.)*

### Revision 2.3: three concerns verified, all three confirmed and corrected

Each concern was first reproduced against the unmodified 2.2 prototype code, then corrected minimally and covered by a regression test. The test was mutation-checked: re-planting the original bug makes it fail. Details are in `docs/AUDIT_2_2_VALIDATION.md`, section 4.

| Concern | Finding | Correction | Tests |
|---|---|---|---|
| **A.** A `valid: always` claim that a later record supersedes on 12-10 | **Confirmed.** Both `Period.at` and the SQL predicate returned TRUE on 12-11: the timeless check ran before the link end, against the documented rule that a link end ends the period for every row | The link end is checked first. A `valid: always` row is one vote among the others, not an override, so a stated start in another row still makes the days before it UNKNOWN. The period summary gains `undated` and `stated`, and the SQL predicate becomes exact | checker 12 (A); 14 (property: the stored summary and the SQL predicate equal `Period.at` on random periods) |
| **B.** Two undated claims | **Confirmed.** The conflict ran from today with no end, while both claims are UNKNOWN tomorrow. The stored row also changed with the calendar, so the computed tier was not a pure function of the vault | Conflicts carry a `scope`: `interval` for dated windows, `current` where an undated row is needed, active only on whatever day is today. `derive()` no longer takes a date. A claim pair can have several conflict rows | checker 13 (B); 14 (property: a conflict is active exactly when both claims are TRUE, on random claim pairs) |
| **C.** Identical lines with different per-copy metadata | **Confirmed.** An identical copy inserted above moved `valid_from`, `valid_to` and `event_date` to the wrong lines without any warning | An occurrence is "the k-th copy of this text in this source", not a physical line. A per-copy meta line applies only while those copies are unchanged since it was written (ledger). Otherwise it is reported (`occurrence_meta_ambiguous` or `_dangling`) and **not applied**; the record-level meta is used, and the owner re-anchors (G.2) | `occurrence_meta23.py` C1–C7 |

The recommendation stays **NOT READY FOR M1**: the design is ready, and the human label review is still pending (M0). *(Superseded on 2026-11-22: READY FOR M1, see R.)*

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

**Status after M0 [V].** M0 ran on isolated copies (`docs/M0_BASELINE.md`). Its retrieval scores reproduce the README, but they rest on model-written labels, so they stay **provisional** until a person has checked the 104-question packet it prepared. **Update, 2026-11-22:** the owner waived the person check for M0. AI reviewers answered the packet, and the owner accepted their answers unchecked (`docs/M0_BASELINE.md`, section 9). M4's gate still needs labels a person has checked (ADR-010).

**Next:** that review, then M1, only with the owner's approval of each of its three work packages (P). Revision 2.2 changes no code; it corrects the design and validates it in throwaway prototypes.

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
| G11 | **Notes and archive record ids embed the absolute folder path.** `NotesStore` passes the full path to `knowledge_records`, which hashes `path#heading` into the id. Moving or renaming a notes or archive folder, or the home folder, re-keys every record in it: 2,805 of the live agent's 6,016 records. That detaches their search keys (`record_meta.md` is keyed by id), their vectors and any `supersedes` link. Found in M0, when a copy of the eval snapshot lost 64 of its gold records **[V]**. Validation found it also hit the baseline: the frozen snapshot's 588 search-key lines for these records are keyed by live-path ids, so none attached in M0's eval or the README's. 182 of the 446 questions name such records. Fix: M1b (tested on copies: migrated ids reproduce M0 question for question) | `notes.py:29`, `vault.py:796`; `docs/M0_BASELINE.md` | Medium. It matters for claim evidence (G.2), which must not churn when a folder moves |

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
| Backups and index rebuild | The index and vectors rebuild from the vault; Hindsight is backed up daily. **Relations do not rebuild (G1)** | Fix G1 first. Even then `brain.db` is not the whole state: transaction history cannot be recreated from the vault, so it lives in its own file, `data/journal.db`, which deleting or rebuilding `brain.db` never touches. `events` and `metrics` stay best-effort logs in `brain.db`, as in 0.9.1. L.5 gives the durability contract, the daily journal backup and the merge-restore |
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
   KNOWLEDGE LAYER: two files in data/ (L.5)
     data/brain.db, DERIVED, rebuildable from the vault (delete it and the next sync refills it):
       per-source raw rows : records_fts · mentions · claim_evidence · record_times · record_links
                             · claim_reviews
       computed from them  : claims · identity_redirects · claim_periods · claim_conflicts · entities.degree
       other               : record_vectors (needs the model) · entities · aliases
                             · events, metrics (best-effort operational logs, as in 0.9.1)
     data/journal.db, HISTORY no file holds (written first, idempotently; backed up daily):
       record_ledger · ledger_gaps · derivation_journal
                          │  brain.db is rebuilt by `brain index --rebuild` from:
   CANONICAL KNOWLEDGE: vault/
     facts.md patterns.md decisions_log.md corrections.md sessions/ knowledge/ raw/
     record_meta.md (keys, source, supersedes; NEW: valid, until, event, occurrence lines, was)
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
5. **Consolidation.** The existing weekly archive, plus open conflicts listed in the daily brief: accepted claims on a *functional* predicate with one subject and role, different objects, and overlapping TRUE days (J.2).

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
| Id | **Unchanged** for the vault: sha256 of the normalised text (knowledge: of `path#heading`). Notes and archive: the same, over a store-relative source id instead of an absolute path (G11, F.3) | **New:** UUIDv7, written once into the entity note's frontmatter | **New:** sha256 of the assertion key (F.3). No date, no source |
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

\*Functional means at most one current object per subject (and per `role` where the predicate takes one). Only functional predicates can conflict. "Brain-Core USES(language) Python" and "Brain-Core USES(index) SQLite" coexist. "Brain-Core USES(graph-database) Neo4j" and "Brain-Core USES(graph-database) Kuzu" with overlapping TRUE days (J.2) produce a **conflict** (J.2). Both claims keep their lifecycle, origin and verification.

**`role` is part of what a functional predicate means**, so it is part of the claim's identity (F.3). Without it, "uses Neo4j as the graph database" and "uses Neo4j as a cache" would be one claim. The role vocabulary for `USES` is open text in v1, normalised (lowercase, hyphens), and listed by the M0 census **[Q]**.

**[Q]** The predicates already in users' `relations` tables are unknown to this audit; it did not open the owner's database. M0's census counts them, so the mapping table gets fixed from real data before v1 is frozen.

### F.3 Claim model (pydantic) [P][T]

The model below is **executable**. The checker runs these blocks (`# audit-code`) together with the SQL of L.1, so the code shown is the code tested. It separates five identities:

| Identity | Key | Changes when |
|---|---|---|
| **Content** | `record_id`: sha256 of the normalised text (knowledge: of `source#heading`), as in 0.9 | the wording changes |
| **Source** | `source_id`: `vault:<path>`, `notes:<root>/<path>`, `archive:<root>/<path>`; never an absolute path (G11) | a file moves or is renamed inside its store |
| **Occurrence** | `Occurrence.id()`: source, record, and the record's ordinal in that source | the copy leaves that source |
| **Version** | `content_hash`: sha256 of the exact text | any byte of the text changes |
| **Evidence row** | `(claim_id, occurrence id, rule)` | — |
| **Claim** | `ClaimKey.id()`: subject, predicate, role, typed object, on canonical ids | a merge or predicate rename re-keys it, and `identity_redirects` keeps the old id |
| **Entity** | UUIDv7 in the entity note's frontmatter | never: a merge sets `merged_into` on the loser, and the id is never reused |
| **Redirect** | `(kind, old_id)` → `new_id`, with a cause | — |

**Comparing identity strategies for an occurrence.** The simplest one that survives ordinary file work wins.

| Strategy | Copy in another file | Edit above it | Move or rename | Two identical lines | Writes to the user's text | Verdict |
|---|---|---|---|---|---|---|
| Content hash only (2.1's ledger) | **inherits the original's time** (finding) | stable | stable | collapse into one | no | rejected |
| `(absolute path, line)` | separate | **every line below shifts** | breaks | separate | no | rejected |
| `(source_id, line)` | separate | shifts | breaks inside a store | separate | no | rejected as identity; kept as a locator for citations |
| Obsidian block ids (`^abc123`) on every line | separate | stable | stable | separate | **yes: thousands of edits to the owner's notes** | rejected |
| **`(source_id, record_id, ordinal)`** | separate | stable | carried by an unambiguous move (ledger) | separate, by ordinal | no | **chosen** |

```python
# audit-code F.3 ─────────────────────────────────────────────────────────────────────────────
from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from datetime import date, datetime
from enum import StrEnum
from itertools import combinations
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

Level = Literal["high", "medium", "low"]
Validity = Literal["true", "false", "unknown"]
FROZEN = ConfigDict(extra="forbid", frozen=True)


def h(*parts: object) -> str:
    """Every derived key: sha256 of a JSON list, first 32 hex characters."""
    return hashlib.sha256(json.dumps(parts, default=str).encode()).hexdigest()[:32]


class Lifecycle(StrEnum):  # review state of the assertion, nothing else (J.2)
    CANDIDATE = "candidate"
    ACCEPTED = "accepted"
    REJECTED = "rejected"


class Origin(StrEnum):  # how ONE evidence row came to be
    USER = "user"
    AGENT = "agent"
    MARKUP = "markup"
    EXTRACTED = "extracted"
    INFERRED = "inferred"
    REFLECTION = "reflection"
    EXTERNAL = "external"


class Verification(StrEnum):  # strongest first; a claim takes its strongest evidence
    STATED = "stated"
    APPROVED = "approved"
    DERIVED = "derived"
    UNVERIFIED = "unverified"


class ClaimKey(BaseModel):
    """What is asserted. A claim's id hashes this and nothing else."""

    model_config = FROZEN
    subject: str  # entity UUID, after merged_into is followed
    predicate: str  # ontology name, after `renames:`
    role: str = ""  # qualifies a functional predicate: USES(graph-database) != USES(cache)
    object_entity: str | None = None
    object_literal: str | None = None
    datatype: Literal["text", "int", "version", "port", "url", "date"] | None = None

    @model_validator(mode="after")
    def _one_object(self) -> Self:
        if (self.object_entity is None) == (self.object_literal is None):
            raise ValueError("exactly one of object_entity, object_literal")
        if (self.object_literal is None) != (self.datatype is None):
            raise ValueError("a literal needs a datatype; an entity has none")
        return self

    def id(self) -> str:
        if self.object_entity is not None:
            obj: tuple[str, str] = ("e", self.object_entity)
        else:
            obj = (f"l:{self.datatype}", " ".join(str(self.object_literal).split()))
        return h("claim/1", self.subject, self.predicate, self.role, *obj)


class Occurrence(BaseModel):
    """One copy of a record's text in one source. Content identity is `record_id` (G.2)."""

    model_config = FROZEN
    source_id: str  # "vault:decisions_log.md", "notes:shared/x.md": never an absolute path (G11)
    record_id: str = Field(min_length=16)  # sha256 of the normalised text, as in 0.9
    ordinal: int = Field(ge=1)  # the 1st, 2nd, ... copy of this record_id in this source

    def id(self) -> str:
        return h("occ/1", self.source_id, self.record_id, self.ordinal)


EntityType = Literal["person", "organization", "project", "component", "technology", "concept",
                     "mission"]


class Entity(BaseModel):
    """A thing claims are about. Canonical form: an Obsidian note in vault/entities/ (F.1)."""

    model_config = FROZEN
    id: str  # UUIDv7, written once into the note's frontmatter; survives renames and moves
    type: EntityType
    name: str
    source_id: str  # "vault:entities/Neo4j.md"
    merged_into: str | None = None  # set on the losing note of a merge; the note stays
    ontology: int = 1
    aliases: frozenset[str] = frozenset()  # normalised (NFKC, casefold): the aliases table


class Mention(BaseModel):
    """An occurrence that names an entity, found without a model (wikilink, alias, tag)."""

    model_config = FROZEN
    occurrence: Occurrence
    entity_id: str
    how: Literal["wikilink", "alias", "tag", "extracted"]


class Redirect(BaseModel):
    """An identity that was retired, and what replaced it. One table for every kind, so any
    old id found in an event, a review or an eval label can be followed to the current one."""

    model_config = FROZEN
    kind: Literal["entity", "claim", "record"]
    old_id: str
    new_id: str
    cause: Literal["merge", "rename", "merge+rename", "id-scheme"]  # id-scheme: G11 `was:` lines


class Evidence(BaseModel):
    """One occurrence supporting one claim through one rule. Row key: (claim, occurrence, rule)."""

    model_config = FROZEN
    occurrence: Occurrence
    rule: str  # "relations.md/1", "decision-field/1", "extract:<model>/<date>"
    line: int = 0  # where it stands now: for citation only, never identity
    content_hash: str  # sha256 of the exact text of this version: the ledger's version key
    subject_name: str  # the raw names as written, so an alias change can re-resolve them
    object_name: str | None = None
    stated_date: date | None  # the date the text gives; None = undated. Valid time only
    event_date: date | None = None  # the day the described event happened, when stated
    valid_from: date | None = None  # an explicit start: meta `valid:`, a decision's own date
    valid_to: date | None = None  # an explicit end: meta `until:` (exclusive)
    timeless: bool = False  # meta `valid: always`; never inferred
    recorded_at: datetime  # transaction time, from the ledger, never from the text (J.1)
    recorded_by: Literal["write", "ingest", "move"]
    origin: Origin
    verification: Verification
    confidence: Level | None = None
    quote: str = Field(min_length=1, max_length=300)  # must occur in the record (grounding)

    @model_validator(mode="after")
    def _time(self) -> Self:
        if self.timeless and (self.valid_from or self.valid_to):
            raise ValueError("timeless takes no valid_from / valid_to")
        if self.valid_from and self.valid_to and self.valid_to <= self.valid_from:
            raise ValueError("valid_to must be after valid_from")
        return self

    def start(self) -> tuple[date | None, bool]:
        """Where this evidence says the claim holds from, and whether that is a stated start
        (`valid:`, which also says "not before") or only the record's own date ("held then")."""
        return (self.valid_from, True) if self.valid_from else (self.stated_date, False)


class Period(BaseModel):
    """One stretch of a claim's validity, with every evidence row that speaks to it (J.1)."""

    model_config = FROZEN
    evidence: tuple[Evidence, ...]
    link_end: date | None = None  # a superseding record that does not assert the claim starts

    @property
    def timeless(self) -> bool:  # some row says `valid: always`
        return any(e.timeless for e in self.evidence)

    @property
    def undated(self) -> bool:  # some row has no date at all: it speaks for today only
        return any(e.start()[0] is None and not e.timeless for e in self.evidence)

    @property
    def stated(self) -> bool:  # some row states a start (`valid:`), which also says "not before"
        return any(e.valid_from for e in self.evidence)

    def votes(self, d: date, today: date) -> tuple[int, int]:
        """How many rows say the claim holds on d, and how many say it does not."""
        yes = no = 0
        for e in self.evidence:
            start, stated = e.start()
            if e.valid_to is not None and d >= e.valid_to:
                no += 1
            elif e.timeless:
                yes += 1  # "always": true on every day, one vote among the others
            elif start is None:
                yes += d == today  # undated: a standing fact, current now, silent on the past
            elif d >= start:
                yes += 1
            elif stated:
                no += 1  # before a stated start: "not yet"
        return yes, no

    def at(self, d: date, today: date) -> Validity:
        if self.link_end is not None and d >= self.link_end:
            return "false"  # superseded: ends every row of the period, a timeless one included
        yes, no = self.votes(d, today)
        if yes and not no:
            return "true"
        if no and not yes:
            return "false"
        return "unknown"  # the sources disagree, or none of them speaks about d

    @property
    def true_from(self) -> date | None:
        """Stored for SQL. With a stated start: the latest one (TRUE needs every stated start
        passed). Otherwise the first dated row. None: no dated row."""
        stated = [e.valid_from for e in self.evidence if e.valid_from]
        starts = [s for s, _stated in (e.start() for e in self.evidence) if s]
        return max(stated) if stated else min(starts) if starts else None

    @property
    def true_to(self) -> date | None:  # exclusive: the first stated end, or the link end
        ends = [e.valid_to for e in self.evidence if e.valid_to]
        return min([*ends, *([self.link_end] if self.link_end else [])], default=None)

    def true_on(self, d: date, today: date) -> bool:
        """Exactly `at(d) == "true"`, from the stored summary alone: what the SQL predicate does."""
        if self.true_to is not None and d >= self.true_to:
            return False
        if self.stated:
            return self.true_from is not None and d >= self.true_from
        return self.timeless or (self.true_from is not None and d >= self.true_from) or (
            self.undated and d == today)

    @property
    def disputed(self) -> bool:
        """Some dated window where rows disagree: a stated start after another row's start or
        after an "always", two different stated ends, or an "always" with a stated end."""
        starts = [s for s, _stated in (e.start() for e in self.evidence) if s]
        stated = [e.valid_from for e in self.evidence if e.valid_from]
        ends = {e.valid_to for e in self.evidence if e.valid_to}
        return bool(stated and (self.timeless or min(starts) < max(stated))) or len(ends) > 1 or bool(
            self.timeless and ends)


class Conflict(BaseModel):
    """Two claims of one functional (subject, predicate, role) TRUE on the same days. Stored
    without reference to today, so the computed tier does not change with the calendar."""

    model_config = FROZEN
    other: str  # the conflicting claim's id
    kind: Literal["functional_overlap"]
    scope: Literal["interval", "current"]  # current: through an undated row, so on "today" only
    overlap_from: date | None  # None: no lower bound
    overlap_to: date | None  # exclusive; None: no upper bound
    acknowledged: bool = False  # an `ack` line in claim_reviews.md: both true, by a person

    def active_on(self, d: date, today: date) -> bool:
        """Both claims are TRUE on d (given today). An interval conflict holds on every day of
        its window; a current one only on today, when today falls in its window."""
        inside = (self.overlap_from is None or d >= self.overlap_from) and (
            self.overlap_to is None or d < self.overlap_to)
        return inside and (self.scope == "interval" or d == today)


class Claim(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    key: ClaimKey
    lifecycle: Lifecycle  # from verification and claim_reviews.md (J.2)
    verification: Verification
    origins: frozenset[Origin]  # every evidence row's origin, kept through conflicts and merges
    confidence: Level | None = None
    evidence: list[Evidence] = Field(min_length=1)  # no evidence, no claim
    periods: list[Period] = Field(min_length=1)
    conflicts: list[Conflict] = []
    retracted_at: datetime | None = None  # the ledger time of the retract line
    aliases: frozenset[str] = frozenset()  # earlier ids of this claim: merges, renames (F.5)

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        if self.id != self.key.id():
            raise ValueError("id must be key.id()")
        if self.lifecycle is Lifecycle.ACCEPTED and self.verification is Verification.UNVERIFIED:
            raise ValueError("an unverified claim stays a candidate until a person approves it")
        if self.retracted_at and self.lifecycle is not Lifecycle.REJECTED:
            raise ValueError("a retracted claim is rejected")
        rows = [(e.occurrence.id(), e.rule) for e in self.evidence]
        if len(rows) != len(set(rows)):
            raise ValueError("one occurrence supports a claim once per rule")
        return self

    @property
    def disputed(self) -> bool:  # a conflict is on record and no person acknowledged it
        return any(not c.acknowledged for c in self.conflicts)

    def disputed_on(self, d: date, today: date) -> bool:  # what recall shows for day d
        return any(not c.acknowledged and c.active_on(d, today) for c in self.conflicts)

    def at(self, d: date, today: date) -> Validity:
        got = {p.at(d, today) for p in self.periods}
        return "true" if "true" in got else "unknown" if "unknown" in got else "false"
```

**Mapping to SQL (checked).**

| Model | Table | Not a column of that table |
|---|---|---|
| `Evidence` | `claim_evidence`: the occurrence flattened into `occ_id`, `source_id`, `record_id`, `ordinal`, plus `claim_id` | — |
| `ClaimKey` + `Claim` | `claims` (plus `rank`, for traversal) | `origins`: computed from evidence. `evidence`, `periods`, `conflicts`: their own tables. `aliases`: `identity_redirects` |
| `Period` | `claim_periods`: `true_from`, `true_to`, `link_end`, `timeless`, `undated`, `stated`, `disputed` | `evidence`: membership is recomputed by `build_periods` |
| `Conflict` | `claim_conflicts`: `other` becomes the pair `(claim_a, claim_b)`, one row per overlap window (`seq`), with its `scope` | — |
| `Review` (F.5) | `claim_reviews`: `key` and `other` as JSON, plus the canonical ids and the line's occurrence | — |
| `LedgerRow` (J.1) | `record_ledger` (in `journal.db`) | — |
| `Entity` | `entities` (plus `degree`, computed) | `aliases`: the `aliases` table |
| `Mention` | `mentions`: the occurrence flattened | — |
| `Redirect` | `identity_redirects` | — |

Foreign keys, and where none is used on purpose:

| Foreign key | Kind |
|---|---|
| `aliases.entity_id`, `mentions.entity_id` → `entities` | `ON DELETE CASCADE` |
| `claim_periods.claim_id`, `claim_conflicts.claim_a/b` → `claims` | `ON DELETE CASCADE` |
| `entities.merged_into` → `entities` | `DEFERRABLE INITIALLY DEFERRED`: a rebuild may insert a merge chain in any order |

None on purpose:

- `claim_evidence.claim_id`, because claims are computed *from* evidence
- `claim_reviews.claim_id`, because a rejection must outlive the evidence of the claim it rejects
- `identity_redirects.new_id`, because it may name an entity, a claim or a record

The checker enforces each with `PRAGMA foreign_keys = ON`, as `storage/db.py` sets it.

The brief's categories, on this model:

| Category | Representation |
|---|---|
| Verified fact | `accepted` with verification `stated` or `approved` |
| User-provided | an evidence row with `origin=user` |
| AI-extracted | `origin=extracted`: `candidate` / `unverified` until approved |
| AI assumption | `origin=inferred`: never accepted without approval |
| Proposed decision | a pending decision in `executive_state.md`; claims from the extraction inbox are `candidate` |
| Approved decision | a `decisions_log.md` entry; its claims are `accepted` / `derived` |
| Outdated | still `accepted`; its period has a `true_to` |
| Contradictory | a conflict row, `disputed` while not acknowledged |
| Disputed dates | a period with `disputed`: the days where rows disagree answer *unknown* (J.1) |

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

The second decision is linked to the first by the existing repeated-title rule, which records `supersedes` (`vault.py`, `_insert_entry`). The derived state on 2026-12-12, abridged (`content_hash`, `subject_name` and `object_name` are left out):

```json
[
  {"id": "3f9c…", "key": {"subject": "<Brain-Core>", "predicate": "USES", "role": "graph-database",
                          "object_entity": "<Neo4j>"},
   "lifecycle": "accepted", "verification": "stated", "origins": ["markup", "agent"],
   "periods": [{"true_from": "2026-11-21", "true_to": "2026-12-10", "link_end": "2026-12-10",
                "timeless": false, "disputed": false}],
   "evidence": [
     {"occurrence": {"source_id": "vault:decisions_log.md", "record_id": "9f2c…", "ordinal": 1},
      "rule": "decision-field/1", "line": 12, "stated_date": "2026-11-21", "valid_from": "2026-11-21",
      "event_date": "2026-11-21", "recorded_at": "2026-11-21T09:14:02Z", "recorded_by": "write",
      "origin": "markup", "verification": "derived",
      "quote": "Use [[Neo4j]] as the Brain-Core graph database."},
     {"occurrence": {"source_id": "vault:relations.md", "record_id": "1b7e…", "ordinal": 1},
      "rule": "relations.md/1", "line": 3, "stated_date": "2026-11-22",
      "recorded_at": "2026-11-22T17:40:51Z", "recorded_by": "write", "origin": "agent",
      "verification": "stated", "quote": "[[Brain-Core]] —[USES: graph-database]→ [[Neo4j]]"}],
   "conflicts": []},
  {"id": "c41a…", "key": {"subject": "<Brain-Core>", "predicate": "USES", "role": "graph-database",
                          "object_entity": "<Kuzu>"},
   "lifecycle": "accepted", "verification": "derived", "origins": ["markup"],
   "periods": [{"true_from": "2026-12-10", "true_to": null, "link_end": null,
                "timeless": false, "disputed": false}],
   "evidence": [{"occurrence": {"source_id": "vault:decisions_log.md", "record_id": "a71d…", "ordinal": 1},
                 "rule": "decision-field/1", "line": 4, "stated_date": "2026-12-10",
                 "valid_from": "2026-12-10", "event_date": "2026-12-10",
                 "recorded_at": "2026-12-10T08:02:37Z", "recorded_by": "write", "origin": "markup",
                 "verification": "derived",
                 "quote": "Replace [[Neo4j]] with [[Kuzu]] as the graph database."}],
   "conflicts": []}
]
```

Why this state:

- The Neo4j period ends on 2026-12-10, because the record that supersedes its decision evidence does not assert it.
- The two periods do not overlap, so there is no conflict.
- If the first decision entry is later deleted, the Neo4j claim survives on its `relations.md` evidence.
  - **Valid time:** 2026-11-21 becomes *unknown*. Only a row dated 11-22 remains, and it says nothing about 11-21 (example E6, tested).
  - **Transaction time:** a `known_at` before the deletion still sees the decision row through the derivation journal, and answers *true* for 11-21 (T11, tested).

The questions on 2026-12-12:

| Question | Answered from |
|---|---|
| Originally selected | the earliest period over the claims of (Brain-Core, USES, graph-database) |
| Why it changed | the **Reason** field of the superseding record |
| When it changed | the end of that period, and the superseding record's `event_date` |
| Which decisions were affected | records whose claims `APPLIES_TO` or `MENTIONS` Neo4j with a period overlapping [2026-11-21, 2026-12-10) |

### F.5 Entity resolution, merging and re-keying [P][T]

1. **Normalise.** NFKC, casefold, collapse whitespace, strip surrounding punctuation and a trailing version (`Neo4j 5.18` → `neo4j`, with the version kept as a `VERSION` literal claim when it matters).
2. **Exact.** Look up the alias table. One hit resolves it.
3. **Ambiguous.** Two or more hits: resolve by the entity type the predicate's domain or range expects. Still ambiguous: a candidate in the inbox, and the evidence row keeps the raw name until it resolves.
4. **Near.** Same type and token Jaccard ≥ 0.8, or edit distance ≤ 2 on names of 6 characters or more: a **merge suggestion** in the inbox, **never automatic**. Hindsight's docs admit that fuzzy merging over-merges **[E]**.
5. **Merge.** The surviving note gains the loser's aliases. The loser's note gets `merged_into: <uuid>` and stays. Ids are never reused. Log an `entity_merged` event.
6. **Validation.** A claim whose subject or object type violates the predicate's domain or range is downgraded to `RELATED_TO` (the raw predicate kept) and flagged in `brain_status`. It is never silently dropped.
7. **Ontology versioning.** `ontology.yaml` ships with `version`, the types, predicates, domain and range, functional flags and a `renames:` map. An entity note records `ontology: N`. A version bump rebuilds the derived tier and never rewrites a vault file.

**Re-keying after a merge or a rename (checked).** A claim id hashes the canonical key: `merged_into` chains followed, predicates renamed. So a merge or rename gives some claims new ids. Nothing about them may be lost:

| What | How it stays traceable |
|---|---|
| Old ids | `identity_redirects` maps every retired id of every kind to the current one: claims from evidence and review lines (cause `merge`, `rename` or `merge+rename`), entities from `merged_into`, records from G11's `was:` lines (cause `id-scheme`). An old id found in an event, a review or an eval label is followed through it |
| Evidence | Rows keep the raw names they were derived from and are re-derived under the new resolution. The derivation journal keeps the pre-merge versions, so the merge itself is in the transaction history |
| Reviews | A `claim_reviews.md` line keeps the key **as written** and is applied to its canonical claim. Reviews are ordered by their ledger time, never by the date written on the line |
| Disagreeing reviews | When claims merged into one carry different latest decisions, `merged_reviews_disagree` is reported. The later decision applies (default, R item 9) |
| Conflicts | Recomputed after every merge. An ack follows its pair; an ack whose pair no longer conflicts is reported as `orphaned_ack` |
| Undo a merge (`merged_into` removed) | A rebuild restores the earlier claims, each with its own evidence and its own reviews as written, and the merge redirect disappears **[T]**. A review written *after* the merge names the survivor's key and stays with the survivor's claim |
| Alias changes | Evidence keeps the raw names; a changed alias re-resolves them, so the affected claims re-key like a merge **[P]** |
| Duplicate claims | Two rows with the same canonical key are one claim with two evidence rows. Two different assertions are never merged: different objects stay two claims, and a functional pair becomes a conflict |
| AI-suggested equivalences | Only ever a merge *suggestion* in the inbox. Nothing sets `merged_into` but a person editing a note |

```python
# audit-code F.5 ─────────────────────────────────────────────────────────────────────────────
class Review(BaseModel):
    """One line of claim_reviews.md. Reviews are ordered by their ledger time, never by the
    date written on the line, and keep the key as it was written (F.5)."""

    model_config = FROZEN
    action: Literal["reject", "retract", "restore", "ack"]
    key: ClaimKey  # as written, before any later merge or rename
    other: ClaimKey | None = None  # ack: the other claim of the pair
    recorded_at: datetime
    reason: str = ""


Link = tuple[str, str, date]  # (old record_id, new record_id, the new record's start): supersedes


def canonical(key: ClaimKey, merged: Mapping[str, str], renames: Mapping[str, str]) -> ClaimKey:
    """The key after merged_into chains (entity notes) and ontology renames."""

    def ent(x: str) -> str:
        seen: set[str] = set()
        while x in merged and x not in seen:
            seen.add(x)
            x = merged[x]
        return x

    return ClaimKey(
        subject=ent(key.subject),
        predicate=renames.get(key.predicate, key.predicate),
        role=key.role,
        object_entity=ent(key.object_entity) if key.object_entity else None,
        object_literal=key.object_literal,
        datatype=key.datatype,
    )


Window = tuple[date, date]  # half-open [lo, hi); date.min / date.max: no bound


def _windows(p: Period) -> tuple[Window | None, Window | None]:
    """Where a period is TRUE, without reference to today: the dated window, and the window in
    which "today" is TRUE through an undated row (exactly `Period.true_on`)."""
    hi = p.true_to or date.max
    if p.stated:
        lo = p.true_from or date.min
        return ((lo, hi) if lo < hi else None), None
    dated = None
    if p.timeless:
        dated = (date.min, hi)
    elif p.true_from is not None and p.true_from < hi:
        dated = (p.true_from, hi)
    return dated, ((date.min, hi) if p.undated else None)


def _overlaps(a: Claim, b: Claim) -> list[tuple[str, date, date]]:
    """Every window where both are TRUE: interval rows for dated windows, current rows where
    an undated row is needed on at least one side."""
    out = []
    for pa in a.periods:
        da, ua = _windows(pa)
        for pb in b.periods:
            db_, ub = _windows(pb)
            if da and db_ and max(da[0], db_[0]) < min(da[1], db_[1]):
                out.append(("interval", max(da[0], db_[0]), min(da[1], db_[1])))
            for wa, wb in ((ua, db_), (da, ub), (ua, ub)):
                if wa and wb and max(wa[0], wb[0]) < min(wa[1], wb[1]):  # each pair has an undated side
                    out.append(("current", max(wa[0], wb[0]), min(wa[1], wb[1])))
    return sorted(set(out), key=lambda o: (o[0], o[1], o[2]))


def derive(
    rows: Sequence[tuple[ClaimKey, Evidence]],  # (key as derived from the text, evidence)
    links: Sequence[Link],
    reviews: Sequence[Review],
    merged: Mapping[str, str],  # entity id -> merged_into
    renames: Mapping[str, str],  # predicate -> current name
    functional: set[str],  # predicates with one current object per (subject, role)
) -> tuple[dict[str, Claim], list[Redirect], list[str]]:
    """Claims are a pure function of evidence, links, reviews, merges and renames (G.2).
    Returns the claims, the claim redirects (old id -> current id) and what a person should
    look at. Nothing here merges two different assertions, and nothing accepts anything."""
    report: list[str] = []
    aliases: dict[str, str] = {}
    causes: dict[str, str] = {}

    def retire(raw: ClaimKey, key: ClaimKey) -> None:
        if raw.id() != key.id() and raw.id() not in aliases:
            aliases[raw.id()] = key.id()
            moved = (raw.subject, raw.object_entity) != (key.subject, key.object_entity)
            renamed = raw.predicate != key.predicate
            causes[raw.id()] = "merge+rename" if moved and renamed else "merge" if moved else "rename"

    by: dict[str, tuple[ClaimKey, list[Evidence]]] = {}
    for raw, ev in rows:
        key = canonical(raw, merged, renames)
        retire(raw, key)
        by.setdefault(key.id(), (key, []))[1].append(ev)
    decided: dict[str, tuple[str, datetime, str]] = {}  # claim -> (action, when, key it was on)
    acks: list[tuple[str, str]] = []
    for r in sorted(reviews, key=lambda r: (r.recorded_at, r.key.id())):
        ckey = canonical(r.key, merged, renames)
        cid = ckey.id()
        retire(r.key, ckey)
        if r.action == "ack":
            other = canonical(r.other, merged, renames).id() if r.other else ""
            acks.append((cid, other))
            continue
        prev = decided.get(cid)
        if prev and prev[2] != r.key.id() and prev[0] != r.action:
            report.append(f"merged_reviews_disagree {cid[:8]}: {prev[0]} then {r.action}")
        decided[cid] = (r.action, r.recorded_at, r.key.id())
    claims: dict[str, Claim] = {}
    for cid, (key, ev) in by.items():
        records = {e.occurrence.record_id for e in ev}
        ends = [d for old, new, d in links if old in records and new not in records]
        ver = min((e.verification for e in ev), key=list(Verification).index)
        action, at = decided.get(cid, ("", None))[:2]
        if action in ("reject", "retract"):
            life = Lifecycle.REJECTED
        elif ver is Verification.UNVERIFIED:
            life = Lifecycle.CANDIDATE
        else:
            life = Lifecycle.ACCEPTED
        levels = [e.confidence for e in ev if e.confidence]
        claims[cid] = Claim(
            id=cid,
            key=key,
            lifecycle=life,
            verification=ver,
            origins=frozenset(e.origin for e in ev),
            confidence=min(levels, key=["high", "medium", "low"].index) if levels else None,
            evidence=ev,
            periods=build_periods(ev, ends),
            retracted_at=at if action == "retract" else None,
            aliases=frozenset(a for a, c in aliases.items() if c == cid),
        )
    groups: dict[tuple[str, str, str], list[Claim]] = {}
    for c in claims.values():
        if c.lifecycle is not Lifecycle.REJECTED and c.key.predicate in functional:
            groups.setdefault((c.key.subject, c.key.predicate, c.key.role), []).append(c)
    found: set[frozenset[str]] = set()
    for members in groups.values():
        for a, b in combinations(sorted(members, key=lambda c: c.id), 2):
            hits = _overlaps(a, b)
            if not hits:
                continue
            pair = frozenset((a.id, b.id))
            found.add(pair)
            ack = any(frozenset(x) == pair for x in acks)
            for scope, lo, hi in hits:
                for me, you in ((a, b), (b, a)):
                    me.conflicts.append(Conflict(
                        other=you.id, kind="functional_overlap", scope=scope,  # type: ignore[arg-type]
                        overlap_from=None if lo == date.min else lo,
                        overlap_to=None if hi == date.max else hi, acknowledged=ack,
                    ))
    for x, y in acks:
        if frozenset((x, y)) not in found:
            report.append(f"orphaned_ack {x[:8]}/{y[:8]}: the pair no longer conflicts")
    redirects = [Redirect(kind="claim", old_id=o, new_id=n, cause=causes[o])  # type: ignore[arg-type]
                 for o, n in sorted(aliases.items())]
    return claims, redirects, report
```

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
| 15 | Errors and retries | An unreadable file is skipped and named in health; a missing vault is an error; the Hindsight queue | A source that fails to derive keeps its old raw rows and journal versions (the signature is not updated), exactly like today's index |
| 16 | Deleted and moved files | Delete: rows dropped. Move: delete plus add | Delete: the source's occurrences close in the ledger, its evidence rows retire into the journal, and each claim it touched is recomputed; a claim with other evidence survives. Move: an unambiguous move keeps recording times (J.1); claim ids do not depend on paths, so the claims stay. G.4 lists every case |

### G.2 Claim derivation and reconciliation [P][T]

**Occurrences, not records, carry provenance.** 0.9's `record_meta.md` keys by record id, so every copy of one text shares its keys and dates. That stays the default, and 2.2 adds an optional occurrence form that applies to one copy:

```
- 9f2c1a7b3e5d4c21 | valid: 2026-06-01 | until: 2026-12-10     (every occurrence of the record)
- 9f2c1a7b3e5d4c21@vault:sessions/2026-11-21.md#2 | event: 2026-11-20   (its second copy in that file)
```

Each evidence row's `valid_from`, `valid_to`, `event_date` and `timeless` are resolved in order:

1. the occurrence line
2. the record line
3. the rule's default (`decision-field/1`: the entry's own date as `valid_from`)

**Copies and per-copy meta (issue C) [T].** An occurrence is "the k-th copy of this text in this source", not a physical line. An identical copy inserted above an existing one shifts the ordinals, and by content alone that cannot be told from a copy appended below.

So an occurrence-scoped line `<rid16>@<source>#<k>` applies only while the copies of that text in that source are exactly as they were when the meta line was recorded (its ledger time). If any copy appeared or disappeared since:
- the line is **not applied**, and is reported as `occurrence_meta_ambiguous` (or `occurrence_meta_dangling` when copy k no longer exists)
- the evidence falls back to the record-level line
- the owner re-anchors: rewrites the meta line, or makes the copies distinct (a word, or an Obsidian block id, on the copy that needs its own dates)

Unrelated edits around the copies (line numbers shift) do not trigger it. Recording times are counted the same way: the k-th copy keeps the time the vault first held k copies, which is never earlier than the truth.

They are stored on the row itself (`claim_evidence`), so a period never needs another table to be rebuilt. `record_times` keeps the raw meta lines only to compute the dirty set. 0.9 readers ignore the new form, because their pattern needs `- <16 hex> |` (`vault.py`, `_META`) **[V]**.

**Three tiers of rows.**

| Tier | Tables | Rule |
|---|---|---|
| **Raw**, in `brain.db`: read from one source, keyed by its `source_id` or the meta/review line's occurrence | `records_fts` (exists), `mentions`, `claim_evidence`, `record_times`, `record_links`, `claim_reviews` | Rebuilt per source |
| **Computed**, in `brain.db` | `claims`, `identity_redirects`, `claim_periods`, `claim_conflicts`, `entities.degree` | A pure function of the raw rows, `ontology.yaml` and the ledger's recording times. Since 2.3 it takes no date at all: conflicts that hold only "today" are stored with scope `current` (J.2) Never edited, only recomputed |
| **Journal**, in `journal.db` | `record_ledger`, `ledger_gaps`, `derivation_journal` | Appended by the sync, idempotently. Never rebuilt (L.5) |

**Per sync, for the changed sources:**

```
journal.db, one transaction (idempotent writes):
  1. ledger: compare occurrences with the open ledger rows; close what is gone, open what is new;
     an unambiguous move between sources of this pass carries its recording time (J.1)
  2. derivation journal: close every raw row version that is gone or changed, open every new one
brain.db, one transaction:
  3. dirty := claims with evidence from the changed sources (before)
            ∪ claims whose evidence records or occurrences the changed record_times / record_links name
            ∪ claims the changed claim_reviews name
  4. replace the changed sources' raw rows; dirty ∪= the same sets after
  5. recompute(dirty): claim rows (upsert with ≥ 1 evidence row, delete with none),
     identity_redirects, periods, lifecycle (reviews in ledger order), conflicts for every
     (subject, predicate, role) group touched, degree of every entity named
  6. update the sources' signatures LAST
```

**Properties.**

1. **Multi-source survival [T: T10].** The same text in two files, or twice in one file, is two evidence rows. Deleting one source removes only its rows.
2. **Incremental equals rebuild [T: reconcile22, 150 random sequences].** Random sequences of add, delete, edit, copy and move, with crashes, rebuilds and `brain.db` deletions mixed in. After each sequence the incremental state equals a fresh rebuild from the same vault and journal.
3. **The journal reconstructs the past [T].** At every past sync, the evidence rows the journal says existed equal the rows `brain.db` held then. A planted bug (a journal that never closes a changed row) is caught.
4. **Rebuilds and deletions add nothing to the journal [T].**
5. **Cross-file effects are explicit.** `record_meta.md` and `claim_reviews.md` change other sources' claims only through the dirty set. Entity notes change name resolution, so they are synced first, and a changed alias marks dirty the evidence rows whose raw names match it **[P]**.
6. **Locator churn [P, R item 18].** `line` is part of an evidence row, so a line inserted above makes a new journal version of every row below it. Correct, but noisy. Excluding the locator from versioning is an owner decision.

The prototype recomputes the whole computed tier on each sync; the dirty set of step 3 is the optimisation that computes the same rows for fewer claims. Its equality to the full recompute is what T8 checks in M3.

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

### G.4 Failure-mode matrix [P][T]

**T** = run in a prototype (test id; see the validation report, `docs/AUDIT_2_2_VALIDATION.md`). **P** = proposed, not yet run.

| Event | Expected behaviour | Data-loss risk | Recovery | Status |
|---|---|---|---|---|
| **Duplicate content**: the same text in two files or stores | one record id (content), two occurrences, two evidence rows with their own recording times and stated dates; record-level keys are shared | none | — | T (T10, L5) |
| **Duplicate occurrences**: the same line twice in one file | ordinals 1 and 2: two occurrences (the k-th copy, not a physical line). Inserting an identical copy, above or below, changes the copies: per-copy meta lines are then reported as ambiguous and not applied, never moved to another copy (G.2) | none: the meta line stays in the vault, unapplied until re-anchored | rewrite the meta line, or make the copies distinct | T (L4, C1–C7) |
| **File moved** inside a store (also `brain weekly`'s archive move) | new source id, new occurrence. An unambiguous move (one copy left, one arrived, same pass) keeps recording time and presence; anything else is new: late, never early. Facts keep their record ids; knowledge sections re-key (`source#heading`) | knowledge keys and vectors detach from the renamed file's sections | R item 13: accept, or `brain index --relink` writes `was:` lines | T (L6, L7, G11-T4) |
| **File renamed** | as a move | as a move | as a move | T (L6) |
| **Folder relocated**: a notes or archive root moved to another parent | 0.9.1: every id in it changes (G11). 2.2: ids hash `<store>:<root name>/<path>`, so nothing changes | none after M1b | — | T (G11-T1) |
| **Root folder renamed** | with `name:` configured: ids unchanged. Without: ids change; `brain doctor` sees every file reappear under a new root and offers `name:` | keys detach until `name:` is set | set `name:` and sync: ids return | T (G11-T2, T3: ids); P (detection) |
| **Record edited** | facts: new record, new occurrence, new version; knowledge: same occurrence, new version. The journal keeps the old evidence row; `known_at` before the edit sees the old wording | none | — | T (L3, reconcile22 property) |
| **Record deleted** | the occurrence closes; its evidence row retires into the journal; the claim lives on other evidence or disappears; reviews stay in `claim_reviews.md` | none: the journal keeps it for `known_at` | restore the line: same occurrence, new presence interval, first recording time kept | T (L8, E6, T11, property) |
| **Claim retracted** | `retract` line: lifecycle `rejected`, `retracted_at` = the line's ledger time; evidence, origins and verification kept; `known_at` before the retraction sees it accepted | none | a `restore` line | T (E4); P (`known_at` over reviews) |
| **Entity merged** | claims re-keyed on canonical ids; `identity_redirects` maps every old id; reviews follow their key as written; conflicts recomputed; disagreeing reviews and orphaned acks reported | none | remove `merged_into`: a rebuild restores the earlier claims, evidence and reviews exactly | T (re-keying, undo) |
| **Predicate renamed** | as a merge, cause `rename` | none | revert `renames:` | T |
| **Index rebuild** | the derived tier in `brain.db` is recomputed identically; `journal.db` gains no row | none | — | T (150 random sequences) |
| **`brain.db` deleted** | rebuilt from the vault; recording times from `journal.db`; `events` and `metrics` lost, as today | operational logs only | — | T |
| **`brain.db` corrupted** | detected by `integrity_check`, moved aside, rebuilt | operational logs only | as deletion | T |
| **`journal.db` deleted or corrupted** | new epoch; earlier transaction-time questions answer *unknown* | transaction history since the last backup | restore the newest journal backup | T (L10, L11) |
| **Backup restored** | union merge; open intervals closed at the backup's time; a `restore` gap until the first sync after the loss | the gap's history: answered *unknown*, never guessed | — | T (L11) |
| **Vault restored from an older copy** | vanished lines close, returning lines reopen with their first recording time, unseen text is recorded now | none for what the ledger saw; newer lines the restore removed are gone from the vault, but their history stays in the journal | the owner's vault backups | T (L8) |
| **Agent folder moved to another computer** | both files travel; ids carry no absolute path | none, if `data/` is copied | copy `data/journal.db` (or restore its backup) | T (copy scenario) |
| **Crash between the two commits** | the next sync converges; recording times are those of the first sync that saw the change | none | automatic | T (reconcile22) |

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
| Truncation | each of these sets `truncated` and names where it happened:<br>• seeds beyond `max_seeds`<br>• a frontier larger than `max_frontier`<br>• a scan window that came back full<br>• `fan` reached with rows left<br>• a hub reached through a path (also listed in `hubs`)<br>• `max_edges` reached<br>`depth`: edges continue past `max_hops` (by design, but reported)<br>The walk returns the set of reasons. Recall reports "graph expansion truncated (<reasons>) at <entity>", never silence |

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
   SELECT 1 FROM claim_periods p WHERE p.claim_id = c.id
      AND (p.true_to IS NULL OR :d < p.true_to)     -- a stated end or a link end, timeless too
      AND ((p.stated = 1 AND p.true_from <= :d)     -- every stated start has passed
        OR (p.stated = 0 AND (p.timeless = 1
                              OR (p.true_from IS NOT NULL AND p.true_from <= :d)
                              OR (p.undated = 1 AND :d = :today)))))
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

**Completeness [T].** A fast walk that misses evidence is not a success, so the bounded walk was compared with an exhaustive one (the same rules, no limits, the same depth):

| Check | Result |
|---|---|
| 292 random graphs (up to 40 claims, random validity), random limits, up to 7 seeds | the bounded walk never returned an edge the exhaustive one did not. Wherever it left edges out (46 and 50 graphs in two runs: hypothesis draws new graphs each run), every one reported a reason |
| The real graph (the M0 live copy, 82 relations, 75 entities) | bounded equals exhaustive from every entity; no cut reason; p50 0.09 ms, max 0.79 ms |
| Named cases | disconnected graphs (stays in its component), a missing entity (an empty walk, reported by the resolver), an alias two entities share (both seeded, reported as ambiguous), multiple seeds (the union, each claim once, deterministic), conflicting claims (both returned; the walk picks no winner), a historical `as_of` (only the claims valid then), a ring longer than the depth (`depth` reported) |

These numbers time the traversal function alone, on in-memory SQLite. End-to-end recall latency with a graph net does not exist until M4 and is gated there against the M0 baseline (O.5).

**A pitfall the prototype caught.** A *partial* index (`WHERE lifecycle <> 'rejected'`) is not used for a query that says `lifecycle = 'accepted'`: SQLite does not prove the one implies the other, and it silently scans the table (140 ms instead of 0.7 ms) **[T]**. Hence the plain composite indexes in L.1, and a query-plan assertion in the test.

**The cost of the work bound.** Valid edges beyond an entity's first `scan` index rows are missed for a historical `as_of` on a hub. Open periods sort first, so the current case is unaffected. The miss is reported as `truncated`, never silent.

**The test to add in M4** (`tests/unit/test_graph_walk.py`; the prototype is its first draft):

- Build the hub graph above; it builds in under 1 s.
- Assert edges ≤ `max_edges`, edge rows read ≤ `2·scan·(seeds+frontier)`, queries ≤ `5·(seeds+frontier)`.
- A hub reached through a path is not expanded, and it sets `truncated`. Every other cut sets it too: extra seeds, an oversized frontier, a full scan window, `fan`, `max_edges`, and `depth` when edges continue past the last hop.
- The completeness property (below), on random graphs.
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

### J.1 Time: valid time from the text, transaction time from clocks [P][T]

**Two kinds of question, never mixed.** A stated date never answers a transaction-time question, and a ledger time never answers a valid-time question.

| Question | Axis | Parameters | Evaluated over |
|---|---|---|---|
| "Was X true on D?" | valid time | `as_of = D` | today's evidence, `Claim.at(D)` |
| "What did brain-core hold on K?" | transaction time | `known_at = K` | the raw rows present at K (ledger + derivation journal), derived as of K |
| "On K, what did brain-core hold true for D?" | both | `known_at = K`, `as_of = D` | the rows present at K, then `at(D)` |

**The fields.**

| Field | Belongs to | Source | NULL means |
|---|---|---|---|
| `stated_date` | evidence | the date the text gives (bullet suffix, entry heading, session file day); can be backdated; valid time only | undated line (0.9.0 meaning) |
| `valid_from` / `valid_to` | evidence | occurrence meta line, else record meta line (`valid:`, `until:`), else the rule's default | not stated |
| `event_date` | evidence | a decision's or correction's heading date; `event:` meta | not stated |
| `timeless` | evidence | `valid: always` only; never inferred | — |
| `recorded_at`, `recorded_by` | evidence | the ledger: the write, the first ingest, or an unambiguous move's origin | never NULL once ingested |
| `true_from`, `true_to`, `link_end`, `timeless`, `undated`, `stated`, `disputed` | period | computed (`Period`, F.3). From these alone, `Period.true_on` and the SQL predicate (H.3) give exactly `at() == "true"` (tested on random periods) | `true_from` NULL: no dated row |

**The validity rule (it is `Period.at` in F.3).** Each evidence row of a period votes on day D:

- `valid_from = v` says "true from v, **not before**"
- `stated_date = s` alone says "true on s, and onwards", and is silent before s
- `valid_to = u` says "not from u"
- an undated row speaks only for today
- a `valid: always` row says "true on every day". It is one vote: a stated start in another row still disagrees with it before that start
- a link end (a superseding record that does not assert the claim) ends the period for every row, a `valid: always` row included; it is checked first (issue A)

The claim is **TRUE** when some row says true and none says false, **FALSE** when some say false and none true, and **UNKNOWN** otherwise: either the rows disagree, or none speaks about D. Unknown is never true, and conflict detection (J.2) only looks at TRUE days.

```python
# audit-code J.1 ─────────────────────────────────────────────────────────────────────────────
class LedgerRow(BaseModel):
    """One presence interval of one version at one occurrence. A journal row: never derived,
    never rebuilt, only backed up (J.1, L.5)."""

    model_config = FROZEN
    occ_id: str  # Occurrence.id(): where
    content_hash: str  # sha256 of the exact text: which version
    seen_from: datetime  # the write, or the first sync that found it there
    seen_to: datetime | None = None  # the first sync that found it gone; None = present
    via: Literal["write", "ingest", "move"]
    moved_from: str | None = None  # the occurrence it came from, for an unambiguous move only


def build_periods(evidence: Sequence[Evidence], ends: Sequence[date]) -> list[Period]:
    """Split one claim's evidence into periods. A link end closes the open period; a row that
    starts on or after it opens the next one. Undated rows join the last period."""
    dated = sorted(
        ((s, e) for e in evidence if (s := e.start()[0]) is not None),
        key=lambda se: (se[0], se[1].occurrence.id(), se[1].rule),
    )
    stops = sorted(set(ends))
    groups: list[list[Evidence]] = []
    opened: date | None = None  # the start of the open period
    for s, e in dated:
        if opened is None or any(opened < x <= s for x in stops):
            groups.append([])
            opened = s
        groups[-1].append(e)
    if not groups:
        groups.append([])
    groups[-1].extend(e for e in evidence if e.start()[0] is None)
    out = []
    for g in groups:
        first = min((s for s, _x in (e.start() for e in g) if s), default=None)
        end = next((x for x in stops if first is None or x > first), None)
        out.append(Period(evidence=tuple(g), link_end=end))
    return out
```

**Deterministic examples [T].** Today is 2026-12-12. Each result below is asserted by the checker.

| Example | Day | Result |
|---|---|---|
| E1 two rows, stated 11-01 and 11-20, no starts given | 10-31 · 11-01 · 11-25 | unknown · true · true |
| E2 row A `valid: 11-10`, row B dated 11-05 with no start | 11-04 · 11-07 · 11-10 | false · unknown · true |
| E2b two rows, `until: 12-01` and `until: 12-08` | 11-30 · 12-03 · 12-08 | true · unknown · false |
| E3 recorded 12-10, `valid: 2027-01-01` | 12-12 · 2027-01-01 | false · true |
| E5 true 11-21, superseded 12-10, asserted again 2027-03-01 | 12-01 · 2027-01-15 · 2027-04-01 | true · false · true |
| E6 before deletion: decision `valid: 11-21` + relation dated 11-22 | 11-21 · 11-20 | true · false |
| E6 after deleting the decision entry | 11-21 · 11-22 | unknown · true |
| E7 one row dated 11-22, no start stated | 06-01 · 11-22 | unknown · true |
| E8 one undated line | 06-01 · 12-12 | unknown · true |
| E9 `valid: always` | 1999-01-01 | true |
| E4 a row dated 11-01, then `retract` (ledger 12-12) | any | the claim is `rejected` for every day; origins and verification are kept; `retracted_at` is the line's ledger time |
| T10 three copies of one text, only copy 2 stating `valid: 10-01` | 2026-10-15 | true; with copies 2 and 3 deleted: unknown |
| T11 a hand-written line on 11-25 that says "(2026-01-01)" | `as_of` 2026-06-01 | true (valid time: what the text asserts) |
| T11, the same line | `known_at` 2026-11-24 | not known (transaction time: first seen 11-25) |
| T11 a decision row deleted on 12-01 | `known_at` 11-23, `as_of` 11-21 | true, from the journal; `known_at` 12-05: unknown |

**The review's twelve cases [T].** Each answer below is asserted by the checker (section 10).

| Case | Example | Determined answer |
|---|---|---|
| 1 no known start | E7 | unknown |
| 2 explicit valid-from 03-01 | E3 | false/true |
| 3 explicit valid-to 06-01 | E3b | true/false |
| 4 recorded today, valid since last year | E10 | true |
| 4 ... with known_at yesterday | E10 | not known |
| 5 two claims, overlapping validity | E11 | conflict from 2026-11-20 |
| 6 contradictory, both starts unknown | E12 | past unknown; one `current` conflict: active today, not tomorrow (revision 2.3) |
| 7 future-effective decision | E3 | false |
| 8 retracted claim | E4 | rejected, evidence kept: 1 |
| 9 valid again after superseded | E5 | false/true |
| 10 evidence deleted from one source, kept in another | E6/T10 | true |
| 11 two records, different dates | E1 | true |
| 12 discovered only after it ended | E13 | true/false; known_at 05-01: not known |

**How `as_of` and `known_at` combine (formal).** Let E(K) be the raw rows the journal says existed at K: evidence, links, times and reviews. K = now gives today's rows.

- **`as_of = D` alone** evaluates `Claim.at(D)` over the claims derived from E(now).
- **`known_at = K` alone** derives from E(K) and reports each claim's lifecycle at K, with validity evaluated at K.
- **Both** derive from E(K), then evaluate at D.
- A K inside a ledger gap gives UNKNOWN for every claim. A K before the epoch does too.
- No row recorded after K can contribute, so a fact learned later never leaks into an earlier `known_at` (case 4, case 12, T11).

**Transaction time: the occurrence ledger [T: L1–L11].** One `LedgerRow` per presence interval of one version at one occurrence.

| Event | Ledger effect | Test |
|---|---|---|
| `brain_remember` writes a line | a row `via=write` at the write time; the next sync finds it open and adds nothing | L1 |
| A line appears by hand (backdated or not) | a row `via=ingest` at the first sync that sees it | L2 |
| A wording edit | new record, new occurrence, new row; the old row closes | L3 |
| A second copy in the same file | ordinal 2: its own row and time | L4 |
| A copy to another source | its own row, `via=ingest`, **nothing inherited** | L5 |
| A move: exactly one copy left, exactly one arrived, same text, same sync pass | the new row has `via=move`, `moved_from`; `recorded_at` follows back; presence is continuous | L6 |
| Anything ambiguous (two left, one arrived; across separate sync passes) | treated as delete plus new: late, never early | L7 |
| Delete, then restore | the row closes; a new row opens at the restore. `recorded_at` stays the first time; the gap is "not present" | L8 |
| `brain index --rebuild` | nothing: the ledger is not derived | L9 |

`recorded_at` is the first `seen_from` of this version at this occurrence, following `moved_from` back. It never comes from a copy.

Known limit: when an identical copy is inserted *above* an existing one in the same file, the ordinals swap. The counts stay right, but which physical line owns the older time is arbitrary. That is deterministic and harmless, because the two texts are identical.

**The derivation journal.** The ledger stores hashes, not text. So a deleted or edited evidence row, a changed meta line or a removed review line could not otherwise be reconstructed for `known_at`.

- `derivation_journal` keeps every version of every raw derived row of the kinds `evidence`, `review`, `link` and `time`, with the interval of syncs in which it existed.
- `known_at = K` means `derive(raw rows whose journal interval covers K)`, then evaluate.
- Journal rows are masked like the index. They hold the quote (≤ 300 characters) and dates, never whole records.
- A rebuild must add no journal version (tested in M3).
- **`known_at` must not be exposed before the journal exists**, or it would answer from today's rows.

**Gaps and the epoch.** `ledger_gaps` holds two kinds of window:

- before the first observation (`epoch`)
- from a restored backup's time to the first sync after the loss (`restore`)

A `known_at` inside a gap answers **unknown** (L10, L11).

### J.2 Claim lifecycle, conflict state and the decision lifecycle [P][T]

**The lifecycle states, evaluated:**

| State | Verdict | Why |
|---|---|---|
| `candidate` | **Keep** | Extracted, inferred, reflection or external claims that no person has approved. Ranked down, flagged, never auto-promoted |
| `accepted` | **Keep** | Stated on purpose, approved, or derived by a deterministic rule from records written on purpose |
| `rejected` | **Keep**, with two causes: refused at review (`reject`), or found wrong after acceptance (`retract`, with `retracted_at` = the line's ledger time). Evidence, origins and verification stay (E4); `known_at` before the retraction still sees it accepted | A rejection must survive rebuilds, so it is a line in `claim_reviews.md` |
| `superseded` | **Not a lifecycle state.** It is temporal: a period ended (`true_to`) | A superseded claim was still accepted and true for its period, and it can be true again later (E5) |
| `disputed` | **Not a lifecycle state.** It is conflict state | Detecting a conflict must not change what a claim is |

**Lifecycle derivation.**

1. `rejected` if the latest `reject` / `retract` / `restore` line for the claim, **in ledger order**, is `reject` or `retract`.
2. Otherwise `accepted` if its verification is `stated`, `approved` or `derived`.
3. Otherwise `candidate`.

Approval needs no review line: the agent moves the candidate to `relations.md` with `origin: extracted` and `approved: <date>`, so its evidence is `approved`.

**Conflict state.** It is computed for each functional `(subject, predicate, role)` group, over every pair of non-rejected claims with different objects whose **TRUE** days overlap.

- An unknown window never creates a conflict.
- **Scope (issue B).** A conflict between dated windows has scope `interval` and holds on every day of its window. One that needs an undated row (TRUE only "today") has scope `current`, and holds only on the day that is today, inside its window (`Conflict.active_on`).
  - Stored rows never depend on the date, so the computed tier stays a pure function of the vault.
  - Tested: a conflict is active exactly when both claims are TRUE, on random claim pairs.
- Disputed dates inside one claim show as `Period.disputed`, not as a conflict.
- `disputed` on a claim means an unacknowledged row between two accepted claims, and recall shows `disputed_with` for the rows active on the asked day (`Claim.disputed_on`). A candidate that would conflict is shown in its inbox entry instead.

Resolution is always an explicit act in the vault, and detection never edits a claim:

| Act | Effect |
|---|---|
| A temporal fix: `until:`, or a `supersedes` link | The TRUE days stop overlapping; the row disappears |
| A lifecycle fix: `reject` or `retract` one claim | It leaves the set |
| An acknowledgement: `ack \| other=<key>` | Both are true; the row stays, marked `acknowledged`, and follows merges (F.5) |

Through all of these, each claim keeps its origins, verification, evidence and periods.

**The decision lifecycle** (records, unchanged):

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
  - periods hang off them: `(:Claim)-[:VALID_DURING]->(:Period {true_from, true_to, link_end, timeless, disputed})`
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
| "On 12-05, what did we hold true for 11-21?" | both axes: `known_at` 12-05, `as_of` 11-21 (J.1) |

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
│   ├── ledger.py                 NEW  occurrences, presence intervals, moves, gaps; known_at reconstruction (J.1)
│   ├── journal.py                NEW  derivation journal; daily journal backup and merge-restore (L.5)
│   ├── extract.py                NEW  optional LLM batch → inbox candidate lines (uses models.Runner)
│   └── projections.py            NEW  bench exporter (neo4j); not imported by the server
├── nets.py                       NEW  KeywordNet, VectorNet, DateNet (moved out of recall.py), GraphNet + walk() (H.3)
├── recall.py                     EXTEND  nets built through the Net protocol; as_of; history mode; claims block
├── remember.py                   EXTEND  relations also to the vault; ontology check; valid/until/event
├── stores/vault.py               EXTEND  relations.md; entities/; claim_reviews.md; frontmatter lists; code fences;
│                                         record_meta fields valid/until/event
├── stores/index.py               EXTEND  per-file sync also writes the raw claim rows and calls reconcile (G.2)
├── stores/graph.py               EXTEND  reads claims; keeps import_dump; relations table → read-only legacy
├── stores/notes.py               EXTEND  store-relative source ids and root names (G11, M1b)
├── status.py                     EXTEND  claims by lifecycle and verification, open conflicts, waiting candidates,
│                                         hubs, alias collisions
├── cron.py                       EXTEND  open conflicts and waiting candidates in the daily brief
├── cli/main.py                   EXTEND  brain entities, brain extract, brain graph migrate|export,
│                                         brain index --check/--rebuild
├── storage/journal_migrations/          NEW  data/journal.db's own migrations: 001_ledger.sql (M1c), 002_derivation.sql (M3)
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

### L.1 SQLite schema: `journal.db` (M1c, M3) and `brain.db` (`008_entities.sql` M2, `009_claims.sql` M3) [P][T]

The checker executes this SQL and compares it with F.3:

- every model field has its column
- every enum equals its `CHECK` list
- rows round-trip
- a repeated occurrence, a move without `moved_from`, and an interval that ends before it starts are all refused

The two tiers are marked in the comments, and L.5 says what each survives.

```sql
-- ═══ data/journal.db: the JOURNAL tier, history no Markdown file holds (L.5, ADR-015).
-- ═══ A file of its own: deleting or rebuilding brain.db never touches it. Backed up daily.

-- journal/001_ledger.sql (M1c) --------------------------------------------------------------
CREATE TABLE IF NOT EXISTS record_ledger (        -- LedgerRow: presence of one text version
    occ_id       TEXT NOT NULL,                     -- Occurrence.id(): where
    content_hash TEXT NOT NULL,                     -- sha256 of the exact text: which version
    seen_from    TEXT NOT NULL,                     -- UTC timestamp
    seen_to      TEXT,                              -- UTC; NULL = present now
    via          TEXT NOT NULL CHECK (via IN ('write', 'ingest', 'move')),
    moved_from   TEXT,                              -- occ_id, for an unambiguous move only
    PRIMARY KEY (occ_id, content_hash, seen_from),
    CHECK (seen_to IS NULL OR seen_to > seen_from),
    CHECK ((via = 'move') = (moved_from IS NOT NULL))
) WITHOUT ROWID;
CREATE UNIQUE INDEX IF NOT EXISTS idx_ledger_open ON record_ledger(occ_id) WHERE seen_to IS NULL;  -- at most one open version per occurrence

CREATE TABLE IF NOT EXISTS ledger_gaps (          -- windows with no observation at all
    gap_from TEXT NOT NULL PRIMARY KEY,             -- '0001-01-01T00:00:00Z': before the epoch
    gap_to   TEXT NOT NULL,
    cause    TEXT NOT NULL CHECK (cause IN ('epoch', 'restore')),
    CHECK (gap_to > gap_from)
) WITHOUT ROWID;

-- journal/002_derivation.sql (M3) ----------------------------------------------------------
CREATE TABLE IF NOT EXISTS derivation_journal (   -- every version of every raw derived row
    kind         TEXT NOT NULL CHECK (kind IN ('evidence', 'review', 'link', 'time')),
    row_key      TEXT NOT NULL,                     -- the row's primary key, as JSON
    row_json     TEXT NOT NULL,                     -- the whole row, masked like the index
    journal_from TEXT NOT NULL,                     -- UTC: the sync that produced this version
    journal_to   TEXT,                              -- UTC: the sync that changed or removed it
    PRIMARY KEY (kind, row_key, journal_from),
    CHECK (journal_to IS NULL OR journal_to > journal_from)
) WITHOUT ROWID;

-- ═══ data/brain.db: the DERIVED tier, a pure function of the vault, ontology.yaml and the
-- ═══ journal's recording times. `brain index --rebuild`, or deleting the file, refills it.

-- 008_entities.sql (M2) ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS entities (
    id          TEXT PRIMARY KEY,                   -- UUIDv7 from the note's frontmatter
    type        TEXT NOT NULL CHECK (type IN ('person', 'organization', 'project', 'component', 'technology', 'concept', 'mission')),
    name        TEXT NOT NULL,
    source_id   TEXT NOT NULL UNIQUE,               -- vault:entities/<file>.md
    merged_into TEXT REFERENCES entities(id) DEFERRABLE INITIALLY DEFERRED,
    ontology    INTEGER NOT NULL DEFAULT 1,
    degree      INTEGER NOT NULL DEFAULT 0          -- non-rejected claims naming it (hub test)
);
CREATE TABLE IF NOT EXISTS aliases (
    alias     TEXT NOT NULL,                        -- normalised (NFKC, casefold)
    entity_id TEXT NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
    PRIMARY KEY (alias, entity_id)
);
CREATE TABLE IF NOT EXISTS mentions (             -- Mention, the occurrence flattened
    occ_id    TEXT NOT NULL,                        -- the occurrence that mentions it
    source_id TEXT NOT NULL,
    record_id TEXT NOT NULL,
    ordinal   INTEGER NOT NULL CHECK (ordinal >= 1),
    entity_id TEXT NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
    how       TEXT NOT NULL CHECK (how IN ('wikilink', 'alias', 'tag', 'extracted')),
    PRIMARY KEY (occ_id, entity_id, how)
) WITHOUT ROWID;
CREATE INDEX IF NOT EXISTS idx_mentions_entity ON mentions(entity_id);
CREATE INDEX IF NOT EXISTS idx_mentions_source ON mentions(source_id);

-- 009_claims.sql (M3), derived part ---------------------------------------------------------
CREATE TABLE IF NOT EXISTS claims (                -- Claim, minus what has its own table
    id             TEXT PRIMARY KEY,                -- ClaimKey.id()
    subject        TEXT NOT NULL,
    predicate      TEXT NOT NULL,
    role           TEXT NOT NULL DEFAULT '',
    object_entity  TEXT,
    object_literal TEXT,
    datatype       TEXT CHECK (datatype IN ('text', 'int', 'version', 'port', 'url', 'date')),
    lifecycle      TEXT NOT NULL CHECK (lifecycle IN ('candidate', 'accepted', 'rejected')),
    verification   TEXT NOT NULL CHECK (verification IN ('stated', 'approved', 'derived', 'unverified')),
    confidence     TEXT CHECK (confidence IN ('high', 'medium', 'low')),
    retracted_at   TEXT,
    rank           INTEGER NOT NULL,                -- traversal order (H.3): open first, then priority
    CHECK ((object_entity IS NULL) <> (object_literal IS NULL)),
    CHECK ((object_literal IS NULL) = (datatype IS NULL)),
    CHECK (retracted_at IS NULL OR lifecycle = 'rejected'),
    CHECK (lifecycle <> 'accepted' OR verification <> 'unverified')
);
-- not partial: SQLite does not prove lifecycle = 'accepted' implies lifecycle <> 'rejected' (H.3)
CREATE INDEX IF NOT EXISTS idx_claims_out ON claims(subject, lifecycle, rank, id);
CREATE INDEX IF NOT EXISTS idx_claims_in  ON claims(object_entity, lifecycle, rank, id);
CREATE INDEX IF NOT EXISTS idx_claims_key ON claims(subject, predicate, role);

CREATE TABLE IF NOT EXISTS identity_redirects (   -- Redirect: retired ids of every kind (F.5)
    kind   TEXT NOT NULL CHECK (kind IN ('entity', 'claim', 'record')),
    old_id TEXT NOT NULL,
    new_id TEXT NOT NULL,                           -- no FK: it names an entity, claim or record
    cause  TEXT NOT NULL CHECK (cause IN ('merge', 'rename', 'merge+rename', 'id-scheme')),
    PRIMARY KEY (kind, old_id),
    CHECK (old_id <> new_id)
) WITHOUT ROWID;
CREATE INDEX IF NOT EXISTS idx_redirects_new ON identity_redirects(kind, new_id);

CREATE TABLE IF NOT EXISTS claim_evidence (       -- Evidence, flattened; raw, one source each
    claim_id     TEXT NOT NULL,                     -- no FK: claims are computed FROM these rows
    occ_id       TEXT NOT NULL,                     -- Occurrence.id()
    source_id    TEXT NOT NULL,                     -- Occurrence.source_id (store-relative)
    record_id    TEXT NOT NULL,                     -- Occurrence.record_id
    ordinal      INTEGER NOT NULL CHECK (ordinal >= 1),
    rule         TEXT NOT NULL,
    line         INTEGER NOT NULL DEFAULT 0,        -- locator only
    content_hash TEXT NOT NULL,
    subject_name TEXT NOT NULL,
    object_name  TEXT,
    stated_date  TEXT,                              -- NULL = undated line
    event_date   TEXT,
    valid_from   TEXT,                              -- resolved: occurrence meta, else record meta,
    valid_to     TEXT,                              --   else the rule's default (G.2)
    timeless     INTEGER NOT NULL DEFAULT 0,
    recorded_at  TEXT NOT NULL,                     -- ledger time (J.1), never from the text
    recorded_by  TEXT NOT NULL CHECK (recorded_by IN ('write', 'ingest', 'move')),
    origin       TEXT NOT NULL CHECK (origin IN ('user', 'agent', 'markup', 'extracted', 'inferred', 'reflection', 'external')),
    verification TEXT NOT NULL CHECK (verification IN ('stated', 'approved', 'derived', 'unverified')),
    confidence   TEXT CHECK (confidence IN ('high', 'medium', 'low')),
    quote        TEXT NOT NULL CHECK (length(quote) BETWEEN 1 AND 300),
    PRIMARY KEY (claim_id, occ_id, rule),           -- one row per occurrence: copies keep their own
    CHECK (timeless = 0 OR (valid_from IS NULL AND valid_to IS NULL)),
    CHECK (valid_from IS NULL OR valid_to IS NULL OR valid_to > valid_from)
) WITHOUT ROWID;
CREATE INDEX IF NOT EXISTS idx_evidence_source ON claim_evidence(source_id);
CREATE INDEX IF NOT EXISTS idx_evidence_record ON claim_evidence(record_id);
CREATE INDEX IF NOT EXISTS idx_evidence_occ    ON claim_evidence(occ_id);

CREATE TABLE IF NOT EXISTS record_times (         -- raw, from record_meta.md valid/until/event
    rid        TEXT NOT NULL,                       -- 16-character record id prefix
    occ_scope  TEXT NOT NULL DEFAULT '',            -- '' = every occurrence of rid; else one occ_id
    valid_from TEXT,
    valid_to   TEXT,
    event_date TEXT,
    timeless   INTEGER NOT NULL DEFAULT 0,
    line_occ   TEXT NOT NULL,                       -- the meta line's own occurrence (ledger)
    PRIMARY KEY (rid, occ_scope),
    CHECK (timeless = 0 OR (valid_from IS NULL AND valid_to IS NULL))
) WITHOUT ROWID;

CREATE TABLE IF NOT EXISTS record_links (         -- raw, from record_meta.md supersedes / was
    new_rid  TEXT NOT NULL,
    old_rid  TEXT NOT NULL,
    kind     TEXT NOT NULL CHECK (kind IN ('supersedes', 'was')),  -- was: G11 id migration
    line_occ TEXT NOT NULL,
    PRIMARY KEY (new_rid, old_rid, kind)
) WITHOUT ROWID;
CREATE INDEX IF NOT EXISTS idx_links_old ON record_links(old_rid);

CREATE TABLE IF NOT EXISTS claim_periods (        -- Period, computed
    claim_id  TEXT NOT NULL REFERENCES claims(id) ON DELETE CASCADE,
    seq       INTEGER NOT NULL,
    true_from TEXT,                                 -- Period.true_from; NULL: undated rows only
    true_to   TEXT,                                 -- Period.true_to (exclusive)
    link_end  TEXT,                                 -- Period.link_end
    timeless  INTEGER NOT NULL DEFAULT 0,           -- Period.timeless: a `valid: always` row
    undated   INTEGER NOT NULL DEFAULT 0,           -- Period.undated: a row with no date at all
    stated    INTEGER NOT NULL DEFAULT 0,           -- Period.stated: a row with a stated start
    disputed  INTEGER NOT NULL DEFAULT 0,           -- Period.disputed: a dated UNKNOWN window
    PRIMARY KEY (claim_id, seq)
) WITHOUT ROWID;

CREATE TABLE IF NOT EXISTS claim_conflicts (      -- Conflict, computed; one row per overlap window
    claim_a      TEXT NOT NULL REFERENCES claims(id) ON DELETE CASCADE,
    claim_b      TEXT NOT NULL REFERENCES claims(id) ON DELETE CASCADE,
    seq          INTEGER NOT NULL,
    kind         TEXT NOT NULL CHECK (kind IN ('functional_overlap')),
    scope        TEXT NOT NULL CHECK (scope IN ('interval', 'current')),  -- current: today only
    overlap_from TEXT,
    overlap_to   TEXT,
    acknowledged INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (claim_a, claim_b, seq),
    CHECK (claim_a < claim_b)
) WITHOUT ROWID;
CREATE INDEX IF NOT EXISTS idx_conflicts_b ON claim_conflicts(claim_b);

CREATE TABLE IF NOT EXISTS claim_reviews (        -- Review: raw, from claim_reviews.md
    occ_id         TEXT PRIMARY KEY,                -- the review line's occurrence (ledger time)
    action         TEXT NOT NULL CHECK (action IN ('reject', 'retract', 'restore', 'ack')),
    key_json       TEXT NOT NULL,                   -- Review.key, as written
    other_json     TEXT,                            -- Review.other (ack)
    claim_id       TEXT NOT NULL,                   -- canonical(key).id(); no FK: a rejection must
                                                    --   outlive the evidence of the claim it rejects
    other_claim_id TEXT,
    recorded_at    TEXT NOT NULL,                   -- the line's ledger time: orders the reviews
    reason         TEXT,
    CHECK ((action = 'ack') = (other_json IS NOT NULL))
) WITHOUT ROWID;
CREATE INDEX IF NOT EXISTS idx_reviews_claim ON claim_reviews(claim_id);
```

Changes from 2.1:

- `claim_evidence` is keyed by occurrence and carries every field of `Evidence`, including the resolved `valid_from`, `valid_to` and `timeless`.
- `record_times` has an occurrence scope (`occ_scope`).
- `record_links` carries the G11 `was` links.
- `record_ledger` is keyed by (occurrence, version, `seen_from`); `ledger_gaps` and `derivation_journal` are new.
- The journal tables live in their own file, `data/journal.db`, with their own migrations (`storage/journal_migrations/`), so deleting `brain.db` cannot touch them (L.5).
- `claim_aliases` became `identity_redirects`, for every kind of retired id.
- `entities.type` is checked against the ontology types, and `mentions` stores the full occurrence.
- Foreign keys are added where safe (F.3).
- Revision 2.3: `claim_periods` gains `undated` and `stated`, so the predicate is exact. `claim_conflicts` gains `scope` and `seq`, for several windows per pair (issues A and B).
- The partial index on open ledger rows is safe: its query uses the same `seen_to IS NULL` term, which SQLite does match (unlike the lifecycle case in H.3).
- There is still no `claims.source_path`.

### L.2 Neo4j, bench projection only [P]

- Labels:
  - `:Entity:<Type>` with `{id, name, aliases}`
  - `:Record:<Kind>` with `{id, path, line, stated_date, recorded_at, text}`
  - `:Claim` with `{id, predicate, role, lifecycle, verification, origins}`
  - `:Period` with `{true_from, true_to, link_end, timeless, disputed}`
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

### L.5 Durability, backup, restore and synchronisation [P][T]

**Where transaction history lives: four options, one chosen.**

| Option | For | Against | Verdict |
|---|---|---|---|
| A. An append-only Markdown journal in the vault | travels with the vault; human-readable | every sync writes into a folder iCloud and Obsidian sync (the reason the lock file already lives outside the vault); thousands of lines of hashes in the owner's notes; sync conflicts | rejected |
| B. **A separate SQLite file, `data/journal.db`** | deleting, rebuilding or corrupting `brain.db` cannot touch it; the README's advice "the SQLite index is a cache: delete it and it is rebuilt from the files" (`README.md:507`) stays true; small, so it is cheap to back up | two files instead of one; SQLite in WAL mode makes a transaction over attached databases atomic per file, not across them, so the write order must make a crash safe (below) | **chosen** |
| C. The same `brain.db`, with a mandatory backup (revision 2.2 draft) | one file | turns the README's documented "delete it" into silent history loss; `brain.db` corruption takes the history with it | rejected |
| D. Git history of the vault | free when present | the live vault is not a git repository (M0); commit times record when the owner committed, not when brain-core learned something | optional later, never required |

**The tiers, and what each survives.**

| Tier | Lives in | Holds | Rebuilt from | Lost when |
|---|---|---|---|---|
| Canonical | `vault/*.md` | all knowledge | — | the owner loses the vault: their own sync and backups |
| Derived | `data/brain.db` | `records_fts`, `index_files`, `mentions`, `claim_evidence`, `record_times`, `record_links`, `claim_reviews`, `claims`, `identity_redirects`, `claim_periods`, `claim_conflicts`, `entities`, `aliases` | the vault, `ontology.yaml` and `journal.db`'s recording times | never for good: delete the file and the next sync refills it |
| Derived, needs the model | `data/brain.db` | `record_vectors` | the vault + the embedding model (already on disk) | never for good; about 10 minutes to re-embed (M0) |
| Derived from expiring files | `data/brain.db` | `transcripts`, `transcript_files` | `~/.claude/projects/*.jsonl` | rows whose transcript Claude Code has since deleted (R item 14) |
| Operational logs (as today) | `data/brain.db` | `events`, `metrics` | nothing | `brain.db` is deleted. Best-effort, unchanged from 0.9.1, and said so |
| **History (journal)** | **`data/journal.db`** | `record_ledger`, `ledger_gaps`, `derivation_journal` | **nothing** | `journal.db` is deleted or corrupted and no backup exists |
| Legacy, not derivable | `data/brain.db` | `facts` rows marked `sole` (0 on the live agent, 2026-11-21); `relations` until M1a | nothing | M1a moves relations into the vault, and keeps writing the table until M3 so that a rollback to 0.9.1 sees every relation; `brain doctor` lists `sole` rows to save again |

**The write order: crash safety without a cross-file transaction [T: reconcile22].** For each sync:

1. **`journal.db` first**, in one transaction: ledger intervals and derivation-journal versions. Every write is idempotent (insert-or-ignore; a close matches only an open row).
2. **`brain.db` second**, in one transaction: raw rows, the recomputed tier, then the source signatures, **last**.

A crash after step 1 leaves the signatures old, so the next sync derives again: its journal writes match what is already there, and its `brain.db` writes complete. A crash during step 1 rolls back that file alone. Tested by injecting a crash between the two commits, in named scenarios and inside the random sequences.

**Durability and one writer [P; second-model review, 2026-11-22].** Process crashes are covered above. Power loss and concurrent writers need four more rules:
- **Durable commits.** `journal.db` uses WAL with `synchronous=FULL`. With `NORMAL`, which `brain.db` keeps because it is derived, SQLite may roll back the last commit after a power loss or an OS crash.
- **Consistency marker.** `journal.db` holds a random `generation` id, created with the file, and each sync takes an increasing `sync_seq`. Both are written in step 1 and, with the signatures, in step 2. At startup:
  - **the journal ahead:** a crash after step 1. Normal: the old signatures make the sync derive again, and step 1 is idempotent.
  - **`brain.db` ahead, or a different `generation`:** a lost commit, an older backup, or a journal from another lineage. Record a `restore` gap, ignore the signatures and re-read every source.
  - **equal:** proceed.
  - **the journal missing or corrupt:** a new generation and epoch. Earlier recording times answer *unknown*; none is invented.
- **One writer.** A sync holds a per-agent OS file lock, kept outside the vault like the vault lock, from before it reads the signatures until step 2 commits. `BEGIN IMMEDIATE` is used inside each transaction, but a SQLite lock ends at its commit, so it cannot span both files. The MCP server, the CLI and cron then serialize.
- **One open version per occurrence**, enforced by the unique index in L.1. The reconciliation prototype passes with it: 150 random sequences, the crash scenarios, and L1–L11.

**Behaviour of each operation.**

| Operation | Behaviour | Tested |
|---|---|---|
| `brain index` | syncs changed sources: journal first, then `brain.db` | T (reconcile22) |
| `brain index --rebuild` | empties the derived tier of `brain.db` and syncs; `journal.db` is not opened for writing except idempotently, and gains no row | T (150 random sequences) |
| `brain.db` deleted | the next sync recreates it from the vault; recording times come back from `journal.db` | T |
| `brain.db` corrupted | `brain doctor` runs `PRAGMA integrity_check`; on failure it moves the file aside and rebuilds. No knowledge and no history is lost | T (a garbage file, detected, rebuilt) |
| `journal.db` deleted, no backup | a new epoch starts at the next sync: every present version is recorded then (late, never early), and every `known_at` before it answers *unknown* | T (ledger22 L10) |
| `journal.db` corrupted | `brain doctor` detects it, moves it aside and restores the newest backup (below). Without one: as deleted | P |
| A vault restored from an older backup | lines that vanish close their intervals; lines that return open new ones and keep their first recording time; text never seen before is recorded now | T (L8, delete then restore) |
| A journal backup restored | see Restore below | T (L11) |
| The agent folder moved to another computer | copy the folder, `data/` included: both files travel, no id holds an absolute path (G11), notes roots keep their ids by name. The embedding model must be present on the new machine (a download needs the owner's approval), and journal backups live outside the folder (`~/Backups/…`) | T (folder copied, same claims and times); P (the new machine's notes paths, configured by the owner) |

**Backup [P].**
- `brain daily` copies `journal.db` through SQLite's backup API to `<cron.backup.journal_dir>/<agent>/journal-YYYY-MM-DD.db`, keeping 14 copies.
- It is small: 1 row per version per occurrence, plus 1 per changed derived row.
- The default directory is an owner decision (R item 3). M1c's ledger holds ids, hashes and timestamps. From M3, the derivation journal adds masked derived rows: names, paths and quotes of at most 300 characters. **Treat backups as private as the vault.**
- The backup is written through the backup API into a temp file, checked with `PRAGMA integrity_check`, then renamed into place. The folder is `0700` and the files `0600`.
- `brain journal restore` refuses a corrupt or truncated backup.
- For a copy of a database another process may be writing, use `mode=ro` as M0 did. Even so, a reader of a WAL database updates its `-shm` file. M0 found the frozen eval database's `-shm` touched while its data file was unchanged. For a frozen file nobody writes, `immutable=1` avoids even that.

**Restore [T: L11].** `brain journal restore FILE`:
- merges the backup's rows (a union)
- closes the backup's open intervals at the time the backup was taken, since presence after it was never observed
- records a `restore` gap from that time to the first sync after the loss
- takes the epoch from the backup

**The durability promise, stated once:**
- Deleting `brain.db` keeps all knowledge (the vault is canonical) and all transaction history (`journal.db`). It loses the best-effort `events` and `metrics` logs, as in 0.9.1.
- Deleting `journal.db` without a backup loses transaction history only, and every question about the lost period answers *unknown*.

**Synchronisation.**
- **Vault → SQLite:** per-source reconciliation in the order above (G.2); `brain index --check` verifies incremental equals rebuild and that a rebuild adds no journal row.
- **SQLite → Hindsight:** write-through with per-layer status plus the queue (exists).
- **→ projections:** a full rebuild on demand.

There is no two-way sync. Only the vault is ever edited by a person.

## M. API design

### M.1 MCP surface: still five tools (ADR-009) [P]

| Tool | Change |
|---|---|
| `brain_remember` | `kind='relation'` also writes `vault/relations.md` and takes an optional `role`. New optional `valid` (an ISO date, or `always`), `until` and `event` (ISO dates) for any kind, kept in `record_meta.md`; a month-only date is refused with a message. New `kind='entity'` (`name`, `entity_type`, `aliases`) creates or extends an entity note; an alias already held by another entity returns `conflict` with both, and writes nothing. The ontology check returns `mapped_to: RELATED_TO` when a predicate is unknown |
| `brain_recall` | New optional `as_of` (ISO date). Results may carry `path` (graph hits), `validity` (`true`, or `unknown` in history mode) and `disputed_with`. When the graph net runs, a structured `claims` block lists each walked claim: key, validity at `as_of`, verification, origins, sources, and `truncated` when a cap was hit. `found_by` gains `graph`. `scope` gains `entity:<name>` (records about one entity) |
| `brain_status` | Adds `entities`; claims by lifecycle and by verification; `open_conflicts`; `candidates_waiting` and the oldest age; `hubs` (degree above `hub_degree`); `alias_collisions`; `relations_not_in_vault` (migration progress); `journal` (epoch, gaps, last backup) |
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
| `brain index --migrate-ids [--apply]` | M1b: map notes and archive ids to store-relative ones; dry run by default |
| `brain journal restore FILE` | M1c: merge a journal backup (L.5) |
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
- **Cost.** p50/p95 latency of keyword, vector, graph-traversal and full recall; tokens per recall; no-change sync time; full rebuild and index build time; peak memory of the recall process and of the embed worker (on Apple Silicon `ps` does not count GPU memory, so measure the worker with `footprint`); truncation frequency and its reasons; disk; services to run.

### O.5 Process and success criteria [P]

1. **Before anything else (M0):** a person checks ≥ 100 labels, stratified by slice, and the new slices' gold. Report how often labels change; the size of that number decides how far any earlier result can be trusted. M0 prepared the packet (104 questions). Until a person has checked it, the M0 scores, and every comparison built on them, are **provisional**. **Update, 2026-11-22:** the owner waived the person check for M0. AI reviewers answered the packet, and the owner accepted their answers unchecked (`docs/M0_BASELINE.md`, section 9). M4's gate still needs labels a person has checked (ADR-010).
2. Keep the existing split discipline: tune on dev, open held-out once per stage, compare pairwise with `compare.py`.
3. **Ship gate for any retrieval change:**
   - held-out found@10 must not fall, and new slices must gain with McNemar p < 0.05, or with fixed ≥ 3 × broken where n is too small
   - **zero** broken in the update and identifier slices, and zero false assertions under `as_of`
   - **latency does not regress:** p95 at most 10% above the M0 baseline on the same corpus and machine (keywords: snapshot 74 ms, live copy 110 ms; vectors: snapshot 204 ms), and the graph net adds at most 25 ms at p95. A keyword p95 under 100 ms stays an **optimisation target**, not a gate: the live copy is already at 110 ms
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

### M0: Measurement and validation — complete 2026-11-22 (labels AI-reviewed, accepted by the owner unchecked)

| | |
|---|---|
| **Preconditions** | none |
| **Authorised scope** | measurement on isolated copies only; no live mutation, no migration, no outside LLM call (S3 needs approval) |
| **Done so far [V]** | <ul><li>baseline S0 and S2 (295 and 346 of 446, both the README's figures)</li><li>census</li><li>performance</li><li>the 104-question packet</li><li>an **AI-assisted pre-review of the packet**, kept apart in `local/audit-m0/ai_review/`; it is not human validation</li><li>the frozen dataset and results checksummed (`local/audit-m0/MANIFEST.json`)</li></ul> |
| **Found in validation** | <ul><li>182 of the 446 questions (41%) have gold or stale ids that depend on the folder path (G11)</li><li>the frozen snapshot's 588 search-key lines for notes and archive records never attached, because they are keyed by live-path ids. The M0 scores, and the README's, measure keyword recall without those keys</li><li>the catalog the labels were drafted from holds 5,394 unique records against the 5,821 that 0.9.1 indexes, so labels can miss records the 0.9.0 reader added</li></ul> |
| **Required to finish** | the five completion criteria below. Separately, before M4 (not part of M0's completion): about 40 multi-hop and 40 temporal questions, person-checked |
| **Performance gates** | none (M0 measures them) |
| **Rollback** | nothing to roll back: copies only |
| **Completion criteria: M0 is not reported complete until all five hold** (all five hold as of 2026-11-22; the owner waived criterion 1, see `docs/M0_BASELINE.md`, sections 8 and 9) | <ol><li>A person has reviewed all 104 items in `local/audit-m0/human_review/M0_HUMAN_REVIEW_PACKET.md`. The AI-assisted pre-review is shown as a hint only and never counts.</li><li>The owner has approved every correction to the gold labels.</li><li>The baseline is recalculated on the corrected labels, written to **new** files (`questions-v2.yaml`, `results/*-v2.json`), with paired fixed and broken counts against the historical runs.</li><li>The results are preserved and reproducible: checksums added to `MANIFEST.json`, the exact commands recorded, nothing earlier overwritten.</li><li>Concerns A, B and C are resolved (done in 2.3) or explicitly accepted as known risks.</li></ol> |
| **Historical results, kept as they are** | 295/446 (keywords + keys) and 346/446 (+ vectors) of 2026-11-21, on model-written labels, are preserved as the historical, provisional baseline. They are never edited or overwritten |
| **Definition of done** | the five criteria hold, and the owner approves the R decisions M1 needs |

### M1: Canonical relations and durable history — not authorised

Three work packages, each approved separately. Order: M1a and M1b before M1c, so the first ledger row already uses stable source ids.

| | M1a: relations canonical (G1), hygiene | M1b: stable source ids (G11) | M1c: the journal (`journal.db`) |
|---|---|---|---|
| **Preconditions** | M0 done; approval | M0 done; approval, including the `was:` vault write (588 lines) | M1a, M1b; approval; R item 3 (backup directory) |
| **Scope** | `relations.md` write and parse; the legacy table stays written (and upserted from the file) until M3; a one-time migration behind a verified backup, refusing unsafe characters, written atomically; the full `created_at` is kept as `recorded:` provenance, never as valid time (R item 21); `relations.md` is append-only until M3, and hand removals are reported; the mirror is written after the vault line and never read by M1 code; docstring; `brain doctor` counts what a rebuild would not restore; the README's rebuild promise is corrected | ids hash `<store>:<root name>/<path>#heading`; optional `name:` per root; the displayed path is unchanged; `brain index --migrate-ids` (dry run by default) writes `was:` lines, remaps vectors and translates eval labels; `--apply` resumes from a mapping manifest after a crash | `journal.db` (`record_ledger`, `ledger_gaps`); ledger in sync; `via=write` in `brain_remember`; daily journal backup; `brain journal restore`; `brain doctor` integrity checks of both files |
| **Files** | `stores/vault.py`, `remember.py`, `stores/graph.py`, `cli/main.py`, `mcp/server.py`, template, `VAULT_SCHEMA.md` | `stores/notes.py`, `config.py`, `stores/vault.py` (`was:`), `stores/vectors.py`, `cli/main.py`, `tests/eval/` (label translator) | `storage/journal_migrations/001_ledger.sql`, `knowledge/ledger.py`, `knowledge/journal.py`, `stores/index.py`, `remember.py`, `cron.py`, `cli/main.py`, `status.py` |
| **Tests** | destructive tests on a copy only; a field-level round trip of every relation, full timestamps included; a hand-deleted line reported; a failed vault write leaves no mirror row; an existing `relations.md` keeps every line; relation recall per entity unchanged; a crash between the file and the sync; a rollback to 0.9.1 after new writes; existing write scenarios | G11-T1 to T5; the M0 eval on migrated ids, as validated (G11 results in the validation report); a 0.9.1 reader ignores `was:` | L1–L11; reconcile22's crash and rebuild properties against the real code; every state of the `generation`/`sync_seq` marker, both directions included; a crash at every commit boundary; two concurrent indexers on the outer lock; a source file edited during a sync is re-read or deferred, never recorded half-old; a second open version refused; a backdated line gets its ingest time; deleting `brain.db` keeps history; a corrupt backup refused |
| **Performance gates** | sync and recall p95 within +10% of M0 | same, on the migrated copy | a no-change sync stays within +10% of 5 ms; journal growth measured |
| **Rollback** | the table stays written until M3, so reverting the code reads every relation, new ones included | delete the `was:` lines and rebuild `brain.db` (restoring the backup is the last resort): old ids return. A 0.9.1 reader on migrated data loses notes and archive keys, as today | revert the code and **keep** `journal.db`: 0.9.1 ignores it, and history continues with a gap if M1c returns |
| **Done when** | tests pass; `brain doctor` clean on a copy | tests pass; the eval on migrated ids matches the validated result | tests pass; a backup restored on a copy recovers history and reports its gap |

### M2: Entity registry — not authorised

| | |
|---|---|
| **Preconditions** | M1 done; R items 11 and 13 decided |
| **Scope** | stable entity ids (UUIDv7 in notes), aliases, wikilinks, `#tags`, mentions by occurrence, safe merges (`merged_into`, never automatic), ontology validation, alias-collision reports |
| **Files** | `knowledge/model.py` (`Entity`, `Mention`, `Redirect`), `ontology.py`, `entities.py`, `links.py`, `ontology.yaml`, `stores/vault.py`, `stores/index.py`, `migrations/008_entities.sql` |
| **Tests** | <ul><li>a renamed entity note keeps its id</li><li>the mentions of a fixture vault match a hand list</li><li>copies get separate mention rows</li><li>a merge chain resolves at commit and a dangling merge is refused (FK, validated)</li><li>an alias shared by two entities seeds both and is reported</li></ul> |
| **Performance gates** | full parse within +20% of M0 (2.5 s); recall p95 within +10% |
| **Rollback** | the entity tables are derived: drop them; the notes stay in the vault |
| **Done when** | tests pass; the census's 75 names are proposed as entities through the inbox, none merged without a person |

### M3: Claims, evidence and temporal semantics — not authorised

| | |
|---|---|
| **Preconditions** | M2; M1c (recording times); R items 5–10, 12 and 22 decided; hook-captured messages form their own trust class and never feed derived claims |
| **Scope** | claim identity, occurrence-level evidence, provenance, periods (votes), lifecycle, review history, conflicts, `identity_redirects`, the derivation journal, deterministic reconstruction |
| **Files** | `knowledge/model.py`, `derive.py`, `reconcile.py`, `temporal.py`, `journal.py`, `migrations/009_claims.sql`, `storage/journal_migrations/002_derivation.sql`, `stores/vault.py`, `remember.py`, `stores/index.py`, `status.py`, `cron.py` |
| **Mandatory tests (M3 is not done without both)** | <ul><li>**T10:** the same text in the vault and twice in a notes file gives three evidence rows, with their own `recorded_at` and resolved dates; deleting any source leaves the others, in SQLite, through `reconcile`</li><li>**T11:** `known_at` never uses a stated date; a backdated line is invisible before its ledger time; a deleted evidence row is still seen before its deletion, through the journal</li></ul> |
| **Other tests** | <ul><li>T1–T9 (as before)</li><li>T12: the twelve temporal cases and E1–E13 exactly</li><li>T13: merge and rename traceability, and undo</li><li>T14: the F.3 models against the L.1 schema (the validated checker as a unit test)</li><li>T15: incremental equals rebuild with `hypothesis`, crashes included</li></ul> |
| **Performance gates** | sync and recall p95 within +10% of M0; journal growth reported |
| **Rollback** | drop the derived claim tables; keep `journal.db` (history of the derivation is harmless when unused) |
| **Done when** | T1–T15 pass with T10 and T11; `brain index --check` is clean on a copy of the real vault |

### M4: Graph retrieval — not authorised

| | |
|---|---|
| **Preconditions** | M3; the human-validated baseline (the M0 baseline is AI-reviewed, so a person-checked benchmark is required, including the 7 widened stale lists and the 3 wide gold lists); the new multi-hop and temporal questions (about 40 each); answer correctness and abstention reported apart from hit rate |
| **Scope** | the bounded walk (H.3) as a net; temporal filtering; evidence-backed results with truncation reasons; fusion by RRF; `as_of` in `brain_recall` |
| **Files** | `nets.py` (refactor first, a `run_gold` diff of zero), `recall.py`, `mcp/server.py` |
| **Tests** | <ul><li>the H.3 test (hub, cycle, bounds, determinism, query plans, VM steps)</li><li>the completeness property: every omission inside the depth reports a reason, as validated</li><li>disconnected graphs, missing entities, alias collisions, multiple seeds</li></ul> |
| **Performance gates** | <ul><li>baseline-relative: keyword p95 at most +10% (live 110 ms, snapshot 74 ms), vectors p95 at most +10% (204 ms), the graph net at most +25 ms p95 end to end</li><li>100 ms keyword p95 stays a target</li><li>measure truncation frequency, memory and indexing time</li></ul> |
| **Quality gate** | O.5, on human-checked labels, paired fixed and broken counts reported, zero broken in update and identifier |
| **Rollback** | the graph net is a config switch; off, recall is exactly 0.9.1's |
| **Done when** | the gates pass; `truncated` is in fewer than 5% of walks on the real vault (depth excluded), or the defaults are revised with evidence |

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

**ADR-003 (revised in 2.2): Reconciliation instead of an outbox; a journal for what reconciliation cannot rebuild.**
- *Reason:* the derived tables share one database, so one transaction per source is atomic, and the source signature, written last, is the retry marker. The only external store (Hindsight) already reports per layer and has a queue.
- *But:* recording times and past versions of derived rows cannot be reconstructed from the vault, so they live in a journal tier (ADR-015).
- *Trade-off:* a live external projection would need an outbox. None is proposed.

**ADR-004: Entities get UUIDv7 ids in Obsidian notes; records keep content-hash ids.**
- *Reason:* entity identity must survive renames and merges, while record ids are idempotency keys every layer depends on. Obsidian `aliases` give human-editable resolution, and wikilinks show in the graph view.
- *Alternative:* a central `entities.md` registry (fewer files, but invisible to Obsidian's link resolution).

**ADR-005 (revised): Claims are computed from the vault; extracted claims need approval; reviews are canonical.**
- *Reason:* LLM extraction is not reproducible, so what is kept must be written down. Candidates are lines in the inbox, approval is a line in `relations.md`, and rejections, retractions and acknowledgements are lines in `claim_reviews.md`. A rebuild therefore reproduces every lifecycle decision.
- *Trade-off:* a slower-growing graph; review effort; one more vault file.

**ADR-006 (revised in 2.2): Two time axes from two sources; validity by votes; unknown is never true.**
- *Reason:*
  - Valid time comes from the text: stated dates, `valid` / `until` / `event`, and `supersedes`.
  - Transaction time comes from clocks: the ledger and the derivation journal.
  - Every evidence row votes. A disagreement, or silence, is UNKNOWN, and so is any day before the first evidence when no start is stated.
  - `stated_date` stays nullable because 0.9.0 deliberately stopped inventing dates for undated lines.
- *Consequence:* `as_of` can answer `unknown` (23 checked examples, J.1), and the eval checks that it never turns that into an assertion.

**ADR-007: Graph expansion is a net in the existing rank fusion, not a separate engine.**
- *Reason:* RRF by rank already joins nets whose scores are not comparable, and the identifier pin and the current-over-old rule then apply to graph hits for free.
- *Alternative:* a GraphRAG engine with its own answer step. Rejected: it duplicates the judge and the agent.

**ADR-008: GraphRAG engines are bench projections only; KAG and Microsoft GraphRAG are not integrated.**
- *Reason:* each has its own construction pipeline and its own representation, so running one live means two truths. As projections they can be compared and thrown away. KAG is dormant and needs a Java/MySQL/Neo4j/MinIO stack. Microsoft GraphRAG is in maintenance mode, excludes Python 3.14, and its `update` skips edited and deleted documents **[E]**.

**ADR-009: The MCP surface stays five tools.**
- *Reason:* the project's own design constraint (SPEC §2, §7 "lean guard"): an agent picks better among few consolidated tools. New capability arrives as parameters and kinds.

**ADR-010: Every retrieval change passes the eval gate, on labels a person has checked.**
- *Reason:* the history in the README shows ties and regressions that a total hides (113 against 110 was 7 fixed and 4 broken). Model-written labels judged by the same model family are not enough to choose an engine.

**ADR-011 (revised in 2.2): A claim's identity is its assertion key; provenance is per occurrence.**
- *Decision:*
  - `claim id = h("claim/1", subject, predicate, role, object type, object)` on canonical entity ids and current predicate names.
  - An evidence row is `(claim, occurrence, rule)`, where the occurrence is `(source_id, record_id, ordinal)`.
- *Reason:*
  - A claim supported by several records must outlive any one of them.
  - Two copies of one text are two pieces of evidence, with their own recording times and dates (T10).
  - A start date learned later must not change the claim, and the role changes what a functional predicate means.
- *Alternatives rejected:*
  - `valid_from` in the id: identity churn, and no repeated periods.
  - The source in the id: one claim per document.
  - `(claim, record)` as the evidence key: copies collapse.
- *Cost:* merges and renames re-key claims. Handled by `identity_redirects`, and by reviews that keep their key as written (F.5).

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

**ADR-015 (finalized in 2.2): Transaction history lives in its own file, `data/journal.db`.**
- *Decision:*
  - `record_ledger`, `ledger_gaps` and `derivation_journal` live in `journal.db`, with their own migrations.
  - `brain.db` holds only what the vault can rebuild, plus the best-effort `events` and `metrics` logs, as today.
  - Each sync writes `journal.db` first, with idempotent writes, then `brain.db` with the signatures last.
- *Reason:*
  - The README tells users that the SQLite index can be deleted and rebuilt (`README.md:507`). History inside `brain.db` would make that advice destroy it.
  - Corruption of `brain.db` must not cost history.
- *Alternatives (L.5):* a Markdown journal in the vault (sync churn in iCloud and Obsidian); history inside `brain.db` with a backup (breaks the README's promise); git (the vault has none).
- *Cost:* no cross-file atomicity in WAL mode, made safe by the write order. Tested with crashes injected between the commits.

**ADR-016 (finalized in 2.2): Notes and archive records take a store-relative source id; the shown path stays.**
- *Decision:* the id hashes `<store>:<root name>/<path>#heading`, with the root name from an optional `name:` defaulting to the folder name. `Record.path`, which recall cites, stays the file's real path. Vault ids are unchanged.
- *Reason:* an absolute path made 2,805 live records depend on where a folder lives. In the frozen eval it already detached 588 search-key lines.
- *Consequences, measured on isolated copies:*
  - With the new ids alone, S0 and S2 reproduce M0 question for question.
  - With the live agent's keys also attached through `was:` lines, S0 goes 295 → 298 (12 fixed, 9 broken, p 0.66) and S2 346 → 347 (7 fixed, 6 broken), with two more false answers on absent questions.
  - So M1b is followed by a re-baseline (R item 19), not gated as an improvement.

**ADR-017 (new in 2.2): Recording times are per version at an occurrence, and inherited only by an unambiguous move.**
- *Reason:* a copy is new knowledge in a new place, and must not look older than it is (finding 2). An ambiguous case is treated as new: late, never early.
- *Consequence:* `recorded_at` can understate how long the vault knew something, and never overstates it.

**ADR-018 (new in 2.2): Disagreeing dates give an UNKNOWN window, not the earliest date.**
- *Reason:* when one row says a claim began on 11-10 and another, dated 11-05, says it already held, neither can be asserted for the days between. Choosing the earliest would assert what a source denies. Revisit if owners find the windows noisy (R item 7).

---

## R. Final recommendations

**Recommendation: READY FOR M1** (2026-11-22).
- **The design is ready.** Every P0 and P1 item is resolved and validated in prototypes (header; `docs/AUDIT_2_2_VALIDATION.md`).
- **M0 is complete.** The owner waived the human label review and accepted AI answers to the 104-question packet, without checking them. The corrected baseline is 298 and 345 of 443 (`docs/M0_BASELINE.md`, section 9). Its labels are AI-reviewed, not human-validated.

A second-model review (2026-11-22) found gaps in M1's safety rules, not in the design. They are now in each package's scope, tests and rollback (`docs/M1_DECISION_CHECKLIST.md`, section 5). M1a runs on an isolated copy first; the live cutover only after its tests pass there.

Ready is not authorised:
1. **Each M1 package needs its own approval.** The owner's decisions below were taken on 2026-11-22, as recommended, except item 16, which stays open (`docs/M1_DECISION_CHECKLIST.md`, section 0).

**For the owner:** the human review packet is at `local/audit-m0/human_review/M0_HUMAN_REVIEW_PACKET.md` (private, git-ignored). The decisions M1 needs, with M1a, M1b and M1c as separate approvals, are in `docs/M1_DECISION_CHECKLIST.md`.

**Done.**
- the audit, revisions 2, 2.1, 2.2 and 2.3
- M0's measurements, on isolated copies
- revision 2.2's validation, in throwaway prototypes

**Next, in order:**
1. M1a, M1b, M1c, each only with explicit approval (the owner's decisions are taken; M0 is complete)
2. M2, M3, M4

M5–M7 stay optional and evidence-driven.

**Leave unchanged:**
- the five-tool MCP surface
- the vault formats
- vault record ids (notes and archive ids change once, in M1b)
- the write order and per-layer status
- the secret gate
- RRF c=10, the identifier pin and the current-over-old rule (relative to `as_of` only when it is given)
- the judge as the optional reranker
- mental models
- the lite install
- Hindsight as an optional store
- the cron jobs
- Python 3.12–3.14 support (UUIDv7 needs a fallback on 3.12–3.13)

**Avoid:**
- Neo4j, Qdrant, PostgreSQL, Redis, Microsoft GraphRAG or OpenSPG KAG as product dependencies
- an LLM query router
- a file-watcher daemon
- auto-merging entities
- auto-accepting extracted claims or AI-suggested equivalences
- reading an unknown start or window as true
- a stated date used as a transaction time
- a recording time inherited by a copy
- transaction history inside `brain.db`
- a recursive CTE with a trailing `LIMIT`
- partial indexes on `lifecycle`
- a second canonical store
- restructuring the package into the brief's idealised tree

**Decisions that need the owner's approval [Q].** Settled for this install by M0 data:
- partial dates: none found, so refuse them
- hub defaults: the maximum degree is 19, so keep them as safety limits
- predicates: 43, ad hoc
- vault under git: no
- v0.1 rows: 0
- no-change sync: 5 ms, so no watcher

| # | Decision | Recommended default | Why | Needed before |
|---|---|---|---|---|
| 1 | Approve M1a, M1b and M1c, separately | approve in that order, after M0 | each is independent and reversible; M1b first so ledger ids are stable | M1 |
| 2 | Root names for notes and archive | default to the folder name; doctor warns on a rename | no config change for existing installs; a rename is detected, not silent | M1b |
| 3 | Journal backup location and transcripts in it | `~/Backups/brain-core/<agent>/`, 14 copies, transcripts excluded | beside the existing Hindsight backups; transcripts are large and Claude Code's to keep | M1c |
| 4 | Expose `known_at` in `brain_recall` | CLI and eval only, never before M3's journal | without the journal it would answer from today's rows | M4 |
| 5 | A decision's date as the `valid_from` of its claims | yes, overridable with `valid:` | a decision takes effect when made unless it says otherwise | M3 |
| 6 | `derived` claims accepted without review | yes, verification `derived` visible | deterministic rules over records the owner wrote; review cost otherwise unbounded | M3 |
| 7 | Contradictory dates | an UNKNOWN window | asserting the earliest date would assert what a source denies | M3 |
| 8 | Occurrence meta syntax `<rid16>@<source_id>#<ordinal>` | as proposed | old readers ignore it, validated against `_META` | M3 |
| 9 | Merged claims whose reviews disagree | the later decision (by ledger time) applies, reported | deterministic and visible; blocking would stall rebuilds | M3 |
| 10 | "Never true" statements | a retraction; "no longer" is an end | no new stance to model | M3 |
| 11 | Functional predicates and `USES` roles | `PART_OF`, literal-valued predicates, `USES` per role | the only ones whose overlap is a contradiction in this vault's data | M2 |
| 12 | Literal datatypes | text, int, version, port, url, date | covers the census's values | M3 |
| 13 | Knowledge pages renamed inside the vault | accept; offer `brain index --relink` with approval | the same rule as today; relinking writes to the vault | M2 |
| 14 | Transcript rows lost when Claude Code deletes old transcripts | accept | they are derived from files brain-core does not own | M1c |
| 15 | Who checks the 104 labels; whether S3 may send eval data to Anthropic | the owner checks; S3 stays off until approved | the gate is human validation; S3 sends private text out | M0 |
| 16 | Fill the live agent's vectors (`brain index`; 83% missing) | the owner's call; operational, outside the plan | hybrid recall on the live agent sees a sixth of memory today | any time |
| 17 | The margin that justifies a JVM service | set before M6 | a benchmark needs its bar fixed in advance | M6 |
| 18 | Exclude `line` (a locator) from journal versioning | yes | a line inserted above otherwise versions every row below it | M3 |
| 19 | Re-baseline after M1b | yes: re-run S0 and S2 once G11 is fixed | the frozen snapshot measured notes and archive recall without their search keys (see the validation report) | M1b |
| 20 | Per-copy meta after the copies changed (issue C) | report it and do not apply it until re-anchored | applying it would give dates to a copy that was never given them | M3 |
| 21 | The date a migrated relation gets | none: the full `created_at` is kept as `recorded:` provenance, and the relation is undated (revised 2026-11-22 after the second review round; confirmed by the owner) | recording a relation does not show when it became true; promoting the recording time to valid time would break the separation revision 2.1 made | M1a |
| 22 | Start M3 only with evidence of need | yes: a class of eval misses that typed claims would fix (open) | M0 found 82 relations and no decision-field links; M3 is the largest milestone | M3 |
