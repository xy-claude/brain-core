# Changelog

All notable changes. Format: [Keep a Changelog](https://keepachangelog.com). Versions follow SemVer; the tag `vX.Y.Z` must equal `pyproject.toml`.

## [Unreleased]

## [0.4.2] - 2026-11-03

### Added
- `session.peers` in `brain.yaml`: globs of other agents' sync files (`last_standalone_session.md`). `brain_session('start')` returns them as `peers`, newest first, first 15 lines each, the agent's own file skipped, and marks a peer idle after 7 days. Rule 04 step 5 reads it.

### Changed
- Docs and the legacy-graph live test no longer point at a private workspace; the test reads `BRAIN_LEGACY_GRAPH` and `BRAIN_LEGACY_PYTHON`.

## [0.4.1] - 2026-11-03

### Added
- `brain index <agent>`: loads the vault's `facts.md` and `patterns.md` into the SQLite FTS index, keeping each line's date and file position so recall ranks and cites them as the vault does. Idempotent; run it once after pointing `brain.yaml` at an existing vault.

### Fixed
- An agent configured on an existing vault had an empty SQLite fact index (`brain doctor` showed `sqlite facts=0`), so recall over facts had no full-text ranking.

## [0.4.0] - 2026-11-03

### Added
- `stores.notes` in `brain.yaml`: read-only markdown folders that `brain_recall` also searches, such as a vault `shared/` folder other agents write or Claude Code's own memory folder (`~/.claude/projects/<slug>/memory`). A file without `## ` sections is one record of its body.
- Missions as one file each: `goals/missions/*.md` with frontmatter (`mission_id`, `title`, `priority`, `status`, `next_step`, `last_reviewed`) is read by the daily brief agenda, the stalled-mission nudge and the goal trait, and wins over the `mission_queue.md` table when present.

- `brain daily` adds a Reinforce section: decisions resurface at 1, 3, 7 and 30 days.
- `brain weekly` writes one draft rule per theme that has three or more unpromoted corrections into `procedures/_drafts/rule-<theme>.md` (never overwritten; the agent approves or deletes), and one Hindsight reflection into `knowledge/_reflections.md`, marked unverified. The daily brief's Growth section points at both.

### Changed
- `brain_remember` no longer waits up to 30 s for Hindsight to finish a retain. It polls for one second so a fast failure is still reported, then returns `written` with the operation id and lets the server finish. A write that used to stall five seconds returns in one.
- Recall skips transcript lines younger than ten minutes: they are the conversation asking, not memory, and used to come back as the top hit.

## [0.3.1] - 2026-11-02

### Added
- Listed in the official MCP registry as `io.github.xy-claude/brain-core`: `server.json` at the repo root, the ownership marker in the README, and a release-workflow job that publishes each tag to the registry over OIDC after the PyPI upload.
- A second console script, `brain-core-mcp`, equal to `brain`, so `uvx brain-core-mcp serve DIR` runs the server with nothing installed.

## [0.3.0] - 2026-11-02

### Added
- Failure recall hook: the template's `settings.json` runs `brain recall --hook` on `PostToolUseFailure` for Bash. It takes the first line of the error, searches the transcript index, and returns up to three hits from earlier sessions as `additionalContext`, so a known error comes back with what was done about it last time. The current session is skipped; nothing is added when there is no hit. Zero always-loaded context; about 150 to 300 tokens per failing command that has a history.
- `brain recall QUERY [--scope] [--limit] [--path]` prints `brain_recall` hits from the shell, one line each.
- Transcript index: the Claude Code session files of the agent's folder (`~/.claude/projects/<cwd>/*.jsonl`) are indexed read-only into `brain.db` (FTS5), so `brain_recall` covers what past sessions said and ran before the agent remembered anything on purpose. `scope='transcript'` searches only them; `scope='all'` includes them. User and assistant text, Bash commands as `$ cmd`, other tool calls as `[Tool] target` and the first 400 characters of tool results are kept; thinking, images and hook chatter are not; key-shaped strings, the value after a password or token flag and bare 16-hex tokens are redacted before storage. Under `scope='all'` a transcript line ranks below written memory of the same relevance. Indexed on first recall in a process and by `brain daily`; a reindex reads only appended bytes. `stores.transcripts` in `brain.yaml` names the projects root; unset disables it.

## [0.2.6] - 2026-11-02

### Changed
- Tool definitions rewritten for agents that pick tools by description: each of the five tools now states what it does first, when to use it instead of its siblings, and the behaviour the schema cannot show (read-only, never deletes, fetches the network, overwrites on repeat). Every parameter has a schema description and every tool carries MCP annotations (`readOnlyHint`, `destructiveHint`, `idempotentHint`, `openWorldHint`). `tdqs lint` goes from 9 warnings to 0. No behaviour change.

## [0.2.5] - 2026-11-02

### Fixed
- `mcp` is pinned below 2. A clean `pip install brain-core-mcp` resolved `mcp` 2.x, whose FastMCP import no longer matches the 1.x API, so `brain serve` failed on every fresh install of 0.2.2 through 0.2.4 while CI stayed green on the lock file. CI now also installs the built wheel into a clean environment and introspects the stdio server.

### Added
- `Dockerfile`: the stdio MCP server in a container with a default agent, for registries that start a server and introspect it. No Hindsight inside the image.

## [0.2.4] - 2026-11-02

### Added
- The growth loops (M22): the daily brief gains a Growth section with three read-only nudges, a correction theme that recurred since its rule was promoted, a mission not reviewed for 14 days, a pending decision that has waited 14 days; `brain daily` keeps the first-seen date per pending decision in `data/pending_seen.json`; `brain_session('start')` snapshots the defensible trait signals and `brain_session('end')` reports which moved (`traits_moved`) and notes the count in the session's close line; metacognition gains a calibration signal, the Brier score of stated confidence against outcomes over resolved decisions (a later correction that names the decision is a miss, thirty days without one is a hold, younger ones are censored).
- The growth eval (M23): the fixture recall set is stratified into single-hop, multi-hop, knowledge-update, abstention and temporal items (the LoCoMo and LongMemEval slices) and run three times, a hit only when all three hit (pass^3); `run_recall.py --out data/eval.json` records the slices and the two pending memory signals read them; a CI test asserts the fixture brain after thirty days of sessions scores higher than the same brain on day one on every defensible trait signal. Every signal now carries `better: higher|lower`.
- Recall ranks a value that a `⚠ Fact changed` banner superseded below the banner; the old line stays on disk and in the results, it just never outranks the new value.
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
