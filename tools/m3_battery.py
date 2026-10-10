"""M3 qualification battery for B-Search — EVALUATION ONLY.

Frozen contract: 4 anchor topics + 6 unseen topics, each run under two budgets
recorded separately (default 6/4/3/60 and enhanced 10/3/6/120). No product code is
modified; this only drives the shipped subsystem and records traceable evidence.

Usage:
    python tools/m3_battery.py                # both budgets
    python tools/m3_battery.py --budget default
    python tools/m3_battery.py --only anchor-weiqi
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv  # noqa: E402

load_dotenv(os.environ.get("STUDY_AGENT_ENV", str(ROOT / ".env")))
from src.web.research.source_directory import load_directory, recall_sources  # noqa: E402
from src.web.research_tool_agent import AgentBudget, run_tool_agent  # noqa: E402
from src.web.semantic_recovery import configured_completion  # noqa: E402
from src.web.tool_gateway import GeneralWebGateway  # noqa: E402

ENTRY_DIRECTORY = ROOT / "config" / "research_entry_directory.json"

BATTERY = [
    {"id": "anchor-weiqi", "kind": "anchor",
     "question": "研究围棋中打劫与提子的规则，说明禁止全局同形再现（劫争）的判定条件与例外。",
     "sub_goals": {"打劫与提子": ["打劫", "提子"], "禁全同判定": ["全局同形", "再现", "禁着"],
                   "例外": ["例外", "缓劫", "长生"]}},
    {"id": "anchor-python", "kind": "anchor",
     "question": "Python 3.13 新增了哪些值得注意的语言特性？列出 2-3 项并说明其对兼容性的影响。",
     "sub_goals": {"新增特性": ["3.13", "free-threading", "JIT", "新特性"],
                   "兼容性": ["兼容", "弃用", "removed"]}},
    {"id": "anchor-minecraft", "kind": "anchor",
     "question": "Minecraft 红石中继器的延迟档位分别对应多少游戏刻？它在红石信号中的作用是什么？",
     "sub_goals": {"延迟档位": ["延迟", "档位", "游戏刻", "tick"], "信号作用": ["信号", "中继", "充能"]}},
    {"id": "anchor-factorio", "kind": "anchor",
     "question": "Factorio 2.0 中列车中断（interrupt）与传统固定时刻表调度有何区别？何时不应使用中断？",
     "sub_goals": {"调度差异": ["interrupt", "中断", "时刻表", "schedule"],
                   "不适用场景": ["不应", "不适用", "固定"]}},
    {"id": "unseen-git", "kind": "unseen",
     "question": "git rebase 与 git merge 在提交历史与冲突处理上的区别是什么？什么情况下不应使用 rebase？",
     "sub_goals": {"历史差异": ["rebase", "merge", "历史", "线性"],
                   "不应使用": ["公共分支", "共享", "风险", "不应"]}},
    {"id": "unseen-tcp", "kind": "unseen",
     "question": "TCP 建立连接为什么是三次握手而不是两次或四次？第三次握手的作用是什么？",
     "sub_goals": {"三次原因": ["三次", "两次", "握手"], "第三次作用": ["第三次", "确认", "SYN-ACK"]}},
    {"id": "unseen-coffee", "kind": "unseen",
     "question": "手冲咖啡中研磨度、水温与萃取时间如何影响萃取率与风味？过萃与欠萃如何区分？",
     "sub_goals": {"参数影响": ["研磨", "水温", "萃取时间"], "过萃欠萃": ["过萃", "欠萃", "苦", "酸"]}},
    {"id": "unseen-redis", "kind": "unseen",
     "question": "Redis 为什么采用单线程处理命令？它的性能瓶颈在哪里？",
     "sub_goals": {"单线程原因": ["单线程", "内存", "顺序"], "瓶颈": ["瓶颈", "网络", "IO", "持久化"]}},
    {"id": "unseen-k8s", "kind": "unseen",
     "question": "Kubernetes 中 liveness、readiness 与 startup 探针的区别是什么？误用会造成什么后果？",
     "sub_goals": {"三者区别": ["liveness", "readiness", "startup"],
                   "误用后果": ["重启", "误用", "流量", "后果"]}},
    {"id": "unseen-chess", "kind": "unseen",
     "question": "中国象棋与国际象棋中「将/王」的移动规则与受限方式有何区别？",
     "sub_goals": {"移动规则": ["将", "王", "宫", "九宫"], "受限方式": ["照面", "将军", "逼和", "限制"]}},
]

BUDGETS = {
    "default": AgentBudget(max_rounds=6, max_searches=4, max_reads=3, hard_seconds=60.0),
    "enhanced": AgentBudget(max_rounds=10, max_searches=3, max_reads=6, hard_seconds=120.0),
}


#: Persist the text the run actually read (bounded by the reader's visible cap) so
#: an audit never substitutes a later re-fetch for the same-run evidence.
CAPTURE_FULL_TEXT = True


def precheck() -> tuple[bool, str]:
    """Refuse to run an invalid evaluation instead of producing silent no-ops.

    A missing env/model makes the agent burn rounds with zero searches and look
    like a legitimate 0-result run. That is worse than no run at all, so the
    battery must fail loudly *before* executing anything.
    """
    env_path = os.environ.get("STUDY_AGENT_ENV") or str(ROOT / ".env")
    if not Path(env_path).is_file():
        return False, f"env_file_missing:{env_path}"
    load_dotenv(env_path)
    has_key = bool((os.environ.get("OPENAI_API_KEY") or "").strip())
    if not has_key:
        return False, "model_credentials_missing"
    return True, "ok"


def seeds_for(index: dict, question: str) -> list[tuple[str, str]]:
    out = []
    for row in recall_sources(index, question, k=3):
        url = row.get("entry_url") or row.get("xml_url")
        if url:
            out.append((row["source_id"], url))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--budget", default="both", choices=["default", "enhanced", "both"])
    ap.add_argument("--only", nargs="*")
    ap.add_argument("--out", default=str(ROOT / "artifacts" / "m3"))
    args = ap.parse_args()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    ok, reason = precheck()
    if not ok:
        print(json.dumps({"run_status": "INVALID_RUN", "reason": reason}), flush=True)
        return 2
    index = load_directory(ENTRY_DIRECTORY)
    gw = GeneralWebGateway()
    budgets = ["default", "enhanced"] if args.budget == "both" else [args.budget]
    cases = [c for c in BATTERY if not args.only or c["id"] in args.only]

    for bname in budgets:
        for case in cases:
            seeds = seeds_for(index, case["question"])
            t0 = time.time()
            trace = run_tool_agent(
                gateway=gw, completion=configured_completion, question=case["question"],
                budget=BUDGETS[bname], registry_sources=tuple(seeds),
                sub_goals=[(label, tuple(terms)) for label, terms in case["sub_goals"].items()],
                capture_full_text=CAPTURE_FULL_TEXT,
            )
            (out / f"{case['id']}.{bname}.json").write_text(
                json.dumps(trace, ensure_ascii=False, indent=2), encoding="utf-8")
            audit = trace.get("coverage_audit") or {}
            bodies = [b for b in trace.get("bodies", []) if b.get("ok") and b.get("chars", 0) > 0]
            print(json.dumps({
                "case": case["id"], "kind": case["kind"], "budget": bname,
                "stop": trace.get("stop_reason"), "rounds": trace.get("rounds"),
                "searches": trace.get("searches"), "reads": trace.get("reads"),
                "elapsed": round(trace.get("elapsed_seconds", time.time() - t0), 1),
                "seeds": [u for _s, u in seeds], "bodies": len(bodies),
                "body_urls": [b.get("url") for b in bodies],
                "sub_goal_status": {k: (v or {}).get("status") for k, v in (audit.get("sub_goals") or {}).items()},
                "covered_n": len(audit.get("covered", [])),
                # Honest evidence labelling: the trace only carries a bounded
                # preview, so a shadow/at-a-distance audit must not be mistaken for
                # a full-text verdict, and no run may self-grant authority.
                "evidence_capture": "full_text" if CAPTURE_FULL_TEXT else "preview_only",
                "evidence_completion": "UNVERIFIED",
            }, ensure_ascii=False), flush=True)
            # evidence view: matched excerpt per sub-goal from the read bodies
            lower_bodies = [(b.get("url", ""), (b.get("preview") or "")) for b in bodies]
            for label, terms in case["sub_goals"].items():
                hits = []
                for url, prev in lower_bodies:
                    low = prev.lower()
                    if any(t.lower() in low for t in terms):
                        i = min((low.find(t.lower()) for t in terms if t.lower() in low), default=0)
                        hits.append({"url": url, "snippet": prev[max(0, i - 60): i + 200]})
                print(json.dumps({"evidence": case["id"], "budget": bname, "sub_goal": label,
                                  "hits": hits[:2]}, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
