"""Opt-in search through the locally paired browse extension."""

from __future__ import annotations

import base64
import binascii
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlsplit

from src.web.tool_evidence import _public_url

# An engine choice, not an engine cascade: the existing gateway owns fallback.
_ENGINES = {
    "google": ("https://www.google.com/search", "a:has(h3)", "Google"),
    "duckduckgo": ("https://html.duckduckgo.com/html/", "a.result__a", "DuckDuckGo"),
    "bing": ("https://www.bing.com/search", "li.b_algo h2 a", "Bing"),
    "brave": (
        "https://search.brave.com/search",
        ".result-content > a:has(.search-snippet-title)", "Brave",
    ),
}


def _result_url(value: object, engine: str) -> str:
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


def search_browse(
    query: str, limit: int, timeout: float, *, engine: str | None = None
) -> tuple[list[dict[str, str]], str]:
    chosen = (engine if engine is not None else os.getenv("WEB_BROWSE_SEARCH_ENGINE", "google")).strip().lower()
    if chosen not in _ENGINES:
        return [], "browse:invalid_engine"
    executable = shutil.which("browse")
    if not executable:
        return [], "browse:cli_unavailable"
    endpoint, selector, label = _ENGINES[chosen]
    url = endpoint + "?" + urlencode({"q": query})
    allowed_origins = ["https://www.bing.com", "https://cn.bing.com"] if chosen == "bing" else [
        f"{urlsplit(endpoint).scheme}://{urlsplit(endpoint).netloc}"
    ]
    # Only the URL is parameterized. Source text is never executable code.
    script = """
await page.goto(SEARCH_URL, {waitUntil: 'domcontentloaded', timeout: TIMEOUT_MS});
await snapshot();
const expected = new URL(SEARCH_URL);
const actual = new URL(page.url());
if (!ALLOWED_ORIGINS.includes(actual.origin) || actual.pathname !== expected.pathname) {
  return {blocked: true, results: []};
}
return await page.evaluate(() => ({
  blocked: Boolean(document.querySelector('form[action*="sorry"], #captcha-form, form[action*="anomaly"], input[name="captcha"]')),
  results: Array.from(document.querySelectorAll(RESULT_SELECTOR)).slice(0, 24).map(a => ({
    title: (a.querySelector('.search-snippet-title, h3, h2')?.innerText || a.innerText || '').trim(),
    url: a.href,
    snippet: ''
  }))
}));
""".replace("SEARCH_URL", json.dumps(url)).replace(
        "TIMEOUT_MS", str(max(1, int(timeout * 1000)))
    ).replace("RESULT_SELECTOR", json.dumps(selector)).replace(
        "ALLOWED_ORIGINS", json.dumps(allowed_origins)
    )
    try:
        with tempfile.TemporaryDirectory(prefix="study-agent-browse-") as folder:
            path = Path(folder) / "search.js"
            path.write_text(script, encoding="utf-8")
            completed = subprocess.run(
                [executable, "execute", "--rm", "--json", "--timeout-ms",
                 str(max(1, int(timeout * 1000))), "--file", str(path)],
                capture_output=True, text=True, encoding="utf-8", timeout=timeout + 1,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                check=False,
            )
        if completed.returncode:
            return [], "browse:execution_failed"
        envelope = json.loads(completed.stdout)
        challenge = (envelope.get("aftermath") or {}).get("challenge")
        if challenge and challenge.get("recommendation") in {"handoff", "stop"}:
            return [], "browse:human_action_required"
        if envelope.get("isError") or not isinstance(envelope.get("value"), dict):
            return [], "browse:execution_failed"
        value = envelope["value"]
        if value.get("blocked"):
            return [], "browse:human_action_required"
        rows = []
        for item in value.get("results", []):
            if not isinstance(item, dict):
                continue
            public = _result_url(item.get("url"), chosen)
            title = item.get("title")
            if public and isinstance(title, str) and title.strip():
                rows.append({"title": title[:500], "url": public,
                             "snippet": "", "source": f"{label} via browse", "published_at": ""})
        return rows[:limit], "" if rows else "browse:no_results"
    except subprocess.TimeoutExpired:
        return [], "browse:timeout"
    except (OSError, ValueError, TypeError):
        return [], "browse:invalid_response"
