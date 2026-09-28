from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import copy

from src.evals.release_benchmark_plan import load_release_benchmark_plan
from src.evals.release_benchmark_registry import load_gold, load_registry
from src.evals.release_benchmark_review import (
    build_review_packet,
    check_github_review,
    review_template,
)

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests/fixtures/release_benchmark"
HEAD = "a" * 40


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
    assert result["verified_external_review"] is True
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
    wrong_body = {**review, "body": review["body"].replace("source_verified: yes", "source_verified: no")}
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
