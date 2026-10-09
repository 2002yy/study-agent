"""B-Search-2B9: cross-topic research probe with FULL-TEXT capture.

Real deepseek-flash, live channels. For each cross-topic task, run the semantic agent
(arm C), then re-fetch every selected URL at full length (>=6000 chars) and record
length / SHA256 / source URL / final URL / truncation — so bodies are auditable, not
the 600-char preview. Python is kept only as a regression reference.
"""
import hashlib
import json
import sys
import time
from pathlib import Path

ROOT = Path("D:/study-agent-validation/model-driven-research-entry")
OUT = Path("D:/study-agent-validation/reading-notebook-ui-evidence/model-driven-search-2b9")
OUT.mkdir(parents=True, exist_ok=True)
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv  # noqa: E402

load_dotenv("C:/Users/Zhang/Desktop/study agent/.env")
from src.web.research_tool_agent import AgentBudget, run_tool_agent  # noqa: E402
from src.web.semantic_recovery import configured_completion  # noqa: E402
from src.web.tool_gateway import GeneralWebGateway  # noqa: E402

TASKS = [
    ("factorio", "Factorio 2.0 中“列车中断（train interrupts）”与传统固定时刻表调度机制的区别，"
                 "并说明何时不应使用中断。区分基础游戏与 Space Age 扩展。"),
    ("go_rules", "围棋中“提子”和“打劫”的规则分别是什么？说明二者的区别。"
                 "注意：这里指围棋，不是 Go 编程语言。"),
    ("python_reference", "Python 3.15.0 正式发布说明"),
]
gw = GeneralWebGateway()
rows = []
for key, question in TASKS:
    t0 = time.monotonic()
    trace = run_tool_agent(
        gateway=gw, completion=configured_completion, question=question,
        budget=AgentBudget(max_rounds=6, max_searches=3, max_reads=3, hard_seconds=90),
        entry_selection=True, assessment_feedback=True,
    )
    full = []
    for b in trace["bodies"]:
        if not (b.get("ok") and b.get("chars")):
            continue
        url = b["url"]
        try:
            r = gw.read(url, max_chars=20000, timeout=15)
            text = str(r.get("content") or r.get("readme") or "")
            full.append({
                "source_url": url, "final_url": str(r.get("url") or url),
                "ok": bool(r.get("ok")), "chars": len(text),
                "reported_chars": b.get("chars"),
                "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                "truncated": len(text) >= 20000,
                "head": text[:1500],
            })
        except Exception as exc:  # noqa: BLE001
            full.append({"source_url": url, "ok": False, "error": f"{type(exc).__name__}: {exc}"})
    row = {
        "task": key, "question": question, "stop": trace["stop_reason"], "rounds": trace["rounds"],
        "searches": trace.get("searches"), "reads": trace["reads"],
        "tools": [c["action"]["tool"] for c in trace["calls"] if c.get("action")],
        "read_urls": [b["url"] for b in trace["bodies"] if b.get("ok") and b.get("chars")],
        "rejections": sum(1 for c in trace["calls"] if c.get("action", {}).get("tool") == "read_page"
                          and c.get("result", {}).get("status") == "entry_not_eligible"),
        "full_text": full, "elapsed": round(time.monotonic() - t0, 1),
    }
    rows.append(row)
    print(json.dumps({k: row[k] for k in ("task", "stop", "rounds", "reads", "read_urls",
                                          "rejections", "elapsed")}, ensure_ascii=False), flush=True)
    (OUT / "crosstopic.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
print("DONE")
