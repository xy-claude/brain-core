# Knowledge program: status by milestone

The plan is `docs/KNOWLEDGE_ARCHITECTURE_AUDIT.md`, revision 2.3; the decisions are in `docs/M1_DECISION_CHECKLIST.md`. Every milestone was built test-first and checked on an isolated copy of a real agent. Each was then released and cut over on the live agents, behind a backup, with a fresh inventory before and a check after.

| Milestone | Release | State |
|---|---|---|
| M0: baseline | — | done; re-baselined after M1b: S0 301/443, S2 347/443 (`docs/M0_BASELINE.md`, section 10) |
| M1a: relations in the vault | 0.10.0 | live |
| M1b: ids independent of folder paths | 0.11.0 | live on all three agents |
| M1c: `data/journal.db` | 0.12.0 | live on all three agents |
| M2: entity registry | 0.13.0 | live on all three agents |
| M3: claims and time | 0.14.0 | live on all three agents |
| M4: graph retrieval | 0.15.0 | live on all three agents (as 0.16.1); eval labels AI-written and AI-checked (the owner's decision), not human-validated |
| M7: conflict checks | 0.16.0 | live on all three agents (as 0.16.1); THREAT_MODEL gates 1 to 3 built for claims |
| M5, M6 | — | not in scope (the owner's decision): no outside LLM calls, no Neo4j download |

## Live cutovers of 2026-11-23

Each followed the same procedure: no brain server running, a read-only inventory, a checked backup of each `brain.db`, the install, the first open, then the check against the inventory.

- **M1c (0.12.0).**
  - Each agent's first open started its journal. Its ledger rows equalled its records: 6,127 for the main agent, 1,375 and 70 for the other two.
  - Records, search keys and vectors were unchanged.
  - The first backups passed `integrity_check` and are readable by the owner only.
- **M2 (0.13.0).**
  - On the main agent the journal grew by exactly the 83 lines of `relations.md`, the one change 0.13.0 makes, and no row closed. The other two have no relations, and their journals did not change.
  - `brain entities propose` staged 77 names in the main agent's inbox and wrote no note.
  - `brain doctor` shows only what it showed before.

## Live cutover of 0.16.1: M4 and M7 (2026-11-23)

0.15.0 and 0.16.0 were released but not installed on their own. 0.16.1 adds the wording an agent needs for undated claims, and a re-read so older notes-folder lines become provisional. The agents went from 0.14.0 straight to 0.16.1, with no brain server running, a fresh inventory and a checked backup of each `brain.db`.

- **Records, keys, vectors, events:** unchanged on all three agents.
- **Ledger:** no row added and none closed on any agent, although index format 7 read every file again: the texts are unchanged. The derivation journal kept its 692 rows on the main agent: a re-read adds no version.
- **Claims:** 83 on the main agent and none on the other two, as before. Nothing to report.
- **`brain index --check`** (with its rebuild from the files): in step on all three.
- **Recall:** for 200 eval questions asked of the main agent before (0.14.0) and after, keywords only, 190 top-10 lists are identical. The 10 that changed each carry a result the graph net found, so the net is on and nothing else moved.
- **Not verified live:** the write-time contradiction. It needs a new relation that conflicts with one held, and none was written on the owner's agent to test it; the unit tests cover it.

## Validation on frozen copies of the main agent (2026-11-23)

**Setup.**
- **Two copies of the main agent at 0.17.0**, with the same vault snapshot and the same 6,016 record ids, differ only in vector coverage:
  - 17%: 1,043 records embedded, as the live agent ran until the gap was found and filled that morning
  - 100%: every record
- **Scoring:** keywords, the vector net, the graph net and `as_of` were scored on the existing question sets (443 regression, 59 builder, 20 held-out). The model judge was off and nothing was sent to any model.
- **Noise floor:** the same run twice differs on 0 of 443 questions.

**Results.**

| | 443 regression | builder multi-hop /40 | as-of /19 | held-out multi-hop /20 |
|---|---|---|---|---|
| keywords | 293 | 0 | 17 | 0 |
| keywords + graph net | 293 | 12 | 17 | 9 |
| vectors at 17% (+ graph net) | 325 (325) | 0 (1) | 16 (16) | 0 (2) |
| vectors at 100% (+ graph net) | 342 (342) | 0 (2) | 16 (16) | 0 (1) |

- **Filling the vectors is a net gain:** on the 443, 29 questions fixed and 12 broken (sign test p = 0.012). About 10 of the 12 are ranking displacements. Two of those are an older value outranking the current one where no `supersedes` line links them.
- **The earlier M4 "with vectors" figures were measured at 17% coverage.** The old result files match the 17% copy question by question (59/59, 20/20, 443/443).
- **The graph net with vectors adds little.** At full coverage it solves 2 of 40 and 1 of 20 multi-hop questions that recall alone missed, and breaks none.
  - Paired over 5 repeats, it adds 2.3 ms at the median and 7.5 ms at p95.
  - A blind pairwise review then preferred recall without it (below), so it is opt-in since 0.18.0.
- **The miss flag is weak, and nothing here moved it:**
  - 20 of 57 questions with no answer in memory come back without a miss flag.
  - 95 of 386 answerable questions are flagged as misses.
- **Cross-layer tests:** 23 of 24 checks passed on a third copy:
  - save then recall
  - a changed fact
  - dated evidence and a conflict
  - entity notes: re-keying, an alias, `merged_into`, a shared alias
  - crash windows and a journal restore
  - untrusted text, the MCP server, and the four hooks
- **0.17.1 fixed two defects these tests found:**
  - The failed check: `brain claims check` exited 0 with an open conflict.
  - A cut claims block did not say so in words.
- **Not covered:** the model judge, answer correctness judged by a model, and transcripts in the ranking.

**Blind pairwise review of the graph net** (by the owner's delegation, AI-judged, not owner-validated).
- **The questions:** 60 real questions from the main agent's sessions and recall misses that name something its relations know. With full vectors, the net changes the top 5 for 46 of them.
- **The judging:** two fresh agents, each shown only the questions and the two top-5 lists in a hidden order, picked the list that better lets someone answer. The rules for combining them and for the decision were fixed beforehand.
- **Agreement:** the judges matched on 42 of 46 and never picked opposite lists.
- **Result:** recall without the net better on 16, with it on 0, the same on 30 (sign test p < 0.001). Over all 60: 0 better, 16 worse, 44 tied.
- **The reason each time:** the net's relation lines push a relevant record out of the top 5. They stay in the top 10, which is why the scored sets saw no break.
- **A limit:** only the lists with the net show relation lines, so the kind of record could tell the sides apart, even though the judges' reasons are about relevance.
- **Decision:** the net is off on the main agent, and opt-in for everyone since 0.18.0. The code, the claims tier and `brain claims` are unchanged.

## Where the program stands

- **Every milestone in scope is built, released and live:** M0, M1a to M1c, M2, M3, M4 and M7. M5 and M6 were left out by the owner's decision.
- **The claims wait for entity notes.** All 83 claims on the main agent still name their entities by name: no entity note exists yet. 77 proposals sit in its inbox (`brain entities propose`); a person makes each note, and the claims then re-key onto it.
- **Every live claim is undated.** The relation lines say when brain-core stored them, not when they became true, so a past `as_of` finds no claim true yet, and the graph net's claims are marked `undated`.
- **The graph net is opt-in since 0.18.0** (`recall.graph: true`). With vectors it solved 2 of 20 independently written multi-hop questions at 17% coverage, and 1 of 20 with every record embedded (neither is significant). With keywords alone it solved 9 of 20. A blind review of 46 real questions preferred recall without it, 16 to 0. Off, recall is 0.14.0's.
- **Labels are AI-written and AI-checked**, as the owner decided for M0 and M4; no person has checked them.
- **Decision 22** (start M3 only with evidence of need) was overridden by the owner's decision to finish the plan.
- **The Graphify check** was still pending at every release; it is a third-party check, and the project's own CI (tests on Linux and Windows, the installer, Hindsight) passed each time.

## M7: conflict checks (2026-11-23)

- **At write time.** `brain_remember(kind='relation')` checks the new claim against those already held on its functional predicate and role. A conflict that holds is returned as `contradiction`: an interval one, or a current one when today is inside its window. A window that has closed is not.
- **In recall.** The `claims` block carries `disputed_with` for a disputed claim. This is the conflict slice of audit O.2, tested on a fixture: two accepted claims of one functional predicate overlap; then an `ack:` line is written and the mark goes.
- **Gate 1.** A notes-folder line is a provisional `candidate` until a person states the relation in `relations.md`.
- **Gate 3.** A reflection line needs `(parents: …)` naming claims held from other evidence, or it stays a candidate and is reported.
- **Not built:** the weekly reflection writer does not emit parent ids itself. Hindsight's reflect gives none, so a reflection relation can only count when a person or the agent writes its parents.

## M4 on isolated copies of the main agent (2026-11-23)

**Copies.** Two copies of the main agent at 0.14.0: one as it is (83 claims, no entity notes), and one with entity notes made for its five most-connected names (5,481 mentions, 61 claims re-keyed onto the notes). Each runs with keywords alone and with vectors.

**Question sets.**
- **The 443 existing questions** (M1b's ids), which measure regression.
- **59 new ones, written by the builder:**
  - 40 multi-hop questions, each naming one entity and needing two relations. Gold: every relation on the path.
  - 19 as-of questions about a value replaced later, asked for a day before the replacement. Gold: the old value, ahead of its replacement.
  - This is fewer than the audit's 40 temporal questions: only 19 replaced values on the copy have dates that allow it.
- **20 multi-hop questions written by a separate agent** that saw only the relation list. They paraphrase the relations rather than reuse their words, and they are the held-out set. They were run once on the final design, after being used once to reject a word filter (below).

**Results against 0.14.0's behaviour** (no graph net, no `as_of`):

| | keywords | keywords + vectors |
|---|---|---|
| 443 existing questions, broken | 0 (both copies) | 0 (both copies) |
| held-out multi-hop, every relation in the top 10 | 0 → 9 of 20, p = 0.004 | 0 → 2 of 20, 0 broken |
| builder multi-hop | 0 → 12 of 40, p = 0.0005 | 0 → 1 of 40, 0 broken |
| as-of, the day's value first | 0 → 17 of 19 | 0 → 16 of 19 |
| recall p95 added | 3 to 5 ms (101 → 105) | 0 to 3 ms (212 → 215) |
| walks cut short on the real graph (depth aside) | 0 of 77 | |

- **Gates:**
  - zero broken in the update and identifier slices
  - the net adds at most 25 ms at p95
  - keyword p95 within 10% of M0's live copy (110 ms), vectors within 10% of 204 ms
  - truncation under 5%
- **Not measured:** the as-of-unknown, conflict and decision-history slices are not built. So "zero false assertions under `as_of`" holds by construction (an unknown claim is never walked as true), not by a measured slice.
- **On this data the two gains do not combine.** Every live claim is undated, so a past `as_of` walks nothing.

**What the copies taught, and what changed because of it:**
- **A word filter** (keep only claims that share a word with the question) and **a double weight** for the net lifted the builder's set to 27 of 40. But they solved none of the 20 paraphrased questions, so both were dropped.
- **The records that merely mention a seed**, which the audit adds to the net, broke 3 to 5 of the 443 once entity notes existed: they repeat the keyword search. Only the claims' own evidence is put forward.
- **Undated relations that the vault never ended** ("X uses NotebookLM", after NotebookLM was removed) led a question asking whether they were "still" used. A question about change now leaves out undated claims, and the claims block marks the rest `undated`.
- **A name inside a file path or an address** seeded the walk and broke an identifier question. Such a name is no seed now.

## Where M4 departs from the audit

- **No `nets.py` refactor.** The net joins `brain_recall` beside the date net, as the audit's "Into recall" paragraph says, without the `Net` protocol.
- **No mention records in the net** (above). M2's `mentions` table is still built and kept current, and `brain entities list` counts from it; the graph net only does not add the records it lists to recall's ranking.
- **Degree is counted from the claims**, capped at the hub threshold, because most entities on a live agent are still names without a note.
- **Ordering inside a hop.** The audit's "keyword score" is read as the number of question words a claim says.

## M3 live cutover (2026-11-23)

0.14.0 was installed on all three agents behind a fresh inventory and a checked backup of each `brain.db`:
- **Ledger:** the main agent's grew by its 609 `record_meta.md` lines that link a record, exactly as predicted from the file, and closed none. The other two grew by 0.
- **Claims:** 83 on the main agent, one per relation line; none on the other two.
- **Checks:** `brain index --check`, with its rebuild from the files, is in step on all three.
- **Backups:** journal backups were taken after the cutover.

## M3 on an isolated copy of the main agent (2026-11-23)

- **What it derives:**
  - 83 claims, one per relation line, all accepted and stated. All are written by brain-core (`recorded:`), so their origin is the agent.
  - All 83 wait for entity notes: none is made yet.
  - No decision names exactly one wikilink, so no decision gives a claim.
  - No conflict, nothing to report.
- **Journal:**
  - The ledger grew by the 609 `record_meta.md` lines that link or time a record (588 `was:`, 21 `supersedes`), and closed nothing.
  - The derivation journal holds 692 rows. The file grew from 3.6 to 4.3 MB.
- **Checks:** `brain index --check`, which rebuilds the claims from the files into a temporary database, is in step.
- **Recall:** identical to 0.13.0 for 200 of 200 queries.
- **Speed** (against 0.13.0 on the same data):
  - full parse 3.43 s against 3.23 s, +6% (the gate is +20%)
  - recall p95 3 to 8% higher, over three alternating runs each (the gate is +10%)
  - a sync with no change 4.4 ms against 4.5 ms
  - a sync after a save that adds search keys 85.8 ms against 85.1 ms
  - the first open after the upgrade, which reads every file once, takes about 4 s
- **Rollback:** 0.13.0 runs on the M3 database and leaves the journal untouched.
- **A bug found on the way:** 0.12 and 0.13 failed every sync after the vault folder moved. Fixed in 0.14.0, and the copy, whose index still named the live paths, is the test.

## Where M3 departs from the audit

- **Decision fields.** A decision selects what its **Decision:** names (`SELECTS`, with the decision record as subject), and only when it names exactly one wikilink. The audit's worked example reads a `USES` claim out of the sentence, which no rule can do without a model.
- **Unknown predicates.** One that is not in `ontology.yaml` is kept as written, in upper case, not folded into `RELATED_TO`. So two different free predicates stay two claims, and nothing is lost.
- **Not built:**
  - checking a claim's subject and object against the predicate's domain and range
  - resolving an alias two entities share by the type the predicate expects. The name is kept and reported.
- **Today's entities.** `--known-at` derives past claims with today's entity notes and ontology. The journal keeps the claim rows' history, not the notes'.
- **Two tables beyond L.1.** `claim_raw` (the raw rows of each source, which `check` compares with the journal) and `claims_state` (whether a recompute is due).
- **Section R defaults applied.** Items 5 to 10, 12, 18 and 20 are applied with their defaults. Item 22 (M3 only with evidence of need) is overridden by the owner's decision to finish the plan.

## M2 on an isolated copy of the main agent (2026-11-22)

- **Recall:** identical to 0.11.0 for 200 of 200 queries. The live agent has no entity notes yet.
- **Speed:**
  - full parse 3.29 s against 2.92 s for 0.11.0 on the same data, +13% (the gate is +20%)
  - recall p95 about 4% above 0.11.0, run alternately three times each (the gate is +10%)
- **Proposals:** `brain entities propose` staged 77 names in the inbox and wrote no note.
- **Mentions:** with five sample entity notes made on the copy, the registry found 3,180 mentions (2,390 by alias, 19 by wikilink). A full recompute over every record took 0.18 s.
