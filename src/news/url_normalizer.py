"""URL normalization helpers for the web/news agent pipeline.

This module is intentionally pure and network-free.  DNS-based SSRF checks
remain in ``article_fetcher`` where the real network request happens.  The
helpers here only reject unsafe schemes, credentialed URLs, localhost names,
and private IP literals before metadata is attached to news items.
"""

from __future__ import annotations

import ipaddress
from dataclasses import dataclass
from urllib.parse import parse_qsl, unquote, urlencode, urlparse, urlunparse


REDIRECT_PARAM_NAMES = {
    "url",
    "u",
    "q",
    "target",
    "target_url",
    "redirect",
    "redirect_url",
    "articleurl",
    "article_url",
    "canonicalurl",
    "canonical_url",
}

_TRACKING_PARAM_NAMES = {
    "fbclid",
    "gclid",
    "yclid",
    "mc_cid",
    "mc_eid",
    "spm",
    "from",
    "ref",
    "ref_src",
    "igshid",
    "msclkid",
}
_TRACKING_PARAM_PREFIXES = ("utm_",)
_SAFE_SCHEMES = {"http", "https"}
_LOCAL_HOSTNAMES = {"localhost", "localhost.localdomain"}


@dataclass(frozen=True)
class RedirectHop:
    """One observed step while unwrapping or following a news URL."""

    url: str
    source: str
    status: str
    is_safe: bool
    status_code: int | None = None
    location: str = ""
    reason: str = ""
    error: str = ""


@dataclass(frozen=True)
class UrlMetadata:
    """Resolved and canonicalized URL metadata attached to a news item."""

    original_url: str
    resolved_url: str
    canonical_url: str
    domain: str
    resolution_status: str
    error: str = ""
    redirect_hops: tuple[RedirectHop, ...] = ()


@dataclass(frozen=True)
class RedirectResolutionResult:
    """Rich URL resolution result with both metadata and hop history."""

    metadata: UrlMetadata
    hops: tuple[RedirectHop, ...] = ()

    @property
    def original_url(self) -> str:
        return self.metadata.original_url

    @property
    def resolved_url(self) -> str:
        return self.metadata.resolved_url

    @property
    def canonical_url(self) -> str:
        return self.metadata.canonical_url

    @property
    def resolution_status(self) -> str:
        return self.metadata.resolution_status


def _decode_repeated(value: str, rounds: int = 3) -> str:
    value = (value or "").strip()
    for _ in range(rounds):
        decoded = unquote(value)
        if decoded == value:
            break
        value = decoded
    return value.replace("\\/", "/").strip()


def _has_parser_confusing_characters(url: str) -> bool:
    if not url:
        return True
    if "\\" in url:
        return True
    return any(ord(char) <= 32 or ord(char) == 127 for char in url)


def _safe_urlparse(url: str):
    url = (url or "").strip()
    if _has_parser_confusing_characters(url):
        return None
    try:
        parsed = urlparse(url)
        _ = parsed.port  # Force validation for invalid ports like :99999.
    except Exception:
        return None
    return parsed


def _hostname_is_private_literal(hostname: str) -> bool:
    host = (hostname or "").strip().strip("[]").lower()
    if not host:
        return True
    if host in _LOCAL_HOSTNAMES or host.endswith(".localhost"):
        return True

    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False

    return bool(
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )


def is_public_http_url(url: str) -> bool:
    """Return True only for public-looking HTTP(S) URLs.

    This is a lightweight preflight check.  The real fetch path must still run
    DNS/IP validation because a hostname can resolve to a private address.
    """
    parsed = _safe_urlparse(url)
    if parsed is None:
        return False

    if parsed.scheme.lower() not in _SAFE_SCHEMES:
        return False
    if parsed.username or parsed.password:
        return False

    hostname = parsed.hostname or ""
    if not hostname:
        return False
    return not _hostname_is_private_literal(hostname)


def extract_domain(url: str) -> str:
    parsed = _safe_urlparse(url)
    if parsed is None:
        return ""
    return (parsed.hostname or "").strip().lower()


