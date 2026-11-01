# Vault schema (v0.2, M9)

The markdown vault is the source of truth. `VaultStore` reads and writes it by **kind**. This page codifies the conventions the the reference agent vault already uses (surveyed 2026-11-02), so legacy files are read as-is and no migration is required. Where a file deviates, the lint reports it; the adapter never rewrites history.

Root: `agents/<NAME>/` (one folder per agent). All files have YAML frontmatter with at least `type`, `owner`, `updated` (YYYY-MM-DD). Every write bumps `updated`.

| kind | file | container | line / entry format | order |
|---|---|---|---|---|
| `fact` | `facts.md` | `## <Domain>` (Title Case; created if missing) | `- <text> (YYYY-MM-DD)` | append |
| `pattern` | `patterns.md` | `## <Domain>` | `- **<title>** — <text> (YYYY-MM-DD)` | append |
| `decision` | `decisions_log.md` | top-level, after the template block | `## YYYY-MM-DD — <title>` then `**Decision:** … / **Reason:** … / **Classification:** [reversible\|irreversible] × [low-risk\|high-risk] / **Confidence:** high\|medium\|low` | newest first |
| `correction` | `corrections.md` | under `## Corrections` | `### [YYYY-MM-DD] <title>` then `- **Error:** / - **Correction:** / - **Implied rule:** / - **Theme:** / - **Promoted:**` | newest first |
| `note` | `sessions/YYYY-MM-DD.md` | `## <Section>` from the HSAM list (What We Discussed, URLs & Links Shared, Decisions Made, Facts & Numbers, Ideas & Possibilities, Questions, Tools/Services/Products, Files & Resources, Mood & Context, Corrections & Feedback, Open loops) | `- <text>` | append |
| `raw` | `raw/YYYY-MM-DD-<slug>.md` | whole file | frontmatter `type: raw, source, title, author, published, fetched, sha256, words, compiled_into` + body | immutable |

Not handled by `VaultStore`: `knowledge/` pages (compiled by the LLM through `/distill`), `executive_state.md`, `session_critique.md`, `intelligence_dashboard.md` (whole-file rewrites by the agent).

## Rules the adapter enforces

- **Dated or legacy.** A bullet without a trailing `(YYYY-MM-DD)` is read with the file's `updated` date and flagged by lint. New writes always carry the date.
- **Idempotent.** The record id is the SHA-256 of the normalised text (whitespace collapsed, date stripped). A write whose id already exists in the target file is a no-op that returns the existing record. Retries after a failed later layer never duplicate.
- **Append-only, atomic.** Writes go to a temp file then `os.replace`, under a `.lock` sidecar (`fcntl.flock`). Two agents writing the same shared file serialise; iCloud's EDEADLK is retried with backoff (same approach as AI-ORG `resilient_write`).
- **Contradiction banner.** When a `fact` write names an existing fact's subject with a different value (caller passes `supersedes=<id>`), the old line is kept and the new line is prefixed `**⚠ Fact changed YYYY-MM-DD:**`. Nothing is deleted.
- **No secrets.** Text matching the gitleaks rules (`hsk_`, bearer tokens, keys) is refused before it touches disk.

## Read model

`Record(id, kind, text, date, domain, path, line)` for bullets; decisions and corrections return their fields in `extra`. `read(kind, query=None, since=None, limit=50)` greps bullets (ripgrep when present, Python fallback), newest first.
