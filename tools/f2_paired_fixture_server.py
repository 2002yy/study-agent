# -*- coding: utf-8 -*-
"""§143-B dedicated paired fixture server (threshold-safe variants).

The §143-B frozen fixture set (docs/PROJECT_STATUS.md §143.26) was carried over
from the A3 browser bakeoff, where every page is deliberately tiny. The
production readers apply a frozen adequacy threshold
(``src/web/research/read_adequacy.py``: ``SHORT_CHAR_THRESHOLD = 800``), so those
miniature pages are classified ``short_doc`` and the paired comparison measured
the threshold instead of content recovery (see the diagnostic-invalid run
``docs/research_quality/F2_PAIRED.json``).

This server serves the **same categories, the same critical units and the same
expected answers**, but each non-PDF fixture is a realistic document whose
normalized text is comfortably above the threshold (target >= 1200 chars). Only
the document carrier changes; the rubric does not.

It is a fixture server, not a product surface: loopback only, started by the
operator, unknown to the runtime.

Usage::

    python tools/f2_paired_fixture_server.py --port 8793
"""

from __future__ import annotations

import argparse
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

SENTINEL_MARKER = "F2_FALLBACK_SENTINEL_OK"

#: Neutral engineering prose used to grow a page past the adequacy threshold.
#: It deliberately contains none of the frozen critical units (or their
#: substrings), so it adds length without adding decision content.
_FILLER = (
    "Maintenance note: this controlled fixture carries ordinary engineering "
    "prose so the rendered body stays comfortably above the reader adequacy "
    "threshold while contributing no decision content of its own. The wording "
    "is intentionally generic and repeats a bounded number of times."
)


def _filler(count: int) -> str:
    return "".join(f"<p>{_FILLER}</p>" for _ in range(count))


# ── simple_static /structured-spec.html ─────────────────────────────────
# critical units: 2026-08-01, ES modules, CommonJS, supported
_STRUCTURED_SPEC = (
    "<html><head><title>Release specification</title></head><body>"
    "<h1>Release specification</h1>"
    "<p>This page documents the verified release in prose form.</p>"
    "<table><tr><th>Field</th><th>Value</th></tr>"
    "<tr><td>release_date</td><td>2026-08-01</td></tr>"
    "<tr><td>module_system</td><td>ES modules</td></tr>"
    "<tr><td>legacy_system</td><td>CommonJS</td></tr>"
    "<tr><td>support_status</td><td>supported</td></tr></table>"
    "<p>Recorded release facts: the release date is 2026-08-01, the module "
    "system is ES modules, the legacy system is CommonJS, and the support "
    "status is supported.</p>"
    "<p>See the linked release notes for the full changelog.</p>"
    + _filler(10)
    + "<p>Operators should record the release identifier together with the "
    "module system before scheduling an upgrade window.</p>"
    "</body></html>"
)

# ── technical_docs /code-docs.html ──────────────────────────────────────
# critical units: Compute API, def compute(value), verified release identifier, canonical id
_CODE_DOCS = (
    "<html><head><title>Compute API</title></head><body>"
    "<h1>Compute API</h1>"
    "<p>The helper below returns the verified release identifier.</p>"
    "<pre><code>def compute(value):\n    return value</code></pre>"
    "<p>Call it with the release date to obtain the canonical id.</p>"
    "<p>The Compute API is documented below. The helper signature is "
    "def compute(value); its docstring returns the verified release "
    "identifier, and callers should persist that value as the canonical id "
    "for later lookups.</p>"
    + _filler(10)
    + "<p>Downstream services should treat the returned value as read-only and "
    "never mutate the caller-supplied mapping in place.</p>"
    "</body></html>"
)

# ── js_heavy /spa-delayed.html ──────────────────────────────────────────
# critical units (only after JS): verified release date is 2026-08-01, CommonJS guidance
_RENDERED_BODY = (
    "<article><h1>Rendered release notes</h1>"
    + "".join(
        f"<p>Paragraph {index}: the verified release date is 2026-08-01 and the "
        "current module guidance differs from the older CommonJS guidance.</p>"
        for index in range(12)
    )
    + "</article>"
)
_SPA_DELAYED = (
    "<html><head><title>Loading application shell</title></head><body>"
    "<div id='root'>Loading application shell. The interactive report will "
    "replace this placeholder once the client runtime has finished starting."
    + _filler(9)
    + "</div>"
    "<script>setTimeout(function(){document.getElementById('root').innerHTML="
    f"'{_RENDERED_BODY}';}},250);</script></body></html>"
)

