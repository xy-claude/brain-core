# Changelog

All notable changes. Format: [Keep a Changelog](https://keepachangelog.com). Versions follow SemVer; the tag `vX.Y.Z` must equal `pyproject.toml`.

## [Unreleased]

## [0.4.27] - 2026-11-09

### Fixed
- The recall-miss log never fired on an agent with Hindsight. A miss was "no results", and a vector store returns its nearest records for any query, so even a nonsense query came back with hits. A miss is now a recall where no written record holds half of the query's words; transcript lines do not count, because a transcript often holds the same question asked before. Measured on one live agent: 11 real queries scored 0.50 to 0.92, 8 absent topics 0.00 to 0.40.

### Added
- `brain_status` and `brain doctor` show `recall_misses`: how many recalls missed in the last 30 days and the five most asked queries. Each is a fact to write or an eval case to add. The daily brief already listed the week's misses.

## [0.4.26] - 2026-11-09

### Changed
- The install line is the same on macOS and Windows. Both README lines carry the agent, the user and the desktop flag, and both install Hindsight. On Windows Hindsight was opt-in; it is now the default, and `-Lite` skips it as `--lite` does on macOS. `-Hindsight` is still accepted and ignored, so a line copied earlier keeps working.
- No API key is needed for Hindsight. With no `--provider` (`-Provider`), the installer uses `anthropic` when `ANTHROPIC_API_KEY` is set and your Claude Code login otherwise, and says which. A provider you name needs its key in the shell: the installer stops before it changes anything.
- The Windows closing summary has a Hindsight line: running, NOT running, or not installed (lite).

### Fixed
- An install without an API key never got a running Hindsight: the server refuses to start for a provider whose key is missing, and the installer only printed a note.
- Running the install line again on an agent made lite installed Hindsight (about 2 GB) that its `brain.yaml` never used. A lite agent now stays lite.
- `--desktop` on Linux printed a failed connection. It is skipped with a message: the desktop app has no Linux build.

## [0.4.25] - 2026-11-09

### Changed
- README: the one-line install command is the first thing on the page, with a short options table (desktop app, quick install, full install) under it. The long introduction is five bullets, "Is it an MCP server or a tool?" sits below the five tools, and the step-by-step section is now "Install details". Requirements lists Windows. No code changed.

## [0.4.24] - 2026-11-09

### Added
- An update notice. Installed copies never updated by themselves and nothing told their owner a newer version existed. `brain daily` now asks PyPI once a day for the newest version and keeps the answer in `data/update.json`; when it is newer than the running one, the daily brief opens with an "Update available" line and `brain doctor` and `brain_status` show it, with the command to run. Nothing is installed automatically. `brain doctor` and `brain_status` read the file and never use the network. Switch the request off with `update_check: false` under `cron:` in `brain.yaml`. Existing agents get the check without editing anything, since the setting defaults to on.

## [0.4.23] - 2026-11-09

### Fixed
- A second run of an installer did not always upgrade `brain`: uv keeps PyPI's index for some minutes, so a release made in that time was not seen. The installers now upgrade with `--no-cache` (`uv tool upgrade` has no `--refresh`) and install with `--refresh`.
- On Windows, upgrading while the Claude desktop app is open makes uv print an error, because the app holds `brain.exe`. `install.ps1` now explains it: the new version is in place and is used once Claude is restarted. Its closing desktop check says the same when the app is still running the previous version.

## [0.4.22] - 2026-11-09

### Added
- `install.ps1 -Desktop` checks that the Claude desktop app has really loaded brain-core. The app reads its settings only at start, and closing its window does not stop it, so a correct install could still show nothing. The script now says whether the app is closed (brain-core loads at the next start), already has it, or is open without it; in the last case it explains how to quit from the tray icon, watches for up to five minutes, and reports what the app did.

## [0.4.21] - 2026-11-09

### Fixed
- `brain cron install` got no answer on a Windows PC with a third-party antivirus. Measured there: `schtasks /Create` started from PowerShell took 0.1 s; started from Python (directly, through cmd or through PowerShell) it never returned; Task Scheduler's own COM interface, called inside Python, took 0.4 s. brain-core now creates, finds and deletes its tasks through that interface and no longer launches `schtasks`. Tasks also start on battery power and catch up after the PC was off at the hour. `pywin32` is declared as a Windows dependency (it was already installed through `mcp`).
- `brain desktop` did not reach newer Microsoft Store builds of the Claude desktop app, which keep their settings in `%LOCALAPPDATA%\Claude-Data\<package>`; the entry was written to two folders that app never reads. That folder is now written too.

## [0.4.20] - 2026-11-09

### Changed
- `install.ps1` shows everything it does and ends with the truth. Downloads print how many MB have arrived; a connection that brings nothing for 60 seconds is an error with a message. Claude Code is fetched by the script itself, from the same source and with the same checksum test as its own installer, because that installer downloads 345 MB without a line on the screen (a five-minute limit had been stopping it mid-download). `brain cron install` says what it is doing before each step and lets Task Scheduler's own lines through. Long steps print "still working" every 15 seconds. The last lines are either "Install complete: every step above finished" or "Install NOT complete" with each step that did not work and how to run it again.
- Running an installer again upgrades a `brain` that is already installed (`uv tool upgrade`), so a second run brings the fixes of newer versions instead of keeping the old program.

## [0.4.19] - 2026-11-09

### Fixed
- `brain cron install` could wait for ever on Windows. `schtasks` ran with the console as its keyboard and no time limit, so a question nobody could see (from it, or from security software watching it) never got an answer. Every Task Scheduler call now runs with no keyboard and a 60-second limit, and a refusal is reported in one line instead of a traceback. The same limits apply to the registry and PowerShell calls of `brain hindsight install`.

### Changed
- `install.ps1` connects the Claude desktop app right after the agent is created, before the scheduled tasks. A task that cannot be created is reported and the install goes on; the memory does not need it.

## [0.4.18] - 2026-11-09

### Fixed
- On a PC with no Python, `uv tool install brain-core-mcp` fetched the newest Python (3.15), for which pyyaml has no ready-made package, and failed asking for a C++ compiler. Both installers now pass `--python 3.12`, and the package declares `requires-python >=3.12,<3.15`, so `uvx brain-core-mcp` and a manual install no longer end up on 3.15 either.

### Changed
- `install.ps1` installs Claude Code last. Its installer can stall in a child PowerShell on some PCs (it is given five minutes); everything the memory needs, including the desktop app entry, is now finished before that step.
- CI's installer job lets uv fetch its own Python, as a new PC must, checks that brain lands on 3.12, and uses an agent folder with a space in its path.

## [0.4.17] - 2026-11-09

### Changed
- `install.ps1` downloads uv itself: the zip from the project's GitHub release, with a five-minute limit, unpacked to `~\.local\bin`. uv's own installer is no longer run. On a real PC it sat silent in a child PowerShell although the child, astral.sh and GitHub all answered; before that it closed the window under the Restricted policy. The Claude Code installer still runs in a child, now for five minutes at most, after which the install goes on without it.

## [0.4.16] - 2026-11-09

### Changed
- `install.ps1` says what it is downloading before the uv and Claude Code steps, and runs those installers with `Start-Process -NoNewWindow -Wait` instead of through a pipe, so their own lines appear as they are printed. A first real run sat at "== 2/7 uv" with nothing on screen.

## [0.4.15] - 2026-11-09

### Fixed
- `install.ps1` closed the user's PowerShell window on a normal Windows PC. It ran uv's installer inside that window; uv's installer refuses the default `Restricted` execution policy and ends with `exit 1`, which ended the session. The uv and Claude Code installers now run in a child PowerShell with `-ExecutionPolicy Bypass`. A missing `winget`, a declined Git install or a failed Claude Code install is reported and the install goes on; only uv is required. CI runs the installer under the `Restricted` policy and checks that the session survives it.

## [0.4.14] - 2026-11-09

### Fixed
- The vault lock file lived inside the vault (`.brain.lock`). A sync service can evict a file there: iCloud turned it into a placeholder that a background process could not open, and every vault write then failed with `PermissionError` while Hindsight kept accepting the same items. The lock is now a file under `~/.cache/brain-core/locks/`, named after the path it guards. An old `.brain.lock` in a vault is ignored and can be deleted.
- `install.ps1` ended a failed step with `exit`, which closes the PowerShell window the documented one-liner runs in, taking the error message with it. It now throws, so the window stays and the reason is on screen.

### Added
- CI runs `install.ps1` end to end in Windows PowerShell 5.1 with no uv preinstalled, then checks the agent folder, both scheduled tasks, the desktop entry, and that the daily task really runs and writes its log.

## [0.4.13] - 2026-11-09

### Added
- `brain desktop [PATH]` connects an agent to the Claude desktop app on macOS and Windows: it adds one `brain` server to `claude_desktop_config.json` (a Microsoft Store install's package folder too, when present), keeps every other key, leaves a `.bak` the first time it changes a file, and refuses a file that is not valid JSON. `--config` names the file when it is elsewhere. `install.sh --desktop` and `install.ps1 -Desktop` run it at the end. The desktop chat gets the five tools on the same memory as Claude Code; it has no hooks, so the brief and the capture do not run there.

## [0.4.12] - 2026-11-09

### Added
- Hindsight on Windows. `brain hindsight install` writes a PowerShell launcher next to the env file (`~/.config/hindsight/hindsight.ps1`), registers it under the user's registry Run key so it starts at every logon without administrator rights, and starts it hidden; the launcher restarts the server five seconds after an exit and reads the key from the env file on each start. `install.ps1 -Hindsight` (with `-Provider`, `-ApiKeyEnv`) sets up a full agent; the default stays lite. `brain hindsight install --wait SECONDS` on every platform, for a slow first start. A CI job installs it for real on Windows and waits for `/health`.

### Fixed
- 0.4.11 said Hindsight "does not run on Windows". It does; brain-core had no way to install it there.

## [0.4.11] - 2026-11-09

### Added
- Windows. `install.ps1` is the one-line installer for PowerShell: Git for Windows, uv, Claude Code, `brain`, a lite agent and the two scheduled jobs. `brain cron install|status|uninstall` use Task Scheduler on Windows (`schtasks`, tasks `brain-core.<agent>.daily` and `.weekly`). The vault lock uses `msvcrt` there; it imported `fcntl` at module load before, so nothing in brain-core could start on Windows. Hindsight stays macOS and Linux only, so Windows agents run lite. CI runs the test suite and the stdio smoke test on Windows.

## [0.4.10] - 2026-11-07

### Fixed
- An agent made by `brain init` calls `brain` in its hooks, and every hook is silent on failure, so when `brain` was not on PATH (Claude Code started from a shell without the `uv tool` bin folder) the brief, capture and recall hooks did nothing and said nothing. The `SessionStart` hook now prints one line into the session when the command is missing, with the fix. `brain adopt` writes the same warning for a program path that has since disappeared. Existing agents: copy the `SessionStart` command from the template's `.claude/settings.json` into your own. `brain init --force` applies it too, but it also rewrites `brain.yaml`, `CLAUDE.md`, the rules and the settings (never the vault).

## [0.4.9] - 2026-11-07

### Fixed
- The task checkpoint (0.4.7) never appeared after a real compaction. Claude Code writes the compaction boundary to the transcript after the `SessionStart` hook has run, so the checkpoint looked for a boundary that was not on disk yet and returned nothing. It now reads the tail of the transcript, which is the stretch just summarised, and steps back one stretch only when the boundary has already landed. Witnessed on a real `/compact`.

## [0.4.8] - 2026-11-06

### Added
- `brain lessons`: past corrections that match a request. It compares the prompt with `corrections.md` by words alone (no model, no network), needs at least two shared subject words and a minimum tf-idf score, returns at most two, and stays silent otherwise. `brain lessons "<request>"` prints the matches and the words they matched on. As a hook it injects each correction once per session and logs a `lessons_injected` event. It is not wired by `brain init` or `brain adopt`; to turn it on, add a `UserPromptSubmit` hook: `{"hooks": [{"type": "command", "command": "brain lessons --hook --path <agent-dir> 2>/dev/null || true", "timeout": 5}]}`.

## [0.4.7] - 2026-11-06

### Added
- Task checkpoint after a compaction: when SessionStart fires with `source: compact`, `brain brief --hook` reads the stretch of the transcript that was just summarised and injects, ahead of the brief, the user's last three requests, the files edited with Edit or Write, and the last reply. It is stateless (nothing is written before the compaction), needs no new hook entry, logs a `checkpoint_injected` event, and stays silent when the transcript holds no compaction. Files changed through shell commands are not listed.
- `brain adopt <agent-dir> --vault PATH [--bank NAME] [--user NAME] [--peers GLOB] …`: puts an existing Claude Code agent folder on brain-core without touching its CLAUDE.md, skills or vault. Writes `brain.yaml`, adds the `brain` MCP server to `.mcp.json`, merges the four hooks into `settings.local.json` (or `settings.json`), renders the memory rule from the template, and backfills the SQLite index. Idempotent: every step reports written or kept. Without `--bank` the agent runs lite.

### Fixed
- Transcript index: an agent folder whose Claude Code project directory uses the older underscore naming is found again instead of indexing nothing.

## [0.4.6] - 2026-11-03

### Added
- Daily brief: a "Missions — blocked, stalled, competing" section (blocked missions with their next step, missions unreviewed for 14 days, more than two P1s) and a "Correction Patterns" section (any theme with three or more corrections, and whether a draft rule exists).
- Recall-miss log: a `brain_recall` that returns nothing logs a `recall_miss` event; the brief's Growth section lists the week's misses so they become facts or eval cases.

## [0.4.5] - 2026-11-03

### Added
- `brain init --lite` and `install.sh --lite`: vault + SQLite only, no Hindsight. The `hindsight:` block stays in `brain.yaml` commented for the upgrade; session start, status, daily and weekly all run without it. The CI recall eval already measures this configuration.
- `brain brief --hook`: a SessionStart hook that injects the daily brief as `additionalContext` and logs it; `brain_session('start')` then omits the brief for 15 minutes instead of repeating it, so the brief is never in context twice. The template `settings.json` wires it.
- `brain daily --shadow`: writes `<brief>.shadow.md` beside a brief another tool still owns, leaves that brief alone, and lists its sections missing from brain-core's, so a migration from another brief writer never loses a section.

## [0.4.4] - 2026-11-03

### Added
- `brain capture`: a Stop / PreCompact hook that files every user message and every URL from the live transcript into today's session file under "Said (hook)" and "Links (hook)", from where the last run stopped, deduplicated, secrets redacted. The template `settings.json` wires it. The hook never calls Hindsight: captures go through the session queue (`session.queue`, now `data/hindsight_queue.jsonl` by default in the template) and `brain_session('end')` drains them; without a queue they stay in the vault.

## [0.4.3] - 2026-11-03

### Added
- `brain_recall(offset=N)`: pagination. The reply carries `total` and, when more hits remain, `next_offset` plus a note saying where to continue; an offset past the end says so instead of "no hits".
- Per-call tool metrics: every MCP tool call records runtime, response tokens and an error flag in the `metrics` table. `brain_status` reports `tools` (calls, avg and p95 ms, avg tokens, errors per tool, last 30 days) with two diagnostics from Anthropic's tool-design guidance: a tool failing more than 10% of calls needs clearer parameter descriptions; recall answers near the cap need a lower `limit` or `offset`. `brain doctor` prints the same line.

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
