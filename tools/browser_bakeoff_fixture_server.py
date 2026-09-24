"""§110 P2-A3-1 deterministic fixture server for the browser bakeoff.

Serves the six A3-0 fixture classes' ``synthetic_local`` targets so both
candidates are measured on identical, reproducible pages. It is a **fixture
server**, not a product surface: it is started by the operator, it binds
loopback only, and nothing in the runtime knows about it.

Usage::

    python tools/browser_bakeoff_fixture_server.py --port 8899
"""

from __future__ import annotations

import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

#: A body long enough to be "adequate" once a renderer extracts it.
RENDERED_BODY = (
    "<article><h1>Release date</h1>"
    + "".join(
        f"<p>Paragraph {index}: the verified release date is 2026-08-01 and the "
        "current module guidance differs from the older CommonJS guidance.</p>"
        for index in range(40)
    )
    + "</article>"
)

#: §119 1(a): a document_heavy fixture must actually be document-heavy. The
#: earlier 309-char body was below the frozen adequacy threshold (800), so the
#: frozen layer correctly classified it short_doc - the fixture was wrong, not
#: the contract. This body is deliberately well clear of the boundary.
_PDF_LINES = tuple(
    [f"Section {n}: the verified release date is 2026-08-01." for n in range(1, 3)]
    + [
        f"Paragraph {n}: current module guidance differs from the older "
        "CommonJS guidance, and this controlled fixture carries real "
        "extractable prose so a PDF extractor must return a substantial body."
        for n in range(1, 31)
    ]
)


def build_text_pdf(lines: tuple[str, ...]) -> bytes:
    """A minimal valid PDF with a real text content stream (no dependencies).

    §112 A3-2: a PDF with no text stream would make any extractor report zero
    characters, so the document gate would fail for the wrong reason.
    """

    def esc(text: str) -> str:
        return text.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")

    body = ["BT", "/F1 12 Tf", "72 720 Td", "16 TL"]
    for index, line in enumerate(lines):
        if index:
            body.append("T*")
        body.append(f"({esc(line)}) Tj")
    body.append("ET")
    stream = "\n".join(body).encode("ascii", "replace")

    objects: list[bytes] = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        (
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>"
        ),
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length "
        + str(len(stream)).encode()
        + b" >>\nstream\n"
        + stream
        + b"\nendstream",
    ]

    out = bytearray(b"%PDF-1.4\n")
    offsets: list[int] = []
    for number, payload in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{number} 0 obj\n".encode() + payload + b"\nendobj\n"

    xref_at = len(out)
    out += f"xref\n0 {len(objects) + 1}\n".encode()
    out += b"0000000000 65535 f \n"
    for offset in offsets:
        out += f"{offset:010d} 00000 n \n".encode()
    out += (
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
        f"startxref\n{xref_at}\n%%EOF\n"
    ).encode()
    return bytes(out)


_PDF_BYTES = build_text_pdf(_PDF_LINES)

#: §113 A3-2 Phase 1.5A: a real session fixture.
#:
#: ``/session/start`` sets a cookie *and* writes localStorage; ``/session/check``
#: consumes both. A backend only has a real ``session`` capability if request 2
#: sees request 1's state - recognising a login wall is not the same thing.
SESSION_COOKIE = "bakeoff_sid"
SESSION_TOKEN = "sess-truth-2026"

_SESSION_START = (
    "<html><body><h1>Session start</h1><p id='out'>pending</p>"
    "<script>"
    "localStorage.setItem('bakeoff_sid', '" + SESSION_TOKEN + "');"
    "document.getElementById('out').textContent = "
    "'cookie=' + document.cookie + ' local=' + localStorage.getItem('bakeoff_sid');"
    "</script></body></html>"
)

_SESSION_CHECK = (
    "<html><body><h1>Session check</h1><p id='out'>pending</p>"
    "<script>"
    "document.getElementById('out').textContent = "
    "'local=' + (localStorage.getItem('bakeoff_sid') || 'MISSING');"
    "</script></body></html>"
)


def session_check_body(cookie_header: str) -> tuple[int, str]:
    """Server-authoritative session verdict from the cookie alone.

    The body-localStorage echo is a client hint; this function is what decides,
    so the probe does not depend on the provider's own page heuristics.
    """

    present = f"{SESSION_COOKIE}={SESSION_TOKEN}" in str(cookie_header or "")
    if present:
        return 200, "<html><body><h1>SESSION OK</h1><p>cookie accepted</p></body></html>"
    return 401, "<html><body><h1>NO SESSION</h1><p>cookie missing</p></body></html>"

