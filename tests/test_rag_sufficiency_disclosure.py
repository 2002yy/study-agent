from __future__ import annotations

from src.pedagogy.evidence import EvidenceDisclosurePolicy, build_evidence_units
from src.pedagogy.types import PedagogyTurnPlan


def _plan() -> PedagogyTurnPlan:
    return PedagogyTurnPlan(
        mode="study",
        phase="explain",
        knowledge_kind="empirical",
        move="provide_library_fact",
        disclosure_level=5,
    )


def test_insufficient_local_retrieval_becomes_private_constraint_not_citable_evidence():
    units = build_evidence_units(
        rag={
            "status": "insufficient",
            "results": [],
        },
        web_context="",
    )

    disclosed = EvidenceDisclosurePolicy().select(units=units, plan=_plan())

    assert disclosed.context == ""
    assert disclosed.units == ()
    assert disclosed.policy == "private_constraints_only"
    assert "evidence is insufficient" in disclosed.private_context
    assert "do not answer the unsupported fact" in disclosed.private_context.lower()


def test_supported_rag_results_remain_disclosable_without_constraint_pollution():
    units = build_evidence_units(
        rag={
            "status": "found",
            "results": [
                {
                    "chunk": {
                        "chunk_id": "chunk-1",
                        "source_path": "notes.md",
                        "start_line": 1,
                        "end_line": 3,
                        "text": "Supported fact from the learner's material.",
                    }
                }
            ],
        },
        web_context="",
    )

    disclosed = EvidenceDisclosurePolicy().select(units=units, plan=_plan())

    assert len(disclosed.units) == 1
    assert disclosed.units[0]["source_id"] == "chunk-1"
    assert "Supported fact" in disclosed.context
    assert "retrieval_constraint" not in disclosed.context
