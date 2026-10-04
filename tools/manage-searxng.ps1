[CmdletBinding()]
param(
    [ValidateSet("Ensure", "Upgrade", "Status", "ListRetained", "RemoveRetained")]
    [string]$Action = "Status",
    [string]$RetainedName = "",
    [switch]$ConfirmRemoval,
    [switch]$ProbeSearch
)

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot
$SearXNGRoot = Join-Path $RepoRoot "infra\searxng"
$ComposePath = Join-Path $SearXNGRoot "compose.yml"
$SettingsPath = Join-Path $SearXNGRoot "settings.yml"
$LocalEnvPath = Join-Path $SearXNGRoot ".env.local"
$ActiveContainerName = "study-agent-searxng"
$PinnedImage = "docker.io/searxng/searxng@sha256:c2dc2d9e6b910653e8628361c23443222490e4cabbb9e02667b7847143db843b"
$RetainedPattern = '^study-agent-searxng-retained-(\d{8}T\d{6}Z)$'

function Fail([string]$Message) {
    throw $Message
}

function Get-DockerCommand {
    $command = Get-Command docker.exe -ErrorAction SilentlyContinue
    if (-not $command) { Fail "找不到 Docker CLI" }
    return $command.Source
}

function Test-DockerReady([string]$DockerPath) {
    # An unavailable daemon is a probe result, not a terminating native stderr
    # error under Windows PowerShell 5.1's inherited Stop preference.
    $ErrorActionPreference = "Continue"
    & $DockerPath info --format "{{.ServerVersion}}" *> $null
    return $LASTEXITCODE -eq 0
}

function Wait-Until([scriptblock]$Probe, [int]$TimeoutSeconds = 60) {
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        if (& $Probe) { return $true }
        Start-Sleep -Milliseconds 700
    }
    return $false
}

function Start-DockerIfNeeded([string]$DockerPath) {
    if (Test-DockerReady $DockerPath) { return }
    $desktopCandidates = @(
        "C:\Program Files\Docker\Docker\Docker Desktop.exe",
        (Join-Path $env:ProgramFiles "Docker\Docker\Docker Desktop.exe")
    ) | Select-Object -Unique
    $desktop = $desktopCandidates |
        Where-Object { Test-Path -LiteralPath $_ } |
        Select-Object -First 1
    if (-not $desktop) { Fail "Docker daemon 未运行，且找不到 Docker Desktop" }
    Write-Host "正在启动 Docker Desktop..." -ForegroundColor Cyan
    Start-Process -FilePath $desktop -WindowStyle Hidden | Out-Null
    if (-not (Wait-Until { Test-DockerReady $DockerPath } 120)) {
        Fail "Docker Desktop 未能在 120 秒内就绪"
    }
}

function Get-Container([string]$DockerPath, [string]$Name) {
    # Missing containers must return null so Ensure can create/recover them.
    $ErrorActionPreference = "Continue"
    $json = & $DockerPath container inspect $Name 2> $null
    if ($LASTEXITCODE -ne 0 -or -not $json) { return $null }
    return ($json | ConvertFrom-Json)[0]
}

function Invoke-DockerChecked(
    [string]$DockerPath,
    [string[]]$Arguments,
    [string]$FailureMessage
) {
    & $DockerPath @Arguments
    if ($LASTEXITCODE -ne 0) { Fail $FailureMessage }
}

function ConvertTo-DotEnvLiteral([string]$Value) {
    if ($Value -match "[\r\n]") { Fail "本机代理值不能包含换行" }
    return "'" + $Value.Replace("'", "\'") + "'"
}

function New-LocalSecret {
    $bytes = New-Object byte[] 32
    $rng = [Security.Cryptography.RandomNumberGenerator]::Create()
    try {
        $rng.GetBytes($bytes)
    } finally {
        $rng.Dispose()
    }
    return ([BitConverter]::ToString($bytes)).Replace("-", "").ToLowerInvariant()
}

function Get-ExistingProxyValues([string]$DockerPath) {
    $values = @{
        HTTP_PROXY = ""
        HTTPS_PROXY = ""
        NO_PROXY = "127.0.0.1,localhost"
    }
    $container = Get-Container $DockerPath $ActiveContainerName
    if (-not $container) { return $values }
    foreach ($entry in @($container.Config.Env)) {
        $parts = [string]$entry -split '=', 2
        if ($parts.Count -eq 2 -and $values.ContainsKey($parts[0])) {
            $values[$parts[0]] = $parts[1]
        }
    }
    return $values
}

