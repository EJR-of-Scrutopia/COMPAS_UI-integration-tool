# Bench Studio launcher: find Python, build the venv on first run, start
# the server, open the browser. See README.md, "Quick start".

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

$port = 8600
while (-not (Test-PortFree $port)) { $port++ }

# Both env vars are read by bench/studio/serve.py: the guard skips its own
# ensure_venv() interpreter search (which looks for a ".venv" beside the
# file, not this venv under %LOCALAPPDATA%), and the port lets us hand
# over whichever free one we just picked.
$env:ANANKE_DEMO_BOOTSTRAPPED = "1"
$env:BENCH_STUDIO_PORT = "$port"
$servePy = Join-Path $repoRoot "bench\studio\serve.py"

Write-Host "Starting Bench Studio on port $port..."
Start-Process -FilePath $venvPython -ArgumentList "`"$servePy`"" -WorkingDirectory $repoRoot

$deadline = (Get-Date).AddSeconds(20)
while ((Get-Date) -lt $deadline) {
    try {
        $client = New-Object System.Net.Sockets.TcpClient
        $client.Connect("127.0.0.1", $port)
        $client.Close()
        break
    } catch {
        Start-Sleep -Milliseconds 400
    }
}

Start-Process "http://127.0.0.1:$port"
