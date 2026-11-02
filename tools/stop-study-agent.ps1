param(
    [string]$ConfigPath = '',
    [switch]$Force
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$ReceiptPath = Join-Path $Root 'logs\launcher\receipt.json'

function Write-Outcome([string]$Message, [ConsoleColor]$Color = [ConsoleColor]::Gray) {
    Write-Host $Message -ForegroundColor $Color
}

if (-not (Test-Path -LiteralPath $ReceiptPath -PathType Leaf)) {
    Write-Outcome "没有启动回执，未发现由本仓库启动的进程：$ReceiptPath" Yellow
    exit 0
}

$receipt = Get-Content -LiteralPath $ReceiptPath -Raw -Encoding UTF8 | ConvertFrom-Json
$recordedRoot = [IO.Path]::GetFullPath([string]$receipt.root)
$currentRoot = [IO.Path]::GetFullPath($Root)
if (-not $recordedRoot.Equals($currentRoot, [StringComparison]::OrdinalIgnoreCase)) {
    Write-Outcome "启动回执属于其他检出（$recordedRoot）；为安全起见不结束任何进程。" Yellow
    exit 2
}

function Get-Descendants([int]$ParentId) {
    $children = @(Get-CimInstance Win32_Process -Filter "ParentProcessId=$ParentId" -ErrorAction SilentlyContinue)
    foreach ($child in $children) {
        Get-Descendants $child.ProcessId
        $child
    }
}

function Get-PortOf([string]$Url) {
    try { return [int]([uri]$Url).Port } catch { return 0 }
}

# The recorded wrapper IDs usually exit before the services do, so the receipt
# ports are the durable anchor: a listening socket is unambiguous, and the
# process fingerprint (uvicorn / vite) proves it is this application rather
# than an unrelated local server. Docker and the SearXNG container are never
# touched here.
$targets = @{}
foreach ($id in @($receipt.started_process_ids)) {
    $process = Get-CimInstance Win32_Process -Filter "ProcessId=$id" -ErrorAction SilentlyContinue
    if ($process) {
        $targets[[int]$process.ProcessId] = $process
        foreach ($child in @(Get-Descendants $process.ProcessId)) { $targets[[int]$child.ProcessId] = $child }
    }
}

foreach ($url in @([string]$receipt.backend_url, [string]$receipt.frontend_url)) {
    $port = Get-PortOf $url
    if (-not $port) { continue }
    $connections = @(Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue)
    foreach ($connection in $connections) {
        $process = Get-CimInstance Win32_Process -Filter "ProcessId=$($connection.OwningProcess)" -ErrorAction SilentlyContinue
        if (-not $process) { continue }
        $commandLine = [string]$process.CommandLine
        $looksLikeThisApp = $commandLine -match 'uvicorn\s+src\.api\.app' -or $commandLine -match 'vite'
        $insideCheckout = $commandLine.IndexOf($currentRoot, [StringComparison]::OrdinalIgnoreCase) -ge 0
        if ($looksLikeThisApp -or $insideCheckout -or $Force) {
            $targets[[int]$process.ProcessId] = $process
            foreach ($child in @(Get-Descendants $process.ProcessId)) { $targets[[int]$child.ProcessId] = $child }
        } else {
            Write-Outcome "端口 $port 由不属于 Study Agent 的进程占用，已跳过（pid $($process.ProcessId)）" Yellow
        }
    }
}

$stopped = @()
foreach ($process in $targets.Values) {
    try {
        Stop-Process -Id $process.ProcessId -Force -ErrorAction Stop
        $stopped += [pscustomobject]@{ Id = $process.ProcessId; Name = $process.Name }
    } catch {
        # Already exited between discovery and shutdown.
    }
}

if ($stopped.Count -eq 0) {
    Write-Outcome "没有发现仍在运行的 Study Agent 进程。" Yellow
} else {
    Write-Outcome "已结束 $($stopped.Count) 个 Study Agent 进程" Green
    foreach ($row in $stopped) { Write-Outcome ("  {0} (pid {1})" -f $row.Name, $row.Id) }
}

$remaining = @()
foreach ($url in @([string]$receipt.backend_url, [string]$receipt.frontend_url)) {
    $port = Get-PortOf $url
    if ($port -and @(Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue).Count) {
        $remaining += $port
    }
}
if ($remaining.Count) {
    Write-Outcome ("端口仍被占用：{0}" -f ($remaining -join ', ')) Yellow
    exit 1
}

Write-Outcome "Docker / SearXNG 容器未改动；如需停止检索服务请使用 tools\manage-searxng.ps1。"
Remove-Item -LiteralPath $ReceiptPath -Force -ErrorAction SilentlyContinue
