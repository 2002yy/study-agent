"""Read a page's text through the locally paired browse extension.

The regular reader handles static HTML. Some pages need the browser that is
already open and logged in: JS-only shells, consent interstitials, and
community pages that return an empty body over plain HTTP. This module is the
single browse read path; it never bypasses a login wall or a challenge.
"""

from __future__ import annotations

import json
from typing import Any

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


def read_browse(
    url: str, *, max_chars: int = 6000, timeout: float = 10.0
) -> dict[str, Any] | None:
    """Return the page as text, or ``None`` when it cannot be read honestly."""

    target = _public_url(url)
    if not target:
        return None
    limit = max(500, min(int(max_chars), 20_000))
    script = (
        _READ_SCRIPT.replace("READ_URL", json.dumps(target))
        .replace("MAX_CHARS", str(limit))
    )
    envelope, _error = _execute(script, "", max(2.0, float(timeout)))
    if envelope is None:
        return None
    value = envelope.get("value")
    if not isinstance(value, dict):
        return None
    text = str(value.get("text") or "").strip()
    if value.get("login") and len(text) < SHORT_READ_CHARS:
        # A password field with no body is a login wall, not an article.
        return None
    if len(text) < 80:
        return None
    final = _public_url(value.get("url") or target) or target
    return {
        "ok": True,
        "kind": "web_page",
        "url": final,
        "method": "browse",
        "content": text[:limit],
        "title": str(value.get("title") or ""),
        "chars": len(text[:limit]),
    }
