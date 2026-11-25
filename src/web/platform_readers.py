"""Thin API readers for platforms whose pages are poor over plain HTTP.

One module, host dispatch, no per-platform tool or workflow. Each reader returns
the same shape the existing gateway already produces; budgets, caching, failure
codes and evidence handling stay in the gateway.
"""

from __future__ import annotations

import html
import json
import re
import time
import urllib.error
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
#: MediaWiki sites with a public ``api.php``. Wikipedia and its sister projects
#: share a suffix; the rest are known installs, listed explicitly so an arbitrary
#: host cannot become an API target.
_MEDIAWIKI_SUFFIXES = (
    ".wikipedia.org",
    ".wiktionary.org",
    ".wikibooks.org",
    ".wikiquote.org",
    ".wikisource.org",
    ".wikinews.org",
    ".wikivoyage.org",
    ".wikiversity.org",
    ".wikimedia.org",
    ".wiki.gg",
)
_MEDIAWIKI_HOSTS = (
    "wiki.archlinux.org",
    "wiki.gentoo.org",
    "wiki.nixos.org",
    "minecraft.wiki",
    "www.mediawiki.org",
    "moegirl.org.cn",
    "zh.moegirl.org.cn",
    "wiki.biligame.com",
)
#: Hosts whose page path is the title itself (no /wiki/ prefix).
_ROOT_TITLE_HOSTS = ("moegirl.org.cn",)


def _is_root_title_host(host: str) -> bool:
    return any(host == item or host.endswith("." + item)
               for item in _ROOT_TITLE_HOSTS)
#: Hosts that mount one MediaWiki install per first path segment.
_SUBPATH_WIKI_HOSTS = ("wiki.biligame.com",)
#: Endpoints the readers discovered per origin, so a host is probed once.
_MEDIAWIKI_ENDPOINTS: dict[str, str] = {}


def _is_mediawiki_host(host: str) -> bool:
    if host in _MEDIAWIKI_HOSTS:
        return True
    return any(host == item.lstrip(".") or host.endswith(item)
               for item in _MEDIAWIKI_SUFFIXES)


_HUGGINGFACE_HOST = "huggingface.co"
_HF_KINDS = ("models", "datasets", "spaces")
#: Top-level Hub paths that are not repositories.
_HF_RESERVED = {
    "papers", "blog", "docs", "join", "login", "settings", "organizations",
    "tasks", "pricing", "enterprise", "collections", "search", "new", "chat",
}


def detect(url: str) -> str:
    host = (urllib.parse.urlsplit(url).hostname or "").lower()
    if host == "news.ycombinator.com":
        return "hn"
    if host in _SE_HOSTS:
        return "stackexchange"
    if host in _DISCOURSE_HOSTS:
        return "discourse"
    if _is_mediawiki_host(host):
        return "mediawiki"
    if host == _HUGGINGFACE_HOST:
        return "huggingface"
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


def _mediawiki_title(url: str) -> str:
    """Take the page title from the wiki URL shapes we support."""

    parsed = urllib.parse.urlsplit(url)
    host = (parsed.hostname or "").lower()
    path = urllib.parse.unquote(parsed.path or "")
    lowered = path.lower()
    if lowered.startswith(("/w/index.php", "/index.php")):
        path = ""
    for prefix in ("/wiki/", "/w/", "/title/"):
        if path.startswith(prefix) and len(path) > len(prefix):
            return path[len(prefix):].replace("_", " ").strip().strip("/")
    if _is_root_title_host(host) and path.strip("/"):
        return path.strip("/").replace("_", " ")
    values = urllib.parse.parse_qs(parsed.query or "")
    return (values.get("title") or [""])[0].replace("_", " ").strip()


