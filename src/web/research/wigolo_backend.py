"""§71C Wigolo REST read backend: shadow (71C-2) and production HTTP tier (71C-3a).

Two tiers, one daemon:

* **http** (production escalation, §71C-3a): ``render_js="never"`` so no browser
  is ever involved. Measured ~1s and it rescued the flagship thin-body cases.
* **browser** (experimental only, §71C-3b): ``render_js="always"``, refused
  unless the experiment flag explicitly enables it. The browser tier costs tens
  of seconds and has only one cost sample so far, so it must not enter the
  default path.

Contract notes (frozen for this experiment):

* ``retrieval_mode`` comes from Wigolo's own ``fetch_method`` field; when the
  field is missing it is ``unknown`` - never guessed from content.
* ``cache_hit`` comes from Wigolo's ``cached`` flag; when absent it stays
  ``None`` rather than being inferred from latency.
* ``rendered`` is derived only from an explicit ``fetch_method``.
* **``max_chars`` is a contract parameter, not a tuning knob**:
  ``WIGOLO_FETCH_MAX_CHARS`` is fixed because the daemon's cache stores the
  truncated text of the ``max_chars`` it was first called with. Changing it is a
  cache-affecting config migration. The request value and the returned length are
  recorded; truncation is only reported when the daemon says so.
* **Preflight is hard**: health must be OK and ``WIGOLO_RERANKER`` must be
  ``off`` (an unset reranker costs ~33s per request and poisons the daemon's
  domain->browser learning). Anything else means the backend is unavailable and
  the caller must continue with the current reader - never "try and see".
* Failures never raise into the caller: they return an empty artifact whose
  ``external_metadata`` carries the terminal state, and they trip a process-level
  circuit breaker so a broken daemon costs at most one request.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from typing import Any, Mapping

from src.web.research.read_escalation import browser_tier_allowed
from src.web.research.retrieval_backends import RawReadArtifact, ReadRequest

WIGOLO_DEFAULT_BASE_URL = "http://127.0.0.1:3333"
WIGOLO_FETCH_PATH = "/v1/fetch"
WIGOLO_HEALTH_PATH = "/health"
WIGOLO_BACKEND_NAME = "wigolo"

# Cache-affecting retrieval contract value (§78.2-1): 20k leaves ~2x headroom
# over the largest rescued page (10.9k) without flooding the extractor.
WIGOLO_FETCH_MAX_CHARS = 20_000

TIER_HTTP = "http"
TIER_BROWSER = "browser"
_HTTP_RENDER_MODE = "never"
_BROWSER_RENDER_MODE = "always"

RERANKER_ENV = "WIGOLO_RERANKER"
PREFLIGHT_READY = "ready"
PREFLIGHT_UNAVAILABLE = "unavailable"
PREFLIGHT_MISCONFIGURED = "misconfigured"

_BROWSER_MARKERS = ("browser", "playwright", "chromium", "firefox", "webkit")


def _explicit_bool(value: Any) -> bool | None:
    return value if isinstance(value, bool) else None


def _rendered_from_method(method: str) -> bool | None:
    lowered = method.lower()
    if not lowered or lowered == "unknown":
        return None
    if any(marker in lowered for marker in _BROWSER_MARKERS):
        return True
    if "http" in lowered or "cache" in lowered:
        return False
    return None


class WigoloShadowReadBackend:
    """``ReadBackend`` implementation talking to a local ``wigolo serve``."""

    name = WIGOLO_BACKEND_NAME

    def __init__(
        self,
        *,
        base_url: str = WIGOLO_DEFAULT_BASE_URL,
        timeout_seconds: float = 8.0,
        tier: str = TIER_HTTP,
        max_chars: int = WIGOLO_FETCH_MAX_CHARS,
        render_js: str | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = float(timeout_seconds)
        self.max_chars = int(max_chars)
        self.tier = TIER_BROWSER if str(tier).lower() == TIER_BROWSER else TIER_HTTP
        if render_js is not None:
            self.render_js = str(render_js)
        elif self.tier == TIER_BROWSER:
            self.render_js = _BROWSER_RENDER_MODE
        else:
            self.render_js = _HTTP_RENDER_MODE
        self._circuit_open = False
        self._preflight_status = ""

    # ------------------------------------------------------------------ setup
    def preflight(self) -> str:
        """Return ``ready`` / ``unavailable`` / ``misconfigured`` (cached).

        Hard gate: no request is attempted unless this says ``ready``.
        """

        if self._preflight_status:
            return self._preflight_status
        if (os.getenv(RERANKER_ENV) or "").strip().lower() != "off":
            # An unset reranker costs ~33s/request and poisons domain routing.
            self._preflight_status = PREFLIGHT_MISCONFIGURED
            return self._preflight_status
        if self.tier == TIER_BROWSER and not browser_tier_allowed():
            self._preflight_status = PREFLIGHT_MISCONFIGURED
            return self._preflight_status
        try:
            request = urllib.request.Request(
                f"{self.base_url}{WIGOLO_HEALTH_PATH}", method="GET"
            )
            with urllib.request.urlopen(request, timeout=3.0) as response:  # noqa: S310
                payload = json.loads(response.read().decode("utf-8", "replace"))
        except Exception:
            self._preflight_status = PREFLIGHT_UNAVAILABLE
            return self._preflight_status
        healthy = (
            isinstance(payload, Mapping)
            and str(payload.get("status") or "") == "healthy"
        )
        self._preflight_status = PREFLIGHT_READY if healthy else PREFLIGHT_UNAVAILABLE
        return self._preflight_status

    def mark_circuit_open(self) -> None:
        """Called by the caller after an unrecoverable failure (defensive)."""

        self._circuit_open = True

    # ------------------------------------------------------------------ fetch
    def fetch(self, request: ReadRequest) -> RawReadArtifact:
        if self._circuit_open:
            return self._failure(
                request.url,
                time.monotonic(),
                state="unsupported",
                detail="circuit_open",
                tier=self.tier,
            )
        if self.preflight() != PREFLIGHT_READY:
            return self._failure(
                request.url,
                time.monotonic(),
                state="unsupported",
                detail=f"preflight:{self._preflight_status}",
                tier=self.tier,
            )
        started = time.monotonic()
        payload = {
            "url": request.url,
            "render_js": self.render_js,
            "max_chars": self.max_chars,
        }
        # §71B2: the effective timeout is the *bindings* value - the caller's
        # envelope/hard-headroom cap must actually be enforced, otherwise a
        # single slow call can punch through the per-run envelope.
        timeout = self.timeout_seconds
        requested_timeout = getattr(request, "timeout_seconds", None)
        if isinstance(requested_timeout, (int, float)) and requested_timeout > 0:
            timeout = min(timeout, float(requested_timeout))
        try:
            body = json.dumps(payload).encode("utf-8")
            http_request = urllib.request.Request(
                f"{self.base_url}{WIGOLO_FETCH_PATH}",
                data=body,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(  # noqa: S310 - loopback only
                http_request, timeout=timeout
            ) as response:
                raw = response.read()
                status = int(getattr(response, "status", 0) or 0)
        except urllib.error.HTTPError as exc:
            return self._failure(
                request.url, started, state="http_error", detail=str(exc), tier=self.tier
            )
        except TimeoutError:
            self.mark_circuit_open()
            return self._failure(
                request.url, started, state="timeout", detail="timeout", tier=self.tier
            )
        except Exception as exc:  # noqa: BLE001 - fallback must never raise upward
            return self._failure(
                request.url,
                started,
                state="transport_error",
                detail=type(exc).__name__,
                tier=self.tier,
            )

        latency_ms = round((time.monotonic() - started) * 1000.0, 1)
        try:
            data = json.loads(raw.decode("utf-8", "replace"))
        except Exception:
            return self._failure(
                request.url,
                started,
                state="invalid_response",
                detail="json_decode",
                tier=self.tier,
            )
        if not isinstance(data, Mapping):
            return self._failure(
                request.url,
                started,
                state="invalid_response",
                detail="not_an_object",
                tier=self.tier,
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
        truncation_signal = data.get("truncated")
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
                "tier": self.tier,
                "http_status": data.get("http_status"),
                "request_status": status,
                "title": str(data.get("title") or ""),
                "fetch_method_raw": method,
                "cached_raw": data.get("cached"),
                "max_chars_requested": self.max_chars,
                "chars_returned": len(markdown),
                # only recorded when the daemon actually says so - never guessed
                "possibly_truncated": (
                    _explicit_bool(truncation_signal)
                    if truncation_signal is not None
                    else None
                ),
                "links": len(data.get("links") or []),
                "images": len(data.get("images") or []),
            },
        )

    def _failure(
        self, url: str, started: float, *, state: str, detail: str, tier: str
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
            external_metadata={
                "state": state,
                "detail": str(detail)[:160],
                "tier": tier,
                "max_chars_requested": self.max_chars,
                "chars_returned": 0,
            },
        )


__all__ = [
    "PREFLIGHT_MISCONFIGURED",
    "PREFLIGHT_READY",
    "PREFLIGHT_UNAVAILABLE",
    "RERANKER_ENV",
    "TIER_BROWSER",
    "TIER_HTTP",
    "WIGOLO_BACKEND_NAME",
    "WIGOLO_DEFAULT_BASE_URL",
    "WIGOLO_FETCH_MAX_CHARS",
    "WIGOLO_FETCH_PATH",
    "WigoloShadowReadBackend",
]
