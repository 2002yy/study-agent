from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import copy

from src.evals.release_benchmark_plan import load_release_benchmark_plan
from src.evals.release_benchmark_registry import load_gold, load_registry
from src.evals.release_benchmark_review import (
    build_independent_review_artifact,
    build_review_packet,
    check_github_review,
    check_independent_review_artifact,
    review_template,
)

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests/fixtures/release_benchmark"
HEAD = "a" * 40
ARTIFACT_KEY = b"k" * 32


def _packet():
    plan = load_release_benchmark_plan(FIXTURES / "plan_v1.json")
    registry = load_registry(FIXTURES / "registry_v1.json", ROOT, plan)
    gold = load_gold(FIXTURES / "gold_v1.json", registry)
    return registry, gold, build_review_packet(registry, gold)


def _api_review(packet):
    pr = {"number": 149, "head": {"sha": HEAD}, "user": {"login": "author"}}
    review = {
        "id": 123,
        "user": {"login": "independent-reviewer", "type": "User"},
        "author_association": "COLLABORATOR",
        "state": "APPROVED",
        "commit_id": HEAD,
        "body": review_template(packet),
        "pull_request_url": "https://api.github.com/repos/2002yy/study-agent/pulls/149",
    }
    return pr, review


def _artifact(packet, **overrides):
    kwargs = {
        "expected_head_sha": HEAD,
        "reviewer": "independent-model-reviewer",
        "reviewer_kind": "model",
        "issuer": "trusted-review-service",
        "issued_at": "2026-09-28T10:00:00Z",
        "decision": "approved",
        "review_axes": {
            "source_verified": True,
            "leakage_checked": True,
            "difficulty_checked": True,
            "modality_checked": True,
        },
        "blocking_findings": (),
        "review_notes": (
            "Reviewed original sources, questions, gold, leakage, difficulty and modality."
        ),
        "issuer_secret": ARTIFACT_KEY,
    }
    kwargs.update(overrides)
    return build_independent_review_artifact(packet, **kwargs)


def test_packet_binds_case_sources_and_substantive_gold():
    registry, gold, packet = _packet()
    assert len(packet["cases"]) == 6
    assert packet["cases"][0]["sources"][0]["sha256"] is not None

    first = gold.reviews[0]
    changed = replace(first, aspect_rubric=((first.aspect_rubric[0][0], "changed"),
                                            *first.aspect_rubric[1:]))
    altered = replace(gold, reviews=(changed, *gold.reviews[1:]))
    assert build_review_packet(registry, altered)["packet_digest"] != packet["packet_digest"]


def test_github_review_check_requires_external_exact_head_and_packet():
    packet = _packet()[2]
    pr, review = _api_review(packet)
    result = check_github_review(packet, pr, [review], review_id=123, expected_head_sha=HEAD)
    assert result["verified_review"] is True
    assert result["verified_external_review"] is True
    assert result["review_method"] == "github_collaborator"
    assert result["admitted_release_cases"] == 0
    assert result["release_gate"] == "NO_GO"

    self_review = {**review, "user": {"login": "author", "type": "User"}}
    assert "reviewer_not_independent_collaborator" in check_github_review(
        packet, pr, [self_review], review_id=123, expected_head_sha=HEAD,
    )["issues"]
    wrong_commit = {**review, "commit_id": "b" * 40}
    assert "review_commit_mismatch" in check_github_review(
        packet, pr, [wrong_commit], review_id=123, expected_head_sha=HEAD,
    )["issues"]
    wrong_body = {
        **review,
        "body": review["body"].replace("source_verified: yes", "source_verified: no"),
    }
    assert "review_packet_or_axes_mismatch" in check_github_review(
        packet, pr, [wrong_body], review_id=123, expected_head_sha=HEAD,
    )["issues"]
    later = {**review, "id": 124, "state": "CHANGES_REQUESTED"}
    assert "review_superseded" in check_github_review(
        packet, pr, [review, later], review_id=123, expected_head_sha=HEAD,
    )["issues"]
    tampered = copy.deepcopy(packet)
    tampered["cases"][0]["question"] = "different question"
    assert "packet_digest_mismatch" in check_github_review(
        tampered, pr, [review], review_id=123, expected_head_sha=HEAD,
    )["issues"]
    annotator_review = {**review, "user": {"login": "codex-draft", "type": "User"}}
    assert "reviewer_not_independent_collaborator" in check_github_review(
        packet, pr, [annotator_review], review_id=123, expected_head_sha=HEAD,
    )["issues"]


