"""Convert source-bound remote answer captures to observation-v2.

This path records completed answers and mechanical source reads. It does not
import the diagnostic model probe as qualified semantic labels.
"""

from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
from typing import Any

from src.evals.release_benchmark_answer_pilot import build_answer_review_packet
from src.evals.release_benchmark_plan import ReleaseBenchmarkPlan, plan_digest
from src.evals.release_benchmark_registry import ReleaseGold, ReleaseRegistry
from src.evals.release_benchmark_scoring import (
    REMOTE_OBSERVATION_SCHEMA_VERSION,
    parse_recording,
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _json_bytes(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True,
                       separators=(",", ":")) + "\n").encode("utf-8")


def build_remote_answer_observation(
    plan: ReleaseBenchmarkPlan, registry: ReleaseRegistry, gold: ReleaseGold,
    root: Path, *, bundle: dict[str, Any], expected_code_sha: str,
) -> dict[str, Any]:
    """Bind a fresh remote answer run to two real frozen source reads."""
    packet = build_answer_review_packet(bundle, registry, gold, root)
    if bundle["code_sha"] != expected_code_sha:
        raise ValueError("remote answer code SHA is not current head")
    rows = bundle["cases"]
    if any("read_observed_at" not in row for row in rows):
        raise ValueError("remote answer lacks an exact source read time")
    models = {row["model"] for row in rows}
    providers = {row["provider"] for row in rows}
    if len(models) != 1 or len(providers) != 1:
        raise ValueError("remote answer bundle mixes provider or model identity")
    bundle_sha = sha256(_json_bytes(bundle)).hexdigest()
    cases = []
    for row, packet_case in zip(rows, packet["cases"], strict=True):
        source = packet_case["source"]
        cases.append({
            "case_id": row["case_id"], "state": "completed", "reason": None,
            "answer_sha256": sha256(row["answer"].encode("utf-8")).hexdigest(),
            "source_reads": [{
                "source_id": source["source_id"], "locator": source["locator"],
                "state": "read_ok", "reason": None,
                "observed_at": row["read_observed_at"],
                "page": source["page"], "region": source["region"],
                "human_reviewed_by": None,
            }],
            "metrics": {}, "hard_failures": [],
        })
    observation = {
        "schema_version": REMOTE_OBSERVATION_SCHEMA_VERSION,
        "code_sha": expected_code_sha,
        "plan_digest": plan_digest(plan),
        "registry_digest": registry.digest,
        "gold_digest": gold.digest,
        "mode": "frozen",
        "captured_at": _now(),
        "execution_kind": "frozen_source_remote_inference",
        "network_disabled": False,
        "source_network_disabled": True,
        "inference_network": "remote_model_api",
        "answer_bundle_sha256": bundle_sha,
        "configuration": {"pilot_kind": "frozen_source_remote_answer",
                          "answer_bundle_sha256": bundle_sha,
                          "source_guard": "python_socket_connect_blocked",
                          "provider": next(iter(providers))},
        "reader_flags": {"vision_adapter_configured": False},
        "budgets": {"max_answer_calls_per_case": 1},
        "model_versions": {"answer": next(iter(models)), "vision": "none"},
        "tool_versions": {"remote_observation": "v2"},
        "time_window": {"started_at": min(row["started_at"] for row in rows),
                        "ended_at": max(row["model_ended_at"] for row in rows)},
        "cases": cases,
    }
    parse_recording(observation, plan, registry, gold, expected_code_sha)
    return observation
