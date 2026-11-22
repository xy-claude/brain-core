# M1 implementation decisions: a checklist for the owner

**Date:** 2026-11-22. **Applies to:** `docs/KNOWLEDGE_ARCHITECTURE_AUDIT.md` revision 2.3, section R and milestone M1.

**Status:**
- **M1 is not authorised.**
- **M0 is not complete:** the human label review is pending.
- **The owner's decisions were taken on 2026-11-22** (section 0). M1a, M1b and M1c still each need their own approval.

Each of M1a, M1b and M1c is approved on its own, by ticking its line below. Nothing in this file has been implemented.

## 0. Decisions taken by the owner, 2026-11-22

| # | Decision | Taken |
|---|---|---|
| 1 | How M1 is approved | One package at a time, M1a → M1b → M1c, each with its own approval after M0 is complete. **None is approved yet** |
| 2 | Notes and archive root names | (a) the folder's own name; `brain doctor` reports a rename |
| 3 | Journal backup | (a) `~/Backups/brain-core/<agent>/journal-YYYY-MM-DD.db`, keeping 14 |
| 14 | Transcript rows lost when Claude Code deletes transcripts | (a) accepted |
| 15 | Who reviews the 104 labels; S3 | The owner reviews the main packet. S3 stays off |
| 19 | After M1b | (a) re-baseline S0 and S2, and report the two absent-question changes |
| 4–13, 17, 18, 20 | The later decisions (section 3) | The recommended defaults are accepted, to be revisited before the milestone named |
| 16 | Fill the live agent's vectors | **Open.** It has no default: it changes the live agent, and is done only when the owner asks |

## 1. The decisions M1 needs

### Decision 1: approve M1a, M1b and M1c, separately

| | |
|---|---|
| **What it means** | Three independent work packages. M1a: relations become canonical. M1b: notes and archive ids become location-independent. M1c: transaction history in `data/journal.db`. Approving one authorises that package only |
| **Why it matters** | Each package changes something in the existing installation (section 2). Approving them separately keeps every change small, testable and reversible on its own |
| **Options** | Approve none yet; approve them in order, one at a time; approve all three |
| **Recommended default** | Approve one at a time, **M1a → M1b → M1c**, each after M0 is complete and the previous package has passed its tests. M1a and M1b may swap. M1c must come after M1b, so the first ledger row already uses stable ids |
| **Risk of the recommendation** | Slower than one big change, and three review cycles. Accepted: each package is easy to roll back alone |
| **Milestone** | M1 |
| **Explicit approval required** | **Yes**, per package |

### Decision 2: how notes and archive roots are named (M1b)

| | |
|---|---|
| **What it means** | After M1b, a notes or archive record's id is built from `<store>:<root name>/<path inside the root>`, no longer from the absolute path. The root name is either the folder's own name, or a `name:` you set in `brain.yaml` |
| **Why it matters** | It decides when ids stay stable. With the folder's name, moving the folder elsewhere keeps every id, but **renaming** the folder changes them. With a configured `name:`, a rename keeps them too |
| **Options** | (a) default to the folder's name, and `brain doctor` reports a root whose files all reappear under another name; (b) require `name:` for every root; (c) a marker file with an id inside each root folder (rejected: it writes into folders brain-core does not own, such as Claude Code's memory folder) |
| **Recommended default** | **(a)**: existing `brain.yaml` files keep working unchanged, and a rename is detected rather than silent |
| **Risk of the recommendation** | Renaming a root before setting `name:` detaches its search keys until `name:` is set (doctor says so) |
| **Milestone** | M1b |
| **Explicit approval required** | **Yes** (part of approving M1b) |

### Decision 3: where the daily journal backup lives (M1c)

| | |
|---|---|
| **What it means** | `data/journal.db` holds the transaction history that cannot be rebuilt from the vault. `brain daily` would copy it once a day to a backup folder |
| **Why it matters** | Without a backup, losing `journal.db` loses that history: every question about the lost period answers *unknown*. The backup holds hashes and short masked quotes (at most 300 characters), not whole records, but they are still private |
| **Options** | (a) `~/Backups/brain-core/<agent>/journal-YYYY-MM-DD.db`, keeping 14, beside the existing Hindsight backups; (b) a folder you choose (`cron.backup.journal_dir`); (c) no backup |
| **Recommended default** | **(a)**: the place backups already go on this machine, no new setting needed |
| **Risk of the recommendation** | The backup folder is not inside the agent folder, so moving the agent to another computer means copying `data/` (which already holds `journal.db`), and the backups only if you want older copies |
| **Milestone** | M1c |
| **Explicit approval required** | **Yes** |

### Decision 14: transcript rows lost when Claude Code deletes old transcripts (M1c)

