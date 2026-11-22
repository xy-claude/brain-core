# M0 baseline: what brain-core measures before the knowledge layer

**Date:** 2026-11-21. **Code:** brain-core 0.9.1, commit `55038ca` (the version the live agent runs too).
**Plan:** `docs/KNOWLEDGE_ARCHITECTURE_AUDIT.md`, section P, milestone M0. M0 only measures: no schema change, no migration, no change to how brain-core behaves.
**Privacy:** this file holds counts and scores only. The questions, record text, predicate and entity names, and the label-review packet stay under `local/audit-m0/`, which git ignores.

**Scores and labels.** Sections 1 to 7 report the historical, provisional scores (295 and 346 of 446), which rest on labels written by a model. On 2026-11-22 the 104-question review sample was corrected, and the baseline re-scored on it (section 9): **298 and 345 of 443**. Those corrections were answered by AI and accepted by the owner without checking them. **No person has validated any label.** Until M4, comparisons use the section 9 baseline, with that caveat. M4's gate still needs labels a person has checked (audit O.5 and ADR-010).

## Summary

| Question M0 had to answer | Answer |
|---|---|
| Does 0.9.1 still score what the README publishes? | **Yes, on provisional labels.** Keywords find 295 of 446, the README's 0.9.0 figure. Against the 2026-11-14 run: 7 fixed, 4 broken, McNemar p 0.55. With vectors: 346, also the README figure (56 fixed and 5 broken against keywords, p < 0.001) |
| How big is the graph the plan would build on? | **Tiny.** 82 relations, 43 predicates (31 used once), 75 entity names, highest degree 19, nothing written since 2026-11-02 |
| Would decisions feed it? | **Not today.** None of the 81 decisions has a `[[link]]` in its fields, so rule `decision-field/1` derives 0 claims. 313 records do carry wikilinks, 301 of them knowledge pages |
| Do the traversal limits bind? | **No.** A 2-hop walk from each of the 75 entities finds at most 49 edges, reads at most 74 rows, takes at most 0.8 ms, and never truncates. `hub_degree` 200 and `fan` 20 are safety limits here, not tuning |
| Is a file watcher needed? | **No.** A sync with no change takes 5 ms; a full parse of every markdown store takes 2.5 s |
| Is recall fast enough? | Snapshot, keywords: p50 49 ms, p95 74 ms. **Live** copy, keywords plus transcripts: p50 73 ms, **p95 110 ms**, already above the audit's 100 ms gate (O.5). The gate needs restating against this baseline. Revision 2.2 does: the gate is now baseline-relative (p95 at most 10% above these numbers), and 100 ms stays a target |
| Are the labels trustworthy? | **Partly corrected, never checked by a person.** AI reviewers changed 50 of the 104 sampled labels (48%), and the owner accepted their answers without checking them. That moved only 7 keyword outcomes and 3 vector outcomes (section 9). The other 342 questions keep their model-written labels |
| Anything wrong that M0 was not looking for? | **Yes, two things.** Notes and archive record ids embed the absolute folder path (audit G11). The live agent has a current vector for only 17% of its records (section 5) |

## 1. Baseline recall

*Provisional: model-written labels, not yet checked by a person.*

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

## 2. Label review: done by AI at the owner's request (section 9)

- **The sample.** `local/audit-m0/label_review.md` and `label_review.csv` hold 104 questions: 24 reworded, 6 real, 6 same, 14 update, 14 temporal, 14 multi, 14 absent and 12 identifier. 47 of them are baseline misses, because a wrong label usually shows up as a false miss.
- **What each entry shows:** the question, its gold records with their text, and today's keyword top 10.
- **The reviewer marks** each one *right*, *wrong*, *incomplete* or *ambiguous*, and adds any corrected gold.
- **Status.** Done on 2026-11-22 by AI reviewers, and accepted by the owner unchecked (section 9). The scores above, and the README's, rest on the uncorrected model-written labels.

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
   - Sized on the live copy, read-only, for revision 2.2: a migration touches 2,805 records. It would write 588 `was:` meta lines for the records that have search keys and remap 633 vectors. No `supersedes` link names them. The plan is M1b in the audit.
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
| O.5 gate | Done in audit revision 2.2: p95 at most 10% above this baseline on the same corpus and machine; a keyword p95 under 100 ms stays an optimisation target |
| S3 | Measuring the judge on 0.9.1 needs the owner's approval to send eval questions and records to Anthropic |
| Labels | The person-checked review (section 2) gates any engine comparison (audit O.5 item 1) |

## 7. Added in validation for audit revision 2.2

**Status (updated 2026-11-22): M0 is complete,** with criterion 1 waived by the owner (sections 8 and 9).

**Where the labels came from.**
- The first 143 questions were written by a model reading the records; 11 of them use the owner's own past words (README).
- The other 303 were drafted by a model from a catalog of the snapshot, under the rules in `local/eval/m0/BRIEF.md`:
  - the gold must answer fully
  - an exact answer substring is given
  - every other record stating the answer is added, archive copies included
  - one clear answer per question
