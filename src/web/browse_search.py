"""Browser-backed search through the locally paired browse extension.

Two entry points share one execution path:

* :func:`search_browse` - Google, the default discovery engine;
* :func:`search_browse_at` - any site that has a search URL (the site pool).

Both treat the page as untrusted data. Only a public URL is kept, and a captcha
or login wall stops that request instead of being worked around.
"""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
from typing import Any
from urllib.parse import urlencode

from src.web.tool_evidence import _public_url

_GOOGLE_SCRIPT = """
await page.goto(SEARCH_URL, {waitUntil: 'domcontentloaded', timeout: TIMEOUT_MS});
await snapshot();
if (!page.url().startsWith('https://www.google.com/search?')) {
  return {blocked: true, results: []};
}
return await page.evaluate(() => ({
  blocked: Boolean(document.querySelector('form[action*="sorry"], #captcha-form')),
  results: Array.from(document.querySelectorAll('a:has(h3)')).slice(0, 24).map(a => ({
    title: a.querySelector('h3').innerText,
    url: a.href,
    snippet: ''
  }))
}));
"""

_GENERIC_SCRIPT = """
try {
  await page.goto(SEARCH_URL, {waitUntil: 'domcontentloaded', timeout: NAV_TIMEOUT_MS});
} catch (error) {
  // A heavy community page can miss domcontentloaded; use whatever rendered.
}
try { await page.waitForTimeout(800); } catch (error) {}
await snapshot();
return await page.evaluate(() => {
  const visible = (element) => Boolean(
    element && (element.offsetWidth || element.offsetHeight || element.getClientRects().length)
  );
  const challenge = Boolean(document.querySelector(
    'form[action*="sorry"], #captcha-form, iframe[src*="captcha"], .g-recaptcha, [data-testid="captcha"]'
  ));
  const seen = new Set();
  const results = [];
  const searchHost = location.hostname;
  const searchPath = location.pathname;
  const navPath = /^[/](?:login|search|feed|portal[.]php|mobile|project-square|users?|settings|preferences)(?:[/]|$)/i;
  for (const anchor of Array.from(document.querySelectorAll(
    'main a[href], [role="main"] a[href], article a[href], li a[href], a[href]'
  ))) {
    const heading = anchor.querySelector('h3');
    const title = ((heading ? heading.innerText : '') || anchor.innerText || '').trim();
    const url = anchor.href;
    if (!url.startsWith('http') || title.length < 12 || seen.has(url)) continue;
    let parsed;
    try { parsed = new URL(url); } catch (error) { continue; }
    if (parsed.hostname === searchHost) {
      // Navigation on the search site itself is not a result.
      if (parsed.pathname === '/' || parsed.pathname === searchPath) continue;
      if (navPath.test(parsed.pathname)) continue;
    }
    if (url === location.href) continue;
    seen.add(url);
    results.push({title: title.slice(0, 300), url, snippet: ''});
    if (results.length >= 40) break;
  }
  // A header login form does not mean the page is a login wall; only flag it
  // when the search page produced nothing and a login control is visible.
  const login = results.length === 0 && (
    Array.from(document.querySelectorAll('input[type="password"]')).some(visible)
    || Array.from(document.querySelectorAll('form[action*="login"]')).some(visible)
    || /\\/login(\\b|\\/|\\?)/.test(location.pathname)
  );
  return {blocked: challenge, login, url: location.href, results};
});
"""


def _execute(script: str, url: str, timeout: float) -> tuple[dict[str, Any] | None, str]:
    executable = shutil.which("browse")
    if not executable:
        return None, "browse:cli_unavailable"
    # Only the URL is parameterized. Source text is never executable code.
    body = (
        script.replace("SEARCH_URL", json.dumps(url))
        .replace("NAV_TIMEOUT_MS", str(max(1500, int(timeout * 600))))
        .replace("TIMEOUT_MS", str(max(1, int(timeout * 1000))))
    )
    try:
        with tempfile.TemporaryDirectory(prefix="study-agent-browse-") as folder:
            path = Path(folder) / "search.js"
            path.write_text(body, encoding="utf-8")
            completed = subprocess.run(
                [executable, "execute", "--rm", "--json", "--timeout-ms",
                 str(max(1, int(timeout * 1000))), "--file", str(path)],
                capture_output=True, text=True, encoding="utf-8", timeout=timeout + 1,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                check=False,
            )
        if completed.returncode:
            return None, "browse:execution_failed"
        envelope = json.loads(completed.stdout)
        if envelope.get("isError") or not isinstance(envelope.get("value"), dict):
            return None, "browse:execution_failed"
        return envelope, ""
    except subprocess.TimeoutExpired:
        return None, "browse:timeout"
    except (OSError, ValueError, TypeError):
        return None, "browse:invalid_response"


def search_browse(query: str, limit: int, timeout: float) -> tuple[list[dict[str, str]], str]:
    url = "https://www.google.com/search?" + urlencode({"q": query})
    envelope, error = _execute(_GOOGLE_SCRIPT, url, timeout)
    if envelope is None:
        return [], error
    challenge = (envelope.get("aftermath") or {}).get("challenge")
    if challenge and challenge.get("recommendation") in {"handoff", "stop"}:
        return [], "browse:human_action_required"
    value = envelope["value"]
    if value.get("blocked"):
        return [], "browse:human_action_required"
    rows = _public_rows(value.get("results"), limit, source="Google via browse")
    return rows[:limit], "" if rows else "browse:no_results"


def search_browse_at(
    url: str, limit: int, timeout: float, *, source: str = "site via browse"
) -> tuple[list[dict[str, str]], str, dict[str, Any]]:
    """Search one site and report what actually happened on its page."""

    started = time.monotonic()
    meta: dict[str, Any] = {"status": "unknown", "seconds": 0.0, "url": url}
    envelope, error = _execute(_GENERIC_SCRIPT, url, timeout)
    meta["seconds"] = round(time.monotonic() - started, 2)
    if envelope is None:
        meta["status"] = error or "browse:execution_failed"
        return [], error, meta
    challenge = (envelope.get("aftermath") or {}).get("challenge")
    value = envelope["value"]
    meta["final_url"] = str(value.get("url") or "")
    if challenge and challenge.get("recommendation") in {"handoff", "stop"}:
        meta["status"] = "browse:human_action_required"
        return [], "browse:human_action_required", meta
    if value.get("blocked"):
        meta["status"] = "browse:human_action_required"
        return [], "browse:human_action_required", meta
    if value.get("login"):
        meta["status"] = "browse:login_required"
        return [], "browse:login_required", meta
    rows = _public_rows(value.get("results"), limit, source=source)
    meta["status"] = "ok" if rows else "browse:no_results"
    return rows[:limit], "" if rows else "browse:no_results", meta


def _public_rows(
    items: Any, limit: int, *, source: str
) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    if not isinstance(items, list):
        return rows
    for item in items:
        if not isinstance(item, dict):
            continue
        public = _public_url(item.get("url"))
        title = item.get("title")
        if public and isinstance(title, str) and title.strip():
            rows.append({"title": title[:500], "url": public,
                         "snippet": "", "source": source, "published_at": ""})
        if len(rows) >= limit:
            break
    return rows
