param(
    [switch]$Install,
    [switch]$NoBrowser
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

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
        [Environment]::SetEnvironmentVariable($name, $value, "Process")
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
        $health = Invoke-RestMethod -Uri "http://127.0.0.1:8000/health" -TimeoutSec 3
        return $health.service -eq "study-agent"
    } catch {
        return $false
    }
}

function Test-FrontendIdentity {
    try {
        $response = Invoke-WebRequest -Uri "http://127.0.0.1:5173" -UseBasicParsing -TimeoutSec 3
        return $response.Content -match "<title>Study Agent Console</title>"
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

function Start-PowerShellWindow([string]$Title, [string]$Command) {
    $safeTitle = $Title.Replace("'", "''")
    $fullCommand = (
        "`$Host.UI.RawUI.WindowTitle = '$safeTitle'" +
        [Environment]::NewLine +
        $Command
    )
    $encoded = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($fullCommand))
    Start-Process powershell.exe -ArgumentList @(
        "-NoExit", "-NoProfile", "-ExecutionPolicy", "Bypass", "-EncodedCommand", $encoded
    ) | Out-Null
}

function Test-DockerReady([string]$Docker) {
    & $Docker info --format "{{.ServerVersion}}" *> $null
    return $LASTEXITCODE -eq 0
}

function Start-DockerDesktop([string]$Docker) {
    if (Test-DockerReady $Docker) { return $true }

    $desktopCandidates = @(
        "C:\Program Files\Docker\Docker\Docker Desktop.exe",
        (Join-Path $env:ProgramFiles "Docker\Docker\Docker Desktop.exe")
    ) | Select-Object -Unique
    $desktop = $desktopCandidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
    if (-not $desktop) { return $false }

    Write-Host "正在启动 Docker Desktop，以恢复本地 SearXNG..." -ForegroundColor Cyan
    Start-Process -FilePath $desktop -WindowStyle Hidden | Out-Null
    return Wait-Until { Test-DockerReady $Docker } 120
}

function Start-SearXNG {
    if (Test-Listening 8080) {
        if (-not (Test-SearXNGIdentity)) {
            Fail "端口 8080 已被非 Study Agent SearXNG 服务占用"
        }
    }

    $dockerCommand = Get-Command docker.exe -ErrorAction SilentlyContinue
    if (-not $dockerCommand) {
        Write-Warning "找不到 Docker CLI；应用仍会启动，但 SearXNG 状态为 unavailable。"
        return $false
    }
    $docker = $dockerCommand.Source
    if (-not (Start-DockerDesktop $docker)) {
        Write-Warning "Docker Desktop 未能在 120 秒内就绪；应用仍会启动，但 SearXNG 状态为 unavailable。"
        return $false
    }

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
    Write-HealthLine "后端 API" "ready · http://127.0.0.1:8000" Green
    Write-HealthLine "前端 Web" "ready · http://127.0.0.1:5173" Green

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
            $providerHealth = Invoke-RestMethod -Uri "http://127.0.0.1:8000/health/providers?probe=true" -Headers $probeHeaders -TimeoutSec 10
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
    Write-Host "人工检查清单（本次启动不自动判定通过）" -ForegroundColor Cyan
    Write-Host "  [ ] 1. 首页、恢复卡和输入框可见，无横向滚动或遮挡"
    Write-Host "  [ ] 2. 发送一个真实学习问题，回复、Learning 状态与引用一致"
    Write-Host "  [ ] 3. 设置 → 检测联网搜索显示 SearXNG 可用；研究结果含可点击来源"
    Write-Host "  [ ] 4. Enter / Ctrl+Enter 设置、焦点返回和错误提示符合预期"
    Write-Host "  [ ] 5. 缩窄窗口后检查抽屉、输入区、来源和恢复操作"
    Write-Host "  [ ] 6. 使用真实屏幕阅读器检查 landmark、按钮名称与动态播报"
    Write-Host "  [ ] 7. 检查普通/高对比度下的正文、焦点环、状态与链接辨识度"
    Write-Host "  [ ] 8. 实体手机验收仍须按 docs/MOBILE_ACCEPTANCE_D4D.md 单独记录"
    Write-Host ""
}

if (-not (Test-Path "requirements.txt")) { Fail "找不到 requirements.txt" }
if (-not (Test-Path "frontend\package.json")) { Fail "找不到 frontend\package.json" }
if (-not (Test-Path ".env")) {
    if (-not (Test-Path ".env.example")) { Fail "找不到 .env.example" }
    Copy-Item ".env.example" ".env"
    Start-Process notepad.exe (Join-Path $Root ".env")
    Fail "已创建 .env；请填写配置后重新运行脚本"
}
Import-DotEnv (Join-Path $Root ".env")

$Python = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $Python)) {
    if (Get-Command py -ErrorAction SilentlyContinue) {
        & py -3.12 -m venv ".venv"
        if ($LASTEXITCODE -ne 0) { & py -3 -m venv ".venv" }
    } elseif (Get-Command python -ErrorAction SilentlyContinue) {
        & python -m venv ".venv"
    } else {
        Fail "找不到 Python"
    }
    $Install = $true
}

