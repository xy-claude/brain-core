# Knowledge program: status by milestone

The plan is `docs/KNOWLEDGE_ARCHITECTURE_AUDIT.md`, revision 2.3; the decisions are in `docs/M1_DECISION_CHECKLIST.md`. Every milestone was built test-first and checked on an isolated copy of a real agent. Each was then released and cut over on the live agents, behind a backup, with a fresh inventory before and a check after.

| Milestone | Release | State |
|---|---|---|
| M0: baseline | — | done; re-baselined after M1b: S0 301/443, S2 347/443 (`docs/M0_BASELINE.md`, section 10) |
| M1a: relations in the vault | 0.10.0 | live |
| M1b: ids independent of folder paths | 0.11.0 | live on all three agents |
| M1c: `data/journal.db` | 0.12.0 | released |
| M2: entity registry | 0.13.0 | built and checked on a copy |
| M3: claims and time | — | next |
| M4: graph retrieval | — | after M3; its eval labels are AI-reviewed (the owner's decision), not human-validated |
| M7: conflict checks | — | after M3 |
| M5, M6 | — | not in scope (the owner's decision): no outside LLM calls, no Neo4j download |

## M2 on an isolated copy of the main agent (2026-11-22)

- **Recall:** identical to 0.11.0 for 200 of 200 queries. The live agent has no entity notes yet.
- **Speed:**
  - full parse 3.29 s against 2.92 s for 0.11.0 on the same data, +13% (the gate is +20%)
  - recall p95 about 4% above 0.11.0, run alternately three times each (the gate is +10%)
- **Proposals:** `brain entities propose` staged 77 names in the inbox and wrote no note.
- **Mentions:** with five sample entity notes made on the copy, the registry found 3,180 mentions (2,390 by alias, 19 by wikilink). A full recompute over every record took 0.18 s.
