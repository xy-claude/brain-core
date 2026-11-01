#!/bin/bash
# brain-core one-line installer (macOS and Linux).
#
#   curl -fsSL https://raw.githubusercontent.com/xy-claude/brain-core/main/install.sh | bash -s -- --agent NAME [--user Alex] [--dir ~/Agents/NAME] [--provider anthropic|openai|claude-code] [--profile DIR] [--dashboard] [--ref v0.2.1]
#
# Idempotent: re-running skips what is already in place. Every step prints what it did.
# It never asks for secrets. Three things stay yours: `claude` login, `gh auth login`, SSH keys.
set -euo pipefail

AGENT=""; USER_NAME="the user"; DIR=""; PROFILE=""; DASHBOARD=0; REF=""; PROVIDER="anthropic"; KEY_ENV=""
while [ $# -gt 0 ]; do
  case "$1" in
    --agent) AGENT="$2"; shift 2;;
    --user) USER_NAME="$2"; shift 2;;
    --dir) DIR="$2"; shift 2;;
    --profile) PROFILE="$2"; shift 2;;
    --dashboard) DASHBOARD=1; shift;;
    --provider) PROVIDER="$2"; shift 2;;
    --api-key-env) KEY_ENV="$2"; shift 2;;
    --ref) REF="$2"; shift 2;;
    -h|--help) sed -n '2,8p' "$0"; exit 0;;
    *) echo "unknown option: $1" >&2; exit 2;;
  esac
done
[ -n "$AGENT" ] || { echo "usage: install.sh --agent NAME [--user Alex] [--dir PATH] [--provider anthropic|openai|claude-code] [--api-key-env VAR] [--profile DIR] [--dashboard] [--ref TAG]" >&2; exit 2; }
DIR="${DIR:-$HOME/Agents/$AGENT}"
OS="$(uname -s)"
case "$OS" in Darwin|Linux) ;; *) echo "install.sh supports macOS and Linux (got $OS)" >&2; exit 1;; esac

step() { printf '\n\033[1m== %s\033[0m\n' "$*"; }
have() { command -v "$1" >/dev/null 2>&1; }
export PATH="$HOME/.local/bin:/opt/homebrew/bin:$PATH"

if [ "$OS" = "Darwin" ]; then
  step "1/8 Xcode command line tools (git)"
  if xcode-select -p >/dev/null 2>&1; then echo "present"; else xcode-select --install || true; echo "finish the macOS dialog, then re-run this script"; exit 1; fi

  step "2/8 Homebrew"
  if have brew; then echo "present"; else
    /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
  fi
  [ -x /opt/homebrew/bin/brew ] && eval "$(/opt/homebrew/bin/brew shellenv)"

  step "3/8 uv, gh, gitleaks, node, Claude Code"
  for pkg in uv gh gitleaks node; do have "$pkg" && echo "$pkg present" || brew install "$pkg"; done
  if have claude; then echo "claude present ($(claude --version 2>/dev/null | head -1))"; else brew install --cask claude-code || npm install -g @anthropic-ai/claude-code; fi
else
  step "1/8 git, curl"
  for pkg in git curl; do have "$pkg" || { echo "$pkg is required: install it with your package manager, then re-run" >&2; exit 1; }; done; echo "present"

  step "2/8 uv"
  if have uv; then echo "present"; else curl -LsSf https://astral.sh/uv/install.sh | sh; fi

  step "3/8 node, Claude Code (gh and gitleaks optional on Linux)"
  if have node; then echo "node present"; else echo "node not found: install Node 18+ (https://nodejs.org or your package manager) for Claude Code"; fi
  if have claude; then echo "claude present"; elif have npm; then npm install -g @anthropic-ai/claude-code; else echo "skipping Claude Code (no npm)"; fi
fi

step "4/8 brain-core${REF:+ ($REF)}"
if [ -n "$REF" ]; then
  uv tool install --force "git+https://github.com/xy-claude/brain-core@$REF"
elif have brain; then
  echo "brain present ($(brain version))"
else
  uv tool install brain-core || uv tool install "git+https://github.com/xy-claude/brain-core@main"
fi

step "5/8 Agent $AGENT at $DIR"
if [ -f "$DIR/brain.yaml" ]; then echo "already initialised, leaving it"; else
  ARGS=(init "$AGENT" --path "$DIR" --user "$USER_NAME"); [ -n "$PROFILE" ] && ARGS+=(--profile "$PROFILE")
  brain "${ARGS[@]}"
fi

step "6/8 Hindsight (required store)"
HS_ARGS=(hindsight install --provider "$PROVIDER"); [ -n "$KEY_ENV" ] && HS_ARGS+=(--api-key-env "$KEY_ENV"); [ "$DASHBOARD" = 1 ] && HS_ARGS+=(--dashboard)
if [ "$PROVIDER" != "claude-code" ]; then KEY_VAR="${KEY_ENV:-$(echo "$PROVIDER" | tr a-z A-Z)_API_KEY}"; [ -n "${!KEY_VAR:-}" ] || echo "note: $KEY_VAR is not set in this shell; Hindsight needs it to reason. Export it, then restart the service (brain hindsight install is safe to re-run)."; fi
brain "${HS_ARGS[@]}"

step "7/8 Cron (brain daily 06:07, brain weekly Sun 07:13)"
brain cron install "$DIR"

step "8/8 Doctor"
brain doctor "$DIR" || true

cat <<EOF

Done. Still yours to do, once:
  claude            # sign in to Claude Code
  export ANTHROPIC_API_KEY=...   # unless --provider claude-code (personal use only)
  gh auth login     # GitHub, if the agent pushes
  ssh-keygen ...    # keys for your GitHub accounts, if any

Then: cd "$DIR" && claude
EOF
