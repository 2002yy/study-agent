"""Thin API readers for platforms whose pages are poor over plain HTTP.

One module, host dispatch, no per-platform tool or workflow. Each reader returns
the same shape the existing gateway already produces; budgets, caching, failure
codes and evidence handling stay in the gateway.
"""

from __future__ import annotations

import html
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from typing import Any, Callable

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


_LOBSTERS_HOST = "lobste.rs"

_DEPSDEV_HOST = "deps.dev"
_DEPSDEV_SYSTEMS = {"pypi", "npm", "maven", "cargo", "go", "nuget"}
_DOI_HOSTS = ("doi.org", "dx.doi.org")
_OPENALEX_HOST = "openalex.org"
_ARXIV_HOST = "arxiv.org"
_ZENODO_HOST = "zenodo.org"


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
    if host == _LOBSTERS_HOST:
        return "lobsters"
    if host == _DEPSDEV_HOST:
        return "depsdev"
    if host in _DOI_HOSTS:
        return "doi"
    if host == _OPENALEX_HOST:
        return "openalex"
    if host == _ARXIV_HOST:
        return "arxiv"
    if host == _ZENODO_HOST:
        return "zenodo"
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


def _mediawiki_endpoint(base: str, remaining: Callable[[], float]) -> str:
    """Find the api.php a wiki actually answers on, once per process."""

    cached = _MEDIAWIKI_ENDPOINTS.get(base)
    if cached:
        return cached
    probe = "?action=query&meta=siteinfo&format=json&formatversion=2"
    for path in ("/w/api.php", "/api.php"):
        left = remaining()
        if left < 0.5:
            return ""
        try:
            data = _get_json(f"{base}{path}{probe}", left)
        except Exception:  # noqa: BLE001 - try the next candidate
            continue
        if (data.get("query") or {}).get("general"):
            _MEDIAWIKI_ENDPOINTS[base] = f"{base}{path}"
            return _MEDIAWIKI_ENDPOINTS[base]
    return ""


def _mediawiki(url: str, timeout: float) -> dict[str, Any]:
    """Read one wiki page through the MediaWiki action API.

    Every request shares one deadline. Probing the endpoint, the extract and the
    parse fallback used to each get the caller's full timeout, so a slow wiki
    could spend four times the read budget.
    """

    parsed = urllib.parse.urlsplit(url)
    values = urllib.parse.parse_qs(parsed.query or "")
    if any(key in values for key in ("oldid", "diff")) or "history" in (
        values.get("action") or []
    ):
        # A revision URL is not the current article; reading the latest text
        # would silently misrepresent history, so the normal reader takes over.
        return {"ok": False, "kind": "web_page", "url": url,
                "error": "revision and diff URLs are not read by this adapter",
                "error_code": "platform_unsupported"}
    base, title = _mediawiki_base(url)
    if not title:
        return {"ok": False, "kind": "web_page", "url": url,
                "error": "no wiki page title in this URL",
                "error_code": "platform_unsupported"}
    deadline = time.monotonic() + max(1.0, float(timeout))

    def remaining() -> float:
        return max(0.0, deadline - time.monotonic())

    endpoint = _mediawiki_endpoint(base, remaining)
    if not endpoint:
        return {"ok": False, "kind": "web_page", "url": url,
                "error": "no MediaWiki api.php answered",
                "error_code": "platform_failed"}
    left = remaining()
    if left < 0.5:
        return {"ok": False, "kind": "web_page", "url": url,
                "error": "read budget exhausted before the wiki request",
                "error_code": "platform_failed"}
    query = urllib.parse.urlencode({
        "action": "query", "prop": "extracts", "explaintext": "1",
        "exlimit": "1", "redirects": "1", "titles": title,
        "format": "json", "formatversion": "2",
    })
    data = _get_json(f"{endpoint}?{query}", left)
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
        left = remaining()
        if left < 0.5:
            return {"ok": False, "kind": "web_page", "url": url,
                    "error": "read budget exhausted before the parse fallback",
                    "error_code": "platform_failed"}
        parse_query = urllib.parse.urlencode({
            "action": "parse", "page": title, "prop": "text",
            "redirects": "1", "format": "json", "formatversion": "2",
        })
        parsed_page = _get_json(f"{endpoint}?{parse_query}", left).get("parse") or {}
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


