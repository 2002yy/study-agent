param(
    [switch]$Install,
    [switch]$NoBrowser,
    [switch]$SkipSearXNG,
    [ValidateRange(1024, 65535)][int]$BackendPort = 8000,
    [ValidateRange(1024, 65535)][int]$FrontendPort = 5173,
    [string]$ConfigPath = '',
    [string]$PythonExecutable = ''
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
if (-not $ConfigPath) { $ConfigPath = Join-Path $Root '.env' }
$BackendUrl = "http://127.0.0.1:$BackendPort"
$FrontendUrl = "http://127.0.0.1:$FrontendPort"
$LaunchLogDirectory = Join-Path $Root 'logs\launcher'
$StartedProcessIds = @()

# The frontend identity probe lives in its own file so the tests can exercise
# the same code the launcher runs.
. (Join-Path $PSScriptRoot "frontend-identity.ps1")

function Fail([string]$Message) {
    Write-Host "启动失败：$Message" -ForegroundColor Red
    exit 1
}

function Import-DotEnv([string]$Path) {
    if (-not (Test-Path -LiteralPath $Path)) { return }
    foreach ($line in Get-Content -LiteralPath $Path -Encoding UTF8) {
        $text = $line.Trim()
        if (-not $text -or $text.StartsWith("#")) { continue }
        $index = $text.IndexOf("=")
        if ($index -le 0) { continue }
        $name = $text.Substring(0, $index).Trim()
        $value = $text.Substring($index + 1).Trim()
        if (($value.StartsWith('"') -and $value.EndsWith('"')) -or
            ($value.StartsWith("'") -and $value.EndsWith("'"))) {
            $value = $value.Substring(1, $value.Length - 2)
        }
        # Explicit CLI environment wins, including the shared live-test budget.
        if ($null -eq [Environment]::GetEnvironmentVariable($name, "Process")) {
            [Environment]::SetEnvironmentVariable($name, $value, "Process")
        }
    }
}

function Test-Listening([int]$Port) {
    $client = [System.Net.Sockets.TcpClient]::new()
    try {
        $result = $client.BeginConnect("127.0.0.1", $Port, $null, $null)
        if (-not $result.AsyncWaitHandle.WaitOne(350)) { return $false }
        $client.EndConnect($result)
        return $true
    } catch {
        return $false
    } finally {
        $client.Dispose()
    }
}

function Test-BackendIdentity {
    try {
        $health = Invoke-RestMethod -Uri "$BackendUrl/health" -TimeoutSec 3
        return $health.service -eq "study-agent"
    } catch {
        return $false
    }
}

function Test-FrontendIdentity {
    try {
        $response = Invoke-WebRequest -Uri $FrontendUrl -UseBasicParsing -TimeoutSec 3
        return Test-StudyAgentFrontendContent -Content $response.Content
    } catch {
        return $false
    }
}

function Test-SearXNGIdentity {
    try {
        $response = Invoke-WebRequest -Uri "http://127.0.0.1:8080/healthz" -UseBasicParsing -TimeoutSec 3
        return $response.StatusCode -eq 200 -and $response.Content.Trim() -eq "OK"
    } catch {
        return $false
    }
}

function Wait-Until([scriptblock]$Probe, [int]$TimeoutSeconds = 45) {
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        if (& $Probe) { return $true }
        Start-Sleep -Milliseconds 700
    }
    return $false
}

