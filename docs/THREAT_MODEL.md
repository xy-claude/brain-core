# Threat Model — Corpus Poisoning

`central-brain` ships a memory + retrieval layer. That layer is RAG-shaped: facts and episodic events go into a knowledge base; an LLM reads retrieved context to reason and answer. This document names the attack surface that comes with that shape and the ingestion-time gates that keep a consumer safe.

## The attack

**PoisonedRAG** (Zou et al., *PoisonedRAG: Knowledge Corruption Attacks to Retrieval-Augmented Generation of Large Language Models*, USENIX Security 2025, arXiv:2402.07867) shows that **5 malicious documents planted in a 2.68 M-document corpus — 0.0002% — hijack LLM answers 97% of the time** on GPT-4 and PaLM 2. The attacker needs no model access, no retriever access, no visibility into the database. They write a document. The document is crafted to solve two conditions at once:

- **Retrieval condition** — embedding near the target question, so the retriever picks it up.
- **Generation condition** — when that document alone is the context, the LLM emits the attacker's chosen answer.

Tested across 8 LLMs and 3 corpora. Bigger databases are *not* safer. Standard defenses — paraphrasing, perplexity filtering, dedup, top-k expansion — all fail: ASR stays 41–93% across defenses.

OWASP 2025 LLM08 (*Vector and Embedding Weaknesses*) recognizes the class. The research frontier has pivoted from prevention to forensics (see *Traceback of Poisoning Attacks to RAG*, 2025).

## The takeaway

From the strongest critique of the paper's framing (accepted widely in the security community): **"Grounding is not a security boundary if your corpus isn't trustworthy."** RAG ingestion needs to behave like a software supply chain, not like input validation.

## How it maps onto `central-brain`

central-brain is a library. It does not own a public ingestion endpoint. The attack surface belongs to the **consuming agent** — whoever writes to the brain. The threats are all internal:

| Writer | Poisoning risk |
|---|---|
| The agent itself (hallucinated fact → `retain` or vault write) | High — most frequent writer |
| Auto-capture / background extraction | Medium — provisional, but searchable |
| External ingestion (distillation, scrapers, file imports) | Medium — external-origin content |
| Cross-agent shared writes | Medium — trust varies by agent |
| Reflection synthesis writes | **Highest leverage** — synthesized writes get laundered into "trusted" artifacts and become ground truth for future recall |

## Gates that `central-brain` provides (or will)

These are ingestion-time gates — the paper shows downstream defenses fail, so the library builds them in at the write path.

1. **Provisional-by-default writes** — any entry written by an automated or external path must carry a `provisional: true` flag until it is explicitly promoted by a deliberate writer. Recall returns them with the flag visible; high-stakes callers filter them out.

2. **Source traceability (HARD INVARIANT)** — every memory entry must carry a `source` field: `self-deliberate` | `self-auto` | `external:<id>` | `reflection:<parent_ids>`. No anonymous memories. Recall results always expose source. This is the library's answer to the paper's "we can't trace what poisoned us" problem.

3. **Reflection is a privileged ingestion path** — a reflection write that surfaces a new fact (not traceable to at least one pre-existing entry via `parent_ids`) must be rejected, not persisted. Reflection synthesizes; it does not discover.

4. **Contradiction flagging** — updating a fact with a different value emits a contradiction event the consumer can inspect. Silent overwrite is not allowed.

5. **No external retrievers by default** — `central-brain` does not pull from Wikipedia, web, or third-party knowledge bases. If a consumer wires one in, they own the corpus-trust assessment and must document the ingestion gate in their `brain.yaml`.

6. **Consumer-owned trust policy** — `brain.yaml` defines which sources are trusted for which operations (e.g., "auto-captured entries may feed recall but may not feed reflection synthesis"). central-brain enforces the policy at the retrieval/synthesis boundary.

## What this is *not*

- Not a claim that central-brain is poison-proof. A determined, authorized writer can still lie to their own brain.
- Not a replacement for the consumer's own threat model. If a consumer ships a public ingestion endpoint, that's their attack surface to document.
- Not a solved problem. The state of the art has not solved corpus poisoning — central-brain's posture is *raise the cost of the attack, expose every poisoned entry's lineage, refuse the highest-leverage poisoning paths by construction*.

## Consumers: questions to answer before shipping

- Where does each write to the brain originate? Is the source tagged?
- Can any automated path write directly to a "trusted" layer without human review?
- Does reflection have a path to create a new ground-truth fact without existing parent entries?
- If your corpus grew 10× tomorrow from an unvetted source, which of your answers would silently change?

If any of those answers are "I don't know," treat the brain as potentially poisoned and start with a source audit.
