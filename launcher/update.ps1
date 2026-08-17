# Bench Studio updater: downloads the latest main branch as a zip and
# replaces the app files. This is a plain file-replace, not a merge: it is
# honest about that, and it never touches the data directories, whichever
# way this runs.
#
# Data dirs, always skipped: bench/studio/hdri (rendered HDRIs),
# bench/demo/upload from grasshopper (your exports), bench/studies (studies
# and their results). App code, always replaced: bench/ minus those three,
# src/, launcher/ (this script updates itself; if that fails mid-run because
# Windows has the file open, re-run Update.cmd once more), requirements*.txt,
# README.md.

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$zipUrl = "https://github.com/EJR-of-Scrutopia/COMPAS_UI-integration-tool/archive/refs/heads/main.zip"

$work = Join-Path $env:TEMP ("BenchStudioUpdate-" + [guid]::NewGuid())
New-Item -ItemType Directory -Path $work | Out-Null
$zipPath = Join-Path $work "main.zip"

try {
    Write-Host "Downloading the latest main..."
    Invoke-WebRequest -Uri $zipUrl -OutFile $zipPath

    Write-Host "Extracting..."
    Expand-Archive -Path $zipPath -DestinationPath $work

    $extracted = Get-ChildItem $work -Directory |
        Where-Object { $_.Name -like "COMPAS_UI-integration-tool-*" } |
        Select-Object -First 1
    if (-not $extracted) {
        throw "The downloaded archive did not contain the expected folder."
    }

    Write-Host ""
    Write-Host "Replacing app files (data directories are left alone)..."
    robocopy (Join-Path $extracted.FullName "bench") (Join-Path $repoRoot "bench") `
        /E /XD hdri "upload from grasshopper" studies /R:2 /W:2 | Out-Host
    robocopy (Join-Path $extracted.FullName "src") (Join-Path $repoRoot "src") `
        /E /R:2 /W:2 | Out-Host
    robocopy (Join-Path $extracted.FullName "launcher") (Join-Path $repoRoot "launcher") `
        /E /R:2 /W:2 | Out-Host

    foreach ($file in @("requirements.txt", "requirements-fea.txt", "README.md")) {
        $from = Join-Path $extracted.FullName $file
        if (Test-Path $from) {
            Copy-Item $from (Join-Path $repoRoot $file) -Force
            Write-Host "Updated $file"
        }
    }

    Write-Host ""
    Write-Host "Update complete. Dependencies refresh next time you run"
    Write-Host "'Launch Bench Studio.cmd', since that always runs pip install."
} finally {
    Remove-Item -Recurse -Force $work -ErrorAction SilentlyContinue
}

Read-Host "Press Enter to close"
