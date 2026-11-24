"""Read a page's text through the locally paired browse extension.

The regular reader handles static HTML. Some pages need the browser that is
already open and logged in: JS-only shells, consent interstitials, and
community pages that return an empty body over plain HTTP. This module is the
single browse read path; it never bypasses a login wall or a challenge.

Discussion is optional and comes from the same navigation: the model asks for
it only when the thread matters, and it always reports how much was read.
"""

from __future__ import annotations

import json
import re
import time
from typing import Any
from urllib.parse import urlsplit

from src.web.browse_search import _execute
from src.web.tool_evidence import _public_url

#: Below this many characters a successful static read is treated as a shell
#: (navigation text, a cookie banner) rather than the page body.
SHORT_READ_CHARS = 300

#: One broad list for every site. Wrappers are dropped below by the leaf rule,
#: so a site needs its own selector only when this list misses it entirely.
_DISCUSSION_SELECTOR = (
    '[role="comment"],[itemprop="comment"],shreddit-comment,'
    '[class*="comment" i],[class*="reply" i],[class*="answer" i],[class~="cell"]'
)

#: Only where the generic pool lands on headers or wrappers. One selector per
#: site, not a separate reader: everything else (budget, failures, scope,
#: pagination, author/time) stays shared.
_DISCUSSION_HINTS = {
    "miyoushe.com": ".reply-card__content",
}


def _discussion_selector(url: str) -> str:
    host = (urlsplit(url).hostname or "").lower()
    for suffix, selector in _DISCUSSION_HINTS.items():
        if host == suffix or host.endswith("." + suffix):
            return selector
    return _DISCUSSION_SELECTOR

_ERROR_CODES = {
    "browse:human_action_required": ("browse_challenge", "the page asked for a human check"),
    "browse:timeout": ("browse_timeout", "the browser did not finish in the time budget"),
    "browse:cli_unavailable": ("browse_unavailable", "the browse CLI is not installed"),
    "browse:invalid_response": ("browse_failed", "the browser returned an unexpected response"),
    "browse:execution_failed": ("browse_failed", "the browser could not open the page"),
}

