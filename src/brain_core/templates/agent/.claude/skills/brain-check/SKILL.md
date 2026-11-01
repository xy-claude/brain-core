---
name: brain-check
description: Health check for this agent's brain. Use at session start when something feels off, before a critical task, or when $user says brain check, health check, is everything up, status. One brain_status call, reported as a table.
---

## Brain check

1. `brain_status()`.
2. Report:

```
Agent: <name> — Brain Check
Stores:      sqlite OK | vault OK | hindsight OK/DOWN (<detail>) | graph OK/absent
Knowledge:   <pages> pages, <raw> raw, <issue_count> lint issues → <first three>
Context:     <tokens> always-loaded tokens (<per-file breakdown>)
Session:     last start <id> · last close <id> · unclosed: yes/no
Pending:     <n> decisions waiting for $user
Status:      HEALTHY | DEGRADED | CRITICAL
```

3. Rules: any store down → **CRITICAL**, tell $user not to proceed until it is back (Hindsight: `launchctl kickstart -k gui/$(id -u)/io.vectorize.hindsight`, then `/mcp`). Lint issues or `unclosed: yes` → **DEGRADED**, say what to fix (`/distill --lint`, or read the unclosed session file). Context tokens above the number recorded in `vault/facts.md` → say by how much and what grew.
