# brain-core one-line installer (Windows 10 1809+, PowerShell 5.1 or 7).
#
#   & ([scriptblock]::Create((irm https://raw.githubusercontent.com/xy-claude/brain-core/main/install.ps1))) -Agent NAME [-User Alex] [-Dir C:\Agents\NAME] [-ProfileDir DIR] [-Ref v0.4.11]
#
# Idempotent: re-running skips what is already in place. Every step prints what it did.
# It never asks for secrets. Two things stay yours: `claude` login and `gh auth login`.
# Vault + SQLite only: Hindsight (the vector store) does not run on Windows yet, so the agent is
# initialised as `brain init --lite`. All five tools work; see README "Windows" for what differs.
param(
  [Parameter(Mandatory = $true)][string]$Agent,
  [string]$User = "the user",
  [string]$Dir = "",
  [string]$ProfileDir = "",
  [string]$Ref = ""
)
$ErrorActionPreference = "Stop"
if ($Agent -notmatch '^[A-Za-z0-9_-]+$') { [Console]::Error.WriteLine("-Agent must be letters, digits, '-' or '_' only (got '$Agent')"); exit 2 }
if (-not $Dir) { $Dir = Join-Path $HOME "Agents\$Agent" }
function Step($s) { Write-Host "`n== $s" -ForegroundColor White }
function Have($c) { [bool](Get-Command $c -ErrorAction SilentlyContinue) }
function Fail-OnError { if ($LASTEXITCODE) { exit $LASTEXITCODE } }
$env:Path = "$HOME\.local\bin;$env:ProgramFiles\Git\cmd;$env:Path"

Step "1/6 Git for Windows (Claude Code runs its hooks in Git Bash)"
if (Have git) { "present" } else {
  winget install --id Git.Git -e --source winget --accept-package-agreements --accept-source-agreements
  Fail-OnError
}

Step "2/6 uv"
if (Have uv) { "present" } else { irm https://astral.sh/uv/install.ps1 | iex }

Step "3/6 Claude Code"
if (Have claude) { "present" } else { irm https://claude.ai/install.ps1 | iex }

Step "4/6 brain-core$(if ($Ref) { " ($Ref)" })"
if ($Ref) { uv tool install --force "git+https://github.com/xy-claude/brain-core@$Ref" }
elseif (Have brain) { "brain present ($(brain version))" }
else { uv tool install brain-core-mcp }
Fail-OnError
uv tool update-shell  # puts %USERPROFILE%\.local\bin on the user PATH for new terminals

Step "5/6 Agent $Agent at $Dir (vault + SQLite; Hindsight is not available on Windows yet)"
if (Test-Path (Join-Path $Dir "brain.yaml")) { "already initialised, leaving it" } else {
  $initArgs = @("init", $Agent, "--path", $Dir, "--user", $User, "--lite")
  if ($ProfileDir) { $initArgs += @("--profile", $ProfileDir) }
  & brain @initArgs
  Fail-OnError
}

Step "6/6 Scheduled tasks (brain daily 06:07, brain weekly Sun 07:13), then doctor"
brain cron install $Dir
Fail-OnError
brain doctor $Dir

@"

Done. Still yours to do, once:
  claude            # sign in to Claude Code
  gh auth login     # GitHub, if the agent pushes (winget install GitHub.cli)

Then, in a NEW terminal so PATH is fresh: cd "$Dir"; claude
"@
