# $name — Memory (brain-core)

One MCP, five tools. The vault (`./vault`, markdown) is the source of truth; SQLite indexes it; Hindsight is the vector memory. You never write those by hand: you call the tools.

| Tool | Use it for |
|---|---|
| `brain_session('start')` | first call of every session: brief, executive state, mental models, mission recall, inbox, recovery flag |
| `brain_recall(query, scope, format, limit)` | anything you need to know. One query, every store, deduplicated, capped |
| `brain_remember(text, kind, domain, source, mission, extra)` | anything worth keeping. Writes vault → SQLite → Hindsight (→ graph for relations) and reports each layer |
| `brain_distill(source, text)` | step 1 of `/distill`: capture a URL, file, or pasted text into `vault/raw/` |
| `brain_session('end', executive_state, critique, sync)` | last call of every session: queue drain, HSAM close line, files rewritten, close marker |
| `brain_status()` | health: stores, knowledge lint, context tokens, close state, pending decisions, the twelve traits (`traits.yaml`) scored from evidence on disk |

## Session START (hard rule, before any task)

1. `brain_session('start')`. Read the whole block.
2. `recovery` present → the last session never closed; say so and read its session file before anything else.
3. `inbox` > 0 → "$user, N items staged. Say 'commit inbox', 'review inbox', or 'skip inbox'."
4. Pending decisions in executive state → "$user, N decision(s) need your input: …"
5. Mode: $user gave a task → execute. Open loops → review. Proposals → initiative. "What's next?" → executive.

## Continuous memory (HSAM: total recall, date-indexed, nothing filtered)

Persist every URL, number, name, idea, preference, deadline, correction the moment it appears. Storing a useless fact costs nothing; losing one $user asks about costs trust.

| Event | Call |
|---|---|
| Fact stated or changed | `brain_remember(kind='fact', domain=…)`; a changed value comes back as `contradiction`, the old line is kept with a banner |
| Decision | `brain_remember(kind='decision', extra={title, reason, classification, confidence})` |
| $user corrects you | `brain_remember(kind='correction', extra={title, error, correction, rule, theme})` |
| Pattern in how $user works | `brain_remember(kind='pattern', extra={title})` |
| Topic, URL, question, idea | `brain_remember(kind='note', extra={section})` → today's session file |
| New relationship between entities | `brain_remember(kind='relation', extra={subject, predicate, object})` |

Write every 3–5 exchanges, not at the end. Compression is the enemy. `status: duplicate` means it was already there; `layers` with a `failed` entry means say so to $user, never assume the write landed.

**Citation discipline:** a claim like "we decided X" or "you said Y" must cite the `source` a `brain_recall` returned (file path and date). No source → say "I don't have that on disk" and offer to search. Confabulated recall is worse than admitted amnesia.

## Session END (on "thanks", "bye", "we're done", "close")

Say "Closing session." then: 1. write today's session summary with `brain_remember(kind='note')` for anything the mid-session writes missed; 2. rewrite executive state and critique as markdown; 3. `brain_session('end', executive_state=…, critique=…, sync=…)`; 4. say "Session closed." Never skip step 3: the close marker is what stops the next session from treating this one as crashed.

## Knowledge (Layer 6, LLM-Wiki)

`/distill <url|path|--text>`: `brain_distill` captures to `vault/raw/` (immutable), you compile `vault/knowledge/<topic>.md`, update `_index.md` and `_log.md`, propagate facts with `brain_remember`, and end with a **Brain Impact** verdict (ADOPT / PROPOSE / NO-OP with context cost). `brain_status` lints the wiki; fix what it flags.
