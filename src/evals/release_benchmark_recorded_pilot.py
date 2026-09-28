"""Convert bounded frozen reader pilots into source-bound score observations.

These records describe reader availability. They do not invent answers, semantic
labels, a qualified vision adapter, or a manually reviewed live observation.
"""

from __future__ import annotations

from typing import Any

from src.evals.release_benchmark_plan import ReleaseBenchmarkPlan, plan_digest
from src.evals.release_benchmark_registry import ReleaseCase, ReleaseGold, ReleaseRegistry
from src.evals.release_benchmark_scoring import (
    OBSERVATION_SCHEMA_VERSION,
    parse_recording,
)

BUNDLE_SCHEMA = "release-benchmark-frozen-pilot-bundle-v1"


def _source(case: ReleaseCase):
    if len(case.sources) != 1:
        raise ValueError("recorded frozen pilot requires one registered source per case")
    return case.sources[0]


def _check_source(row: dict[str, Any], case: ReleaseCase, *, visual: bool) -> None:
    source = _source(case)
    if (row.get("locator") != source.locator
            or row.get("source_sha256") != source.sha256
            or row.get("page") != source.page
            or row.get("region") != source.region):
        raise ValueError("pilot source does not match the registered source bytes/location")
    if visual and row.get("source_id") != source.source_id:
        raise ValueError("visual pilot source ID mismatch")


def _read(row: dict[str, Any], case: ReleaseCase, at: str,
          *, state: str, reason: str | None) -> dict[str, Any]:
    source = _source(case)
    return {
        "source_id": source.source_id,
        "locator": source.locator,
        "state": state,
        "reason": reason,
        "observed_at": at,
        "page": source.page,
        "region": source.region,
        "human_reviewed_by": None,
    }


def _text_read(case: ReleaseCase, result: dict[str, Any], at: str) -> dict[str, Any]:
    if (result.get("case_id") != case.case_id
            or result.get("case_content_sha256") != case.content_sha256
            or result.get("run_status") != "completed"
            or result.get("provider_status") != "found"
            or result.get("stop_reason") != "sources_read"
            or result.get("network_guard") != "python_socket_connect_blocked"):
        raise ValueError("frozen text/PDF pilot did not complete its guarded read")
    rows = result.get("source_reads")
    if not isinstance(rows, list) or len(rows) != 1 or not isinstance(rows[0], dict):
        raise ValueError("frozen text/PDF pilot needs one source read")
    row = rows[0]
    _check_source(row, case, visual=False)
    if row.get("state") != "read":
        raise ValueError("frozen text/PDF pilot source was not read")
    # WebLookupService's local source ID is not the registry source ID. The
    # registered locator, snapshot SHA, page and region supply the binding.
    return _read(row, case, at, state="read_ok", reason=None)


def _visual_read(case: ReleaseCase, result: dict[str, Any], at: str
                 ) -> tuple[dict[str, Any], str]:
    if (result.get("case_id") != case.case_id
            or result.get("case_content_sha256") != case.content_sha256
            or result.get("network_guard") != "python_socket_connect_blocked"):
        raise ValueError("visual pilot is not bound to the frozen case")
    rows = result.get("source_outcomes")
    if not isinstance(rows, list) or len(rows) != 1 or not isinstance(rows[0], dict):
        raise ValueError("frozen visual pilot needs one source outcome")
    row = rows[0]
    _check_source(row, case, visual=True)
    reason = row.get("reason")
    if (row.get("status") != "unavailable" or not isinstance(reason, str)
            or not reason):
        raise ValueError("recorded pilot cannot qualify a visual observation")
    return _read(row, case, at, state="read_failed", reason=reason), reason


def build_frozen_pilot_observation(
    plan: ReleaseBenchmarkPlan, registry: ReleaseRegistry, gold: ReleaseGold,
    *, code_sha: str, bundle: dict[str, Any], transcript_sha256: str,
) -> dict[str, Any]:
    """Build and strictly validate one frozen observation from real pilot outputs."""
    if (set(bundle) != {"schema_version", "code_sha", "started_at", "ended_at", "pilots"}
            or bundle["schema_version"] != BUNDLE_SCHEMA or bundle["code_sha"] != code_sha
            or not isinstance(transcript_sha256, str) or len(transcript_sha256) != 64):
        raise ValueError("frozen pilot bundle binding is invalid")
    selected = [case for case in registry.cases if case.mode == "frozen"
                and any(review.case_id == case.case_id and review.structurally_reviewed
                        for review in gold.reviews)]
    pilots = bundle["pilots"]
    if (not isinstance(pilots, list) or len(pilots) != len(selected)
            or [item.get("case_id") for item in pilots if isinstance(item, dict)]
            != [case.case_id for case in selected]):
        raise ValueError("frozen pilot case scope mismatch")
    cases: list[dict[str, Any]] = []
    for case, item in zip(selected, pilots, strict=True):
        result, at = item.get("result"), item.get("observed_at")
        if not isinstance(result, dict) or not isinstance(at, str):
            raise ValueError("frozen pilot result or read time missing")
        if case.modality in {"text", "pdf"}:
            reads = [_text_read(case, result, at)]
            reason = "answer_generation_not_run"
        elif case.modality in {"image", "chart"}:
            read, reason = _visual_read(case, result, at)
            reads = [read]
        elif case.modality == "mixed":
            if result.get("case_id") != case.case_id:
                raise ValueError("mixed pilot case mismatch")
            text_result, visual_result = result.get("text_read"), result.get("visual_read")
            if not isinstance(text_result, dict) or not isinstance(visual_result, dict):
                raise ValueError("mixed pilot needs text and visual outcomes")
            text_read = _text_read(case, text_result, at)
            _, reason = _visual_read(case, visual_result, at)
            # One registered PDF source is read as text; the case remains
            # unavailable because the required visual interpretation is absent.
            reads = [text_read]
        else:
            raise ValueError("unsupported frozen pilot modality")
        cases.append({
            "case_id": case.case_id,
            "state": "unavailable",
            "reason": reason,
            "source_reads": reads,
            "metrics": {},
            "hard_failures": [],
        })
    observation = {
        "schema_version": OBSERVATION_SCHEMA_VERSION,
        "code_sha": code_sha,
        "plan_digest": plan_digest(plan),
        "registry_digest": registry.digest,
        "gold_digest": gold.digest,
        "mode": "frozen",
        "captured_at": bundle["ended_at"],
        "execution_kind": "offline_replay",
        "network_disabled": True,
        "configuration": {"pilot_kind": "frozen_reader_only",
                          "pilot_transcript_sha256": transcript_sha256,
                          "network_guard": "python_socket_connect_blocked"},
        "reader_flags": {"vision_adapter_configured": False},
        "budgets": {"max_vision_calls_per_case": 1},
        "model_versions": {"answer": "none", "vision": "none"},
        "tool_versions": {"recorded_pilot": "v1"},
        "time_window": {"started_at": bundle["started_at"],
                        "ended_at": bundle["ended_at"]},
        "cases": cases,
    }
    parse_recording(observation, plan, registry, gold, code_sha)
    return observation
