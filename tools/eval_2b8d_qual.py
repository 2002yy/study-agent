"""B-Search-2B8-D-QUAL: real dual-channel A/B with frozen REAL snapshots.

- Feed: real blog.python.org RSS, frozen; SHA256 recorded.
- Search: real GeneralWebGateway.search_exact per case, frozen (or kept as a real
  failure if SearXNG is unavailable); SHA256 of the snapshot file recorded.
- Both arms replay the SAME candidates; only entry_selection on/off differs.
- Post-read `assessment` is written back into the next observation (arm B).
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
import src.web.research_tool_agent as rt  # noqa: E402
from src.web.research_tool_agent import AgentBudget, run_tool_agent  # noqa: E402
from src.web.safe_http import safe_fetch  # noqa: E402
from src.web.semantic_recovery import configured_completion  # noqa: E402
from src.web.tool_gateway import GeneralWebGateway  # noqa: E402

FEED = "https://blog.python.org/feeds/posts/default"


def sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


try:
    xml = safe_fetch(FEED, timeout=20.0)
    feed_sha, feed_err = sha(xml.encode("utf-8")), None
except Exception as exc:  # noqa: BLE001
    xml, feed_sha, feed_err = "", None, f"{type(exc).__name__}: {exc}"
(SA / "feed_snapshot.xml").write_text(xml, encoding="utf-8")

CASES = [
    ("not_first", "Python 3.15.0 正式发布说明", "python-3150-final-is-here"),
    ("final_vs_prerelease", "Python 3.15.0 正式版发布了吗", "python-3150-final-is-here"),
    ("tutorial_vs_release", "Python 3.15.0 入门教程", None),
    ("download_conflict", "Python 3.15.0 下载安装", None),
    ("similar_title", "Python free-threading 自由线程 现状", "free-threading"),
    ("no_article", "围棋 提子 规则", None),
]

gw = GeneralWebGateway()
cap = {}
for key, q, _ in CASES:
    try:
        r = gw.search_exact(q, max_results=5)
        cap[key] = {"status": r.get("status"),
                    "results": [{"url": x.get("url"), "title": x.get("title"), "snippet": x.get("snippet")}
                                for x in (r.get("results") or [])]}
    except Exception as exc:  # noqa: BLE001
        cap[key] = {"status": "unavailable", "reason": f"{type(exc).__name__}", "results": []}
snap_bytes = json.dumps(cap, ensure_ascii=False, indent=2).encode("utf-8")
(SA / "d_qual_search_snapshot.json").write_bytes(snap_bytes)
search_sha = sha(snap_bytes)

rows = []
for arm in ("A", "B"):
    for key, q, expect in CASES:
        rt.safe_fetch = lambda url, timeout=15.0, deadline=None, _x=xml: _x  # noqa: E731
        gw.search_exact = (lambda k: (lambda query, max_results=5, _c=cap[k]: _c))(key)
        t0 = time.monotonic()
        tr = run_tool_agent(
            gateway=gw, completion=configured_completion, question=q,
            budget=AgentBudget(max_rounds=5, max_searches=2, max_reads=2, hard_seconds=60),
            registry_sources=(("python-blog", FEED),), entry_selection=(arm == "B"),
        )
        reads = [b for b in tr["bodies"] if b["ok"] and b["chars"] > 0]
        read_urls = [b["url"] for b in reads]
        verdict = {b["url"]: (b.get("assessment") or {}).get("verdict", "") for b in reads}
        false_claim = [u for u, v in verdict.items() if v == "matches" and expect and expect not in u]
        rejected = [c for c in tr["calls"] if c.get("action", {}).get("tool") == "read_page"
                    and c.get("result", {}).get("status") == "entry_not_eligible"]
        rows.append({
            "arm": arm, "case": key, "expect": expect,
            "tools": [c["action"]["tool"] for c in tr["calls"] if c.get("action")],
            "read_urls": read_urls, "verdict": verdict, "hit": (any(expect in u for u in read_urls) if expect else None),
            "false_match_claims": false_claim, "rejected": len(rejected),
            "refusal_ok": (len(read_urls) == 0) if expect is None else None,
            "reads": tr["reads"], "searches": tr.get("searches"), "rounds": tr["rounds"],
            "stop": tr["stop_reason"], "elapsed": round(time.monotonic() - t0, 1),
        })
        print(json.dumps(rows[-1], ensure_ascii=False), flush=True)
        (SA / "d_qual_ab.json").write_text(
            json.dumps({"feed_sha256": feed_sha, "feed_error": feed_err,
                        "search_sha256": search_sha, "rows": rows}, ensure_ascii=False, indent=2),
            encoding="utf-8")
print("DONE feed=", feed_sha, feed_err, "search=", search_sha)
