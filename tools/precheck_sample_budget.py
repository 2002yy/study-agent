"""Zero-cost precheck for a paid sample run: does the budget really bound the bill?

Sends no request. It reports what the environment would enforce and compares the
configured prices against the provider's published rate card, because a cap is
only a cap if the reservation is at least as expensive as the real call.

    python tools/precheck_sample_budget.py

Exit codes: 0 all checks pass, 1 something must be fixed before spending money.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

#: DeepSeek's published rate card, CNY per 1M tokens, read from
#: https://api-docs.deepseek.com/zh-cn/quick_start/pricing (2026-10-19).
#: Peak = Mon-Fri 09:00-12:00 and 14:00-18:00 Beijing time; off-peak is half.
#: ``deepseek-flash`` is DeepSeek-V4.1-Flash-1017 and understands images
#: natively, so vision needs no separate model id.
RATE_CARD_CNY_PER_MTOK = {
    "deepseek-flash": {"input_peak": 2.0, "input_offpeak": 1.0, "output_peak": 8.0, "output_offpeak": 4.0},
    "deepseek-v4-pro": {"input_peak": 9.0, "input_offpeak": 4.5, "output_peak": 27.0, "output_offpeak": 13.5},
}
#: The run is Flash-only: the reservation is priced for this model, so anything
#: else must be refused rather than silently charged at the wrong rate.
REQUIRED_MODELS = ("deepseek-flash",)

#: A representative Deep research sample, used only to show worst-case sizes.
SAMPLE_SHAPE = {
    "planner_calls": 4,      # plan + revise per round, flash
    "answer_calls": 1,       # final answer
    "vision_calls": 1,       # one screenshot, flash vision
    "prompt_chars": 12_000,  # a round's context
    "answer_max_tokens": 2_000,
}


def _float_env(name: str) -> float | None:
    raw = os.getenv(name, "").strip()
    if not raw:
        return None
    return float(raw)


def main() -> int:
    from src.llm_spend_guard import (
        experiment_cap_cny,
        experiment_id,
        reservation_cny,
        spend_cap_cny,
    )

    input_price = _float_env("LLM_SPEND_INPUT_CNY_PER_MTOK")
    output_price = _float_env("LLM_SPEND_OUTPUT_CNY_PER_MTOK")
    process_cap = spend_cap_cny()
    experiment = experiment_id()
    experiment_cap = experiment_cap_cny()
    ledger = os.getenv("LLM_SPEND_LEDGER_DB", "(runtime database)")
    retries = os.getenv("DEEPSEEK_MAX_RETRIES") or os.getenv("LLM_MAX_RETRIES") or "2 (default)"

    print("=== configured")
    print(f"  experiment id        : {experiment or '(unset - the ledger refuses every call)'}")
    print(f"  experiment cap       : {experiment_cap}")
    print(f"  process cap          : {process_cap}")
    print(f"  ledger               : {ledger}")
    print(f"  input price          : {input_price} CNY / 1M tokens")
    print(f"  output price         : {output_price} CNY / 1M tokens")
    print(f"  provider retries     : {retries}")

    failures: list[str] = []
    if input_price is None or output_price is None:
        failures.append("pricing is not configured; a cap without pricing fails closed")
    if experiment_cap is None:
        failures.append("no experiment cap is configured, so no durable CNY limit exists")
    if not experiment:
        failures.append("no experiment id is configured")
    if ledger == "(runtime database)":
        print("  note                 : LLM_SPEND_LEDGER_DB unset; the runtime database is used")

    allowed = os.getenv("LLM_EXPERIMENT_ALLOWED_MODELS", "").strip()
    print(f"  allowed models       : {allowed or '(unrestricted - the router may pick pro)'}")
    if not allowed:
        failures.append(
            "LLM_EXPERIMENT_ALLOWED_MODELS is unset, so a hard question could be routed "
            "to a model the reservation was not priced for"
        )
    else:
        pinned = {part.strip() for part in allowed.split(",") if part.strip()}
        if pinned != set(REQUIRED_MODELS):
            failures.append(
                f"this run must be Flash-only; allowed models are {sorted(pinned)}"
            )

    print("\n=== coverage against the provider rate card (worst case = peak)")
    if input_price is not None and output_price is not None:
        for model in REQUIRED_MODELS:
            rates = RATE_CARD_CNY_PER_MTOK[model]
            ok_input = input_price >= rates["input_peak"]
            ok_output = output_price >= rates["output_peak"]
            print(
                f"  {model:<16} input {rates['input_peak']:>5} vs {input_price:>5} "
                f"{'OK' if ok_input else 'UNDER'}   "
                f"output {rates['output_peak']:>5} vs {output_price:>5} "
                f"{'OK' if ok_output else 'UNDER'}"
            )
            if not (ok_input and ok_output):
                failures.append(
                    f"{model} peak ({rates['input_peak']}/{rates['output_peak']} CNY per 1M) "
                    f"is not covered by the configured {input_price}/{output_price}"
                )

    print("\n=== vision and retrieval")
    from src.application.attachment_vision import vision_model_name

    vision = vision_model_name()
    print(f"  vision model         : {vision}")
    if vision not in REQUIRED_MODELS:
        failures.append(f"vision model {vision!r} is not one of {list(REQUIRED_MODELS)}")
    print(
        "  note                 : DeepSeek Search/Fetch become billable on 2026-11-01 "
        "(5 CNY / 1000 requests); this run must use the repository's own retrieval"
    )

    print("\n=== worst-case reservation of one representative sample")
    if input_price is not None and output_price is not None:
        planner = reservation_cny(
            prompt_chars=SAMPLE_SHAPE["prompt_chars"], max_tokens=700, attempts=3
        )
        answer = reservation_cny(
            prompt_chars=SAMPLE_SHAPE["prompt_chars"] * 3,
            max_tokens=SAMPLE_SHAPE["answer_max_tokens"],
            attempts=1,
        )
        vision = reservation_cny(
            prompt_chars=len("x") + 4096 * 2, max_tokens=1200, attempts=3
        )
        total = planner * SAMPLE_SHAPE["planner_calls"] + answer
        total += vision * SAMPLE_SHAPE["vision_calls"]
        print(f"  planner call         : {planner:.4f} CNY x {SAMPLE_SHAPE['planner_calls']}")
        print(f"  answer call          : {answer:.4f} CNY")
        print(f"  vision call          : {vision:.4f} CNY")
        print(f"  sample worst case    : {total:.4f} CNY (reserved up front, never refunded)")
        if experiment_cap is not None and total * 3 > experiment_cap:
            print(
                f"  note                 : three samples at this shape would reserve "
                f"{total * 3:.4f} CNY against a {experiment_cap} CNY cap"
            )

    print("\n=== result")
    if failures:
        for failure in failures:
            print(f"  FAIL: {failure}")
        print("PRECHECK: FAIL - do not start a paid sample yet")
        return 1
    print(
        "PRECHECK: PASS - Flash-only, and the configured reservation is at least "
        "the published flash peak"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
