# uninstall.ps1 - undoes install.ps1. Removes the registry value and the JSON
# file, nothing else. The extension itself is removed from chrome://extensions.
#
#     powershell -ExecutionPolicy Bypass -File uninstall.ps1

$ErrorActionPreference = "Stop"

$HostName = "com.mediadownload.host"
$here     = Split-Path -Parent $MyInvocation.MyCommand.Path
$jsonPath = Join-Path $here "$HostName.json"
$key      = "HKCU:\Software\Google\Chrome\NativeMessagingHosts\$HostName"

if (Test-Path $key) {
    Remove-Item -Path $key -Recurse -Force
    Write-Host "Removed registry key."
} else {
    Write-Host "Registry key was not there."
}

if (Test-Path $jsonPath) {
    Remove-Item -Path $jsonPath -Force
    Write-Host "Removed $jsonPath"
} else {
    Write-Host "Host manifest was not there."
}

Write-Host "Done. Remove the extension itself at chrome://extensions."
