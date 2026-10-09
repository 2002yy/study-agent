"""Shared SSRF-constrained HTTP transport (Reader-Safety-1).

One implementation reused by the feed/agent path and available to the article
reader: validate scheme + resolved IP of EVERY hop BEFORE connecting, and connect
to the validated IP (no re-resolution), keeping TLS SNI/cert for the real host.
"""

from __future__ import annotations

import http.client
import ipaddress
import socket
import ssl
from typing import NoReturn
from urllib.parse import urljoin, urlsplit

from src.web.tool_evidence import _public_url

MAX_BYTES = 300_000
MAX_HOPS = 4

# Security refusals (SSRF-class) must be distinguishable from ordinary network
# failures so a caller never routes a refusal into a weaker fallback.
_SECURITY_REASONS = frozenset({
    "unsafe_scheme", "unsafe_port", "unsafe_target", "dns_failed", "dns_empty",
    "dns_invalid", "redirect_without_location", "too_many_redirects",
    "deadline_exhausted", "response_too_large",
})


class SafeFetchRefusal(ValueError):
    """A security refusal: the target was not (and must not be) contacted."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class SafeFetchError(ValueError):
    """An ordinary network/status/limit failure (not a security refusal)."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def _raise_safe(reason: str) -> NoReturn:
    raise SafeFetchRefusal(reason) if reason in _SECURITY_REASONS else SafeFetchError(reason)


_DOH_CACHE: dict[tuple[str, str], tuple[float, list[str]]] = {}
_DOH_CACHE_MAX = 128
_DNS_STATS = {"queries": 0, "cache_hits": 0, "doh_failures": 0, "seconds": 0.0}


def get_dns_stats() -> dict:
    """Diagnostics: DoH request count, cache hits, hit rate and cumulative seconds."""
    lookups = _DNS_STATS["queries"] + _DNS_STATS["cache_hits"]
    stats = dict(_DNS_STATS)
    stats["seconds"] = round(_DNS_STATS["seconds"], 3)
    stats["hit_rate"] = round(_DNS_STATS["cache_hits"] / lookups, 3) if lookups else 0.0
    return stats


def reset_dns_stats() -> None:
    """Start a research run from a clean slate: drop cached answers and counters.

    The cache exists to avoid re-querying a host inside one bounded run; counters
    are per-run so evidence is not polluted by earlier runs.
    """
    _DOH_CACHE.clear()
    for key in _DNS_STATS:
        _DNS_STATS[key] = 0.0 if key == "seconds" else 0


def _doh_lookup(host: str, doh: str, *, deadline: float | None = None) -> list[str]:
    """Query A and AAAA via DoH. A failed request for EITHER type fails closed — one
    type's success must not mask the other's failure. Returns raw record strings.

    ``deadline`` is the caller's absolute monotonic limit: each request is clamped to
    the remaining budget, and an exhausted budget fails closed instead of granting a
    fresh per-request timeout. DoH wall time is accumulated in the run statistics.
    """
    import json as _json
    import time as _time
    from urllib.request import Request, urlopen

    started = _time.monotonic()
    try:
        answers: list[str] = []
        for rtype in ("A", "AAAA"):
            req_timeout = 5.0
            if deadline is not None:
                req_timeout = min(req_timeout, deadline - _time.monotonic())
                if req_timeout <= 0:
                    raise ValueError("deadline_exhausted")
            try:
                req = Request(f"{doh}?name={host}&type={rtype}",
                              headers={"Accept": "application/dns-json"})
                with urlopen(req, timeout=req_timeout) as resp:  # noqa: S310 (operator-configured endpoint)
                    data = _json.loads(resp.read().decode("utf-8", "replace"))
            except Exception as exc:  # noqa: BLE001
                _DNS_STATS["doh_failures"] += 1
                raise ValueError("dns_failed") from exc
            for answer in (data.get("Answer") or []):
                if answer.get("type") in (1, 28) and answer.get("data"):
                    answers.append(str(answer["data"]))
        return answers
    finally:
        _DNS_STATS["seconds"] += _time.monotonic() - started


