"""B-Search-2B9-D phase 1: SearXNG root-cause probe (host -> raw JSON -> adapter)."""
import json
import os
import sys
from pathlib import Path
from urllib.request import Request, urlopen

ROOT = Path("D:/study-agent-validation/model-driven-research-entry")
OUT = Path("D:/study-agent-validation/reading-notebook-ui-evidence/model-driven-search-2b9d")
OUT.mkdir(parents=True, exist_ok=True)
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv  # noqa: E402

load_dotenv("C:/Users/Zhang/Desktop/study agent/.env")
from src.news.search_sources.searxng_source import (  # noqa: E402
    build_searxng_search_url,
    get_last_searxng_error,
    searxng_base_url,
    searxng_enabled,
    search_searxng,
)

Q = "Factorio 2.0 train interrupts"
env = {k: os.getenv(k) for k in ("SEARXNG_BASE_URL", "WEB_ENABLE_SEARXNG", "NEWS_ENABLE_SEARXNG",
                                 "SEARXNG_ALLOW_LOOPBACK", "WEB_SEARXNG_CATEGORIES")}
base = searxng_base_url()
url = build_searxng_search_url(Q, base_url=base, max_results=5,
                              categories=os.getenv("WEB_SEARXNG_CATEGORIES", "general")) if base else ""
raw = {"enabled": searxng_enabled(), "env": env, "base_url": base, "url": url}
if url:
    try:
        with urlopen(Request(url, headers={"User-Agent": "study-agent/2b9d"}), timeout=8) as resp:
            body = resp.read()
            raw["http_status"] = getattr(resp, "status", None)
            raw["content_type"] = resp.headers.get("Content-Type")
            raw["bytes"] = len(body)
            try:
                data = json.loads(body.decode("utf-8", "replace"))
                raw["json_keys"] = sorted(data.keys())
                raw["n_results"] = len(data.get("results") or [])
                raw["unresponsive_engines"] = data.get("unresponsive_engines")
                raw["first_urls"] = [(r.get("url") or r.get("link")) for r in (data.get("results") or [])][:5]
            except Exception as exc:  # noqa: BLE001
                raw["json_error"] = f"{type(exc).__name__}: {exc}"
                raw["body_head"] = body[:300].decode("utf-8", "replace")
    except Exception as exc:  # noqa: BLE001
        raw["request_error"] = f"{type(exc).__name__}: {exc}"
# adapter view
adapter = {}
try:
    items = search_searxng(Q, max_results=5, timeout=6, categories=os.getenv("WEB_SEARXNG_CATEGORIES", "general"))
    adapter = {"n": len(items), "last_error": get_last_searxng_error(),
               "urls": [str(i.get("link") or i.get("resolved_link")) for i in items][:5]}
except Exception as exc:  # noqa: BLE001
    adapter = {"error": f"{type(exc).__name__}: {exc}", "last_error": get_last_searxng_error()}
result = {"raw": raw, "adapter": adapter}
print(json.dumps(result, ensure_ascii=False, indent=2))
(OUT / "searxng_probe.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
