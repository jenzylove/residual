# Registers a Windows Scheduled Task that runs the RESIDUAL live watcher every 10 minutes.
# Run once from the repo root:   powershell -ExecutionPolicy Bypass -File scripts\install_watcher.ps1
# Remove it later with:          schtasks /Delete /TN ResidualWatcher /F
$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
$py = (Get-Command python).Source
if ($py -like "*WindowsApps*") {
    $real = Get-ChildItem "$env:LOCALAPPDATA\Python" -Recurse -Filter python.exe -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($real) { $py = $real.FullName }
}
$cmd = "cmd /c cd /d `"$repo`" && `"$py`" -m residual live >> data\watcher.log 2>&1"
schtasks /Create /F /SC MINUTE /MO 10 /TN "ResidualWatcher" /TR $cmd | Out-Null
schtasks /Run /TN "ResidualWatcher" | Out-Null
Write-Host "ResidualWatcher installed: every 10 minutes, log at $repo\data\watcher.log"
Write-Host "Python: $py"