def host_resolves_public(host: str, *, deadline: float | None = None) -> bool:
    """True only if every resolved address is a global (public) IP."""
    if not host:
        return False
    try:
        resolve_public_ips(host, deadline=deadline)
    except Exception:  # noqa: BLE001
        return False
    return True


def resolve_public_ips(host: str, *, deadline: float | None = None) -> list[str]:
    """Resolve once and require every address to be a global IP; return the IPs.

    With ``SAFE_HTTP_DOH_URL`` set, resolution goes through DoH (real public IPs) and
    **fails closed** on DoH failure or any non-global answer. Results are cached per
    (DoH endpoint, host) with a short TTL — ONLY fully-validated public IPs are cached;
    failures and unsafe answers are never cached. The returned IPs are the ones pinned
    by ``http_get_raw``/``safe_fetch`` — check and connect never diverge.
    """
    import os as _os
    import time as _time

    doh = (_os.getenv("SAFE_HTTP_DOH_URL") or "").strip()
    if doh:
        key = (doh, host)
        now = _time.monotonic()
        cached = _DOH_CACHE.get(key)
        if cached and cached[0] > now:
            _DNS_STATS["cache_hits"] += 1
            return list(cached[1])
        _DNS_STATS["queries"] += 1
        raw_ips = _doh_lookup(host, doh, deadline=deadline)
        if not raw_ips:
            raise ValueError("dns_failed")
        ips: list[str] = []
        for raw in raw_ips:
            try:
                ip = ipaddress.ip_address(raw)
            except ValueError as exc:
                raise ValueError("dns_invalid") from exc
            if not ip.is_global:
                raise ValueError("unsafe_target")
            ips.append(str(ip))
        if len(_DOH_CACHE) >= _DOH_CACHE_MAX:
            _DOH_CACHE.clear()
        ttl = float(_os.getenv("SAFE_HTTP_DOH_CACHE_TTL", "120") or 120)
        _DOH_CACHE[key] = (now + ttl, ips)
        return ips

    try:
        infos = socket.getaddrinfo(host, None)
    except Exception as exc:  # noqa: BLE001
        raise ValueError("dns_failed") from exc
    if not infos:
        raise ValueError("dns_empty")
    ips = []
    for info in infos:
        try:
            ip = ipaddress.ip_address(info[4][0])
        except ValueError as exc:
            raise ValueError("dns_invalid") from exc
        if not ip.is_global:
            raise ValueError("unsafe_target")
        ips.append(str(ip))
    return ips


def http_get_raw(url: str, host: str, ip: str, *, timeout: float,
                 max_bytes: int = MAX_BYTES) -> tuple[int, dict[str, str], bytes, bool]:
    """GET ``url`` connecting to the validated ``ip`` (no re-resolution); return
    (status, lowercased headers, raw bytes, truncated). The real host is kept for
    the Host header and TLS SNI/certificate checks."""
    parts = urlsplit(url)
    port = parts.port or (443 if parts.scheme == "https" else 80)
    target = parts.path or "/"
    if parts.query:
        target += "?" + parts.query
    if parts.scheme == "https":
        context = ssl.create_default_context()
        sock = socket.create_connection((ip, port), timeout=timeout)
        conn: http.client.HTTPConnection = http.client.HTTPSConnection(host, port, timeout=timeout)
        conn.sock = context.wrap_socket(sock, server_hostname=host)
    else:
        conn = http.client.HTTPConnection(ip, port, timeout=timeout)
    try:
        conn.request("GET", target, headers={"Host": host, "User-Agent": "StudyAgent/feed"})
        response = conn.getresponse()
        raw = response.read(max_bytes + 1)
        truncated = len(raw) > max_bytes
        if truncated:
            raw = raw[:max_bytes]
        return response.status, {k.lower(): v for k, v in response.getheaders()}, raw, truncated
    finally:
        conn.close()