| | |
|---|---|
| **What it means** | brain-core indexes the Claude Code session transcripts (`~/.claude/projects/*.jsonl`). Claude Code deletes old transcripts after a while, and a rebuild of `brain.db` cannot bring back rows whose transcript file is gone |
| **Why it matters** | It is the one kind of searchable text that a full rebuild can lose |
| **Options** | (a) accept it, as 0.9.1 does today; (b) include the transcript rows in the daily journal backup |
| **Recommended default** | **(a) accept**. Transcripts are Claude Code's files, they are large (17,803 rows on the live agent), and the knowledge in them that matters is meant to be written to the vault on purpose |
| **Risk of the recommendation** | After a rebuild of `brain.db`, `scope='transcript'` recall finds only the transcripts Claude Code still keeps |
| **Milestone** | M1c |
| **Explicit approval required** | **Yes** (a decision about what is kept) |

### Decision 19: re-measure the baseline after M1b

| | |
|---|---|
| **What it means** | After M1b, run the eval again (S0 and S2) on corrected labels, and record the results as the new baseline. Do not count M1b as an improvement or a regression |
| **Why it matters** | The frozen snapshot measured notes and archive recall **without** their 588 search-key lines, because those keys use the live agent's absolute paths (G11). On isolated copies:<ul><li>M1b's new ids alone reproduce M0 question for question.</li><li>With the keys finally attached, S0 moves 295 → 298 (12 fixed, 9 broken) and S2 346 → 347 (7 fixed, 6 broken), with two more false answers on questions that are not in memory</li></ul> |
| **Options** | (a) re-baseline; (b) gate M1b on "no regression" (it would fail on those two absent questions, though the cause is keys that should always have applied); (c) do not attach the old keys |
| **Recommended default** | **(a) re-baseline**, and report the two absent-question changes explicitly |
| **Risk of the recommendation** | The new baseline is a moving point; M4's gate must compare with it, not with 295/346 |
| **Milestone** | M1b, then M4's gate |
| **Explicit approval required** | **Yes** |

### Decision 15 (gates M0, so it comes first): who reviews the labels; S3

| | |
|---|---|
| **What it means** | A person must review the 104 questions in `local/audit-m0/human_review/` before M0 is complete. S3, the model judge, would send questions and memory records to Anthropic |
| **Recommended default** | You review the main packet, and optionally give the blind copy to an independent reviewer. S3 stays off until you approve it |
| **Explicit approval required** | **Yes**, for S3 |

## 2. The three work packages

### M1a: relations become canonical, plus hygiene

| | |
|---|---|
| **Depends on** | M0 complete; decision 1 |
| **Scope** | <ul><li>Relations are written to and read from a new vault file, `vault/relations.md` (one line each: `- [[S]] —[p: role]→ [[O]] (date)`).</li><li>A one-time `brain graph migrate` copies the existing table rows into it (82 on the live agent).</li><li>From then on the `relations` table is rebuilt from the file.</li><li>Also: the stale docstring in `mcp/server.py`, and a row count of the unused v0.1 tables in `brain doctor`</li></ul> |
| **Impact on the existing installation** | <ul><li>**Vault:** one new file, `relations.md`, visible in Obsidian as ordinary notes with wikilinks. The migration writes it once.</li><li>**brain.db:** unchanged rows.</li><li>**Recall:** the same relations, from a rebuildable source. No id changes. No config change.</li><li>A 0.9.1 install reading the same vault ignores the new file</li></ul> |
| **Tests (acceptance)** | <ul><li>Delete `brain.db`, run `brain index`: every relation comes back.</li><li>Running the migration twice adds nothing.</li><li>The existing write scenarios pass.</li><li>`ruff`, `mypy --strict` and `pytest` pass</li></ul> |
| **Rollback** | Revert the code. The table was never emptied, so 0.9.1 reads it as before. `relations.md` can stay (it is readable notes) or be deleted |
| **Approve** | [ ] **M1a approved** — date and initials: |

### M1b: stable source ids for notes and archive (fixes G11)

