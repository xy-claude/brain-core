#!/bin/bash
# block-dangerous-bash.sh — PreToolUse hook for Bash
# Reads tool-call JSON from stdin, blocks destructive commands the user did NOT
# explicitly authorize, exits 0 (allow) or 2 (block with reason on stderr).
#
# Patterns blocked unconditionally:
#   - rm -rf with recursive force on dangerous paths
#   - git push --force / -f to main, master, production
#   - git reset --hard on a branch with unpushed work
#   - Anything that pipes curl/wget straight into bash/sh
#
# Protect first, ask second.
# 0.5-second annoyance; an accidental rm -rf is hours of recovery.

set -euo pipefail

# Read the tool-call payload from stdin (Claude Code provides JSON)
INPUT="$(cat)"

# Extract the bash command being run. Prefer jq if available, fall back to grep.
if command -v jq >/dev/null 2>&1; then
  CMD="$(printf '%s' "$INPUT" | jq -r '.tool_input.command // empty')"
else
  # Naive extraction: grab the first "command" string in the payload.
  CMD="$(printf '%s' "$INPUT" | sed -n 's/.*"command"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' | head -1)"
fi

# If we can't extract, allow (don't break legit calls)
if [ -z "$CMD" ]; then
  exit 0
fi

block() {
  # Print the reason to stderr; exit 2 tells Claude Code to block
  printf 'BLOCKED by block-dangerous-bash: %s\n' "$1" >&2
  printf 'Command: %s\n' "$CMD" >&2
  exit 2
}

# 1) rm -rf on dangerous targets
if printf '%s' "$CMD" | grep -Eq 'rm[[:space:]]+(-[a-zA-Z]*[rRfF][a-zA-Z]*[[:space:]]+|-rf[[:space:]]+|-fr[[:space:]]+|-Rf[[:space:]]+|-fR[[:space:]]+)'; then
  # check if path looks dangerous: /, ~, $HOME, ., .., or wildcards near root
  if printf '%s' "$CMD" | grep -Eq 'rm[[:space:]]+-[rRfF]+[[:space:]]+(/|~|\$HOME|\.|\*|\$\{HOME\})([[:space:]]|$)'; then
    block "rm -rf on critical path detected"
  fi
fi

# 2) git push --force / -f to protected branches
if printf '%s' "$CMD" | grep -Eq 'git[[:space:]]+push.*(--force|-f )'; then
  if printf '%s' "$CMD" | grep -Eq '(main|master|production|prod)([[:space:]]|$)'; then
    block "force-push to protected branch (main/master/production)"
  fi
fi

# 3) git reset --hard
if printf '%s' "$CMD" | grep -Eq 'git[[:space:]]+reset[[:space:]]+--hard'; then
  block "git reset --hard can wipe uncommitted work — use a safer alternative or confirm explicitly"
fi

# 4) curl/wget piped to shell
if printf '%s' "$CMD" | grep -Eq '(curl|wget)[[:space:]].*\|[[:space:]]*(bash|sh|zsh)([[:space:]]|$)'; then
  block "piping remote content directly to a shell is unsafe — download, inspect, then run"
fi

# 5) chmod 777 on broad targets
if printf '%s' "$CMD" | grep -Eq 'chmod[[:space:]]+(-R[[:space:]]+)?777'; then
  block "chmod 777 grants world-writable permissions — use the least-permissive mode that works"
fi

# 6) bypassing the gitleaks git hooks (2026-10-29)
# quoted strings stripped first so a "-n" inside a commit message does not trip it
if printf '%s' "$CMD" | sed -E "s/\"[^\"]*\"//g; s/'[^']*'//g" | grep -Eq 'git[[:space:]]+(commit|push)[^|;&]*(--no-verify|[[:space:]]-n([[:space:]]|$))|SKIP_GITLEAKS='; then
  block "git hooks bypass (--no-verify / SKIP_GITLEAKS) — the secret scan must run; fix the file instead"
fi

# All clear
exit 0
