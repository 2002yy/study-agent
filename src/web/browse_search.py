"""Browser-backed search through the locally paired browse extension.

Three entry points share one execution path:

* :func:`search_browse` - one general search engine (Google by default);
* :func:`search_browse_at` - any site that has a search URL (the site pool);
* the site pool in :mod:`src.web.site_pool` picks which of the two to use.

All treat the page as untrusted data. Only a public URL is kept, and a captcha,
verification wall or login wall stops that request instead of being worked
around.
"""

from __future__ import annotations

import base64
import binascii
import json
import math
import os
from queue import Empty, Queue
import re
import shutil
import subprocess
from threading import Thread
import time
from typing import Any
from urllib.parse import parse_qs, urlencode, urlsplit

from src.web.tool_evidence import _public_url

#: An engine choice, not an engine cascade: the gateway owns fallback. Each
#: entry is (search endpoint, result selector, label). The selectors were
#: measured on the real pages - Brave's title is not an ``h3``, and Bing wraps
#: some outbound links in a redirect.
_ENGINES: dict[str, tuple[str, str, str]] = {
    "google": ("https://www.google.com/search", "a:has(h3)", "Google"),
    "duckduckgo": ("https://html.duckduckgo.com/html/", "a.result__a", "DuckDuckGo"),
    "bing": ("https://www.bing.com/search", "li.b_algo h2 a", "Bing"),
    "brave": (
        "https://search.brave.com/search",
        ".result-content > a:has(.search-snippet-title)",
        "Brave",
    ),
}

_ENGINE_SCRIPT = r"""
await page.goto(SEARCH_URL, {waitUntil: 'domcontentloaded', timeout: TIMEOUT_MS});
await snapshot();
// The execute sandbox has no URL global; parse on the page side instead.
const landed = await page.evaluate(() => ({origin: location.origin, pathname: location.pathname}));
const expectedPath = SEARCH_URL.split('?')[0].replace(/^https?:\/\/[^/]+/, '');
if (!ALLOWED_ORIGINS.includes(landed.origin) || landed.pathname !== expectedPath) {
  // A redirect away from the engine's own result page is never trusted.
  return {blocked: true, results: []};
}
return await page.evaluate(() => ({
  blocked: Boolean(document.querySelector(
    'form[action*="sorry"], #captcha-form, form[action*="anomaly"], input[name="captcha"]'
  )),
  results: Array.from(document.querySelectorAll(RESULT_SELECTOR)).slice(0, 24).map(a => ({
    title: (a.querySelector('.search-snippet-title, h3, h2')?.innerText || a.innerText || '').trim(),
    url: a.href,
    snippet: ''
  }))
}));
"""


_BRAVE_RESOLVE_SCRIPT = r"""
const targets = WRAPPER_URLS;
const out = [];
const tab = await context.newPage();
try {
  for (const target of targets) {
    let finalUrl = "";
    try {
      await tab.goto(target, {waitUntil: 'domcontentloaded', timeout: PER_NAV_MS});
      for (let i = 0; i < POLL_STEPS; i++) {
        const current = tab.url();
        if (current && current.indexOf('/go/') === -1) { finalUrl = current; break; }
        await tab.waitForTimeout(100);
      }
      if (!finalUrl) finalUrl = tab.url();
    } catch (error) {
      finalUrl = "";
    }
    out.push(finalUrl);
  }
} finally {
  try { await tab.close(); } catch (error) {}
}
return {urls: out};
"""


def _result_url(value: object, engine: str) -> str:
    """Resolve an engine's own redirect wrapper before validating the URL."""

    if engine == "brave" and isinstance(value, str):
        # Brave wraps every result in /go/v1#<opaque token>; the target is not
        # in the DOM, and following the wrapper is a tracking hop. It is not a
        # citable URL, so it is dropped instead of being published as a source.
        parsed = urlsplit(value)
        if parsed.hostname == "search.brave.com" and parsed.path.startswith("/go/"):
            return ""
    if engine != "bing" or not isinstance(value, str):
        return _public_url(value)
    parsed = urlsplit(value)
    if parsed.hostname in {"www.bing.com", "cn.bing.com", "bing.com"} and parsed.path == "/ck/a":
        encoded = parse_qs(parsed.query).get("u", [""])[0]
        if not encoded.startswith("a1"):
            return ""
        try:
            value = base64.urlsafe_b64decode(encoded[2:] + "===").decode("utf-8")
        except (ValueError, binascii.Error):
            return ""
    return _public_url(value)