def _depsdev(url: str, timeout: float) -> dict[str, Any]:
    """Read one package version and its dependency graph from deps.dev."""

    parsed = urllib.parse.urlsplit(url)
    if (parsed.hostname or "").lower() != _DEPSDEV_HOST:
        return {"ok": False, "kind": "web_page", "url": url,
                "error": "not a deps.dev host",
                "error_code": "platform_unsupported"}
    segments = [urllib.parse.unquote(part) for part in parsed.path.split("/") if part]
    system = segments[0].lower() if segments else ""
    if system not in _DEPSDEV_SYSTEMS or len(segments) < 3:
        return {"ok": False, "kind": "web_page", "url": url,
                "error": "not a deps.dev package version URL",
                "error_code": "platform_unsupported"}
    version = segments[-1]
    name = "/".join(segments[1:-1])
    if system == "maven":
        # deps.dev names Maven packages by "group:artifact"; the site URL uses
        # a slash between them.
        name = ":".join(segments[1:-1])
    base = (f"https://api.{_DEPSDEV_HOST}/v3/systems/"
            f"{urllib.parse.quote(system, safe='')}/packages/"
            f"{urllib.parse.quote(name, safe='')}/versions/"
            f"{urllib.parse.quote(version, safe='')}")
    deadline = time.monotonic() + max(1.0, float(timeout))

    def remaining() -> float:
        return max(0.0, deadline - time.monotonic())

    def left() -> float | None:
        value = remaining()
        return value if value >= 0.5 else None

    budget = left()
    if budget is None:
        return {"ok": False, "kind": "web_page", "url": url,
                "error": "read budget exhausted before the deps.dev request",
                "error_code": "platform_failed"}
    try:
        data = _get_json(base, budget)
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return {"ok": False, "kind": "web_page", "url": url,
                    "error": f"{system} {name} {version} not found",
                    "error_code": "platform_empty"}
        raise

    header = [
        f"[package] {system} {name} {version}",
        f"published: {data.get('publishedAt') or '-'}",
        f"default version: {data.get('isDefault')} | deprecated: {data.get('isDeprecated')}"
        + (f" ({data.get('deprecatedReason')})" if data.get("deprecatedReason") else ""),
        f"licenses: {', '.join(str(item) for item in data.get('licenses') or []) or '-'}",
    ]
    advisories = data.get("advisoryKeys") or []
    if advisories:
        ids = [str((item or {}).get("id") or "") for item in advisories][:8]
        header.append(f"advisories: {len(advisories)} ({', '.join(i for i in ids if i)})")
    else:
        header.append("advisories: 0")
    links = [
        f"{item.get('label')}={item.get('url')}"
        for item in (data.get("links") or [])[:6] if isinstance(item, dict)
    ]
    if links:
        header.append("links: " + " | ".join(links))

    dependency_lines: list[str] = []
    budget = left()
    if budget is not None:
        try:
            graph = _get_json(f"{base}:dependencies", budget)
        except Exception:  # noqa: BLE001 - the graph is optional context
            graph = {}
        nodes = (graph.get("nodes") or []) if isinstance(graph, dict) else []
        dependencies = [
            node for node in nodes
            if isinstance(node, dict) and node.get("relation") != "SELF"
        ]
        if dependencies:
            dependency_lines.append(f"[dependencies] {len(dependencies)} direct/transitive nodes")
            for node in dependencies[:30]:
                key = node.get("versionKey") or {}
                dependency_lines.append(
                    f"- {key.get('name')} {key.get('version')} ({node.get('relation') or '-'})"
                )

    content = "\n".join(header)
    if dependency_lines:
        content += "\n\n" + "\n".join(dependency_lines)
    return _result(url, "depsdev_api", f"{system} {name} {version}", content)