function Initialize-LocalEnv([string]$DockerPath) {
    if (Test-Path -LiteralPath $LocalEnvPath) {
        $secretLine = Get-Content -LiteralPath $LocalEnvPath -Encoding UTF8 |
            Where-Object { $_ -match '^\s*SEARXNG_SECRET\s*=' } |
            Select-Object -First 1
        if (-not $secretLine) { Fail "$LocalEnvPath 缺少 SEARXNG_SECRET" }
        $secret = (($secretLine -split '=', 2)[1]).Trim().Trim('"').Trim("'")
        if ($secret.Length -lt 32 -or $secret -match 'replace-with') {
            Fail "$LocalEnvPath 的 SEARXNG_SECRET 无效；脚本不会自动轮换已有 secret"
        }
        return
    }

    $proxyValues = Get-ExistingProxyValues $DockerPath
    $lines = @(
        "# Generated once by tools/manage-searxng.ps1. Keep this file local.",
        ("SEARXNG_SECRET={0}" -f (New-LocalSecret)),
        ("HTTP_PROXY={0}" -f (ConvertTo-DotEnvLiteral ([string]$proxyValues.HTTP_PROXY))),
        ("HTTPS_PROXY={0}" -f (ConvertTo-DotEnvLiteral ([string]$proxyValues.HTTPS_PROXY))),
        ("NO_PROXY={0}" -f (ConvertTo-DotEnvLiteral ([string]$proxyValues.NO_PROXY)))
    )
    Set-Content -LiteralPath $LocalEnvPath -Value $lines -Encoding UTF8
    Write-Host "已创建 ignored 本机配置：$LocalEnvPath（secret 不会自动轮换）" -ForegroundColor Green
}

function Backup-ActiveSettings([string]$DockerPath) {
    $container = Get-Container $DockerPath $ActiveContainerName
    if (-not $container) { return $null }
    $mount = @($container.Mounts) |
        Where-Object { $_.Destination -eq "/etc/searxng/settings.yml" -and $_.Type -eq "bind" } |
        Select-Object -First 1
    if (-not $mount -or -not (Test-Path -LiteralPath $mount.Source -PathType Leaf)) {
        Fail "现有容器的 settings.yml 不是可备份的 host bind file；为避免不可恢复迁移，已停止"
    }
    $timestamp = (Get-Date).ToUniversalTime().ToString("yyyyMMddTHHmmssZ")
    $backupPath = "{0}.bak-{1}" -f $mount.Source, $timestamp
    Copy-Item -LiteralPath $mount.Source -Destination $backupPath
    Write-Host "已备份现有 settings：$backupPath" -ForegroundColor Green
    return $backupPath
}

function Invoke-Compose(
    [string]$DockerPath,
    [string]$ProjectName,
    [string]$ContainerName,
    [int]$HostPort,
    [string]$DataVolume,
    [string[]]$ComposeArguments
) {
    $variableNames = @(
        "SEARXNG_CONTAINER_NAME",
        "SEARXNG_HOST_PORT",
        "SEARXNG_PUBLIC_URL",
        "SEARXNG_DATA_VOLUME"
    )
    $previous = @{}
    foreach ($name in $variableNames) {
        $previous[$name] = [Environment]::GetEnvironmentVariable($name, "Process")
    }
    try {
        $env:SEARXNG_CONTAINER_NAME = $ContainerName
        $env:SEARXNG_HOST_PORT = [string]$HostPort
        $env:SEARXNG_PUBLIC_URL = "http://127.0.0.1:$HostPort/"
        $env:SEARXNG_DATA_VOLUME = $DataVolume
        & $DockerPath compose --env-file $LocalEnvPath --project-name $ProjectName --file $ComposePath @ComposeArguments
        if ($LASTEXITCODE -ne 0) { Fail "docker compose 执行失败：$($ComposeArguments -join ' ')" }
    } finally {
        foreach ($name in $variableNames) {
            [Environment]::SetEnvironmentVariable($name, $previous[$name], "Process")
        }
    }
}

