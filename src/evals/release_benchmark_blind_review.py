"""§162 A3-A: blind reviewer packet and ingest harness.

Builds the frozen, leakage-free packet that an external independent-family
reviewer consumes, and ingests that reviewer's raw response back through the
§162 A2 validators and the shared calibration checker.

Nothing here calls a model, grants a judge, or produces an official label. The
reviewer runs in a separate isolated session and the operator bridges its raw
response back by hand, which is why the traceability tuple is explicit:

    which frozen input -> which reviewer -> which raw output -> which calibration

The packet never names a variant, never reveals how many items are controls, and
never carries a §161 verdict, an expected label, or a directional hint.
"""

from __future__ import annotations

from dataclasses import replace
from hashlib import sha256
import json
from typing import Any, Mapping, Sequence, cast

from src.evals.release_benchmark_reviewer_qualification import (
    CalibrationResult,
    ReviewObservation,
    ReviewedControl,
    ReviewerIdentity,
    ReviewerProvenance,
    ReviewerQualificationViolation,
    build_reviewer_input,
    canonical_hash,
    check_calibration,
    parse_review_observation,
    reviewer_identity_hash,
    validate_blind_input,
    validate_provenance,
    validate_reviewer_independence,
)
from src.evals.release_benchmark_semantic_controls import dimension_consistency_holds

SCHEMA_PACKET = "release-benchmark-blind-review-packet-v1"
SCHEMA_MANIFEST = "release-benchmark-blind-review-manifest-v1"
SCHEMA_INGEST = "release-benchmark-blind-review-ingest-v1"

VARIANT_ACTUAL = "actual"
CONTROL_VARIANTS = ("wrong_citation", "missing_aspect", "unsupported_claim")

# The operator moves bytes between the repository and an isolated reviewer
# session. That makes the operator transport, not a reviewer: no human verdict
# is ever recorded under this path.
TRANSPORT_MANUAL_COPY_PASTE = "manual_copy_paste"

# One vocabulary for every item. It is emitted once, at packet level, so it can
# never become a per-variant side channel.
ISSUE_TYPE_VOCABULARY = (
    "coverage_gap", "unsupported_claim", "wrong_citation", "overstatement", "other",
)

REASON_RESPONSE_SHAPE = "reviewer_response_shape_invalid"
REASON_RUN_ID_MISMATCH = "review_run_id_mismatch"
REASON_UNKNOWN_ITEM = "unknown_blind_case_id"
REASON_MISSING_ITEM = "missing_blind_case_id"
REASON_DUPLICATE_ITEM = "duplicate_blind_case_id"
REASON_SELF_REPORTED_CONSISTENCY = "reviewer_self_reported_consistency"

REVIEWER_INSTRUCTIONS = (
    "Review each item independently against only the frozen source excerpt and the "
    "fixed rubric supplied with it. Return a single JSON object with exactly two "
    "keys: review_run_id (echo the value given to you) and observations (an array "
    "with one entry per item, in any order). Each observation entry must have "
    "exactly these keys: blind_case_id (echo that item's id), question_coverage "
    "(covered|partial|unverified), evidence_grounding (supported|gap|unverified), "
    "citation_support (supported|gap|unverified), and issues (array of objects with "
    "issue_type, reason and evidence_refs). Allowed issue_type values are "
    "coverage_gap, unsupported_claim, wrong_citation, overstatement and other. "
    "evidence_refs must be an empty array or the supplied source id. Compare every "
    "Markdown citation URL against source_locator exactly; for a PDF only a matching "
    "#page=source_page suffix is permitted. An unrelated URL requires "
    "citation_support=gap with a wrong_citation issue. A citation is not proof that "
    "the source supports the sentence. Any unsupported or contradicted factual "
    "sentence requires evidence_grounding=gap with an unsupported_claim issue. If an "
    "issue reports a coverage gap, question_coverage must be partial. Never mark an "
    "axis supported while its issue reports a gap. Do not add any other keys. Judge "
    "every item on its own material. Do not state whether you are qualified, do not "
    "score yourself, and do not output any approval or label."
)

