# Changelog

All notable changes. Format: [Keep a Changelog](https://keepachangelog.com). Versions follow SemVer; the tag `vX.Y.Z` must equal `pyproject.toml`.

## [Unreleased]

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
