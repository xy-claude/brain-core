---
type: log
owner: fix
status: active
updated: 2026-11-02
---
# Decisions Log

## 2026-11-02 — Repo goes public, Hindsight required, generic rulebook default
**Decision:** brain-core becomes a public repository; the installer sets up Hindsight; the rulebook template is generic with a profile flag.
**Reason:** the raw install URL must resolve without a token.
**Classification:** reversible × low-risk
**Confidence:** high

## 2026-11-01 — Hindsight moves from cloud to self-hosted
**Decision:** run the open-source Hindsight server on the Mac with the claude-code provider and local embeddings.
**Reason:** no budget for the hosted plan; the software is MIT.
**Classification:** reversible × low-risk
**Confidence:** high

## 2026-09-25 — Delete the Colima VM
**Decision:** remove the local Supabase stack running in Colima; use the hosted project branches instead.
**Reason:** 20 GB of disk for a stack nobody used in a month.
**Classification:** reversible × low-risk
**Confidence:** medium