function Test-SearXNGHealth([int]$Port) {
    try {
        $response = Invoke-WebRequest -Uri "http://127.0.0.1:$Port/healthz" -UseBasicParsing -TimeoutSec 3
        return $response.StatusCode -eq 200 -and $response.Content.Trim() -eq "OK"
    } catch {
        return $false
    }
}

function Test-SearXNGSearch([int]$Port) {
    $queries = @(
        "Python 3.12 documentation",
        "Godot Engine documentation",
        "OpenAI API documentation"
    )
    foreach ($query in $queries) {
        try {
            $encoded = [Uri]::EscapeDataString($query)
            $uri = "http://127.0.0.1:$Port/search?q=$encoded&format=json&categories=general"
            $payload = Invoke-RestMethod -Uri $uri -TimeoutSec 10
            $valid = @($payload.results | Where-Object {
                $_.title -and ([string]$_.url -match '^https?://')
            })
            if ($valid.Count -gt 0) {
                Write-Host "有效搜索通过：端口 $Port · $($valid.Count) 条结果" -ForegroundColor Green
                return $true
            }
        } catch {
            # Try the next deterministic probe. Upstream engines may degrade independently.
        }
    }
    return $false
}

function Assert-ManagedContainer([string]$DockerPath, [string]$Name, [int]$ExpectedPort) {
    $container = Get-Container $DockerPath $Name
    if (-not $container) { Fail "找不到容器 $Name" }
    if ($container.Config.Labels.'com.study-agent.component' -ne "searxng" -or
        $container.Config.Labels.'com.study-agent.config-version' -ne "sx1") {
        Fail "容器 $Name 不是仓库管理的 SX1 SearXNG；请显式运行 tools\upgrade-searxng.bat"
    }

    $binding = @($container.HostConfig.PortBindings.'8080/tcp') | Select-Object -First 1
    if (-not $binding -or $binding.HostIp -ne "127.0.0.1" -or
        $binding.HostPort -ne [string]$ExpectedPort) {
        Fail "容器 $Name 未严格绑定 127.0.0.1:$ExpectedPort"
    }

    $expectedImageId = & $DockerPath image inspect $PinnedImage --format "{{.Id}}" 2> $null
    if ($LASTEXITCODE -ne 0 -or -not $expectedImageId) {
        Fail "本机缺少固定镜像 $PinnedImage"
    }
    if ([string]$container.Image -ne ([string]$expectedImageId).Trim()) {
        Fail "容器 $Name 未运行仓库固定 digest"
    }

    $settingsMount = @($container.Mounts) |
        Where-Object { $_.Destination -eq "/etc/searxng/settings.yml" -and $_.Type -eq "bind" } |
        Select-Object -First 1
    if (-not $settingsMount -or -not $settingsMount.RW -eq $false) {
        Fail "容器 $Name 未以只读方式挂载仓库 settings.yml"
    }
    $expectedSettings = [IO.Path]::GetFullPath($SettingsPath)
    $actualSettings = [IO.Path]::GetFullPath([string]$settingsMount.Source)
    if (-not $actualSettings.Equals($expectedSettings, [StringComparison]::OrdinalIgnoreCase)) {
        Fail "容器 $Name 使用了仓库外 settings.yml"
    }

    $secretEntry = @($container.Config.Env) |
        Where-Object { $_ -match '^SEARXNG_SECRET=.{32,}$' } |
        Select-Object -First 1
    if (-not $secretEntry -or $secretEntry -match 'replace-with|overridden-by') {
        Fail "容器 $Name 未取得有效的 ignored 本机 secret"
    }
    return $container
}

function Ensure-PinnedImage([string]$DockerPath, [switch]$Pull) {
    if ($Pull) {
        Invoke-DockerChecked $DockerPath @("pull", $PinnedImage) "固定 SearXNG 镜像拉取失败"
    }
    & $DockerPath image inspect $PinnedImage *> $null
    if ($LASTEXITCODE -ne 0) {
        Fail "本机没有固定 SearXNG 镜像；请显式运行 tools\upgrade-searxng.bat"
    }
}

