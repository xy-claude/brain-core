# M1 implementation decisions: a checklist for the owner

**Date:** 2026-11-22. **Applies to:** `docs/KNOWLEDGE_ARCHITECTURE_AUDIT.md` revision 2.3, section R and milestone M1.

**Status:**
- **M1 is not authorised.** M1a needs its own approval (section 2).
- **M0 is complete as of 2026-11-22,** with the human label review waived by the owner: the labels are AI-reviewed, not human-validated (`docs/M0_BASELINE.md`, section 9).
- **The owner's decisions were taken on 2026-11-22** (section 0). M1a, M1b and M1c still each need their own approval.

Each of M1a, M1b and M1c is approved on its own, by ticking its line below. Nothing in this file has been implemented.

## 0. Decisions taken by the owner, 2026-11-22

| # | Decision | Taken |
|---|---|---|
| 1 | How M1 is approved | One package at a time, M1a → M1b → M1c, each with its own approval after M0 is complete. **None is approved yet** |
| 2 | Notes and archive root names | (a) the folder's own name; `brain doctor` reports a rename |
| 3 | Journal backup | (a) `~/Backups/brain-core/<agent>/journal-YYYY-MM-DD.db`, keeping 14 |
| 14 | Transcript rows lost when Claude Code deletes transcripts | (a) accepted |
| 15 | Who reviews the 104 labels; S3 | **Changed the same day.** The owner had Claude answer the packet, then accepted the AI answers as they are, without checking them. The corrected labels are AI-reviewed, not human-validated (`docs/M0_BASELINE.md`, section 9). S3 stays off |
| 19 | After M1b | (a) re-baseline S0 and S2, and report the two absent-question changes |
| 4–13, 17, 18, 20 | The later decisions (section 3) | The recommended defaults are accepted, to be revisited before the milestone named |
| 21 | The date a migrated relation gets (M1a) | **Revised after the second review round:** the full `created_at` is kept as `recorded:` provenance, and no stated date is given, so migrated relations are undated. The first version, "holds from the recorded day", mixed recording time with valid time. **Confirmed by the owner, 2026-11-22** |
| 16 | Fill the live agent's vectors | **Open.** It has no default: it changes the live agent, and is done only when the owner asks |

### The owner's program decisions (2026-11-22, after M1a)

The owner asked for the whole plan to be finished, with housekeeping, without stopping at each gate:

| Decision | Taken |
|---|---|
| Live cutovers | Claude cuts the live agents over itself after each milestone passes its tests on an isolated copy, with M1a's procedure each time: release, stop the agents' brain servers, take a fresh inventory, back up, migrate, verify. It stops if a check fails |
| M4's eval gate | AI-reviewed labels, as for M0, recorded as not human-validated |
| Optional milestones | M7 (conflict checks) only. Not M5 (it sends memory text to an LLM) and not M6 (a Neo4j download) |
| Decision 22 (M3 only with evidence of need) | Overridden by the owner's instruction to finish the plan |
| M1a step 6 | A relation the vault already stated, saved on the live agent and verified: M1a accepted |

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
| **Why it matters** | The frozen snapshot measured notes and archive recall **without** their 588 search-key lines, because those keys use the live agent's absolute paths (G11). On isolated copies:<ul><li>M1b's new ids alone reproduce M0 question for question.</li><li>With the keys finally attached, on the historical labels, S0 moves 295 → 298 (12 fixed, 9 broken) and S2 346 → 347 (7 fixed, 6 broken), with two more false answers on questions that are not in memory</li></ul> |
| **Options** | (a) re-baseline; (b) gate M1b on "no regression" (it would fail on those two absent questions, though the cause is keys that should always have applied); (c) do not attach the old keys |
| **Recommended default** | **(a) re-baseline**, and report the two absent-question changes explicitly |
| **Risk of the recommendation** | The new baseline is a moving point; M4's gate must compare with it, not with the M0 baseline (298/345 of 443, or the historical 295/346 of 446) |
| **Milestone** | M1b, then M4's gate |
| **Explicit approval required** | **Yes** |