def _iter_query_pairs(url: str) -> list[tuple[str, str]]:
    parsed = _safe_urlparse(url)
    if parsed is None:
        return []
    pairs = parse_qsl(parsed.query, keep_blank_values=False)
    if parsed.fragment and "=" in parsed.fragment:
        pairs.extend(parse_qsl(parsed.fragment, keep_blank_values=False))
    return pairs


def extract_redirect_target(url: str) -> str:
    """Extract a real URL from common redirect query parameters.

    Search engines and RSS aggregators often wrap links with parameters like
    ``url=``, ``u=``, ``q=`` or ``target=``.  Only HTTP(S) public-looking targets
    are returned; otherwise an empty string is returned.
    """
    try:
        pairs = _iter_query_pairs(url)
    except Exception:
        return ""

    for key, value in pairs:
        if key.strip().lower() not in REDIRECT_PARAM_NAMES:
            continue
        candidate = _decode_repeated(value)
        if is_public_http_url(candidate):
            return candidate
    return ""


def extract_redirect_target_candidate(url: str) -> str:
    """Return the first decoded redirect target, even when it is unsafe.

    This is intended for diagnostics and hop history only.  Callers must still
    validate the returned URL before using it as a navigation target.
    """
    try:
        pairs = _iter_query_pairs(url)
    except Exception:
        return ""

    for key, value in pairs:
        if key.strip().lower() in REDIRECT_PARAM_NAMES:
            return _decode_repeated(value)
    return ""


def _is_tracking_param(name: str) -> bool:
    lowered = (name or "").strip().lower()
    if lowered in _TRACKING_PARAM_NAMES:
        return True
    return any(lowered.startswith(prefix) for prefix in _TRACKING_PARAM_PREFIXES)


def _normalized_netloc(parsed) -> str:
    hostname = (parsed.hostname or "").lower()
    if not hostname:
        return ""
    port = parsed.port
    if port and not (
        (parsed.scheme.lower() == "http" and port == 80)
        or (parsed.scheme.lower() == "https" and port == 443)
    ):
        return f"{hostname}:{port}"
    return hostname


def canonicalize_url(url: str) -> str:
    """Return a stable URL key for deduplication and caching."""
    url = (url or "").strip()
    if not is_public_http_url(url):
        return ""

    parsed = _safe_urlparse(url)
    if parsed is None:
        return ""
    scheme = parsed.scheme.lower()
    netloc = _normalized_netloc(parsed)
    path = parsed.path or "/"

    query_pairs = []
    seen_pairs: set[tuple[str, str]] = set()
    for key, value in parse_qsl(parsed.query, keep_blank_values=True):
        if _is_tracking_param(key):
            continue
        pair = (key, value)
        if pair in seen_pairs:
            continue
        seen_pairs.add(pair)
        query_pairs.append(pair)
    query_pairs.sort(key=lambda pair: (pair[0].lower(), pair[1]))
    query = urlencode(query_pairs, doseq=True)

    return urlunparse((scheme, netloc, path, "", query, ""))


def build_url_metadata(
    original_url: str,
    resolved_url: str = "",
    resolution_status: str = "",
    error: str = "",
    redirect_hops: tuple[RedirectHop, ...] = (),
) -> UrlMetadata:
    """Build URL metadata while preserving safe fallback behavior."""
    original_url = (original_url or "").strip()
    resolved_url = (resolved_url or "").strip()

    candidate = resolved_url or extract_redirect_target(original_url) or original_url
    if not candidate:
        return UrlMetadata(original_url, "", "", "", "empty", error, redirect_hops)

    if not is_public_http_url(candidate):
        return UrlMetadata(
            original_url,
            candidate,
            "",
            extract_domain(candidate),
            "unsafe",
            error,
            redirect_hops,
        )

    canonical = canonicalize_url(candidate)
    status = resolution_status.strip() if resolution_status else ""
    if not status:
        status = "resolved" if candidate and candidate != original_url else "original"

    return UrlMetadata(
        original_url=original_url,
        resolved_url=candidate,
        canonical_url=canonical,
        domain=extract_domain(candidate),
        resolution_status=status,
        error=error,
        redirect_hops=redirect_hops,
    )
