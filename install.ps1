# brain-core one-line installer (Windows 10 1809+, PowerShell 5.1 or 7).
#
#   & ([scriptblock]::Create((irm https://raw.githubusercontent.com/xy-claude/brain-core/main/install.ps1))) -Agent NAME [-User Alex] [-Dir C:\Agents\NAME] [-Desktop] [-Hindsight] [-Provider anthropic|openai|claude-code] [-ApiKeyEnv VAR] [-ProfileDir DIR] [-Ref v0.4.19]
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

# Claude Code's installer ends with `exit`, which would close this window, so it runs in a child
# PowerShell, and never for longer than the limit: a first real run sat in a child with no output.
function Run-Installer($url, $minutes) {
  Write-Host "running the installer from $url in a separate PowerShell (up to $minutes minutes)"
  $p = Start-Process powershell -ArgumentList "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", "irm $url | iex" -NoNewWindow -PassThru
  $null = $p.Handle  # without this, ExitCode is empty for a process started without -Wait
  if (-not $p.WaitForExit($minutes * 60000)) {
    try { $p.Kill() } catch { }
    Write-Host "gave up after $minutes minutes"
    return $false
  }
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
if (Have uv) { "present" } else {
  # Downloaded here, not through uv's own installer: that script refuses the Restricted execution
  # policy and ends with `exit`, and in a child PowerShell it sat silent on a real PC (2026-11-09).
  $cpu = if ($env:PROCESSOR_ARCHITEW6432) { $env:PROCESSOR_ARCHITEW6432 } else { $env:PROCESSOR_ARCHITECTURE }
  $arch = switch ($cpu) { "ARM64" { "aarch64" } "x86" { "i686" } default { "x86_64" } }
  $zip = Join-Path $env:TEMP "uv-$arch-pc-windows-msvc.zip"
  $bin = Join-Path $HOME ".local\bin"
  "downloading uv for $arch from github.com (about 15 MB, up to 5 minutes on a slow line)"
  $ProgressPreference = "SilentlyContinue"  # the progress bar makes Windows PowerShell downloads many times slower
  Invoke-WebRequest -UseBasicParsing -TimeoutSec 300 -OutFile $zip "https://github.com/astral-sh/uv/releases/latest/download/uv-$arch-pc-windows-msvc.zip"
  New-Item -ItemType Directory -Force $bin | Out-Null
  tar -xf $zip -C $bin  # Expand-Archive is a script module, which the Restricted policy will not load
  if ($LASTEXITCODE) { throw "could not unpack $zip" }
  Remove-Item $zip
  if (-not (Have uv)) { throw "uv was unpacked to $bin but does not start from there" }
  "installed $(uv --version) to $bin"
}

Step "3/7 brain-core$(if ($Ref) { " ($Ref)" })"
# --python 3.12: left to itself uv fetches the newest Python, and a dependency without a ready-made
# package for it then needs a C++ compiler (pyyaml on 3.15, seen on a real PC 2026-11-09)
if ($Ref) { uv tool install --python 3.12 --force "git+https://github.com/xy-claude/brain-core@$Ref" }
elseif (Have brain) { "brain present ($(brain version))" }
else { uv tool install --python 3.12 brain-core-mcp }
Fail-OnError
uv tool update-shell  # puts %USERPROFILE%\.local\bin on the user PATH for new terminals

Step "4/7 Agent $Agent at $Dir"
if (Test-Path (Join-Path $Dir "brain.yaml")) { "already initialised, leaving it" } else {
  $initArgs = @("init", $Agent, "--path", $Dir, "--user", $User)
  if (-not $Hindsight) { $initArgs += "--lite" }
  if ($ProfileDir) { $initArgs += @("--profile", $ProfileDir) }
  & brain @initArgs
  Fail-OnError
}

if ($Hindsight) {
  Step "5/7 Hindsight (vector store; the first start downloads a database and a model)"
  $hsArgs = @("hindsight", "install", "--provider", $Provider, "--wait", "600")
  if ($ApiKeyEnv) { $hsArgs += @("--api-key-env", $ApiKeyEnv) }
  & brain @hsArgs
  if ($LASTEXITCODE) { "Hindsight is not healthy yet; the agent still works. Check again with: brain hindsight status" }
} else {
  Step "5/7 Hindsight skipped (lite). Later: brain hindsight install, then uncomment it in brain.yaml"
}

if ($Desktop) {
  Step "+ Claude desktop app (-Desktop)"
  brain desktop $Dir
  if ($LASTEXITCODE) { "not connected; in the app open Settings > Developer > Edit Config, then: brain desktop `"$Dir`" --config <that file>" }
}

# From here on nothing is required: the memory is installed and, with -Desktop, connected.
Step "6/7 Scheduled tasks (brain daily 06:07, brain weekly Sun 07:13), then doctor"
brain cron install $Dir
if ($LASTEXITCODE) { "the scheduled tasks were not created; the memory works without them. Later: brain cron install `"$Dir`"" }
brain doctor $Dir

# Last on purpose: everything above is finished before the one step that can stall, and the
# desktop app does not need it.
Step "7/7 Claude Code (the memory above is ready without it; Ctrl+C here loses nothing)"
if (Have claude) { "present" }
elseif (-not (Run-Installer "https://claude.ai/install.ps1" 5)) { "Claude Code was not installed. The memory still works in the Claude desktop app; for Claude Code see https://code.claude.com/docs/en/setup" }

@"

Done. Still yours to do, once:
  claude            # sign in to Claude Code
  gh auth login     # GitHub, if the agent pushes (winget install GitHub.cli)

Then, in a NEW terminal so PATH is fresh: cd "$Dir"; claude
"@
