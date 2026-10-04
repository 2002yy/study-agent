param(
    [switch]$Install,
    [switch]$NoBrowser,
    [switch]$SkipSearXNG,
    [ValidateRange(1024, 65535)][int]$BackendPort = 8000,
    [ValidateRange(1024, 65535)][int]$FrontendPort = 5173
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
$BackendUrl = "http://127.0.0.1:$BackendPort"
$FrontendUrl = "http://127.0.0.1:$FrontendPort"
$LogRoot = Join-Path $Root "logs\launcher"
$SearchStartupPending = $false
New-Item -ItemType Directory -Path $LogRoot -Force | Out-Null
if ($BackendPort -eq $FrontendPort) { throw "BackendPort and FrontendPort must differ" }

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
        $health = Invoke-RestMethod -Uri "$BackendUrl/health" -TimeoutSec 3
        return $health.service -eq "study-agent" -and $health.status -eq "ok"
    } catch {
        return $false
    }
}

function Test-FrontendIdentity {
    try {
        $response = Invoke-WebRequest -Uri $FrontendUrl -UseBasicParsing -TimeoutSec 3
        # Vite may omit charset; Windows PowerShell 5.1 otherwise decodes UTF-8
        # Chinese titles as Latin-1. Decode the original bytes explicitly.
        $html = [Text.Encoding]::UTF8.GetString($response.RawContentStream.ToArray())
        $index = [IO.File]::ReadAllText((Join-Path $Root "frontend\index.html"), [Text.Encoding]::UTF8)
        $title = [regex]::Match($index, '<title>[^<]+</title>').Value
        if (-not $title -or $html -notmatch [regex]::Escape($title)) { return $false }
        $health = Invoke-RestMethod -Uri "$FrontendUrl/health" -TimeoutSec 3
        return $health.service -eq "study-agent" -and $health.status -eq "ok"
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

function Start-PowerShellWindow([string]$Title, [string]$Command, [string]$LogName) {
    $safeTitle = $Title.Replace("'", "''")
    $fullCommand = (
        "`$Host.UI.RawUI.WindowTitle = '$safeTitle'" +
        [Environment]::NewLine +
        $Command
    )
    $encoded = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($fullCommand))
    Start-Process powershell.exe -ArgumentList @(
        "-NoProfile", "-ExecutionPolicy", "Bypass", "-OutputFormat", "Text", "-EncodedCommand", $encoded
    ) -WindowStyle Hidden -RedirectStandardOutput (Join-Path $LogRoot "$LogName.stdout.log") `
        -RedirectStandardError (Join-Path $LogRoot "$LogName.stderr.log") | Out-Null
}

function Start-SearXNG {
    if (Test-Listening 8080) {
        if (-not (Test-SearXNGIdentity)) {
            Fail "端口 8080 已被非 Study Agent SearXNG 服务占用"
        }
        return $true
    }

    if ($SkipSearXNG) {
        Write-Warning "已跳过 SearXNG 启动；应用继续使用当前可用的检索提供方。"
        return $false
    }

    $dockerCommand = Get-Command docker.exe -ErrorAction SilentlyContinue
    if (-not $dockerCommand) {
        Write-Warning "找不到 Docker CLI；应用仍会启动，但 SearXNG 状态为 unavailable。"
        return $false
    }
    $manager = Join-Path $PSScriptRoot "manage-searxng.ps1"
    if (-not (Test-Path -LiteralPath $manager -PathType Leaf)) {
        Write-Warning "找不到固定版本 SearXNG manager；应用仍会启动，但 SearXNG 状态为 unavailable。"
        return $false
    }
    # Preserve the manager's original PSScriptRoot. Search preparation must not
    # block opening the application; the manager owns Docker/container readiness.
    $managerQuoted = $manager.Replace("'", "''")
    $searchCommand = @"
`$ErrorActionPreference = 'Stop'
`$searchMutex = New-Object Threading.Mutex(`$false, 'Local\StudyAgentSearXNGLauncher')
if (-not `$searchMutex.WaitOne(0)) { `$searchMutex.Dispose(); exit 0 }
try {
    `$manager = '$managerQuoted'
    & `$manager -Action Ensure
} finally {
    `$searchMutex.ReleaseMutex()
    `$searchMutex.Dispose()
}
"@
    Start-PowerShellWindow "Study Agent Search" $searchCommand "searxng"
    $script:SearchStartupPending = $true
    Write-Host "SearXNG 正在后台准备；学习工作台可先使用。日志：$LogRoot" -ForegroundColor Cyan
    return $false
}

