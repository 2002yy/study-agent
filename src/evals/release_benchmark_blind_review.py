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
from pathlib import Path
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
SCHEMA_HOLDOUT_PACKET = "release-benchmark-qualification-holdout-packet-v1"
SCHEMA_HOLDOUT_MANIFEST = "release-benchmark-qualification-holdout-manifest-v1"
SCHEMA_HOLDOUT_INGEST = "release-benchmark-qualification-holdout-ingest-v1"

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


def _manifest_refs(manifest: Mapping[str, object]) -> tuple[str, str, str]:
    """Frozen references a reviewer input binds to.

    Composite manifests declare ``frozen_refs``; single-run manifests keep the
    legacy triple so their already-recorded manifest hashes still validate.
    """
    refs = manifest.get("frozen_refs")
    if isinstance(refs, Mapping) and refs:
        ordered = [str(refs[key]) for key in sorted(refs)]
        while len(ordered) < 3:
            ordered.append("")
        return ordered[0], ordered[1], ordered[2]
    return (
        str(manifest.get("answer_bundle_sha256", "")),
        str(manifest.get("registry_sha256", "")),
        str(manifest.get("gold_sha256", "")),
    )


def _validated_observations(
    *,
    packet: Mapping[str, object],
    manifest: Mapping[str, object],
    raw_response_text: str,
    reviewer_identity: ReviewerIdentity,
    invocation_id: str,
    timestamp: str,
    answer_model_families: Sequence[str],
    raw_response_bytes: bytes | None = None,
) -> tuple[str, dict[str, dict[str, Any]], dict[str, dict[str, Any]],
           dict[str, ReviewObservation]]:
    """Validate a bridged response into per-item observations. Grants nothing."""
    if raw_response_bytes is not None:
        if raw_response_bytes.decode("utf-8") != raw_response_text:
            raise ReviewerQualificationViolation(
                REASON_RESPONSE_SHAPE, "raw bytes do not match the parsed text"
            )
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

    ref_a, ref_b, ref_c = _manifest_refs(manifest)
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
        reviewer_input = build_reviewer_input(
            answer_bundle_ref=ref_a,
            source_bundle_ref=ref_b,
            rubric_ref=ref_c,
            control_set_ref=str(manifest.get("input_manifest_hash", "")),
            blind_case_id=blind_case_id,
            blind_payload=packet_items[blind_case_id],
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
    return review_run_id, packet_items, manifest_items, observations


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
    raw_response_bytes: bytes | None = None,
) -> dict[str, object]:
    """Validate a bridged reviewer response and score it. Grants nothing.

    `raw_response_bytes` is the operator-supplied payload exactly as received.
    When given it must decode to `raw_response_text` and it is what gets hashed,
    so the recorded `output_hash` always describes the original bytes rather
    than a newline-normalised re-encoding.
    """
    review_run_id, _, manifest_items, observations = _validated_observations(
        packet=packet,
        manifest=manifest,
        raw_response_text=raw_response_text,
        reviewer_identity=reviewer_identity,
        invocation_id=invocation_id,
        timestamp=timestamp,
        answer_model_families=answer_model_families,
        raw_response_bytes=raw_response_bytes,
    )

    control_ids = [
        blind_case_id for blind_case_id, _ in observations.items()
        if manifest_items[blind_case_id]["variant"] in CONTROL_VARIANTS
    ]
    controls = [
        ReviewedControl(str(manifest_items[blind_case_id]["variant"]),
                        observations[blind_case_id])
        for blind_case_id in control_ids
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
        raw_response_bytes=raw_response_bytes,
        answer_model_families=answer_model_families,
        calibration=calibration,
        observations=observations,
        manifest_items=manifest_items,
        control_ids=control_ids,
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
    raw_response_bytes: bytes | None,
    answer_model_families: Sequence[str],
    calibration: CalibrationResult,
    observations: Mapping[str, ReviewObservation],
    manifest_items: Mapping[str, Mapping[str, object]],
    control_ids: Sequence[str],
    transport: str,
) -> dict[str, object]:
    # Verdicts are positional: the checker returns one verdict per control
    # observation, in the order they were supplied. Matching on variant alone
    # would attribute the first verdict of a variant to every item sharing it.
    verdicts = dict(zip(control_ids, calibration.controls, strict=True))
    items = []
    for blind_case_id, observation in sorted(observations.items()):
        verdict = verdicts.get(blind_case_id)
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
        "output_hash": sha256(
            raw_response_bytes if raw_response_bytes is not None
            else raw_response_text.encode("utf-8")
        ).hexdigest(),
        "raw_response_bytes_preserved": raw_response_bytes is not None,
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

# ------------------------------------------------- composite holdout transport


def _cluster_fixture_path(root: Path, cluster: Mapping[str, object]) -> Path:
    relative = str(cluster.get("manifest", ""))
    if not relative:
        raise ReviewerQualificationViolation(REASON_RESPONSE_SHAPE, "cluster manifest")
    return root / relative


