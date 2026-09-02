# install.ps1 - lets Chrome talk to the downloader.
#
# Run this once, after loading the extension in chrome://extensions:
#
#     powershell -ExecutionPolicy Bypass -File install.ps1
#
# It writes one JSON file next to this script and one registry value under
# HKEY_CURRENT_USER. No admin rights, nothing machine-wide, nothing installed.
# Run uninstall.ps1 to undo both.
#
#   -ExtensionId <id>   override the ID (only needed if manifest.json's "key"
#                       has been removed, which makes the ID folder-dependent)
#   -InstallFfmpeg      also install ffmpeg via winget if it is missing
#   -Source             run host.py from this folder instead of the frozen
#                       host.exe, so edits to the Python take effect on reload

param(
    [string]$ExtensionId = "",
    [switch]$InstallFfmpeg,
    [switch]$Source
)

$ErrorActionPreference = "Stop"

$HostName = "com.mediadownload.host"

# Fixed by the "key" field in the extension's manifest.json, so it is the same
# on every machine. See native-host/make-key.py.
$DefaultExtensionId = "kkfepfljdgflemilngnbpkdadanpaleb"

$here = Split-Path -Parent $MyInvocation.MyCommand.Path

# --- work out which id to authorise ------------------------------------------
if ([string]::IsNullOrWhiteSpace($ExtensionId)) {
    $id = $DefaultExtensionId
} else {
    $id = $ExtensionId.Trim().Trim('"').Trim("'").ToLower()
}

if ($id -notmatch '^[a-p]{32}$') {
    Write-Host "That doesn't look like a Chrome extension ID." -ForegroundColor Red
    Write-Host "  Expected: 32 letters, a through p."
    Write-Host "  Got:      '$id'"
    exit 1
}

# --- find the program Chrome should run --------------------------------------
# Shared build first, then a freshly built one, then the source checkout.
# -Source points Chrome at host.bat, which runs host.py straight from this
# folder. Use it while developing: without it Chrome runs the frozen host.exe,
# and every edit to the Python is invisible until it is rebuilt.
if ($Source) {
    $candidates = @( (Join-Path $here "host.bat") )
} else {
    $candidates = @(
        (Join-Path $here "host\host.exe"),
        (Join-Path $here "dist\host\host.exe"),
        (Join-Path $here "host.bat")
    )
}

$target = $null
foreach ($candidate in $candidates) {
    if (Test-Path $candidate) { $target = $candidate; break }
}

if (-not $target) {
    Write-Host "Couldn't find host.exe or host.bat next to this script." -ForegroundColor Red
    Write-Host "Looked in:"
    $candidates | ForEach-Object { Write-Host "  $_" }
    exit 1
}

# host.bat needs the project's Python; host.exe carries its own.
if ($target.EndsWith(".bat")) {
    $python = Join-Path (Split-Path -Parent $here) ".venv\Scripts\python.exe"
    if (-not (Test-Path $python)) {
        Write-Host "host.bat needs .venv\Scripts\python.exe, which isn't there." -ForegroundColor Red
        exit 1
    }
}

# --- ffmpeg: needed to join video and audio into one mp4 ---------------------
$ffmpeg = Get-Command ffmpeg -ErrorAction SilentlyContinue
if (-not $ffmpeg) {
    $winget = Join-Path $env:LOCALAPPDATA "Microsoft\WinGet\Packages"
    if (Test-Path $winget) {
        $ffmpeg = Get-ChildItem -Path $winget -Filter ffmpeg.exe -Recurse -ErrorAction SilentlyContinue | Select-Object -First 1
    }
}

if (-not $ffmpeg) {
    if ($InstallFfmpeg) {
        Write-Host "Installing ffmpeg via winget..." -ForegroundColor Cyan
        winget install --id Gyan.FFmpeg -e --accept-source-agreements --accept-package-agreements
    } else {
        Write-Host ""
        Write-Host "NOTE: ffmpeg isn't installed." -ForegroundColor Yellow
        Write-Host "Most videos arrive as separate video and audio streams, and ffmpeg is"
        Write-Host "what joins them into one .mp4. Without it many downloads will fail."
        Write-Host ""
        Write-Host "  winget install --id Gyan.FFmpeg -e"
        Write-Host ""
        Write-Host "Then open a NEW terminal. Or re-run this script with -InstallFfmpeg."
        Write-Host ""
    }
}

# --- write the host manifest -------------------------------------------------
$jsonPath = Join-Path $here "$HostName.json"

$manifest = [ordered]@{
    name            = $HostName
    description     = "Sends video links from Chrome to the downloader"
    path            = $target
    type            = "stdio"
    allowed_origins = @("chrome-extension://$id/")
}

$json = $manifest | ConvertTo-Json -Depth 3

# WriteAllText with UTF8Encoding($false), not Out-File: PowerShell 5.1 writes a
# byte-order mark by default and Chrome's JSON parser rejects the file outright.
[System.IO.File]::WriteAllText($jsonPath, $json, (New-Object System.Text.UTF8Encoding($false)))

# --- point Chrome at it ------------------------------------------------------
$key = "HKCU:\Software\Google\Chrome\NativeMessagingHosts\$HostName"
if (-not (Test-Path $key)) {
    New-Item -Path $key -Force | Out-Null
}
Set-ItemProperty -Path $key -Name "(default)" -Value $jsonPath

# --- read it back, don't assume ----------------------------------------------
$written = (Get-ItemProperty -Path $key)."(default)"
if ($written -ne $jsonPath) {
    Write-Host "The registry value didn't stick. Expected '$jsonPath', found '$written'." -ForegroundColor Red
    exit 1
}

Write-Host ""
Write-Host "Installed." -ForegroundColor Green
Write-Host "  extension : $id"
Write-Host "  manifest  : $jsonPath"
Write-Host "  runs      : $target"
if ($ffmpeg) { Write-Host "  ffmpeg    : found" }
Write-Host ""
Write-Host "Now go to chrome://extensions and click Reload on the extension."
