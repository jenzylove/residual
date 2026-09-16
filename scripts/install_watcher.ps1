# Registers the RESIDUAL live watcher as a Windows Scheduled Task, running every 10 minutes.
# It runs pythonw.exe (no console window), so nothing pops up while it works.
# Install:  powershell -ExecutionPolicy Bypass -File scripts\install_watcher.ps1
# Remove:   schtasks /Delete /TN ResidualWatcher /F
$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
# The Windows Store alias under WindowsApps exits silently when run from a task, so skip it.
$py = (Get-Command python).Source
$pyw = Join-Path (Split-Path -Parent $py) "pythonw.exe"
if ($pyw -like "*WindowsApps*" -or -not (Test-Path $pyw)) {
    $found = Get-ChildItem "$env:LOCALAPPDATA\Python" -Recurse -Filter pythonw.exe -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($found) { $pyw = $found.FullName } else { throw "pythonw.exe not found; install Python or edit this script" }
}
$script = Join-Path $repo "scripts\watch_once.py"
schtasks /Create /F /SC MINUTE /MO 10 /TN "ResidualWatcher" /TR "`"$pyw`" `"$script`"" | Out-Null
schtasks /Run /TN "ResidualWatcher" | Out-Null
Write-Host "ResidualWatcher installed (every 10 min, windowless)."
Write-Host "  python : $pyw"
Write-Host "  script : $script"
Write-Host "  log    : $repo\data\watcher.log  ·  site status: $repo\web\live.json"
