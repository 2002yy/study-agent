"""§144.13 boundaries 2-4: research-side wiring, budget, audit, fail-closed.

Operator-style end-to-end run with an injected fetcher and describer: no network
and no real model call, but the full production composition (metadata projection
-> bounded fetch -> G14-c-shaped adapter -> units -> RQ-A -> audit + budget).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.application.research_vision_adapter import (
    REASON_DESCRIPTION_FAILED,
    REASON_EMPTY_DESCRIPTION,
    REASON_NOT_MATERIALIZED,
    build_research_vision_adapter,
)
from src.application.research_visual_read import read_visual_evidence
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
    ResearchState,
    build_research_state,
)
from src.web.research.evidence_units import RequiredUnit
from src.web.research.multimodal_reader import (
    VisualImage,
)
from src.web.research.visual_metadata import VISUAL_METADATA_KEY
from src.web.research.visual_read_budget import (
    MAX_VISION_CALLS_ENV,
    VISUAL_AUDIT_KEY,
    configured_max_vision_calls,
    visual_read_budget,
)

_PNG = b"\x89PNG\r\n\x1a\n" + b"y" * 48

_METADATA = {
    "image_id": "fig4",
    "kind": "chart",
    "source": "https://docs.example/report.pdf",
    "page": 4,
    "region": "bbox:10,10,200,120",
    "alt": "platform support matrix",
    "triggers": ["text_references_figure"],
    "carries_required_evidence": True,
}


def _state(*, elapsed: float = 1.0) -> ResearchState:
    requirement = EvidenceRequirement(
        source_roles=("primary",),
        min_independent_sources=1,
        requires_successful_read=True,
        required_units=(RequiredUnit("fig4", "figure 4 conclusion", "visual"),),
    )
    return build_research_state(
        mode="shadow",
        questions=[ResearchQuestion("q1", "Is feature X supported?", "critical")],
        claims=[
            ResearchClaim(
                "c1", "q1", "Feature X is unsupported.", "factual", "critical", "searching", requirement
            )
        ],
        evidence=(),
        evidence_links=(),
        source_clusters=(),
        gaps=(),
        conflict_gaps=(),
        budget=ResearchBudget(20, 8, 45, 60, 16000, elapsed_seconds=elapsed),
        known_evidence_ids=(),
    )


def _fake_fetcher(calls: list[str]):
    def fetch(url: str):
        calls.append(url)
        return _PNG, "image/png"

    return fetch


def _describer(calls: list[str], text: str = "Figure 4: feature X unsupported on Windows."):
    def describe(path: Path) -> str:
        calls.append(str(path))
        return text

    return describe


# ------------------------------------------------------------------- budget

def test_max_vision_calls_defaults_to_zero(monkeypatch) -> None:
    monkeypatch.delenv(MAX_VISION_CALLS_ENV, raising=False)

    assert configured_max_vision_calls() == 0
    assert visual_read_budget(_state()).max_vision_calls == 0


def test_max_vision_calls_reads_the_operator_setting(monkeypatch) -> None:
    monkeypatch.setenv(MAX_VISION_CALLS_ENV, "3")
    assert configured_max_vision_calls() == 3

    monkeypatch.setenv(MAX_VISION_CALLS_ENV, "nonsense")
    assert configured_max_vision_calls() == 0

    monkeypatch.setenv(MAX_VISION_CALLS_ENV, "-2")
    assert configured_max_vision_calls() == 0


def test_budget_collapses_when_the_hard_clock_is_almost_spent(monkeypatch) -> None:
    monkeypatch.setenv(MAX_VISION_CALLS_ENV, "3")

    assert visual_read_budget(_state(elapsed=1.0)).max_vision_calls == 3
    assert visual_read_budget(_state(elapsed=59.0)).max_vision_calls == 0


# ------------------------------------------------------------------ adapter

def test_adapter_is_inert_when_the_gate_is_off() -> None:
    adapter = build_research_vision_adapter(enabled=False)

    assert adapter.available is False


def _probe_image(*, local_path: str = "") -> VisualImage:
    return VisualImage(
        image_id="fig4",
        kind="chart",
        source="https://docs.example/report.pdf",
        local_path=local_path,
    )


def test_adapter_requires_a_materialized_file() -> None:
    adapter = build_research_vision_adapter(enabled=True, describer=lambda path: "x")

    with pytest.raises(Exception) as exc:
        adapter.observe(image=_probe_image(), prompt="ignored")

    assert REASON_NOT_MATERIALIZED in str(exc.value)


def test_adapter_normalizes_describer_failures() -> None:
    def explode(path: Path) -> str:
        raise RuntimeError("provider blew up")

    adapter = build_research_vision_adapter(enabled=True, describer=explode)

    with pytest.raises(Exception) as exc:
        adapter.observe(image=_probe_image(local_path="x.png"), prompt="p")

    assert REASON_DESCRIPTION_FAILED in str(exc.value)


def test_adapter_rejects_an_empty_description() -> None:
    adapter = build_research_vision_adapter(enabled=True, describer=lambda path: "   ")

    with pytest.raises(Exception) as exc:
        adapter.observe(image=_probe_image(local_path="x.png"), prompt="p")

    assert REASON_EMPTY_DESCRIPTION in str(exc.value)


# --------------------------------------------------------- end-to-end wiring

def test_no_metadata_means_no_work(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv(MAX_VISION_CALLS_ENV, "2")
    fetches: list[str] = []

    result = read_visual_evidence(
        read_payload={"content": "plain text"},
        required_units=("fig4",),
        state=_state(),
        fetcher=_fake_fetcher(fetches),
        destination_dir=tmp_path,
        adapter=build_research_vision_adapter(enabled=True, describer=_describer([])),
    )

    assert result.outcomes == ()
    assert fetches == []


def test_default_inert_performs_no_fetch_and_no_vision(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv(MAX_VISION_CALLS_ENV, raising=False)
    fetches: list[str] = []
    described: list[str] = []

    result = read_visual_evidence(
        read_payload={VISUAL_METADATA_KEY: [_METADATA]},
        required_units=("fig4",),
        state=_state(),
        fetcher=_fake_fetcher(fetches),
        destination_dir=tmp_path,
        adapter=build_research_vision_adapter(
            enabled=True, describer=_describer(described)
        ),
    )

    assert fetches == []
    assert described == []
    assert result.vision_calls == 0
    assert result.outcomes[0].status == "unavailable"
    assert result.outcomes[0].reason == "vision_budget_exhausted"


def test_gate_off_is_fail_closed_even_with_budget(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv(MAX_VISION_CALLS_ENV, "2")
    fetches: list[str] = []

    result = read_visual_evidence(
        read_payload={VISUAL_METADATA_KEY: [_METADATA]},
        required_units=("fig4",),
        state=_state(),
        fetcher=_fake_fetcher(fetches),
        destination_dir=tmp_path,
        adapter=build_research_vision_adapter(enabled=False),
    )

    assert result.vision_calls == 0
    assert result.units == ()
    assert result.outcomes[0].status == "unavailable"


def test_operator_e2e_produces_units_budget_and_audit(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv(MAX_VISION_CALLS_ENV, "1")
    fetches: list[str] = []
    described: list[str] = []
    context: dict = {}

    result = read_visual_evidence(
        read_payload={VISUAL_METADATA_KEY: [_METADATA]},
        required_units=("fig4",),
        state=_state(),
        context=context,
        fetcher=_fake_fetcher(fetches),
        destination_dir=tmp_path,
        adapter=build_research_vision_adapter(
            enabled=True, describer=_describer(described)
        ),
    )

    assert fetches == ["https://docs.example/report.pdf"]
    assert len(described) == 1
    assert result.vision_calls == 1
    unit = result.units[0]
    assert unit.unit_id == "fig4"
    assert unit.source_type == "chart"
    assert unit.page == 4
    assert unit.provenance == "https://docs.example/report.pdf#page=4#region=bbox:10,10,200,120"
    assert "unsupported on Windows" in unit.observation

    audit = context[VISUAL_AUDIT_KEY]
    assert len(audit) == 1
    assert audit[0]["purpose"] == "image_description"
    assert audit[0]["status"] == "normalized"
    assert audit[0]["evidence_id"] == "fig4"
    assert audit[0]["data_categories"] == ["image_content"]


def test_fetch_failure_is_reported_and_vision_is_not_called(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv(MAX_VISION_CALLS_ENV, "2")
    described: list[str] = []

    result = read_visual_evidence(
        read_payload={VISUAL_METADATA_KEY: [_METADATA]},
        required_units=("fig4",),
        state=_state(),
        fetcher=lambda url: (b"", "image/png"),
        destination_dir=tmp_path,
        adapter=build_research_vision_adapter(
            enabled=True, describer=_describer(described)
        ),
    )

    assert described == []
    assert result.vision_calls == 0
    assert result.outcomes[0].status == "unavailable"
    assert result.outcomes[0].reason == "image_body_empty"


def test_lower_level_units_skip_fetch_entirely(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv(MAX_VISION_CALLS_ENV, "2")
    fetches: list[str] = []

    result = read_visual_evidence(
        read_payload={
            VISUAL_METADATA_KEY: [
                {**_METADATA, "ocr_text": "feature X unsupported"}
            ]
        },
        required_units=("fig4",),
        available_units_by_level={"ocr": ("fig4",)},
        state=_state(),
        fetcher=_fake_fetcher(fetches),
        destination_dir=tmp_path,
        adapter=build_research_vision_adapter(enabled=True, describer=_describer([])),
    )

    assert fetches == []
    assert result.vision_calls == 0
    assert result.outcomes[0].stop_at == "ocr"
    assert result.units[0].content == "feature X unsupported"


def test_produced_units_satisfy_the_visual_requirement_in_rq_a(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv(MAX_VISION_CALLS_ENV, "1")

    result = read_visual_evidence(
        read_payload={VISUAL_METADATA_KEY: [_METADATA]},
        required_units=("fig4",),
        state=_state(),
        fetcher=_fake_fetcher([]),
        destination_dir=tmp_path,
        adapter=build_research_vision_adapter(
            enabled=True, describer=_describer([])
        ),
    )
    unit = result.units[0]

    state = build_research_state(
        mode="shadow",
        questions=[ResearchQuestion("q1", "Is feature X supported?", "critical")],
        claims=[
            ResearchClaim(
                "c1",
                "q1",
                "Feature X is unsupported.",
                "factual",
                "critical",
                "searching",
                EvidenceRequirement(
                    source_roles=("primary",),
                    min_independent_sources=1,
                    requires_successful_read=True,
                    required_units=(RequiredUnit("fig4", "figure 4 conclusion", "visual"),),
                ),
            )
        ],
        evidence=(
            ResearchEvidence(
                "ev1", lifecycle_status="read", extraction_status="eligible", units=(unit,)
            ),
        ),
        evidence_links=(
            ResearchClaimEvidenceLink(
                ClaimEvidenceLinkV1("c1", "ev1", "supports", 0.9),
                source_role="primary",
                source_cluster_id="k1",
            ),
        ),
        source_clusters=(EvidenceCluster("k1", ("ev1",)),),
        gaps=(),
        conflict_gaps=(),
        budget=ResearchBudget(20, 8, 45, 60, 16000),
        known_evidence_ids=("ev1",),
    )

    assessment = assess_claim_evidence(state, state.claims[0])

    assert assessment.semantic_adequacy == "adequate"
    assert assessment.state == "satisfied"
