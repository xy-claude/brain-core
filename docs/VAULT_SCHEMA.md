# Vault schema (v0.2, updated for 0.9)

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

`models/<name>.md` holds the mental models `brain models` writes (frontmatter `type: model`, `question`, `records: N read, M cited`; bullets ending in `[file:line]`), with `<name>.prev.md` one generation back. They are not records: no kind reads them and the index leaves them out.

Not written by `VaultStore`: `knowledge/` pages (compiled by the LLM through `/distill`; read and indexed, never written), `executive_state.md`, `session_critique.md` (whole-file rewrites by the agent).

`record_meta.md` holds what a record's own line cannot carry. `keys` are the other words a memory would be asked for by, written by the agent at save time. `learned` are words from a question that missed and was then answered by this record (`brain_remember(kind='key')`), kept apart so they can be reviewed. `supersedes` names the record this one replaced. The id is the first 16 characters of the record id.

## Rules the adapter enforces

- **Dated or undated.** A fact or pattern bullet without a trailing `(YYYY-MM-DD)` has no date of its own. It is read as undated: recall shows no date for it, it is not found by day and it never wins a tie as the newest. It is ranked as current, the way a standing fact should be, so an old undated value that no banner marks can stand above a newer dated line. Lint flags it. New writes always carry the date.
- **Idempotent.** The record id is the SHA-256 of the normalised text (whitespace collapsed, date stripped). A write whose id already exists in the target file is a no-op that returns the existing record. Retries after a failed later layer never duplicate.
- **Append-only, atomic.** Writes go to a temp file then `os.replace`, under one exclusive lock per vault (`fcntl.flock`, `msvcrt.locking` on Windows). The lock file lives in `~/.cache/brain-core/locks/`, never inside the vault, because a sync service can evict a file there. Two agents writing the same vault serialise; iCloud's EDEADLK is retried with backoff.
- **Contradiction banner.** `brain_remember` compares a new fact or pattern with the closest one on disk. Nearly the same words with a different number, or with a word the old line lacks, is a changed value: the old line is kept, the new line is prefixed `**⚠ Fact changed YYYY-MM-DD:**`, and `supersedes: <old id>` is recorded in `record_meta.md`. Recall ranks the old record below the new one and marks it `superseded`. Any record can be retired the same way with `extra={"supersedes": id}`. Nothing is deleted.
- **No secrets, by shape.** Text that holds a credential is refused before it touches any store, and masked as `[redacted]` when a hand-written file is indexed and in every reply. Known shapes: vendor key formats (Hindsight, Anthropic and OpenAI style `sk-`, AWS, GitHub, Slack, Stripe, Google, Telegram, Hugging Face, npm, PyPI, GitLab, SendGrid, DigitalOcean), bearer tokens, JWTs, private-key blocks with their body, a password inside a URL, dash-joined licence keys, and a long mixed value after a label (`key`, `token`, `auth`, `licence`, `credential`: a letter and a digit must touch twice; `password`, `secret`: once). The filter knows shapes, not meaning: see `docs/THREAT_MODEL.md` for what it cannot see.
- **A repeated title is a second entry.** A decision or correction saved under a title an earlier entry already has, with a different body, is stored as `<title> (2)`; a decision is also linked to the one before it (`supersedes`), so recall shows the newer one first. The first entry keeps its id.
- **One bad file does not stop the vault.** A byte that is not UTF-8 costs one character of one record and is written back unchanged. A file that cannot be read is skipped, named by `health`, and raised as `attention` in `brain_status`.

## What the reader takes as a record

Besides the line and entry formats above, the reader takes in what a hand-written vault holds: a decision under a level-3 heading (`### YYYY-MM-DD — <title>`) or with a time or note between the date and the dash; a `## YYYY-MM-DD — <title>` entry in `corrections.md`; every field of a decision or correction, whatever its name; a paragraph, list or table in a session file that is not a bullet under a section (one record per block; a line that is only a label is not one); and the text above a knowledge page's first heading. A `####` to `######` heading ends the entry above it. The text of a correction is kept as a `**Summary:**` field when an error is also given.

## Read model

`Record(id, kind, text, date, domain, path, line, extra, score, undated)` for bullets; decisions and corrections return their fields in `extra`. `read(kind, query=None, limit=50)` with no query parses the files, newest first. With a query it searches the record index and returns records in bm25 order with `score` set.

## The record index

Every record of every kind (facts, patterns, decisions, corrections, session notes, raw sources, knowledge pages) and every `stores.notes` and `stores.archive` folder is in one SQLite FTS5 table in `data/brain.db`, tokenised with stemming and accent folding, ranked by bm25. Search keys are indexed in their own column and never returned. A date stays one token, and a date asked in words ("August 21 2026") is turned into it.

The index is a cache. A file whose size or mtime changed is parsed again on the next search, a deleted file loses its rows, and deleting the table loses nothing: the vault rebuilds it. A vault folder that is missing (a drive not mounted) is an error, never an empty vault: no row and no vector is dropped.

With a vault configured, the vault's files are the only truth for facts and patterns: the SQLite `facts` table is a copy, it is not searched and not used for the duplicate check, so a line edited or deleted by hand is what recall and `brain_remember` see. The copy answers only for rows no vault file ever held (saved with no vault, or when the vault write failed), when asked by name (`scope='sqlite'`), or when the vault cannot be read.
