"""B-Search-2B9-C: per-provider recall diagnosis (who returns the generic homepages)."""
import json
import os
import sys
from pathlib import Path

ROOT = Path("D:/study-agent-validation/model-driven-research-entry")
OUT = Path("D:/study-agent-validation/reading-notebook-ui-evidence/model-driven-search-2b9c")
OUT.mkdir(parents=True, exist_ok=True)
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv  # noqa: E402

load_dotenv("C:/Users/Zhang/Desktop/study agent/.env")
from src.news.search_sources.searxng_source import searxng_enabled, search_searxng  # noqa: E402
from src.web.tool_gateway import GeneralWebGateway  # noqa: E402

gw = GeneralWebGateway()
QUERIES = [
    ("factorio", "Factorio 2.0 train interrupts vs fixed schedule"),
    ("go_rules", "围棋 提子 打劫 规则 区别"),
    ("python_ref", "Python 3.15.0 正式发布说明"),
    ("factorio_zh", "Factorio 列车中断 时刻表 区别"),
]
out = {"searxng_enabled": searxng_enabled(), "queries": {}}
for key, q in QUERIES:
    rec = {}
    if searxng_enabled():
        try:
            sx = search_searxng(q, max_results=5, timeout=6.0,
                                categories=os.getenv("WEB_SEARXNG_CATEGORIES", "general"))
            rec["searxng"] = {"n": len(sx),
                              "urls": [str(i.get("link") or i.get("resolved_link")) for i in sx][:5]}
        except Exception as exc:  # noqa: BLE001
            rec["searxng"] = {"error": f"{type(exc).__name__}: {exc}"}
    try:
        b, be = gw._search_bing_rss(q, 5, 6.0)
        rec["bing_rss"] = {"n": len(b), "error": be, "urls": [x.get("url") for x in b][:5]}
    except Exception as exc:  # noqa: BLE001
        rec["bing_rss"] = {"error": f"{type(exc).__name__}: {exc}"}
    try:
        d, de = gw._search_duckduckgo(q, 5, 6.0)
        rec["duckduckgo"] = {"n": len(d), "error": de, "urls": [x.get("url") for x in d][:5]}
    except Exception as exc:  # noqa: BLE001
        rec["duckduckgo"] = {"error": f"{type(exc).__name__}: {exc}"}
    out["queries"][key] = rec
    print(key, q, json.dumps(rec, ensure_ascii=False), flush=True)
(OUT / "providers.json").write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
print("DONE")
