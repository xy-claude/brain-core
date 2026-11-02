# Pinned issue draft: Roadmap and how to help

**Title:** Roadmap (pinned) — what is next, and good first issues

brain-core 0.3 is out: five `brain_*` tools, `brain init`, cron, one-line install on macOS and Linux, PyPI `brain-core-mcp`. This issue is the living roadmap; comment to vote or claim.

## Next

- [ ] **SQLite-only day-one mode** — run without Hindsight for the first session; vector recall becomes an upgrade, not a prerequisite. Removes the 2 GB first install. (#help-wanted)
- [ ] **Import an existing notes folder** — `brain import DIR` that reads markdown you already have into the vault kinds. (#good-first-issue for the facts.md half)
- [x] **Capture without asking** — shipped in 0.3.0 as the transcript index (`brain_recall scope='transcript'`) and the failure-recall hook (`brain recall --hook` on `PostToolUseFailure`). Nothing depends on the agent remembering to remember.
- [ ] **Windows** — `brain init` and the MCP already run; the installer and cron do not.
- [ ] **A second eval vault** — a public fixture from a real open-source project's history, so recall numbers are not only the author's.

## Good first issues

- `brain status --json` flag for scripts
- `brain init --list-skills` to show what the pack ships
- README: a "what the agent sees" section with real tool replies for each kind

## Not planned

Hosted mode, multi-user, a UI beyond Hindsight's control plane. Five tools stay five.

No classifier model in core. An optional extra for offline triage in cron (a small local decision model such as Laya, deciding kind, duplicate or stale) may come later, gated on two things: enough labelled `brain_remember` rows to fine-tune on, and a measured eval win over the rules it would replace that pays for the ~2 GB it adds. Claude already classifies for free on every live call.