function Ensure-Active([string]$DockerPath) {
    Initialize-LocalEnv $DockerPath
    Ensure-PinnedImage $DockerPath
    $container = Get-Container $DockerPath $ActiveContainerName
    if ($container) {
        Assert-ManagedContainer $DockerPath $ActiveContainerName 8080 | Out-Null
        if (-not $container.State.Running) {
            Invoke-DockerChecked $DockerPath @("start", $ActiveContainerName) "SearXNG 容器启动失败"
        }
    } else {
        if (Test-SearXNGHealth 8080) { Fail "端口 8080 已由未知 SearXNG 服务占用" }
        Invoke-Compose $DockerPath "study-agent-searxng-active" $ActiveContainerName 8080 `
            "study-agent-searxng-data" @("up", "-d", "--pull", "never")
        Assert-ManagedContainer $DockerPath $ActiveContainerName 8080 | Out-Null
    }
    if (-not (Wait-Until { Test-SearXNGHealth 8080 } 60)) {
        Fail "SearXNG 未在 60 秒内通过 /healthz"
    }
    Write-Host "SearXNG ready · fixed digest · http://127.0.0.1:8080" -ForegroundColor Green
}

function Remove-Candidate(
    [string]$DockerPath,
    [string]$ProjectName,
    [string]$ContainerName,
    [string]$DataVolume
) {
    try {
        Invoke-Compose $DockerPath $ProjectName $ContainerName 18080 $DataVolume @("down", "--volumes")
    } catch {
        Write-Warning "candidate 自动清理失败，请检查容器 $ContainerName"
    }
}

function Invoke-Upgrade([string]$DockerPath) {
    Initialize-LocalEnv $DockerPath
    Backup-ActiveSettings $DockerPath | Out-Null
    Ensure-PinnedImage $DockerPath -Pull

    $timestamp = (Get-Date).ToUniversalTime().ToString("yyyyMMddTHHmmssZ")
    $candidateProject = "study-agent-searxng-candidate-$($timestamp.ToLowerInvariant())"
    $candidateName = "study-agent-searxng-candidate-$timestamp"
    $candidateVolume = "study-agent-searxng-candidate-$timestamp-data".ToLowerInvariant()
    $activeProject = "study-agent-searxng-active-$($timestamp.ToLowerInvariant())"
    $retainedName = "study-agent-searxng-retained-$timestamp"

    Write-Host "启动 candidate：http://127.0.0.1:18080" -ForegroundColor Cyan
    try {
        Invoke-Compose $DockerPath $candidateProject $candidateName 18080 $candidateVolume `
            @("up", "-d", "--pull", "never", "--force-recreate")
        Assert-ManagedContainer $DockerPath $candidateName 18080 | Out-Null
        if (-not (Wait-Until { Test-SearXNGHealth 18080 } 60)) {
            Fail "candidate 未通过 /healthz"
        }
        if (-not (Test-SearXNGSearch 18080)) {
            Fail "candidate 没有取得一次有效搜索；保持现有 8080，不切换"
        }
    } catch {
        Remove-Candidate $DockerPath $candidateProject $candidateName $candidateVolume
        throw
    }

    $oldContainer = Get-Container $DockerPath $ActiveContainerName
    if ($oldContainer) {
        Invoke-DockerChecked $DockerPath @("stop", $ActiveContainerName) "无法停止现有 SearXNG"
        Invoke-DockerChecked $DockerPath @("rename", $ActiveContainerName, $retainedName) `
            "无法把现有 SearXNG 保留为 $retainedName"
        Write-Host "旧容器已停止保留 7 天：$retainedName" -ForegroundColor Yellow
    } elseif (Test-SearXNGHealth 8080) {
        Remove-Candidate $DockerPath $candidateProject $candidateName $candidateVolume
        Fail "端口 8080 已由未知服务占用，未切换"
    }

    try {
        Invoke-Compose $DockerPath $activeProject $ActiveContainerName 8080 `
            "study-agent-searxng-data" @("up", "-d", "--pull", "never", "--force-recreate")
        Assert-ManagedContainer $DockerPath $ActiveContainerName 8080 | Out-Null
        if (-not (Wait-Until { Test-SearXNGHealth 8080 } 60)) {
            Fail "新 active 未通过 /healthz"
        }
    } catch {
        try {
            Invoke-Compose $DockerPath $activeProject $ActiveContainerName 8080 `
                "study-agent-searxng-data" @("down")
        } catch {
            $failedActive = Get-Container $DockerPath $ActiveContainerName
            if ($failedActive) { & $DockerPath rm --force $ActiveContainerName *> $null }
        }
        if ($oldContainer) {
            Invoke-DockerChecked $DockerPath @("rename", $retainedName, $ActiveContainerName) `
                "自动回滚时无法恢复旧容器名称"
            Invoke-DockerChecked $DockerPath @("start", $ActiveContainerName) "自动回滚时旧容器启动失败"
            if (-not (Wait-Until { Test-SearXNGHealth 8080 } 60)) {
                Fail "新 active 失败，且旧容器自动回滚后健康检查也失败"
            }
            Write-Warning "新 active 失败；旧容器已自动回滚到 8080"
        }
        Remove-Candidate $DockerPath $candidateProject $candidateName $candidateVolume
        throw
    }

    Remove-Candidate $DockerPath $candidateProject $candidateName $candidateVolume
    Write-Host "升级完成：固定 digest 已在 127.0.0.1:8080 运行" -ForegroundColor Green
    if ($oldContainer) {
        Write-Host "旧容器不会自动删除；7 天后可显式运行：" -ForegroundColor Yellow
        Write-Host "  tools\manage-searxng.bat -Action RemoveRetained -RetainedName $retainedName -ConfirmRemoval"
    }
}

