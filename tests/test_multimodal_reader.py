"""§144.11 Multimodal Reader v1: discovery, escalation, vision, normalization."""

from __future__ import annotations

import pytest

from src.domain.evidence import ClaimEvidenceLinkV1
from src.web.research.claim_evidence_assessment import assess_claim_evidence
from src.web.research.contracts import (
    EvidenceCluster,
    EvidenceRequirement,
    ResearchBudget,
    ResearchClaim,
    ResearchClaimEvidenceLink,
    ResearchEvidence,
    ResearchQuestion,
    build_research_state,
)
from src.web.research.evidence_units import RequiredUnit
from src.web.research.multimodal_reader import (
    REASON_NORMALIZED_LOWER_LEVEL,
    REASON_NORMALIZED_VISION,
    REASON_VISION_BUDGET_EXHAUSTED,
    REASON_VISION_FAILED,
    REASON_VISION_NOT_CONFIGURED,
    VisionAdapter,
    VisionObservation,
    VisionUnavailable,
    VisualImage,
    VisualReadBudget,
    discover_visual_candidates,
    plan_visual_escalation,
    read_visual_candidates,
    to_evidence_unit,
    visual_prompt,
)

_CHART = VisualImage(
    image_id="fig4",
    kind="chart",
    source="report.pdf",
    page=4,
    region="bbox:10,10,200,120",
    caption="Figure 4: platform support",
    triggers=("text_references_figure",),
    carries_required_evidence=True,
)


def _observer(observation: VisionObservation | None = None):
    calls: list[dict] = []

    def observe(*, image, prompt):
        calls.append({"image_id": image.image_id, "prompt": prompt})
        return observation or VisionObservation(
            text="Figure 4 shows feature X is unsupported on Windows.",
            confidence=0.8,
            model="fake-vision",
            latency_ms=12.0,
        )

    return observe, calls


# --------------------------------------------------------------- discovery

def test_discovery_requires_a_declared_trigger() -> None:
    untriggered = VisualImage(image_id="i1", kind="image", source="https://x/y.png")

    assert discover_visual_candidates([untriggered]) == ()


def test_discovery_drops_a_candidate_without_provenance() -> None:
    unlocated = VisualImage(
        image_id="i1", kind="image", source="", triggers=("text_references_figure",)
    )

    assert discover_visual_candidates([unlocated]) == ()


def test_discovery_accepts_a_triggered_located_candidate() -> None:
    candidates = discover_visual_candidates([_CHART])

    assert len(candidates) == 1
    assert candidates[0].reason == "text_references_figure"
    assert candidates[0].provenance == "report.pdf#page=4#region=bbox:10,10,200,120"
    assert candidates[0].source_type == "chart"


def test_user_request_adds_the_trigger_without_metadata() -> None:
    plain = VisualImage(image_id="shot", kind="screenshot", source="https://x/s.png")

    candidates = discover_visual_candidates([plain], user_requested=True)

    assert len(candidates) == 1
    assert candidates[0].reason == "user_requested"


def test_source_type_mapping_covers_the_frozen_vocabulary() -> None:
    def candidate(kind: str):
        return discover_visual_candidates(
            [
                VisualImage(
                    image_id="i",
                    kind=kind,  # type: ignore[arg-type]
                    source="https://x/y",
                    triggers=("user_requested",),
                )
            ]
        )[0]

    assert candidate("diagram").source_type == "image"
    assert candidate("pdf_figure").source_type == "pdf_figure"
    assert candidate("table").source_type == "table"
    assert candidate("screenshot").source_type == "screenshot"


# -------------------------------------------------------------- escalation

def test_escalation_stops_at_the_first_sufficient_level() -> None:
    candidate = discover_visual_candidates([_CHART])[0]

    text_plan = plan_visual_escalation(
        candidate,
        required_units=("a",),
        available_units_by_level={"text": ("a",)},
    )
    alt_plan = plan_visual_escalation(
        candidate,
        required_units=("a",),
        available_units_by_level={"text": (), "alt": ("a",)},
    )
    ocr_plan = plan_visual_escalation(
        candidate,
        required_units=("a",),
        available_units_by_level={"text": (), "alt": (), "ocr": ("a",)},
    )

    assert text_plan is not None and alt_plan is not None and ocr_plan is not None
    assert (text_plan.stop_at, text_plan.needs_vision) == ("text", False)
    assert (alt_plan.stop_at, alt_plan.needs_vision) == ("alt", False)
    assert (ocr_plan.stop_at, ocr_plan.needs_vision) == ("ocr", False)


