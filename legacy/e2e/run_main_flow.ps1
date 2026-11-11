# Run the main-path E2E test against an isolated platform database.
# Starts API (8765) and web (5173) with mock OCR/extractor, then runs
# e2e/test_main_flow.py in a real Chromium via Python Playwright.

param(
    [int]$ApiPort = 8765,
    [int]$WebPort = 5173,
    [switch]$KeepData
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Tmp = Join-Path $PSScriptRoot ".tmp"
$LogDir = Join-Path $Tmp "logs"

function Wait-Http {
    param([string]$Url, [int]$TimeoutSeconds = 90)
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        try {
            $response = Invoke-WebRequest -UseBasicParsing -Uri $Url -TimeoutSec 3
            if ($response.StatusCode -ge 200 -and $response.StatusCode -lt 400) {
                return
            }
        } catch {
            # service not ready yet
        }
        Start-Sleep -Milliseconds 500
    }
    throw "timeout waiting for $Url"
}

python -c "import playwright" 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host "python playwright is not installed: python -m pip install playwright && python -m playwright install chromium" -ForegroundColor Red
    exit 2
}

foreach ($port in @($ApiPort, $WebPort)) {
    if (Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue) {
        Write-Host "port $port is already in use; stop the local stack first" -ForegroundColor Red
        exit 2
    }
}

if (Test-Path $Tmp) {
    Remove-Item -Recurse -Force $Tmp
}
New-Item -ItemType Directory -Force -Path `
    (Join-Path $Tmp "platform"), (Join-Path $Tmp "engine"), $LogDir | Out-Null

$env:HANSON_PLATFORM_DATA = Join-Path $Tmp "platform"
$dbPath = (Join-Path $env:HANSON_PLATFORM_DATA "platform.db").Replace("\", "/")
$env:HANSON_DATABASE_URL = "sqlite:///$dbPath"
$env:HANSON_SECRET_KEY = "e2e-secret"
$env:HANSON_INLINE_JOBS = "1"
$env:METAL_DOC_DATA = Join-Path $Tmp "engine"
$env:METAL_DOC_OCR = "mock"
$env:METAL_DOC_EXTRACTOR = "mock"
$env:E2E_BASE_URL = "http://127.0.0.1:$WebPort"
$env:E2E_USERNAME = "e2e"
$env:E2E_PASSWORD = "e2e-pass"

$api = $null
$web = $null
$code = 1
try {
    Push-Location (Join-Path $Root "apps\api")
    try {
        python -m hanson_api.bootstrap --username e2e --password "e2e-pass" | Out-Host
    } finally {
        Pop-Location
    }

    $api = Start-Process python -ArgumentList @(
        "-m", "uvicorn", "hanson_api.main:app", "--app-dir", "apps/api",
        "--host", "127.0.0.1", "--port", "$ApiPort"
    ) -WorkingDirectory $Root -RedirectStandardOutput "$LogDir\api.out.log" `
        -RedirectStandardError "$LogDir\api.err.log" -PassThru -WindowStyle Hidden

    $vite = Join-Path $Root "apps\web\node_modules\vite\bin\vite.js"
    $web = Start-Process node -ArgumentList @(
        $vite, "--host", "127.0.0.1", "--port", "$WebPort"
    ) -WorkingDirectory (Join-Path $Root "apps\web") -RedirectStandardOutput "$LogDir\web.out.log" `
        -RedirectStandardError "$LogDir\web.err.log" -PassThru -WindowStyle Hidden

    Wait-Http "http://127.0.0.1:$ApiPort/health" 90
    Wait-Http "http://127.0.0.1:$WebPort/" 90

    Push-Location $Root
    try {
        $test = Start-Process python -ArgumentList @(
            (Join-Path $Root "e2e\test_main_flow.py")
        ) -WorkingDirectory $Root -NoNewWindow -Wait -PassThru `
            -RedirectStandardOutput (Join-Path $LogDir "e2e.out.log") `
            -RedirectStandardError (Join-Path $LogDir "e2e.err.log")
        $code = $test.ExitCode
        Get-Content (Join-Path $LogDir "e2e.out.log") -ErrorAction SilentlyContinue
        Get-Content (Join-Path $LogDir "e2e.err.log") -ErrorAction SilentlyContinue
    } finally {
        Pop-Location
    }
    if ($code -eq 0) {
        Write-Host "E2E passed" -ForegroundColor Green
    }
} catch {
    Write-Host "E2E failed: $_" -ForegroundColor Red
    $code = 1
} finally {
    if ($web) { & taskkill /PID $web.Id /T /F *> $null }
    if ($api) { Stop-Process -Id $api.Id -Force -ErrorAction SilentlyContinue }
    if ($code -ne 0) {
        Write-Host "logs kept at $LogDir" -ForegroundColor Yellow
        Get-ChildItem $LogDir -File | ForEach-Object {
            Write-Host "--- $($_.Name)"
            Get-Content $_.FullName -Tail 30
        }
    } elseif (-not $KeepData) {
        Remove-Item -Recurse -Force $Tmp
    }
}
exit $code
