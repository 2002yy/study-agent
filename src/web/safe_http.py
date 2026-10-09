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
from urllib.parse import urljoin, urlsplit

from src.web.tool_evidence import _public_url

MAX_BYTES = 300_000
MAX_HOPS = 4


def host_resolves_public(host: str) -> bool:
    """True only if every resolved address is a global (public) IP."""
    if not host:
        return False
    try:
        infos = socket.getaddrinfo(host, None)
    except Exception:  # noqa: BLE001
        return False
    if not infos:
        return False
    for info in infos:
        try:
            ip = ipaddress.ip_address(info[4][0])
        except ValueError:
            return False
        if not ip.is_global:
            return False
    return True


def resolve_public_ips(host: str) -> list[str]:
    """Resolve once and require every address to be a global IP; return the IPs."""
    try:
        infos = socket.getaddrinfo(host, None)
    except Exception as exc:  # noqa: BLE001
        raise ValueError("dns_failed") from exc
    if not infos:
        raise ValueError("dns_empty")
    ips: list[str] = []
    for info in infos:
        try:
            ip = ipaddress.ip_address(info[4][0])
        except ValueError as exc:
            raise ValueError("dns_invalid") from exc
        if not ip.is_global:
            raise ValueError("unsafe_target")
        ips.append(str(ip))
    return ips


def http_get_pinned(url: str, host: str, ip: str, *, timeout: float,
                    max_bytes: int = MAX_BYTES) -> tuple[int, dict[str, str], str]:
    """GET ``url`` connecting to the already-validated ``ip`` (no re-resolution),
    keeping the real host for the Host header and TLS SNI/certificate checks."""
    parts = urlsplit(url)
    port = parts.port or (443 if parts.scheme == "https" else 80)
    target = parts.path or "/"
    if parts.query:
        target += "?" + parts.query
    if parts.scheme == "https":
        context = ssl.create_default_context()
        raw = socket.create_connection((ip, port), timeout=timeout)
        conn: http.client.HTTPConnection = http.client.HTTPSConnection(host, port, timeout=timeout)
        conn.sock = context.wrap_socket(raw, server_hostname=host)
    else:
        conn = http.client.HTTPConnection(ip, port, timeout=timeout)
    try:
        conn.request("GET", target, headers={"Host": host, "User-Agent": "StudyAgent/feed"})
        response = conn.getresponse()
        body = response.read(max_bytes).decode("utf-8", "replace")
        return response.status, {k.lower(): v for k, v in response.getheaders()}, body
    finally:
        conn.close()


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
        ips = resolve_public_ips(parts.hostname)
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
