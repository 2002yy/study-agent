"""Digest-bound external review packets and fail-closed GitHub review checks.

This diagnostic check does not admit a case. Its CLI fetches GitHub review
records directly; caller-authored JSON cannot grant release authority.
"""

from __future__ import annotations

from typing import Any, Sequence

from src.evals.release_benchmark_registry import (
    ReleaseGold,
    ReleaseRegistry,
    canonical_digest,
)

PACKET_SCHEMA = "release-benchmark-review-packet-v1"
CHECK_SCHEMA = "release-benchmark-review-check-v1"
MARKER = "RELEASE-BENCHMARK-REVIEW-V1"
REVIEW_AXES = (
    "source_verified", "leakage_checked", "difficulty_checked", "modality_checked",
)
TRUSTED_ASSOCIATIONS = {"OWNER", "MEMBER", "COLLABORATOR"}


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
        "I reviewed the original sources, case questions, and substantive gold for the packet above.",
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


def check_github_review(
    packet: dict[str, Any], pr: dict[str, Any], reviews: Sequence[dict[str, Any]],
    *, review_id: int, expected_head_sha: str,
) -> dict[str, Any]:
    """Check API-fetched review facts; never alter release admission."""

    issues: list[str] = []
    actual_digest = packet.get("packet_digest")
    if (packet.get("schema_version") != PACKET_SCHEMA
            or not isinstance(actual_digest, str)
            or canonical_digest({key: value for key, value in packet.items()
                                 if key != "packet_digest"}) != actual_digest):
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
    return {
        "schema_version": CHECK_SCHEMA,
        "packet_digest": actual_digest,
        "pr_number": pr_number,
        "head_sha": current_sha,
        "review_id": review_id,
        "reviewer": reviewer_login,
        "verified_external_review": not issues,
        "issues": issues,
        "admitted_release_cases": 0,
        "release_gate": "NO_GO",
    }
