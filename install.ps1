# brain-core one-line installer (Windows 10 1809+, PowerShell 5.1 or 7).
#
#   & ([scriptblock]::Create((irm https://raw.githubusercontent.com/xy-claude/brain-core/main/install.ps1))) -Agent NAME [-User Alex] [-Dir C:\Agents\NAME] [-Desktop] [-Hindsight] [-Provider anthropic|openai|claude-code] [-ApiKeyEnv VAR] [-ProfileDir DIR] [-Ref v0.4.15]
#
# Idempotent: re-running skips what is already in place. Every step prints what it did.
# It never asks for secrets. Two things stay yours: `claude` login and `gh auth login`.
# Default is lite: vault + SQLite, installed in about a minute. -Hindsight adds the vector store
# (about 2 GB, a few minutes): it runs in the background and starts again at every logon.
param(
  [Parameter(Mandatory = $true)][string]$Agent,
  [string]$User = "the user",
  [string]$Dir = "",
  [switch]$Hindsight,
  [switch]$Desktop,
  [string]$Provider = "anthropic",
  [string]$ApiKeyEnv = "",
  [string]$ProfileDir = "",
  [string]$Ref = ""
)
$ErrorActionPreference = "Stop"
# throw, never exit: the documented one-liner runs this in the user's own window, and exit closes it
if ($Agent -notmatch '^[A-Za-z0-9_-]+$') { throw "-Agent must be letters, digits, '-' or '_' only (got '$Agent')" }
if (-not $Dir) { $Dir = Join-Path $HOME "Agents\$Agent" }
function Step($s) { Write-Host "`n== $s" -ForegroundColor White }
function Have($c) { [bool](Get-Command $c -ErrorAction SilentlyContinue) }
function Fail-OnError { if ($LASTEXITCODE) { throw "the last step failed with exit code $LASTEXITCODE; the lines above say why" } }
$env:Path = "$HOME\.local\bin;$env:ProgramFiles\Git\cmd;$env:Path"

# Other people's installers run in a child PowerShell: they end with `exit`, which would close this
# window, and uv's refuses the Restricted execution policy a new Windows PC ships with.
function Run-Installer($url) {
  Write-Host "downloading and installing from $url (this can take a minute or two; if nothing moves, press Esc once: a click in this window pauses it)"
  # Start-Process, no pipe: the child writes straight to this console, so its lines show as they come
  $p = Start-Process powershell -ArgumentList "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", "irm $url | iex" -NoNewWindow -Wait -PassThru
  return $p.ExitCode -eq 0
}

Step "1/7 Git for Windows (Claude Code runs its hooks in Git Bash)"
if (Have git) { "present" }
elseif (-not (Have winget)) { "skipped: no winget on this PC. Claude Code needs Git: https://git-scm.com/download/win" }
else {
  winget install --id Git.Git -e --source winget --accept-package-agreements --accept-source-agreements
  if ($LASTEXITCODE) { "Git was not installed (exit code $LASTEXITCODE). Claude Code needs it: https://git-scm.com/download/win" }
}

Step "2/7 uv"
if (Have uv) { "present" }
elseif (-not (Run-Installer "https://astral.sh/uv/install.ps1")) { throw "uv could not be installed; the lines above say why" }

Step "3/7 Claude Code"
if (Have claude) { "present" }
elseif (-not (Run-Installer "https://claude.ai/install.ps1")) { "Claude Code was not installed. The memory still works in the Claude desktop app; for Claude Code see https://code.claude.com/docs/en/setup" }

Step "4/7 brain-core$(if ($Ref) { " ($Ref)" })"
if ($Ref) { uv tool install --force "git+https://github.com/xy-claude/brain-core@$Ref" }
elseif (Have brain) { "brain present ($(brain version))" }
else { uv tool install brain-core-mcp }
Fail-OnError
uv tool update-shell  # puts %USERPROFILE%\.local\bin on the user PATH for new terminals

Step "5/7 Agent $Agent at $Dir"
if (Test-Path (Join-Path $Dir "brain.yaml")) { "already initialised, leaving it" } else {
  $initArgs = @("init", $Agent, "--path", $Dir, "--user", $User)
  if (-not $Hindsight) { $initArgs += "--lite" }
  if ($ProfileDir) { $initArgs += @("--profile", $ProfileDir) }
  & brain @initArgs
  Fail-OnError
}

if ($Hindsight) {
  Step "6/7 Hindsight (vector store; the first start downloads a database and a model)"
  $hsArgs = @("hindsight", "install", "--provider", $Provider, "--wait", "600")
  if ($ApiKeyEnv) { $hsArgs += @("--api-key-env", $ApiKeyEnv) }
  & brain @hsArgs
  if ($LASTEXITCODE) { "Hindsight is not healthy yet; the agent still works. Check again with: brain hindsight status" }
} else {
  Step "6/7 Hindsight skipped (lite). Later: brain hindsight install, then uncomment it in brain.yaml"
}

Step "7/7 Scheduled tasks (brain daily 06:07, brain weekly Sun 07:13), then doctor"
brain cron install $Dir
Fail-OnError
brain doctor $Dir

if ($Desktop) {
  Step "+ Claude desktop app (-Desktop)"
  brain desktop $Dir
  if ($LASTEXITCODE) { "not connected; in the app open Settings > Developer > Edit Config, then: brain desktop `"$Dir`" --config <that file>" }
}

@"

Done. Still yours to do, once:
  claude            # sign in to Claude Code
  gh auth login     # GitHub, if the agent pushes (winget install GitHub.cli)

Then, in a NEW terminal so PATH is fresh: cd "$Dir"; claude
"@
