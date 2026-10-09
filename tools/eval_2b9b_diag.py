"""B-Search-2B9-B Phase 1: locate the 'arrival' failure (search -> specific entry -> body).

Wraps search_exact / read to record, per task: every query, engine status, candidate
title/snippet/url, and the model's chosen reads + reader branch/error. No production change.
"""
import json
import sys
import time
from pathlib import Path

ROOT = Path("D:/study-agent-validation/model-driven-research-entry")
OUT = Path("D:/study-agent-validation/reading-notebook-ui-evidence/model-driven-search-2b9b")
OUT.mkdir(parents=True, exist_ok=True)
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv  # noqa: E402

load_dotenv("C:/Users/Zhang/Desktop/study agent/.env")
from src.web.research_tool_agent import AgentBudget, run_tool_agent  # noqa: E402
from src.web.semantic_recovery import configured_completion  # noqa: E402
from src.web.tool_gateway import GeneralWebGateway  # noqa: E402

FEED = "https://blog.python.org/feeds/posts/default"
gw = GeneralWebGateway()
log = {"search": [], "read": []}
_orig_search, _orig_read = gw.search_exact, gw.read


def search_spy(query, max_results=5):
    r = _orig_search(query, max_results=max_results)
    log["search"].append({"query": query, "status": r.get("status"),
                          "rows": [{"url": x.get("url"), "title": x.get("title"),
                                    "snippet": (x.get("snippet") or "")[:160]} for x in (r.get("results") or [])]})
    return r


def read_spy(url, *a, **k):
    try:
        r = _orig_read(url, *a, **k)
    except Exception as exc:  # noqa: BLE001
        log["read"].append({"url": url, "ok": False, "error": f"{type(exc).__name__}: {exc}"})
        raise
    log["read"].append({"url": url, "ok": r.get("ok"),
                        "chars": len(str(r.get("content") or r.get("readme") or "")),
                        "error": r.get("error") or r.get("error_code")})
    return r


gw.search_exact = search_spy
gw.read = read_spy

TASKS = [
    ("factorio", "Factorio 2.0 中“列车中断（train interrupts）”与传统固定时刻表调度机制的区别，并说明何时不应使用中断。"),
    ("go_rules", "围棋中“提子”和“打劫”的规则分别是什么？说明二者的区别。注意：这里指围棋，不是 Go 编程语言。"),
    ("python_reference", "Python 3.15.0 正式发布说明"),
]
rows = []
for key, q in TASKS:
    log["search"].clear()
    log["read"].clear()
    t0 = time.monotonic()
    tr = run_tool_agent(gateway=gw, completion=configured_completion, question=q,
                        budget=AgentBudget(max_rounds=6, max_searches=3, max_reads=3, hard_seconds=90),
                        registry_sources=(("python-blog", FEED),) if key == "python_reference" else (),
                        entry_selection=True, assessment_feedback=True)
    rows.append({"task": key, "stop": tr["stop_reason"], "rounds": tr["rounds"],
                 "searches": tr.get("searches"), "reads": tr["reads"],
                 "tools": [c["action"]["tool"] for c in tr["calls"] if c.get("action")],
                 "searches_log": list(log["search"]), "reads_log": list(log["read"]),
                 "elapsed": round(time.monotonic() - t0, 1)})
    print(json.dumps({"task": key, "stop": tr["stop_reason"], "searches": tr.get("searches"),
                      "reads": tr["reads"],
                      "queries": [s["query"] for s in log["search"]],
                      "candidates": [[x["url"] for x in s["rows"]] for s in log["search"]],
                      "read_errs": [(r["url"], r.get("error")) for r in log["read"]]}, ensure_ascii=False), flush=True)
    (OUT / "diag.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
print("DONE")
