"""RQ-B: validate RQ-A semantic adequacy on the §143-B threshold-safe cohort.

Frozen context: ``docs/PROJECT_STATUS.md`` §144.1 (RQ-A criteria) and the §143-B
paired characterization cohort (``docs/research_quality/F2_PAIRED.threshold_safe.json``).

Validation only. This module does not touch stop/gate/routing, does not generate
``required_units`` from evidence, and adds no new fixture: it reuses the real
cohort, where each case already declares ``expected_critical_units`` (the
claim-side requirement) and each side reports its recovered ``unit_set``.

The three contrasts it must prove:

1. full coverage            -> ``adequate`` + ``satisfied``
2. read success, units short -> ``partial`` / ``insufficient``, never ``satisfied``
3. no ``required_units``    -> ``not_evaluated``
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Mapping

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.domain.evidence import ClaimEvidenceLinkV1  # noqa: E402
from src.web.research.claim_evidence_assessment import (  # noqa: E402
    assess_claim_evidence,
)
from src.web.research.contracts import (  # noqa: E402
    EvidenceCluster,
    EvidenceRequirement,
    ResearchBudget,
    ResearchClaim,
    ResearchClaimEvidenceLink,
    ResearchEvidence,
    ResearchQuestion,
    build_research_state,
)
from src.web.research.evidence_units import EvidenceUnit, RequiredUnit  # noqa: E402

SCHEMA_VERSION = "rq-b-semantic-validation-v1"
DEFAULT_COHORT = REPO_ROOT / "docs" / "research_quality" / "F2_PAIRED.threshold_safe.json"
DEFAULT_OUTPUT = REPO_ROOT / "docs" / "research_quality" / "RQ_B_SEMANTIC_VALIDATION.json"

SIDES = ("default", "crawl4ai")
SHORT_ADEQUACY = frozenset({"partial", "insufficient"})


def _units(raw: Any) -> tuple[str, ...]:
    return tuple(str(item) for item in (raw or []))


def build_side_state(
    item: Mapping[str, Any],
    *,
    side: str,
    with_requirement: bool = True,
) -> Any:
    """Project one cohort side onto the RQ-A input contract.

    ``expected_critical_units`` is the claim-side requirement (never inferred);
    the side's ``unit_set`` is what the reader actually recovered.
    """

    expected = _units(item.get("expected_critical_units")) if with_requirement else ()
    recovered = _units((item.get(side) or {}).get("unit_set"))
    requirement = EvidenceRequirement(
        source_roles=("primary",),
        min_independent_sources=1,
        requires_primary_source=False,
        requires_successful_read=True,
        required_units=tuple(RequiredUnit(unit_id=unit) for unit in expected),
    )
    evidence = ResearchEvidence(
        "ev",
        lifecycle_status="read",
        extraction_status="eligible",
        units=tuple(EvidenceUnit(unit_id=unit) for unit in recovered),
    )
    link = ResearchClaimEvidenceLink(
        ClaimEvidenceLinkV1("claim", "ev", "supports", 1.0),
        source_role="primary",
        source_cluster_id="c1",
    )
    return build_research_state(
        mode="shadow",
        questions=[ResearchQuestion("q", "Which units does this source cover?", "critical")],
        claims=[
            ResearchClaim(
                "claim",
                "q",
                "The source covers the required units.",
                "factual",
                "critical",
                "searching",
                requirement,
            )
        ],
        evidence=(evidence,),
        evidence_links=(link,),
        source_clusters=(EvidenceCluster("c1", ("ev",)),),
        gaps=(),
        conflict_gaps=(),
        budget=ResearchBudget(5, 2, 45, 60, 6000),
        known_evidence_ids=("ev",),
    )


def assess_side(item: Mapping[str, Any], *, side: str) -> dict[str, Any]:
    """One cohort side judged by RQ-A, with its declared read outcome."""

    state = build_side_state(item, side=side)
    assessment = assess_claim_evidence(state, state.claims[0])
    side_payload = item.get(side) or {}
    expected = _units(item.get("expected_critical_units"))
    recovered = _units(side_payload.get("unit_set"))
    return {
        "category": str(item.get("category") or ""),
        "fixture": str(item.get("fixture") or ""),
        "side": side,
        "read_useful": bool(side_payload.get("useful")),
        "expected_unit_count": len(expected),
        "recovered_unit_count": len(recovered),
        "semantic_adequacy": assessment.semantic_adequacy,
        "claim_state": assessment.state,
        "missing_unit_count": len(assessment.missing_units),
    }


def assess_without_requirement(item: Mapping[str, Any], *, side: str) -> dict[str, Any]:
    """The same side judged with no claim-side requirement at all."""

    state = build_side_state(item, side=side, with_requirement=False)
    assessment = assess_claim_evidence(state, state.claims[0])
    return {
        "category": str(item.get("category") or ""),
        "side": side,
        "semantic_adequacy": assessment.semantic_adequacy,
        "claim_state": assessment.state,
    }


def validate_cohort(cohort: Mapping[str, Any]) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for item in cohort.get("raw") or []:
        for side in SIDES:
            rows.append(assess_side(item, side=side))

    no_requirement_rows = [
        assess_without_requirement(item, side=side)
        for item in cohort.get("raw") or []
        for side in SIDES
    ]

    full = [r for r in rows if r["expected_unit_count"] and r["missing_unit_count"] == 0]
    short = [
        r
        for r in rows
        if r["read_useful"] and r["missing_unit_count"] > 0
    ]

    contrast_full_ok = all(
        r["semantic_adequacy"] == "adequate" and r["claim_state"] == "satisfied" for r in full
    )
    contrast_short_ok = all(
        r["semantic_adequacy"] in SHORT_ADEQUACY and r["claim_state"] != "satisfied"
        for r in short
    )
    contrast_none_ok = all(
        r["semantic_adequacy"] == "not_evaluated" for r in no_requirement_rows
    )
    # Universal invariant: "satisfied" may never coexist with a missing unit.
    no_false_satisfied = all(
        r["claim_state"] != "satisfied" or r["missing_unit_count"] == 0 for r in rows
    )

    verdict = (
        "PASS"
        if contrast_full_ok
        and contrast_short_ok
        and contrast_none_ok
        and no_false_satisfied
        and full
        and short
        and no_requirement_rows
        else "FAIL"
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "cohort": DEFAULT_COHORT.name,
        "rows": rows,
        "contrasts": {
            "full_coverage": {
                "count": len(full),
                "rule": "adequate + satisfied",
                "ok": contrast_full_ok,
                "examples": [f"{r['category']}/{r['side']}" for r in full[:6]],
            },
            "read_success_units_short": {
                "count": len(short),
                "rule": "partial/insufficient and never satisfied",
                "ok": contrast_short_ok,
                "examples": [f"{r['category']}/{r['side']}" for r in short[:6]],
            },
            "no_required_units": {
                "count": len(no_requirement_rows),
                "rule": "not_evaluated",
                "ok": contrast_none_ok,
            },
            "no_false_satisfied": {"ok": no_false_satisfied},
        },
        "summary": {
            "rows": len(rows),
            "adequate": sum(1 for r in rows if r["semantic_adequacy"] == "adequate"),
            "partial": sum(1 for r in rows if r["semantic_adequacy"] == "partial"),
            "insufficient": sum(1 for r in rows if r["semantic_adequacy"] == "insufficient"),
            "not_evaluated": sum(
                1 for r in rows if r["semantic_adequacy"] == "not_evaluated"
            ),
            "read_useful": sum(1 for r in rows if r["read_useful"]),
            "read_useful_but_units_short": len(short),
        },
        "verdict": verdict,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate RQ-A on the §143-B cohort")
    parser.add_argument("--cohort", type=Path, default=DEFAULT_COHORT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)

    cohort = json.loads(args.cohort.read_text(encoding="utf-8"))
    artifact = validate_cohort(cohort)
    args.output.write_text(
        json.dumps(artifact, indent=1, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    summary = artifact["summary"]
    print(
        f"RQ-B {artifact['verdict']}: rows={summary['rows']} "
        f"adequate={summary['adequate']} partial={summary['partial']} "
        f"insufficient={summary['insufficient']} "
        f"read_useful_but_units_short={summary['read_useful_but_units_short']}"
    )
    return 0 if artifact["verdict"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
