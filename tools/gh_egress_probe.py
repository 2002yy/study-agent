"""GitHub Runner egress probe (B-Search-2B2): DNS/HTTPS/status/latency + tool fetch.

Read-only, anonymous, no cookies/keys, no anti-bot bypass. Prints one JSON blob.
"""
from __future__ import annotations

import hashlib
import json
import socket
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request

TARGETS = (
    ("bilibili_search_api", "https://api.bilibili.com/x/web-interface/search/type?search_type=video&keyword=Factorio&page=1"),
    ("youtube_watch", "https://www.youtube.com/watch?v=jNQXAC9IVRw"),
    ("v2ex_feed", "https://www.v2ex.com/api/topics/hot.json"),
    ("rss_python_blog", "https://blog.python.org/feeds/posts/default?alt=rss"),
    ("google", "https://www.google.com/"),
    ("duckduckgo_html", "https://html.duckduckgo.com/html/?q=factorio+interrupts"),
    ("brave", "https://search.brave.com/"),
    ("startpage", "https://www.startpage.com/"),
)


def probe(name: str, url: str) -> dict:
    row: dict = {"name": name, "url": url}
    host = urllib.parse.urlsplit(url).hostname or ""
    try:
        row["dns"] = socket.gethostbyname(host)
    except Exception as exc:  # noqa: BLE001
        row["dns"] = type(exc).__name__
    started = time.monotonic()
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "StudyAgent/egress-probe"})
        with urllib.request.urlopen(req, timeout=25) as response:
            payload = response.read(200_000)
            row.update(status=response.status, final_url=response.url, bytes=len(payload),
                       sha256=hashlib.sha256(payload).hexdigest(),
                       latency_s=round(time.monotonic() - started, 3))
    except urllib.error.HTTPError as exc:
        row.update(status=exc.code, reason=f"http_{exc.code}",
                   latency_s=round(time.monotonic() - started, 3))
    except Exception as exc:  # noqa: BLE001
        row.update(reason=type(exc).__name__, latency_s=round(time.monotonic() - started, 3))
    return row


def _run(cmd: list[str], timeout: int = 120) -> dict:
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return {"rc": out.returncode, "stdout_len": len(out.stdout), "stderr": out.stderr[-400:]}
    except Exception as exc:  # noqa: BLE001
        return {"error": type(exc).__name__}


def main() -> None:
    report: dict = {"probes": [probe(name, url) for name, url in TARGETS], "tools": {}}
    report["tools"]["yt_dlp_version"] = _run(["yt-dlp", "--version"], 30)
    report["tools"]["ytdlp_bilibili_search"] = _run(
        ["yt-dlp", "--no-warnings", "--flat-playlist", "--playlist-end", "1",
         "--dump-single-json", "bilisearch1:Factorio train interrupts"], 120)
    report["tools"]["ytdlp_youtube"] = _run(
        ["yt-dlp", "--no-warnings", "--dump-single-json", "https://www.youtube.com/watch?v=jNQXAC9IVRw"], 120)
    report["tools"]["feedparser_rss"] = _run(
        ["python", "-c", "import feedparser;d=feedparser.parse('https://blog.python.org/feeds/posts/default?alt=rss');"
         "print('entries',len(d.entries),'bozo',d.bozo)"], 60)
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
