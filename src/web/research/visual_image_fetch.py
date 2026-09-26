"""Bounded fetch-to-file for a discovered web image.

Frozen context: ``docs/PROJECT_STATUS.md`` §144.13 boundary 2 (precondition).

The existing vision seam only accepts a **local file path** (image bytes leave the
machine only through it), so a web image must be materialized first. This module
does exactly that, fail-closed:

* only declared image content types are accepted;
* an empty or oversized body is rejected;
* any fetcher failure is normalized to a bounded reason (never propagated raw);
* the file name is content-addressed, so a re-fetch cannot collide.

The fetcher is injected (like the provider/read seams elsewhere), so this module
performs no network I/O of its own.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping

MAX_IMAGE_BYTES = 8 * 1024 * 1024

ALLOWED_IMAGE_TYPES: frozenset[str] = frozenset(
    {
        "image/png",
        "image/jpeg",
        "image/jpg",
        "image/gif",
        "image/webp",
        "image/bmp",
        "image/tiff",
    }
)

_EXTENSION_BY_TYPE: Mapping[str, str] = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/gif": ".gif",
    "image/webp": ".webp",
    "image/bmp": ".bmp",
    "image/tiff": ".tiff",
}

REASON_NOT_A_FETCHER = "image_fetcher_unavailable"
REASON_FETCH_FAILED = "image_fetch_failed"
REASON_UNSUPPORTED_TYPE = "image_content_type_unsupported"
REASON_EMPTY = "image_body_empty"
REASON_TOO_LARGE = "image_body_too_large"
REASON_WRITE_FAILED = "image_write_failed"


class ImageFetchError(RuntimeError):
    """A discovered image could not be materialized (fail-closed)."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class FetchedImage:
    path: Path
    content_type: str
    byte_count: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": str(self.path),
            "content_type": self.content_type,
            "byte_count": self.byte_count,
        }


def _normalize_content_type(raw: Any) -> str:
    return str(raw or "").split(";", 1)[0].strip().lower()


def materialize_image(
    url: str,
    *,
    fetcher: Callable[[str], Any] | None,
    destination_dir: Path,
    max_bytes: int = MAX_IMAGE_BYTES,
    allowed_types: frozenset[str] = ALLOWED_IMAGE_TYPES,
) -> FetchedImage:
    """Fetch one image and write it to ``destination_dir`` as a local file."""

    if fetcher is None:
        raise ImageFetchError(REASON_NOT_A_FETCHER)

    try:
        raw = fetcher(url)
    except Exception as exc:  # noqa: BLE001 - normalized into a bounded reason
        raise ImageFetchError(REASON_FETCH_FAILED) from exc

    body, content_type = _unpack(raw)
    if content_type not in allowed_types:
        raise ImageFetchError(REASON_UNSUPPORTED_TYPE)
    if not body:
        raise ImageFetchError(REASON_EMPTY)
    if len(body) > max_bytes:
        raise ImageFetchError(REASON_TOO_LARGE)

    digest = hashlib.sha1(body).hexdigest()[:20]
    target = destination_dir / f"{digest}{_EXTENSION_BY_TYPE.get(content_type, '.bin')}"
    try:
        destination_dir.mkdir(parents=True, exist_ok=True)
        target.write_bytes(body)
    except OSError as exc:
        raise ImageFetchError(REASON_WRITE_FAILED) from exc

    return FetchedImage(path=target, content_type=content_type, byte_count=len(body))


def _unpack(raw: Any) -> tuple[bytes, str]:
    """Accept ``(bytes, content_type)`` or ``{"body": ..., "content_type": ...}``."""

    if isinstance(raw, tuple) and len(raw) == 2:
        body, content_type = raw
    elif isinstance(raw, Mapping):
        body = raw.get("body")
        content_type = raw.get("content_type")
    else:
        raise ImageFetchError(REASON_FETCH_FAILED)
    if not isinstance(body, (bytes, bytearray)):
        raise ImageFetchError(REASON_FETCH_FAILED)
    return bytes(body), _normalize_content_type(content_type)


__all__ = [
    "ALLOWED_IMAGE_TYPES",
    "FetchedImage",
    "ImageFetchError",
    "MAX_IMAGE_BYTES",
    "REASON_EMPTY",
    "REASON_FETCH_FAILED",
    "REASON_NOT_A_FETCHER",
    "REASON_TOO_LARGE",
    "REASON_UNSUPPORTED_TYPE",
    "REASON_WRITE_FAILED",
    "materialize_image",
]
