"""Read public Bilibili comments, one bounded page at a time.

The endpoint is public and needs no cookies. The caller chooses the page; the
result reports how much of the thread was read instead of implying completeness.
"""

from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Any

_BVID = re.compile(r"(BV[0-9A-Za-z]{10})")
_UA = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/141.0 Safari/537.36",
    "Referer": "https://www.bilibili.com/",
}
_PAGE_SIZE = 20


def _failure(url: str, code: str, message: str) -> dict[str, Any]:
    return {
        "ok": False,
        "kind": "comments",
        "url": url,
        "error": message,
        "error_code": code,
    }


def _get_json(url: str, timeout: float) -> dict[str, Any]:
    request = urllib.request.Request(url, headers=_UA)
    with urllib.request.urlopen(request, timeout=max(1, int(timeout))) as response:
        return json.loads(response.read().decode("utf-8"))


def _time_text(epoch: Any) -> str:
    try:
        return datetime.fromtimestamp(float(epoch), tz=timezone.utc).isoformat(timespec="seconds")
    except (TypeError, ValueError, OSError):
        return ""


def read_comments(
    url: str, *, page: int = 1, limit: int = 20, timeout: float = 15.0,
) -> dict[str, Any]:
    """Return one page of public comments for a Bilibili video."""

    match = _BVID.search(str(url or ""))
    if not match:
        return _failure(str(url or ""), "comments_unsupported", "not a Bilibili video URL")
    video_id = match.group(1)
    page = max(1, min(int(page), 50))
    limit = max(1, min(int(limit), 20))
    try:
        view = _get_json(
            "https://api.bilibili.com/x/web-interface/view?"
            + urllib.parse.urlencode({"bvid": video_id}),
            timeout,
        )
    except Exception as exc:  # noqa: BLE001 - one bounded probe
        return _failure(url, "comments_unavailable", f"{type(exc).__name__}: {exc}")
    aid = (view.get("data") or {}).get("aid")
    if not aid:
        return _failure(url, "comments_unavailable", "the video id has no comment thread")

    try:
        reply = _get_json(
            "https://api.bilibili.com/x/v2/reply?"
            + urllib.parse.urlencode({
                "type": 1, "oid": aid, "pn": page,
                "ps": _PAGE_SIZE, "sort": 2,
            }),
            timeout,
        )
    except Exception as exc:  # noqa: BLE001 - one bounded probe
        return _failure(url, "comments_unavailable", f"{type(exc).__name__}: {exc}")
    data = reply.get("data") or {}
    raw = data.get("replies") or []
    comments = []
    for row in raw[:limit]:
        if not isinstance(row, dict):
            continue
        member = row.get("member") or {}
        content = row.get("content") or {}
        text = str(content.get("message") or "").strip()
        if not text:
            continue
        comments.append({
            "author": str(member.get("uname") or "").strip()[:80],
            "time": _time_text(row.get("ctime")),
            "text": text[:1200],
            "likes": int(row.get("like") or 0),
            "replies": int(row.get("rcount") or 0),
        })
    total = int((data.get("page") or {}).get("count") or 0)
    if not comments:
        return _failure(url, "comments_empty", "this page has no readable comments")
    return {
        "ok": True,
        "kind": "comments",
        "url": url,
        "video_id": video_id,
        "title": str((view.get("data") or {}).get("title") or ""),
        "page": page,
        "read": len(comments),
        "total": total,
        "comments": comments,
        "may_be_partial": total > len(comments),
        "scope": {"page": page, "page_size": _PAGE_SIZE},
    }
