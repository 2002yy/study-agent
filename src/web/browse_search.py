"""Opt-in Google search through the locally paired browse extension."""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import tempfile
from urllib.parse import urlencode

from src.web.tool_evidence import _public_url


def search_browse(query: str, limit: int, timeout: float) -> tuple[list[dict[str, str]], str]:
    executable = shutil.which("browse")
    if not executable:
        return [], "browse:cli_unavailable"
    url = "https://www.google.com/search?" + urlencode({"q": query})
    # Only the URL is parameterized. Source text is never executable code.
    script = """
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
""".replace("SEARCH_URL", json.dumps(url)).replace("TIMEOUT_MS", str(max(1, int(timeout * 1000))))
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
            public = _public_url(item.get("url"))
            title = item.get("title")
            if public and isinstance(title, str) and title.strip():
                rows.append({"title": title[:500], "url": public,
                             "snippet": "", "source": "Google via browse", "published_at": ""})
        return rows[:limit], "" if rows else "browse:no_results"
    except subprocess.TimeoutExpired:
        return [], "browse:timeout"
    except (OSError, ValueError, TypeError):
        return [], "browse:invalid_response"
