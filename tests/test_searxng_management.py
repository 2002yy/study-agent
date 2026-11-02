from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
COMPOSE = ROOT / "infra" / "searxng" / "compose.yml"
SETTINGS = ROOT / "infra" / "searxng" / "settings.yml"
MANAGER = ROOT / "tools" / "manage-searxng.ps1"


def test_compose_pins_image_and_loopback_without_public_stack():
    text = COMPOSE.read_text(encoding="utf-8")

    assert "searxng/searxng@sha256:" in text
    assert "searxng/searxng:latest" not in text
    assert '127.0.0.1:${SEARXNG_HOST_PORT:-8080}:8080' in text
    assert "SEARXNG_SECRET: ${SEARXNG_SECRET:?" in text
    assert "valkey" not in text.lower()
    assert "image-proxy" not in text.lower()


def test_settings_enable_json_but_keep_private_instance_features_off():
    text = SETTINGS.read_text(encoding="utf-8")

    assert "use_default_settings: true" in text
    assert "- json" in text
    assert "limiter: false" in text
    assert "public_instance: false" in text
    assert "image_proxy: false" in text
    assert "overridden-by-SEARXNG_SECRET" in text


def test_manager_has_candidate_backup_switch_and_guarded_retention_contract():
    text = MANAGER.read_text(encoding="utf-8")

    assert '18080' in text
    assert 'Copy-Item -LiteralPath $mount.Source -Destination $backupPath' in text
    assert 'Test-SearXNGSearch 18080' in text
    assert '@("rename", $ActiveContainerName, $retainedName)' in text
    assert 'Write-Warning "新 active 失败；旧容器已自动回滚到 8080"' in text
    assert 'TotalDays -lt 7' in text
    assert 'if (-not $ConfirmRemoval)' in text
    assert 'docker.io/searxng/searxng@sha256:' in text
    assert 'searxng/searxng:latest' not in text


def test_manager_never_rotates_existing_secret_or_opens_lan():
    text = MANAGER.read_text(encoding="utf-8")

    assert "脚本不会自动轮换已有 secret" in text
    assert '"http://127.0.0.1:$HostPort/"' in text
    assert 'ExpectedPort' in text
    assert 'HostIp -ne "127.0.0.1"' in text
    assert "0.0.0.0:$HostPort" not in text


def test_manager_reuses_foreign_container_only_when_settings_bytes_match():
    """A second checkout must be able to reuse the healthy pinned container.

    Path equality alone rejected legitimate multi-worktree launches; content
    equality keeps the "no silent config drift" guarantee while allowing reuse.
    """
    text = MANAGER.read_text(encoding="utf-8")

    assert "Get-FileHash -LiteralPath $actualSettings -Algorithm SHA256" in text
    assert "Get-FileHash -LiteralPath $expectedSettings -Algorithm SHA256" in text
    assert "复用其他检出创建的同内容 settings.yml" in text
    assert "使用了仓库外 settings.yml，且内容与本仓库不一致" in text


def test_powershell_scripts_carry_a_bom_when_they_contain_non_ascii():
    """Windows PowerShell 5.1 parses BOM-less scripts as ANSI.

    A UTF-8 script with Chinese text then mis-tokenises (a GBK trail byte can be
    read as a backslash) and the whole startup chain dies with a parse error.
    """
    for script in sorted((ROOT / "tools").glob("*.ps1")):
        raw = script.read_bytes()
        if all(byte < 128 for byte in raw):
            continue
        assert raw.startswith(b"\xef\xbb\xbf"), f"{script.name} needs a UTF-8 BOM"
