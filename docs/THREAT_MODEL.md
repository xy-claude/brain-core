# Threat Model — Corpus Poisoning

`brain-core` ships a memory + retrieval layer. That layer is RAG-shaped: facts and episodic events go into a knowledge base; an LLM reads retrieved context to reason and answer. This document names the attack surface that comes with that shape and the ingestion-time gates that keep a consumer safe.

## The attack

**PoisonedRAG** (Zou et al., *PoisonedRAG: Knowledge Corruption Attacks to Retrieval-Augmented Generation of Large Language Models*, USENIX Security 2025, arXiv:2402.07867) shows that **5 malicious documents planted in a 2.68 M-document corpus — 0.0002% — hijack LLM answers 97% of the time** on GPT-4 and PaLM 2. The attacker needs no model access, no retriever access, no visibility into the database. They write a document. The document is crafted to solve two conditions at once:

- **Retrieval condition** — embedding near the target question, so the retriever picks it up.
- **Generation condition** — when that document alone is the context, the LLM emits the attacker's chosen answer.

Tested across 8 LLMs and 3 corpora. Bigger databases are *not* safer. Standard defenses — paraphrasing, perplexity filtering, dedup, top-k expansion — all fail: ASR stays 41–93% across defenses.

OWASP 2025 LLM08 (*Vector and Embedding Weaknesses*) recognizes the class. The research frontier has pivoted from prevention to forensics (see *Traceback of Poisoning Attacks to RAG*, 2025).

## The takeaway

From the strongest critique of the paper's framing (accepted widely in the security community): **"Grounding is not a security boundary if your corpus isn't trustworthy."** RAG ingestion needs to behave like a software supply chain, not like input validation.

## How it maps onto `brain-core`

brain-core is a library. It does not own a public ingestion endpoint. The attack surface belongs to the **consuming agent** — whoever writes to the brain. The threats are all internal:

| Writer | Poisoning risk |
|---|---|
| The agent itself (hallucinated fact → `retain` or vault write) | High — most frequent writer |
| Auto-capture / background extraction | Medium — provisional, but searchable |
| External ingestion (distillation, scrapers, file imports) | Medium — external-origin content |
| Cross-agent shared writes | Medium — trust varies by agent |
| Reflection synthesis writes | **Highest leverage** — synthesized writes get laundered into "trusted" artifacts and become ground truth for future recall |

## Gates: what is built and what is planned

These are ingestion-time gates — the paper shows downstream defenses fail, so they belong at the write path. As of 0.5.1 two of the six are built, one is partly built and three are design intent. Each says which.

1. **Provisional-by-default writes (planned, not built)** — any entry written by an automated or external path must carry a `provisional: true` flag until it is explicitly promoted by a deliberate writer. Recall returns them with the flag visible; high-stakes callers filter them out. Today there is no `provisional` flag. What exists instead: what the capture hook files goes into the day's session notes, not into facts, and a transcript line ranks below written memory in recall.

2. **Source traceability (partly built)** — the design is that every memory entry carries a `source` field: `self-deliberate` | `self-auto` | `external:<id>` | `reflection:<parent_ids>`, with no anonymous memories. Built today: every recall result names the file and line it came from, and a `source` passed to `brain_remember` is kept in `record_meta.md`. Not built: `source` is optional, and the four-value vocabulary is not enforced. This is the library's answer to the paper's "we can't trace what poisoned us" problem.

3. **Reflection is a privileged ingestion path (planned, not built)** — a reflection write that surfaces a new fact (not traceable to at least one pre-existing entry via `parent_ids`) must be rejected, not persisted. Reflection synthesizes; it does not discover. Today no `parent_ids` check runs. What exists instead: the weekly reflection is appended to `knowledge/_reflections.md` under a header that calls it unverified, and that file is left out of the search index, so a reflection cannot come back from `brain_recall` as a fact.

4. **Contradiction flagging (built)** — updating a fact with a different value returns `contradiction` to the caller, writes the new line with a `⚠ Fact changed` banner, keeps the old line, and marks the old record `superseded` in recall. Silent overwrite is not possible: the vault is append-only.

5. **No external retrievers by default (built)** — `brain-core` does not pull from Wikipedia, web, or third-party knowledge bases. `brain_distill` fetches only the URL the agent passes, stores it unchanged in `raw/` with its sha256 and source, and never feeds it to facts by itself. If a consumer wires one in, they own the corpus-trust assessment and must document the ingestion gate in their `brain.yaml`.