_GENERIC_SCRIPT = """
try {
  await page.goto(SEARCH_URL, {waitUntil: 'domcontentloaded', timeout: NAV_TIMEOUT_MS});
} catch (error) {
  // A heavy community page can miss domcontentloaded; use whatever rendered.
}
try { await page.waitForTimeout(800); } catch (error) {}
// Client-rendered search pages (Algolia, Steam, Nowcoder) add their results
// after the first paint; wait for a result container instead of guessing.
const waitFor = WAIT_FOR_SELECTOR;
if (waitFor) {
  try { await page.waitForSelector(waitFor, {timeout: WAIT_FOR_MS}); } catch (error) {}
}
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
  // A site-specific selector is authoritative: a header, footer or sidebar
  // link can match a generic rule but never a result container.
  const scopes = RESULT_SELECTOR
    ? Array.from(document.querySelectorAll(RESULT_SELECTOR))
    : Array.from(document.querySelectorAll(
        'main a[href], [role="main"] a[href], article a[href], li a[href], a[href]'
      ));
  for (const scope of scopes) {
    const anchor = scope.tagName === 'A' ? scope : scope.querySelector('a[href]');
    if (!anchor) continue;
    const heading = anchor.querySelector('h3, h2, [role="heading"]') || scope.querySelector('h3, h2');
    const title = ((heading ? heading.innerText : '') || anchor.innerText || '').trim();
    const url = anchor.href;
    if (!url.startsWith('http') || title.length < 12 || seen.has(url)) continue;
    let parsed;
    try { parsed = new URL(url); } catch (error) { continue; }
    if (!RESULT_SELECTOR && parsed.hostname === searchHost) {
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
  return {blocked: challenge, login, url: location.href, title: document.title, results};
});
"""


def _run_mcp(command: list[str], *, input: str, timeout: float) -> str:
    # The relay can close requests on EOF while navigation is still in flight.
    # Keep stdin open until the matching tools/call response arrives.
    process = subprocess.Popen(
        command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL, text=True, encoding="utf-8",
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    stdin, stdout = process.stdin, process.stdout
    assert stdin is not None and stdout is not None
    responses: Queue[str] = Queue(maxsize=1)

    def read_reply() -> None:
        reply = ""
        try:
            for line in stdout:
                message = json.loads(line)
                if isinstance(message, dict) and message.get("id") == 2:
                    reply = line
                    break
        except (OSError, ValueError):
            pass
        finally:
            responses.put(reply)

    reader = Thread(target=read_reply, daemon=True)
    reader.start()
    try:
        stdin.write(input)
        stdin.flush()
        try:
            return responses.get(timeout=timeout)
        except Empty as exc:
            raise subprocess.TimeoutExpired(command, timeout) from exc
    finally:
        stdin.close()
        try:
            process.wait(timeout=1)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=1)
        reader.join(timeout=1)
        if not reader.is_alive():
            stdout.close()