### Decision 15 (gates M0, so it comes first): who reviews the labels; S3

| | |
|---|---|
| **What it means** | A person must review the 104 questions in `local/audit-m0/human_review/` before M0 is complete. S3, the model judge, would send questions and memory records to Anthropic |
| **Recommended default** | You review the main packet, and optionally give the blind copy to an independent reviewer. S3 stays off until you approve it |
| **Explicit approval required** | **Yes**, for S3 |
| **Taken, 2026-11-22** | The owner waived the human review: Claude answered the packet, and the owner accepted the answers unchecked. S3 stays off |

## 2. The three work packages

### M1a: relations become canonical, plus hygiene

| | |
|---|---|
| **Depends on** | M0 complete; decision 1 |
| **Scope** | <ul><li>Relations are written to and read from a new vault file, `vault/relations.md` (one line each: `- [[S]] —[p: role]→ [[O]] (date)`). The date is a stated date: the day the relation holds from, written only when the text gives one. Each line also carries `recorded: <UTC timestamp>`, which is provenance only: never valid time, and never transaction time either (that comes from the journal's clock from M1c on).</li><li>**The legacy `relations` table stays written until M3, as a compatibility mirror.** M1a's own code never reads it: recall reads the index built from `relations.md`. `brain_remember` writes the vault line first (atomically, under the vault lock), then the mirror row; a failed vault write leaves no mirror row, and a retry converges by id. Every sync upserts the mirror from `relations.md`. A 0.9.1 reader after a rollback therefore sees every relation, including those written after the migration.</li><li>**`relations.md` is append-only until M3,** as every vault file already is (README: "append-only, nothing deleted"). A line removed or edited by hand is named by `brain doctor` and `brain_status`, drops out of M1a's recall, and keeps its mirror row. A 0.9.1 reader after a rollback cannot honour such a removal; that is documented. Retracting a relation properly arrives with M3's `claim_reviews.md`.</li><li>A one-time `brain graph migrate` copies the existing rows into the file (82 on the live agent). Before it writes anything, it:<ul><li>takes a verified backup: `brain.db` through SQLite's backup API, checked with `PRAGMA integrity_check`, plus the checksum of every vault file it touches</li><li>refuses, and names, any row whose subject or object contains `[[`, `]]` or `\|`, or whose predicate contains `]` or `:` (0 such rows on the live agent)</li></ul>It writes `relations.md` atomically (a temp file, then a rename), so a crash leaves either the old file or the new one. **It never overwrites or drops existing lines:** if the file exists, it appends only the ids not yet in it. Rerunning adds nothing.</li><li>**Date mapping (decision 21, revised):** a migrated row keeps its full `created_at` as `recorded:`, and gets no stated date. Recording a relation does not show when it became true, so migrated relations are undated: true today, unknown for past dates.</li><li>**Hygiene:**<ul><li>the stale docstring in `mcp/server.py`</li><li>`brain doctor` counts the rows a rebuild of `brain.db` would not restore: unused v0.1 tables, `sole` facts (0 on the live agent on 2026-11-21), events (1,191) and metrics (276)</li><li>the README's "one SQLite file, rebuilt from the vault" is corrected to name those exceptions</li></ul></li></ul> |
| **Impact on the existing installation** | <ul><li>**Vault:** one new file, `relations.md`, visible in Obsidian as ordinary notes with wikilinks.</li><li>**brain.db:** the `relations` table keeps every row and gains the new ones.</li><li>**Recall:** the same relations for every entity (tested), now from a rebuildable source. No id changes. No config change.</li><li>A 0.9.1 install ignores the new file and reads the table</li></ul> |
| **Tests (acceptance)** | <ul><li>**Every destructive test runs on a copy.** The migration refuses to run without the verified backup above.</li><li>**Field-level round trip:** migrate, delete `brain.db` (on the copy), run `brain index`. The table's set of (id, subject, predicate, object, `created_at`) is identical to before, full timestamps included.</li><li>**Relation recall** for each of the 75 entities is identical before and after.</li><li>**Crash:** kill the migration after `relations.md` is written and before the sync; the rerun converges, and running the migration twice adds nothing.</li><li>**Rollback after new writes:** on a copy, migrate, write 5 new relations, then switch back to 0.9.1: all 87 are visible.</li><li>**Refused characters:** a row with `]]` is refused and reported, and the rest migrate.</li><li>**A hand-deleted line** is reported and drops out of M1a's recall; its mirror row stays.</li><li>**A failed vault write** leaves no mirror row, and the retry converges without duplicates.</li><li>**A pre-existing `relations.md`** keeps every line it had.</li><li>The `sole` inventory is re-counted at cutover, not trusted from 2026-11-21.</li><li>The existing write scenarios pass.</li><li>`ruff`, `mypy --strict` and `pytest` pass</li></ul> |
| **Rollback** | Revert the code. The table holds every relation, including those written after the migration, because it stays written until M3, so 0.9.1 reads them all. `relations.md` can stay (it is readable notes). The backup taken before the migration is the last resort |
| **Implementation (2026-11-22, branch `claude/m1a-canonical-relations`; not cut over)** | <ul><li>**Code:**<ul><li>`relations.md` is read and written by the vault store</li><li>the mirror is refilled whenever the file is re-indexed</li><li>recall reads relations through the table, limited to those the file holds, so they rank as in 0.9.1 and stay out of the keyword index</li><li>`brain graph migrate` exits 1, as incomplete, while a row it refused remains</li><li>`brain doctor` counts what only `brain.db` holds and names drift</li><li>the whole suite passes (589, 3 skipped); `ruff` and `mypy --strict` are clean</li></ul></li><li>**Agreed with the second-model review, round four:**<ul><li>default-scope ranking is preserved, because M1a changes storage only</li><li>no relation is saved while `brain.db` holds relations and `relations.md` does not exist: the save is refused with the instruction to run `brain graph migrate`, so the file is only ever first made behind a backup</li><li>a row no line can hold is still read from the table, as temporary compatibility, and the migration is not complete while one remains</li><li>`scope='graph'` reads the file's relations</li></ul></li><li>**On an isolated copy of the live data** (2026-11-21):<ul><li>before the migration a relation write is refused and makes no file, while recall still finds the 82 relations</li><li>82 of 82 migrated with every field identical, 0 refused, complete; a re-run adds nothing</li><li>the backup, restored into a new folder, passes `integrity_check` and holds the same relations and events</li><li>all 75 entities recall every relation of theirs</li><li>**default-scope recall for the 75 entity names: top 10 identical to 0.9.1 (ids, order, kinds) for 75 of 75**</li><li>a `brain.db` rebuilt from the vault alone is identical</li><li>a line removed by hand stays out of recall and is named</li><li>a crash between the vault line and the mirror row heals on the next sync (unit test)</li><li>after 5 new relations, **real 0.9.1 code** reads all 87 and recalls the 5</li><li>no-change sync 0.83 ms against 0.85 ms on 0.9.1; recall p95 66.7 ms against 67.1 ms</li><li>S0 on the eval snapshot 298 of 443, 0 fixed and 0 broken</li><li>every live `created_at` is a date, and a full timestamp is covered by a unit test</li><li>no credentials, no network; the tripwire stayed empty</li></ul></li><li>**Live cutover procedure** (each step on the live agent, after the owner's approval):<ol><li>stop the writers: close Claude Code sessions on the agent, and let no cron job run</li><li>take a fresh inventory: relation count, rows the line cannot hold, `sole` facts, events and metrics, never reused from this copy</li><li>install the release</li><li>run `brain graph migrate`; it must report complete</li><li>check relation parity with the inventory</li><li>start the MCP server, then save one genuine relation the owner approves (the file is append-only, so no throwaway test relation) and check it in the file, in the mirror and in recall</li></ol>Any step that fails stops the cutover: it is not declared done.Until step 4 the code itself refuses relation saves.</li></ul> |
| **Approve** | [x] **M1a approved** for implementation on an isolated copy — 2026-11-22, by the owner. The live cutover needs a separate approval after the acceptance tests pass |

