# Start the platform plane + engine plane on this workstation.
# Model plane: public tunnel first, LAN 192.168.188.75 as automatic fallback.
param(
    [int]$ApiPort = 8765,
    [int]$WebPort = 5173,
    [switch]$NoWeb,
    [switch]$SkipModelCheck
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$RunDir = Join-Path $PSScriptRoot "run"
$LogDir = Join-Path $PSScriptRoot "logs"
New-Item -ItemType Directory -Force -Path $RunDir, $LogDir | Out-Null

# Load deploy/.env when present; existing process env wins.
$EnvFile = Join-Path $PSScriptRoot ".env"
if (Test-Path $EnvFile) {
    Get-Content $EnvFile | ForEach-Object {
        $line = $_.Trim()
        if ($line -and -not $line.StartsWith("#") -and $line -match "^([^=]+)=(.*)$") {
            $name = $matches[1].Trim()
            $value = $matches[2].Trim().Trim('"')
            if (-not [Environment]::GetEnvironmentVariable($name, "Process")) {
                [Environment]::SetEnvironmentVariable($name, $value, "Process")
            }
        }
    }
}

if (-not $env:GLM_OCR_BASE_URL) { $env:GLM_OCR_BASE_URL = "http://39.107.239.208:35032/v1" }
if (-not $env:GLM_OCR_FALLBACK_BASE_URL) { $env:GLM_OCR_FALLBACK_BASE_URL = "http://192.168.188.75:9977/v1" }
if (-not $env:LAYOUT_SERVICE_URL) { $env:LAYOUT_SERVICE_URL = "http://39.107.239.208:35034" }
if (-not $env:LAYOUT_SERVICE_FALLBACK_URL) { $env:LAYOUT_SERVICE_FALLBACK_URL = "http://192.168.188.75:9979" }
if (-not $env:LAYOUT_SERVICE_FALLBACK_URLS) { $env:LAYOUT_SERVICE_FALLBACK_URLS = "http://192.168.188.75:9978,http://39.107.239.208:35033" }
if (-not $env:QWEN_BASE_URL) { $env:QWEN_BASE_URL = "http://39.107.239.208:35035/v1" }
if (-not $env:QWEN_FALLBACK_BASE_URL) { $env:QWEN_FALLBACK_BASE_URL = "http://192.168.188.75:9991/v1" }
if (-not $env:SFT_BASE_URL) { $env:SFT_BASE_URL = "http://39.107.239.208:35035/v1" }
if (-not $env:SFT_FALLBACK_BASE_URL) { $env:SFT_FALLBACK_BASE_URL = "http://192.168.188.75:9991/v1" }
if (-not $env:MODEL_FAILOVER_PROBE_SECONDS) { $env:MODEL_FAILOVER_PROBE_SECONDS = "60" }
if (-not $env:SFT_MODEL) { $env:SFT_MODEL = "adapter-v5" }
if (-not $env:QWEN_MODEL) { $env:QWEN_MODEL = "Qwen3.5-9B" }
if (-not $env:METAL_DOC_OCR) { $env:METAL_DOC_OCR = "glm" }
if (-not $env:METAL_DOC_EXTRACTOR) { $env:METAL_DOC_EXTRACTOR = "qwen" }
if (-not $env:METAL_DOC_EXTRACTOR_PROMPT) { $env:METAL_DOC_EXTRACTOR_PROMPT = "sft_m2" }
if (-not $env:METAL_DOC_SFT_RULES_FIRST) { $env:METAL_DOC_SFT_RULES_FIRST = "1" }
if (-not $env:METAL_DOC_SFT_ROW_LIMIT) { $env:METAL_DOC_SFT_ROW_LIMIT = "0" }
if (-not $env:MODEL_TIMEOUT) { $env:MODEL_TIMEOUT = "180" }
if (-not $env:HANSON_ENV) { $env:HANSON_ENV = "local" }
if (-not $env:HANSON_INLINE_JOBS) { $env:HANSON_INLINE_JOBS = "false" }
if (-not $env:HANSON_DATABASE_URL) { $env:HANSON_DATABASE_URL = "sqlite:///data/platform/platform.db" }

function Assert-Service {
    param([string]$Name, [string[]]$Urls)
    $errors = @()
    foreach ($Url in $Urls) {
        if (-not $Url) { continue }
        try {
            $response = Invoke-WebRequest -UseBasicParsing -Uri $Url -TimeoutSec 4
            if ($response.StatusCode -ge 500) { throw "HTTP $($response.StatusCode)" }
            Write-Host ("model {0} ok  {1}" -f $Name, $Url)
            return
        } catch {
            $errors += ("{0}: {1}" -f $Url, $_.Exception.Message)
        }
    }
    throw ("{0} is not reachable. Tried: {1}. Start the model plane first (docs/runbook.md), or pass -SkipModelCheck." -f $Name, ($errors -join "; "))
}

if (-not $SkipModelCheck) {
    Assert-Service "GLM-OCR" @(
        ($env:GLM_OCR_BASE_URL.TrimEnd("/") + "/models"),
        ($env:GLM_OCR_FALLBACK_BASE_URL.TrimEnd("/") + "/models")
    )
    $layoutUrls = @(
        ($env:LAYOUT_SERVICE_URL.TrimEnd("/") + "/health"),
        ($env:LAYOUT_SERVICE_FALLBACK_URL.TrimEnd("/") + "/health")
    )
    if ($env:LAYOUT_SERVICE_FALLBACK_URLS) {
        $layoutUrls += $env:LAYOUT_SERVICE_FALLBACK_URLS.Split(",") |
            ForEach-Object { $_.Trim().TrimEnd("/") + "/health" }
    }
    Assert-Service "layout" $layoutUrls
    Assert-Service "vLLM" @(
        ($env:QWEN_BASE_URL.TrimEnd("/") + "/models"),
        ($env:QWEN_FALLBACK_BASE_URL.TrimEnd("/") + "/models")
    )
}

function Start-Tracked {
    param(
        [string]$Name,
        [string]$FilePath,
        [string[]]$Arguments,
        [string]$WorkDir
    )
    $stdout = Join-Path $LogDir "$Name.out.log"
    $stderr = Join-Path $LogDir "$Name.err.log"
    $process = Start-Process -FilePath $FilePath -ArgumentList $Arguments `
        -WorkingDirectory $WorkDir -RedirectStandardOutput $stdout `
        -RedirectStandardError $stderr -PassThru -WindowStyle Hidden
    $process.Id | Set-Content (Join-Path $RunDir "$Name.pid")
    Write-Host ("started {0} pid={1} log={2}" -f $Name, $process.Id, $stdout)
}

Start-Tracked -Name "api" -FilePath "python" -WorkDir $Root -Arguments @(
    "-m", "uvicorn", "hanson_api.main:app", "--app-dir", "apps/api",
    "--host", "127.0.0.1", "--port", "$ApiPort"
)
Start-Tracked -Name "worker" -FilePath "python" -WorkDir $Root -Arguments @(
    "apps/worker/main.py", "--watch", "--poll", "2"
)
if (-not $NoWeb) {
    Start-Tracked -Name "web" -FilePath "pnpm" -WorkDir $Root -Arguments @(
        "--dir", "apps/web", "dev", "--", "--host", "127.0.0.1", "--port", "$WebPort"
    )
}

Write-Host ""
Write-Host ("API     http://127.0.0.1:{0}" -f $ApiPort)
if (-not $NoWeb) {
    Write-Host ("Web     http://127.0.0.1:{0}" -f $WebPort)
}
Write-Host "Models  public 39.107.239.208:35032/35033/35034/35035, fallback 192.168.188.75:9977/9978/9979/9991"
Write-Host "Stop    deploy/stop_local.ps1"