# ── document_path /document-mixed.html ──────────────────────────────────
# critical units live in the LINKED PDF, not in this HTML
_DOCUMENT_MIXED = (
    "<html><head><title>Quarterly report landing page</title></head><body>"
    "<h1>Quarterly report</h1>"
    "<p>Download the report:</p>"
    "<p><a href='/report.pdf'>report.pdf</a></p>"
    + _filler(10)
    + "<p>This landing page intentionally contains only navigation prose; the "
    "decision content is carried by the linked document.</p>"
    "</body></html>"
)

# ── session_sensitive /session/check (+ /session/start) ─────────────────
_SESSION_COOKIE = "f2_sid"
_SESSION_TOKEN = "f2-session-truth-2026"
_SESSION_LOGIN_WALL = (
    "<html><head><title>Members only</title></head><body>"
    "<h1>Members only</h1>"
    "<p>Please log in to continue reading this article.</p>"
    + _filler(10)
    + "<p>Sign in with the workspace account to view the protected section.</p>"
    "</body></html>"
)
_SESSION_GRANTED = (
    "<html><head><title>Protected report</title></head><body>"
    "<h1>SESSION OK</h1><p>cookie accepted</p>"
    + _filler(10)
    + "<p>The protected section is now visible to the authenticated session.</p>"
    "</body></html>"
)
_SESSION_START = (
    "<html><head><title>Session start</title></head><body>"
    "<h1>Session start</h1><p>Establishing the workspace session.</p>"
    + _filler(10)
    + "</body></html>"
)

# ── fallback sentinel (short by design: forces NATIVE_HTTP -> WIGOLO_HTTP) ─
_SENTINEL = (
    "<html><head><title>Fallback sentinel</title></head><body>"
    f"<p>{SENTINEL_MARKER}</p></body></html>"
)

# ── selected_pdf /report.pdf ────────────────────────────────────────────
# critical units: verified release date is 2026-08-01, CommonJS guidance, extractable prose
from tools.browser_bakeoff_fixture_server import build_text_pdf  # noqa: E402

_PDF_LINES = tuple(
    [f"Section {n}: the verified release date is 2026-08-01." for n in range(1, 3)]
    + [
        f"Paragraph {n}: current module guidance differs from the older "
        "CommonJS guidance, and this controlled fixture carries real "
        "extractable prose so a PDF extractor must return a substantial body."
        for n in range(1, 31)
    ]
)
_PDF_BYTES = build_text_pdf(_PDF_LINES)

PAGES: dict[str, tuple[int, str, bytes]] = {
    "/structured-spec.html": (200, "text/html; charset=utf-8", _STRUCTURED_SPEC.encode("utf-8")),
    "/code-docs.html": (200, "text/html; charset=utf-8", _CODE_DOCS.encode("utf-8")),
    "/spa-delayed.html": (200, "text/html; charset=utf-8", _SPA_DELAYED.encode("utf-8")),
    "/document-mixed.html": (200, "text/html; charset=utf-8", _DOCUMENT_MIXED.encode("utf-8")),
    "/report.pdf": (200, "application/pdf", _PDF_BYTES),
    "/f2-fallback-sentinel.html": (200, "text/html; charset=utf-8", _SENTINEL.encode("utf-8")),
    "/session/start": (200, "text/html; charset=utf-8", _SESSION_START.encode("utf-8")),
    # /session/check is served dynamically (cookie decides the body)
}

#: The session cookie is set here, not in the body.
PAGE_HEADERS: dict[str, tuple[tuple[str, str], ...]] = {
    "/session/start": (("Set-Cookie", f"{_SESSION_COOKIE}={_SESSION_TOKEN}; Path=/"),),
}


def session_check_body(cookie_header: str) -> tuple[int, str]:
    present = f"{_SESSION_COOKIE}={_SESSION_TOKEN}" in str(cookie_header or "")
    if present:
        return 200, _SESSION_GRANTED
    return 401, _SESSION_LOGIN_WALL


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_GET(self) -> None:  # noqa: N802 - http.server API
        path = self.path.split("?", 1)[0]
        if path == "/session/check":
            status, body = session_check_body(self.headers.get("Cookie", ""))
            payload = body.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(payload)
            return
        entry = PAGES.get(path)
        if entry is None:
            self.send_response(404)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        status, content_type, body = entry
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for header, value in PAGE_HEADERS.get(path, ()):
            self.send_header(header, value)
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        return


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8793)
    args = parser.parse_args(argv)
    server = ThreadingHTTPServer((args.host, args.port), _Handler)
    print(f"f2 paired fixture server on http://{args.host}:{args.port} ({len(PAGES)} + session paths)")
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
