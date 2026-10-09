"""B-Search-2B9-B Phase 3: real validation of bounded `follow` arrival."""
import json
import sys
import time
from pathlib import Path

ROOT = Path("D:/study-agent-validation/model-driven-research-entry")
OUT = Path("D:/study-agent-validation/reading-notebook-ui-evidence/model-driven-search-2b9b")
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv  # noqa: E402

load_dotenv("C:/Users/Zhang/Desktop/study agent/.env")
from src.web.research_tool_agent import AgentBudget, run_tool_agent  # noqa: E402
from src.web.semantic_recovery import configured_completion  # noqa: E402
from src.web.tool_gateway import GeneralWebGateway  # noqa: E402

FEED = "https://blog.python.org/feeds/posts/default"
gw = GeneralWebGateway()
log = {"search": [], "read": []}
_os, _or = gw.search_exact, gw.read


def spy_search(query, max_results=5):
    r = _os(query, max_results=max_results)
    log["search"].append({"query": query, "status": r.get("status"),
                          "providers": r.get("providers_attempted"), "errors": r.get("provider_errors")})
    return r


def spy_read(url, *a, **k):
    try:
        r = _or(url, *a, **k)
    except Exception as exc:  # noqa: BLE001
        log["read"].append({"url": url, "ok": False, "error": f"{type(exc).__name__}: {exc}"})
        raise
    log["read"].append({"url": url, "ok": r.get("ok"),
                        "chars": len(str(r.get("content") or r.get("readme") or ""))})
    return r


gw.search_exact = spy_search
gw.read = spy_read

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
    follows = [c for c in tr["calls"] if c.get("action", {}).get("tool") == "follow"]
    row = {"task": key, "stop": tr["stop_reason"], "rounds": tr["rounds"],
           "searches": tr.get("searches"), "reads": tr["reads"],
           "tools": [c["action"]["tool"] for c in tr["calls"] if c.get("action")],
           "follow_links": [link["url"] for c in follows for link in (c.get("links") or [])],
           "read_urls": [b["url"] for b in tr["bodies"] if b.get("ok") and b.get("chars")],
           "search_log": list(log["search"]), "read_log": list(log["read"]),
           "elapsed": round(time.monotonic() - t0, 1)}
    rows.append(row)
    print(json.dumps({k: row[k] for k in ("task", "stop", "tools", "follow_links",
                                          "read_urls", "elapsed")}, ensure_ascii=False), flush=True)
    (OUT / "validate.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
print("DONE")
