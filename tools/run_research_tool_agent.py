"""Run the B-Search-2 controlled tool agent on the three natural cases."""
import json
import sys
from pathlib import Path

ROOT = Path("D:/study-agent-validation/model-driven-research-entry")
OUT = Path(r"D:/study-agent-validation/reading-notebook-ui-evidence/model-driven-tool-agent-1")
OUT.mkdir(exist_ok=True)
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv  # noqa: E402

load_dotenv("C:/Users/Zhang/Desktop/study agent/.env")
from src.web.research_tool_agent import AgentBudget, run_tool_agent  # noqa: E402
from src.web.semantic_recovery import configured_completion  # noqa: E402
from src.web.tool_gateway import GeneralWebGateway  # noqa: E402

CASES = [
    ("energy", "比较空气源和地源热泵在寒冷气候下的工作机制、安装条件与效率限制。区分设备效率和建筑总能耗，不假定某种方案总是最优。"),
    ("history", "研究明治初期地租改正的时间线、计税方式和对农民负担的影响。区分制度条文与实际执行，并说明证据不足的部分。"),
    ("factory", "比较 Factorio 2.0 中列车中断与传统固定时刻表的调度机制及适用条件。区分基础游戏与 Space Age 扩展，解释何时不应使用中断。"),
]
gw = GeneralWebGateway()
results = []
for name, question in CASES:
    trace = run_tool_agent(
        gateway=gw, completion=configured_completion, question=question,
        budget=AgentBudget(),
    )
    (OUT / f"{name}-agent.json").write_text(json.dumps(trace, ensure_ascii=False, indent=2), encoding="utf-8")
    real_bodies = [b for b in trace["bodies"] if b["ok"] and b["chars"] > 0]
    results.append({k: trace[k] for k in ("stop_reason", "rounds", "searches", "reads", "elapsed_seconds")}
                   | {"case": name, "bodies_ok": len(real_bodies),
                      "body_urls": [b["url"] for b in real_bodies]})
    print(json.dumps(results[-1], ensure_ascii=False), flush=True)
(OUT / "results.json").write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
