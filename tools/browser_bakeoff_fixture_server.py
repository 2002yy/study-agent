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

_PDF_BYTES = (
    b"%PDF-1.4\n"
    b"1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
    b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
    b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 200 200]>>endobj\n"
    b"trailer<</Root 1 0 R>>\n%%EOF\n"
)

PAGES: dict[str, tuple[int, str, bytes]] = {
    # (status, content-type, body)
    "/js-shell.html": (
        200,
        "text/html; charset=utf-8",
        b"<html><head><title>App</title></head><body>"
        b"<noscript>Please enable JavaScript to view this page.</noscript>"
        b"<div id='root'></div></body></html>",
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
}


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_GET(self) -> None:  # noqa: N802 - http.server API
        path = self.path.split("?", 1)[0]
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
