# Knowledge program: status by milestone

The plan is `docs/KNOWLEDGE_ARCHITECTURE_AUDIT.md`, revision 2.3; the decisions are in `docs/M1_DECISION_CHECKLIST.md`. Every milestone was built test-first and checked on an isolated copy of a real agent. Each was then released and cut over on the live agents, behind a backup, with a fresh inventory before and a check after.

| Milestone | Release | State |
|---|---|---|
| M0: baseline | — | done; re-baselined after M1b: S0 301/443, S2 347/443 (`docs/M0_BASELINE.md`, section 10) |
| M1a: relations in the vault | 0.10.0 | live |
| M1b: ids independent of folder paths | 0.11.0 | live on all three agents |
| M1c: `data/journal.db` | 0.12.0 | live on all three agents |
| M2: entity registry | 0.13.0 | live on all three agents |
| M3: claims and time | 0.14.0 | built and checked on a copy |
| M4: graph retrieval | — | after M3; its eval labels are AI-reviewed (the owner's decision), not human-validated |
| M7: conflict checks | — | after M3 |
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
