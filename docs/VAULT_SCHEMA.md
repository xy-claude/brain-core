# Vault schema (v0.2, updated for 0.5)

The markdown vault is the source of truth. `VaultStore` reads and writes it by **kind**. This page codifies the conventions the the reference agent vault already uses (surveyed 2026-11-02), so legacy files are read as-is and no migration is required. Where a file deviates, the lint reports it; the adapter never rewrites history.

Root: the folder `stores.vault` names in `brain.yaml` (one folder per agent). All files have YAML frontmatter with at least `type`, `owner`, `updated` (YYYY-MM-DD). Every write bumps `updated`.

| kind | file | container | line / entry format | order |
|---|---|---|---|---|
| `fact` | `facts.md` | `## <Domain>` (Title Case; created if missing) | `- <text> (YYYY-MM-DD)` | append |
| `pattern` | `patterns.md` | `## <Domain>` | `- **<title>** — <text> (YYYY-MM-DD)` | append |
| `decision` | `decisions_log.md` | top-level, after the template block | `## YYYY-MM-DD — <title>` then `**Decision:** … / **Reason:** … / **Classification:** [reversible\|irreversible] × [low-risk\|high-risk] / **Confidence:** high\|medium\|low` | newest first |
| `correction` | `corrections.md` | under `## Corrections` | `### [YYYY-MM-DD] <title>` then `- **Error:** / - **Correction:** / - **Implied rule:** / - **Theme:** / - **Promoted:**` | newest first |
| `note` | `sessions/YYYY-MM-DD.md` | `## <Section>` from the HSAM list (What We Discussed, URLs & Links Shared, Decisions Made, Facts & Numbers, Ideas & Possibilities, Questions, Tools/Services/Products, Files & Resources, Mood & Context, Corrections & Feedback, Open loops) | `- <text>` | append |
| mission (read-only) | `goals/missions/<ID>.md` | frontmatter `mission_id`, `title`, `priority`, `status`, `next_step`, `last_reviewed` | one file per mission; wins over the `goals/mission_queue.md` table when the folder has files | — |
| `raw` | `raw/YYYY-MM-DD-<slug>.md` | whole file | frontmatter `type: raw, source, title, author, published, fetched, sha256, words, compiled_into` + body | immutable |
| `knowledge` (read-only) | `knowledge/<topic>.md` (files starting with `_` are skipped) | one record per heading | written by the agent through `/distill`; read and indexed here | — |
| record meta | `record_meta.md` | one line per record id | `- <id16> \| keys: … \| learned: … \| source: … \| mission: … \| supersedes: <id16>` | append-only; a later line for the same id adds keys and replaces the rest |

Not written by `VaultStore`: `knowledge/` pages (compiled by the LLM through `/distill`; read and indexed, never written), `executive_state.md`, `session_critique.md` (whole-file rewrites by the agent).

`record_meta.md` holds what a record's own line cannot carry. `keys` are the other words a memory would be asked for by, written by the agent at save time. `learned` are words from a question that missed and was then answered by this record (`brain_remember(kind='key')`), kept apart so they can be reviewed. `supersedes` names the record this one replaced. The id is the first 16 characters of the record id.

## Rules the adapter enforces

- **Dated or legacy.** A bullet without a trailing `(YYYY-MM-DD)` is read with the file's `updated` date and flagged by lint. New writes always carry the date.
- **Idempotent.** The record id is the SHA-256 of the normalised text (whitespace collapsed, date stripped). A write whose id already exists in the target file is a no-op that returns the existing record. Retries after a failed later layer never duplicate.
- **Append-only, atomic.** Writes go to a temp file then `os.replace`, under one exclusive lock per vault (`fcntl.flock`, `msvcrt.locking` on Windows). The lock file lives in `~/.cache/brain-core/locks/`, never inside the vault, because a sync service can evict a file there. Two agents writing the same vault serialise; iCloud's EDEADLK is retried with backoff.
- **Contradiction banner.** `brain_remember` compares a new fact or pattern with the closest one on disk. Nearly the same words with a different number, or with a word the old line lacks, is a changed value: the old line is kept, the new line is prefixed `**⚠ Fact changed YYYY-MM-DD:**`, and `supersedes: <old id>` is recorded in `record_meta.md`. Recall ranks the old record below the new one and marks it `superseded`. Any record can be retired the same way with `extra={"supersedes": id}`. Nothing is deleted.
- **No secrets, by format.** Text matching a known secret format is refused before it touches any store: Hindsight keys (`hsk_`), bearer tokens, `sk-` API keys, AWS access key ids, GitHub and Slack tokens, JWTs, private-key blocks. The filter knows formats, not meaning: a key in a format it does not know is written like any other text.

## Read model

`Record(id, kind, text, date, domain, path, line, extra, score)` for bullets; decisions and corrections return their fields in `extra`. `read(kind, query=None, limit=50)` with no query parses the files, newest first. With a query it searches the record index and returns records in bm25 order with `score` set.

## The record index

Every record of every kind (facts, patterns, decisions, corrections, session notes, raw sources, knowledge pages) and every `stores.notes` folder is in one SQLite FTS5 table in `data/brain.db`, tokenised with stemming and accent folding, ranked by bm25. Search keys are indexed in their own column and never returned. A date stays one token, and a date asked in words ("August 21 2026") is turned into it.

The index is a cache. A file whose size or mtime changed is parsed again on the next search, a deleted file loses its rows, and deleting the table loses nothing: the vault rebuilds it.