def _mediawiki_base(url: str) -> tuple[str, str]:
    """Return the API base and the title for this wiki URL."""

    parsed = urllib.parse.urlsplit(url)
    host = (parsed.hostname or "").lower()
    origin = f"{parsed.scheme}://{parsed.netloc}"
    path = urllib.parse.unquote(parsed.path or "")
    if host in _SUBPATH_WIKI_HOSTS:
        segments = [part for part in path.split("/") if part]
        if len(segments) < 2:
            return "", ""
        title = "/".join(segments[1:]).replace("_", " ")
        return f"{origin}/{segments[0]}", title
    return origin, _mediawiki_title(url)


def _mediawiki_endpoint(base: str, timeout: float) -> str:
    """Find the api.php a wiki actually answers on, once per process."""

    cached = _MEDIAWIKI_ENDPOINTS.get(base)
    if cached:
        return cached
    probe = "?action=query&meta=siteinfo&format=json&formatversion=2"
    for path in ("/w/api.php", "/api.php"):
        try:
            data = _get_json(f"{base}{path}{probe}", timeout)
        except Exception:  # noqa: BLE001 - try the next candidate
            continue
        if (data.get("query") or {}).get("general"):
            _MEDIAWIKI_ENDPOINTS[base] = f"{base}{path}"
            return _MEDIAWIKI_ENDPOINTS[base]
    return ""


def _mediawiki(url: str, timeout: float) -> dict[str, Any]:
    """Read one wiki page through the MediaWiki action API."""

    base, title = _mediawiki_base(url)
    if not title:
        return {"ok": False, "kind": "web_page", "url": url,
                "error": "no wiki page title in this URL",
                "error_code": "platform_unsupported"}
    endpoint = _mediawiki_endpoint(base, timeout)
    if not endpoint:
        return {"ok": False, "kind": "web_page", "url": url,
                "error": "no MediaWiki api.php answered",
                "error_code": "platform_failed"}
    query = urllib.parse.urlencode({
        "action": "query", "prop": "extracts", "explaintext": "1",
        "exlimit": "1", "redirects": "1", "titles": title,
        "format": "json", "formatversion": "2",
    })
    data = _get_json(f"{endpoint}?{query}", timeout)
    pages = (data.get("query") or {}).get("pages") or []
    page = pages[0] if pages else {}
    if page.get("missing"):
        return {"ok": False, "kind": "web_page", "url": url,
                "error": f"page {title!r} does not exist",
                "error_code": "platform_empty"}
    page_title = str(page.get("title") or title)
    text = str(page.get("extract") or "").strip()
    if not text:
        # TextExtracts is an extension; plain installs still answer action=parse.
        parse_query = urllib.parse.urlencode({
            "action": "parse", "page": title, "prop": "text",
            "redirects": "1", "format": "json", "formatversion": "2",
        })
        parsed_page = _get_json(f"{endpoint}?{parse_query}", timeout).get("parse") or {}
        page_title = str(parsed_page.get("title") or page_title)
        text = _text(parsed_page.get("text"))
    return _result(url, "mediawiki_api", page_title, text)


def _get_text(url: str, timeout: float, max_bytes: int = 30_000) -> str:
    request = urllib.request.Request(url, headers=_UA)
    with urllib.request.urlopen(request, timeout=max(1, int(timeout))) as response:
        return response.read(max_bytes).decode("utf-8", errors="replace")


