# Audit revision 2.2: technical change log and validation report

**Date:** 2026-11-21; section 4 added 2026-11-22. **Applies to:** `docs/KNOWLEDGE_ARCHITECTURE_AUDIT.md`, revisions 2.2 and 2.3, and `docs/M0_BASELINE.md`.
**Authorisation:** architecture review, documentation and isolated validation only.

What was **not** done:
- M1–M7
- any change to the live agent, its database or the Obsidian vault
- any migration on live data
- any model or package download
- any outside LLM call by brain-core
- any commit or push

**Privacy:** this file holds counts and scores only. Record text, names and the label packets stay under `local/audit-m0/`, which git ignores.

Labels:

| Label | Meaning |
|---|---|
| **[V]** | verified in the repository |
| **[T]** | run in a throwaway prototype, with the result below |
| **[P]** | proposed, not implemented |
| **[A]** | an assumption |
| **[Q]** | an open question |

## 1. Verdict

**NOT READY FOR M1.**
- **The design is ready.** Every P0 and P1 issue below is resolved and validated in prototypes.
- **Two gates the owner set are still open:**
  1. **M0 is not complete.** No person has reviewed the 104 labels. An AI-assisted pre-review exists, but it is kept apart and is not validation.
  2. **M1 needs the owner's decisions**, at least audit R items 1–3, 14 and 19.

**Update, 2026-11-22: both gates are closed, and the verdict is now READY FOR M1.**
- **The decisions are taken.**
- **M0 is complete.** The owner waived the human review and accepted AI answers to the label packet unchecked, so the labels are AI-reviewed, not human-validated.

See `docs/M1_DECISION_CHECKLIST.md`, sections 0 and 4, and `docs/M0_BASELINE.md`, section 9. Each M1 package still needs its own approval.

## 2. Technical change log

### P0-01: Evidence model and SQLite schema inconsistency