_READ_SCRIPT = r"""
await page.goto(READ_URL, {waitUntil: 'domcontentloaded', timeout: TIMEOUT_MS});
try { await page.waitForLoadState('networkidle', {timeout: WAIT_FOR_MS}); } catch (error) {}
return await page.evaluate((limit) => {
  const drop = 'script,style,noscript,svg,nav,header,footer,aside,form,[aria-hidden="true"],' +
    '[role="banner"],[role="navigation"],[role="contentinfo"],' +
    '[class*="breadcrumb" i],[class*="cookie" i],[class*="advert" i],[id*="advert" i]';
  const scope = document.querySelector('article, main, [role="main"]') || document.body;
  let text = '';
  if (scope) {
    const copy = scope.cloneNode(true);
    copy.querySelectorAll(drop).forEach((node) => node.remove());
    text = copy.innerText || '';
  }
  const login = Array.from(document.querySelectorAll('input[type="password"]')).some(
    (element) => element.offsetWidth || element.offsetHeight || element.getClientRects().length
  );
  const result = {
    title: document.title || '',
    url: location.href,
    login,
    // Collapse indentation before the cap, or the limit is spent on spaces.
    text: text.replace(/[ \t\u00a0]+/g, ' ').trim().slice(0, limit),
    author: (document.querySelector('meta[name="author"]') || {}).content || '',
    published_at: (document.querySelector('meta[property="article:published_time"]') || {}).content || '',
    discussion: [],
    next_url: '',
  };
  if (INCLUDE_DISCUSSION) {
    const sel = DISCUSSION_SELECTOR;
    const nodes = Array.from(document.querySelectorAll(sel));
    const lengths = new Map();
    for (const node of nodes) {
      lengths.set(node, ((node.innerText || '').replace(/\s+/g, ' ').trim()).length);
    }
    const picked = [];
    const bodyText = (scope ? (scope.innerText || '') : '')
      .replace(/\s+/g, ' ').trim();
    for (const node of nodes) {
      const length = lengths.get(node) || 0;
      if (length < 5 || length > 2000) continue;
      // Keep the leaves: a wrapper whose child carries most of its text is the
      // thread container, not one comment.
      const nested = Array.from(node.querySelectorAll(sel))
        .some((child) => (lengths.get(child) || 0) >= length * 0.6);
      if (nested) continue;
      if (node.closest('[class*="pagination" i],nav,[role="navigation"],[class*="page_" i]')) continue;
      const raw = (node.innerText || '').replace(/\s+/g, ' ').trim();
      // The article itself and counters such as "1 2 ❮ ❯" are not replies.
      if (length >= 200 && bodyText.includes(raw.slice(0, 60))) continue;
      if (/^[\d\s•·:：/|]+$/.test(raw)) continue;
      const metaScope = node.closest(
        '[class*="reply-card" i],[class*="comment" i],[class*="reply" i]'
      ) || node.parentElement || node;
      const authorNode = metaScope.querySelector(
        '[rel="author"],[class*="author" i],[class*="user" i],[class*="name" i],a[href*="/member"],a[href*="/u/"],a[href*="/space"]'
      );
      const timeNode = metaScope.querySelector('time,[datetime],[class*="time" i],[class*="date" i]');
      let depth = 0;
      let parent = node.parentElement;
      while (parent && parent !== document.body && depth < 6) {
        if (parent.matches(sel)) depth += 1;
        parent = parent.parentElement;
      }
      picked.push({
        text: raw.slice(0, 1200),
        author: authorNode ? (authorNode.innerText || '').trim().slice(0, 80) : '',
        time: timeNode ? (timeNode.getAttribute('datetime') || timeNode.innerText || '').trim().slice(0, 60) : '',
        depth,
      });
      if (picked.length >= DISC_LIMIT) break;
    }
    result.discussion = picked;
    const pageNumber = (href) => {
      const match = String(href).match(/[?&](?:p|page)=(\d+)/);
      return match ? Number(match[1]) : 0;
    };
    const current = pageNumber(location.href) || 1;
    const next = Array.from(document.querySelectorAll('a[href]'))
      .map((anchor) => anchor.href)
      .filter((href) => href.startsWith(location.origin) && pageNumber(href) > current)
      .sort((left, right) => pageNumber(left) - pageNumber(right))[0] || '';
    result.next_url = next;
  }
  return result;
}, MAX_CHARS);
"""


def _tidy(text: str) -> str:
    """Drop obvious line-level noise while keeping paragraph structure."""

    lines: list[str] = []
    previous = ""
    blanks = 0
    for raw in str(text or "").replace("\r\n", "\n").split("\n"):
        line = re.sub(r"[ \t\u00a0]+", " ", raw).strip()
        if not line:
            blanks += 1
            if blanks == 1 and lines:
                lines.append("")
            continue
        blanks = 0
        if line == previous:
            # Repeated chrome (site name, breadcrumb) is one line, not ten.
            continue
        lines.append(line)
        previous = line
    while lines and lines[-1] == "":
        lines.pop()
    return "\n".join(lines)


_UI_NOISE = re.compile(
    r"^(?:\d+\s*(?:条回复|comments?)|[\d\s•·:：/|‹›«»❮❯<>-]+)$"
    r"|\d+\s*条回复\s*[•·]|只看楼主|排序\s*[:：]|看帖是喜欢",
    re.I,
)


def _discussion(value: dict[str, Any], max_comments: int) -> tuple[list[dict[str, Any]], str]:
    raw_items = value.get("discussion")
    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    if isinstance(raw_items, list):
        for item in raw_items:
            if not isinstance(item, dict):
                continue
            author = str(item.get("author") or "").strip()[:80]
            when = str(item.get("time") or "").strip()[:60]
            text = _tidy(str(item.get("text") or ""))
            # The caller usually wants the reply, not its header.
            if author and text.startswith(author):
                text = text[len(author):].lstrip(" :：·-|")
            if when and when in text[:80]:
                index = text.find(when)
                text = text[index + len(when):].lstrip(" :：·-|")
            text = text[:800]
            if len(text) < 2 or _UI_NOISE.search(text):
                continue
            key = text[:80]
            if key in seen:
                continue
            seen.add(key)
            items.append({
                "text": text,
                "author": author,
                "time": when,
                "depth": int(item.get("depth") or 0) if isinstance(item.get("depth"), int) else 0,
            })
            if max_comments and len(items) >= max_comments:
                break
    next_url = _public_url(value.get("next_url")) if isinstance(value.get("next_url"), str) else ""
    return items, next_url


