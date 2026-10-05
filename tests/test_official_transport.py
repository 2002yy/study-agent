from __future__ import annotations

import os
import urllib.request

import pytest

from src.web.research import official_transport as transport


def setup_proxies(monkeypatch, configured, system, *, windows=True):
    monkeypatch.setattr(transport, "_WINDOWS", windows)
    monkeypatch.setattr(urllib.request, "getproxies", lambda: dict(configured))
    monkeypatch.setattr(urllib.request, "getproxies_registry", lambda: dict(system), raising=False)


def test_no_proxy_alone_cannot_erase_windows_system_proxy(monkeypatch):
    setup_proxies(monkeypatch, {"no": "localhost,127.0.0.1"}, {"https": "http://system.example:8080"})
    before = dict(os.environ)
    assert transport.official_proxy_settings() == {"https": "http://system.example:8080", "no": "localhost,127.0.0.1"}
    assert dict(os.environ) == before


@pytest.mark.parametrize("configured", [{"https": "http://explicit.example:8080", "no": "localhost"},
                                       {"http": "http://explicit.example:8080"},
                                       {"all": "socks5://explicit.example:1080"}])
def test_explicit_environment_proxy_retains_precedence(monkeypatch, configured):
    setup_proxies(monkeypatch, configured, {"https": "http://system.example:8080"})
    monkeypatch.setattr(urllib.request, "getproxies_registry", lambda: pytest.fail("explicit configuration is authoritative"))
    assert transport.official_proxy_settings() == configured


def test_non_windows_configuration_is_not_changed(monkeypatch):
    setup_proxies(monkeypatch, {"no": "localhost"}, {"https": "http://system.example:8080"}, windows=False)
    assert transport.official_proxy_settings() == {"no": "localhost"}


def test_no_proxy_wildcard_is_preserved_and_still_bypasses(monkeypatch):
    setup_proxies(monkeypatch, {"no": "*"}, {"https": "http://system.example:8080"})
    settings = transport.official_proxy_settings()
    assert settings["no"] == "*"
    assert urllib.request.proxy_bypass_environment("platform.claude.com", settings)


def test_local_bypass_remains_local(monkeypatch):
    setup_proxies(monkeypatch, {"no": "localhost,127.0.0.1"}, {"https": "http://system.example:8080"})
    settings = transport.official_proxy_settings()
    assert urllib.request.proxy_bypass_environment("localhost", settings)
    assert urllib.request.proxy_bypass_environment("127.0.0.1", settings)
    assert not urllib.request.proxy_bypass_environment("platform.claude.com", settings)


def test_missing_or_unreadable_registry_keeps_existing_configuration(monkeypatch):
    setup_proxies(monkeypatch, {"no": "localhost"}, {})
    monkeypatch.delattr(urllib.request, "getproxies_registry", raising=False)
    assert transport.official_proxy_settings() == {"no": "localhost"}
    def unavailable():
        raise OSError("registry unavailable")
    monkeypatch.setattr(urllib.request, "getproxies_registry", unavailable, raising=False)
    assert transport.official_proxy_settings() == {"no": "localhost"}
