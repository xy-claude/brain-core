# brain-core one-line installer (Windows 10 1809+, PowerShell 5.1 or 7).
#
#   & ([scriptblock]::Create((irm https://raw.githubusercontent.com/xy-claude/brain-core/main/install.ps1))) -Agent NAME [-User Alex] [-Dir C:\Agents\NAME] [-Desktop] [-Lite] [-Provider anthropic|openai|claude-code] [-ApiKeyEnv VAR] [-ProfileDir DIR] [-Ref v0.7.0]
#
# Idempotent: re-running skips what is already in place. Every step prints what it did.
# It never asks for secrets. Two things stay yours: `claude` login and `gh auth login`.
# Hindsight, the vector store, is installed by default (about 2 GB, a few minutes): it runs in the
# background and starts again at every logon. -Lite skips it: vault + SQLite, about a minute.
param(
  [Parameter(Mandatory = $true)][string]$Agent,
  [string]$User = "the user",
  [string]$Dir = "",
  [switch]$Lite,
  [switch]$Hindsight,  # ignored: Hindsight is the default now, and lines written when it was opt-in still run
  [switch]$Desktop,
  [string]$Provider = "",
  [string]$ApiKeyEnv = "",
  [string]$ProfileDir = "",
  [string]$Ref = ""
)
$ErrorActionPreference = "Stop"
# throw, never exit: the documented one-liner runs this in the user's own window, and exit closes it
if ($Agent -notmatch '^[A-Za-z0-9_-]+$') { throw "-Agent must be letters, digits, '-' or '_' only (got '$Agent')" }
if (-not $Dir) { $Dir = Join-Path $HOME "Agents\$Agent" }
# Hindsight does not start for a provider whose key is missing. So with no -Provider: anthropic
# when its key is in this window, otherwise the Claude Code login. A named provider needs its key.
if (-not $Provider) {
  $keyVar = if ($ApiKeyEnv) { $ApiKeyEnv } else { "ANTHROPIC_API_KEY" }
  if ([Environment]::GetEnvironmentVariable($keyVar)) { $Provider = "anthropic" } else { $Provider = "claude-code"; $ApiKeyEnv = "" }
} elseif ($Provider -ne "claude-code" -and -not $Lite) {
  $keyVar = if ($ApiKeyEnv) { $ApiKeyEnv } else { "$($Provider.ToUpper())_API_KEY" }
  if (-not [Environment]::GetEnvironmentVariable($keyVar)) { throw "-Provider $Provider needs $keyVar set in this window: set it and run this line again, or leave -Provider out to use your Claude Code login" }
}
function Step($s, $color = "White") { Write-Host "`n== $s" -ForegroundColor $color }
function Have($c) { [bool](Get-Command $c -ErrorAction SilentlyContinue) }
function Fail-OnError { if ($LASTEXITCODE) { throw "the last step failed with exit code $LASTEXITCODE; the lines above say why" } }
$env:Path = "$HOME\.local\bin;$env:ProgramFiles\Git\cmd;$env:Path"