def _materialized_cases(materialized: Mapping[str, object]) -> list[dict[str, Any]]:
    cases = materialized.get("cases")
    if not isinstance(cases, list) or not cases:
        raise ValueError("materialized review cases are missing")
    return cast(list[dict[str, Any]], cases)


def build_blind_review_packet(
    materialized: Mapping[str, object],
    *,
    review_run_id: str,
    answer_bundle_sha256: str,
    registry_sha256: str,
    gold_sha256: str,
) -> dict[str, object]:
    """Return ``{"packet": ..., "manifest": ...}``.

    The packet is reviewer-facing and carries no variant, no count and no verdict.
    The manifest stays in the repository and is the only place a variant is named.
    """
    if not review_run_id.strip():
        raise ReviewerQualificationViolation(REASON_RESPONSE_SHAPE, "review_run_id")
    for label, digest in (
        ("answer_bundle_sha256", answer_bundle_sha256),
        ("registry_sha256", registry_sha256),
        ("gold_sha256", gold_sha256),
    ):
        if not isinstance(digest, str) or len(digest) != 64:
            raise ReviewerQualificationViolation(REASON_RESPONSE_SHAPE, label)
    input_manifest_hash = canonical_hash({
        "review_run_id": review_run_id,
        "answer_bundle_sha256": answer_bundle_sha256,
        "registry_sha256": registry_sha256,
        "gold_sha256": gold_sha256,
    })

    staged: list[tuple[str, dict[str, Any], str]] = []
    for case in _materialized_cases(materialized):
        case_id = str(case["case_id"])
        answers = {"actual": case["answer"]}
        answers.update(cast(Mapping[str, str], case["control_answers"]))
        for variant, answer in answers.items():
            staged.append((case_id, {"variant": variant, "answer": answer}, variant))
    # Deterministic, variant-blind ordering: the sort key hides the variant and
    # the case, so position leaks nothing about which item is a control.
    staged.sort(key=lambda row: canonical_hash(f"{review_run_id}|{row[0]}|{row[2]}"))

    packet_case_by_id = {
        str(case["case_id"]): cast(dict[str, Any], case["packet_case"])
        for case in _materialized_cases(materialized)
    }
    items = []
    manifest_items = []
    for index, (case_id, row, variant) in enumerate(staged, start=1):
        blind_case_id = f"{review_run_id}-item-{index:02d}"
        packet_case = packet_case_by_id[case_id]
        source = cast(dict[str, Any], packet_case["source"])
        items.append({
            "blind_case_id": blind_case_id,
            "question": packet_case["question"],
            "aspects": packet_case["aspects"],
            "aspect_rubric": packet_case["aspect_rubric"],
            "source_id": source["source_id"],
            "source_locator": source["locator"],
            "source_page": source["page"],
            "source_region": source["region"],
            "source_text": _source_text_for(case_id, materialized),
            "answer": row["answer"],
        })
        manifest_items.append({
            "blind_case_id": blind_case_id,
            "case_id": case_id,
            "variant": variant,
            "answer_sha256": sha256(str(row["answer"]).encode("utf-8")).hexdigest(),
        })

    packet = {
        "schema_version": SCHEMA_PACKET,
        "review_run_id": review_run_id,
        "input_manifest_hash": input_manifest_hash,
        "instructions": REVIEWER_INSTRUCTIONS,
        "items": items,
    }
    manifest = {
        "schema_version": SCHEMA_MANIFEST,
        "packet_sha256": canonical_hash(packet),
        "review_run_id": review_run_id,
        "input_manifest_hash": input_manifest_hash,
        "answer_bundle_sha256": answer_bundle_sha256,
        "registry_sha256": registry_sha256,
        "gold_sha256": gold_sha256,
        "items": manifest_items,
    }
    return {"packet": packet, "manifest": manifest}


def _source_text_for(case_id: str, materialized: Mapping[str, object]) -> str:
    for case in _materialized_cases(materialized):
        if str(case["case_id"]) == case_id:
            return str(case["source_text"])
    raise ValueError(f"unknown materialized case: {case_id}")


