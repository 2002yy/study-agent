"""Read a page's text through the locally paired browse extension.

The regular reader handles static HTML. Some pages need the browser that is
already open and logged in: JS-only shells, consent interstitials, and
community pages that return an empty body over plain HTTP. This module is the
single browse read path; it never bypasses a login wall or a challenge.

Failures are reported, not swallowed: the caller needs to tell a login wall
from a timeout, a challenge, or a page that simply had no body.
"""

from __future__ import annotations

import json
import time
from typing import Any
from urllib.parse import urlsplit

from src.web.browse_search import _execute
from src.web.tool_evidence import _public_url

#: Below this many characters a successful static read is treated as a shell
#: (navigation text, a cookie banner) rather than the page body.
SHORT_READ_CHARS = 300

_READ_SCRIPT = r"""
await page.goto(READ_URL, {waitUntil: 'domcontentloaded', timeout: TIMEOUT_MS});
try { await page.waitForLoadState('networkidle', {timeout: WAIT_FOR_MS}); } catch (error) {}
return await page.evaluate((limit) => {
  const drop = 'script,style,noscript,svg,nav,header,footer,aside,form,[aria-hidden="true"]';
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
  return {
    title: document.title || '',
    url: location.href,
    login,
    text: text.replace(/\n{3,}/g, '\n\n').trim().slice(0, limit),
  };
}, MAX_CHARS);
"""

_ERROR_CODES = {
    "browse:human_action_required": ("browse_challenge", "the page asked for a human check"),
    "browse:timeout": ("browse_timeout", "the browser did not finish in the time budget"),
    "browse:cli_unavailable": ("browse_unavailable", "the browse CLI is not installed"),
    "browse:invalid_response": ("browse_failed", "the browser returned an unexpected response"),
    "browse:execution_failed": ("browse_failed", "the browser could not open the page"),
}


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


def _payload(value: dict[str, Any], final: str, limit: int) -> dict[str, Any]:
    text = str(value.get("text") or "").strip()
    if value.get("login") and len(text) < SHORT_READ_CHARS:
        return _failure(final, "browse_login_wall", "the page requires a login")
    if len(text) < 80:
        return _failure(final, "browse_no_content", "the page had no usable body")
    return {
        "ok": True,
        "kind": "web_page",
        "url": final,
        "method": "browse",
        "content": text[:limit],
        "title": str(value.get("title") or ""),
        "chars": len(text[:limit]),
    }


def read_browse(
    url: str, *, max_chars: int = 6000, timeout: float = 10.0
) -> dict[str, Any]:
    """Read one page in the paired browser; always returns a result object."""

    target = _public_url(url)
    if not target:
        return _failure(str(url or ""), "browse_unsafe_url", "not a public HTTP(S) URL")
    if timeout < 1:
        return _failure(target, "browse_no_budget", "no time left for a browser read")
    limit = max(500, min(int(max_chars), 20_000))
    deadline = time.monotonic() + float(timeout)
    attempt = target
    for _ in range(2):
        remaining = deadline - time.monotonic()
        if remaining < 0.5:
            return _failure(target, "browse_no_budget", "no time left for a browser read")
        script = (
            _READ_SCRIPT.replace("READ_URL", json.dumps(attempt))
            .replace("MAX_CHARS", str(limit))
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
        return _payload(value, final, limit)
    return _failure(target, "browse_failed", "the site kept returning an interstitial")
