"""B-Search-2B9-A fixtures: full-text capture via the PROVEN gw.read path (cache cleared)."""
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path("D:/study-agent-validation/model-driven-research-entry")
OUT = Path("D:/study-agent-validation/reading-notebook-ui-evidence/model-driven-search-2b9a")
OUT.mkdir(parents=True, exist_ok=True)
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv  # noqa: E402

load_dotenv("C:/Users/Zhang/Desktop/study agent/.env")
import src.news.article_fetcher as af  # noqa: E402
from src.web.research.entry_selection import assess_body  # noqa: E402
from src.web.tool_gateway import GeneralWebGateway  # noqa: E402

gw = GeneralWebGateway()
FIX = [
    ("https://blog.python.org/2026/10/python-3150-final-is-here/", "Python 3.15.0 正式发布说明", "matches"),
    ("https://www.python.org/downloads/", "Python 3.15.0 入门教程", "mismatch"),
    ("https://www.runoob.com/python/python-tutorial.html", "Python 3.15.0 入门教程", "partial_background"),
]
fixtures, texts = [], {}
for url, q, label in FIX:
    af._ARTICLE_CACHE.clear()  # force a fresh, uncached full read
    try:
        r = gw.read(url, max_chars=20000, timeout=20)
    except Exception as exc:  # noqa: BLE001
        r = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    text = str(r.get("content") or r.get("readme") or "")
    got = assess_body(text, q)["verdict"] if r.get("ok") else ""
    texts[url] = text
    fixtures.append({"url": url, "goal": q, "expected": label, "assess_body": got,
                     "ok": bool(r.get("ok")), "chars": len(text),
                     "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                     "bounded_excerpt": len(text) >= 20000, "fixture": "evaluation_fixture"})
    print("FIX", json.dumps(fixtures[-1], ensure_ascii=False), flush=True)

(OUT / "fixtures.json").write_text(json.dumps(fixtures, ensure_ascii=False, indent=2), encoding="utf-8")
(OUT / "fixture_texts.json").write_text(json.dumps(texts, ensure_ascii=False, indent=2), encoding="utf-8")
print("DONE")
