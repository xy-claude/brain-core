# M0 baseline: what brain-core measures before the knowledge layer

**Date:** 2026-11-21. **Code:** brain-core 0.9.1, commit `55038ca` (the version the live agent runs too).
**Plan:** `docs/KNOWLEDGE_ARCHITECTURE_AUDIT.md`, section P, milestone M0. M0 only measures: no schema change, no migration, no change to how brain-core behaves.
**Privacy:** this file holds counts and scores only. The questions, record text, predicate and entity names, and the label-review packet stay under `local/audit-m0/`, which git ignores.

## Summary

| Question M0 had to answer | Answer |
|---|---|
| Does 0.9.1 still score what the README publishes? | **Yes.** Keywords find 295 of 446, the README's 0.9.0 figure. Against the 2026-11-14 run: 7 fixed, 4 broken, McNemar p 0.55. With vectors: 346, also the README figure (56 fixed and 5 broken against keywords, p < 0.001) |
| How big is the graph the plan would build on? | **Tiny.** 82 relations, 43 predicates (31 used once), 75 entity names, highest degree 19, nothing written since 2026-11-02 |
| Would decisions feed it? | **Not today.** None of the 81 decisions has a `[[link]]` in its fields, so rule `decision-field/1` derives 0 claims. 313 records do carry wikilinks, 301 of them knowledge pages |
| Do the traversal limits bind? | **No.** A 2-hop walk from each of the 75 entities finds at most 49 edges, reads at most 74 rows, takes at most 0.8 ms, and never truncates. `hub_degree` 200 and `fan` 20 are safety limits here, not tuning |
| Is a file watcher needed? | **No.** A sync with no change takes 5 ms; a full parse of every markdown store takes 2.5 s |
| Is recall fast enough? | Snapshot, keywords: p50 49 ms, p95 74 ms. **Live** copy, keywords plus transcripts: p50 73 ms, **p95 110 ms**, already above the audit's 100 ms gate (O.5). The gate needs restating against this baseline |
| Are the labels trustworthy? | **Not checked yet.** A 104-question review packet is ready for a person (section 2) |
| Anything wrong that M0 was not looking for? | **Yes, two things.** Notes and archive record ids embed the absolute folder path (audit G11). The live agent has a current vector for only 17% of its records (section 5) |

## 1. Baseline recall

446 labelled questions on the frozen eval snapshot of 2026-11-14, the one the labels were written against, with `--today 2026-11-14`. A hit means a gold record is in the top 10.

| Slice | n | S0 keywords + keys | S2 + vectors (RRF) | S3 + judge |
|---|---:|---:|---:|---|
| reworded | 160 | 83 | 114 | not run |
| real | 11 | 8 | 10 | not run |
| same | 20 | 20 | 20 | not run |
| update | 37 | 24 | 27 | not run |
| temporal | 53 | 42 | 46 | not run |
| multi (every gold) | 53 | 29 | 37 | not run |
| absent (flagged) | 57 | 38 | 38 | not run |
| identifier | 55 | 51 | 54 | not run |
| **all** | **446** | **295** | **346** | 398 published for 0.9.0 **[M]** |

| Error (all 446) | S0 | S2 |
|---|---:|---:|
| False answer: absent, not flagged | 19 of 57 | 19 of 57 |
| False refusal: answerable, flagged | 104 of 389 | 104 of 389 |
| Missed with no warning | 70 of 389 | 42 of 389 |
| Median latency per question | 49 ms (p95 74) | 152 ms (p95 204) |

- **S1 (vectors alone)** has no switch in `run_gold.py`. The README's earlier figure was 89 of 143 **[M]**.
- **S3 was not run.** The judge sends each question, and up to 50 records of up to 700 characters, to Anthropic. That needs the owner's explicit approval, and M0 was authorised only with no outside LLM calls. The published 0.9.0 figure is quoted instead.
- **S2 agrees with history too:** 346, the README's 0.9.0 vectors figure. Against S0 it fixes 56 questions and breaks 5 (reworded +31, multi +8, p < 0.001 overall). Vectors do nothing for the absent slice (38 of 57 flagged either way), as the README says: a vector search returns its nearest records for any question.
- **S0 agrees with history.** 295 against the 2026-11-14 keyword run's 292: 7 questions fixed, 4 broken, p 0.55. That is no significant change, and it matches the README's "keywords 295 against 292".