def test_escalation_reaches_vision_only_for_declared_required_evidence() -> None:
    carrying = discover_visual_candidates([_CHART])[0]
    plain_image = VisualImage(
        image_id="i2",
        kind="image",
        source="https://x/y.png",
        triggers=("user_requested",),
        carries_required_evidence=False,
    )
    plain = discover_visual_candidates([plain_image])[0]

    carrying_plan = plan_visual_escalation(carrying, required_units=("a",))
    assert carrying_plan is not None
    assert carrying_plan.needs_vision is True
    assert plan_visual_escalation(plain, required_units=("a",)) is None


def test_lower_level_material_is_used_when_it_already_covers_the_requirement() -> None:
    image = VisualImage(
        image_id="fig9",
        kind="pdf_figure",
        source="report.pdf",
        page=9,
        alt="Figure 9: latency by backend",
        ocr_text="backend latency_ms",
        triggers=("text_references_figure",),
        carries_required_evidence=True,
    )
    observe, calls = _observer()

    result = read_visual_candidates(
        images=[image],
        required_units=("latency",),
        available_units_by_level={"alt": ("latency",)},
        adapter=VisionAdapter(observe),
        budget=VisualReadBudget(max_vision_calls=3),
    )

    assert result.vision_calls == 0
    assert calls == []
    assert result.outcomes[0].status == "normalized"
    assert result.outcomes[0].reason == REASON_NORMALIZED_LOWER_LEVEL
    assert result.outcomes[0].stop_at == "alt"
    assert result.units[0].content == "Figure 9: latency by backend"


# ----------------------------------------------------------------- vision

def test_vision_is_fail_closed_when_not_configured() -> None:
    result = read_visual_candidates(images=[_CHART], required_units=("a",))

    assert result.vision_calls == 0
    assert result.outcomes[0].status == "unavailable"
    assert result.outcomes[0].reason == REASON_VISION_NOT_CONFIGURED
    assert result.units == ()


def test_vision_observation_is_normalized_with_provenance() -> None:
    observe, calls = _observer()
    adapter = VisionAdapter(observe)

    result = read_visual_candidates(
        images=[_CHART],
        required_units=("feature_x_windows",),
        adapter=adapter,
        budget=VisualReadBudget(max_vision_calls=2),
    )

    assert result.vision_calls == 1
    assert len(calls) == 1
    assert "feature_x_windows" in calls[0]["prompt"]
    assert result.outcomes[0].reason == REASON_NORMALIZED_VISION
    unit = result.units[0]
    assert unit.source_type == "chart"
    assert unit.page == 4
    assert unit.region == "bbox:10,10,200,120"
    assert unit.provenance == "report.pdf#page=4#region=bbox:10,10,200,120"
    assert unit.confidence == 0.8
    assert "unsupported on Windows" in unit.observation
    assert unit.is_visual is True


def test_vision_prompt_is_bounded_and_anchored_to_the_requirement() -> None:
    candidate = discover_visual_candidates([_CHART])[0]

    prompt = visual_prompt(candidate, required_units=("u1", "u2"))

    assert "u1, u2" in prompt
    assert "Do not infer" in prompt


def test_vision_failure_never_breaks_the_read() -> None:
    def exploding(*, image, prompt):
        raise RuntimeError("provider blew up")

    result = read_visual_candidates(
        images=[_CHART],
        required_units=("a",),
        adapter=VisionAdapter(exploding),
        budget=VisualReadBudget(max_vision_calls=1),
    )

    assert result.outcomes[0].status == "unavailable"
    assert result.outcomes[0].reason == REASON_VISION_FAILED
    assert result.units == ()


def test_adapter_raises_vision_unavailable_by_default() -> None:
    with pytest.raises(VisionUnavailable):
        VisionAdapter().observe(image=_CHART, prompt="p")


# ----------------------------------------------------------------- budget

def test_budget_is_charged_per_vision_call_and_never_reset() -> None:
    budget = VisualReadBudget(max_vision_calls=1)
    observe, _ = _observer()

    result = read_visual_candidates(
        images=[_CHART],
        required_units=("a",),
        adapter=VisionAdapter(observe),
        budget=budget,
    )

    assert result.vision_calls == 1
    assert budget.vision_calls == 1
    assert budget.remaining == 0
    assert budget.exhausted is True


