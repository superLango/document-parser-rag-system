# Stop processes started by deploy/start_local.ps1.
$ErrorActionPreference = "Stop"
$RunDir = Join-Path $PSScriptRoot "run"

foreach ($name in @("web", "worker", "api")) {
    $pidFile = Join-Path $RunDir "$name.pid"
    if (-not (Test-Path $pidFile)) { continue }
    $processId = [int](Get-Content $pidFile)
    $process = Get-Process -Id $processId -ErrorAction SilentlyContinue
    if ($null -eq $process) {
        Remove-Item $pidFile -Force
        Write-Host ("{0} not running (pid {1})" -f $name, $processId)
        continue
    }
    & taskkill /T /F /PID $processId | Out-Null
    Remove-Item $pidFile -Force
    Write-Host ("stopped {0} pid={1}" -f $name, $processId)
}