- Each answerable question was then checked once by a second model (README), and mechanically by `check_labels.py`: the gold resolves and the answer is in the store.
- No person has checked any of them.
- The catalog holds 5,394 unique records (5,762 lines), while 0.9.1 indexes 5,821 for the same snapshot. Labels can therefore miss records the 0.9.0 reader added.

**AI-assisted pre-review of the 104-item packet: a hint, not validation.**
- Four model agents classified the items. Their verdicts are in `local/audit-m0/ai_review/label_review_ai.csv`, apart from the human `label_review.csv`, whose verdict column is empty.
- Results: 58 correct, 40 incomplete, 4 ambiguous, 2 incorrect, 0 unverifiable.
- Every absent item was judged correct.
- Most "incomplete" verdicts name an archive copy or a same-day note missing from the gold. The agents applied that rule differently, which is one more reason a person must decide.

**Questions affected by path-dependent ids (G11).**
- 182 of 446: reworded 76, real 1, same 4, update 28, multi 34, identifier 39.
- The frozen snapshot's 588 search-key lines for notes and archive records are keyed by the live agent's paths, so in this snapshot none of them ever attached. The scores above, and the README's, measure notes and archive recall without their search keys.

**What fixing G11 does, measured on fresh isolated copies, labels translated:**

| Variant | S0 | S2 |
|---|---|---|
| New ids only | 295, 0 fixed, 0 broken | 346, 0 fixed, 0 broken |
| New ids plus the 588 live key lines attached | 298 (12 fixed, 9 broken, p 0.66) | 347 (7 fixed, 6 broken, p 1.0) |

With the keys attached, the absent slice goes 38 → 36 in both, and S0 breaks one identifier question. So after M1b the baseline must be re-measured, not counted as an improvement.

**Paired S0 → S2, by slice** (from `compare.py`):

| Slice | S0 → S2 | Fixed / broken |
|---|---|---|
| reworded | 83 → 114 | 33 / 2 |
| real | 8 → 10 | 2 / 0 |
| same | 20 → 20 | 0 / 0 |
| update | 24 → 27 | 5 / 2 |
| temporal | 42 → 46 | 4 / 0 |
| multi | 29 → 37 | 9 / 1 |
| absent | 38 → 38 | 0 / 0 |
| identifier | 51 → 54 | 3 / 0 |
| **all** | **295 → 346** | **56 / 5, p < 0.001** |

**Memory.**
- A keyword eval process peaks at 52 MB resident; a recall process with vectors at 124 MB.
- The embed worker showed 58 MB in `ps`. That does not count the model's GPU memory on Apple Silicon, so the worker's real footprint was not measured.

