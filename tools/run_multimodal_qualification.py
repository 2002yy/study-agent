"""Multimodal Reader v1 qualification (Q1-Q6).

Frozen context: ``docs/PROJECT_STATUS.md`` §144.17.

Deterministic, no network and no model call: every scenario drives the production
seams (``read_visual_evidence``, the SSRF-aware fetcher, the RQ assessors) with an
injected fetcher/adapter, and records what actually happened.

Scenarios:

* Q1 default-inert  -- vision disabled: no fetch, no vision call, no units;
* Q2 enabled        -- enabled + declared + allowed image: one visual unit;
* Q3 semantic value -- that unit changes RQ-A adequacy and flows into RQ-C/RQ-D;
* Q4 fail-closed    -- SSRF and provider failures stay unavailable, text-side safe;
* Q5 provenance     -- page/region/source/provenance + audit are traceable;
* Q6 budget         -- one vision call charged, derived from the same clock,
                       ``reads_used`` untouched.

The read-site-level invariants (declared metadata + enabled ⇒ units on the source
record; failure ⇒ the text read stays successful) are locked separately by
``tests/test_read_site_visual_evidence.py``; this artifact records that reference
instead of re-running the runtime harness.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any, Callable

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.application.research_visual_read import read_visual_evidence  # noqa: E402
from src.application.research_vision_adapter import (  # noqa: E402
    build_research_vision_adapter,
)
from src.domain.evidence import ClaimEvidenceLinkV1  # noqa: E402
from src.web.research.claim_conflict_assessment import (  # noqa: E402
    assess_claim_conflict,
)
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
    ResearchState,
    build_research_state,
)
from src.web.research.coverage_stop_assessment import (  # noqa: E402
    assess_coverage_stop,
)
from src.web.research.evidence_units import RequiredUnit  # noqa: E402
from src.web.research.visual_image_fetch import ImageFetchError  # noqa: E402
from src.web.research.visual_image_http import fetch_image  # noqa: E402
from src.web.research.visual_read_budget import (  # noqa: E402
    MAX_VISION_CALLS_ENV,
    VISUAL_AUDIT_KEY,
    visual_read_budget,
)

SCHEMA_VERSION = "multimodal-qualification-v1"
DEFAULT_OUTPUT = REPO_ROOT / "docs" / "research_quality" / "MULTIMODAL_QUALIFICATION.json"

READ_SITE_E2E_REFERENCE = "tests/test_read_site_visual_evidence.py"

_PNG = b"\x89PNG\r\n\x1a\n" + b"q" * 64
_METADATA = {
    "image_id": "fig4",
    "kind": "chart",
    "source": "https://cdn.example.com/figure4.png",
    "page": 4,
    "region": "bbox:10,10,200,120",
    "alt": "platform support matrix",
    "triggers": ["text_references_figure"],
    "carries_required_evidence": True,
}
_REQUIRED = ("fig4",)
_DESCRIPTION = "Figure 4: feature X is unsupported on Windows."


def _state(*, elapsed: float = 1.0, units: tuple[Any, ...] = ()) -> ResearchState:
    requirement = EvidenceRequirement(
        source_roles=("primary", "community"),
        min_independent_sources=1,
        requires_successful_read=True,
        required_units=(RequiredUnit("fig4", "figure 4 conclusion", "visual"),),
    )
    evidence = (
        ResearchEvidence(
            "ev_fig",
            lifecycle_status="read",
            extraction_status="eligible",
            units=units,
        ),
    )
    return build_research_state(
        mode="shadow",
        questions=[ResearchQuestion("q1", "Is feature X supported on Windows?", "critical")],
        claims=[
            ResearchClaim(
                "c1",
                "q1",
                "Feature X is unsupported on Windows.",
                "factual",
                "critical",
                "searching",
                requirement,
            )
        ],
        evidence=evidence,
        evidence_links=(),
        source_clusters=(),
        gaps=(),
        conflict_gaps=(),
        budget=ResearchBudget(20, 8, 45, 60, 16000, elapsed_seconds=elapsed),
        known_evidence_ids=("ev_fig",),
    )


def _rq_view(state: ResearchState, *, contradictory: bool = False) -> dict[str, Any]:
    """RQ-A/C/D view of the same claim; a contradiction can be added for RQ-C."""

    links = [
        ResearchClaimEvidenceLink(
            ClaimEvidenceLinkV1("c1", "ev_fig", "supports", 0.9),
            source_role="primary",
            source_cluster_id="k_fig",
        )
    ]
    clusters = [EvidenceCluster("k_fig", ("ev_fig",))]
    evidence = list(state.evidence)
    if contradictory:
        evidence.append(
            ResearchEvidence(
                "ev_text",
                lifecycle_status="read",
                extraction_status="eligible",
                units=(),
            )
        )
        links.append(
            ResearchClaimEvidenceLink(
                ClaimEvidenceLinkV1("c1", "ev_text", "contradicts", 0.9),
                source_role="community",
                source_cluster_id="k_text",
            )
        )
        clusters.append(EvidenceCluster("k_text", ("ev_text",)))
    view = build_research_state(
        mode="shadow",
        questions=state.questions,
        claims=state.claims,
        evidence=tuple(evidence),
        evidence_links=tuple(links),
        source_clusters=tuple(clusters),
        gaps=(),
        conflict_gaps=(),
        budget=state.budget,
        known_evidence_ids=tuple(item.evidence_id for item in evidence),
    )
    claim = view.claims[0]
    coverage = assess_coverage_stop(view)
    return {
        "adequacy": assess_claim_evidence(view, claim).semantic_adequacy,
        "claim_state": assess_claim_evidence(view, claim).state,
        "conflict_status": assess_claim_conflict(view, claim).status,
        "conflict_preferred_side": assess_claim_conflict(view, claim).preferred_side,
        "coverage_recommendation": coverage.recommendation,
    }


def _read(*, vision_calls: int | None, fetcher: Any, adapter: Any, context: dict, tmp: Path):
    return read_visual_evidence(
        read_payload={"visual_metadata": [_METADATA]},
        required_units=_REQUIRED,
        state=_state(),
        context=context,
        fetcher=fetcher,
        destination_dir=tmp,
        adapter=adapter,
    )


def _enabled_adapter(described: list[str], *, failing: bool = False) -> Any:
    def describer(path: Path) -> str:
        described.append(str(path))
        if failing:
            raise RuntimeError("provider unavailable")
        return _DESCRIPTION

    return build_research_vision_adapter(enabled=True, describer=describer)


def _fetcher(fetches: list[str]) -> Callable[[str], tuple[bytes, str]]:
    def fetch(url: str) -> tuple[bytes, str]:
        fetches.append(url)
        return _PNG, "image/png"

    return fetch


def scenario_q1(tmp: Path, monkeypatch_env: Callable[[str | None], None]) -> dict[str, Any]:
    monkeypatch_env(None)
    fetches: list[str] = []
    described: list[str] = []
    context: dict = {}
    result = _read(
        vision_calls=None,
        fetcher=_fetcher(fetches),
        adapter=_enabled_adapter(described),
        context=context,
        tmp=tmp,
    )
    passed = (
        fetches == []
        and described == []
        and result.units == ()
        and result.vision_calls == 0
    )
    return {
        "id": "Q1_default_inert",
        "gate": {"max_vision_calls": 0, "declared_metadata": True},
        "fetched": bool(fetches),
        "vision_called": bool(described),
        "units": len(result.units),
        "vision_calls": result.vision_calls,
        "read_site_e2e_reference": READ_SITE_E2E_REFERENCE,
        "verdict": "PASS" if passed else "FAIL",
    }


def scenario_q2(tmp: Path, monkeypatch_env: Callable[[str | None], None]) -> dict[str, Any]:
    monkeypatch_env("1")
    fetches: list[str] = []
    described: list[str] = []
    context: dict = {}
    result = _read(
        vision_calls=1,
        fetcher=_fetcher(fetches),
        adapter=_enabled_adapter(described),
        context=context,
        tmp=tmp,
    )
    unit = result.units[0] if result.units else None
    passed = (
        len(result.units) == 1
        and result.vision_calls == 1
        and fetches == [_METADATA["source"]]
        and len(described) == 1
    )
    return {
        "id": "Q2_enabled_declared",
        "gate": {"max_vision_calls": 1, "declared_metadata": True},
        "fetched": bool(fetches),
        "vision_called": bool(described),
        "units": len(result.units),
        "vision_calls": result.vision_calls,
        "unit": unit.to_dict() if unit else None,
        "verdict": "PASS" if passed else "FAIL",
    }


def scenario_q3(tmp: Path, monkeypatch_env: Callable[[str | None], None]) -> dict[str, Any]:
    monkeypatch_env("1")
    described: list[str] = []
    result = _read(
        vision_calls=1,
        fetcher=_fetcher([]),
        adapter=_enabled_adapter(described),
        context={},
        tmp=tmp,
    )
    unit = result.units[0] if result.units else None
    before = _rq_view(_state(units=()))
    after = _rq_view(_state(units=(unit,) if unit else ()))
    conflict_before = _rq_view(_state(units=(unit,) if unit else ()), contradictory=True)
    passed = (
        unit is not None
        and before["adequacy"] in {"insufficient", "partial"}
        and after["adequacy"] == "adequate"
        and after["claim_state"] == "satisfied"
        and before["coverage_recommendation"] == "continue_candidate"
        and after["coverage_recommendation"] == "stop_candidate"
        and conflict_before["conflict_status"] == "preferred_side"
        and conflict_before["conflict_preferred_side"] == "support"
    )
    return {
        "id": "Q3_semantic_value",
        "rq_a_c_d_before": before,
        "rq_a_c_d_after": after,
        "rq_c_with_contradiction": conflict_before,
        "verdict": "PASS" if passed else "FAIL",
    }


def scenario_q4(tmp: Path, monkeypatch_env: Callable[[str | None], None]) -> dict[str, Any]:
    monkeypatch_env("1")
    described: list[str] = []

    # (a) SSRF: the real fetcher refuses a private target before any read.
    ssrf_reason = ""
    try:
        fetch_image("http://127.0.0.1/pic.png")
    except ImageFetchError as exc:
        ssrf_reason = exc.reason
    ssrf_result = read_visual_evidence(
        read_payload={"visual_metadata": [{**_METADATA, "source": "http://127.0.0.1/pic.png"}]},
        required_units=_REQUIRED,
        state=_state(),
        context={},
        fetcher=fetch_image,
        destination_dir=tmp,
        adapter=_enabled_adapter(described),
    )

    # (b) provider failure after a successful fetch.
    provider_result = _read(
        vision_calls=1,
        fetcher=_fetcher([]),
        adapter=_enabled_adapter([], failing=True),
        context={},
        tmp=tmp,
    )

    passed = (
        ssrf_reason == "image_url_not_public"
        and ssrf_result.units == ()
        and ssrf_result.vision_calls == 0
        and ssrf_result.outcomes[0].reason == "image_url_not_public"
        and provider_result.units == ()
        and provider_result.outcomes[0].reason == "vision_description_failed"
    )
    return {
        "id": "Q4_fail_closed",
        "ssrf": {
            "fetcher_reason": ssrf_reason,
            "outcome_reason": ssrf_result.outcomes[0].reason,
            "units": len(ssrf_result.units),
            "vision_calls": ssrf_result.vision_calls,
        },
        "provider_failure": {
            "outcome_reason": provider_result.outcomes[0].reason,
            "units": len(provider_result.units),
            "vision_calls": provider_result.vision_calls,
        },
        "text_read_guarantee": READ_SITE_E2E_REFERENCE,
        "verdict": "PASS" if passed else "FAIL",
    }


def scenario_q5(tmp: Path, monkeypatch_env: Callable[[str | None], None]) -> dict[str, Any]:
    monkeypatch_env("1")
    context: dict = {}
    result = _read(
        vision_calls=1,
        fetcher=_fetcher([]),
        adapter=_enabled_adapter([]),
        context=context,
        tmp=tmp,
    )
    unit = result.units[0] if result.units else None
    audit = context.get(VISUAL_AUDIT_KEY) or []
    traceable = bool(
        unit is not None
        and unit.page == 4
        and unit.region == "bbox:10,10,200,120"
        and unit.source == _METADATA["source"]
        and unit.provenance.startswith(_METADATA["source"])
        and audit
        and audit[0]["purpose"] == "image_description"
        and audit[0]["status"] == "normalized"
    )
    return {
        "id": "Q5_provenance",
        "unit": unit.to_dict() if unit else None,
        "audit": audit,
        "verdict": "PASS" if traceable else "FAIL",
    }


def scenario_q6(tmp: Path, monkeypatch_env: Callable[[str | None], None]) -> dict[str, Any]:
    monkeypatch_env("1")
    state = _state()
    reads_before = state.budget.reads_used
    budget = visual_read_budget(state)
    near_deadline = visual_read_budget(_state(elapsed=59.0))
    result = _read(
        vision_calls=1,
        fetcher=_fetcher([]),
        adapter=_enabled_adapter([]),
        context={},
        tmp=tmp,
    )
    reads_after = state.budget.reads_used
    passed = (
        budget.max_vision_calls == 1
        and near_deadline.max_vision_calls == 0
        and result.vision_calls == 1
        and reads_before == reads_after
    )
    return {
        "id": "Q6_budget",
        "max_vision_calls_with_time_left": budget.max_vision_calls,
        "max_vision_calls_near_deadline": near_deadline.max_vision_calls,
        "vision_calls_used": result.vision_calls,
        "reads_used_before": reads_before,
        "reads_used_after": reads_after,
        "verdict": "PASS" if passed else "FAIL",
    }


def _env_setter(value: str | None) -> Callable[[str | None], None]:
    def apply(new: str | None) -> None:
        if new is None:
            os.environ.pop(MAX_VISION_CALLS_ENV, None)
        else:
            os.environ[MAX_VISION_CALLS_ENV] = new

    apply(value)
    return apply


def run_qualification() -> dict[str, Any]:
    setter = _env_setter(None)
    scenarios: list[dict[str, Any]] = []
    try:
        with tempfile.TemporaryDirectory(prefix="multimodal_qual_") as directory:
            tmp = Path(directory)
            for runner in (scenario_q1, scenario_q2, scenario_q3, scenario_q4, scenario_q5, scenario_q6):
                scenarios.append(runner(tmp, setter))
    finally:
        setter(None)

    verdict = "PASS" if all(item["verdict"] == "PASS" for item in scenarios) else "FAIL"
    return {
        "schema_version": SCHEMA_VERSION,
        "scenarios": scenarios,
        "verdict": verdict,
        "read_site_e2e_reference": READ_SITE_E2E_REFERENCE,
        "notes": [
            "Deterministic: injected fetcher/adapter, no network, no model call.",
            "Default-inert: max_vision_calls=0 means no fetch and no vision call.",
            "Read-site-level invariants are locked by the referenced e2e test.",
        ],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Multimodal Reader v1 qualification")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)

    artifact = run_qualification()
    args.output.write_text(
        json.dumps(artifact, indent=1, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    passed = sum(1 for item in artifact["scenarios"] if item["verdict"] == "PASS")
    print(f"multimodal qualification {artifact['verdict']}: {passed}/{len(artifact['scenarios'])} scenarios")
    return 0 if artifact["verdict"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