def test_independent_artifact_requires_trusted_signature_and_independence():
    packet = _packet()[2]
    artifact = _artifact(packet)
    result = check_independent_review_artifact(
        packet,
        artifact,
        expected_head_sha=HEAD,
        author_login="author",
        trusted_issuers={"trusted-review-service": ARTIFACT_KEY},
    )
    assert result["verified_review"] is True
    assert result["verified_independent_review"] is True
    assert result["review_method"] == "independent_artifact"
    assert result["admitted_release_cases"] == 0
    assert result["release_gate"] == "NO_GO"

    untrusted = check_independent_review_artifact(
        packet,
        artifact,
        expected_head_sha=HEAD,
        author_login="author",
        trusted_issuers={},
    )
    assert "artifact_issuer_untrusted" in untrusted["issues"]

    self_artifact = _artifact(packet, reviewer="author")
    assert "artifact_reviewer_or_issuer_not_independent" in check_independent_review_artifact(
        packet,
        self_artifact,
        expected_head_sha=HEAD,
        author_login="author",
        trusted_issuers={"trusted-review-service": ARTIFACT_KEY},
    )["issues"]

    annotator_artifact = _artifact(packet, reviewer="codex-draft")
    assert "artifact_reviewer_or_issuer_not_independent" in check_independent_review_artifact(
        packet,
        annotator_artifact,
        expected_head_sha=HEAD,
        author_login="author",
        trusted_issuers={"trusted-review-service": ARTIFACT_KEY},
    )["issues"]


def test_independent_artifact_rejects_tamper_wrong_scope_and_blockers():
    packet = _packet()[2]
    artifact = _artifact(packet)

    tampered = copy.deepcopy(artifact)
    tampered["review_notes"] = "changed after signing"
    assert "artifact_digest_mismatch" in check_independent_review_artifact(
        packet,
        tampered,
        expected_head_sha=HEAD,
        author_login="author",
        trusted_issuers={"trusted-review-service": ARTIFACT_KEY},
    )["issues"]

    wrong_key = check_independent_review_artifact(
        packet,
        artifact,
        expected_head_sha=HEAD,
        author_login="author",
        trusted_issuers={"trusted-review-service": b"z" * 32},
    )
    assert "artifact_signature_invalid" in wrong_key["issues"]

    wrong_head = _artifact(packet, expected_head_sha="b" * 40)
    assert "artifact_head_mismatch" in check_independent_review_artifact(
        packet,
        wrong_head,
        expected_head_sha=HEAD,
        author_login="author",
        trusted_issuers={"trusted-review-service": ARTIFACT_KEY},
    )["issues"]

    blockers = _artifact(
        packet,
        blocking_findings=("ambiguous chart gold",),
        decision="request_changes",
    )
    blocker_issues = check_independent_review_artifact(
        packet,
        blockers,
        expected_head_sha=HEAD,
        author_login="author",
        trusted_issuers={"trusted-review-service": ARTIFACT_KEY},
    )["issues"]
    assert "artifact_has_blocking_findings" in blocker_issues
    assert "artifact_not_approved" in blocker_issues

    incomplete_axes = _artifact(packet, review_axes={
        "source_verified": True,
        "leakage_checked": True,
        "difficulty_checked": False,
        "modality_checked": True,
    })
    assert "artifact_axes_incomplete" in check_independent_review_artifact(
        packet,
        incomplete_axes,
        expected_head_sha=HEAD,
        author_login="author",
        trusted_issuers={"trusted-review-service": ARTIFACT_KEY},
    )["issues"]

    extra_field = {**artifact, "verified_review": True}
    assert "artifact_fields_or_schema_invalid" in check_independent_review_artifact(
        packet,
        extra_field,
        expected_head_sha=HEAD,
        author_login="author",
        trusted_issuers={"trusted-review-service": ARTIFACT_KEY},
    )["issues"]
