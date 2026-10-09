"""B-Search-2B9-A: baseline alignment + trustworthy full-text capture + independent fixtures.

- Baseline: same model/budget/gateway/question, WITH vs WITHOUT the Python blog seed,
  to separate seed-config / model variance / search-feed failure.
- Full text: re-read each article with a CLEARED article cache (the cache is URL-keyed and
  ignores max_chars), recording method / chars / sha256 / bounded_excerpt — not the preview.
- Fixtures: real URLs with goals labeled by us (evaluation_fixture, NOT agent-discovered),
  compared against assess_body for FP / FN / undecidable.
"""
import hashlib
import json
import sys
import time
from pathlib import Path

ROOT = Path("D:/study-agent-validation/model-driven-research-entry")
OUT = Path("D:/study-agent-validation/reading-notebook-ui-evidence/model-driven-search-2b9a")
OUT.mkdir(parents=True, exist_ok=True)
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv  # noqa: E402

load_dotenv("C:/Users/Zhang/Desktop/study agent/.env")
import src.news.article_fetcher as af  # noqa: E402
from src.web.research.entry_selection import assess_body  # noqa: E402
from src.web.research_tool_agent import AgentBudget, run_tool_agent  # noqa: E402
from src.web.semantic_recovery import configured_completion  # noqa: E402
from src.web.tool_gateway import GeneralWebGateway  # noqa: E402

FEED = "https://blog.python.org/feeds/posts/default"
gw = GeneralWebGateway()


def fresh_text(url: str, max_chars: int = 30000) -> dict:
    af._ARTICLE_CACHE.clear()  # bypass the URL-only cache
    try:
        r = af.fetch_article_read_result(url, max_chars=max_chars)
        text = str(r.get("text") or "")
        return {"ok": bool(r.get("ok")), "method": r.get("method"), "chars": len(text),
                "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                "bounded_excerpt": len(text) >= max_chars, "text": text}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}", "chars": 0, "text": ""}


Q = "Python 3.15.0 正式发布说明"
baseline, texts = [], {}
for name, seeds in (("with_seed", (("python-blog", FEED),)), ("no_seed", ())):
    t0 = time.monotonic()
    tr = run_tool_agent(gateway=gw, completion=configured_completion, question=Q,
                        budget=AgentBudget(max_rounds=6, max_searches=3, max_reads=3, hard_seconds=90),
                        registry_sources=seeds, entry_selection=True, assessment_feedback=True)
    urls = [b["url"] for b in tr["bodies"] if b.get("ok") and b.get("chars")]
    baseline.append({"variant": name, "seeded": bool(seeds), "stop": tr["stop_reason"],
                     "rounds": tr["rounds"], "searches": tr.get("searches"), "reads": tr["reads"],
                     "read_urls": urls, "tools": [c["action"]["tool"] for c in tr["calls"] if c.get("action")],
                     "elapsed": round(time.monotonic() - t0, 1)})
    print("BASE", json.dumps(baseline[-1], ensure_ascii=False), flush=True)
    for u in urls:
        a = fresh_text(u)
        a.pop("text", None)
        a["url"] = u
        baseline[-1].setdefault("audit", []).append(a)

FIX = [
    ("https://blog.python.org/2026/10/python-3150-final-is-here/", "Python 3.15.0 正式发布说明", "matches"),
    ("https://www.python.org/downloads/", "Python 3.15.0 入门教程", "mismatch"),
    ("https://www.runoob.com/python/python-tutorial.html", "Python 3.15.0 入门教程", "partial_background"),
]
fixtures = []
for url, q, label in FIX:
    a = fresh_text(url, max_chars=20000)
    got = assess_body(a["text"], q)["verdict"] if a.get("ok") else ""
    texts[url] = a["text"]
    fixtures.append({"url": url, "goal": q, "expected": label, "assess_body": got,
                     "chars": a.get("chars"), "bounded_excerpt": a.get("bounded_excerpt"), "method": a.get("method"),
                     "fixture": "evaluation_fixture"})
    print("FIX", json.dumps(fixtures[-1], ensure_ascii=False), flush=True)

(OUT / "baseline_fixtures.json").write_text(
    json.dumps({"baseline": baseline, "fixtures": fixtures}, ensure_ascii=False, indent=2), encoding="utf-8")
(OUT / "audited_texts.json").write_text(json.dumps(texts, ensure_ascii=False, indent=2), encoding="utf-8")
print("DONE")