6. **Consumer-owned trust policy (planned, not built)** — `brain.yaml` would define which sources are trusted for which operations (e.g., "auto-captured entries may feed recall but may not feed reflection synthesis"). brain-core would enforce the policy at the retrieval/synthesis boundary. No such setting exists in `brain.yaml` today.

## Also built, outside the six gates

- **A secret filter on every write, and a mask on every read.** Text that holds a credential is refused before any store sees it. The same patterns mask such text when a file written by hand is indexed, and again in every reply, in the session start block, the daily brief and the lessons hook. `brain_status` and `brain doctor` count the masked records (`secrets_masked`). What it knows: vendor formats (API keys, tokens, JWTs, private-key blocks, a password inside a URL, dash-joined licence keys) and a long mixed value after a label such as `key`, `token`, `password` or `secret`. What no pattern can see: a short password, a passphrase of plain words, a password with punctuation, digits alone, a random string with neither a label nor a vendor prefix. A match is masked or refused, never removed: the file still holds it, so rotate the credential and delete the line.
- **Original text can stay in `data/brain.db`.** Masking happens when a record is indexed. A transcript row indexed before a pattern knew its format, and a fact that 0.8.0 copied into the SQLite table, keep their original text in the database file. No reply returns it (replies are masked on the way out), but the file itself should be treated like the vault: private, not shared, not committed.
- **One match refuses the whole text.** `brain_remember`, `brain_distill` and `brain_session('end')` write nothing when any part of the text matches, including a `://user:password@` example in a page you distill. Remove the value and call again.
- **A weak match is said to be weak.** `brain_recall` returns `weak_match` when no record holds most of what was asked, which keeps a near miss from being read as an answer.
- **Files you can audit.** Every memory is a line in a markdown file with a date, so a poisoned entry can be found with grep and removed by hand.

## What leaves the machine

The vault, the database and the vector index stay on disk. What goes out depends on what you switch on:

| Feature | What is sent | To whom | Off by default? How to turn it off |
|---|---|---|---|
| Keyword recall, `brain_remember`, the record index | Nothing | | Always local |
| Vector search (`stores.vectors`) | Nothing about your memory. The embedding model (about 1.3 GB) is downloaded once | Hugging Face, for the download only. Once the model is on disk the worker loads it without contacting the hub | Off unless set |
| Model judge (`recall.judge: model`) | On every recall: the question and up to `recall.judge_candidates` records (default 50), up to 700 characters each. Credential-shaped text is masked when a record is indexed, and a record that still matches a pattern is withheld whole. Roughly 7,000 tokens a call | Anthropic: your API key (`runner: api`) or your own Claude Code login (`runner: claude`). The model is `claude-haiku-5-5` unless `recall.model` names another | Off unless set (`judge: agent` is the default: the calling agent reads the list itself) |
| Mental models (`brain models`) | Per model, per refresh: up to `models.records` records (default 150), up to 600 characters each; a record that matches a credential pattern is never sent | Anthropic, through `models.runner` | Runs only when you run it or schedule it |
| Hindsight (`stores.hindsight`) | The text of what you save and ask, to the Hindsight service you configured, and from there to the LLM it uses | Your Hindsight server and its LLM provider | Off unless set |
| `brain_distill` | A request for the page you name; the first run also fetches a pinned page reader from npm | The site you asked for, and npm | Only when called |
| Update check | A version lookup that sends nothing about you | PyPI, once a day | `cron.update_check: false` |

With the judge on, `brain_recall` tells the client it reaches outside the machine (`openWorldHint`).

## What this is *not*

- Not a claim that brain-core is poison-proof. A determined, authorized writer can still lie to their own brain.
- Not a replacement for the consumer's own threat model. If a consumer ships a public ingestion endpoint, that's their attack surface to document.
- Not a solved problem. The state of the art has not solved corpus poisoning — brain-core's posture is *raise the cost of the attack, expose every poisoned entry's lineage, refuse the highest-leverage poisoning paths by construction*.

## Consumers: questions to answer before shipping

- Where does each write to the brain originate? Is the source tagged?
- Can any automated path write directly to a "trusted" layer without human review?
- Does reflection have a path to create a new ground-truth fact without existing parent entries?
- If your corpus grew 10× tomorrow from an unvetted source, which of your answers would silently change?

If any of those answers are "I don't know," treat the brain as potentially poisoned and start with a source audit.
