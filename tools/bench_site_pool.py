"""Measure the site pool's cost and yield on a fixed question set.

Browser-only: no model call, so it can be re-run whenever routing or a site
adapter changes. It records, per question, the wall time, which sites actually
ran, how many *new* results each site contributed after de-duplication, and how
many distinct hosts the answer would see.

    python tools/bench_site_pool.py --out D:/study-agent-validation/bench.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
import statistics
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.web.tool_gateway import GeneralWebGateway

QUESTIONS: tuple[tuple[str, str], ...] = (
    ("technical", "SQLite WAL 多个进程并发写入 会锁住吗"),
    ("technical", "FastAPI 多 worker 场景 SQLite database is locked"),
    ("technical", "PostgreSQL 与 SQLite 迁移 需要考虑什么"),
    ("community", "RTX 5090 值得买吗 价格 实测"),
    ("community", "OpenCode 和 Codex 哪个更适合大型项目"),
    ("community", "MacBook 还是 Windows 笔记本 开发 体验"),
    ("game", "星铁 流萤 配队 推荐"),
    ("game", "原神 纳西妲 配队 推荐"),
    ("game", "Steam 新游 值得买吗 评价"),
    ("tutorial", "Windows 上部署 OpenCode 教程"),
    ("tutorial", "本地大模型 量化 显存 需求"),
    ("ai", "Codex API 中转 有哪些坑"),
)


def _percentile(values: list[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round(fraction * (len(ordered) - 1))))
    return ordered[index]


def run(questions=QUESTIONS) -> dict:
    rows = []
    for domain, question in questions:
        gateway = GeneralWebGateway(search_strategy="browse_sites")
        started = time.monotonic()
        outcome = gateway.search_exact(question)
        seconds = round(time.monotonic() - started, 2)
        hosts = sorted({
            row["url"].split("/")[2]
            for row in outcome.get("results", [])
            if row.get("url", "").count("/") >= 2
        })
        rows.append({
            "domain": domain,
            "question": question,
            "seconds": seconds,
            "route": outcome.get("site_route"),
            "outcomes": outcome.get("site_outcomes"),
            "results": len(outcome.get("results", [])),
            "distinct_hosts": hosts,
            "errors": outcome.get("provider_errors"),
        })
        fresh = sum(
            item.get("new_results", 0) for item in outcome.get("site_outcomes") or []
        )
        print(
            f"{domain:10} {seconds:6.2f}s  sites="
            f"{len(outcome.get('site_outcomes') or [])} fresh={fresh} "
            f"hosts={len(hosts)}  {question}",
            flush=True,
        )
    times = [row["seconds"] for row in rows]
    return {
        "measured_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "questions": rows,
        "summary": {
            "count": len(rows),
            "median_seconds": round(statistics.median(times), 2) if times else 0.0,
            "p95_seconds": _percentile(times, 0.95),
            "mean_seconds": round(statistics.fmean(times), 2) if times else 0.0,
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True)
    parser.add_argument("--limit", type=int, default=0, help="first N questions only")
    args = parser.parse_args(argv)

    questions = QUESTIONS[: args.limit] if args.limit else QUESTIONS
    report = run(questions)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    summary = report["summary"]
    print(
        f"{summary['count']} questions: median {summary['median_seconds']}s, "
        f"p95 {summary['p95_seconds']}s, mean {summary['mean_seconds']}s"
    )
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
