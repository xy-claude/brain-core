# $name — System Rules

## Hard rules

- **Git staging:** stage only files you changed this session. Never `git add -A` or `git add .`. `git status` before every commit.
- **Commit authorship:** $user is the sole author. One short imperative subject line under 72 characters. No `Co-Authored-By`, no `Generated with`, no agent trailers.
- **Secrets:** never in a tracked file, a vault file, a Hindsight retain, or a chat reply. Keychain or an untracked `.env`. A blocked push means fix the file, never bypass the hook (`--no-verify`, `SKIP_GITLEAKS`).
- **Push needs $user.** "push" is the approval; nothing else is.
- **Verify before claim.** Paste the test or build output. "No error" is not "done". Witness a fix before reporting it.
- **Prior art first.** Before writing anything unfamiliar, search for two or three existing implementations and say what you reused.
- **Self-capability check.** Before recommending a tool, MCP, or service: can the current stack plus a rule do it? A missing rule is not a missing capability.
- **Context discipline.** Before adding an MCP, tool, agent, skill, or rule: "This adds N tokens to context. Proceed?" Prefer, in order: script or hook (zero context) → skill (loaded on use) → rule line (always loaded). `brain_status` reports the current number.

## Hooks

`.claude/hooks/block-dangerous-bash.sh` (PreToolUse on Bash) blocks `rm -rf` on critical paths, force-push to protected branches, `git reset --hard`, `curl | sh`, `chmod 777`, and hook bypasses. A block is feedback, not an obstacle: change the command.

## Procedures

`vault/procedures/<name>.md`: Purpose, Steps, Routing, Known Exceptions; frontmatter `status`, `last_validated`, `rigidity` (guide or strict). Match task → procedure → apply as a guide. Draft one after any workflow that took five or more tool calls, an error recovery, or a correction; $user approves drafts at session end.

## Scores

`brain_status` plus the session critique are the health signal. Memory failing → audit the vault and Hindsight reachability. Learning failing → `/distill --lint`. Structure failing → `brain doctor`.
