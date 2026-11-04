"""Prepare a reproducible M4-C3 manifest offline; never authorize or send calls."""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
from contextlib import closing
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.interactive_history import INTERACTIVE_CAPABILITY_MARKER  # noqa: E402
from src.performance_budget import interactive_reply_budget  # noqa: E402

TASKS = {
    "J01": "演示 Java 两个引用共享一个对象，再将其中一个引用重新指向新对象；可逐步操作并看清引用、对象和箭头的变化。",
    "J02": "演示 Java 多态：Animal 类型变量引用 Dog 对象，调用 sound 方法，展示实际执行的方法。",
    "A01": "逐步演示在有序数组 [1,3,5,7,9] 中二分查找 7，显示每步边界、检查索引和结果。",
    "A02": "逐步演示 Dijkstra 求 A 到 D 的最短路：无向图 A-B=2、A-C=5、B-C=1、C-D=3、B-D=7，显示距离和路径。",
    "D01": "演示数据库事务：账户初始余额 A=100、B=40，从 A 向 B 转账 30；可分别操作提交和回滚，观察余额及事务状态。",
    "D02": "演示丢失更新：库存初始为 10，两个事务各减 1；可对比交错读写与串行执行的过程及最终库存。",
    "C01": "演示信号量：两个许可、三个任务同时请求；展示运行与等待队列，允许释放许可观察排队任务。",
    "M01": "可交互演示 y=2x+1，调整 x 并观察曲线上的点和数值；至少能取 x=3 与 x=-1。",
    "M02": "可交互演示 y=x²-4，显示零点和顶点，可将常数项调整为 -1，观察曲线及零点变化。",
    "P01": "用画布演示简谐运动 x=2sin(φ)，带位置刻度，可设置 φ=0、π/2、π，并可播放和暂停。",
    "S01": "可交互演示混淆矩阵 TP=40、FP=10、FN=20、TN=30，显示精确率、召回率及计算关系。",
    "N01": "逐步演示 TCP 三次握手，标明客户端、服务端、SYN/ACK、消息先后及箭头方向。",
}


def ledger_snapshot(path: Path, experiment: str) -> dict:
    """Read a single SQLite snapshot without migrations or creating a missing DB."""
    with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)) as db:
        db.execute("PRAGMA query_only=ON")
        db.execute("BEGIN")
        budget = db.execute(
            "SELECT cap_micros FROM llm_spend_experiments WHERE experiment_id=?",
            (experiment,),
        ).fetchone()
        if budget is None or budget[0] != 30_000_000:
            raise ValueError("shared experiment missing or cap differs from CNY 30")
        total, count = db.execute(
            "SELECT COALESCE(SUM(amount_micros),0),COUNT(*) "
            "FROM llm_spend_reservations WHERE experiment_id=?",
            (experiment,),
        ).fetchone()
        if total < 0 or total > budget[0]:
            raise ValueError("invalid reserved total")
        return {
            "experiment_id": experiment,
            "cap_micros": budget[0],
            "reserved_micros": total,
            "remaining_micros": budget[0] - total,
            "reservation_count": count,
            "meaning": "read-only historical reservations, not billed cost or authorization",
        }


def build_manifest() -> dict:
    cases = []
    for task_id, task in TASKS.items():
        prompt = (
            "请制作可交互的界面演示以下任务："
            + task
            + "界面须适配桌面和手机，字号至少14px、操作控件至少40px，不得横向溢出。"
        )
        budget = interactive_reply_budget(
            700, [{"role": "system", "content": INTERACTIVE_CAPABILITY_MARKER}], prompt
        )
        cases.append(
            {
                "task_id": task_id,
                "invocation_key": f"m4c3-v1:{task_id}:first",
                "prompt": prompt,
                "prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
                "offline_budget": budget,
            }
        )
    return {
        "schema_version": "m4c3-plan-v1",
        "execution": "not_started",
        "paid_authorized": False,
        "proposed_limits": {
            "calls": 12,
            "per_call_micros": 1_000_000,
            "batch_micros": 12_000_000,
            "shared_micros": 30_000_000,
        },
        "sampling": {
            "temperature": 0.7,
            "top_p": "provider_default_not_sent",
            "seed": "not_sent",
        },
        "cases": cases,
        "blocking_gates": [
            "explicit_paid_authorization",
            "verify_provider_model_version_and_current_pricing",
            "enforce_batch_call_count_and_money_limits_before_send",
            "freeze_actual_product_requests_and_budget_tiers_offline",
            "sandbox_replay_with_explicit_indeterminate_for_unsupported_tasks",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--ledger", type=Path)
    parser.add_argument("--experiment", default="study-agent-live-20261102")
    args = parser.parse_args()
    report = build_manifest()
    if args.ledger:
        report["ledger_observation"] = ledger_snapshot(args.ledger, args.experiment)
    # Exclusive create: never overwrite prompts/evidence from an existing batch.
    with args.out.open("x", encoding="utf-8") as output:
        json.dump(report, output, ensure_ascii=False, indent=2)
        output.write("\n")
    print(
        f"Prepared {len(report['cases'])} tasks; paid_authorized=false; no calls sent"
    )


if __name__ == "__main__":
    main()
