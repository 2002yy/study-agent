"""B-Search-2B9-E: trusted DoH resolver — check and connect use the same public IPs."""
from __future__ import annotations

import json

import pytest

import src.web.safe_http as sh


def _mk(payload: dict):
    class _R:
        def __init__(self):
            self._b = json.dumps(payload).encode("utf-8")

        def read(self):
            return self._b

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    return _R()


def test_doh_returns_real_public_ips(monkeypatch):
    import urllib.request as ur

    monkeypatch.setenv("SAFE_HTTP_DOH_URL", "https://doh.example/resolve")
    monkeypatch.setattr(ur, "urlopen",
                        lambda req, timeout=0: _mk({"Answer": []})
                        if "type=AAAA" in req.full_url
                        else _mk({"Answer": [{"type": 1, "data": "151.101.1.140"}]}))
    assert sh.resolve_public_ips("www.python.org") == ["151.101.1.140"]
    assert sh.host_resolves_public("www.python.org") is True


def test_doh_fake_ip_is_rejected_not_whitelisted(monkeypatch):
    import urllib.request as ur

    monkeypatch.setenv("SAFE_HTTP_DOH_URL", "https://doh.example/resolve")
    monkeypatch.setattr(ur, "urlopen",
                        lambda req, timeout=0: _mk({"Answer": [{"type": 1, "data": "198.18.0.71"}]}))
    with pytest.raises(ValueError):
        sh.resolve_public_ips("wiki.factorio.com")
    assert sh.host_resolves_public("wiki.factorio.com") is False


def test_doh_failure_fails_closed(monkeypatch):
    import urllib.request as ur

    monkeypatch.setenv("SAFE_HTTP_DOH_URL", "https://doh.example/resolve")

    def boom(req, timeout=0):
        raise TimeoutError("doh down")

    monkeypatch.setattr(ur, "urlopen", boom)
    with pytest.raises(ValueError):
        sh.resolve_public_ips("www.python.org")


def test_mixed_public_and_fake_is_rejected(monkeypatch):
    import urllib.request as ur

    monkeypatch.setenv("SAFE_HTTP_DOH_URL", "https://doh.example/resolve")
    monkeypatch.setattr(ur, "urlopen",
                        lambda req, timeout=0: _mk({"Answer": []})
                        if "type=AAAA" in req.full_url
                        else _mk({"Answer": [{"type": 1, "data": "151.101.1.140"},
                                             {"type": 1, "data": "198.18.0.71"}]}))
    with pytest.raises(ValueError):
        sh.resolve_public_ips("mixed.example")