PAGES: dict[str, tuple[int, str, bytes]] = {
    # §119 2(a): a real JS shell. The initial DOM is a shell; a timer then
    # writes deterministic prose into #root. Without the script there is
    # nothing to rescue, which is what the previous fixture accidentally tested.
    "/js-shell.html": (
        200,
        "text/html; charset=utf-8",
        (
            "<html><head><title>App</title></head><body>"
            "<noscript>Please enable JavaScript to view this page.</noscript>"
            "<div id='root'>Loading...</div>"
            "<script>setTimeout(function(){"
            "document.getElementById('root').innerHTML="
            f"'{RENDERED_BODY}';"
            "},100);</script></body></html>"
        ).encode("utf-8"),
    ),
    "/js-shell-nested.html": (
        200,
        "text/html; charset=utf-8",
        b"<html><body><iframe src='/js-shell.html'></iframe></body></html>",
    ),
    "/spa-delayed.html": (
        200,
        "text/html; charset=utf-8",
        (
            "<html><body><div id='root'>Loading...</div>"
            "<script>setTimeout(function(){document.getElementById('root').innerHTML="
            f"'{RENDERED_BODY}';}},250);</script></body></html>"
        ).encode("utf-8"),
    ),
    "/spa-xhr.html": (
        200,
        "text/html; charset=utf-8",
        (
            "<html><body><div id='root'>Loading...</div>"
            "<script>var x=new XMLHttpRequest();x.open('GET','/api/content',false);"
            "x.send();document.getElementById('root').innerHTML=x.responseText;"
            "</script></body></html>"
        ).encode("utf-8"),
    ),
    "/api/content": (200, "text/html; charset=utf-8", RENDERED_BODY.encode("utf-8")),
    "/anti-bot-challenge.html": (
        200,
        "text/html; charset=utf-8",
        b"<html><body><h1>Checking your browser before accessing</h1>"
        b"<p>Please complete the CAPTCHA to continue. Just a moment...</p>"
        b"</body></html>",
    ),
    "/anti-bot-soft-403.html": (
        403,
        "text/html; charset=utf-8",
        b"<html><body><h1>Unusual traffic</h1>"
        b"<p>Are you a robot? Please verify you are human.</p></body></html>",
    ),
    "/session-gated.html": (
        200,
        "text/html; charset=utf-8",
        b"<html><body><h1>Members only</h1>"
        b"<p>Please log in to continue reading this article.</p></body></html>",
    ),
    "/document-mixed.html": (
        200,
        "text/html; charset=utf-8",
        b"<html><body><p>Download the report:</p>"
        b"<a href='/report.pdf'>report.pdf</a></body></html>",
    ),
    "/report.pdf": (200, "application/pdf", _PDF_BYTES),
    # §113 A3-2 Phase 1.5A: real session endpoints (cookie + localStorage).
    # §131 FG1: a genuinely structured page - heading, prose, a key/value
    # table and a decision-critical cell - so the structured-content gate is
    # actually exercised rather than a link stub.
    "/structured-spec.html": (
        200,
        "text/html; charset=utf-8",
        (
            "<html><head><title>Release specification</title></head><body>"
            "<h1>Release specification</h1>"
            "<p>This page documents the verified release in prose form.</p>"
            "<table><tr><th>Field</th><th>Value</th></tr>"
            "<tr><td>release_date</td><td>2026-08-01</td></tr>"
            "<tr><td>module_system</td><td>ES modules</td></tr>"
            "<tr><td>legacy_system</td><td>CommonJS</td></tr>"
            "<tr><td>support_status</td><td>supported</td></tr></table>"
            "<p>See the linked release notes for the full changelog.</p>"
            "</body></html>"
        ).encode("utf-8"),
    ),
    "/session/start": (200, "text/html; charset=utf-8", _SESSION_START.encode("utf-8")),
    "/session/check": (200, "text/html; charset=utf-8", _SESSION_CHECK.encode("utf-8")),
}

#: Extra response headers per path (the session cookie is set here, not in the body).
PAGE_HEADERS: dict[str, tuple[tuple[str, str], ...]] = {
    "/session/start": (("Set-Cookie", f"{SESSION_COOKIE}={SESSION_TOKEN}; Path=/"),),
}


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_GET(self) -> None:  # noqa: N802 - http.server API
        path = self.path.split("?", 1)[0]
        if path == "/stalled-report.pdf":
            # §121 gate C(3): headers plus a little data, then stall far past
            # the budget. Proves the quantum socket timeout returns control to
            # the absolute-deadline loop instead of waiting on the peer.
            import time as _stall_time

            self.send_response(200)
            self.send_header("Content-Type", "application/pdf")
            self.send_header("Content-Length", str(len(_PDF_BYTES)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            try:
                self.wfile.write(_PDF_BYTES[:128])
                self.wfile.flush()
            except Exception:
                return
            _stall_time.sleep(30)
            return
        if path == "/slow-report.pdf":
            # §120 gate C: trickle a PDF so each read is small but the total
            # wall time far exceeds the browser budget.
            import time as _time

            body = _PDF_BYTES
            self.send_response(200)
            self.send_header("Content-Type", "application/pdf")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            for offset in range(0, len(body), 256):
                try:
                    self.wfile.write(body[offset:offset + 256])
                    self.wfile.flush()
                except Exception:
                    return
                _time.sleep(0.25)
            return
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
        print(f"[fixture] {self.address_string()} {format % args}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8899)
    args = parser.parse_args(argv)
    server = ThreadingHTTPServer((args.host, args.port), _Handler)
    print(f"fixture server on http://{args.host}:{args.port} ({len(PAGES)} paths)")
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
