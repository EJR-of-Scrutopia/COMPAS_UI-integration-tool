# Bench Studio launcher: find Python, build the venv on first run, start
# the server hidden with its own rotating log file, open the browser, then
# exit. See README.md, "Quick start", and "Logs and stopping".
#
# The server used to run in this window's own console, so closing that
# window was how you stopped Bench Studio. It now starts hidden (see the
# Start-Process call near the bottom) and outlives this script; use "Stop
# Bench Studio.cmd" (launcher/stop.ps1) to stop it, or Task Manager if
# that ever fails to find it.
#
# Hiding mechanism, confirmed empirically on this machine (Windows 11,
# Windows Terminal as the default terminal app): plain
# `Start-Process -WindowStyle Hidden` was tested first because of a
# previously confirmed gotcha where Windows 11 with Windows Terminal
# default ignores -WindowStyle Hidden for processes started by Task
# Scheduler (the terminal claims the console instead of leaving it
# hidden). That gotcha is specific to the Task Scheduler launch path.
# Started directly from a script the way this launcher does it,
# -WindowStyle Hidden was verified (EnumWindows over every visible
# top-level window on the desktop, filtered to the spawned PIDs, found
# none) to genuinely produce no window, and -RedirectStandardOutput/
# -RedirectStandardError still captured the child's output correctly, so
# there is no need for the conhost.exe --headless fallback the plan
# flagged as a possible second step.

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot

function Find-Python {
    foreach ($spec in @("-3.12", "-3")) {
        try {
            & py $spec -c "exit(0)" 2>$null
            if ($LASTEXITCODE -eq 0) { return $spec }
        } catch {
            # 'py' launcher itself is missing; nothing to try further.
            return $null
        }
    }
    return $null
}

function Test-PortFree([int]$port) {
    try {
        $listener = New-Object System.Net.Sockets.TcpListener([Net.IPAddress]::Loopback, $port)
        $listener.Start()
        $listener.Stop()
        return $true
    } catch {
        return $false
    }
}

function Test-PortAnswering([int]$port) {
    try {
        $client = New-Object System.Net.Sockets.TcpClient
        $client.Connect("127.0.0.1", $port)
        $client.Close()
        return $true
    } catch {
        return $false
    }
}

# If Bench Studio is already up on its default port, there is nothing to
# launch: just bring the browser to it. This has to run before any of the
# venv/pip work below, or a second launch while the first is still running
# would pay that cost for nothing (and, if a free port were picked instead
# of reusing this check, would start a second server instance).
$defaultPort = 8600
if (Test-PortAnswering $defaultPort) {
    Write-Host "Bench Studio is already running on port $defaultPort. Opening the browser."
    Start-Process "http://127.0.0.1:$defaultPort"
    exit 0
}

$pySpec = Find-Python
if (-not $pySpec) {
    Write-Host "`nBench Studio needs Python 3.12+ on PATH, found via the 'py' launcher."
    Write-Host "See README.md, Prerequisite.`n"
    Read-Host "Press Enter to close"
    exit 1
}

$venvDir = Join-Path $env:LOCALAPPDATA "BenchStudio\venv"

# Microsoft Store Python virtualises writes under AppData\Local into its
# package's LocalCache, so the venv can land somewhere other than the
# requested path. Same probe setup-fea.ps1 uses: prefer the requested
# location, fall back to any Store package redirect that actually exists.
function Resolve-VenvPython([string]$requested) {
    $direct = Join-Path $requested "Scripts\python.exe"
    if (Test-Path $direct) { return $direct }
    $relative = $requested.Substring(($env:LOCALAPPDATA).Length + 1)
    $packages = Join-Path $env:LOCALAPPDATA "Packages"
    if (Test-Path $packages) {
        foreach ($pkg in Get-ChildItem $packages -Filter "PythonSoftwareFoundation.Python.*" -Directory -ErrorAction SilentlyContinue) {
            $redirected = Join-Path $pkg.FullName "LocalCache\Local\$relative\Scripts\python.exe"
            if (Test-Path $redirected) { return $redirected }
        }
    }
    return $null
}