def build_holdout_packet(
    *, composite: Mapping[str, object], root: Path, review_run_id: str
) -> dict[str, object]:
    """Build one blind packet over every cluster of a composite holdout.

    The reviewer-visible packet carries no cluster label, no per-cluster count,
    no gate rule and no composite structure: those live only in the manifest.
    """
    if not review_run_id.strip():
        raise ReviewerQualificationViolation(REASON_RESPONSE_SHAPE, "review_run_id")
    clusters = cast(list[dict[str, Any]], composite.get("clusters", []))
    if not clusters:
        raise ReviewerQualificationViolation(REASON_RESPONSE_SHAPE, "composite clusters")

    staged: list[tuple[str, str, dict[str, Any]]] = []
    source_digests: dict[str, str] = {}
    fixture_digests: dict[str, str] = {}
    for cluster in clusters:
        cluster_id = str(cluster["cluster_id"])
        fixture = json.loads(_cluster_fixture_path(root, cluster).read_text(encoding="utf-8"))
        if fixture.get("content_sha256") != cluster.get("content_sha256"):
            raise ReviewerQualificationViolation(
                REASON_RESPONSE_SHAPE, f"cluster fixture drifted: {cluster_id}"
            )
        fixture_digests[cluster_id] = str(fixture["content_sha256"])
        sources = {
            str(source["source_id"]): source
            for source in cast(list[dict[str, Any]], fixture["sources"])
        }
        for source_id, source in sources.items():
            source_digests[source_id] = str(source["sha256"])
        for instance in cast(list[dict[str, Any]], fixture["instances"]):
            source = sources[str(instance["source_id"])]
            rows = [("actual", cast(dict[str, Any], instance["baseline"])["answer"])]
            rows += [
                (str(control["variant"]), str(control["answer"]))
                for control in cast(list[dict[str, Any]], instance["controls"])
            ]
            for variant, answer in rows:
                staged.append((cluster_id, str(instance["instance_id"]), {
                    "variant": variant,
                    "answer": answer,
                    "question": instance["question"],
                    "aspects": instance["aspects"],
                    "aspect_rubric": instance["aspect_rubric"],
                    "source_id": source["source_id"],
                    "source_locator": source["locator"],
                    "source_page": instance.get("page"),
                    "source_region": instance.get("region"),
                    "source_text": instance["source_text"],
                }))
    staged.sort(key=lambda row: canonical_hash(f"{review_run_id}|{row[0]}|{row[1]}|{row[2]['variant']}"))

    composite_sha = str(composite.get("content_sha256", ""))
    input_manifest_hash = canonical_hash({
        "review_run_id": review_run_id,
        "composite_manifest_sha256": composite_sha,
        "clusters": sorted(fixture_digests.items()),
        "sources": sorted(source_digests.items()),
    })

    items = []
    manifest_items = []
    for index, (cluster_id, instance_id, row) in enumerate(staged, start=1):
        blind_case_id = f"{review_run_id}-item-{index:02d}"
        items.append({
            "blind_case_id": blind_case_id,
            "question": row["question"],
            "aspects": row["aspects"],
            "aspect_rubric": row["aspect_rubric"],
            "source_id": row["source_id"],
            "source_locator": row["source_locator"],
            "source_page": row["source_page"],
            "source_region": row["source_region"],
            "source_text": row["source_text"],
            "answer": row["answer"],
        })
        manifest_items.append({
            "blind_case_id": blind_case_id,
            "cluster_id": cluster_id,
            "instance_id": instance_id,
            "variant": row["variant"],
            "answer_sha256": sha256(str(row["answer"]).encode("utf-8")).hexdigest(),
        })

    packet = {
        "schema_version": SCHEMA_HOLDOUT_PACKET,
        "review_run_id": review_run_id,
        "input_manifest_hash": input_manifest_hash,
        "instructions": REVIEWER_INSTRUCTIONS,
        "items": items,
    }
    frozen_refs = {
        "composite_manifest_sha256": composite_sha,
        **{f"cluster_fixture_sha256::{key}": value for key, value in fixture_digests.items()},
        **{f"cluster_source_sha256::{key}": value for key, value in source_digests.items()},
    }
    manifest = {
        "schema_version": SCHEMA_HOLDOUT_MANIFEST,
        "review_run_id": review_run_id,
        "input_manifest_hash": input_manifest_hash,
        "packet_sha256": canonical_hash(packet),
        "composite_manifest_sha256": composite_sha,
        "cluster_fixture_sha256": fixture_digests,
        "cluster_source_sha256": source_digests,
        "frozen_refs": frozen_refs,
        "gate_rule": cast(dict[str, Any], composite.get("gate_rule", {})),
        "items": manifest_items,
    }
    return {"packet": packet, "manifest": manifest}


