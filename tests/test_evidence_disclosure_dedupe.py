from __future__ import annotations

from src.pedagogy.evidence import EvidenceDisclosurePolicy, EvidenceUnit
from src.pedagogy.types import PedagogyTurnPlan


def _unit(source_id: str, kind: str = "search_excerpt") -> EvidenceUnit:
    return EvidenceUnit(
        source_id=source_id,
        type=kind,
        content=f"body of {source_id}",
        citation=f"web:{source_id}",
        disclosure_role="external_fact",
        reliability=0.72,
    )


def _plan(*, level: int, kind: str = "empirical") -> PedagogyTurnPlan:
    return PedagogyTurnPlan(
        mode="study",
        phase="explain",
        knowledge_kind=kind,  # type: ignore[arg-type]
        move="provide_library_fact",
        disclosure_level=level,
    )


def _occurrences(haystack: str, needle: str) -> int:
    return haystack.count(needle)


def test_full_disclosure_injects_each_evidence_body_once() -> None:
    """At level 5 the private block used to repeat the whole evidence body."""

    units = [_unit("web-1"), _unit("web-2"), _unit("web-3")]
    disclosed = EvidenceDisclosurePolicy().select(units=units, plan=_plan(level=5))

    assert disclosed.policy == "full"
    assert len(disclosed.units) == 3
    # Everything is disclosed, so nothing is private-only.
    assert disclosed.private_context == ""
    for unit in units:
        assert _occurrences(disclosed.context, unit.content) == 1
        assert _occurrences(disclosed.private_context, unit.content) == 0


def test_partial_disclosure_keeps_private_only_units_apart() -> None:
    """A withheld unit stays available for planning, but only in one block."""

    units = [
        _unit("web-1"),
        _unit("web-2", kind="article_excerpt"),
        _unit("web-3", kind="article_excerpt"),
    ]
    disclosed = EvidenceDisclosurePolicy().select(
        units=units, plan=_plan(level=3, kind="procedural")
    )

    assert disclosed.policy == "bounded_units"
    assert len(disclosed.units) == 1
    for unit in units:
        combined = disclosed.context + disclosed.private_context
        assert _occurrences(combined, unit.content) == 1
    assert "body of web-2" in disclosed.private_context
    assert "body of web-2" not in disclosed.context


def test_withheld_disclosure_still_carries_every_unit_privately() -> None:
    units = [_unit("web-1"), _unit("web-2")]
    disclosed = EvidenceDisclosurePolicy().select(
        units=units, plan=_plan(level=1, kind="procedural")
    )

    assert disclosed.policy == "withheld_derivable_answer"
    assert disclosed.context == ""
    assert "body of web-1" in disclosed.private_context
    assert "body of web-2" in disclosed.private_context


def test_a_retrieval_constraint_is_never_treated_as_disclosed_evidence() -> None:
    constraint = EvidenceUnit(
        source_id="retrieval-constraint",
        type="constraint",
        content="evidence is insufficient for the specific question",
        citation="local",
        disclosure_role="constraint",
        reliability=1.0,
    )
    units = [constraint, _unit("web-1")]
    disclosed = EvidenceDisclosurePolicy().select(units=units, plan=_plan(level=5))

    assert disclosed.policy == "full"
    assert len(disclosed.units) == 1
    assert "evidence is insufficient" in disclosed.private_context
    assert "evidence is insufficient" not in disclosed.context
