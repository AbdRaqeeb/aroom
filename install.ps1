# Install Agent Room (`aroom`) on Windows.
#
# From anywhere (PowerShell):
#   irm https://raw.githubusercontent.com/AbdRaqeeb/aroom/main/install.ps1 | iex
# With options:
#   & ([scriptblock]::Create((irm https://raw.githubusercontent.com/AbdRaqeeb/aroom/main/install.ps1))) -Service
# From a checkout:
#   .\install.ps1 [-Service] [-Listen ADDR] [-Ref REF]
#
# Options:
#   -Service       Run the dashboard and the supervisor in the background with
#                  Task Scheduler: they start when you log in, restart if they
#                  crash, and open no console windows.
#   -Listen ADDR   Address the dashboard binds (default 127.0.0.1). Any other
#                  address creates the access token.
#   -Ref REF       Branch or tag to install (default: main).
#
# Environment:
#   AROOM_HOME     where the checkout lives (default %LOCALAPPDATA%\aroom)
#   AROOM_REPO     GitHub owner/name (default AbdRaqeeb/aroom)
#   AROOM_GIT_URL  clone from this URL instead (fork, mirror, local path)
#
# Needs: Git for Windows (git + Git Bash) and Python 3.10+.
# Safe to re-run: it updates the checkout, rewrites the launcher and tasks.

param(
    [switch]$Service,
    [string]$Listen = "127.0.0.1",
    [string]$Ref = $(if ($env:AROOM_REF) { $env:AROOM_REF } else { "main" })
)

# Native commands (git, python, py) report through exit codes, which are
# checked below; "Stop" would turn their stderr output into fatal errors on
# Windows PowerShell 5.1.
$ErrorActionPreference = "Continue"

function Say($label, $text) { Write-Host ("{0,-10} {1}" -f $label, $text) }
# throw, not exit: under `irm | iex` exit would close the user's PowerShell window.
function Fail($text) { throw "aroom install: $text" }

# --- prerequisites -----------------------------------------------------------

if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    Fail "git is required. Install Git for Windows (it includes Git Bash): https://git-scm.com/download/win  (or: winget install Git.Git)"
}

function Find-Python {
    $candidates = @()
    if (Get-Command py -ErrorAction SilentlyContinue) {
        foreach ($v in @("-3.13", "-3.12", "-3.11", "-3.10", "-3")) { $candidates += , @("py", $v) }
    }
    foreach ($name in @("python3", "python")) {
        $cmd = Get-Command $name -ErrorAction SilentlyContinue
        # Skip the Microsoft Store stub that only opens the Store.
        if ($cmd -and $cmd.Source -notmatch "WindowsApps") { $candidates += , @($cmd.Source) }
    }
    foreach ($c in $candidates) {
        $exe = $c[0]; $rest = @($c | Select-Object -Skip 1)
        try {
            $out = & $exe @rest -c "import sys; print(sys.executable if sys.version_info >= (3, 10) else '')" 2>$null
            if ($LASTEXITCODE -eq 0 -and $out) { return ($out | Select-Object -Last 1).Trim() }
        } catch { }
    }
    return $null
}

$Python = Find-Python
if (-not $Python) {
    Fail "Agent Room needs Python 3.10 or newer. Install it from https://www.python.org/downloads/ (or: winget install Python.Python.3.12), then re-run."
}

# --- checkout: clone or update unless running from one ----------------------

$Here = $null
if ($PSScriptRoot -and (Test-Path (Join-Path $PSScriptRoot "ar")) -and (Test-Path (Join-Path $PSScriptRoot "agentroom"))) {
    $Here = $PSScriptRoot
} else {
    $repo = if ($env:AROOM_REPO) { $env:AROOM_REPO } else { "AbdRaqeeb/aroom" }
    $url = if ($env:AROOM_GIT_URL) { $env:AROOM_GIT_URL } else { "https://github.com/$repo.git" }
    $Here = if ($env:AROOM_HOME) { $env:AROOM_HOME } else { Join-Path $env:LOCALAPPDATA "aroom" }
    $env:GIT_TERMINAL_PROMPT = "0"
    if (Test-Path (Join-Path $Here ".git")) {
        Say "updating:" "$Here ($Ref)"
        git -C $Here fetch --quiet --tags $url "+refs/heads/*:refs/remotes/origin/*"
        if ($LASTEXITCODE -ne 0) { Fail "git fetch failed" }
        git -C $Here rev-parse --verify --quiet "refs/remotes/origin/$Ref" *> $null
        if ($LASTEXITCODE -eq 0) { git -C $Here checkout --quiet -B $Ref "origin/$Ref" } else { git -C $Here checkout --quiet $Ref }
        if ($LASTEXITCODE -ne 0) { Fail "could not check out $Ref" }
    } else {
        if ((Test-Path $Here) -and (Get-ChildItem $Here -Force | Select-Object -First 1)) {
            Fail "$Here exists and is not a git checkout; move it or set AROOM_HOME"
        }
        Say "cloning:" "$repo ($Ref) -> $Here"
        git clone --quiet --branch $Ref $url $Here
        if ($LASTEXITCODE -ne 0) { Fail "git clone failed" }
    }
}

# --- Git Bash check (project commands and agents run through it) ------------

