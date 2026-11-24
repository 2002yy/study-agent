"""Thin API readers for platforms whose pages are poor over plain HTTP.

One module, host dispatch, no per-platform tool or workflow. Each reader returns
the same shape the existing gateway already produces; budgets, caching, failure
codes and evidence handling stay in the gateway.
"""

from __future__ import annotations

import html
import json
import re
import urllib.parse
import urllib.request
from typing import Any

_UA = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/141.0 Safari/537.36",
}
_SE_HOSTS = {
    "stackoverflow.com": "stackoverflow",
    "serverfault.com": "serverfault",
    "superuser.com": "superuser",
    "askubuntu.com": "askubuntu",
    "math.stackexchange.com": "math",
    "dba.stackexchange.com": "dba",
    "softwareengineering.stackexchange.com": "softwareengineering",
    "unix.stackexchange.com": "unix",
}
_DISCOURSE_HOSTS = (
    "forum.godotengine.org",
    "devtalk.blender.org",
    "discuss.huggingface.co",
    "discourse.julialang.org",
    "users.rust-lang.org",
)


def detect(url: str) -> str:
    host = (urllib.parse.urlsplit(url).hostname or "").lower()
    if host == "news.ycombinator.com":
        return "hn"
    if host in _SE_HOSTS:
        return "stackexchange"
    if host in _DISCOURSE_HOSTS:
        return "discourse"
    if host == "openreview.net":
        return "openreview"
    return ""


def _get_json(url: str, timeout: float) -> dict[str, Any]:
    request = urllib.request.Request(url, headers=_UA)
    with urllib.request.urlopen(request, timeout=max(1, int(timeout))) as response:
        return json.loads(response.read().decode("utf-8", errors="replace"))


def _text(value: Any) -> str:
    raw = str(value or "")
    raw = re.sub(r"<br\s*/?>", "\n", raw, flags=re.I)
    raw = re.sub(r"</p>", "\n", raw, flags=re.I)
    raw = re.sub(r"<[^>]+>", " ", raw)
    raw = html.unescape(raw)
    return re.sub(r"[ \t]+", " ", raw).strip()


def _result(url: str, method: str, title: str, content: str, **extra: Any) -> dict[str, Any]:
    content = content[:20_000].strip()
    if not content:
        return {
            "ok": False, "kind": "web_page", "url": url, "method": method,
            "error": "the API returned no readable text", "error_code": "platform_empty",
        }
    return {
        "ok": True, "kind": "web_page", "url": url, "method": method,
        "title": title[:300], "content": content, **extra,
    }


def _hn(url: str, timeout: float) -> dict[str, Any]:
    match = re.search(r"[?&]id=(\d+)", url)
    if not match:
        return {"ok": False, "kind": "web_page", "url": url, "error": "no item id",
                "error_code": "platform_unsupported"}
    item = _get_json(f"https://hn.algolia.com/api/v1/items/{match.group(1)}", timeout)
    lines = [_text(item.get("text"))]
    count = 0

    def walk(node: dict[str, Any], depth: int) -> None:
        nonlocal count
        for child in node.get("children") or []:
            if count >= 40 or depth > 6:
                return
            text = _text(child.get("text"))
            if text:
                author = child.get("author") or ""
                when = child.get("created_at") or ""
                lines.append(f"[d{depth}] {author} {when}\n{text}"[:1200])
                count += 1
            walk(child, depth + 1)

    walk(item, 1)
    title = str(item.get("title") or f"Hacker News item {match.group(1)}")
    return _result(url, "hn_api", title, "\n\n".join(part for part in lines if part),
                   comments=count)


def _stackexchange(url: str, timeout: float) -> dict[str, Any]:
    parsed = urllib.parse.urlsplit(url)
    site = _SE_HOSTS.get((parsed.hostname or "").lower(), "")
    match = re.search(r"/questions/(\d+)", parsed.path)
    if not site or not match:
        return {"ok": False, "kind": "web_page", "url": url, "error": "unsupported question URL",
                "error_code": "platform_unsupported"}
    question_id = match.group(1)
    base = f"https://api.stackexchange.com/2.3/questions/{question_id}"
    query = urllib.parse.urlencode({"site": site, "filter": "withbody"})
    question = _get_json(f"{base}?{query}", timeout)
    items = question.get("items") or []
    if not items:
        return {"ok": False, "kind": "web_page", "url": url, "error": "question not found",
                "error_code": "platform_empty"}
    item = items[0]
    answers = _get_json(
        f"{base}/answers?{urllib.parse.urlencode({'site': site, 'filter': 'withbody', 'sort': 'votes', 'order': 'desc', 'pagesize': 10})}",
        timeout,
    ).get("items") or []
    parts = [_text(item.get("body"))]
    for answer in answers:
        owner = (answer.get("owner") or {}).get("display_name") or ""
        parts.append(f"[answer score={answer.get('score', 0)}] {owner}\n{_text(answer.get('body'))}"[:2000])
    return _result(url, "stackexchange_api", _text(item.get("title")), "\n\n".join(parts),
                   answers=len(answers))