function Write-HealthLine([string]$Label, [string]$Status, [ConsoleColor]$Color) {
    Write-Host ("  {0,-12} {1}" -f $Label, $Status) -ForegroundColor $Color
}

function Write-StartupSummary([bool]$SearXNGStarted) {
    Write-Host ""
    Write-Host "Study Agent 运行状态" -ForegroundColor Cyan
    Write-HealthLine "后端 API" "ready · $BackendUrl" Green
    Write-HealthLine "前端 Web" "ready · $FrontendUrl" Green

    if (($SearXNGStarted -or $SearchStartupPending) -and (Test-SearXNGIdentity)) {
        Write-HealthLine "SearXNG 服务" "ready · http://127.0.0.1:8080" Green
    } elseif ($SearchStartupPending) {
        Write-HealthLine "SearXNG 服务" "starting · 后台准备中，当前可用检索提供方仍可使用" Yellow
    } else {
        Write-HealthLine "SearXNG 服务" "unavailable · 应用可用，联网研究将降级" Yellow
    }

    try {
        $providerHealth = Invoke-RestMethod -Uri "$BackendUrl/health/providers?probe=false" -TimeoutSec 3
        $provider = $providerHealth.providers | Where-Object { $_.name -eq "searxng" } | Select-Object -First 1
        if ($provider) {
            $providerColor = if ($provider.status -eq "ready") { [ConsoleColor]::Green } else { [ConsoleColor]::Yellow }
            Write-HealthLine "检索能力" ("{0} · {1}" -f $provider.status, $provider.detail) $providerColor
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

$rootQuoted = $Root.Replace("'", "''")
$pythonQuoted = $Python.Replace("'", "''")

if (Test-Listening $BackendPort) {
    if (-not (Test-BackendIdentity)) {
        Fail "端口 $BackendPort 已被非 Study Agent 服务占用"
    }
} else {
    $backend = [string]::Join([Environment]::NewLine, @(
        ("Set-Location '{0}'" -f $rootQuoted),
        ("& '{0}' -m uvicorn src.api.app:app --host 127.0.0.1 --port {1} --reload" -f $pythonQuoted, $BackendPort)
    ))
    Start-PowerShellWindow "Study Agent API :$BackendPort" $backend "api-$BackendPort"
}

# Child processes inherit these values. The API token is never embedded in the
# encoded PowerShell command or exposed in process command-line arguments.
$env:VITE_DEV_API_TARGET = $BackendUrl
$env:VITE_STUDY_AGENT_API_TOKEN = [string]$env:STUDY_AGENT_API_TOKEN
if (Test-Listening $FrontendPort) {
    if (-not (Test-FrontendIdentity)) {
        Fail "端口 $FrontendPort 已被非 Study Agent 服务占用或代理未就绪"
    }
} else {
    $frontend = [string]::Join([Environment]::NewLine, @(
        ("Set-Location '{0}\frontend'" -f $rootQuoted),
        ("& '{0}' run dev -- --host 127.0.0.1 --port {1} --strictPort" -f $Npm, $FrontendPort)
    ))
    Start-PowerShellWindow "Study Agent Web :$FrontendPort" $frontend "web-$FrontendPort"
}

if (-not (Wait-Until { Test-BackendIdentity })) {
    Fail "后端未在限定时间内通过身份检查"
}
if (-not (Wait-Until { Test-FrontendIdentity })) {
    Fail "前端未在限定时间内通过身份检查"
}

Write-Host "Study Agent 已就绪：$FrontendUrl" -ForegroundColor Green
if (-not $NoBrowser) { Start-Process $FrontendUrl }
$SearXNGStarted = Start-SearXNG
Write-StartupSummary $SearXNGStarted
Write-Host "启动日志：$LogRoot" -ForegroundColor Cyan
exit 0
