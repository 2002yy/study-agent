"""Run the B-Search controlled tool agent.

Optional registry seeds come from ``config/research_entry_directory.json`` — a list
of trusted ENTRY pages (index / main pages only). Listing a domain authorises
reading THAT entry URL only; any deeper URL is still subject to the normal
discovery + confirmation + safety checks, so guessed deep links stay rejected.

Usage:
    python tools/run_research_tool_agent.py                # seeds ON (default)
    python tools/run_research_tool_agent.py --no-seeds     # seeds OFF (baseline)
    python tools/run_research_tool_agent.py --cases weiqi python
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = ROOT / "artifacts" / "b-search-run"
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv("C:/Users/Zhang/Desktop/study agent/.env")
from src.web.research_tool_agent import AgentBudget, run_tool_agent  # noqa: E402
from src.web.research.source_directory import load_directory, recall_sources  # noqa: E402
from src.web.semantic_recovery import configured_completion  # noqa: E402
from src.web.tool_gateway import GeneralWebGateway  # noqa: E402

ENTRY_DIRECTORY = ROOT / "config" / "research_entry_directory.json"

CASES: dict[str, tuple[str, list[tuple[str, list[str]]]]] = {
    "weiqi": (
        "研究围棋中打劫与提子的规则，说明禁止全局同形再现（劫争）的判定条件与例外。",
        [("打劫与提子", ["打劫", "提子", "劫"]),
         ("禁全同判定", ["全局同形", "再现", "禁着"]),
         ("例外", ["例外", "缓劫", "长生"])],
    ),
    "python": (
        "Python 3.13 新增了哪些值得注意的语言特性？列出 2-3 项并说明其对兼容性的影响。",
        [("新增特性", ["3.13", "新特性", "free-threading", "JIT"]),
         ("兼容性", ["兼容", "弃用", "removed"])],
    ),
    "minecraft": (
        "Minecraft 红石中继器的延迟档位分别对应多少游戏刻？它在红石信号中的作用是什么？",
        [("延迟档位", ["延迟", "档位", "游戏刻", "tick"]),
         ("信号作用", ["信号", "中继", "强度", "充能"])],
    ),
    "factorio": (
        "Factorio 2.0 中列车中断（interrupt）与传统固定时刻表调度有何区别？何时不应使用中断？",
        [("调度差异", ["interrupt", "中断", "时刻表", "schedule"]),
         ("不适用场景", ["不应", "不适用", "固定"])],
    ),
    # Unseen topic: not represented in the entry directory.
    "unseen-http": (
        "HTTP/2 与 HTTP/3 在队头阻塞和连接建立上的区别是什么？",
        [("队头阻塞", ["队头", "阻塞", "head-of-line"]),
         ("连接建立", ["连接", "握手", "QUIC", "TCP"])],
    ),
}


def select_seeds(index: dict, question: str, k: int = 3) -> list[tuple[str, str]]:
    """Registered ENTRY urls for a question, as (source_id, entry_url)."""
    seeds: list[tuple[str, str]] = []
    for row in recall_sources(index, question, k=k):
        url = row.get("entry_url") or row.get("xml_url")
        if url:
            seeds.append((row["source_id"], url))
    return seeds


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cases", nargs="*", default=list(CASES))
    ap.add_argument("--no-seeds", action="store_true", help="disable registry entry seeds")
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    ap.add_argument("--rounds", type=int, default=6)
    ap.add_argument("--searches", type=int, default=4)
    ap.add_argument("--reads", type=int, default=3)
    ap.add_argument("--seconds", type=float, default=60.0)
    args = ap.parse_args()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    index = {} if args.no_seeds else load_directory(ENTRY_DIRECTORY)
    budget = AgentBudget(max_rounds=args.rounds, max_searches=args.searches,
                         max_reads=args.reads, hard_seconds=args.seconds)
    gw = GeneralWebGateway()
    summary = []
    for name in args.cases:
        question, goals = CASES[name]
        seeds = select_seeds(index, question) if index else []
        trace = run_tool_agent(
            gateway=gw, completion=configured_completion, question=question,
            budget=budget, registry_sources=tuple(seeds),
            sub_goals=[(label, tuple(terms)) for label, terms in goals],
        )
        (out / f"{name}.json").write_text(json.dumps(trace, ensure_ascii=False, indent=2),
                                          encoding="utf-8")
        audit = trace.get("coverage_audit") or {}
        ok = [b for b in trace.get("bodies", []) if b.get("ok") and b.get("chars", 0) > 0]
        summary.append({
            "case": name, "seeds_off": bool(args.no_seeds),
            "seeds_injected": [f"{sid}:{url}" for sid, url in seeds],
            "trace_registry_sources": trace.get("registry_sources"),
            "stop": trace.get("stop_reason"), "rounds": trace.get("rounds"),
            "searches": trace.get("searches"), "reads": trace.get("reads"),
            "elapsed_s": round(trace.get("elapsed_seconds", 0.0), 1),
            "bodies_ok": len(ok), "body_urls": [b["url"] for b in ok],
            "sub_goals": {k: (v or {}).get("status") for k, v in (audit.get("sub_goals") or {}).items()},
            "covered_n": len(audit.get("covered", [])),
        })
        print(json.dumps(summary[-1], ensure_ascii=False), flush=True)
    (out / ("results-no-seeds.json" if args.no_seeds else "results.json")).write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