$Npm = (Get-Command npm.cmd -ErrorAction SilentlyContinue).Source
if (-not $Npm) { Fail "找不到 npm.cmd，请安装 Node.js LTS" }

if ($Install -or -not (Test-Path "frontend\node_modules")) {
    & $Python -m pip install -r "requirements.txt"
    if ($LASTEXITCODE -ne 0) { Fail "Python 依赖安装失败" }
    Push-Location "frontend"
    try {
        if (Test-Path "package-lock.json") { & $Npm ci } else { & $Npm install }
        if ($LASTEXITCODE -ne 0) { Fail "前端依赖安装失败" }
    } finally {
        Pop-Location
    }
}

$SearXNGStarted = Start-SearXNG

$rootQuoted = $Root.Replace("'", "''")
$pythonQuoted = $Python.Replace("'", "''")

if (Test-Listening 8000) {
    if (-not (Test-BackendIdentity)) {
        Fail "端口 8000 已被非 Study Agent 服务占用"
    }
} else {
    $backend = [string]::Join([Environment]::NewLine, @(
        ("Set-Location '{0}'" -f $rootQuoted),
        ("& '{0}' -m uvicorn src.api.app:app --host 127.0.0.1 --port 8000 --reload" -f $pythonQuoted)
    ))
    Start-PowerShellWindow "Study Agent API :8000" $backend
}

# Child processes inherit these values. The API token is never embedded in the
# encoded PowerShell command or exposed in process command-line arguments.
$env:VITE_DEV_API_TARGET = "http://127.0.0.1:8000"
# Vite exposes every VITE_* variable to client code, so the server secret must
# never be handed to the dev server under that name - not even to "help" a
# browser. The app reads the token from its own settings (localStorage) instead.
# Clear any value inherited from the parent shell or an old .env.
Remove-Item Env:VITE_STUDY_AGENT_API_TOKEN -ErrorAction SilentlyContinue
if (Test-Listening 5173) {
    if (-not (Test-FrontendIdentity)) {
        Fail "端口 5173 已被非 Study Agent 服务占用"
    }
} else {
    $frontend = [string]::Join([Environment]::NewLine, @(
        ("Set-Location '{0}\frontend'" -f $rootQuoted),
        ("& '{0}' run dev -- --host 127.0.0.1" -f $Npm)
    ))
    Start-PowerShellWindow "Study Agent Web :5173" $frontend
}

if (-not (Wait-Until { Test-BackendIdentity })) {
    Fail "后端未在限定时间内通过身份检查"
}
if (-not (Wait-Until { Test-FrontendIdentity })) {
    Fail "前端未在限定时间内通过身份检查"
}

Write-StartupSummary $SearXNGStarted
Write-Host "Study Agent 已就绪：http://127.0.0.1:5173" -ForegroundColor Green
if (-not $NoBrowser) { Start-Process "http://127.0.0.1:5173" }
