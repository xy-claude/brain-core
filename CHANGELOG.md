# Changelog

All notable changes. Format: [Keep a Changelog](https://keepachangelog.com). Versions follow SemVer; the tag `vX.Y.Z` must equal `pyproject.toml`.

## [Unreleased]

### Added
- The twelve traits (M21): `traits.yaml` ships in the agent pack; `brain_status()["traits"]` scores each from evidence on disk with signals marked defensible, cost or pending and counts instead of percentages below n=20; `brain daily` writes a Traits section into the brief and one line into `health_log.md`; `brain doctor` prints how many traits have grown. Taxonomy and signals in `docs/TRAITS.md`.

## [0.2.3] - 2026-11-02

### Fixed
- Installer: the LLM key now reaches Hindsight. launchd and systemd do not expand `${VAR}`; `brain hindsight install` writes the key to `~/.config/hindsight/env` (mode 600) and the service sources it. Re-run after exporting the key.
- `mcp` is a required dependency; `brain serve` works after `uv tool install brain-core-mcp` with no extra.
- `brain init --force` refreshes rules and skills but never overwrites existing `vault/` files.
- Titled decisions, corrections and patterns written twice are reported `exists` instead of duplicated; the vault id now matches what the parser reads back.
- Multi-line text is collapsed to one bullet line before writing, so its id and date survive a re-read.
- The Hindsight client re-initialises once when the server has restarted and forgotten the session, instead of failing every call until Claude Code restarts.
- `brain_session('end')` refuses a critique, executive state or sync body that looks like a secret, and drops queued entries that do.
- Two raw captures with the same title on one day no longer overwrite each other; an empty slug becomes `untitled`.
- Recall deduplicates by the full text, so two "Fact changed" banners that share a prefix are both returned.
- A mistyped date in a decision or correction heading no longer takes down `brain_recall` or `brain daily`.
- The template bash guard now blocks `rm -rf ~/`, `rm -rf /*`, `rm -r -f /`, `rm -rf $HOME/`, `bash -c "rm -rf /"` and `curl … | sudo bash`, and the hook path is quoted so it runs from a folder with a space. The guard has a test.
- Two processes applying the same new migration no longer crash the second one (`INSERT OR IGNORE`).
- Session start tolerates a non-UTF-8 byte in a vault file, the same as cron and status already did; one shared reader.
- Linux: crontab lines quote the agent path and log path, so a space in `$HOME` works; `brain cron status` reads the crontab instead of always saying "not installed".
- `brain init` and `install.sh` reject an agent name that is not letters, digits, `-` or `_`; the name becomes a folder, a launchd label, a crontab tag and a bank id.
- The Hindsight queue is drained under a lock and rewritten atomically, so a crash mid-drain cannot truncate it.
- The `bearer` secret pattern needs a digit in the token, so "bearer authentication-header" is an ordinary sentence again.
- `brain_distill` runs `npx defuddle` once, not twice, when the first call fails.
- Vault writes take one lock file per vault (`.brain.lock`) instead of one per file; `brain weekly` removes the per-file locks older versions left in `sessions/`.

### Removed
- v0.1 code nothing in v0.2 reached: the `decisions`, `reflection` and `memory.hsam` modules, `brain export`, the `mcp/tools.py` wrappers, the v0.1 `Agent` methods (`remember`, `recall`, `supersede`, `append_today`, `decide`, `reverse`, `complete`, `list_decisions`, `gather_context`, `save_reflection`, `template_summary`), and the `capabilities`, `memory`, `reflection`, `logging` and `version` keys of `brain.yaml`. A `brain.yaml` that still has those keys fails to load: delete them. About 1,370 source lines gone; the `brain doctor` output is now the `brain_status` report only.

### Added
- Tests for the backup prune loop, crontab and launchctl install paths, `brain daily`, `weekly`, `cron`, `serve` and `hindsight` commands, the YouTube subtitle parser, and the migration race.

## [0.2.2] - 2026-11-02

### Changed
- PyPI distribution name is `brain-core-mcp`; PyPI rejected `brain-core` as too similar to an existing project. Command `brain` and package `brain_core` unchanged.

## [0.2.1] - 2026-11-02

### Added
- Linux support: `install.sh` runs on Linux (uv, systemd user unit for Hindsight, user crontab for `brain daily` / `brain weekly`).
- Release pipeline: tag `v*` builds, tests, publishes to PyPI by trusted publishing, and creates a GitHub Release with these notes.
- `CHANGELOG.md`, `docs/RELEASING.md`.

### Changed
- `install.sh` installs from PyPI first and falls back to the git tag.

## [0.2.0] - 2026-11-02

### Added
- The five `brain_*` MCP tools: `brain_recall`, `brain_remember`, `brain_session`, `brain_distill`, `brain_status`.
- Store adapters: markdown vault, SQLite + FTS5, Hindsight (MCP over HTTP), entity graph as a SQLite relations table.
- `brain init` template pack: CLAUDE.md, five generic rule files, three skills, bash guard hook, `.mcp.json`, vault skeleton (3,014 always-loaded tokens); `--user`, `--profile`.
- `brain daily`, `brain weekly`, `brain cron install` (launchd).
- `install.sh` one-line installer for macOS; `brain hindsight install`; `brain doctor` on `brain_status`.
- Eval suite: 20-task fixture vault in CI, write scenarios; live recall evals on the author's vault at 100%.

### Removed
- The 14 one-tool-per-function MCP endpoints from v0.1 (still available as the Python API).
- Kuzu as the graph backend; `brain graph import` loads a legacy dump.