### M1b: stable source ids for notes and archive (fixes G11)

| | |
|---|---|
| **Depends on** | M0 complete; decisions 1, 2 and 19 |
| **Scope** | <ul><li>Notes and archive record ids hash `<store>:<root name>/<path>#heading`.</li><li>An optional `name:` per root.</li><li>The displayed path, as cited in recall, is unchanged.</li><li>Vault ids are unchanged.</li><li>`brain index --migrate-ids` is a dry run by default. With `--apply` it does three things:<ul><li>appends `was:` lines to `record_meta.md` (588 on the live agent), under a dated comment line so they are easy to find</li><li>remaps the affected vectors in `brain.db` (633)</li><li>can translate the owner's private eval labels under `local/`</li></ul></li><li>`brain doctor` reports a renamed root.</li><li>**`--apply` can resume after a crash.** It runs these steps in order:<ol><li>takes a verified backup of `brain.db` (backup API and `PRAGMA integrity_check`) and the checksum of `record_meta.md`</li><li>writes a mapping manifest under `data/`: old id, new id and checksums</li><li>appends the `was:` lines, skipping any already present</li><li>remaps the vectors, which is idempotent</li><li>records that the migration is applied</li></ol>A crash at any step resumes from the manifest. **A resume first checks the manifest** against the current source files and configuration, and refuses (asking for a fresh dry run) if they changed. A rollback removes only the migration's own dated block, never `record_meta.md` lines added later.</li></ul> |
| **Impact on the existing installation** | <ul><li>**Vault:** 588 appended lines in `record_meta.md`, nothing else.</li><li>**brain.db:** the notes and archive index rows are re-read under new ids, and vectors are remapped (the rest are re-embedded lazily, as today).</li><li>**Recall:** identical, question by question, until the keys attach. Then the notes and archive search keys the agent wrote start to work: about 20 of 446 eval questions change.</li><li>**Config:** optional `name:`; plain path lists stay valid.</li><li>**Downgrade:** a 0.9.1 install ignores the `was:` lines and computes the old ids, so the keys detach exactly as they do today</li></ul> |
| **Tests (acceptance)** | <ul><li>G11-T1 a moved root keeps its ids; T2 a renamed root with `name:` keeps them; T3 a rename without `name:` is detected; T4 a file moved inside a root re-keys only its knowledge sections; T5 keys, `supersedes` links and vectors follow the migration.</li><li>The M0 eval on the new ids alone is identical question by question (already validated on copies).</li><li>**Crash injected after each `--apply` step** (manifest, `was:` append, half the vectors): the rerun ends in the same state as an uninterrupted run.</li><li>**Rollback tested after ordinary writes made since the migration.**</li><li>Then the re-baseline (decision 19)</li></ul> |
| **Rollback** | Delete the dated block of `was:` lines from `record_meta.md`, revert the code, and run `brain index --rebuild`. The old ids return, events and metrics written since are kept, and the remapped vectors are re-embedded lazily. Restoring the backup taken before `--apply` is the last resort: it would drop the events and metrics written since |
| **Implementation (2026-11-22)** | <ul><li>**Code:**<ul><li>ids hash `<store>:<root name>/<file>#heading`; a folder takes its own name or `{path, name}`; two folders sharing a name keep their path ids, and doctor says so</li><li>each record keeps its old id as `extra["was"]`, so keys and `supersedes` links hold without a migration</li><li>`brain index --migrate-ids [--apply] [--old-path NAME=PATH]`: a checked backup, then a manifest, `was:` lines, vector remap, re-index and check; it resumes after a crash and refuses changed files</li><li>`brain doctor` names detached keys</li><li>`tests/eval/translate_labels.py`</li></ul></li><li>**On an isolated copy of today's live agent**, with its folders read in place:<ul><li>upgrading alone keeps all 588 keyed records, detaches none, and recall matches 0.10.0 for 199 of 200 queries (one tie)</li><li>the migration moves 2,805 ids, adds 588 `was:` lines, remaps 633 vectors and verifies; a re-run adds nothing</li><li>recall matches 0.10.0 for 198 of 200 queries, the other two at near-ties (0.322 against 0.321, and an equal score)</li><li>**with the folders moved elsewhere,** all 2,805 ids, 588 keys and 1,043 vectors stay, and recall is identical to the in-place copy for 200 of 200</li><li>rollback to real 0.10.0 keeps every key and recalls 199 of 200 identically; the 633 remapped vectors would be made again</li><li>timing, the two run alternately twice each: recall p95 96.5 and 100.8 ms against 112.7 and 103.8 ms for 0.10.0; no-change sync about 4.4 ms for both</li></ul></li><li>**Found and fixed on the copies:**<ul><li>keys counted twice after the migration, which changed the ranking</li><li>the old id in replies cost the token budget a result</li></ul></li><li>**Eval (decision 19), labels translated:**<ul><li>the new ids alone reproduce M0 exactly: S0 298 of 443, 0 fixed and 0 broken</li><li>with the snapshot's 588 keys attached through `--old-path`: **S0 301 of 443** (12 fixed, 9 broken, p 0.66) and **S2 347 of 443** (7 fixed, 5 broken, p 0.77), with 2 more false answers on absent questions in each. That is the new baseline (`docs/M0_BASELINE.md`, section 10)</li></ul></li></ul> |
| **Approve** | [x] **M1b approved** by the owner's program decision of 2026-11-22, including the vault write of the `was:` lines |

