"""Security policies for configured service endpoints."""

from __future__ import annotations

import ipaddress
from urllib.parse import urlparse


def validate_service_endpoint(
    url: str,
    *,
    allow_loopback: bool = False,
    allow_private_network: bool = False,
) -> bool:
    """Validate an administrator-configured HTTP service endpoint.

    This policy is intentionally separate from public target URL validation.
    """
    try:
        parsed = urlparse((url or "").strip())
        _ = parsed.port
    except Exception:
        return False
    if parsed.scheme.lower() not in {"http", "https"}:
        return False
    if parsed.username or parsed.password:
        return False
    host = (parsed.hostname or "").strip().lower()
    if not host:
        return False
    if host == "localhost" or host.endswith(".localhost"):
        return allow_loopback
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return True
    if ip.is_loopback:
        return allow_loopback
    if ip.is_private or ip.is_link_local:
        return allow_private_network
    return not (
        ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )
