"""Thin harness for the three Flash-only research samples.

It orchestrates what already exists - the app's own Deep research chain, the
durable spend ledger and the evidence reader - and adds nothing to the product.
It never contacts a provider unless it is asked to execute *and* the paid run has
been confirmed explicitly:

    python tools/run_sample_research.py                 # dry run: no request
    python tools/run_sample_research.py --execute       # paid, needs confirmation

``--execute`` refuses to run unless ``LLM_SAMPLE_PAID_RUN_CONFIRMED=1`` is set,
and it refuses if the zero-cost precheck does not pass first.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

EXPERIMENT_ENV = "LLM_SPEND_EXPERIMENT_ID"
CONFIRM_ENV = "LLM_SAMPLE_PAID_RUN_CONFIRMED"


@dataclass(frozen=True)
class Sample:
    key: str
    question: str
    supplement: str
    attachment: str | None
    #: What the reader must judge from the run's evidence.
    acceptance: str


SAMPLES = (
    Sample(
        key="photoshop-automation",
        question="比较 Photoshop 与开源替代品在批量导出上的差异",
        supplement="再考虑一下 Agent 自动编辑：脚本接口能不能批量改图层？这会不会改变上面的比较标准？",
        attachment=None,
        acceptance="能否理解补充改变了哪些比较标准，而不只是复述原问题",
    ),
    Sample(
        key="game-guide-supplement",
        question="整理一款开放世界游戏的进阶攻略要点",
        supplement="我补充一点：只用单手手柄能完成吗？把这条限制并进已有攻略要求里重新研究。",
        attachment=None,
        acceptance="能否继承已有攻略需求并结合新增限制重新研究",
    ),
    Sample(
        key="coding-question-supplement",
        question="Python 里怎么做结构化并发（结构化并发库选型）",
        supplement="补一句：项目已经在用 asyncio，不要引入新的运行时。区分哪些是已有结论、哪些还需验证。",
        attachment="screenshot",
        acceptance="能否区分已有结论、待验证事实与用户新约束（含一张截图）",
    ),
)


def _precheck() -> int:
    from tools.precheck_sample_budget import main as precheck_main

    return precheck_main()


def _config_report() -> dict[str, object]:
    from src.application.attachment_vision import vision_model_name
    from src.llm_spend_guard import (
        allowed_models,
        experiment_cap_cny,
        experiment_id,
        spend_cap_cny,
    )

    return {
        "experiment_id": experiment_id(),
        "experiment_cap": experiment_cap_cny(),
        "process_cap": spend_cap_cny(),
        "allowed_models": sorted(allowed_models() or []),
        "vision_model": vision_model_name(),
        "ledger": os.getenv("LLM_SPEND_LEDGER_DB", "(runtime database)"),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true", help="run the paid samples")
    parser.add_argument(
        "--sample", default="", help="run one sample by key (default: all three)"
    )
    args = parser.parse_args(argv)

    print("=== configuration")
    config = _config_report()
    for key, value in config.items():
        print(f"  {key:<16}: {value}")

    print("\n=== zero-cost precheck")
    if _precheck() != 0:
        print("refusing to continue: the precheck did not pass")
        return 1

    selected = [s for s in SAMPLES if not args.sample or s.key == args.sample]
    print(f"\n=== samples ({len(selected)})")
    for sample in selected:
        print(f"  {sample.key}")
        print(f"    question   : {sample.question}")
        print(f"    supplement : {sample.supplement}")
        print(f"    attachment : {sample.attachment or '-'}")
        print(f"    acceptance : {sample.acceptance}")

    if not args.execute:
        print(
            "\nDRY RUN - no request was sent. The paid path stays closed until the "
            f"run is confirmed ({CONFIRM_ENV}=1)."
        )
        return 0

    if os.getenv(CONFIRM_ENV, "").strip() != "1":
        print(
            f"\nREFUSED: --execute requires {CONFIRM_ENV}=1. A paid run is an "
            "operator decision, not a default."
        )
        return 1

    print("\n=== executing the paid samples")
    print(
        "  entry: the app's own chat stream with research_mode=deep, then one "
        "mid-run supplement; the third sample attaches a screenshot."
    )
    print(
        "  evidence per sample: G1/G2/final-answer text, their real visible times "
        "(browser clock), and the ledger delta."
    )
    before = _spend()
    print(f"  ledger before: {json.dumps(before, sort_keys=True)}")
    print(
        "  note: this harness does not drive a browser itself. Run the samples "
        "through the app UI/API with the same env, then re-run this command "
        "without --execute to re-read the ledger."
    )
    return 0


def _spend() -> dict[str, int] | None:
    from src.llm_spend_guard import experiment_spend, experiment_id

    if not experiment_id():
        return None
    try:
        return experiment_spend(experiment_id())
    except Exception as exc:  # noqa: BLE001 - a missing experiment is not fatal here
        return {"error": str(exc)[:120]}


if __name__ == "__main__":
    raise SystemExit(main())
