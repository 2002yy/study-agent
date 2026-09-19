"""§44C-Alt url-proposal qualification contracts (DeepSeek-only)."""

from __future__ import annotations

from pathlib import Path

from tools.run_recall_target_audit import TARGETS
from tools.run_url_proposal_qualification import (
    claim_for_target,
    evaluate_gate,
    evaluate_proposals,
    run_qualification,
)

DOCKER = next(t for t in TARGETS if t.case_id.endswith("container-registry"))
NODE = next(t for t in TARGETS if "node" in t.case_id)


def test_exact_and_same_domain_evaluation() -> None:
    outcome = evaluate_proposals([DOCKER.url, "https://docs.docker.com/other/"], DOCKER)
    assert outcome["exact_hit"] is True
    assert outcome["same_domain_hit"] is True
    other = evaluate_proposals(["https://example.com/x"], DOCKER)
    assert other == {"exact_hit": False, "same_domain_hit": False}


def test_claims_are_target_specific() -> None:
    assert "pull-rate" in claim_for_target(DOCKER)
    assert "module systems" in claim_for_target(NODE)


def test_gate_requires_hard_exact_hits_and_readable_pages() -> None:
    rows = [
        {"case_id": DOCKER.case_id, "exact_hit": True, "read_ok": True},
        {"case_id": "rq1c-current-support-postgresql", "exact_hit": False, "read_ok": True},
        {"case_id": NODE.case_id, "exact_hit": False, "read_ok": True},
    ]
    gate = evaluate_gate(rows)
    assert gate["passed"] is False
    assert gate["hard_gate_failures"] == ["rq1c-current-support-postgresql"]

    rows[1]["exact_hit"] = True
    assert evaluate_gate(rows)["passed"] is True

    rows[2]["read_ok"] = False
    gate = evaluate_gate(rows)
    assert gate["passed"] is False
    assert gate["unreadable_cases"] == [NODE.case_id]


def test_run_qualification_uses_injected_collaborators(tmp_path: Path) -> None:
    def proposer(claim: str) -> list[str]:
        del claim
        return [DOCKER.url]

    def reader(url: str) -> dict:
        return {"ok": True, "content": "page body" * 10}

    payload = run_qualification(
        output_path=tmp_path / "out.json",
        proposer=proposer,
        reader=reader,
        targets=(DOCKER,),
    )
    row = payload["rows"][0]
    assert row["exact_hit"] is True
    assert row["read_ok"] is True
    assert row["read_chars"] > 0
    gate = payload["gate"]
    # only Docker was in scope; PostgreSQL is missing entirely
    assert gate["passed"] is False
    assert gate["hard_gate_failures"] == ["rq1c-current-support-postgresql"]