def _lobsters(url: str, timeout: float) -> dict[str, Any]:
    """Read a Lobsters story and its threaded comments in one request."""

    def username(value: Any) -> str:
        if isinstance(value, dict):
            return str(value.get("username") or "")
        return str(value or "")

    match = re.search(r"/s/([A-Za-z0-9]+)", urllib.parse.urlsplit(url).path)
    if not match:
        return {"ok": False, "kind": "web_page", "url": url,
                "error": "not a Lobsters story URL",
                "error_code": "platform_unsupported"}
    data = _get_json(f"https://{_LOBSTERS_HOST}/s/{match.group(1)}.json", timeout)
    header = [
        f"[story] {data.get('title') or ''}",
        f"url: {data.get('url') or '(text post)'}",
        f"score: {data.get('score', 0)} | comments: {data.get('comment_count', 0)}",
        f"tags: {', '.join(str(tag) for tag in data.get('tags') or []) or '-'}",
        f"submitted: {username(data.get('submitter_user')) or '-'} "
        f"{data.get('created_at') or ''}",
    ]
    description = _text(data.get("description_plain"))
    if description:
        header.append("")
        header.append(description[:4000])

    comments = data.get("comments") or []
    lines: list[str] = []
    shown = 0
    for comment in comments:
        if shown >= 40:
            break
        depth = int(comment.get("depth") or 0)
        if depth > 6 or comment.get("is_deleted") or comment.get("is_moderated"):
            continue
        text = _text(comment.get("comment_plain"))
        if not text:
            continue
        who = username(comment.get("commenting_user"))
        when = str(comment.get("created_at") or "")[:16]
        lines.append(f"[d{depth}] {who} {when}\n{text}"[:1200])
        shown += 1
    content = "\n".join(header)
    if lines:
        content += "\n\n[comments]\n" + "\n\n".join(lines)
    return _result(url, "lobsters_api", str(data.get("title") or ""), content,
                   comments=shown)


def _get_text(url: str, timeout: float, max_bytes: int = 400_000) -> str:
    request = urllib.request.Request(url, headers=_UA)
    with urllib.request.urlopen(request, timeout=max(1, int(timeout))) as response:
        return response.read(max_bytes).decode("utf-8", errors="replace")


def _openalex_abstract(index: Any, limit: int = 4000) -> str:
    if not isinstance(index, dict):
        return ""
    positions: dict[int, str] = {}
    for word, places in index.items():
        if not isinstance(places, list):
            continue
        for place in places:
            if isinstance(place, int):
                positions[place] = str(word)
    if not positions:
        return ""
    text = " ".join(positions[key] for key in sorted(positions))
    return text[:limit]


def _date_parts(value: Any) -> str:
    try:
        parts = ((value or {}).get("date-parts") or [[]])[0]
    except AttributeError:
        return ""
    return "-".join(str(part) for part in parts if part is not None)


def _doi_from_url(url: str) -> str:
    parsed = urllib.parse.urlsplit(url)
    if (parsed.hostname or "").lower() not in _DOI_HOSTS:
        return ""
    path = urllib.parse.unquote(parsed.path or "").lstrip("/")
    return path if path.lower().startswith("10.") else ""


def _unpaywall(doi: str, timeout: float) -> str:
    """Open-access location, only when the operator configured an email."""

    email = os.getenv("UNPAYWALL_EMAIL", "").strip()
    if not email:
        return "[open access] not checked (UNPAYWALL_EMAIL is unset)"
    try:
        data = _get_json(
            "https://api.unpaywall.org/v2/"
            + urllib.parse.quote(doi, safe="/")
            + "?email=" + urllib.parse.quote(email),
            timeout,
        )
    except Exception as exc:  # noqa: BLE001 - optional enrichment
        return f"[open access] lookup failed ({type(exc).__name__})"
    location = data.get("best_oa_location") or {}
    pdf = location.get("url_for_pdf") or ""
    landing = location.get("url") or ""
    lines = [f"[open access] is_oa={data.get('is_oa')} status={data.get('oa_status') or '-'}"]
    if landing:
        lines.append(f"  landing: {landing}")
    if pdf:
        lines.append(f"  pdf: {pdf} (not read)")
    return "\n".join(lines)