def _execute(
    script: str, url: str, timeout: float, *, selector: str = "",
    origins: tuple[str, ...] = (), wait_for: str = "",
    urls: tuple[str, ...] = (), deadline: float = 0.0,
) -> tuple[dict[str, Any] | None, str]:
    executable = shutil.which("browse")
    if not executable:
        return None, "browse:cli_unavailable"
    # Only the URL and the selectors are parameterized; source text is never
    # executable code.
    body = (
        script.replace("SEARCH_URL", json.dumps(url))
        .replace("RESULT_SELECTOR", json.dumps(selector))
        .replace("WAIT_FOR_SELECTOR", json.dumps(wait_for))
        .replace("WRAPPER_URLS", json.dumps(list(urls)))
        .replace("ALLOWED_ORIGINS", json.dumps(list(origins)))
        .replace("NAV_TIMEOUT_MS", str(max(1500, int(timeout * 600))))
        .replace("WAIT_FOR_MS", str(max(1000, min(6000, int(timeout * 1000 / 2)))))
        .replace("TIMEOUT_MS", str(max(1, int(timeout * 1000))))
    )
    # Use the same stdio transport as OpenCode. Script and query data stay off
    # the command line, including on Windows where npm installs a .cmd shim.
    script_input = "try {\n" + body + "\n} finally { try { await page.close(); } catch {} }"
    # A relay or tab detach is a transport hiccup, not a site verdict: retry it
    # once. Challenge, login walls, permission errors, cancellation, budget
    # exhaustion and a normal empty result are never retried.
    transient = re.compile(
        r"detached while handling|tab closed|lost its connection", re.I
    )
    for attempt in range(2):
        budget = timeout
        if deadline:
            budget = min(timeout, deadline - time.monotonic())
            if budget < 1:
                return None, "browse:timeout"
        requests = (
            {
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "study-agent", "version": "1"},
                },
            },
            {"method": "notifications/initialized"},
            {
                "id": 2,
                "method": "tools/call",
                "params": {
                    "name": "execute",
                    "arguments": {
                        "code": script_input,
                        # ceil keeps a 3 s call at 3000 ms: computing from the
                        # remaining budget must not round 2.999 s down to 2999.
                        "timeoutMs": max(1, math.ceil(budget * 1000)),
                    },
                },
            },
        )
        try:
            line = _run_mcp(
                [executable, "mcp"],
                input="".join(json.dumps({"jsonrpc": "2.0", **msg}) + "\n" for msg in requests),
                timeout=budget + 1,
            )
        except subprocess.TimeoutExpired:
            return None, "browse:timeout"
        except (OSError, ValueError, TypeError):
            return None, "browse:invalid_response"
        if not line:
            return None, "browse:execution_failed"
        try:
            response = json.loads(line)
        except ValueError:
            return None, "browse:invalid_response"
        result = response.get("result")
        if not isinstance(result, dict):
            return None, "browse:execution_failed"
        content = result.get("content")
        if not isinstance(content, list):
            return None, "browse:invalid_response"
        messages = "\n".join(
            str(item.get("text") or "")
            for item in content
            if isinstance(item, dict) and item.get("type") == "text"
        ).lstrip()
        if result.get("isError"):
            if re.search(r"\b(?:captcha|bot challenge|human action required)\b", messages, re.I):
                return None, "browse:human_action_required"
            if attempt == 0 and transient.search(messages):
                if deadline and deadline - time.monotonic() < 2:
                    return None, "browse:execution_failed"
                continue
            return None, "browse:execution_failed"
        try:
            value, boundary = json.JSONDecoder().raw_decode(messages)
        except ValueError:
            return None, "browse:invalid_response"
        if re.search(r"(?im)^\s*(?:bot challenge|challenge|handoff|human action required)\b",
                     messages[boundary:]):
            return None, "browse:human_action_required"
        if isinstance(value, dict):
            return {"value": value}, ""
        return None, "browse:invalid_response"
    return None, "browse:execution_failed"