## 2. Label review: prepared, waiting for a person

- **The sample.** `local/audit-m0/label_review.md` and `label_review.csv` hold 104 questions: 24 reworded, 6 real, 6 same, 14 update, 14 temporal, 14 multi, 14 absent and 12 identifier. 47 of them are baseline misses, because a wrong label usually shows up as a false miss.
- **What each entry shows:** the question, its gold records with their text, and today's keyword top 10.
- **The reviewer marks** each one *right*, *wrong*, *incomplete* or *ambiguous*, and adds any corrected gold.
- **Status.** Not done. Until it is, every score above, and every score in the README, rests on labels written by a model. The change rate this review finds sets how much weight they carry (audit ADR-010).

## 3. Census of the live agent (copy taken 2026-11-21)

**Records (distinct ids).** 6,016 in total:

| Store | Kind | Records |
|---|---|---:|
| vault | session note | 2,684 |
| vault | fact | 261 |
| vault | knowledge | 105 |
| vault | decision | 81 |
| vault | pattern | 50 |
| vault | correction | 26 |
| vault | raw | 4 |
| archive | knowledge | 2,137 |
| notes | knowledge | 668 |

The snapshot of 2026-11-14 held 5,821.

| Measure | Value | What it settles |
|---|---|---|
| Relations | 82 rows; 43 predicates, 31 of them used once; no spelling variants after normalising; 75 entity names, no case variants; no self-loops; written 2026-04-10 to 2026-11-02 | R item 10: the predicate vocabulary is small and ad hoc. Ontology v1 maps 43 names, most of them by hand |
| Degree (subject or object) | max 19, p99 15, p90 4, median 1; none above 20 | R item 5: the defaults never bind; keep them as safety limits |
| Records with a `[[wikilink]]` | 313: 301 knowledge, 9 facts, 3 notes | The deterministic graph source in M2 is knowledge pages |
| Decisions with a link in their fields | 0 of 81 | `decision-field/1` derives nothing until decisions link entities (M2 alias matching, or guidance in `04-memory.md`) |
| `#tags` | 18 records | Minor |
| Undated facts and patterns | 64 of 311 (21%) | `as_of` in the past answers *unknown* for a fifth of standing facts (J.1, by design) |
| Month-only dates | 0 records | R item 3: refusing them in v1 costs nothing |
| One id in more than one place | 64 ids: 23 in two different files, the rest twice in one file | Review point B is real: evidence identity needs `source_path` and `line` |
| Vault under git | No | R item 11: the git option for `recorded_at` does not apply; the ledger is the only transaction clock |
| v0.1 tables `decisions`, `reflections`, `hsam_days` | 0 rows each | R item 12, for this install: safe to drop later |
| Transcript index | 17,803 rows from 19 files | — |
| Journal events | 1,191 (capture 653, `brain_remember` 259, `recall_miss` 182, brief 51, checkpoint 18, `session_start` 12, lessons 11, `session_end` 5) | — |
| `brain.db` | 58.6 MB | — |

## 4. Performance

| Measure | Value |
|---|---|
| Full parse of every markdown store (vault, notes, archive; record index emptied) | 2.5 s |
| First sync of the copied vault (new paths, notes and archive unchanged) | 1.3 s |
| Sync with no change (median of 5) | 5 ms |
| Recall, keywords, snapshot (446 questions) | p50 49 ms, p95 74 ms, max 104 ms |
| Recall, keywords, **live** copy with transcripts (446 questions) | p50 73 ms, **p95 110 ms**, max 160 ms |
| Recall with vectors, snapshot | p50 152 ms, p95 204 ms, max 371 ms |
| Embedding the snapshot from scratch (5,821 records, Apple GPU) | 5,805 records in 597 s (about 10 minutes) |
| H.3 walk over the real graph (all 75 entities, 2 hops) | ≤ 49 edges, ≤ 74 rows, ≤ 100 queries, ≤ 0.8 ms (median 0.09 ms), 0 truncated |
| H.3 walk on the synthetic 10,000-neighbour hub (audit prototype) | 200 edges, 363 rows, about 1 ms |