def _failure(url: str, code: str, message: str) -> dict[str, Any]:
    return {
        "ok": False,
        "kind": "web_page",
        "url": url,
        "method": "browse",
        "error": message,
        "error_code": code,
    }


def _interstitial_target(url: str) -> str:
    """The real target carried by a site's own ad interstitial, if any."""

    if "adpage_insert" not in url:
        return ""
    inner = urlsplit(url).query
    if not inner.startswith(("http://", "https://")) or "adpage_insert" in inner:
        return ""
    return _public_url(inner)


def _payload(
    value: dict[str, Any], final: str, limit: int,
    *, include_discussion: bool, max_comments: int,
) -> dict[str, Any]:
    text = _tidy(value.get("text"))[:limit]
    if value.get("login") and len(text) < SHORT_READ_CHARS:
        return _failure(final, "browse_login_wall", "the page requires a login")
    if len(text) < 80:
        return _failure(final, "browse_no_content", "the page had no usable body")
    payload = {
        "ok": True,
        "kind": "web_page",
        "url": final,
        "method": "browse",
        "content": text,
        "title": str(value.get("title") or ""),
        "chars": len(text),
        "author": str(value.get("author") or "")[:120],
        "published_at": str(value.get("published_at") or "")[:80],
    }
    if include_discussion:
        items, next_url = _discussion(value, max_comments)
        payload["discussion"] = items
        payload["discussion_scope"] = {
            "page": 1,
            "comments_read": len(items),
            # The first page is not the whole thread; say so instead of
            # presenting a slice as a complete discussion.
            "may_be_partial": True,
        }
        payload["next_url"] = next_url
    return payload


def read_browse(
    url: str, *, max_chars: int = 6000, timeout: float = 10.0,
    include_discussion: bool = False, max_comments: int = 0,
) -> dict[str, Any]:
    """Read one page in the paired browser; always returns a result object."""

    target = _public_url(url)
    if not target:
        return _failure(str(url or ""), "browse_unsafe_url", "not a public HTTP(S) URL")
    if timeout < 1:
        return _failure(target, "browse_no_budget", "no time left for a browser read")
    limit = max(500, min(int(max_chars), 20_000))
    wanted = max(0, min(int(max_comments), 50)) if include_discussion else 0
    deadline = time.monotonic() + float(timeout)
    attempt = target
    for _ in range(2):
        remaining = deadline - time.monotonic()
        if remaining < 0.5:
            return _failure(target, "browse_no_budget", "no time left for a browser read")
        script = (
            _READ_SCRIPT.replace("READ_URL", json.dumps(attempt))
            .replace("MAX_CHARS", str(limit))
            .replace("INCLUDE_DISCUSSION", "true" if include_discussion else "false")
            .replace("DISCUSSION_SELECTOR", json.dumps(_discussion_selector(attempt)))
            .replace("DISC_LIMIT", str(max(30, wanted * 3)))
        )
        envelope, error = _execute(script, "", remaining)
        if envelope is None:
            code, message = _ERROR_CODES.get(error, ("browse_failed", error or "browse failed"))
            return _failure(attempt, code, message)
        value = envelope.get("value")
        if not isinstance(value, dict):
            return _failure(attempt, "browse_failed", "the browser returned an unexpected response")
        raw_final = value.get("url")
        final = _public_url(raw_final) if isinstance(raw_final, str) else ""
        if not final:
            # Never publish the requested URL as if it were the page that was
            # read: the citation must match the page the browser landed on.
            return _failure(
                attempt, "browse_invalid_final_url",
                "the browser did not report a public final URL",
            )
        follow = _interstitial_target(final)
        if follow and follow != attempt:
            # NGA and similar sites serve their own ad page first; the thread
            # is the URL that page carries. One hop, only within the site.
            attempt = follow
            continue
        return _payload(
            value, final, limit,
            include_discussion=include_discussion, max_comments=wanted,
        )
    return _failure(target, "browse_failed", "the site kept returning an interstitial")
