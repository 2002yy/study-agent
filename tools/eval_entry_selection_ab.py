"""B-Search-2B8-C: real-model A/B with a FROZEN feed snapshot.

arm A = entry_selection off (old behaviour); arm B = forced tool-layer admission.
Fixed snapshot, model, budget. Metrics count hits AND extra mis-reads AND tool-layer
rejections separately (tool name from calls[].action.tool).
"""
import json
import sys
import time
from pathlib import Path

ROOT = Path("D:/study-agent-validation/model-driven-research-entry")
OUT = Path("D:/study-agent-validation/reading-notebook-ui-evidence/model-driven-search-2b8")
OUT.mkdir(parents=True, exist_ok=True)
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv  # noqa: E402

load_dotenv("C:/Users/Zhang/Desktop/study agent/.env")
import src.web.research_tool_agent as rt  # noqa: E402
from src.web.research_tool_agent import AgentBudget, run_tool_agent  # noqa: E402
from src.web.semantic_recovery import configured_completion  # noqa: E402
from src.web.tool_gateway import GeneralWebGateway  # noqa: E402

FEED = "https://blog.python.org/feeds/posts/default"
CASES = [
    ("not_first", "Python 3.15.0 正式发布说明", "python-3150-final"),
    ("tutorial_conflict", "Python 3.15.0 入门教程", None),
    ("final_vs_prerelease", "Python 3.15.0 正式版发布了吗", "python-3150-final"),
    ("similar_title", "Python 自由线程 free-threading 现在是什么状况", "free-threading"),
    ("no_article", "围棋 提子 规则", None),
]

# --- freeze the feed snapshot once, reuse byte-for-byte for every run ---
snap = OUT / "feed_snapshot.xml"
if not snap.exists():
    from src.web.safe_http import safe_fetch

    snap.write_text(safe_fetch(FEED, timeout=20.0), encoding="utf-8")
FEED_XML = snap.read_text(encoding="utf-8")
rt.safe_fetch = lambda url, timeout=15.0, deadline=None: FEED_XML  # noqa: E731

gw = GeneralWebGateway()
rows = []
for arm in ("A", "B"):
    for key, q, expect in CASES:
        t0 = time.monotonic()
        trace = run_tool_agent(
            gateway=gw, completion=configured_completion, question=q,
            budget=AgentBudget(max_rounds=4, max_searches=2, max_reads=2, hard_seconds=60),
            registry_sources=(("python-blog", FEED),), entry_selection=(arm == "B"),
        )
        read_attempts = [c for c in trace["calls"] if c.get("action", {}).get("tool") == "read_page"]
        rejected = [c for c in read_attempts if c.get("result", {}).get("status") == "entry_not_eligible"]
        ok_urls = [b["url"] for b in trace["bodies"] if b["ok"] and b["chars"] > 0]
        hit = any(expect in u for u in ok_urls) if expect else None
        extra = ([u for u in ok_urls if expect not in u] if expect else ok_urls)
        row = {
            "arm": arm, "case": key, "expect": expect,
            "tools": [c["action"]["tool"] for c in trace["calls"] if c.get("action")],
            "read_attempts": len(read_attempts), "rejected": len(rejected),
            "reject_reasons": [c["result"].get("reason") for c in rejected],
            "read_urls": ok_urls, "hit": hit, "extra_misreads": extra,
            "refusal_ok": (len(ok_urls) == 0) if expect is None else None,
            "stop": trace["stop_reason"], "rounds": trace["rounds"],
            "searches": trace.get("searches"), "reads": trace["reads"],
            "elapsed": round(time.monotonic() - t0, 1),
        }
        rows.append(row)
        print(json.dumps(row, ensure_ascii=False), flush=True)
        (OUT / "ab_results_c.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
print("DONE")
