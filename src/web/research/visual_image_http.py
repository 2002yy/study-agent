"""Bounded, SSRF-aware HTTP fetch for one declared web image.

Frozen context: ``docs/PROJECT_STATUS.md`` §144.16.

Safety contract (all enforced here, all locked by tests):

* ``http`` / ``https`` only, and the **initial URL and every redirect hop** are
  re-validated with the engine's own public-URL preflight;
* redirects are followed manually with a hard hop limit (the automatic handler is
  removed), so a hop can never bypass the public-URL check;
* connect/read timeout plus an overall wall-clock budget;
* ``Content-Type`` must be an allowed ``image/*``;
* ``Content-Length`` is only an early reject: the body is still streamed with a
  hard ``max_bytes`` cap, so a lying or absent length cannot exceed it;
* a non-identity ``Content-Encoding`` is refused (no decompression bombs);
* no cookies, no credentials, no inherited auth headers -- one fixed User-Agent;
* failures are normalized to bounded :class:`ImageFetchError` reasons.

It returns ``(bytes, content_type)``; the caller owns atomic persistence.
"""

from __future__ import annotations

import time
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin
from urllib.request import HTTPRedirectHandler, Request, build_opener

from src.news.url_normalizer import is_public_http_url
from src.web.research.visual_image_fetch import (
    ALLOWED_IMAGE_TYPES,
    MAX_IMAGE_BYTES,
    REASON_EMPTY,
    REASON_FETCH_FAILED,
    REASON_TOO_LARGE,
    REASON_UNSUPPORTED_TYPE,
    ImageFetchError,
)

DEFAULT_TIMEOUT_SECONDS = 6.0
DEFAULT_OVERALL_TIMEOUT_SECONDS = 15.0
MAX_REDIRECTS = 3
CHUNK_BYTES = 64 * 1024
USER_AGENT = "StudyAgent/1.0 (+research-visual-reader)"

REASON_NOT_PUBLIC = "image_url_not_public"
REASON_REDIRECT_NOT_PUBLIC = "image_redirect_not_public"
REASON_TOO_MANY_REDIRECTS = "image_redirect_limit"
REASON_ENCODING_UNSUPPORTED = "image_content_encoding_unsupported"
REASON_HTTP_STATUS = "image_http_status"
REASON_TIMEOUT = "image_timeout"


class _NoRedirect(HTTPRedirectHandler):
    """Make 3xx surface as an HTTPError so each hop can be re-validated."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[override]
        return None


def _default_opener() -> Callable[..., Any]:
    return build_opener(_NoRedirect).open


def _header(headers: Any, name: str) -> str:
    if headers is None:
        return ""
    try:
        return str(headers.get(name) or "")
    except Exception:  # noqa: BLE001 - a malformed header block is "absent"
        return ""


def _int_header(headers: Any, name: str) -> int | None:
    raw = _header(headers, name).strip()
    if not raw:
        return None
    try:
        value = int(raw)
    except ValueError:
        return None
    return value if value >= 0 else None


def fetch_image(
    url: str,
    *,
    opener: Callable[..., Any] | None = None,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    overall_timeout: float = DEFAULT_OVERALL_TIMEOUT_SECONDS,
    max_bytes: int = MAX_IMAGE_BYTES,
    max_redirects: int = MAX_REDIRECTS,
    allowed_types: frozenset[str] = ALLOWED_IMAGE_TYPES,
) -> tuple[bytes, str]:
    """Fetch one declared image, or fail closed with a bounded reason."""

    if not is_public_http_url(url):
        raise ImageFetchError(REASON_NOT_PUBLIC)

    open_url = opener or _default_opener()
    started = time.monotonic()
    current = url

    for hop in range(max_redirects + 1):
        if time.monotonic() - started > overall_timeout:
            raise ImageFetchError(REASON_TIMEOUT)
        request = Request(current, headers={"User-Agent": USER_AGENT})
        try:
            response = open_url(request, timeout=timeout)
        except HTTPError as exc:
            location = _header(getattr(exc, "headers", None), "Location")
            status = int(getattr(exc, "code", 0) or 0)
            if 300 <= status < 400 and location:
                target = urljoin(current, location)
                if not is_public_http_url(target):
                    raise ImageFetchError(REASON_REDIRECT_NOT_PUBLIC) from exc
                if hop >= max_redirects:
                    raise ImageFetchError(REASON_TOO_MANY_REDIRECTS) from exc
                current = target
                continue
            raise ImageFetchError(REASON_HTTP_STATUS) from exc
        except (TimeoutError, URLError) as exc:
            if isinstance(exc, URLError) and not isinstance(exc.reason, TimeoutError):
                raise ImageFetchError(REASON_FETCH_FAILED) from exc
            raise ImageFetchError(REASON_TIMEOUT) from exc
        except OSError as exc:
            raise ImageFetchError(REASON_FETCH_FAILED) from exc

        with response:
            status = int(getattr(response, "status", 200) or 200)
            if status != 200:
                raise ImageFetchError(REASON_HTTP_STATUS)
            headers = getattr(response, "headers", None)
            encoding = _header(headers, "Content-Encoding").strip().lower()
            if encoding and encoding != "identity":
                raise ImageFetchError(REASON_ENCODING_UNSUPPORTED)
            content_type = _header(headers, "Content-Type").split(";", 1)[0].strip().lower()
            if content_type not in allowed_types:
                raise ImageFetchError(REASON_UNSUPPORTED_TYPE)
            declared = _int_header(headers, "Content-Length")
            if declared is not None and declared > max_bytes:
                raise ImageFetchError(REASON_TOO_LARGE)

            chunks: list[bytes] = []
            total = 0
            while True:
                if time.monotonic() - started > overall_timeout:
                    raise ImageFetchError(REASON_TIMEOUT)
                chunk = response.read(CHUNK_BYTES)
                if not chunk:
                    break
                total += len(chunk)
                if total > max_bytes:
                    raise ImageFetchError(REASON_TOO_LARGE)
                chunks.append(chunk)
            body = b"".join(chunks)

        if not body:
            raise ImageFetchError(REASON_EMPTY)
        return body, content_type

    raise ImageFetchError(REASON_TOO_MANY_REDIRECTS)


def default_image_fetcher() -> Callable[[str], tuple[bytes, str]]:
    """The production fetcher bound to the read-site visual seam."""

    return fetch_image


__all__ = [
    "CHUNK_BYTES",
    "DEFAULT_OVERALL_TIMEOUT_SECONDS",
    "DEFAULT_TIMEOUT_SECONDS",
    "MAX_REDIRECTS",
    "REASON_ENCODING_UNSUPPORTED",
    "REASON_HTTP_STATUS",
    "REASON_NOT_PUBLIC",
    "REASON_REDIRECT_NOT_PUBLIC",
    "REASON_TIMEOUT",
    "REASON_TOO_MANY_REDIRECTS",
    "USER_AGENT",
    "default_image_fetcher",
    "fetch_image",
]
