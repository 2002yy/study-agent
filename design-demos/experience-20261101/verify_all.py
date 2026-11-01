"""One-command offline design check; starts a temporary loopback server."""

from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import subprocess
import sys
from threading import Thread

ROOT = Path(__file__).resolve().parent


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, format, *args):
        pass


server = ThreadingHTTPServer(
    ("127.0.0.1", 0), partial(QuietHandler, directory=str(ROOT))
)
thread = Thread(target=server.serve_forever, daemon=True)
thread.start()
env = dict(os.environ, DESIGN_PREVIEW_URL=f"http://127.0.0.1:{server.server_port}/")
results = []
try:
    for number in (1, 2, 3):
        completed = subprocess.run(
            [sys.executable, str(ROOT / f"dir-{number}-verify.py")],
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=90,
        )
        results.append({"direction": number, "exit_code": completed.returncode})
        if completed.returncode:
            print(completed.stderr[-5000:])
finally:
    server.shutdown()
    server.server_close()
print(json.dumps({"results": results, "paid_calls": 0}, indent=2))
raise SystemExit(1 if any(item["exit_code"] for item in results) else 0)
