# Bench Studio FEA environment setup, run once by hand (not part of
# Launch Bench Studio.cmd; FEA is an optional, advanced, opt-in check, see
# README.md and docs/BENCH.md, "The three environments").
#
# bench/studio/staging.py shells per-stage structural solves out to a
# second interpreter and hardcodes exactly where to find it:
#
#     FEA_PYTHON = REPO / ".venv-fea" / "Scripts" / "python.exe"
#
# with no environment-variable override (unlike the main launcher's
# ANANKE_DEMO_BOOTSTRAPPED bypass for bench/demo/_bootstrap.py's own venv
# search). That path is fixed, so this script has to make it resolve to a
# real interpreter one way or another. Rather than build a multi-gigabyte
# environment (numpy, scipy, compas, compas_fea2, openseespy) inside the
# OneDrive-synced repo itself, which is exactly the failure
# bench/scripts/setup_fea_env.sh works around with `--link-mode=copy`
# (OneDrive's cloud-file hardlinking fails outright, os error 396) and
# which the main launcher already avoids for the same reason, the real
# environment is built at %LOCALAPPDATA%\BenchStudio\venv-fea, matching
# launch.ps1's own convention, and a directory junction at
# <repo>\.venv-fea points staging.py's hardcoded path at it. Junctions
# need no elevation on Windows, unlike symlinks.
#
# This uses plain `py`/`pip`, not `uv`: the OneDrive hardlink failure
# setup_fea_env.sh works around is a uv-specific behaviour (its default
# link mode), and pip copies files, so building outside the repo tree
# here sidesteps the whole problem without needing uv installed at all.
#
# ananke_fea (src/ananke_fea/) is made importable with a .pth file
# pointing at src/, not `pip install --no-deps -e .`: that needs a
# pyproject.toml, which this standalone repo does not carry (the source
# repo's setup_fea_env.sh runs it against a pyproject.toml this repo does
# not have; see requirements-fea.txt).
#
# One more redirect to work around, confirmed by actually running this
# script: Microsoft Store Python virtualises %LOCALAPPDATA% writes made by
# its own process to a per-package LocalCache folder, so venv creation
# reports success at the requested path while the real files land
# elsewhere; other processes (this script's own later pip install, the
# studio) see nothing at the requested path. `python -m venv` itself
# warns about this ("Actual environment location may have moved due to
# redirects, links or junctions") when it happens. This is the same quirk
# bench/demo/_bootstrap.py already documents and works around for IPOPT
# under .venv-cra (IPOPT_CANDIDATES); Resolve-VenvHome below does the same
# thing for this venv: try the requested path, then the Store redirect.

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$venvDir = Join-Path $env:LOCALAPPDATA "BenchStudio\venv-fea"
$junctionPath = Join-Path $repoRoot ".venv-fea"

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