**Preserved.**
- `local/audit-m0/MANIFEST.json` holds the sha256 of the frozen questions (identical to M0's copy), the frozen 2026-11-14 baseline and every M0 result file. No earlier run was overwritten.
- Opening the frozen database read-only updated its WAL index file (`brain.db-shm`). Its data file and WAL are unchanged since 2026-11-14.

**Then still required (updated 2026-11-22):**
1. ~~the human review~~: done by AI and accepted unchecked (section 9)
2. ~~a re-scored baseline on the corrected labels~~: done (section 9)
3. about 40 multi-hop and 40 temporal questions, person-checked, before M4
4. optionally S3, with the owner's approval

## 8. M0 completion criteria (from 2026-11-22)

**M0 is complete as of 2026-11-22.** Four criteria hold, and the owner waived criterion 1:

| # | Criterion | State on 2026-11-22 |
|---|---|---|
| 1 | A person has reviewed all 104 questions in `local/audit-m0/human_review/M0_HUMAN_REVIEW_PACKET.md` (git-ignored). The AI-assisted pre-review is a hint only and never counts | **waived by the owner, 2026-11-22.** The owner asked Claude to answer the packet, then accepted the AI answers as they are, without checking them. No person reviewed the labels: the corrected labels are **AI-reviewed, not human-validated** (section 9). The main packet stays blank, so a person can still review it later |
| 2 | The owner has approved every correction to the gold labels | **done, by acceptance.** The owner accepted every AI correction and drop as a whole, unchecked (section 9) |
| 3 | The baseline is recalculated on the corrected labels, written to new files (`questions-v2.yaml`, `results/s0-v2.json`, `results/s2-v2.json`), with paired fixed and broken counts against the historical runs | **done.** 298 and 345 of 443; paired against the historical runs, keywords: 6 fixed and 1 broken; vectors: 2 fixed and 1 broken (section 9) |
| 4 | The results are preserved and reproducible: checksums added to `MANIFEST.json`, commands recorded, nothing earlier overwritten | **done.** 10 new checksums were added to `MANIFEST.json`: the accepted draft, the four answer files, `questions-v2.yaml`, `decisions.json` and the new results. The 11 earlier entries are unchanged, and the historical files still match them |
| 5 | Concerns A, B and C are resolved or explicitly accepted as known risks | **done.** All three were confirmed and corrected in audit revision 2.3, with regression tests |

**Historical results, kept as they are.** 295/446 (keywords + keys) and 346/446 (+ vectors), measured on 2026-11-21 on model-written labels, are the historical, provisional baseline. They and their result files (`local/audit-m0/results/s0.json`, `s2.json`) are never edited or overwritten. Corrected scores go to new files beside them.

S3 is not part of M0's completion and needs explicit approval, because it sends questions and records to Anthropic.

## 9. Label review outcome and corrected baseline (2026-11-22)

**Provenance: AI-reviewed, not human-validated.**
- **Who answered.** The owner asked Claude to answer the 104-question packet. Four Claude agents did it, with one shared written rule set taken from the original labelling brief, working from the blind packet so the earlier pre-review did not anchor them.
- **Acceptance.** The owner accepted the answers as they are, without checking them. That includes two stricter labelling choices:
  - complete `stale` lists on 7 update questions
  - very wide gold lists on 3 questions, of 11, 28 and 35 records
- **Privacy.** The questions and records went through the Claude session to Anthropic, at the owner's request. S3, the model judge, was not run.
- **Where the record is.** The accepted packet is `local/audit-m0/human_review/ai_draft/M0_REVIEW_PACKET_AI_ANSWERED.md`. The main packet stays blank, so a person can still review it later.

**What changed.**
- **Verdicts:** 54 correct, 41 incomplete, 6 incorrect, 3 ambiguous.
- **Actions:** 54 kept, 47 corrected, 3 dropped (2 reworded, 1 identifier).
- **Agreement:** the verdict matches the earlier AI pre-review on 77 of 104.

| Labels changed | absent | multi | temporal | update | identifier | reworded | same | real |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| of those sampled | 0/14 | 1/14 | 6/14 | 8/14 | 7/12 | 17/24 | 5/6 | 6/6 |

- **Most corrections add copies to the gold** (146 gold ids added, half of them archive copies, plus 33 stale ids). The original labeller often missed copies the brief required.
- **The rate overstates the whole set.** 47 of the 104 were baseline misses, chosen because a wrong label usually shows up as a miss.

**Checks on the corrected labels.**
- Every added id is in the snapshot index, in a store both eval configs search.
- `check_labels.py` reports 21 items, none of them a real defect. 19 are record ids that exist in the index but not in the older catalog the checker reads. The other 2 are answers found only in gold records that the catalog lacks.
- Every new answer substring appears in a gold record.
- No update question's answer appears in one of its stale records.

**Corrected baseline.** Same snapshot, same `--today 2026-11-14`, offline, no credentials, no outside calls (the CLI tripwire stayed empty).

| Slice | n | S0 keywords + keys | S2 + vectors (RRF) |
|---|---:|---:|---:|
| reworded | 158 | 81 | 112 |
| real | 11 | 10 | 11 |
| same | 20 | 20 | 20 |
| update | 37 | 24 | 26 |
| temporal | 53 | 44 | 47 |
| multi (every gold) | 53 | 29 | 37 |
| absent (flagged) | 57 | 38 | 38 |
| identifier | 54 | 52 | 54 |
| **all** | **443** | **298** | **345** |

- **Paired against the historical runs, on the same 443 questions:**
  - S0: 293 → 298, with 6 fixed and 1 broken (p 0.125)
  - S2: 344 → 345, with 2 fixed and 1 broken (p 1.0). The broken one is an update question, where the stale list grew
- **The other errors are unchanged:**
  - false answers: 19 of 57 in both runs
  - false refusals: 104 of 386
  - missed with no warning: 64 of 386 for S0 and 40 of 386 for S2
- **The label errors barely moved the historical scores.** Correcting half of the sampled labels changed 7 keyword outcomes and 3 vector outcomes, because most added copies sit beside a gold record the search already finds, or one it still misses.
- **This is now the baseline** for M1 to M3. Decision 19's re-baseline after M1b compares with 298 and 345 of 443, not with 295 and 346 of 446.
- **Use it as a regression smoke test for M1–M3,** not as proof of answer quality. The paired counts above describe what the label fixes changed, not a better search (second-model review, 2026-11-22).
- **It is not enough for M4.** M4's gate needs labels a person has checked (audit ADR-010), plus about 40 multi-hop and 40 temporal questions, also person-checked. The owner's waiver covers M0 only.

**Files** (all under `local/audit-m0/`, git-ignored, with checksums in `MANIFEST.json`):
- `human_review/questions-v2.yaml` and `decisions.json`, both marked as not human-validated
- `results/s0-v2.json`, `results/s2-v2.json` and `results/s2-v2.txt`

**Commands:**
- `human_review/apply_review.py --packet human_review/ai_draft/M0_REVIEW_PACKET_AI_ANSWERED.md --accepted-ai`
- then `run_gold.py` and `compare.py`, as in `human_review/README.md`

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