| | |
|---|---|
| **Depends on** | M0 complete; decisions 1, 2 and 19 |
| **Scope** | <ul><li>Notes and archive record ids hash `<store>:<root name>/<path>#heading`.</li><li>An optional `name:` per root.</li><li>The displayed path, as cited in recall, is unchanged.</li><li>Vault ids are unchanged.</li><li>`brain index --migrate-ids` is a dry run by default. With `--apply` it does three things:<ul><li>appends `was:` lines to `record_meta.md` (588 on the live agent), under a dated comment line so they are easy to find</li><li>remaps the affected vectors in `brain.db` (633)</li><li>can translate the owner's private eval labels under `local/`</li></ul></li><li>`brain doctor` reports a renamed root</li></ul> |
| **Impact on the existing installation** | <ul><li>**Vault:** 588 appended lines in `record_meta.md`, nothing else.</li><li>**brain.db:** the notes and archive index rows are re-read under new ids, and vectors are remapped (the rest are re-embedded lazily, as today).</li><li>**Recall:** identical, question by question, until the keys attach. Then the notes and archive search keys the agent wrote start to work: about 20 of 446 eval questions change.</li><li>**Config:** optional `name:`; plain path lists stay valid.</li><li>**Downgrade:** a 0.9.1 install ignores the `was:` lines and computes the old ids, so the keys detach exactly as they do today</li></ul> |
| **Tests (acceptance)** | <ul><li>G11-T1 a moved root keeps its ids; T2 a renamed root with `name:` keeps them; T3 a rename without `name:` is detected; T4 a file moved inside a root re-keys only its knowledge sections; T5 keys, `supersedes` links and vectors follow the migration.</li><li>The M0 eval on the new ids alone is identical question by question (already validated on copies).</li><li>Then the re-baseline (decision 19)</li></ul> |
| **Rollback** | Delete the dated block of `was:` lines from `record_meta.md`, revert the code, and rebuild `brain.db` (or restore a copy taken before `--apply`): the old ids return. Make that copy before `--apply` |
| **Approve** | [ ] **M1b approved**, including the vault write of the `was:` lines — date and initials: |

### M1c: durable transaction history in `data/journal.db`

| | |
|---|---|
| **Depends on** | M1b (stable ids before the first ledger row); decisions 1, 3 and 14 |
| **Scope** | <ul><li>A new file `data/journal.db` (`record_ledger`, `ledger_gaps`), with its own migrations.</li><li>Each sync writes it first, idempotently, then `brain.db` with the signatures last.</li><li>`brain_remember` stamps its writes.</li><li>`brain daily` copies `journal.db` to the backup folder (decision 3).</li><li>`brain journal restore FILE` merges a backup.</li><li>`brain doctor` checks the integrity of both files</li></ul> |
| **Impact on the existing installation** | <ul><li>**New files:** `data/journal.db`, and the daily backups.</li><li>**Vault:** untouched.</li><li>**History:** starts on the day M1c is installed. Everything already in the vault gets that day as its first recording time: late, never early.</li><li>**Cost:** one small extra transaction per sync (to be measured: within +10% of the 5 ms no-change sync); the journal is small (measured on a copy before release).</li><li>**Deleting `brain.db`:** still safe, as the README says, and now keeps history</li></ul> |
| **Tests (acceptance)** | <ul><li>The ledger scenarios L1–L11 against the real code.</li><li>The reconciliation property: incremental equals rebuild, with injected crashes between the two commits.</li><li>A backdated hand-written line gets its ingest time.</li><li>`brain index --rebuild` keeps every ledger row.</li><li>A backup restored on a copy recovers the history up to it and reports the gap</li></ul> |
| **Rollback** | Revert the code and delete `data/journal.db`. Only the history recorded since M1c is lost; `brain.db` and the vault are unaffected |
| **Approve** | [ ] **M1c approved** — date and initials: |

## 3. The other decisions in section R

None of these is needed for M1. Each has a recommended default in the audit (section R) and is decided before the milestone named.

| # | Decision | Default | Before |
|---|---|---|---|
| 4 | expose `known_at` in `brain_recall` | CLI and eval only, never before M3's journal | M4 |
| 5 | a decision's date as the start of its claims | yes, overridable | M3 |
| 6 | rule-derived claims accepted without review | yes, shown as `derived` | M3 |
| 7 | contradictory dates | an UNKNOWN window | M3 |
| 8 | per-copy meta syntax | `<rid16>@<source>#<k>` | M3 |
| 9 | merged claims whose reviews disagree | the later one applies, reported | M3 |
| 10 | "never true" statements | a retraction | M3 |
| 11 | functional predicates and roles | `PART_OF`, literal values, `USES` per role | M2 |
| 12 | literal datatypes | text, int, version, port, url, date | M3 |
| 13 | knowledge pages renamed in the vault | accept; offer `--relink` with approval | M2 |
| 16 | fill the live agent's vectors (83% missing) | your call; operational | any time |
| 17 | the margin that justifies a JVM service | set before the benchmark | M6 |
| 18 | leave the line number out of journal versions | yes | M3 |
| 20 | per-copy meta after the copies changed | report it, do not apply it until re-anchored | M3 |

## 4. Readiness

**NOT READY FOR M1.** The design is ready: revision 2.3 resolved the last three concerns, each with regression tests, and the owner's decisions are taken (section 0). Two things are open:

1. M0 is not complete: the owner must review the 104 labels, approve the corrections, and re-score.
2. After that, M1a needs its own approval (section 2), and later M1b and M1c theirs.