function Resolve-VenvHome([string]$Requested) {
    if (Test-Path (Join-Path $Requested "Scripts\python.exe")) { return $Requested }

    # BenchStudio\venv-fea, relative to %LOCALAPPDATA%, re-rooted under the
    # Store Python package's own LocalCache.
    $relative = $Requested.Substring($env:LOCALAPPDATA.Length).TrimStart("\")
    $redirected = Join-Path $env:LOCALAPPDATA `
        "Packages\PythonSoftwareFoundation.Python.3.12_qbz5n2kfra8p0\LocalCache\Local\$relative"
    if (Test-Path (Join-Path $redirected "Scripts\python.exe")) { return $redirected }

    return $null
}

$pySpec = Find-Python
if (-not $pySpec) {
    Write-Host "`nBench Studio needs Python 3.12+ on PATH, found via the 'py' launcher."
    Write-Host "See README.md, Prerequisite.`n"
    Read-Host "Press Enter to close"
    exit 1
}

$resolved = Resolve-VenvHome $venvDir
if (-not $resolved) {
    Write-Host "Creating the FEA environment at $venvDir"
    & py $pySpec -m venv $venvDir
    if ($LASTEXITCODE -ne 0) {
        Write-Host "Could not create the virtual environment."
        Read-Host "Press Enter to close"
        exit 1
    }
    $resolved = Resolve-VenvHome $venvDir
    if (-not $resolved) {
        Write-Host "venv creation reported success, but no python.exe was found at"
        Write-Host "$venvDir or its Microsoft Store redirect."
        Read-Host "Press Enter to close"
        exit 1
    }
    if ($resolved -ne $venvDir) {
        Write-Host ""
        Write-Host "Microsoft Store Python redirected this venv (see this script's own"
        Write-Host "comments); using the real location for everything below:"
        Write-Host "  requested : $venvDir"
        Write-Host "  actual    : $resolved"
    }
} else {
    Write-Host "FEA environment already exists at $resolved"
}
$venvDir = $resolved
$venvPython = Join-Path $venvDir "Scripts\python.exe"

Write-Host ""
Write-Host "Installing requirements-fea.txt (compas_fea2 is pinned to a git commit"
Write-Host "and takes a moment to build; output is visible below)..."
& $venvPython -m pip install --disable-pip-version-check -r (Join-Path $repoRoot "requirements-fea.txt")
if ($LASTEXITCODE -ne 0) {
    Write-Host "pip install failed; see the output above."
    Read-Host "Press Enter to close"
    exit 1
}

Write-Host ""
Write-Host "Making src/ananke_fea importable in this environment..."
$srcDir = Join-Path $repoRoot "src"
$sitePackages = (& $venvPython -c "import sysconfig; print(sysconfig.get_path('purelib'))").Trim()
$pthFile = Join-Path $sitePackages "ananke_fea_src.pth"
Set-Content -Path $pthFile -Value $srcDir -Encoding ascii
Write-Host "  wrote $pthFile"
Write-Host "  ->    $srcDir"

Write-Host ""
if (Test-Path $junctionPath) {
    $existing = Get-Item $junctionPath -Force
    if ($existing.LinkType -eq "Junction") {
        Write-Host "Junction already in place: $junctionPath"
        Write-Host "  ->  $($existing.Target)"
    } else {
        Write-Host "$junctionPath already exists and is not a junction; leaving it alone."
        Write-Host "Remove or rename it, then re-run this script, if it should point at $venvDir."
    }
} else {
    New-Item -ItemType Junction -Path $junctionPath -Target $venvDir | Out-Null
    Write-Host "Created junction: $junctionPath"
    Write-Host "  ->  $venvDir"
}

Write-Host ""
Write-Host "=== FEA environment ready ==="
Write-Host "Real files at    : $venvDir"
Write-Host "The studio finds it at : $junctionPath"
Write-Host "(bench/studio/staging.py hardcodes that exact repo-relative path;"
Write-Host " the junction is what makes it resolve outside the repo tree.)"
Write-Host ""
Write-Host "Verify the packages installed (confirmed by actually running this: any"
Write-Host "tests\fea\*.py check, including test_cantilever.py, fails at collection"
Write-Host "with NotImplementedError until the OpenSees step below is done, because"
Write-Host "tests\fea\conftest.py's own guard only catches ImportError, not the"
Write-Host "NotImplementedError compas_fea2_opensees raises with no executable"
Write-Host "configured yet):"
Write-Host "    `"$venvPython`" -c `"import ananke_fea, compas_fea2; print('ok')`""
Write-Host ""
Write-Host "One manual step remains: OpenSees itself. compas_fea2_opensees shells"
Write-Host "out to a standalone executable that openseespy does not provide."
Write-Host "Download it from https://opensees.berkeley.edu/ (the page is"
Write-Host "JavaScript-driven, so this step cannot be scripted), then run:"
Write-Host "    `"$venvPython`" bench\scripts\install_opensees.py <extracted folder>"
Write-Host ""
Write-Host "Only after that does the full test suite collect; then verify with:"
Write-Host "    `"$venvPython`" -m pytest tests\fea\test_cantilever.py -q"
Write-Host ""

Read-Host "Press Enter to close"