def search_browse(
    query: str, limit: int, timeout: float, *, engine: str | None = None
) -> tuple[list[dict[str, str]], str]:
    """Search one general engine; the caller still owns fallback."""

    chosen = (
        engine if engine is not None
        else os.getenv("WEB_BROWSE_SEARCH_ENGINE", "google")
    ).strip().casefold()
    if chosen not in _ENGINES:
        return [], "browse:invalid_engine"
    endpoint, selector, label = _ENGINES[chosen]
    parsed = urlsplit(endpoint)
    origins: tuple[str, ...]
    if chosen == "bing":
        origins = ("https://www.bing.com", "https://cn.bing.com")
    elif chosen == "duckduckgo":
        origins = ("https://html.duckduckgo.com", "https://duckduckgo.com")
    else:
        origins = (f"{parsed.scheme}://{parsed.netloc}",)
    url = endpoint + "?" + urlencode({"q": query})
    deadline = time.monotonic() + timeout
    envelope, error = _execute(
        _ENGINE_SCRIPT, url, timeout, selector=selector, origins=origins,
        deadline=deadline,
    )
    if envelope is None:
        return [], error
    challenge = (envelope.get("aftermath") or {}).get("challenge")
    if challenge and challenge.get("recommendation") in {"handoff", "stop"}:
        return [], "browse:human_action_required"
    value = envelope["value"]
    if value.get("blocked"):
        return [], "browse:human_action_required"
    raw_results = [item for item in value.get("results", []) if isinstance(item, dict)]
    resolved: list[str] = []
    if chosen == "brave" and raw_results:
        # Brave wraps every result in a tracker. Resolve at most three, and
        # share the one remaining budget across the batch instead of giving
        # each link the full timeout again. A link that fails keeps the ones
        # already resolved.
        wrappers = tuple(
            str(item.get("url") or "") for item in raw_results[:3]
        )
        remaining = max(2.0, deadline - time.monotonic())
        per_nav = max(1500, min(8000, int(remaining * 1000 / max(1, len(wrappers)))))
        script = _BRAVE_RESOLVE_SCRIPT.replace("PER_NAV_MS", str(per_nav)).replace(
            "POLL_STEPS", str(max(10, per_nav // 100))
        )
        envelope, error = _execute(
            script, "", remaining, urls=wrappers, deadline=deadline
        )
        if envelope is None:
            return [], error
        resolved = [
            item for item in envelope["value"].get("urls", []) if isinstance(item, str)
        ]
    rows: list[dict[str, str]] = []
    for index, item in enumerate(raw_results):
        if index < len(resolved) and resolved[index]:
            candidate: object = resolved[index]
        else:
            candidate = item.get("url")
        public = _result_url(candidate, chosen)
        title = item.get("title")
        if public and isinstance(title, str) and title.strip():
            rows.append({"title": title[:500], "url": public,
                         "snippet": "", "source": f"{label} via browse",
                         "published_at": ""})
        if len(rows) >= limit:
            break
    return rows[:limit], "" if rows else "browse:no_results"


def search_browse_at(
    url: str,
    limit: int,
    timeout: float,
    *,
    source: str = "site via browse",
    selector: str = "",
    pattern: str = "",
    own_hosts: tuple[str, ...] = (),
    wait_for: str = "",
) -> tuple[list[dict[str, str]], str, dict[str, Any]]:
    """Search one site and report what actually happened on its page.

    ``selector`` is the site's result container. ``pattern`` is the URL shape a
    real result takes there. A page that opens but yields nothing that passes
    both is reported as ``browse:no_valid_results`` instead of ``ok``, so a
    navigation link can never end the search early. ``wait_for`` is the element
    that only exists once results rendered; it is waited for instead of sleeping
    a fixed time.
    """

    started = time.monotonic()
    meta: dict[str, Any] = {
        "status": "unknown", "seconds": 0.0, "url": url, "page_results": 0,
    }
    envelope, error = _execute(
        _GENERIC_SCRIPT, url, timeout, selector=selector, wait_for=wait_for
    )
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
    if value.get("blocked") or _is_verification_page(meta["final_url"], value.get("title")):
        meta["status"] = "browse:human_action_required"
        return [], "browse:human_action_required", meta
    if value.get("login"):
        meta["status"] = "browse:login_required"
        return [], "browse:login_required", meta
    raw = value.get("results")
    meta["page_results"] = len(raw) if isinstance(raw, list) else 0
    meta["sample"] = [row["url"] for row in _public_rows(raw, 8, source=source)]
    rows = _valid_rows(
        raw, limit, source=source, pattern=pattern, own_hosts=own_hosts
    )
    if rows:
        meta["status"] = "ok"
        return rows[:limit], "", meta
    meta["status"] = "browse:no_valid_results" if meta["page_results"] else "browse:no_results"
    return [], meta["status"], meta


_NAV_SEGMENTS = {
    "login", "logout", "signup", "register", "search", "about", "help",
    "settings", "preferences", "notifications", "explore", "trending",
}

#: A site may answer a search with a verification wall instead of results. That
#: is a human-action signal, never something to work around. Only the path and
#: the title are checked: a query that happens to contain a word like
#: "challenge" is a normal search, not a challenge page.
_VERIFICATION_PATH_HINTS = ("/nocaptcha", "/captcha", "/challenge", "verify-human")
_VERIFICATION_TITLE_HINTS = (
    "human verification", "are you a robot", "just a moment",
    "verify you are human", "安全验证", "人机验证",
)


def _is_verification_page(url: str, title: Any) -> bool:
    path = urlsplit(str(url or "")).path.casefold()
    lowered_title = str(title or "").casefold()
    return any(hint in path for hint in _VERIFICATION_PATH_HINTS) or any(
        hint in lowered_title for hint in _VERIFICATION_TITLE_HINTS
    )


def _valid_rows(
    items: Any,
    limit: int,
    *,
    source: str,
    pattern: str = "",
    own_hosts: tuple[str, ...] = (),
) -> list[dict[str, str]]:
    """Keep only rows that look like a result on this site."""

    rows: list[dict[str, str]] = []
    if not isinstance(items, list):
        return rows
    compiled = re.compile(pattern, re.IGNORECASE) if pattern else None
    hosts = {host.casefold() for host in own_hosts if host}
    for item in items:
        if not isinstance(item, dict):
            continue
        public = _public_url(item.get("url"))
        title = item.get("title")
        if not public or not isinstance(title, str) or not title.strip():
            continue
        parsed = urlsplit(public)
        host = (parsed.hostname or "").casefold()
        if compiled is not None:
            if not compiled.search(public):
                continue
        elif host in hosts:
            continue
        elif host and parsed.path.strip("/") in _NAV_SEGMENTS:
            continue
        rows.append({"title": title[:500], "url": public,
                     "snippet": "", "source": source, "published_at": ""})
        if len(rows) >= limit:
            break
    return rows


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
