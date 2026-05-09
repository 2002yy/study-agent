# package_project.ps1
# Creates a release zip with forward-slash paths.
param(
    [string]$Version = "",
    [string]$OutputDir = "release",
    [switch]$IncludeTests = $true
)

$ErrorActionPreference = "Stop"
$Root = $PSScriptRoot | Split-Path -Parent

if (-not $Version) {
    $stateFile = Join-Path $Root "memory\internal_state.md"
    if (Test-Path $stateFile) {
        $text = Get-Content $stateFile -Raw -Encoding UTF8
        if ($text -match "current_version\s*:\s*(\S+)") {
            $Version = $Matches[1].Trim()
        }
    }
}
if (-not $Version) { $Version = "dev" }

$time = Get-Date -Format "yyyyMMdd_HHmmss"
$zipName = "study_agent_release_$Version`_$time.zip"
$OutputZip = Join-Path $Root "$OutputDir\$zipName"
$OutDir = Split-Path $OutputZip -Parent
if (-not (Test-Path $OutDir)) {
    New-Item -ItemType Directory -Path $OutDir | Out-Null
}

function Get-PythonCommand {
    $candidates = @("python", "py", "python3")
    foreach ($cmd in $candidates) {
        try {
            & $cmd --version | Out-Null
            return $cmd
        }
        catch {
            continue
        }
    }
    Write-Error "Python interpreter not found. Expected one of: python, py, python3."
    exit 1
}

$PythonCmd = Get-PythonCommand
$HelperScript = Join-Path $PSScriptRoot "package_project_helper.py"
$includeTestsFlag = if ($IncludeTests) { "1" } else { "0" }

Write-Host "Root: $Root"
Write-Host "Version: $Version"
Write-Host "Output: $OutputZip"

$result = & $PythonCmd $HelperScript $Root $OutputZip $includeTestsFlag 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Error $result
    exit 1
}

Write-Host $result
$sizeMB = [Math]::Round((Get-Item $OutputZip).Length / 1MB, 2)
Write-Host ("Done: {0} ({1} MB)" -f $OutputZip, $sizeMB)