def render_packet_text(packet: Mapping[str, object]) -> str:
    """The exact text an operator pastes into the isolated reviewer session."""
    body = json.dumps(
        {key: value for key, value in packet.items() if key != "instructions"},
        ensure_ascii=False, sort_keys=True, indent=2,
    )
    return f"{packet['instructions']}\n\nINPUT JSON:\n{body}\n"


def _parse_response(raw_response_text: str) -> dict[str, Any]:
    try:
        payload = json.loads(raw_response_text)
    except (TypeError, ValueError) as exc:
        raise ReviewerQualificationViolation(
            REASON_RESPONSE_SHAPE, "response is not JSON"
        ) from exc
    if not isinstance(payload, dict) or set(payload) != {"review_run_id", "observations"}:
        raise ReviewerQualificationViolation(
            REASON_RESPONSE_SHAPE, "expected review_run_id and observations only"
        )
    if not isinstance(payload["observations"], list):
        raise ReviewerQualificationViolation(REASON_RESPONSE_SHAPE, "observations")
    return cast(dict[str, Any], payload)


def ingest_review_run(
    *,
    packet: Mapping[str, object],
    manifest: Mapping[str, object],
    raw_response_text: str,
    reviewer_identity: ReviewerIdentity,
    invocation_id: str,
    timestamp: str,
    answer_model_families: Sequence[str],
    transport: str = TRANSPORT_MANUAL_COPY_PASTE,
) -> dict[str, object]:
    """Validate a bridged reviewer response and score it. Grants nothing."""
    if packet.get("input_manifest_hash") != manifest.get("input_manifest_hash"):
        raise ReviewerQualificationViolation(REASON_RESPONSE_SHAPE, "manifest mismatch")
    review_run_id = str(packet.get("review_run_id", ""))
    payload = _parse_response(raw_response_text)
    if payload["review_run_id"] != review_run_id:
        raise ReviewerQualificationViolation(REASON_RUN_ID_MISMATCH)

    packet_items = {
        str(item["blind_case_id"]): cast(dict[str, Any], item)
        for item in cast(list[dict[str, Any]], packet.get("items", []))
    }
    manifest_items = {
        str(item["blind_case_id"]): cast(dict[str, Any], item)
        for item in cast(list[dict[str, Any]], manifest.get("items", []))
    }
    if set(packet_items) != set(manifest_items) or not manifest_items:
        raise ReviewerQualificationViolation(REASON_RESPONSE_SHAPE, "item set mismatch")

    seen: set[str] = set()
    observations: dict[str, ReviewObservation] = {}
    for row in cast(list[Any], payload["observations"]):
        if not isinstance(row, dict):
            raise ReviewerQualificationViolation(REASON_RESPONSE_SHAPE, "observation")
        blind_case_id = row.get("blind_case_id")
        if not isinstance(blind_case_id, str) or not blind_case_id:
            raise ReviewerQualificationViolation(REASON_MISSING_ITEM)
        if blind_case_id not in manifest_items:
            raise ReviewerQualificationViolation(REASON_UNKNOWN_ITEM, blind_case_id)
        if blind_case_id in seen:
            raise ReviewerQualificationViolation(REASON_DUPLICATE_ITEM, blind_case_id)
        seen.add(blind_case_id)
        if "dimension_consistent" in row:
            raise ReviewerQualificationViolation(
                REASON_SELF_REPORTED_CONSISTENCY, blind_case_id
            )
        item = packet_items[blind_case_id]
        reviewer_input = build_reviewer_input(
            answer_bundle_ref=str(manifest.get("answer_bundle_sha256", "")),
            source_bundle_ref=str(manifest.get("registry_sha256", "")),
            rubric_ref=str(manifest.get("gold_sha256", "")),
            control_set_ref=str(manifest.get("input_manifest_hash", "")),
            blind_case_id=blind_case_id,
            blind_payload=item,
        )
        validate_blind_input(reviewer_input, authorized_case_ids=sorted(manifest_items))
        provenance = ReviewerProvenance(
            identity=reviewer_identity,
            invocation_id=invocation_id,
            timestamp=timestamp,
            input_manifest_hash=reviewer_input.input_manifest_hash,
            rubric_hash=reviewer_input.resolved_rubric_hash(),
            controls_hash=reviewer_input.resolved_controls_hash(),
        )
        validate_provenance(provenance, reviewer_input=reviewer_input)
        validate_reviewer_independence(
            provenance, answer_model_families=answer_model_families
        )
        parsed = parse_review_observation(
            {key: value for key, value in row.items() if key != "blind_case_id"},
            provenance=provenance,
            blind_case_id=blind_case_id,
        )
        observations[blind_case_id] = replace(
            parsed,
            dimension_consistent=dimension_consistency_holds(parsed.judgment()),
        )

    missing = sorted(set(manifest_items) - seen)
    if missing:
        raise ReviewerQualificationViolation(REASON_MISSING_ITEM, ",".join(missing))

    controls = [
        ReviewedControl(str(manifest_items[blind_case_id]["variant"]), observation)
        for blind_case_id, observation in observations.items()
        if manifest_items[blind_case_id]["variant"] in CONTROL_VARIANTS
    ]
    clean = [
        observation
        for blind_case_id, observation in observations.items()
        if manifest_items[blind_case_id]["variant"] == VARIANT_ACTUAL
    ]
    calibration = check_calibration(
        reviewer_provenance=next(iter(observations.values())).provenance,
        control_observations=controls,
        clean_answer_observations=clean,
    )
    return _ingest_artifact(
        review_run_id=review_run_id,
        manifest=manifest,
        reviewer_identity=reviewer_identity,
        invocation_id=invocation_id,
        timestamp=timestamp,
        raw_response_text=raw_response_text,
        answer_model_families=answer_model_families,
        calibration=calibration,
        observations=observations,
        manifest_items=manifest_items,
        transport=transport,
    )


