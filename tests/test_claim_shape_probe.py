"""§38c claim-shape probe: capture parsing, matrix construction, injection."""

from __future__ import annotations

from tools.run_claim_shape_probe import (
    build_claims,
    build_harnesses,
    load_capture,
    run_matrix,
)

TARGET = "https://nodejs.cn/api/modules.html"


def _capture_artifact() -> dict:
    return {
        "cases": [
            {
                "question": "What module systems does current Node.js officially support, and how does current guidance differ from older guidance?",
                "sources": [
                    {"url": "https://nodejs.org/", "title": "Home", "source_role": "primary"},
                    {
                        "url": TARGET,
                        "title": "Node.js modules docs",
                        "source_role": "primary",
                        "cluster_id": "candidate_cluster_x",
                    },
                ],
            }
        ],
        "source_reads": [
            {"url": "https://nodejs.org/", "content_chars": 1497, "content": "home"},
            {
                "url": TARGET,
                "content_chars": 6000,
                "content": "CommonJS modules ... ECMAScript modules ...",
                "content_sha256": "abc123",
            },
        ],
        "claims": [
            {
                "id": "claim_atomic",
                "text": "What module systems does current Node.js officially support",
                "kind": "factual",
                "priority": "critical",
                "state": "unresolved",
                "created_by": "runtime_claim_planner",
                "created_reason": "policy_profile:official_statement",
                "evidence_requirement": {
                    "min_independent_sources": 1,
                    "requires_successful_read": True,
                },
            },
            {
                "id": "claim_comparison",
                "text": "how does current guidance differ from older CommonJS-versus-ES-modules guidance?",
                "kind": "analytical",
                "priority": "major",
                "state": "pending",
                "created_by": "runtime_claim_planner",
                "created_reason": "policy_profile:causal_analysis",
                "evidence_requirement": {"min_independent_sources": 1},
            },
        ],
    }


def test_capture_selects_target_content_and_both_claims() -> None:
    capture = load_capture(_capture_artifact())
    assert capture["content_chars"] == 6000
    assert capture["content_sha256"] == "abc123"
    assert capture["target_source"]["cluster_id"] == "candidate_cluster_x"
    assert capture["atomic_claim"]["id"] == "claim_atomic"
    assert capture["comparison_claim"]["id"] == "claim_comparison"


def test_claims_and_harnesses_rows() -> None:
    capture = load_capture(_capture_artifact())
    claims = build_claims(capture)
    assert [claim.key for claim in claims] == [
        "offline_question",
        "runtime_comparison_claim",
        "runtime_atomic_claim",
    ]
    assert claims[1].kind == "analytical" and claims[1].priority == "major"
    assert claims[2].kind == "factual" and claims[2].priority == "critical"

    harnesses = build_harnesses(capture)
    assert [item.key for item in harnesses] == ["offline_harness", "runtime_harness"]
    assert harnesses[0].source_cluster_id == "hybrid_cluster"
    assert harnesses[1].source_cluster_id == "candidate_cluster_x"


def test_matrix_runs_six_cells_and_propagates_relations() -> None:
    capture = load_capture(_capture_artifact())

    def extract(claim, harness, content):
        assert content.startswith("CommonJS")
        if claim.key == "offline_question":
            return {"status": "completed", "relation": "supports", "strength": 0.9}
        if claim.key == "runtime_comparison_claim":
            return {
                "status": "completed",
                "relation": "background",
                "strength": 0.3,
                "caveats": ["no explicit contrast"],
            }
        return {"status": "completed", "relation": "supports", "strength": 0.8}
    cells = run_matrix(
        capture=capture,
        claims=build_claims(capture),
        harnesses=build_harnesses(capture),
        extract=extract,
    )
    assert [cell.cell for cell in cells] == ["A", "B", "C", "D", "E", "F"]
    by_cell = {cell.cell: cell for cell in cells}
    assert by_cell["A"].relation == "supports"
    assert by_cell["B"].relation == "supports"
    assert by_cell["C"].relation == "background"
    assert by_cell["D"].relation == "background"
    assert by_cell["E"].relation == "supports"
    assert by_cell["F"].relation == "supports"
    assert by_cell["D"].caveats == ["no explicit contrast"]


def test_matrix_records_extractor_exceptions() -> None:
    capture = load_capture(_capture_artifact())

    def extract(claim, harness, content):
        raise RuntimeError("model down")

    cells = run_matrix(
        capture=capture,
        claims=build_claims(capture)[:1],
        harnesses=build_harnesses(capture)[:1],
        extract=extract,
    )
    assert cells[0].status == "exception"
    assert cells[0].reason == "RuntimeError"