def _doi_reader(url: str, timeout: float) -> dict[str, Any]:
    """Crossref (or DataCite) metadata for a DOI, clearly not the full text."""

    doi = _doi_from_url(url)
    if not doi:
        return {"ok": False, "kind": "web_page", "url": url,
                "error": "not a DOI URL",
                "error_code": "platform_unsupported"}
    deadline = time.monotonic() + max(1.0, float(timeout))

    def remaining() -> float:
        return max(0.0, deadline - time.monotonic())

    method = "crossref_api"
    try:
        message = _get_json(
            "https://api.crossref.org/works/" + urllib.parse.quote(doi, safe="/"),
            max(1.0, remaining()),
        ).get("message") or {}
    except urllib.error.HTTPError as exc:
        if exc.code != 404:
            raise
        method = "datacite_api"
        record = _get_json(
            "https://api.datacite.org/dois/" + urllib.parse.quote(doi, safe="/"),
            max(1.0, remaining()),
        )
        attrs = (record.get("data") or {}).get("attributes") or {}
        title = ((attrs.get("titles") or [{}])[0] or {}).get("title") or ""
        authors = "; ".join(
            str((creator or {}).get("name") or "") for creator in attrs.get("creators") or []
        )
        description = next(
            (
                item.get("description") or ""
                for item in attrs.get("descriptions") or []
                if str(item.get("descriptionType") or "").lower() == "abstract"
            ),
            "",
        )
        lines = [
            f"[work] {title}",
            f"[identifiers] doi={doi} source=datacite",
            f"[authors] {authors or '-'}",
            f"[published] {attrs.get('publicationYear') or '-'}",
            f"[publisher] {attrs.get('publisher') or '-'}",
            f"[type] {(attrs.get('types') or {}).get('resourceTypeGeneral') or '-'}",
            f"[abstract] {' '.join(_text(description).split())[:4000] or '-'}"
            " (abstract only; the full text was not read)",
            "[full text] not read by this adapter",
        ]
        if attrs.get("url"):
            lines.insert(6, f"[links] landing={attrs['url']}")
        return _result(url, method, title, "\n".join(lines))

    title = str((message.get("title") or [""])[0] or "")
    authors = "; ".join(
        " ".join(part for part in (author.get("given"), author.get("family")) if part)
        or str(author.get("name") or "")
        for author in message.get("author") or []
    )
    published = (
        _date_parts(message.get("published-print"))
        or _date_parts(message.get("published-online"))
        or _date_parts(message.get("issued"))
        or _date_parts(message.get("created"))
    )
    venue = str((message.get("container-title") or [""])[0] or "")
    licenses = ", ".join(
        str(item.get("URL") or "") for item in message.get("license") or [] if item
    )
    landing = ((message.get("resource") or {}).get("primary") or {}).get("URL") or ""
    lines = [
        f"[work] {title}",
        f"[identifiers] doi={message.get('DOI') or doi} source=crossref",
        f"[authors] {authors or '-'}",
        f"[published] {published or '-'}",
        f"[venue] {venue or '-'}",
        f"[type] {message.get('type') or '-'}",
        f"[license] {licenses or '-'}",
        f"[links] publisher={landing or '-'}",
        "[abstract] "
        + (" ".join(_text(message.get("abstract")).split())[:4000] or "-")
        + " (abstract only; the full text was not read)",
        _unpaywall(doi, max(1.0, remaining())),
        "[full text] not read by this adapter",
    ]
    return _result(url, method, title, "\n".join(lines))


def _openalex(url: str, timeout: float) -> dict[str, Any]:
    parsed = urllib.parse.urlsplit(url)
    match = re.search(r"/(?:works/)?(W\d+)", parsed.path or "")
    if not match:
        return {"ok": False, "kind": "web_page", "url": url,
                "error": "not an OpenAlex work URL",
                "error_code": "platform_unsupported"}
    data = _get_json(f"https://api.openalex.org/works/{match.group(1)}", timeout)
    title = str(data.get("title") or "")
    authors = "; ".join(
        str(((item.get("author") or {}).get("display_name")) or "")
        for item in data.get("authorships") or []
    )
    venue = str(
        ((data.get("primary_location") or {}).get("source") or {}).get("display_name") or ""
    )
    references = data.get("referenced_works") or []
    reference_ids = [
        str(item).rsplit("/", 1)[-1] for item in references[:10] if item
    ]
    access = data.get("open_access") or {}
    lines = [
        f"[work] {title}",
        f"[identifiers] openalex={data.get('id') or match.group(1)} doi={data.get('doi') or '-'}",
        f"[authors] {authors or '-'}",
        f"[published] {data.get('publication_date') or data.get('publication_year') or '-'}",
        f"[venue] {venue or '-'}",
        f"[type] {data.get('type') or '-'}",
        f"[citations] cited_by={data.get('cited_by_count', 0)}",
        f"[references] {len(references)} works"
        + (f" (first: {', '.join(reference_ids)})" if reference_ids else ""),
        "[abstract] " + (_openalex_abstract(data.get("abstract_inverted_index")) or "-")
        + " (abstract only; the full text was not read)",
        f"[open access] is_oa={access.get('is_oa')} url={access.get('oa_url') or '-'} (not read)",
        "[full text] not read by this adapter",
    ]
    return _result(url, "openalex_api", title, "\n".join(lines))