function Get-RetainedContainers([string]$DockerPath) {
    $names = & $DockerPath container ls --all --format "{{.Names}}"
    if ($LASTEXITCODE -ne 0) { Fail "无法列出 SearXNG 容器" }
    return @($names | Where-Object { $_ -match $RetainedPattern } | Sort-Object)
}

function Show-Retained([string]$DockerPath) {
    $names = Get-RetainedContainers $DockerPath
    if ($names.Count -eq 0) {
        Write-Host "没有 retained SearXNG 容器。"
        return
    }
    foreach ($name in $names) {
        $container = Get-Container $DockerPath $name
        Write-Host ("{0} · running={1} · created={2}" -f $name, $container.State.Running, $container.Created)
    }
}

function Remove-Retained([string]$DockerPath) {
    if (-not $ConfirmRemoval) { Fail "删除 retained 容器必须显式添加 -ConfirmRemoval" }
    if ($RetainedName -notmatch $RetainedPattern) { Fail "RetainedName 不符合受控命名规则" }
    $container = Get-Container $DockerPath $RetainedName
    if (-not $container) { Fail "找不到 retained 容器 $RetainedName" }
    if ($container.State.Running) { Fail "retained 容器仍在运行，拒绝删除" }
    $stamp = [DateTime]::ParseExact(
        $Matches[1],
        "yyyyMMddTHHmmssZ",
        [Globalization.CultureInfo]::InvariantCulture,
        [Globalization.DateTimeStyles]::AssumeUniversal
    )
    if (([DateTime]::UtcNow - $stamp.ToUniversalTime()).TotalDays -lt 7) {
        Fail "retained 容器尚未保留满 7 天，拒绝提前删除"
    }
    Invoke-DockerChecked $DockerPath @("rm", $RetainedName) "删除 retained 容器失败"
    Write-Host "已删除 retained 容器：$RetainedName；容器本身不可恢复，镜像和独立 volume 未删除。" -ForegroundColor Yellow
}

function Show-Status([string]$DockerPath) {
    $container = Get-Container $DockerPath $ActiveContainerName
    if (-not $container) {
        Write-Host "active: missing" -ForegroundColor Yellow
    } else {
        $managed = $container.Config.Labels.'com.study-agent.config-version' -eq "sx1"
        $health = Test-SearXNGHealth 8080
        Write-Host ("active: {0} · managed={1} · health={2}" -f $container.State.Status, $managed, $health)
        if ($managed) { Assert-ManagedContainer $DockerPath $ActiveContainerName 8080 | Out-Null }
        if ($ProbeSearch) {
            $search = Test-SearXNGSearch 8080
            Write-Host "search_capable: $search"
        }
    }
    Show-Retained $DockerPath
}

if (-not (Test-Path -LiteralPath $ComposePath -PathType Leaf)) { Fail "找不到 $ComposePath" }
if (-not (Test-Path -LiteralPath $SettingsPath -PathType Leaf)) { Fail "找不到 $SettingsPath" }
$Docker = Get-DockerCommand
Start-DockerIfNeeded $Docker

switch ($Action) {
    "Ensure" { Ensure-Active $Docker }
    "Upgrade" { Invoke-Upgrade $Docker }
    "Status" { Show-Status $Docker }
    "ListRetained" { Show-Retained $Docker }
    "RemoveRetained" { Remove-Retained $Docker }
}
