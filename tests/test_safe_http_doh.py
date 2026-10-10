"""B-Search-2B9-E: trusted DoH resolver — check and connect use the same public IPs."""
from __future__ import annotations

import json

import pytest

import src.web.safe_http as sh


@pytest.fixture(autouse=True)
def _clear_doh_cache():
    sh.reset_dns_stats()
    yield
    sh.reset_dns_stats()


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


def test_cache_hit_avoids_second_query(monkeypatch):
    import urllib.request as ur

    monkeypatch.setenv("SAFE_HTTP_DOH_URL", "https://doh.example/resolve")
    calls = {"n": 0}

    def fake(req, timeout=0):
        calls["n"] += 1
        return _mk({"Answer": []}) if "type=AAAA" in req.full_url \
            else _mk({"Answer": [{"type": 1, "data": "151.101.1.140"}]})

    monkeypatch.setattr(ur, "urlopen", fake)
    assert sh.resolve_public_ips("cache.example") == ["151.101.1.140"]
    assert sh.resolve_public_ips("cache.example") == ["151.101.1.140"]
    assert calls["n"] == 2  # A+AAAA once; second call served from cache


def test_one_type_failure_fails_closed(monkeypatch):
    import urllib.request as ur

    monkeypatch.setenv("SAFE_HTTP_DOH_URL", "https://doh.example/resolve")

    def fake(req, timeout=0):
        if "type=AAAA" in req.full_url:
            raise TimeoutError("aaaa down")
        return _mk({"Answer": [{"type": 1, "data": "151.101.1.140"}]})

    monkeypatch.setattr(ur, "urlopen", fake)
    with pytest.raises(ValueError):
        sh.resolve_public_ips("partial.example")


def test_doh_timeout_is_clamped_by_deadline(monkeypatch):
    """Each DoH request must spend at most the remaining run budget, never a fresh 5s."""
    import time
    import urllib.request as ur

    monkeypatch.setenv("SAFE_HTTP_DOH_URL", "https://doh.example/resolve")
    seen: list[float] = []

    def fake(req, timeout=0):
        seen.append(timeout)
        return _mk({"Answer": []}) if "type=AAAA" in req.full_url \
            else _mk({"Answer": [{"type": 1, "data": "151.101.1.140"}]})

    monkeypatch.setattr(ur, "urlopen", fake)
    assert sh.resolve_public_ips("clamp.example", deadline=time.monotonic() + 1.0) == ["151.101.1.140"]
    assert seen, "DoH must have been queried"
    assert all(0 < t <= 1.0 for t in seen), seen


def test_doh_exhausted_deadline_fails_closed(monkeypatch):
    """An already-exhausted budget must refuse instead of starting a new query."""
    import time
    import urllib.request as ur

    monkeypatch.setenv("SAFE_HTTP_DOH_URL", "https://doh.example/resolve")
    monkeypatch.setattr(ur, "urlopen",
                        lambda req, timeout=0: _mk({"Answer": [{"type": 1, "data": "151.101.1.140"}]}))
    with pytest.raises(ValueError, match="deadline_exhausted"):
        sh.resolve_public_ips("late.example", deadline=time.monotonic() - 0.001)


def test_stats_record_queries_hits_and_seconds(monkeypatch):
    """Run statistics must expose DoH request count, hit rate and cumulative seconds."""
    import urllib.request as ur

    monkeypatch.setenv("SAFE_HTTP_DOH_URL", "https://doh.example/resolve")
    monkeypatch.setattr(ur, "urlopen",
                        lambda req, timeout=0: _mk({"Answer": []})
                        if "type=AAAA" in req.full_url
                        else _mk({"Answer": [{"type": 1, "data": "151.101.1.140"}]}))

    sh.resolve_public_ips("stats.example")
    sh.resolve_public_ips("stats.example")  # served from cache
    stats = sh.get_dns_stats()
    assert stats["queries"] == 1
    assert stats["cache_hits"] == 1
    assert stats["hit_rate"] == 0.5
    assert stats["seconds"] >= 0.0
    assert stats["doh_failures"] == 0

    sh.reset_dns_stats()
    cleared = sh.get_dns_stats()
    assert cleared == {"queries": 0, "cache_hits": 0, "doh_failures": 0,
                       "seconds": 0.0, "hit_rate": 0.0}
