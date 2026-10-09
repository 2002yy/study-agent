"""B-Search-2B8-B: real-model A/B for feed entry selection (arm A plain vs B ranked)."""
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
from src.web.research_tool_agent import AgentBudget, run_tool_agent  # noqa: E402
from src.web.semantic_recovery import configured_completion  # noqa: E402
from src.web.tool_gateway import GeneralWebGateway  # noqa: E402

FEED = "https://blog.python.org/feeds/posts/default"
CASES = [
    ("not_first", "Python 3.15.0 正式发布说明", "python-3150-final"),
    ("tutorial_conflict", "Python 3.15.0 入门教程", None),
    ("final_vs_prerelease", "Python 3.15.0 正式版发布了吗", "python-3150-final"),
    ("similar_title", "Python 自由线程 free-threaded 现在是什么状况", "free-threaded"),
    ("no_article", "围棋 提子 规则", None),
]
gw = GeneralWebGateway()
rows = []
for arm in ("A", "B"):
    for key, q, expect in CASES:
        t0 = time.monotonic()
        try:
            trace = run_tool_agent(
                gateway=gw, completion=configured_completion, question=q,
                budget=AgentBudget(max_rounds=4, max_searches=2, max_reads=2, hard_seconds=60),
                registry_sources=(("python-blog", FEED),),
                entry_selection=(arm == "B"),
            )
            bodies = [b for b in trace["bodies"] if b["ok"] and b["chars"] > 0]
            urls = [b["url"] for b in bodies]
            correct = (len(urls) == 0) if expect is None else any(expect in u for u in urls)
            action_tools = [c["tool"] for c in trace["calls"] if "tool" in c]
            row = {"arm": arm, "case": key, "q": q, "expect": expect,
                   "stop": trace["stop_reason"], "rounds": trace["rounds"],
                   "tools": action_tools, "read_urls": urls, "correct": correct,
                   "elapsed": round(time.monotonic() - t0, 1)}
        except Exception as exc:  # noqa: BLE001
            row = {"arm": arm, "case": key, "q": q, "expect": expect,
                   "error": f"{type(exc).__name__}: {exc}", "correct": False,
                   "elapsed": round(time.monotonic() - t0, 1)}
        rows.append(row)
        print(json.dumps(row, ensure_ascii=False), flush=True)
        (OUT / "ab_results.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
print("DONE")
