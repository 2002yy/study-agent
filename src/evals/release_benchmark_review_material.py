"""Frozen source/answer/control materialization for independent blind review.

This is pure, deterministic packet preparation. It has no model calls, judge
classification, calibration or scoring authority. Retained from the retired
diagnostic semantic probe because the active blind-review transport uses it.
"""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path
from typing import Any, cast

from src.evals.release_benchmark_answer_pilot import build_answer_review_packet
from src.evals.release_benchmark_registry import ReleaseGold, ReleaseRegistry

_CONTROLS = ("wrong_citation", "missing_aspect", "unsupported_claim")


def _control_answer(case_id: str, answer: str, locator: str,
                    variant: str) -> str:
    if variant == "wrong_citation":
        if locator not in answer:
            raise ValueError("answer lacks registered citation")
        return answer.replace(locator, "https://invalid.example/unregistered", 1)
    if variant == "missing_aspect":
        return answer.splitlines()[0]
    if variant == "unsupported_claim":
        if case_id not in {"REL-F-TEXT-001", "REL-F-PDF-001"}:
            raise ValueError("unsupported semantic probe case")
        falsehood = (
            "The source says lunar gravity is the primary cause of storm surge."
            if case_id == "REL-F-TEXT-001" else
            "The source says the Moon does not rotate on its own axis."
        )
        return answer + f"\n{falsehood} [source]({locator})"
    raise ValueError("unknown semantic probe control")

def materialize_review_items(
    bundle: dict[str, object], registry: ReleaseRegistry, gold: ReleaseGold,
    root: Path,
) -> dict[str, object]:
    """Frozen review inputs per case: real answer plus the three controls.

    No model call and no scoring. Exposed so a blind reviewer packet can be
    built from exactly the material §161 calibrates against.
    """
    packet = build_answer_review_packet(bundle, registry, gold, root)
    cases = []
    answer_rows = cast(list[dict[str, Any]], bundle["cases"])
    packet_cases = cast(list[dict[str, Any]], packet["cases"])
    for answer_row, packet_case in zip(answer_rows, packet_cases, strict=True):
        source_text = answer_row["messages"][1]["content"].split("Source text:\n", 1)[1]
        locator = packet_case["source"]["locator"]
        cases.append({
            "case_id": packet_case["case_id"],
            "answer_model": answer_row["model"],
            "answer_provider": answer_row["provider"],
            "answer": answer_row["answer"],
            "answer_sha256": sha256(answer_row["answer"].encode("utf-8")).hexdigest(),
            "source_text": source_text,
            "packet_case": packet_case,
            "control_answers": {
                variant: _control_answer(packet_case["case_id"], answer_row["answer"],
                                         locator, variant)
                for variant in _CONTROLS
            },
        })
    return {
        "review_packet": packet,
        "answer_bundle_sha256": packet["answer_bundle_sha256"],
        "cases": cases,
    }