function Start-ServiceProcess([string]$Name, [string]$FilePath, [string[]]$Arguments, [string]$WorkingDirectory) {
    New-Item -ItemType Directory -Path $LaunchLogDirectory -Force | Out-Null
    # Launch the service executable directly: the recorded PID is the process a
    # stop request must end, and its output lands in the launcher logs without a
    # hidden PowerShell hop swallowing it.
    $process = Start-Process -FilePath $FilePath -ArgumentList $Arguments `
        -WorkingDirectory $WorkingDirectory -WindowStyle Hidden -PassThru `
        -RedirectStandardOutput (Join-Path $LaunchLogDirectory "$Name.stdout.log") `
        -RedirectStandardError (Join-Path $LaunchLogDirectory "$Name.stderr.log")
    $script:StartedProcessIds += $process.Id
}

function Start-SearXNG {
    if (Test-Listening 8080) {
        if (-not (Test-SearXNGIdentity)) {
            Fail "端口 8080 已被非 Study Agent SearXNG 服务占用"
        }
    }

    # The manager owns Docker startup and the pinned container lifecycle.
    $manager = Join-Path $PSScriptRoot "manage-searxng.ps1"
    if (-not (Test-Path -LiteralPath $manager -PathType Leaf)) {
        Write-Warning "找不到固定版本 SearXNG manager；应用仍会启动，但 SearXNG 状态为 unavailable。"
        return $false
    }
    try {
        & $manager -Action Ensure
    } catch {
        Write-Warning "固定版本 SearXNG 未就绪：$($_.Exception.Message)"
        return $false
    }
    if (-not (Wait-Until { Test-SearXNGIdentity } 60)) {
        Write-Warning "SearXNG 未在 60 秒内通过 /healthz；应用仍会启动，但联网研究可能降级。"
        return $false
    }
    return $true
}

function Write-HealthLine([string]$Label, [string]$Status, [ConsoleColor]$Color) {
    Write-Host ("  {0,-12} {1}" -f $Label, $Status) -ForegroundColor $Color
}

function Write-StartupSummary([bool]$SearXNGStarted) {
    Write-Host ""
    Write-Host "Study Agent 运行状态" -ForegroundColor Cyan
    Write-HealthLine "后端 API" "ready · $BackendUrl" Green
    Write-HealthLine "前端 Web" "ready · $FrontendUrl" Green

    if ($SearXNGStarted -and (Test-SearXNGIdentity)) {
        Write-HealthLine "SearXNG 服务" "ready · http://127.0.0.1:8080" Green
    } else {
        Write-HealthLine "SearXNG 服务" "unavailable · 应用可用，联网研究将降级" Yellow
    }

    try {
        if ([string]::IsNullOrWhiteSpace([string]$env:STUDY_AGENT_API_TOKEN)) {
            Write-HealthLine "检索能力" "未配置 API 令牌，跳过探针（先设置 STUDY_AGENT_API_TOKEN）" Yellow
        } else {
            $probeHeaders = @{ "X-Study-Agent-Token" = [string]$env:STUDY_AGENT_API_TOKEN }
            $providerHealth = Invoke-RestMethod -Uri "$BackendUrl/health/providers?probe=true" -Headers $probeHeaders -TimeoutSec 10
            $provider = $providerHealth.providers | Where-Object { $_.name -eq "searxng" } | Select-Object -First 1
            if ($provider) {
                $providerColor = if ($provider.status -eq "ready") { [ConsoleColor]::Green } else { [ConsoleColor]::Yellow }
                Write-HealthLine "检索能力" ("{0} · {1}" -f $provider.status, $provider.detail) $providerColor
            }
        }
    } catch {
        Write-HealthLine "检索能力" "unknown · provider probe failed" Yellow
    }

    Write-Host ""
    Write-Host "启动回执与服务日志：$LaunchLogDirectory"
    Write-Host "功能验证使用 CLI；实体手机人工检查清单见 docs/MOBILE_ACCEPTANCE_D4D.md。"
    Write-Host ""
}

if (-not (Test-Path "requirements.txt")) { Fail "找不到 requirements.txt" }
if (-not (Test-Path "frontend\package.json")) { Fail "找不到 frontend\package.json" }
if (-not (Test-Path -LiteralPath $ConfigPath)) {
    if ($ConfigPath -ne (Join-Path $Root '.env')) { Fail "找不到指定配置文件" }
    if (-not (Test-Path ".env.example")) { Fail "找不到 .env.example" }
    Copy-Item ".env.example" ".env"
    Fail "已创建 .env；请填写配置后重新运行脚本"
}
Import-DotEnv $ConfigPath

$Python = if ($PythonExecutable) { $PythonExecutable } else { Join-Path $Root ".venv\Scripts\python.exe" }
$FreshPython = $false
if (-not (Test-Path $Python)) {
    if ($PythonExecutable) { Fail "找不到指定 Python" }
    if (Get-Command py -ErrorAction SilentlyContinue) {
        & py -3.12 -m venv ".venv"
        if ($LASTEXITCODE -ne 0) { & py -3 -m venv ".venv" }
    } elseif (Get-Command python -ErrorAction SilentlyContinue) {
        & python -m venv ".venv"
    } else {
        Fail "找不到 Python"
    }
    $Install = $true
    $FreshPython = $true
}

$Npm = (Get-Command npm.cmd -ErrorAction SilentlyContinue).Source
if (-not $Npm) { Fail "找不到 npm.cmd，请安装 Node.js LTS" }

# Python and frontend dependencies install independently: a half-populated
# .venv must not be masked by an existing frontend\node_modules.
if ($Install -or $FreshPython) {
    & $Python -m pip install -r "requirements.txt"
    if ($LASTEXITCODE -ne 0) { Fail "Python 依赖安装失败" }
}
if ($Install -or $FreshPython -or -not (Test-Path "frontend\node_modules")) {
    Push-Location "frontend"
    try {
        if (Test-Path "package-lock.json") { & $Npm ci } else { & $Npm install }
        if ($LASTEXITCODE -ne 0) { Fail "前端依赖安装失败" }
    } finally {
        Pop-Location
    }
}

# Piped child output is block buffered otherwise: the launcher logs would stay
# empty for minutes even while the service is serving traffic.
$env:PYTHONUNBUFFERED = "1"
$env:PYTHONIOENCODING = "utf-8"

$SearXNGStarted = if ($SkipSearXNG) { Test-SearXNGIdentity } else { Start-SearXNG }
if (-not $SkipSearXNG -and -not $SearXNGStarted) { Fail "Docker / SearXNG 尚未就绪" }

if (Test-Listening $BackendPort) {
    if (-not (Test-BackendIdentity)) {
        Fail "端口 $BackendPort 已被非 Study Agent 服务占用"
    }
} else {
    Start-ServiceProcess 'backend' $Python `
        @("-m", "uvicorn", "src.api.app:app", "--host", "127.0.0.1", "--port", "$BackendPort") `
        $Root
}

# Child processes inherit these values. The API token is never written into the
# service command line, where any local process could read it.
$env:VITE_DEV_API_TARGET = $BackendUrl
# Vite exposes every VITE_* variable to client code, so the server secret must
# never be handed to the dev server under that name - not even to "help" a
# browser. The app reads the token from its own settings (localStorage) instead.
# Clear any value inherited from the parent shell or an old .env.
Remove-Item Env:VITE_STUDY_AGENT_API_TOKEN -ErrorAction SilentlyContinue
if (Test-Listening $FrontendPort) {
    if (-not (Test-FrontendIdentity)) {
        Fail "端口 $FrontendPort 已被非 Study Agent 服务占用"
    }
} else {
    $Node = (Get-Command node.exe -ErrorAction SilentlyContinue).Source
    $ViteBin = Join-Path $Root "frontend\node_modules\vite\bin\vite.js"
    if ($Node -and (Test-Path -LiteralPath $ViteBin -PathType Leaf)) {
        Start-ServiceProcess 'frontend' $Node `
            @("$ViteBin", "--host", "127.0.0.1", "--port", "$FrontendPort", "--strictPort") `
            (Join-Path $Root "frontend")
    } else {
        # Fall back to the package script when the local Vite entry is absent.
        Start-ServiceProcess 'frontend' $Npm `
            @("run", "dev", "--", "--host", "127.0.0.1", "--port", "$FrontendPort", "--strictPort") `
            (Join-Path $Root "frontend")
    }
}

if (-not (Wait-Until { Test-BackendIdentity })) {
    Fail "后端未在限定时间内通过身份检查"
}
if (-not (Wait-Until { Test-FrontendIdentity })) {
    Fail "前端未在限定时间内通过身份检查"
}

Write-StartupSummary $SearXNGStarted
New-Item -ItemType Directory -Path $LaunchLogDirectory -Force | Out-Null
@{
    root = $Root; backend_url = $BackendUrl; frontend_url = $FrontendUrl
    started_process_ids = $StartedProcessIds; started_at = (Get-Date).ToString('o')
} | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $LaunchLogDirectory 'receipt.json') -Encoding UTF8
Write-Host "Study Agent 已就绪：$FrontendUrl" -ForegroundColor Green
if (-not $NoBrowser) { Start-Process $FrontendUrl }