| | |
|---|---|
| **Original problem** | The pydantic `Evidence` carried `valid_from`, `valid_to`, `timeless`, `stated_date`, `recorded_at` and `event_date`; `claim_evidence` did not carry them all. Dates lived in `record_times`, keyed by record id, so two copies of one text shared them |
| **Root cause** | Stated dates were modelled per record (as `record_meta.md` is keyed today) while evidence was modelled per occurrence |
| **Correction** | Dates are resolved per occurrence (occurrence meta line, else record line, else the rule's default) and stored on the evidence row itself. `record_times` keeps the raw meta lines for the dirty set only. One field set in model and table |
| **Foreign keys and constraints** | <ul><li>Six foreign keys where safe.</li><li>Three places with none, on purpose: evidence is the source of claims; a rejection must outlive its evidence; a redirect may name an entity, claim or record.</li><li>`CHECK`s for every enum, for nullability pairs (one object; a literal needs a datatype), for date order, for accepted-not-unverified, and for retracted-is-rejected</li></ul> |
| **Affected modules** | `knowledge/model.py`, `derive.py`, `reconcile.py`, `stores/vault.py` (occurrence meta lines), migration `009_claims.sql` |
| **Schema implications** | `claim_evidence` PK `(claim_id, occ_id, rule)` with the full occurrence and resolved dates; `record_times.occ_scope`; FKs as listed |
| **Compatibility** | `record_meta.md` unchanged for existing lines. The occurrence form `<rid16>@<source>#<n>` is ignored by 0.9.1's `_META` pattern **[V]** |
| **Validation [T]** | `rev22_check.py`, run against the audit's own code blocks and SQL. <ul><li>9 models against 9 tables, field by field</li><li>15 enum lists equal to their `CHECK` lists</li><li>round trips through SQLite</li><li>foreign keys enforced: an orphan refused, a cascade on delete, a deferred merge chain, a dangling merge refused</li><li>invalid states refused (accepted + unverified, retracted + accepted, a repeated occurrence, a move without `moved_from`, an interval ending before it starts)</li></ul> Inserts, edits, deletes and rebuilds are tested in SQLite by `reconcile22.py` (P0-03) |
| **Remaining risks** | The dirty-set optimisation is not prototyped: the prototype recomputes the whole computed tier. M3's T8 must prove the two equal |

### P0-02: Transaction-time identity too coarse

| | |
|---|---|
| **Original problem** | `record_ledger` keyed by exact-text hash: a later independent copy could inherit the first copy's earlier recording time |
| **Root cause** | Content identity was used as occurrence identity |
| **Correction** | Five identities, plus redirects: <ul><li>**content:** `record_id`</li><li>**source:** `source_id`, store-relative</li><li>**occurrence:** `(source, record, ordinal)`</li><li>**version:** exact-text hash</li><li>**claim:** canonical key</li></ul> Presence intervals are kept per version at an occurrence. A time carries over only through an unambiguous move (one copy left, one arrived, same text, same sync pass); everything else is new: late, never early. Strategies compared in audit F.3: content hash, `(path, line)`, `(source, line)`, Obsidian block ids, ordinal. The ordinal one was chosen |
| **Affected modules** | `knowledge/ledger.py`, `stores/index.py`, `remember.py` (`via=write`) |
| **Schema implications** | `record_ledger` PK `(occ_id, content_hash, seen_from)`; `CHECK (via='move') = (moved_from IS NOT NULL)` |
| **Compatibility** | content identity (`record_id`) unchanged; deduplication by content still works |
| **Validation [T]** | `ledger22.py`, L1–L11: write, backdated line, edit, duplicate in one file, copy (**no inheritance**), unambiguous move (inherits), ambiguous move (no inheritance), delete and restore, rebuild, database loss, backup restore. In SQLite (`reconcile22.py`): a copy is recorded one hour later than the original, not at its time |
| **Remaining risks** | Inserting an identical copy *above* an existing one swaps which physical line owns the older time. Deterministic, harmless (identical text), documented. Moves across separate sync passes or stores count as new |

### P0-03: Rebuild guarantees and transaction-history durability

| | |
|---|---|
| **Original problem** | Rebuilds kept the ledger, but deleting `brain.db` would destroy it, and `README.md:507` tells users that deleting the SQLite index is safe **[V]** |
| **Root cause** | Derived data and history shared one file |
| **Correction** | Options A–D compared (audit L.5): <ul><li>A: a Markdown journal in the vault</li><li>**B: a separate SQLite file (chosen)**</li><li>C: the same file with a backup</li><li>D: git</li></ul> History lives in `data/journal.db`: <ul><li>written first, idempotently</li><li>then `brain.db` in one transaction, with the signatures last</li><li>a daily journal backup and a merge-restore</li></ul> Behaviour is defined for `brain index`, `--rebuild`, deletion and corruption of either file, vault restoration, backup restoration, and a move to another computer |
| **Affected modules** | `storage/journal_migrations/`, `knowledge/journal.py`, `stores/index.py`, `cron.py` (backup), `cli/main.py` (`brain journal restore`), `status.py`, `brain doctor` (integrity checks) |
| **Schema implications** | `journal.db`: `record_ledger`, `ledger_gaps`, `derivation_journal`. `brain.db`: derived tables, plus `events` and `metrics` as best-effort logs (unchanged from 0.9.1) |
| **Compatibility** | the README's "delete it and it is rebuilt" stays true for `brain.db`; `events` and `metrics` behave as today |
| **Validation [T]** | `reconcile22.py`, on two real SQLite files: <ul><li>150 random sequences of add, delete, edit, copy and move, with injected crashes between the two commits, rebuilds and `brain.db` deletions</li><li>after each sequence: incremental state equals a fresh rebuild; a rebuild and a deletion add no journal row; the journal reconstructs `claim_evidence` exactly at every past sync; at most one open interval per version</li><li>a planted bug (a journal that never closes changed rows) is caught</li><li>named scenarios: copy, `brain.db` deleted, `brain.db` corrupted (detected, rebuilt), a crash between commits (converges), the agent folder copied elsewhere (same claims and times)</li></ul> |
| **Remaining risks** | <ul><li>Backup scheduling and restore are prototyped as logic (L11), not as a `cron` job.</li><li>`journal.db` corruption recovery is proposed, not run.</li><li>`events` and `metrics` remain lost when `brain.db` is deleted, as today.</li><li>Locator churn: an inserted line versions every row below it (R item 18)</li></ul> |

### P1-01: G11, path-dependent record identity

| | |
|---|---|
| **Original problem** | 2,805 of 6,016 live records hash the absolute folder path into their id (`notes.py:29` → `vault.py:796`) **[V]** |
| **Root cause** | `NotesStore` passes `str(p)` as the record's source for both id and display |
| **Correction** | <ul><li>The id hashes `<store>:<root name>/<path>#heading`.</li><li>The root name is an optional `name:`, defaulting to the folder name.</li><li>Two roots with the same name are a config error.</li><li>The displayed path is unchanged, so citations look the same.</li><li>Vault ids are unchanged.</li><li>Migration (M1b): `was:` meta lines, a vector remap, a translation of the eval labels, and `brain doctor` detection of a renamed root</li></ul> |
| **Affected modules** | `stores/notes.py`, `config.py`, `stores/vault.py`, `stores/vectors.py`, `cli/main.py`, `tests/eval/` |
| **Schema implications** | `record_links.kind = 'was'`; `identity_redirects.cause = 'id-scheme'` |
| **Compatibility** | A 0.9.1 reader ignores `was:` lines. A downgrade detaches notes and archive keys, exactly as today. Reversible: delete the `was:` lines and rebuild `brain.db` |
| **Validation [T]** | <ul><li>`g11_proto.py` (brain-core's own `knowledge_records`): G11-T1 a moved root keeps ids; T2 a renamed root with `name:` keeps them; T3 a rename without `name:` changes them (detection itself is proposed); T4 a file moved inside a root re-keys its knowledge records; T5 keys, a `supersedes` link and vectors follow a migration</li><li>`g11_eval.py`, on two fresh isolated copies of the frozen snapshot, with the eval labels translated:<ul><li>(a) new ids only: S0 295 = 295 and S2 346 = 346, **0 fixed, 0 broken: retrieval is preserved question by question**</li><li>(b) also the live agent's 588 search-key lines attached via `was:`: S0 298 (12 fixed, 9 broken, p 0.66; absent 38 → 36, identifier 1 broken) and S2 347 (7 fixed, 6 broken, p 1.0)</li></ul></li></ul> |
| **Found while validating** | The frozen snapshot's 588 search-key lines for notes and archive records are keyed by **live**-path ids, so they never attached in M0's or the README's eval. 182 of the 446 questions name such records |
| **Remaining risks** | Fixing G11 moves about 20 questions with no significant net change, and adds two false answers on absent questions. **Re-baseline after M1b** (R item 19); do not gate M1b as an improvement. Knowledge pages renamed inside the vault still re-key (R item 13) |

### P1-02: Temporal semantics and historical correctness

| | |
|---|---|
| **Correction** | Validity is decided by votes per evidence row, and is three-valued: <ul><li>a stated start says "not before"</li><li>a row's own date says only "held then"</li><li>a stated end says "not from"</li><li>an undated row speaks for today only</li><li>a link end closes the period</li></ul> TRUE when someone says true and nobody false; FALSE the reverse; otherwise UNKNOWN (disagreement or silence). `as_of` and `known_at` are defined separately and together: `known_at = K` derives only from the rows the journal says existed at K |
| **Validation [T]** | <ul><li>The review's twelve cases, each with a determined answer (audit J.1): no known start; explicit start; explicit end; recorded today but valid last year; overlapping claims (a conflict from 11-20); contradictory claims with unknown starts (UNKNOWN in the past, a conflict only from today); future-effective; retracted (rejected, evidence kept); valid again after superseded; evidence deleted from one source but kept in another; two records with different dates; discovered after it ended (true in March, false in August, not known on 05-01)</li><li>23 further results (E1–E9)</li><li>the SQL TRUE predicate equals `Period.at` on 2,000 (claim, day) pairs</li></ul> |
| **Remaining risks** | Partial dates are refused (none in the live vault); the cost of an UNKNOWN window when sources disagree on dates (R item 7) |

### P1-03: Entity merges and claim identity

| | |
|---|---|
| **Correction** | <ul><li>Claim ids are computed on canonical keys.</li><li>`identity_redirects` keeps every retired id: claims (`merge`, `rename`, `merge+rename`), entities (`merged_into`), records (`id-scheme`).</li><li>Reviews keep their key as written and are ordered by ledger time.</li><li>Disagreeing merged reviews and orphaned acks are reported.</li><li>Conflicts are recomputed; two different assertions are never merged.</li><li>AI-suggested equivalences are only inbox suggestions</li></ul> |
| **Validation [T]** | A merge plus a rename joins two claims and keeps both evidence rows; the old id is redirected with cause `merge+rename`; the later review applies and the disagreement is reported; the ack follows its pair. **Undo:** a rebuild without `merged_into` restores three claims, each with its own evidence and its own review as written |
| **Remaining risks** | Alias-change re-resolution is proposed, not prototyped. A review written after a merge stays with the survivor's claim after an undo |

### G-01: Graph retrieval completeness

| | |
|---|---|
| **Correction** | The walk returns a set of truncation reasons: `seeds`, `frontier`, `scan`, `fan`, `hub`, `edges`, and `depth` (edges past the last hop) |
| **Validation [T]** | <ul><li>Random graphs, random limits, compared with an exhaustive walk: the bounded walk never returned an extra edge. Every graph where it left edges out reported a reason (46 and 50 such graphs in two runs of 300 drawn examples, 292 usable).</li><li>The real graph: bounded equals exhaustive from all 75 entities; p50 0.09 ms, max 0.8 ms, traversal only.</li><li>Named cases: disconnected graphs, a missing entity, an alias collision, multiple seeds, conflicting claims, a historical query, a ring longer than the depth.</li><li>The synthetic hub benchmark (unchanged): 200 edges, 363 rows read, about 1 ms. It is kept apart from end-to-end recall, which M4 measures</li></ul> |
| **Remaining risks** | A historical `as_of` on a hub is cut by the scan window by design, and reported |

### E-01: M0 evaluation

| | |
|---|---|
| **State** | **Not complete.** The scores are **provisional** |
| **Done** | <ul><li>The frozen dataset and results are preserved and checksummed (`local/audit-m0/MANIFEST.json`); the frozen question file is byte-identical to the copy M0 used.</li><li>No earlier run was overwritten; new runs have new file names.</li><li>The provenance of the labels is documented (`docs/M0_BASELINE.md`).</li><li>An AI-assisted pre-review of the 104 items is in `local/audit-m0/ai_review/label_review_ai.csv`, kept apart from the human `label_review.csv`, whose verdict column is still empty.</li><li>Questions affected by path-dependent ids: 182.</li><li>Paired results are reported, not only totals.</li><li>Memory was measured where it can be.</li></ul> |
| **AI-assisted pre-review (not human validation)** | <ul><li>58 correct, 40 incomplete, 4 ambiguous, 2 incorrect, 0 unverifiable.</li><li>Every absent item was judged correct.</li><li>Most "incomplete" verdicts name an archive copy or a same-day note left out of the gold. The four agents applied that rule differently (one ignored archive copies), which is itself a reason the human review is needed.</li><li>The agents also found that the catalog the labels were drafted from holds 5,394 unique records against the 5,821 that 0.9.1 indexes</li></ul> |
| **Remaining** | the human review; a re-scored baseline; about 40 multi-hop and 40 temporal questions before M4; optionally S3, with approval |

## 3. Validation report

### 3.1 Verified repository behaviour [V]

- `README.md:507` says the SQLite index can be deleted and rebuilt.
- `notes.py:29` → `vault.py:796`: notes and archive ids hash the absolute path.
- `vault.py` `_META` matches only `- <16 hex> |`.
- `storage/db.py` sets WAL and `foreign_keys = ON` and uses autocommit.
- `vault.py:398`: undated lines carry no date (0.9.0).
- 0.9.1 code reproduces the README's keyword (295) and hybrid (346) figures on the frozen snapshot.
- The live agent runs 0.9.1; its vault is not a git repository.

### 3.2 Prototype behaviour that was run [T]

| Prototype (under `local/audit-m0/prototypes/`) | Result |
|---|---|
| `rev22_check.py` (the audit's own code and SQL) | all 11 sections pass: consistency, round trips, T10, temporal examples, T11, re-keying, predicate agreement, foreign keys, the twelve cases, undoing a merge |
| `ledger22.py` | L1–L11 pass |
| `reconcile22.py` | 5 scenarios and 150 random sequences pass; a planted journal bug is caught |
| `traversal_proto.py` (Python 3.12.13 and 3.14.6, SQLite 3.53.1) | bounds, truncation reasons, query plans, VM-step bound |
| `traversal_complete22.py` | the completeness property, the named cases, the real graph |
| `g11_proto.py` | G11-T1 to T5; live sizing: 2,805 records, 588 `was:` lines, 633 vectors, 0 links |
| `g11_eval.py` | (a) 0 fixed / 0 broken, (b) as above; the `claude` tripwire stayed empty |

### 3.3 Proposed, not implemented [P]

Everything in M1–M4:
- the dirty-set optimisation
- alias re-resolution
- the root-rename detection in `brain doctor`
- `journal.db` corruption recovery
- backup scheduling
- `known_at` over reviews and meta lines (the journal kinds `review`, `link` and `time`; only `evidence` was prototyped)
- the occurrence meta syntax

### 3.4 Assumptions [A]

- Two-hop traversal stays in milliseconds at about 50k edges: the synthetic 310k-claim hub supports it.
- A daily journal backup is frequent enough.
- On Apple Silicon `ps` does not count the embedding model's GPU memory, so the embed worker's footprint (58 MB RSS by `ps`) is **not** a valid measurement. The README's 1.6 GB is unverified here.

### 3.5 Open questions [Q]

Audit R items 1–19. M0 left open: who reviews the labels, and whether S3 may send data to Anthropic.

### 3.6 Side effects of this work

- **Writes:** everything was written under `local/audit-m0/` (untracked) and `docs/`. Nothing went to the live agent or the vault.
- **Reads of database files:** the frozen eval database and the live database were opened read-only (`mode=ro`). A reader of a WAL database updates its `-shm` index file. The frozen database's `-shm` shows today's time, while its data file and WAL are unchanged since 2026-11-14 **[V]**. For frozen files, future copies should use `immutable=1`.
- **Temporary files:** a short symlink, `~/.bcm0`, was used for the embed worker's socket path and has been removed.

## 4. Revision 2.3 addendum (2026-11-22): concerns A, B and C

Each concern was reproduced first against the unmodified 2.2 prototypes, kept as `local/audit-m0/prototypes.before-2.3/`. Only then was the code corrected. Every regression test below was mutation-checked: putting the original bug back makes it fail.

### A. Timeless claims and supersession: confirmed, corrected

| | |
|---|---|
| **Reproduction [T]** | A claim with one `valid: always` row and a superseding record starting 2026-12-10. `Period.at(2026-12-11)` gave `true`, and so did the SQL predicate, although `true_to` was correctly 12-10. The timeless check returned before the link end was read. That contradicts J.1: "a link end ends the period for every row" |
| **Correction** | <ul><li>`Period.at` checks the link end first.</li><li>A `valid: always` row is one vote ("true on every day"), not an override, so a stated start in another row makes the days before it UNKNOWN, as the votes rule says.</li><li>The period summary gains `undated` and `stated`, and `Period.true_on` and the SQL predicate (H.3) now equal `at() == "true"` exactly</li></ul> |
| **Tests [T]** | <ul><li>Checker section 12: false on 12-10 and 12-11, true on 12-09 and in 1999, in Python and SQL; an always-row plus `valid: 2026-11-10` elsewhere is unknown on 11-01 and true on 11-10.</li><li>Section 14, a property over random periods (every kind of row, random link ends, random day and today): the summary and the SQL predicate equal `Period.at` on 815 periods.</li><li>**Mutation:** the old timeless shortcut makes the checker fail</li></ul> |
| **Schema** | `claim_periods` + `undated`, `stated` |

### B. Undated claims and future conflicts: confirmed, corrected

| | |
|---|---|
| **Reproduction [T]** | Two undated claims on one functional (subject, predicate, role). The conflict was stored from today (`2026-11-22`) with no end, while both claims are UNKNOWN tomorrow and in the past. Derived again "the next day", the same vault gave `overlap_from = 2026-11-23`: the stored computed tier changed with the calendar |
| **Correction** | <ul><li>Conflicts carry a `scope`. `interval` is a window where both are TRUE on dated evidence; `current` is a window where an undated row is needed, active only on whatever day is today (`Conflict.active_on`).</li><li>`derive()` no longer takes a date: the computed tier is a pure function of the vault again.</li><li>A pair can have several conflict rows (`seq`), one per window, so claims with several periods are covered.</li><li>`Claim.disputed_on(d, today)` is what recall shows</li></ul> |
| **Tests [T]** | <ul><li>Checker section 13: one `current` conflict, active today, not tomorrow, not on 2026-06-01, and active tomorrow once tomorrow is today; the rows are identical on every derivation.</li><li>Section 14, a property over 400 random claim pairs (dated, undated and timeless rows, stated starts and ends, link ends): a conflict is active on (d, today) exactly when both claims are TRUE.</li><li>**Mutation:** the old today-to-forever window makes the checker fail</li></ul> |
| **Schema** | `claim_conflicts` + `scope`, `seq`; PK `(claim_a, claim_b, seq)` |

### C. Duplicate occurrence identity: confirmed; detection specified and tested

| | |
|---|---|
| **Reproduction [T]** | Two identical lines with their own `valid_from`, `valid_to` and `event_date`, set by occurrence lines `#1` and `#2`. Inserting an identical copy above them moved the metadata: the new line took `#1`'s dates, the original first copy took `#2`'s, and the original second copy lost its own. No warning |
| **Why it cannot be disambiguated** | An occurrence is "the k-th copy of this text in this source". By content alone, a copy inserted above cannot be told from a copy appended below |
| **Safe handling** | <ul><li>A per-copy meta line applies only while the copies of that text in that source are unchanged since the line's ledger time.</li><li>Otherwise it is reported (`occurrence_meta_ambiguous`; `occurrence_meta_dangling` when copy k no longer exists) and **not applied**; the record-level line applies.</li><li>The owner re-anchors by rewriting the meta line, or by making the copies distinct</li></ul> |
| **Tests [T]** (`occurrence_meta23.py`) | <ul><li>C1: two copies each resolved correctly.</li><li>C2: a copy inserted above. 2.2's rule shown moving the metadata; 2.3 reports both lines and applies only the record-level meta to all three copies.</li><li>C3: a copy appended below, also reported.</li><li>C4: a copy deleted (dangling plus ambiguous).</li><li>C5: rewritten meta lines apply again.</li><li>C6: unrelated edits around the copies, still applied.</li><li>C7: the k-th copy keeps the time the vault first held k copies, never earlier than the truth</li></ul> |
| **Remaining risk** | Owners who give two identical lines different dates must re-anchor after any change to those copies. Strict on purpose (R item 20) |

### Re-run of the whole suite after the corrections [T]

| Prototype | Result |
|---|---|
| `rev22_check.py`, on the audit's own code and SQL | 14 sections pass |
| `reconcile22.py` | 150 random sequences: incremental equals rebuild, with `derive()` now date-free |
| `traversal_proto.py`, Python 3.12 and 3.14 | passes |
| `traversal_complete22.py` | completeness property and real graph pass |
| `ledger22.py` | L1–L11 pass |
| `occurrence_meta23.py` | C1–C7 pass |