def _discourse(url: str, timeout: float) -> dict[str, Any]:
    parsed = urllib.parse.urlsplit(url)
    host = parsed.hostname or ""
    match = re.search(r"/t/(?:[^/]+/)?(\d+)", parsed.path)
    if not host or not match:
        return {"ok": False, "kind": "web_page", "url": url, "error": "unsupported topic URL",
                "error_code": "platform_unsupported"}
    data = _get_json(f"https://{host}/t/{match.group(1)}.json", timeout)
    posts = (data.get("post_stream") or {}).get("posts") or []
    parts = []
    for post in posts[:20]:
        who = post.get("username") or ""
        when = post.get("created_at") or ""
        parts.append(f"[{who} {when}]\n{_text(post.get('cooked'))}"[:2000])
    next_url = ""
    stream = (data.get("post_stream") or {}).get("stream") or []
    if len(stream) > len(posts):
        next_url = f"{url.split('?')[0]}?page=2"
    return _result(url, "discourse_api", str(data.get("title") or ""), "\n\n".join(parts),
                   replies=len(posts), next_url=next_url)


def _openreview(url: str, timeout: float) -> dict[str, Any]:
    match = re.search(r"[?&]id=([^&]+)", url)
    if not match:
        return {"ok": False, "kind": "web_page", "url": url, "error": "no forum id",
                "error_code": "platform_unsupported"}
    forum = match.group(1)
    notes: list[dict[str, Any]] = []
    limited = False
    try:
        notes = _get_json(
            "https://api2.openreview.net/notes?"
            + urllib.parse.urlencode({"forum": forum, "limit": 50}), timeout,
        ).get("notes") or []
    except Exception:  # noqa: BLE001 - the forum endpoint may require auth
        notes = []
    if not notes:
        # Public search still returns the paper's own note; reviews need auth.
        limited = True
        found = _get_json(
            "https://api2.openreview.net/notes/search?"
            + urllib.parse.urlencode({"term": forum, "limit": 20}), timeout,
        ).get("notes") or []
        notes = [
            note for note in found
            if str(note.get("forum") or note.get("id")) == forum
        ][:1] or found[:1]

    def value(content: dict[str, Any], key: str) -> str:
        raw = content.get(key)
        if isinstance(raw, dict):
            raw = raw.get("value")
        return str(raw or "")

    title = ""
    parts: list[str] = []
    reviews = 0
    for note in notes:
        content = note.get("content") or {}
        if not title:
            title = value(content, "title")
        invitation = " ".join(note.get("invitations") or [])
        if "Official_Review" in invitation or "Decision" in invitation:
            reviews += 1
            body = " ".join(
                value(content, key) for key in ("summary", "strengths", "weaknesses", "rating", "decision")
            )
            if body.strip():
                parts.append(f"[review] {body}"[:2000])
        elif not parts and value(content, "abstract"):
            parts.append(value(content, "abstract")[:3000])
    if not parts:
        parts = [value(note.get("content") or {}, "abstract") for note in notes]
    return _result(url, "openreview_api", title, "\n\n".join(part for part in parts if part),
                   reviews=reviews, thread_limited=limited)


_READERS = {
    "hn": _hn,
    "stackexchange": _stackexchange,
    "discourse": _discourse,
    "openreview": _openreview,
}


def read(url: str, *, timeout: float = 15.0) -> dict[str, Any]:
    platform = detect(url)
    if not platform:
        return {"ok": False, "kind": "web_page", "url": url, "error": "unsupported host",
                "error_code": "platform_unsupported"}
    try:
        return _READERS[platform](url, timeout)
    except Exception as exc:  # noqa: BLE001 - normalized for the gateway
        return {
            "ok": False, "kind": "web_page", "url": url,
            "error": f"{type(exc).__name__}: {exc}", "error_code": "platform_failed",
        }