def http_get_pinned(url: str, host: str, ip: str, *, timeout: float,
                    max_bytes: int = MAX_BYTES) -> tuple[int, dict[str, str], str]:
    """String convenience wrapper over :func:`http_get_raw` (unchanged Feed path)."""
    status, headers, raw, _ = http_get_raw(url, host, ip, timeout=timeout, max_bytes=max_bytes)
    return status, headers, raw.decode("utf-8", "replace")


def safe_fetch(url: str, *, timeout: float, max_hops: int = MAX_HOPS,
               deadline: float | None = None, max_bytes: int = MAX_BYTES) -> str:
    """Fetch a URL with per-hop validation and IP pinning; a private hop is never
    contacted. ``deadline`` is one absolute monotonic time shared by all hops."""
    import time

    current = url
    for _ in range(max_hops):
        hop_timeout = timeout
        if deadline is not None:
            hop_timeout = min(timeout, deadline - time.monotonic())
            if hop_timeout <= 0:
                raise ValueError("deadline_exhausted")
        parts = urlsplit(current)
        if parts.scheme not in {"http", "https"} or not parts.hostname:
            raise ValueError("unsafe_scheme")
        if parts.port not in (None, 80, 443):
            raise ValueError("unsafe_port")
        if not _public_url(current):
            raise ValueError("unsafe_target")
        ips = resolve_public_ips(parts.hostname, deadline=deadline)
        status, headers, body = http_get_pinned(
            current, parts.hostname, ips[0], timeout=hop_timeout, max_bytes=max_bytes
        )
        if status in {301, 302, 303, 307, 308}:
            location = headers.get("location")
            if not location:
                raise ValueError("redirect_without_location")
            current = urljoin(current, location)
            continue
        if status >= 400:
            raise ValueError(f"http_{status}")
        return body
    raise ValueError("too_many_redirects")


def safe_fetch_result(url: str, *, timeout: float, max_hops: int = MAX_HOPS,
                      deadline: float | None = None, max_bytes: int = MAX_BYTES) -> dict:
    """Structured article-reader transport over the same safety rules.

    Returns status/headers/raw bytes/text/requested+final URL/redirect chain/
    content type+encoding/truncated. Raises ``ValueError`` (fail-closed) on any
    security refusal, network error, bad status or resource limit — the caller must
    NOT route a refusal into a weaker fallback.
    """
    import time

    current = url
    chain: list[str] = []
    for _ in range(max_hops):
        hop_timeout = timeout
        if deadline is not None:
            hop_timeout = min(timeout, deadline - time.monotonic())
            if hop_timeout <= 0:
                _raise_safe("deadline_exhausted")
        parts = urlsplit(current)
        if parts.scheme not in {"http", "https"} or not parts.hostname:
            _raise_safe("unsafe_scheme")
        if parts.port not in (None, 80, 443):
            _raise_safe("unsafe_port")
        if not _public_url(current):
            _raise_safe("unsafe_target")
        try:
            ips = resolve_public_ips(parts.hostname, deadline=deadline)
        except SafeFetchRefusal:
            raise
        except Exception as exc:  # noqa: BLE001
            _raise_safe(str(exc) or "dns_failed")
        try:
            status, headers, raw, truncated = http_get_raw(
                current, parts.hostname, ips[0], timeout=hop_timeout, max_bytes=max_bytes
            )
        except (OSError, http.client.HTTPException) as exc:
            raise SafeFetchError(f"network:{type(exc).__name__}") from exc
        if status in {301, 302, 303, 307, 308}:
            location = headers.get("location")
            if not location:
                _raise_safe("redirect_without_location")
            chain.append(current)
            current = urljoin(current, location)
            continue
        if status >= 400:
            _raise_safe(f"http_{status}")
        if truncated:
            # A truncated body must NOT be reported as a clean success.
            _raise_safe("response_too_large")
        return {
            "requested_url": url,
            "redirect_chain": chain,
            "final_url": current,
            "status": status,
            "headers": headers,
            "content_type": headers.get("content-type", ""),
            "content_encoding": headers.get("content-encoding", ""),
            "raw": raw,
            "text": raw.decode("utf-8", "replace"),
            "truncated": False,
        }
    _raise_safe("too_many_redirects")
