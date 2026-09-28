"""Digest-bound review packets and fail-closed independent review checks.

Two review transports are supported:
1. an exact-head GitHub collaborator approval; or
2. a digest-bound independent review artifact signed by an out-of-band trusted issuer.

Neither transport admits release cases by itself. Caller-authored JSON, self-review,
and untrusted artifact issuers cannot grant release authority.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timezone
from hashlib import sha256
import hmac
from typing import Any, Sequence

from src.evals.release_benchmark_registry import (
    ReleaseGold,
    ReleaseRegistry,
    canonical_digest,
)

PACKET_SCHEMA = "release-benchmark-review-packet-v1"
CHECK_SCHEMA = "release-benchmark-review-check-v1"
ARTIFACT_SCHEMA = "release-benchmark-independent-review-artifact-v1"
ARTIFACT_CHECK_SCHEMA = "release-benchmark-independent-review-check-v1"
MARKER = "RELEASE-BENCHMARK-REVIEW-V1"
REVIEW_AXES = (
    "source_verified", "leakage_checked", "difficulty_checked", "modality_checked",
)
TRUSTED_ASSOCIATIONS = {"OWNER", "MEMBER", "COLLABORATOR"}
ARTIFACT_REVIEWER_KINDS = {"human", "model", "agent"}
_ARTIFACT_FIELDS = {
    "schema_version",
    "packet_digest",
    "head_sha",
    "reviewer",
    "reviewer_kind",
    "issuer",
    "issued_at",
    "decision",
    "review_axes",
    "reviewed_cases",
    "blocking_findings",
    "review_notes",
    "artifact_digest",
    "signature",
}


def build_review_packet(
    registry: ReleaseRegistry, gold: ReleaseGold,
    *, case_ids: Sequence[str] | None = None,
) -> dict[str, Any]:
    selected = set(case_ids) if case_ids is not None else {case.case_id for case in registry.cases}
    if not selected or len(selected) != (len(case_ids) if case_ids is not None else len(selected)):
        raise ValueError("review packet needs distinct selected cases")
    cases = {case.case_id: case for case in registry.cases}
    reviews = {review.case_id: review for review in gold.reviews}
    if not selected <= cases.keys() or not selected <= reviews.keys():
        raise ValueError("review packet has an unknown or goldless case")
    entries = []
    for case_id in sorted(selected):
        case, review = cases[case_id], reviews[case_id]
        substantive_gold = {
            "case_id": review.case_id,
            "case_content_sha256": review.case_content_sha256,
            "aspect_rubric": dict(review.aspect_rubric),
            "unit_sources": {unit: list(refs) for unit, refs in review.unit_sources},
        }
        entries.append({
            "case_id": case_id,
            "case_content_sha256": case.content_sha256,
            "question": case.question,
            "aspects": list(case.aspects),
            "required_units": list(case.required_units),
            "limitations": list(case.limitations),
            "annotator": review.annotator,
            "gold_content_sha256": canonical_digest(substantive_gold),
            "substantive_gold": substantive_gold,
            "sources": [
                {"source_id": source.source_id, "locator": source.locator,
                 "sha256": source.sha256, "page": source.page,
                 "region": source.region}
                for source in case.sources
            ],
        })
    packet: dict[str, Any] = {
        "schema_version": PACKET_SCHEMA,
        "plan_digest": registry.plan_digest,
        "cases": entries,
        "review_axes": list(REVIEW_AXES),
    }
    packet["packet_digest"] = canonical_digest(packet)
    return packet


def review_template(packet: dict[str, Any]) -> str:
    return "\n".join([
        f"{MARKER} {packet['packet_digest']}",
        "cases: " + ", ".join(entry["case_id"] for entry in packet["cases"]),
        *[f"{axis}: yes" for axis in REVIEW_AXES],
        "I reviewed the original sources, case questions, and substantive gold "
        "for the packet above.",
    ])


def _review_fields_valid(body: Any, digest: str) -> bool:
    if not isinstance(body, str):
        return False
    lines = [line.strip() for line in body.splitlines()]
    markers = [line for line in lines if line.startswith(MARKER)]
    if markers != [f"{MARKER} {digest}"]:
        return False
    return all(
        [line for line in lines if line.startswith(f"{axis}:")] == [f"{axis}: yes"]
        for axis in REVIEW_AXES
    )


def _packet_digest_valid(packet: dict[str, Any]) -> bool:
    actual_digest = packet.get("packet_digest")
    return (
        packet.get("schema_version") == PACKET_SCHEMA
        and isinstance(actual_digest, str)
        and canonical_digest(
            {key: value for key, value in packet.items() if key != "packet_digest"}
        ) == actual_digest
    )


def _utc_timestamp(value: Any) -> bool:
    if not isinstance(value, str) or not value:
        return False
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return parsed.tzinfo is not None and parsed.utcoffset() == timezone.utc.utcoffset(parsed)


def _artifact_payload(artifact: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in artifact.items()
        if key not in {"artifact_digest", "signature"}
    }


def _artifact_signature(artifact_digest: str, secret: bytes) -> str:
    return hmac.new(secret, artifact_digest.encode("ascii"), sha256).hexdigest()


def build_independent_review_artifact(
    packet: dict[str, Any],
    *,
    expected_head_sha: str,
    reviewer: str,
    reviewer_kind: str,
    issuer: str,
    issued_at: str,
    decision: str,
    review_axes: Mapping[str, bool],
    blocking_findings: Sequence[str],
    review_notes: str,
    issuer_secret: bytes,
) -> dict[str, Any]:
    """Build a signed artifact for an out-of-band trusted review issuer.

    The issuer secret is intentionally supplied by the caller and must live outside
    the repository. Possessing or editing the artifact alone is not authorization.
    """

    if not _packet_digest_valid(packet):
        raise ValueError("review packet digest is invalid")
    if len(expected_head_sha) != 40:
        raise ValueError("review artifact needs an exact 40-character head SHA")
    if reviewer_kind not in ARTIFACT_REVIEWER_KINDS:
        raise ValueError("unsupported independent reviewer kind")
    if not reviewer.strip() or not issuer.strip() or not review_notes.strip():
        raise ValueError("review artifact identity and notes must be non-empty")
    if not _utc_timestamp(issued_at):
        raise ValueError("review artifact issued_at must be UTC")
    if (set(review_axes) != set(REVIEW_AXES)
            or any(type(value) is not bool for value in review_axes.values())):
        raise ValueError("review artifact axes must match the frozen checklist")
    if decision not in {"approved", "request_changes"}:
        raise ValueError("invalid independent review decision")
    if not isinstance(issuer_secret, bytes) or len(issuer_secret) < 32:
        raise ValueError("independent review issuer secret must be at least 32 bytes")
    if any(not isinstance(item, str) or not item.strip() for item in blocking_findings):
        raise ValueError("blocking findings must be non-empty strings")

    artifact: dict[str, Any] = {
        "schema_version": ARTIFACT_SCHEMA,
        "packet_digest": packet["packet_digest"],
        "head_sha": expected_head_sha,
        "reviewer": reviewer,
        "reviewer_kind": reviewer_kind,
        "issuer": issuer,
        "issued_at": issued_at,
        "decision": decision,
        "review_axes": dict(review_axes),
        "reviewed_cases": [entry["case_id"] for entry in packet["cases"]],
        "blocking_findings": list(blocking_findings),
        "review_notes": review_notes,
    }
    artifact_digest = canonical_digest(artifact)
    artifact["artifact_digest"] = artifact_digest
    artifact["signature"] = _artifact_signature(artifact_digest, issuer_secret)
    return artifact


def check_github_review(
    packet: dict[str, Any], pr: dict[str, Any], reviews: Sequence[dict[str, Any]],
    *, review_id: int, expected_head_sha: str,
) -> dict[str, Any]:
    """Check API-fetched GitHub review facts; never alter release admission."""

    issues: list[str] = []
    actual_digest = packet.get("packet_digest")
    if not _packet_digest_valid(packet):
        issues.append("packet_digest_mismatch")
    pr_number = pr.get("number")
    head = pr.get("head")
    current_sha = head.get("sha") if isinstance(head, dict) else None
    author = pr.get("user")
    author_login = author.get("login") if isinstance(author, dict) else None
    if (type(pr_number) is not int or pr_number < 1
            or not isinstance(author_login, str) or not author_login
            or current_sha != expected_head_sha or len(expected_head_sha) != 40):
        issues.append("pr_head_or_author_mismatch")
    selected = next((review for review in reviews if review.get("id") == review_id), None)
    reviewer_login = None
    if selected is None:
        issues.append("review_not_found")
    else:
        user = selected.get("user")
        reviewer_login = user.get("login") if isinstance(user, dict) else None
        if (not isinstance(reviewer_login, str) or not reviewer_login
                or reviewer_login == author_login
                or reviewer_login in {entry.get("annotator") for entry in packet.get("cases", [])
                                      if isinstance(entry, dict)}
                or not isinstance(user, dict) or user.get("type") != "User"
                or selected.get("author_association") not in TRUSTED_ASSOCIATIONS):
            issues.append("reviewer_not_independent_collaborator")
        if selected.get("state") != "APPROVED":
            issues.append("review_not_approved")
        if selected.get("commit_id") != expected_head_sha:
            issues.append("review_commit_mismatch")
        if not _review_fields_valid(selected.get("body"), str(actual_digest)):
            issues.append("review_packet_or_axes_mismatch")
        expected_url = (
            f"https://api.github.com/repos/2002yy/study-agent/pulls/{pr_number}"
        )
        if selected.get("pull_request_url") != expected_url:
            issues.append("review_pr_mismatch")
        same_reviewer = [review for review in reviews
                         if isinstance(review.get("user"), dict)
                         and review["user"].get("login") == reviewer_login
                         and type(review.get("id")) is int]
        if same_reviewer and max(review["id"] for review in same_reviewer) != review_id:
            issues.append("review_superseded")
    verified = not issues
    return {
        "schema_version": CHECK_SCHEMA,
        "review_method": "github_collaborator",
        "packet_digest": actual_digest,
        "pr_number": pr_number,
        "head_sha": current_sha,
        "review_id": review_id,
        "reviewer": reviewer_login,
        "verified_review": verified,
        "verified_external_review": verified,
        "issues": issues,
        "admitted_release_cases": 0,
        "release_gate": "NO_GO",
    }


def check_independent_review_artifact(
    packet: dict[str, Any],
    artifact: dict[str, Any],
    *,
    expected_head_sha: str,
    author_login: str,
    trusted_issuers: Mapping[str, bytes],
) -> dict[str, Any]:
    """Verify a signed independent review artifact against an out-of-band trust root.

    The artifact cannot authorize itself: its issuer must be present in
    ``trusted_issuers`` and its HMAC must verify with that external secret.
    """

    issues: list[str] = []
    packet_digest = packet.get("packet_digest")
    if not _packet_digest_valid(packet):
        issues.append("packet_digest_mismatch")

    if set(artifact) != _ARTIFACT_FIELDS or artifact.get("schema_version") != ARTIFACT_SCHEMA:
        issues.append("artifact_fields_or_schema_invalid")

    reviewer = artifact.get("reviewer")
    reviewer_kind = artifact.get("reviewer_kind")
    issuer = artifact.get("issuer")
    annotators = {
        entry.get("annotator")
        for entry in packet.get("cases", [])
        if isinstance(entry, dict) and isinstance(entry.get("annotator"), str)
    }
    if (not isinstance(author_login, str) or not author_login
            or not isinstance(reviewer, str) or not reviewer
            or reviewer == author_login or reviewer in annotators
            or not isinstance(issuer, str) or not issuer
            or issuer == author_login or issuer in annotators):
        issues.append("artifact_reviewer_or_issuer_not_independent")
    if reviewer_kind not in ARTIFACT_REVIEWER_KINDS:
        issues.append("artifact_reviewer_kind_invalid")
    if artifact.get("packet_digest") != packet_digest:
        issues.append("artifact_packet_mismatch")
    if artifact.get("head_sha") != expected_head_sha or len(expected_head_sha) != 40:
        issues.append("artifact_head_mismatch")
    expected_cases = [
        entry.get("case_id")
        for entry in packet.get("cases", [])
        if isinstance(entry, dict)
    ]
    reviewed_cases = artifact.get("reviewed_cases")
    if (not isinstance(reviewed_cases, list)
            or reviewed_cases != expected_cases
            or any(not isinstance(case_id, str) for case_id in reviewed_cases)):
        issues.append("artifact_case_scope_mismatch")
    axes = artifact.get("review_axes")
    if (not isinstance(axes, dict) or set(axes) != set(REVIEW_AXES)
            or any(axes.get(axis) is not True for axis in REVIEW_AXES)):
        issues.append("artifact_axes_incomplete")
    blockers = artifact.get("blocking_findings")
    if (not isinstance(blockers, list)
            or any(not isinstance(item, str) or not item.strip() for item in blockers)):
        issues.append("artifact_blocking_findings_invalid")
    elif blockers:
        issues.append("artifact_has_blocking_findings")
    if artifact.get("decision") != "approved":
        issues.append("artifact_not_approved")
    if not _utc_timestamp(artifact.get("issued_at")):
        issues.append("artifact_timestamp_invalid")
    notes = artifact.get("review_notes")
    if not isinstance(notes, str) or not notes.strip():
        issues.append("artifact_notes_missing")

    artifact_digest = artifact.get("artifact_digest")
    if (not isinstance(artifact_digest, str)
            or canonical_digest(_artifact_payload(artifact)) != artifact_digest):
        issues.append("artifact_digest_mismatch")

    issuer_secret = trusted_issuers.get(issuer) if isinstance(issuer, str) else None
    if not isinstance(issuer_secret, bytes) or len(issuer_secret) < 32:
        issues.append("artifact_issuer_untrusted")
    else:
        signature = artifact.get("signature")
        expected_signature = (
            _artifact_signature(artifact_digest, issuer_secret)
            if isinstance(artifact_digest, str) else ""
        )
        if (not isinstance(signature, str)
                or not hmac.compare_digest(signature, expected_signature)):
            issues.append("artifact_signature_invalid")

    verified = not issues
    return {
        "schema_version": ARTIFACT_CHECK_SCHEMA,
        "review_method": "independent_artifact",
        "packet_digest": packet_digest,
        "head_sha": artifact.get("head_sha"),
        "reviewer": reviewer,
        "reviewer_kind": reviewer_kind,
        "issuer": issuer,
        "artifact_digest": artifact_digest,
        "verified_review": verified,
        "verified_independent_review": verified,
        "issues": issues,
        "admitted_release_cases": 0,
        "release_gate": "NO_GO",
    }