def _huggingface(url: str, timeout: float) -> dict[str, Any]:
    """Read a model, dataset or space through the public Hub API.

    The card and the discussion titles are separate optional requests; losing
    either still leaves a usable record. All requests share one deadline so a
    slow Hub cannot multiply the caller's read budget.
    """

    parsed = urllib.parse.urlsplit(url)
    if (parsed.hostname or "").lower() != _HUGGINGFACE_HOST:
        return {"ok": False, "kind": "web_page", "url": url,
                "error": "not a Hugging Face host",
                "error_code": "platform_unsupported"}
    segments = [part for part in parsed.path.split("/") if part]
    kind = "models"
    if segments and segments[0] in _HF_KINDS:
        kind = segments[0]
        segments = segments[1:]
    if len(segments) != 2:
        return {"ok": False, "kind": "web_page", "url": url,
                "error": "not a model, dataset or space URL",
                "error_code": "platform_unsupported"}
    if kind == "models" and segments[0].lower() in _HF_RESERVED:
        return {"ok": False, "kind": "web_page", "url": url,
                "error": "not a model repository URL",
                "error_code": "platform_unsupported"}
    repo_id = f"{segments[0]}/{segments[1]}"
    deadline = time.monotonic() + max(1.0, float(timeout))

    def remaining() -> float:
        return max(0.0, deadline - time.monotonic())

    def left() -> float | None:
        value = remaining()
        return value if value >= 0.5 else None

    budget = left()
    if budget is None:
        return {"ok": False, "kind": "web_page", "url": url,
                "error": "read budget exhausted before the Hub request",
                "error_code": "platform_failed"}
    try:
        data = _get_json(f"https://{_HUGGINGFACE_HOST}/api/{kind}/{repo_id}", budget)
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return {"ok": False, "kind": "web_page", "url": url,
                    "error": f"{repo_id} not found",
                    "error_code": "platform_empty"}
        raise

    card_data = data.get("cardData") or {}
    license_name = str(card_data.get("license") or "")
    if not license_name:
        license_name = next(
            (tag.split(":", 1)[1] for tag in data.get("tags") or []
             if str(tag).startswith("license:")),
            "",
        )
    label = {"models": "model", "datasets": "dataset", "spaces": "space"}[kind]
    header = [
        f"[{label}] {data.get('id') or repo_id}",
        f"task: {data.get('pipeline_tag') or '-'}",
        f"library: {data.get('library_name') or '-'}",
        f"license: {license_name or '-'}",
        f"downloads: {data.get('downloads', '-')} | likes: {data.get('likes', '-')}",
        f"gated: {data.get('gated')} | private: {data.get('private')}",
        f"created: {data.get('createdAt') or '-'} | modified: {data.get('lastModified') or '-'}",
        f"files: {len(data.get('siblings') or [])}",
    ]
    tags = [str(tag) for tag in (data.get("tags") or [])][:20]
    if tags:
        header.append("tags: " + ", ".join(tags))

    discussion_lines: list[str] = []
    discussion_total: int | None = None
    budget = left()
    if budget is not None:
        try:
            discussions = _get_json(
                f"https://{_HUGGINGFACE_HOST}/api/{kind}/{repo_id}/discussions?p=0",
                budget,
            )
        except Exception:  # noqa: BLE001 - discussions are optional context
            discussions = {}
        else:
            items = discussions.get("discussions") or []
            discussion_total = int(discussions.get("count") or len(items))
            if items:
                discussion_lines.append(f"[discussions] {discussion_total} total")
                for item in items[:5]:
                    discussion_lines.append(
                        f"[#{item.get('num')}] {str(item.get('title') or '')[:120]} "
                        f"({item.get('numComments', 0)} comments)"
                    )

    card = ""
    budget = left()
    if budget is not None:
        prefix = "" if kind == "models" else f"{kind}/"
        try:
            card = _get_text(
                f"https://{_HUGGINGFACE_HOST}/{prefix}{repo_id}/raw/main/README.md",
                budget,
                20_000,
            )
        except Exception:  # noqa: BLE001 - a missing card is not a failed read
            card = ""

    content = "\n".join(header)
    if discussion_lines:
        content += "\n\n" + "\n".join(discussion_lines)
    if card.strip():
        content += "\n\n[model card]\n" + card
    extra: dict[str, Any] = {}
    if discussion_total is not None:
        extra["discussions"] = discussion_total
    return _result(url, "huggingface_api", str(data.get("id") or repo_id), content,
                   **extra)


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
    "mediawiki": _mediawiki,
    "huggingface": _huggingface,
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