$venvPython = Resolve-VenvPython $venvDir
if (-not $venvPython) {
    Write-Host "First run: creating a Python environment at $venvDir"
    & py $pySpec -m venv $venvDir
    if ($LASTEXITCODE -ne 0) {
        Write-Host "Could not create the virtual environment. See README.md, Prerequisite."
        Read-Host "Press Enter to close"
        exit 1
    }
    $venvPython = Resolve-VenvPython $venvDir
    if (-not $venvPython) {
        Write-Host "The environment was created but its python.exe could not be located."
        Write-Host "This can happen with Microsoft Store Python; see README.md, Prerequisite."
        Read-Host "Press Enter to close"
        exit 1
    }
}

Write-Host "Installing dependencies (visible below; quick once the venv is warm)..."
& $venvPython -m pip install --disable-pip-version-check -r (Join-Path $repoRoot "requirements.txt")
if ($LASTEXITCODE -ne 0) {
    Write-Host "pip install failed; see the output above."
    Read-Host "Press Enter to close"
    exit 1
}

$port = $defaultPort
while (-not (Test-PortFree $port)) { $port++ }

# Logs: one file per run, newest 10 kept. Both live at
# %LOCALAPPDATA%\BenchStudio\logs; server.pid there too, read by stop.ps1.
$stateDir = Join-Path $env:LOCALAPPDATA "BenchStudio"
$logDir = Join-Path $stateDir "logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$logFile = Join-Path $logDir "server-$stamp.log"
$errFile = Join-Path $logDir "server-$stamp.err.log"
$pidFile = Join-Path $stateDir "server.pid"

# "server-*.log" also matches the "*.err.log" companions (they end in
# ".log" too), so filter those back out here or counting would silently
# keep half as many runs as intended; each stale primary log's own
# .err.log is removed alongside it below. Skip 9, not 10: this trim runs
# before today's new log is written, so keeping 9 of the old ones plus
# the one this run is about to create lands on 10 total, not 11.
$existingLogs = Get-ChildItem -LiteralPath $logDir -Filter "server-*.log" -File -ErrorAction SilentlyContinue |
    Where-Object { $_.Name -notlike "*.err.log" } |
    Sort-Object LastWriteTime -Descending
if ($existingLogs.Count -ge 10) {
    foreach ($stale in $existingLogs | Select-Object -Skip 9) {
        Remove-Item -LiteralPath $stale.FullName -Force -ErrorAction SilentlyContinue
        $staleErr = $stale.FullName -replace '\.log$', '.err.log'
        Remove-Item -LiteralPath $staleErr -Force -ErrorAction SilentlyContinue
    }
}

# Both env vars are read by bench/studio/serve.py: the guard skips its own
# ensure_venv() interpreter search (which looks for a ".venv" beside the
# file, not this venv under %LOCALAPPDATA%), and the port lets us hand
# over whichever free one we just picked. Set before Start-Process so the
# child inherits them.
$env:ANANKE_DEMO_BOOTSTRAPPED = "1"
$env:BENCH_STUDIO_PORT = "$port"
$servePy = Join-Path $repoRoot "bench\studio\serve.py"

Write-Host "Starting Bench Studio on port $port (hidden; logging to $logFile)..."
$serverProcess = Start-Process -FilePath $venvPython -ArgumentList "`"$servePy`"" `
    -WorkingDirectory $repoRoot -WindowStyle Hidden `
    -RedirectStandardOutput $logFile -RedirectStandardError $errFile -PassThru
Set-Content -LiteralPath $pidFile -Value $serverProcess.Id

$deadline = (Get-Date).AddSeconds(30)
$up = $false
while ((Get-Date) -lt $deadline) {
    if (Test-PortAnswering $port) { $up = $true; break }
    Start-Sleep -Milliseconds 400
}

if (-not $up) {
    Write-Host "Bench Studio did not answer on port $port within 30 seconds."
    Write-Host "Check the log for what happened: $logFile"
    Read-Host "Press Enter to close"
    exit 1
}

Start-Process "http://127.0.0.1:$port"
Write-Host "Bench Studio is up. Log: $logFile"