# Nothing in this script waits or downloads without saying so. On a real PC three steps looked
# frozen: two were silent downloads (one of 345 MB), one a hidden question (2026-11-09).
$problems = @()  # every step that did not work, repeated in the last lines
$brainChanged = $false  # true when this run replaced an older brain
$cpu = if ($env:PROCESSOR_ARCHITEW6432) { $env:PROCESSOR_ARCHITEW6432 } else { $env:PROCESSOR_ARCHITECTURE }
[Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12

# Downloads a file and prints how far it is, about every twentieth of it. A connection that
# brings nothing for 60 seconds is an error with a message, not a wait.
function Get-File($url, $path, $what) {
  $req = [Net.HttpWebRequest]::Create($url)
  $req.Timeout = 30000
  $req.ReadWriteTimeout = 60000
  $resp = $req.GetResponse()
  $total = $resp.ContentLength
  $in = $resp.GetResponseStream()
  $out = [IO.File]::Create($path)
  $buf = New-Object byte[] 1048576
  $done = 0
  $next = 0
  try {
    while (($n = $in.Read($buf, 0, $buf.Length)) -gt 0) {
      $out.Write($buf, 0, $n)
      $done += $n
      if ($done -ge $next) {
        Write-Host ("  {0}: {1} of {2} MB" -f $what, [int]($done / 1MB), [int]($total / 1MB))
        $next = $done + [Math]::Max(1MB, [int64]($total / 20))
      }
    }
  } finally { $out.Close(); $in.Close(); $resp.Close() }
  if ($total -gt 0 -and $done -ne $total) { throw "the download of $what stopped at $done of $total bytes" }
  Write-Host ("  {0}: downloaded, {1} MB" -f $what, [int]($done / 1MB))
}

# Runs a program, says every 15 seconds that it is still going, and stops it at a limit that is
# far beyond what the step needs.
function Run-Bounded($file, $arguments, $seconds) {
  $p = Start-Process $file -ArgumentList $arguments -NoNewWindow -PassThru
  $null = $p.Handle  # without this, ExitCode is empty for a process started without -Wait
  $waited = 0
  while (-not $p.WaitForExit(15000)) {
    $waited += 15
    if ($waited -ge $seconds) {
      try { $p.Kill() } catch { }
      Write-Host "  stopped: not finished after $seconds seconds" -ForegroundColor Red
      return $false
    }
    Write-Host "  still working ($waited of at most $seconds seconds)"
  }
  return $p.ExitCode -eq 0
}

# The Claude desktop app, not the Claude Code program of the same name in .local\bin.
function Get-ClaudeApp { Get-CimInstance Win32_Process -Filter "Name='claude.exe'" | Where-Object { $_.ExecutablePath -and $_.ExecutablePath -notlike "*\.local\bin\*" } }
# True once the desktop app itself has started `brain serve`: the proof that it read the setting.
function Test-ClaudeLoadedBrain {
  $apps = @(Get-ClaudeApp | ForEach-Object { $_.ProcessId })
  [bool](Get-CimInstance Win32_Process -Filter "Name='brain.exe'" | Where-Object { $_.CommandLine -like "* serve *" -and $apps -contains $_.ParentProcessId })
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
  $arch = switch ($cpu) { "ARM64" { "aarch64" } "x86" { "i686" } default { "x86_64" } }
  $zip = Join-Path $env:TEMP "uv-$arch-pc-windows-msvc.zip"
  $bin = Join-Path $HOME ".local\bin"
  "downloading uv for $arch from github.com"
  Get-File "https://github.com/astral-sh/uv/releases/latest/download/uv-$arch-pc-windows-msvc.zip" $zip "uv"
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
elseif (Have brain) {
  # A second run of this script brings the fixes of newer versions. --no-cache: uv keeps PyPI's
  # index for some minutes, and a release made in that time is invisible without it (upgrade has
  # no --refresh).
  $before = "$(brain version)"
  uv tool upgrade --no-cache brain-core-mcp
  $upgradeError = [bool]$LASTEXITCODE
  $after = "$(brain version)"
  $brainChanged = $after -ne $before
  "brain $after$(if ($brainChanged) { " (was $before)" })"
  if ($upgradeError) { "uv reported an error above. When the Claude app is open it holds brain.exe and uv cannot replace that file; the version shown here is in place and is used once Claude is restarted." }
}
else { uv tool install --python 3.12 --refresh brain-core-mcp }
Fail-OnError
uv tool update-shell  # puts %USERPROFILE%\.local\bin on the user PATH for new terminals

Step "4/7 Agent $Agent at $Dir"
if (Test-Path (Join-Path $Dir "brain.yaml")) {
  "already initialised, leaving it"
  # an agent made lite stays lite: Hindsight would be 2 GB that its brain.yaml never uses
  if (-not $Lite -and -not (Select-String -Path (Join-Path $Dir "brain.yaml") -Pattern '^  hindsight:' -Quiet)) { $Lite = $true; "this agent was made lite and stays lite" }
} else {
  $initArgs = @("init", $Agent, "--path", $Dir, "--user", $User)
  if ($Lite) { $initArgs += "--lite" }
  if ($ProfileDir) { $initArgs += @("--profile", $ProfileDir) }
  & brain @initArgs
  Fail-OnError
}

$hindsightState = "not installed (lite)"
if (-not $Lite) {
  Step "5/7 Hindsight (vector store, provider $Provider; the first start downloads a database and a model)"
  if ($Provider -eq "claude-code") { "Hindsight reasons through your Claude Code login (personal use only). For an API key instead: set ANTHROPIC_API_KEY, then: brain hindsight install" }
  $hsArgs = @("hindsight", "install", "--provider", $Provider, "--wait", "600")
  if ($ApiKeyEnv) { $hsArgs += @("--api-key-env", $ApiKeyEnv) }
  "installing and starting Hindsight; its first start downloads about 2 GB"
  if (Run-Bounded (Get-Command brain).Source $hsArgs 1500) { $hindsightState = "running (provider $Provider)" } else {
    $hindsightState = "NOT running"
    $problems += "Hindsight did not report healthy. Check: brain hindsight status. The log is in $HOME\.config\hindsight\api.log"
  }
} else {
  Step "5/7 Hindsight skipped (lite: vault + SQLite only). Later: brain hindsight install, then uncomment it in brain.yaml"
}

$desktopOk = $false
if ($Desktop) {
  Step "+ Claude desktop app (-Desktop)"
  brain desktop $Dir
  $desktopOk = $LASTEXITCODE -eq 0
  if (-not $desktopOk) { $problems += "The Claude desktop app was not connected. In the app open Settings > Developer > Edit Config, then run: brain desktop `"$Dir`" --config <that file>" }
}

Step "6/7 Scheduled tasks (brain daily 06:07, brain weekly Sun 07:13), then doctor"
$tasksOk = Run-Bounded (Get-Command brain).Source @("cron", "install", "`"$Dir`"") 180
if (-not $tasksOk) { $problems += "The two scheduled tasks were not created; the lines under 6/7 say why. Again: brain cron install `"$Dir`"" }
"checking the agent"
brain doctor $Dir
if ($LASTEXITCODE) { $problems += "brain doctor reported a problem; its lines are under 6/7" }

Step "7/7 Claude Code"
$claudeOk = Have claude
if ($claudeOk) { "present" } else {
  # Fetched here, not through its own installer: that one downloads 345 MB without a line on the
  # screen and ends with `exit`. Same source, same checksum test, same `install` at the end.
  try {
    $base = "https://downloads.claude.ai/claude-code-releases"
    $plat = if ($cpu -eq "ARM64") { "win32-arm64" } else { "win32-x64" }
    "asking downloads.claude.ai for the current version"
    $ver = "$(Invoke-RestMethod -TimeoutSec 30 "$base/latest")".Trim()
    if ($ver -notmatch '^\d+\.\d+\.\d+') { throw "downloads.claude.ai did not answer with a version number" }
    $want = (Invoke-RestMethod -TimeoutSec 30 "$base/$ver/manifest.json").platforms.$plat.checksum
    if (-not $want) { throw "Claude Code $ver has no build for $plat" }
    $exe = Join-Path $env:TEMP "claude-$ver-$plat.exe"
    "downloading Claude Code $ver (a large file)"
    Get-File "$base/$ver/$plat/claude.exe" $exe "Claude Code"
    "checking the download"
    $stream = [IO.File]::OpenRead($exe)
    try { $got = ([BitConverter]::ToString([Security.Cryptography.SHA256]::Create().ComputeHash($stream)) -replace "-", "").ToLower() } finally { $stream.Close() }
    if ($got -ne $want) { throw "the Claude Code download is damaged (its checksum is wrong); run this line again" }
    "running Claude Code's own setup"
    $claudeOk = Run-Bounded $exe @("install", "latest") 900
    Remove-Item $exe -ErrorAction SilentlyContinue
    if (-not $claudeOk) { throw "Claude Code's own setup did not finish; its lines are above" }
  } catch {
    $problems += "Claude Code was not installed: $($_.Exception.Message). By hand: https://code.claude.com/docs/en/setup"
    Write-Host "  $($_.Exception.Message)" -ForegroundColor Red
  }
}

# The app reads its settings only when it starts, and closing its window does not stop it. So the
# script watches for the restart and reports what the app did, instead of leaving that to trust.
$desktopState = "not asked for (add -Desktop)"
if ($Desktop -and -not $desktopOk) { $desktopState = "NOT connected" }
if ($Desktop -and $desktopOk) {
  Step "+ Claude desktop app: has it loaded brain-core?"
  if (Test-ClaudeLoadedBrain) {
    "yes: the app is running and has started brain-core"
    $desktopState = "connected and loaded"
    if ($brainChanged) {
      Write-Host "It started brain-core before this upgrade, so it is still on $before. Quit Claude from the icon near the clock and open it again to use $after." -ForegroundColor Yellow
      $desktopState = "connected and loaded; restart Claude to use $after"
    }
  } elseif (-not @(Get-ClaudeApp).Count) {
    "the Claude app is not open. brain-core loads the next time you open it"
    $desktopState = "connected; loads when Claude is next opened"
  } else {
    Write-Host "The Claude app is open but started before this install, so it has not read the new setting." -ForegroundColor Yellow
    Write-Host "  1. Right-click the Claude icon near the clock (the ^ arrow shows hidden icons) and choose Quit." -ForegroundColor Yellow
    Write-Host "  2. Open Claude again from the Start menu." -ForegroundColor Yellow
    "watching for that, for at most 5 minutes"
    $waited = 0
    while ($waited -lt 300 -and -not (Test-ClaudeLoadedBrain)) {
      Start-Sleep -Seconds 5
      $waited += 5
      if ($waited % 30 -eq 0) { Write-Host "  still watching ($waited of at most 300 seconds): $(if (@(Get-ClaudeApp).Count) { 'Claude is open, brain-core not loaded yet' } else { 'Claude is closed, open it again' })" }
    }
    if (Test-ClaudeLoadedBrain) {
      "yes: Claude was restarted and has started brain-core"
      $desktopState = "connected and loaded"
    } else {
      $problems += "The Claude app has not loaded brain-core. Quit it from the icon near the clock, open it again, then ask it: use brain_status"
      $desktopState = "connected, but the app has NOT loaded it yet"
    }
  }
}

if ($problems.Count -eq 0) {
  Step "Install complete: every step above finished" "Green"
} else {
  Step "Install NOT complete: $($problems.Count) step(s) did not work" "Red"
  $problems | ForEach-Object { Write-Host "  - $_" -ForegroundColor Red }
}
"  memory folder     $Dir"
"  Hindsight         $hindsightState"
"  desktop app       $desktopState"
"  scheduled tasks   $(if ($tasksOk) { 'created' } else { 'NOT created' })"
"  Claude Code       $(if ($claudeOk) { 'installed' } else { 'NOT installed' })"

@"

Done. Still yours to do, once:
  claude            # sign in to Claude Code$(if (-not $Lite -and $Provider -eq "claude-code") { "; Hindsight reasons through this login" })
  gh auth login     # GitHub, if the agent pushes (winget install GitHub.cli)

Then, in a NEW terminal so PATH is fresh: cd "$Dir"; claude
"@