def _ingest_artifact(
    *,
    review_run_id: str,
    manifest: Mapping[str, object],
    reviewer_identity: ReviewerIdentity,
    invocation_id: str,
    timestamp: str,
    raw_response_text: str,
    answer_model_families: Sequence[str],
    calibration: CalibrationResult,
    observations: Mapping[str, ReviewObservation],
    manifest_items: Mapping[str, Mapping[str, object]],
    transport: str,
) -> dict[str, object]:
    items = []
    for blind_case_id, observation in sorted(observations.items()):
        verdict = next(
            (row for row in calibration.controls
             if row.variant == manifest_items[blind_case_id]["variant"]),
            None,
        )
        items.append({
            "blind_case_id": blind_case_id,
            "case_id": manifest_items[blind_case_id]["case_id"],
            "variant": manifest_items[blind_case_id]["variant"],
            "target_detected": None if verdict is None else verdict.target_detected,
            "specific": None if verdict is None else verdict.specific,
            "axes": dict(observation.axes),
        })
    return {
        "schema_version": SCHEMA_INGEST,
        "review_run_id": review_run_id,
        "input_manifest_hash": manifest.get("input_manifest_hash"),
        "output_hash": sha256(raw_response_text.encode("utf-8")).hexdigest(),
        "reviewer": reviewer_identity.to_dict(),
        "reviewer_identity_hash": reviewer_identity_hash(reviewer_identity),
        "invocation_id": invocation_id,
        "timestamp": timestamp,
        "invocation_id_kind": "harness_assigned_run_id",
        "transport": transport,
        "packet_sha256": manifest.get("packet_sha256"),
        "answer_model_families": sorted(answer_model_families),
        "independence_ok": True,
        "calibration": calibration.to_dict(),
        "calibration_pass": calibration.calibration_pass,
        "eligible_for_authority_review": calibration.eligible_for_authority_review,
        "items": items,
        "qualified_judge": False,
        "formal_semantic_label": False,
        "release_observation": False,
        "release_gate": "NO_GO",
    }
