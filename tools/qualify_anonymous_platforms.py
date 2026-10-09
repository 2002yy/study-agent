"""Bounded anonymous probes, with no login/profile/Cookie or provider-key access.

Public HTTP success is not proof that a CLI specialist or video reader works.
This writes diagnostic capability evidence only, never production qualification.
"""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
from pathlib import Path
import subprocess
import time
from urllib.error import HTTPError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
PROBES = (
    ("bilibili", "search", "https://api.bilibili.com/x/web-interface/search/type?search_type=video&keyword=Python&page=1"),
    ("youtube", "public_page", "https://www.youtube.com/watch?v=jNQXAC9IVRw"),
    ("rss", "feed", "https://blog.python.org/feeds/posts/default?alt=rss"),
    ("v2ex", "feed", "https://www.v2ex.com/api/topics/hot.json"),
)
MAX_BYTES = 500_000


def probe(platform: str, operation: str, url: str) -> dict:
    started = time.monotonic()
    row = {"platform": platform, "operation": operation, "url": url,
           "auth_mode": "anonymous", "qualified": False, "status": "unavailable"}
    try:
        with urlopen(Request(url, headers={"User-Agent": "StudyAgent/anonymous-qualification"}), timeout=8) as response:
            payload = response.read(MAX_BYTES + 1)
            row["http_status"] = response.status
            row["final_url"] = response.url
        row["payload_sha256"] = hashlib.sha256(payload).hexdigest()
        if len(payload) > MAX_BYTES:
            row["reason"] = "response_too_large"
            return row
        if platform == "rss":
            import feedparser
            feed = feedparser.parse(payload)
            row["observed_records"] = len(feed.entries)
            row["status"] = "public_feed_observed" if feed.entries and not feed.bozo else "invalid_feed"
        elif platform == "bilibili":
            value = json.loads(payload)
            row["platform_code"] = value.get("code")
            items = (value.get("data") or {}).get("result") or []
            row["observed_records"] = len(items)
            row["status"] = "public_search_observed" if value.get("code") == 0 and items else "platform_rejected"
        elif platform == "v2ex":
            value = json.loads(payload)
            valid = isinstance(value, list) and bool(value) and all(isinstance(item, dict) and item.get("id") for item in value)
            row["observed_records"] = len(value) if isinstance(value, list) else 0
            row["status"] = "public_feed_observed" if valid else "invalid_response"
        else:
            row["status"] = "public_page_observed"
            row["reason"] = "html_is_not_subtitle_or_video_content"
    except HTTPError as exc:
        row.update(http_status=exc.code, reason=f"http_{exc.code}")
    except Exception as exc:
        row["reason"] = type(exc).__name__
    finally:
        row["elapsed_seconds"] = round(time.monotonic() - started, 3)
    return row


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="Explicitly run four public probes once each")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    if output == ROOT or ROOT in output.parents or output.exists():
        parser.error("Use a new artifact path outside this checkout")
    packages = {}
    for package in ("bilibili-cli", "yt-dlp", "feedparser"):
        try:
            packages[package] = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            packages[package] = None
    with ThreadPoolExecutor(max_workers=4) as pool:
        rows = list(pool.map(lambda args: probe(*args), PROBES)) if args.live else []
    artifact = {"schema_version": "anonymous-platform-probe-v1", "created_at": datetime.now(timezone.utc).isoformat(),
                "head": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
                "tool_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                "packages": packages, "live": args.live, "probes": rows,
                "cookie_access": False, "browser_profile_access": False, "qualified": False,
                "limitations": ["HTTP observations are not CLI/sidecar search/detail qualification",
                                "No subtitles, comments, login-bound platforms or Evidence admission tested"]}
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(artifact, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"artifact": str(output), "statuses": {row["platform"]: row["status"] for row in rows}}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