def _arxiv(url: str, timeout: float) -> dict[str, Any]:
    path = urllib.parse.urlsplit(url).path or ""
    match = re.search(r"/(?:abs|pdf)/(.+?)(?:\.pdf)?/?$", path)
    if not match:
        return {"ok": False, "kind": "web_page", "url": url,
                "error": "not an arXiv abs/pdf URL",
                "error_code": "platform_unsupported"}
    identifier = match.group(1)
    text = _get_text(
        "https://export.arxiv.org/api/query?"
        + urllib.parse.urlencode({"id_list": identifier}),
        timeout,
    )
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        return {"ok": False, "kind": "web_page", "url": url,
                "error": "arXiv returned malformed Atom",
                "error_code": "platform_failed"}
    ns = {"a": "http://www.w3.org/2005/Atom"}
    entry = root.find("a:entry", ns)
    if entry is None:
        return {"ok": False, "kind": "web_page", "url": url,
                "error": "arXiv entry not found",
                "error_code": "platform_empty"}
    title = " ".join((entry.findtext("a:title", default="", namespaces=ns) or "").split())
    summary = " ".join((entry.findtext("a:summary", default="", namespaces=ns) or "").split())
    authors = "; ".join(
        (author.findtext("a:name", default="", namespaces=ns) or "")
        for author in entry.findall("a:author", ns)
    )
    published = entry.findtext("a:published", default="", namespaces=ns) or ""
    updated = entry.findtext("a:updated", default="", namespaces=ns) or ""
    pdf = ""
    for link in entry.findall("a:link", ns):
        if link.get("title") == "pdf":
            pdf = link.get("href") or ""
    lines = [
        f"[work] {title}",
        f"[identifiers] arxiv={identifier}",
        f"[authors] {authors or '-'}",
        f"[published] {published[:10] or '-'} | updated={updated[:10] or '-'}",
        "[abstract] " + (summary[:4000] or "-")
        + " (abstract only; the PDF was not parsed)",
        f"[links] pdf={pdf or '-'} (not read)",
        "[full text] not read by this adapter",
    ]
    return _result(url, "arxiv_api", title, "\n".join(lines))


def _zenodo(url: str, timeout: float) -> dict[str, Any]:
    match = re.search(r"/records?/(\d+)", urllib.parse.urlsplit(url).path or "")
    if not match:
        return {"ok": False, "kind": "web_page", "url": url,
                "error": "not a Zenodo record URL",
                "error_code": "platform_unsupported"}
    data = _get_json(f"https://zenodo.org/api/records/{match.group(1)}", timeout)
    meta = data.get("metadata") or {}
    title = str(meta.get("title") or "")
    creators = "; ".join(
        str((item or {}).get("name") or "") for item in meta.get("creators") or []
    )
    description = " ".join(_text(meta.get("description")).split())[:4000]
    files = data.get("files") or []
    file_lines = [
        f"  - {item.get('key')} ({item.get('size', 0)} bytes, not downloaded)"
        for item in files[:10]
    ]
    lines = [
        f"[record] {title}",
        f"[identifiers] doi={meta.get('doi') or data.get('doi') or '-'} zenodo={match.group(1)}",
        f"[authors] {creators or '-'}",
        f"[published] {meta.get('publication_date') or '-'}",
        f"[type] {(meta.get('resource_type') or {}).get('title') or '-'}",
        f"[license] {(meta.get('license') or {}).get('id') or '-'}",
        f"[description] {description or '-'}",
        f"[files] {len(files)} total",
        *file_lines,
        "[full text] files were listed, not downloaded or parsed",
    ]
    return _result(url, "zenodo_api", title, "\n".join(lines))


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
    "depsdev": _depsdev,
    "lobsters": _lobsters,
    "huggingface": _huggingface,
    "doi": _doi_reader,
    "openalex": _openalex,
    "arxiv": _arxiv,
    "zenodo": _zenodo,
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