### M1c: durable transaction history in `data/journal.db`

| | |
|---|---|
| **Depends on** | M1b (stable ids before the first ledger row); decisions 1, 3 and 14 |
| **Scope** | <ul><li>A new file `data/journal.db` (`record_ledger`, `ledger_gaps`), with its own migrations.</li><li>Each sync writes it first, idempotently, then `brain.db` with the signatures last.</li><li>**Durable commits:** `journal.db` uses WAL with `synchronous=FULL`, so a committed ledger row survives a power loss. `brain.db` stays at `NORMAL`, because it is derived.</li><li>**Consistency marker:** `journal.db` holds a random `generation` id, created with the file, and each sync gets an increasing `sync_seq`. Both go into the journal's ledger transaction and into `brain.db` with the signatures. At startup:<ul><li>**journal ahead of `brain.db`** (a crash after the journal commit): normal; the old signatures make the sync derive again, and the journal writes are idempotent</li><li>**`brain.db` ahead, or a different `generation`** (a lost commit, an older backup restored, or a journal from another lineage): record a `restore` gap, ignore the signatures and re-read every source</li><li>**equal:** proceed</li><li>**journal missing or corrupt:** a new generation and epoch; earlier recording times answer *unknown* and are never invented</li></ul></li><li>**One writer at a time:** a sync holds a per-agent OS file lock, kept outside the vault like the vault lock, from before it reads the signatures until `brain.db` commits. `BEGIN IMMEDIATE` is still used inside each database's transaction, but a SQLite lock ends at its commit, so it cannot cover both. The MCP server, the CLI and cron therefore never interleave.</li><li>**At most one open version per occurrence,** enforced by a unique index (audit L.1).</li><li>`brain_remember` stamps its writes.</li><li>**Backups:** `brain daily` copies `journal.db` to the backup folder (decision 3) through the backup API into a temp file, checks it with `PRAGMA integrity_check`, then renames it into place. The folder is `0700` and the files `0600`; the 14 newest are kept.</li><li>`brain journal restore FILE` merges a backup and refuses a corrupt one.</li><li>`brain doctor` checks the integrity of both files</li></ul> |
| **Impact on the existing installation** | <ul><li>**New files:** `data/journal.db`, and the daily backups.</li><li>**Vault:** untouched.</li><li>**History:** starts on the day M1c is installed. Everything already in the vault gets that day as its first recording time: late, never early.</li><li>**Cost:** one small extra transaction per sync (to be measured: within +10% of the 5 ms no-change sync); the journal is small (measured on a copy before release).</li><li>**Deleting `brain.db`:** still safe for everything derived, and now keeps history. **`journal.db` is not derived and must never be deleted to "rebuild"**; the README says so</li></ul> |
| **Tests (acceptance)** | <ul><li>The ledger scenarios L1–L11 against the real code.</li><li>The reconciliation property: incremental equals rebuild, with injected crashes between the two commits.</li><li>A backdated hand-written line gets its ingest time.</li><li>`brain index --rebuild` keeps every ledger row.</li><li>A backup restored on a copy recovers the history up to it and reports the gap. A restore whose gap overlaps recent writes reports that, and a corrupt or truncated backup is refused.</li><li>**Every state of the marker:** the journal ahead (a crash after its commit); `brain.db` ahead (a lost commit: `journal.db` replaced by a copy taken before its last commit); an older backup restored; a `generation` mismatch; a missing journal. In each, the gap is recorded where history was lost, and the derived state converges.</li><li>**A crash at every commit boundary.**</li><li>**A source file edited while a sync runs** (by Obsidian or by hand): the sync re-checks each file's signature after reading it. A file that changed is read again or left for the next sync; it is never recorded half-old, half-new.</li><li>**Two concurrent indexers:** one waits on the file lock; the result equals a single run.</li><li>**A second open version for one occurrence is refused.**</li><li>The backup files have `0600` permissions</li></ul> |
| **Rollback** | Revert the code and **keep** `data/journal.db` and its backups. 0.9.1 ignores them, and reinstalling M1c later continues the history with a recorded gap. Deleting `journal.db` destroys history that nothing can rebuild, so it is never part of a rollback; it would be a separate, explicit owner decision. `brain.db` and the vault are unaffected |
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
| 22 | start M3 only with evidence of need (a class of eval misses that typed claims would fix) | yes (suggested by the second-model review); **open, your call** | M3 |

