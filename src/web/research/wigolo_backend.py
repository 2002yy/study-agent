"""§71C-1 Wigolo REST ``fetch``-only shadow read backend.

Not wired into the runtime: this backend exists so a shadow bakeoff can compare
Wigolo's rendered fetch against the current HTTP reader without influencing any
production result. It implements the §71B ``ReadBackend`` surface and maps the
daemon's response into ``RawReadArtifact``.

Contract notes (frozen for this experiment):

* ``retrieval_mode`` comes from Wigolo's own ``fetch_method`` field; when the
  field is missing it is reported as ``unknown`` - never guessed from content.
* ``cache_hit`` comes from Wigolo's ``cached`` flag; when absent it stays
  ``None`` rather than being inferred from latency.
* ``rendered`` is derived only from an explicit ``fetch_method`` value; an
  unknown method leaves it ``None``.
* Only ``/v1/fetch`` is used. ``search``/``research``/``agent``/``extract`` are
  deliberately not part of this backend.
* Failures never raise into the caller's evidence path: they return an empty
  artifact whose ``external_metadata`` carries the terminal state.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from typing import Any, Mapping

from src.web.research.retrieval_backends import (
    READ_OPERATION,
    RawReadArtifact,
    ReadRequest,
)

WIGOLO_DEFAULT_BASE_URL = "http://127.0.0.1:3333"
WIGOLO_FETCH_PATH = "/v1/fetch"
WIGOLO_BACKEND_NAME = "wigolo"

_BROWSER_MARKERS = ("browser", "playwright", "chromium", "firefox", "webkit")


def _explicit_bool(value: Any) -> bool | None:
    return value if isinstance(value, bool) else None


def _rendered_from_method(method: str) -> bool | None:
    lowered = method.lower()
    if not lowered or lowered == "unknown":
        return None
    if any(marker in lowered for marker in _BROWSER_MARKERS):
        return True
    if "http" in lowered:
        return False
    return None


class WigoloShadowReadBackend:
    """``ReadBackend`` implementation talking to a local ``wigolo serve``."""

    name = WIGOLO_BACKEND_NAME

    def __init__(
        self,
        *,
        base_url: str = WIGOLO_DEFAULT_BASE_URL,
        timeout_seconds: float = 40.0,
        render_js: str = "auto",
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = float(timeout_seconds)
        self.render_js = render_js

    @property
    def operation(self) -> str:
        return READ_OPERATION

    def fetch(self, request: ReadRequest) -> RawReadArtifact:
        started = time.monotonic()
        payload = {
            "url": request.url,
            "render_js": self.render_js,
            "max_chars": int(request.max_chars),
        }
        try:
            body = json.dumps(payload).encode("utf-8")
            http_request = urllib.request.Request(
                f"{self.base_url}{WIGOLO_FETCH_PATH}",
                data=body,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(  # noqa: S310 - loopback only
                http_request, timeout=self.timeout_seconds
            ) as response:
                raw = response.read()
                status = int(getattr(response, "status", 0) or 0)
        except urllib.error.HTTPError as exc:
            return self._failure(request.url, started, state="http_error", detail=str(exc))
        except TimeoutError:
            return self._failure(request.url, started, state="timeout", detail="timeout")
        except Exception as exc:  # noqa: BLE001 - shadow must never raise upward
            return self._failure(
                request.url, started, state="transport_error", detail=type(exc).__name__
            )

        latency_ms = round((time.monotonic() - started) * 1000.0, 1)
        try:
            data = json.loads(raw.decode("utf-8", "replace"))
        except Exception:
            return self._failure(
                request.url, started, state="invalid_response", detail="json_decode"
            )
        if not isinstance(data, Mapping):
            return self._failure(
                request.url, started, state="invalid_response", detail="not_an_object"
            )

        markdown = str(data.get("markdown") or "")
        method = str(data.get("fetch_method") or "").strip()
        raw_metadata = data.get("metadata")
        metadata: Mapping[str, Any] = (
            raw_metadata if isinstance(raw_metadata, Mapping) else {}
        )
        content_type = str(
            metadata.get("content_type") or metadata.get("contentType") or ""
        )
        return RawReadArtifact(
            url=str(data.get("url") or request.url),
            content=markdown,
            content_type=content_type,
            retrieval_mode=method or "unknown",
            backend=self.name,
            latency_ms=latency_ms,
            bytes=len(markdown.encode("utf-8")),
            rendered=_rendered_from_method(method),
            cache_hit=_explicit_bool(data.get("cached")),
            external_metadata={
                "http_status": data.get("http_status"),
                "request_status": status,
                "title": str(data.get("title") or ""),
                "fetch_method_raw": method,
                "cached_raw": data.get("cached"),
                "links": len(data.get("links") or []),
                "images": len(data.get("images") or []),
            },
        )

    def _failure(
        self, url: str, started: float, *, state: str, detail: str
    ) -> RawReadArtifact:
        return RawReadArtifact(
            url=url,
            content="",
            content_type="",
            retrieval_mode="unknown",
            backend=self.name,
            latency_ms=round((time.monotonic() - started) * 1000.0, 1),
            bytes=0,
            rendered=None,
            cache_hit=None,
            external_metadata={"state": state, "detail": str(detail)[:160]},
        )


__all__ = [
    "WIGOLO_BACKEND_NAME",
    "WIGOLO_DEFAULT_BASE_URL",
    "WIGOLO_FETCH_PATH",
    "WigoloShadowReadBackend",
]
