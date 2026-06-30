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
$env:VITE_STUDY_AGENT_API_TOKEN = [string]$env:STUDY_AGENT_API_TOKEN
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

Write-Host "Study Agent 已就绪：http://127.0.0.1:5173" -ForegroundColor Green
if (-not $NoBrowser) { Start-Process "http://127.0.0.1:5173" }