## 4. Readiness

**READY FOR M1** (2026-11-22).
- **The design is ready.** Revision 2.3 resolved the last three concerns, each with regression tests.
- **The owner's decisions are taken** (section 0).
- **M0 is complete.**

One caveat comes with it: the corrected baseline, 298 and 345 of 443, rests on labels that AI reviewed and the owner accepted without checking. No person has validated them.

**Ready is not authorised.** M1a starts only when the owner ticks its approval (section 2). M1b and M1c each wait for their own approval after that.

**The second-model review's conditions are now part of each package's acceptance tests** (section 5). M1a may run on an isolated copy as soon as it is approved. The live cutover happens only after those tests pass on the copy.

## 5. Second-model review (2026-11-22)

An independent review by a different model family checked these documents. Each finding was verified against the documents, the code and the live copy, then folded in:

| # | Finding | Verified | Where it is now |
|---|---|---|---|
| 1 | M1a's rollback would hide relations written after the migration | Yes: the audit kept the table read-only | M1a: the table stays written until M3; a rollback test after new writes |
| 2 | A "delete `brain.db`" test can destroy data that is not in the vault | Partly: 0 `sole` facts, but events (1,191) and metrics (276) | M1a: destructive tests on copies only; `brain doctor` counts what a rebuild would not restore |
| 3 | The migration is not proven to preserve relations exactly | Yes | M1a: a field-level round trip, refused characters, the date mapping (decision 21), relation recall per entity |
| 4 | M1b's `--apply` spans two stores with no crash plan | Partly: vectors are derived | M1b: resumable steps, a crash test after each, rollback by rebuild |
| 5 | `journal.db` can lose its last commit on power loss | Yes: no durability setting was specified | M1c: `synchronous=FULL`, the `sync_seq` marker, a lost-commit test, rollback keeps the file |
| 6 | The ledger allows two open versions of one occurrence | **Reproduced** | Audit L.1: a unique index. The prototypes pass with it (150 random sequences, L1–L11) |
| 7 | Stable ids survive a moved root, not a renamed one | Already accepted (decision 2) | Unchanged; `brain doctor` detects a rename |
| 8, 9 | The eval does not establish answer quality, and the statistics describe label changes only | Yes | `docs/M0_BASELINE.md`, section 9: regression smoke tests for M1–M3; M4 needs a person-checked benchmark |
| 10 | Backups need permissions, atomic copies and a tested restore | Yes | M1c scope and tests |
| 11 | Hook-captured messages could become trusted claims | Partly: extracted claims stay candidates | Audit M3 precondition: captured messages never feed derived claims |
| 12 | M2–M7 may be more than the data needs | Owner's call | Decision 22, open |
| 13 | The docs overstate rebuildability, and the M0 wording | Yes | M1a: README correction; M1c: `journal.db` never deleted; M0 wording fixed |