## 5. Findings M0 was not looking for

1. **Notes and archive ids depend on the absolute folder path (audit G11).**
   - What happens: `NotesStore` hashes the full path into each record id (`notes.py:29` → `vault.py:796`). The 2,805 notes and archive records change id when their folder moves.
   - How it showed: a copy of the eval snapshot "lost" 64 gold records this way.
   - What it breaks: search keys in `record_meta.md`, vectors and `supersedes` links all key on those ids.
   - The fix: hash the path relative to the store's root. That is a migration of existing keys, so it is the owner's call, and the natural place is M1 hygiene. M0 worked around it by reading those folders in place, read-only.
2. **The live agent's vector index is 83% empty.**
   - What happens: 4,976 of 6,016 records have no vector for their current text. Recall embeds at most 16 a call, so hybrid recall on the live agent sees about a sixth of memory, and the README's hybrid gains do not hold there.
   - The fix: `brain index` on the live agent fills it, about five minutes on this machine.
   - Not done here, because M0 does not touch the live agent. It is the owner's call.
3. **A long `BRAIN_EMBED_HOME` silently disables vectors.**
   - What happens: macOS limits a Unix socket path to 104 bytes. Past it the embed worker cannot bind, and recall answers from keywords. It does say `degraded`, so it is not silent to the agent, but it is easy to miss in a script.
   - The fix: a check in `brain doctor`, or a shorter socket name. Low priority.

## 6. What this changes in the plan (for the owner to decide; nothing done)

| Item | Recommendation |
|---|---|
| M1 | Proceed as planned, and add the G11 id fix and a `brain index` reminder for stale vectors. Starting the ledger in M1 matters more than M0 expected: the graph is nearly empty, so the knowledge layer will be built mostly from records written after M1 |
| M2–M4 | The value of the graph net depends on M2's deterministic links (knowledge pages, entity notes, alias matches in decisions), not on the 82 existing relations. Before building M4, draft the relation and multi-hop slices (O.2) and measure how many of their answers any graph could reach |
| O.5 gate | Restate "p95 under 100 ms with keywords" as "no worse than this baseline's p95 + 10%": live p95 is 110 ms today |
| S3 | Measuring the judge on 0.9.1 needs the owner's approval to send eval questions and records to Anthropic |
| Labels | The person-checked review (section 2) gates any engine comparison (audit O.5 item 1) |

## How it was run

- **Two copies under `local/audit-m0/`:**
  - *Snapshot:* the vault and `brain.db` of `local/eval/m0` (the frozen 2026-11-14 snapshot) were copied. Its notes and archive folders are read in place, read-only, because of finding 1.
  - *Live:* the live vault was copied, and its `brain.db` taken through SQLite's backup API on a read-only connection (`mode=ro`). Its notes and archive folders are read in place, read-only.
  - The live agent's files were only read.
- **Configuration:** new `brain.yaml` files with no Hindsight store, no judge (`recall.judge` left at `agent`), no mental models and no graph script.
- **Credentials and network:** every command ran with:
  - Anthropic, OpenAI and Hugging Face tokens unset
  - `HTTP(S)_PROXY` pointed at a closed local port, so any outbound HTTP fails
  - `HF_HUB_OFFLINE=1`; the embedding model was already on disk
  - the `claude` CLI replaced on `PATH` by a stub that refuses and logs; its log stayed empty
  - its own embed-worker home
- **Repository changes:** one new tracked file, `tests/eval/census.py`. It opens `brain.db` with `mode=ro` and reports counts only unless `--names` is passed. Lint and `mypy --strict` are clean. No other tracked file changed for M0.

To reproduce:

```bash
. local/audit-m0/env.sh
.venv/bin/python tests/eval/run_gold.py --config local/audit-m0/snap-s0.brain.yaml --questions local/audit-m0/questions.yaml --today 2026-11-14 --out local/audit-m0/results/s0.json
.venv/bin/python tests/eval/census.py --db local/audit-m0/live/data/brain.db --out local/audit-m0/results/census-live.json
```
