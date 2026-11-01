# Contributing

Thanks for looking. brain-core is small on purpose; the best pull request is the one that removes a line.

## Setup

```bash
git clone https://github.com/xy-claude/brain-core && cd brain-core
uv sync --all-extras --all-groups
uv run pytest            # 200+ tests, includes the fixture eval, no network
uv run ruff check src tests && uv run ruff format --check src tests && uv run mypy
```

CI runs exactly those four commands. If they pass locally they pass there.

## Ground rules

- **Five tools stay five.** A new capability goes inside an existing `brain_*` tool or into `brain daily`, not into a sixth tool. The point of the project is an agent that never has to choose between 30 endpoints.
- **Context is a budget.** Anything added to the template pack (`src/brain_core/templates/agent/`) must state its token cost in the PR. Rules are always loaded; skills load on use; scripts and hooks cost nothing. Prefer the cheaper one.
- **The vault is readable.** Markdown layouts are documented in `docs/VAULT_SCHEMA.md`. A write that a human cannot read in Obsidian is a bug.
- **Evals before claims.** A change to recall or remember comes with an eval row in `tests/eval/` that fails without it.
- **No secrets, anywhere.** gitleaks runs in CI and the vault refuses token-shaped text. If you need a key for a test, it comes from the environment and the test skips when it is absent.
- **Failed layers are reported, never swallowed.** Every store call returns a status; a `try/except: pass` will not be merged.

## Pull requests

One change per PR. Subject line under 72 characters in the imperative. Describe what breaks without the change. No attribution trailers.

## Reporting a bug

Use the bug template. `brain doctor` output and `brain version` save a round trip.