def ingest_holdout_review_run(
    *,
    packet: Mapping[str, object],
    manifest: Mapping[str, object],
    raw_response_text: str,
    reviewer_identity: ReviewerIdentity,
    invocation_id: str,
    timestamp: str,
    answer_model_families: Sequence[str],
    transport: str = TRANSPORT_MANUAL_COPY_PASTE,
    raw_response_bytes: bytes | None = None,
) -> dict[str, object]:
    """Score a composite holdout per cluster. Gates, never totals. Grants nothing."""
    review_run_id, _, manifest_items, observations = _validated_observations(
        packet=packet,
        manifest=manifest,
        raw_response_text=raw_response_text,
        reviewer_identity=reviewer_identity,
        invocation_id=invocation_id,
        timestamp=timestamp,
        answer_model_families=answer_model_families,
        raw_response_bytes=raw_response_bytes,
    )
    provenance = next(iter(observations.values())).provenance

    cluster_order: list[str] = []
    for blind_case_id in observations:
        cluster_id = str(manifest_items[blind_case_id]["cluster_id"])
        if cluster_id not in cluster_order:
            cluster_order.append(cluster_id)

    cluster_results: dict[str, object] = {}
    cluster_pass: dict[str, bool] = {}
    for cluster_id in cluster_order:
        control_ids = [
            blind_case_id for blind_case_id, _ in observations.items()
            if str(manifest_items[blind_case_id]["cluster_id"]) == cluster_id
            and manifest_items[blind_case_id]["variant"] in CONTROL_VARIANTS
        ]
        controls = [
            ReviewedControl(str(manifest_items[blind_case_id]["variant"]),
                            observations[blind_case_id])
            for blind_case_id in control_ids
        ]
        clean = [
            observation
            for blind_case_id, observation in observations.items()
            if str(manifest_items[blind_case_id]["cluster_id"]) == cluster_id
            and manifest_items[blind_case_id]["variant"] == VARIANT_ACTUAL
        ]
        result = check_calibration(
            reviewer_provenance=provenance,
            control_observations=controls,
            clean_answer_observations=clean,
        )
        cluster_pass[cluster_id] = result.calibration_pass
        verdicts = dict(zip(control_ids, result.controls, strict=True))
        cluster_results[cluster_id] = {
            "target_detected": result.target_detected,
            "target_total": result.target_total,
            "target_missed": result.target_missed,
            "specificity_correct": result.specificity_correct,
            "specificity_total": result.specificity_total,
            "specificity_violations": result.specificity_violations,
            "confusion": result.confusion.to_dict(),
            "target_gate_pass": result.target_gate_pass,
            "specificity_gate_pass": result.specificity_gate_pass,
            "cluster_pass": result.calibration_pass,
            "clean_answer_correct": result.clean_answer_correct,
            "clean_answer_total": result.clean_answer_total,
            "controls": [row.to_dict() for row in result.controls],
            "items": [
                {
                    "blind_case_id": blind_case_id,
                    "instance_id": manifest_items[blind_case_id]["instance_id"],
                    "variant": manifest_items[blind_case_id]["variant"],
                    "target_detected": (None if blind_case_id not in verdicts
                                         else verdicts[blind_case_id].target_detected),
                    "specific": (None if blind_case_id not in verdicts
                                  else verdicts[blind_case_id].specific),
                }
                for blind_case_id in sorted(observations)
                if str(manifest_items[blind_case_id]["cluster_id"]) == cluster_id
            ],
        }

    overall_pass = bool(cluster_pass) and all(cluster_pass.values())
    return {
        "schema_version": SCHEMA_HOLDOUT_INGEST,
        "review_run_id": review_run_id,
        "input_manifest_hash": manifest.get("input_manifest_hash"),
        "output_hash": sha256(
            raw_response_bytes if raw_response_bytes is not None
            else raw_response_text.encode("utf-8")
        ).hexdigest(),
        "raw_response_bytes_preserved": raw_response_bytes is not None,
        "composite_manifest_sha256": manifest.get("composite_manifest_sha256"),
        "cluster_fixture_sha256": manifest.get("cluster_fixture_sha256"),
        "cluster_source_sha256": manifest.get("cluster_source_sha256"),
        "packet_sha256": manifest.get("packet_sha256"),
        "reviewer": reviewer_identity.to_dict(),
        "reviewer_identity_hash": reviewer_identity_hash(reviewer_identity),
        "invocation_id": invocation_id,
        "timestamp": timestamp,
        "invocation_id_kind": "harness_assigned_run_id",
        "transport": transport,
        "answer_model_families": sorted(answer_model_families),
        "independence_ok": True,
        "cluster_results": cluster_results,
        "overall_pass": overall_pass,
        "eligible_for_authority_review": overall_pass,
        "qualified_judge": False,
        "formal_semantic_label": False,
        "release_observation": False,
        "release_gate": "NO_GO",
    }