def test_exhausted_budget_skips_vision_without_calling_it() -> None:
    observe, calls = _observer()
    budget = VisualReadBudget(max_vision_calls=0)

    result = read_visual_candidates(
        images=[_CHART],
        required_units=("a",),
        adapter=VisionAdapter(observe),
        budget=budget,
    )

    assert calls == []
    assert result.outcomes[0].status == "unavailable"
    assert result.outcomes[0].reason == REASON_VISION_BUDGET_EXHAUSTED


def test_one_budget_slot_serves_only_the_first_image() -> None:
    second = VisualImage(
        image_id="fig5",
        kind="chart",
        source="report.pdf",
        page=5,
        triggers=("text_references_figure",),
        carries_required_evidence=True,
    )
    observe, calls = _observer()

    result = read_visual_candidates(
        images=[_CHART, second],
        required_units=("a",),
        adapter=VisionAdapter(observe),
        budget=VisualReadBudget(max_vision_calls=1),
    )

    assert len(calls) == 1
    assert result.statuses == ("normalized", "unavailable")
    assert result.outcomes[1].reason == REASON_VISION_BUDGET_EXHAUSTED


# ------------------------------------------------------------ normalize

def test_normalize_refuses_an_unlocated_visual_assertion() -> None:
    unlocated = VisualImage(
        image_id="i1", kind="image", source="", triggers=("user_requested",)
    )
    candidate = type(discover_visual_candidates([_CHART])[0])(
        image=unlocated, reason="user_requested", provenance=""
    )

    with pytest.raises(ValueError):
        to_evidence_unit(candidate)


def test_read_result_is_serialisable_for_provenance() -> None:
    observe, _ = _observer()
    result = read_visual_candidates(
        images=[_CHART],
        required_units=("a",),
        adapter=VisionAdapter(observe),
        budget=VisualReadBudget(max_vision_calls=1),
    )

    payload = result.to_dict()

    assert payload["vision_calls"] == 1
    assert payload["outcomes"][0]["unit"]["provenance"].startswith("report.pdf#page=4")


# ------------------------------------------------- feed the existing RQ chain

def _rq_state(unit):
    requirement = EvidenceRequirement(
        source_roles=("primary",),
        min_independent_sources=1,
        requires_successful_read=True,
        required_units=(RequiredUnit("fig4", "figure 4 conclusion", "visual"),),
    )
    evidence = ResearchEvidence(
        "ev1", lifecycle_status="read", extraction_status="eligible", units=(unit,)
    )
    link = ResearchClaimEvidenceLink(
        ClaimEvidenceLinkV1("c1", "ev1", "supports", 0.9),
        source_role="primary",
        source_cluster_id="k1",
    )
    return build_research_state(
        mode="shadow",
        questions=[ResearchQuestion("q1", "Is feature X supported?", "critical")],
        claims=[
            ResearchClaim(
                "c1", "q1", "Feature X is unsupported.", "factual", "critical", "searching", requirement
            )
        ],
        evidence=(evidence,),
        evidence_links=(link,),
        source_clusters=(EvidenceCluster("k1", ("ev1",)),),
        gaps=(),
        conflict_gaps=(),
        budget=ResearchBudget(20, 8, 45, 60, 16000),
        known_evidence_ids=("ev1",),
    )


def test_vision_units_satisfy_a_visual_requirement_in_rq_a() -> None:
    observe, _ = _observer()
    result = read_visual_candidates(
        images=[_CHART],
        required_units=("fig4",),
        adapter=VisionAdapter(observe),
        budget=VisualReadBudget(max_vision_calls=1),
    )
    state = _rq_state(result.units[0])

    assessment = assess_claim_evidence(state, state.claims[0])

    assert assessment.semantic_adequacy == "adequate"
    assert assessment.state == "satisfied"


def test_lower_level_units_also_feed_rq_a_without_vision() -> None:
    image = VisualImage(
        image_id="fig4",
        kind="chart",
        source="report.pdf",
        page=4,
        region="bbox:1",
        ocr_text="feature X unsupported",
        triggers=("text_references_figure",),
        carries_required_evidence=True,
    )
    result = read_visual_candidates(
        images=[image],
        required_units=("fig4",),
        available_units_by_level={"ocr": ("fig4",)},
        budget=VisualReadBudget(max_vision_calls=1),
    )
    state = _rq_state(result.units[0])

    assessment = assess_claim_evidence(state, state.claims[0])

    assert result.vision_calls == 0
    assert assessment.semantic_adequacy == "adequate"
