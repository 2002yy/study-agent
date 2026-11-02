param(
    [switch]$Install,
    [switch]$NoBrowser,
    [switch]$SkipSearXNG,
    [switch]$StartSearXNG,
    [string]$ProjectRoot = (Join-Path $PSScriptRoot 'study agent'),
    [string]$ConfigPath = '',
    [string]$PythonExecutable = '',
    [ValidateRange(1024, 65535)][int]$BackendPort = 8001,
    [ValidateRange(1024, 65535)][int]$FrontendPort = 5174
)

$ErrorActionPreference = 'Stop'
$repoStart = Join-Path $ProjectRoot 'tools\start-study-agent.ps1'
if (-not (Test-Path -LiteralPath $repoStart -PathType Leaf)) {
    Write-Error "Missing Study Agent startup script: $repoStart"
    exit 1
}

try {
    # Docker/SearXNG starts by default. Only an explicit offline request skips it.
    $skipSearchStartup = $SkipSearXNG -and -not $StartSearXNG
    & $repoStart -BackendPort $BackendPort -FrontendPort $FrontendPort `
        -ConfigPath $ConfigPath -PythonExecutable $PythonExecutable `
        -Install:$Install -NoBrowser:$NoBrowser -SkipSearXNG:$skipSearchStartup
    exit $LASTEXITCODE
} catch {
    Write-Error "Study Agent startup failed: $($_.Exception.Message)"
    exit 1
}