$env:PYTHONUTF8 = "1"
$bashCheck = & $Python -c "import sys; sys.path.insert(0, r'$Here'); from agentroom import osutil; print(osutil.bash())" 2>&1
if ($LASTEXITCODE -ne 0) { Fail ($bashCheck | Out-String).Trim() }

# --- launcher ----------------------------------------------------------------

$BinDir = Join-Path $env:LOCALAPPDATA "Programs\aroom"
New-Item -ItemType Directory -Force -Path $BinDir -ErrorAction Stop | Out-Null
$Ar = Join-Path $Here "ar"
$shim = "@echo off`r`nset PYTHONUTF8=1`r`n`"$Python`" `"$Ar`" %*`r`n"
foreach ($name in @("aroom.cmd", "ar.cmd")) {
    [System.IO.File]::WriteAllText((Join-Path $BinDir $name), $shim, [System.Text.Encoding]::ASCII)
}

$userPath = [Environment]::GetEnvironmentVariable("Path", "User")
if (-not $userPath) { $userPath = "" }
if (($userPath -split ";") -notcontains $BinDir) {
    [Environment]::SetEnvironmentVariable("Path", ($userPath.TrimEnd(";") + ";" + $BinDir).TrimStart(";"), "User")
    Say "updated:" "user PATH (+ $BinDir)"
}
if (($env:Path -split ";") -notcontains $BinDir) { $env:Path = "$env:Path;$BinDir" }

$Launcher = Join-Path $BinDir "aroom.cmd"
& $Launcher --version *> $null
if ($LASTEXITCODE -ne 0) { Fail "the launcher failed to start; run: $Launcher --version" }

Say "installed:" "$Launcher -> $Ar"
Say "python:" $Python
Say "bash:" ($bashCheck | Select-Object -Last 1)

# --- optional: background tasks ----------------------------------------------

if ($Service) {
    $Pythonw = Join-Path (Split-Path $Python) "pythonw.exe"
    if (-not (Test-Path $Pythonw)) { $Pythonw = $Python }
    $StateDir = Join-Path $env:USERPROFILE ".local\state\agent-room"
    New-Item -ItemType Directory -Force -Path $StateDir -ErrorAction Stop | Out-Null

    if ($Listen -notin @("127.0.0.1", "localhost", "::1")) {
        & $Launcher token --create *> $null
    }

    $tasks = @(
        @{ Name = "Agent Room dashboard";  Args = "-X utf8 `"$Ar`" --log=`"$StateDir\ui.log`" ui --no-open --host $Listen" },
        @{ Name = "Agent Room supervisor"; Args = "-X utf8 `"$Ar`" --log=`"$StateDir\supervisor.log`" supervise --interval 60" }
    )
    $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
        -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit ([TimeSpan]::Zero) `
        -MultipleInstances IgnoreNew -StartWhenAvailable
    # Logon starts it; the every-minute trigger brings it back if the process
    # dies (Task Scheduler's restart-on-failure only covers failed launches).
    # MultipleInstances IgnoreNew keeps a running copy from being doubled.
    $atLogon = New-ScheduledTaskTrigger -AtLogOn -User "$env:USERDOMAIN\$env:USERNAME"
    $everyMinute = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -Minutes 1)
    $trigger = @($atLogon, $everyMinute)
    $principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel Limited
    foreach ($t in $tasks) {
        $existing = Get-ScheduledTask -TaskName $t.Name -ErrorAction SilentlyContinue
        if ($existing) {
            Stop-ScheduledTask -TaskName $t.Name -ErrorAction SilentlyContinue
            Unregister-ScheduledTask -TaskName $t.Name -Confirm:$false
        }
        $action = New-ScheduledTaskAction -Execute $Pythonw -Argument $t.Args -WorkingDirectory $env:USERPROFILE
        Register-ScheduledTask -TaskName $t.Name -Action $action -Trigger $trigger -Settings $settings -Principal $principal `
            -Description "Agent Room (aroom). Re-run install.ps1 -Service to update." -ErrorAction Stop | Out-Null
        Start-ScheduledTask -TaskName $t.Name
    }
    $port = & $Python -c "import sys; sys.path.insert(0, r'$Here'); from agentroom import config; print(config.load_registry()['ui'].get('port', 4400))" 2>$null
    if (-not $port) { $port = 4400 }
    Say "service:" "'Agent Room dashboard' + 'Agent Room supervisor' in Task Scheduler (dashboard on http://${Listen}:$port)"
    Say "" "start at logon, come back within a minute if they stop; logs in $StateDir"
    Say "" "pause:   Disable-ScheduledTask 'Agent Room dashboard'; Stop-ScheduledTask 'Agent Room dashboard'"
    Say "" "resume:  Enable-ScheduledTask 'Agent Room dashboard'"
    Say "" "remove:  Unregister-ScheduledTask 'Agent Room*' -Confirm:`$false"
    $token = & $Launcher token 2>$null
    if ($LASTEXITCODE -eq 0 -and $token) { Say "token:" $token }
}

Write-Host ""
Write-Host "next (open a new terminal so PATH is updated):"
Write-Host "  aroom doctor"
Write-Host "  aroom init C:\path\to\repo"
if (-not $Service) { Write-Host "  aroom ui" }
