"""B-Search-2B8-D Final Qualification.

Three arms: A (old), B (semantic admission, no assessment feedback), C (admission +
assessment fed back). Real deepseek-flash, LIVE feed+search. Body relevance is judged
by INDEPENDENT per-case rules over the read body (never assess_body's own output).
Plus two extra live runs (a new positive and a negative) on different topics.
"""
import hashlib
import json
import sys
import time
from pathlib import Path

ROOT = Path("D:/study-agent-validation/model-driven-research-entry")
SA = Path("D:/study-agent-validation/reading-notebook-ui-evidence/model-driven-search-2b8")
SA.mkdir(parents=True, exist_ok=True)
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv  # noqa: E402

load_dotenv("C:/Users/Zhang/Desktop/study agent/.env")
from src.web.research_tool_agent import AgentBudget, run_tool_agent  # noqa: E402
from src.web.safe_http import safe_fetch  # noqa: E402
from src.web.semantic_recovery import configured_completion  # noqa: E402
from src.web.tool_gateway import GeneralWebGateway  # noqa: E402

FEED = "https://blog.python.org/feeds/posts/default"


def _satisfies(key: str, text: str) -> bool:
    """INDEPENDENT goal-satisfaction judgement (not assess_body)."""
    t = text.casefold()
    if key in ("not_first", "final_vs_prerelease"):
        return "3.15.0" in t and ("final" in t or "is here" in t or "released" in t)
    if key == "similar_title":
        return "free-thread" in t
    if key == "download_conflict":
        return "download" in t and "python" in t
    return False  # tutorial_vs_release / no_article: no page satisfies the goal


CASES = [
    ("not_first", "Python 3.15.0 正式发布说明", "python-3150-final-is-here"),
    ("final_vs_prerelease", "Python 3.15.0 正式版发布了吗", "python-3150-final-is-here"),
    ("tutorial_vs_release", "Python 3.15.0 入门教程", None),
    ("download_conflict", "Python 3.15.0 下载安装", "downloads"),
    ("similar_title", "Python free-threading 自由线程 现状", "free-threading"),
    ("no_article", "围棋 提子 规则", None),
]
ARMS = {
    "A": {"entry_selection": False, "assessment_feedback": False},
    "B": {"entry_selection": True, "assessment_feedback": False},
    "C": {"entry_selection": True, "assessment_feedback": True},
}
gw = GeneralWebGateway()

try:
    _xml = safe_fetch(FEED, timeout=20.0)
    feed_sha, feed_err = hashlib.sha256(_xml.encode("utf-8")).hexdigest(), None
except Exception as exc:  # noqa: BLE001
    feed_sha, feed_err = None, f"{type(exc).__name__}: {exc}"


def run(arm, key, q, expect):
    t0 = time.monotonic()
    tr = run_tool_agent(
        gateway=gw, completion=configured_completion, question=q,
        budget=AgentBudget(max_rounds=5, max_searches=2, max_reads=2, hard_seconds=60),
        registry_sources=(("python-blog", FEED),), **ARMS[arm],
    )
    reads = [b for b in tr["bodies"] if b["ok"] and b["chars"] > 0]
    per = []
    for b in reads:
        ind = _satisfies(key, str(b.get("preview") or ""))
        v = (b.get("assessment") or {}).get("verdict", "")
        per.append({"url": b["url"], "verdict": v, "independent_satisfies": ind})
    false_match = sum(1 for p in per if p["verdict"] == "matches" and not p["independent_satisfies"])
    hit = any(expect in p["url"] for p in per) if expect else None
    extra = ([p["url"] for p in per if expect not in p["url"]] if expect else None)
    reject = sum(1 for c in tr["calls"] if c.get("action", {}).get("tool") == "read_page"
                 and c.get("result", {}).get("status") == "entry_not_eligible")
    return {"arm": arm, "case": key, "expect": expect, "stop": tr["stop_reason"],
            "rounds": tr["rounds"], "searches": tr.get("searches"), "reads": tr["reads"],
            "read_detail": per, "hit": hit, "extra_misreads": extra, "false_match": false_match,
            "tool_rejected": reject, "refusal_ok": (len(per) == 0) if expect is None else None,
            "elapsed": round(time.monotonic() - t0, 1)}


rows = [run(arm, key, q, expect) for arm in ("A", "B", "C") for key, q, expect in CASES]
for r in rows:
    print(json.dumps(r, ensure_ascii=False), flush=True)

EXTRA = [("live_positive", "Factorio 2.0 列车中断 与 固定时刻表 调度机制 区别", None),
         ("live_negative", "2027 年 围甲联赛 第 99 轮 赛果", None)]
live = []
for key, q, _ in EXTRA:
    r = run("C", key, q, None)
    r["live"] = True
    live.append(r)
    print(json.dumps(r, ensure_ascii=False), flush=True)

summary = {}
for arm in ("A", "B", "C"):
    ar = [r for r in rows if r["arm"] == arm]
    summary[arm] = {
        "hits": sum(1 for r in ar if r["hit"]),
        "extra_misreads": sum(len(r["extra_misreads"] or []) for r in ar),
        "false_match": sum(r["false_match"] for r in ar),
        "correct_refusal": sum(1 for r in ar if r["refusal_ok"]),
        "tool_rejected": sum(r["tool_rejected"] for r in ar),
        "total_reads": sum(r["reads"] for r in ar),
    }
(SA / "final_qual.json").write_text(json.dumps(
    {"feed_sha256": feed_sha, "feed_error": feed_err, "summary": summary, "rows": rows, "live": live},
    ensure_ascii=False, indent=2), encoding="utf-8")
print("SUMMARY", json.dumps(summary, ensure_ascii=False))
print("DONE feed=", feed_sha, feed_err)