**Second round (the same day).** The reviewer accepted the round-one corrections and the partial verdicts on findings 2, 4, 7 and 11. It found four more problems, all now folded in:
1. `BEGIN IMMEDIATE` cannot span two commits. Fixed with an outer per-agent file lock (M1c).
2. Decision 21 mixed recording time with valid time. Revised: `created_at` is kept as `recorded:` provenance only (M1a).
3. The mirror had no rule for hand-removed or edited lines. Fixed: `relations.md` is append-only until M3, and removals are reported (M1a).
4. The `sync_seq` marker handled only one direction. Fixed: a `generation` id and a rule for every state (M1c).

It also asked that M1b's resume check its manifest against the current sources, now in M1b. Its verdict: implement M1a on an isolated copy; cut over live only after the acceptance tests pass.

**Outcome (round three).** The reviewer found no remaining design-level blockers. It added one acceptance test: a source file edited while a sync runs, now in M1c.

| Package | Agreed design verdict | Conditions |
|---|---|---|
| M1a | Ready for implementation on an isolated copy | The live cutover needs a field-level round trip, recall parity, crash recovery, a verified backup, and a rollback after new writes |
| M1b | Design accepted | Implemented after M1a's acceptance. The live cutover needs manifest validation, crash and resume, metadata preservation, vector recovery and a verified rollback |
| M1c | Design accepted | Implemented after M1b's acceptance. It needs to verify the cross-process lock, both mismatch directions, generation and sequence recovery, concurrent indexers, backup and restore, and power-loss durability |

**Agreed position:**
- Revision 2.3 is frozen with these corrections, and the order stays M1a → M1b → M1c.
- Each live cutover needs the owner's separate approval after its acceptance tests pass.
- The 298 and 345 of 443 baseline is a regression smoke test, not evidence of answer quality.
- M2–M7 stay unauthorised, each subject to demonstrated need.

The reviewer did not see these final edits; it judged them from a description of the changes.

**Round four (M1a implementation, the same day).** The reviewer checked the implementation report against the agreed conditions. It asked for four changes, all now made:
- default-scope ranking preserved: 75 of 75 identical to 0.9.1
- a bootstrap enforced in code
- tests for a crash between the vault line and the mirror row, and for a restore from the backup
- an incomplete migration while unrepresentable rows remain

Its final position: **M1a is accepted for an owner-authorised, verification-gated live cutover. After a successful cutover, M1b may be implemented on an isolated copy under its own authorisation.** M1b's live migration, M1c's implementation and M2–M7 remain separately gated. The reviewer judged the reported evidence; it did not read or run the code.

