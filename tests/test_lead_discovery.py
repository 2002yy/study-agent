from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from src.web.research.candidate_pool import CandidatePoolItem
from src.web.research.candidate_ranking import (
    CandidateSemanticAssessment,
    RankedCandidate,
)
from src.web.research.gap_planner import GapSearchIntent
from src.web.research.lead_discovery import (
    LEAD_DISCOVERY_SCHEMA_VERSION,
    RuntimeLeadDiscoverer,
    parse_lead_discovery_response,
)
from src.web.research.scheduler import is_schedulable_lead


def _payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema_version": LEAD_DISCOVERY_SCHEMA_VERSION,
        "candidate_id": "cand-1",
        "discovered_urls": ["https://www.bankofengland.co.uk/monetary-policy/bank-rate"],
        "domains": ["bankofengland.co.uk"],
        "organizations": ["Bank of England"],
        "primary_source_hints": ["Bank of England Bank Rate official"],
        "warnings": [],
    }
    payload.update(overrides)
    return payload


def _candidate() -> CandidatePoolItem:
    return CandidatePoolItem(
        id="cand-1",
        canonical_url="https://news.example/report",
        url="https://news.example/report",
        title="Report",
        snippet="snippet",
        source="Publisher",
        published_at="2026-08-20",
        query_ids=("q",),
        intents=(GapSearchIntent.PRIMARY,),
        providers=("bing_rss",),
        first_seen_rank=1,
    )


def _ranked(*, eligibility: str, intents: tuple[str, ...]) -> RankedCandidate:
    candidate = CandidatePoolItem(
        id="cand-1",
        canonical_url="https://news.example/report",
        url="https://news.example/report",
        title="Report",
        snippet="snippet",
        source="Publisher",
        published_at="2026-08-20",
        query_ids=("q",),
        intents=intents,
        providers=("bing_rss",),
        first_seen_rank=1,
    )
    assessment = CandidateSemanticAssessment(
        candidate_id="cand-1",
        relevance="topic_only",
        relevance_confidence=0.6,
        source_role="aggregator",
        source_role_confidence=0.8,
        cluster_id="cluster-1",
    )
    return RankedCandidate(
        candidate=candidate,
        assessment=assessment,
        rank=1,
        eligibility=eligibility,  # type: ignore[arg-type]
        reason_codes=(),
        new_cluster=True,
        expected_information_gain=1,
    )


def test_parser_accepts_bounded_discovery_payload() -> None:
    parsed = parse_lead_discovery_response(_payload(), candidate_id="cand-1")
    assert parsed.source_candidate_id == "cand-1"
    assert parsed.discovered_urls == (
        "https://www.bankofengland.co.uk/monetary-policy/bank-rate",
    )
    assert parsed.domains == ("bankofengland.co.uk",)
    assert parsed.organizations == ("Bank of England",)


def test_parser_rejects_evidence_shaped_fields() -> None:
    with pytest.raises(ValueError):
        parse_lead_discovery_response(
            _payload(claim_support="supports", evidence_strength=0.9),
            candidate_id="cand-1",
        )


def test_parser_rejects_changed_candidate_id() -> None:
    with pytest.raises(ValueError):
        parse_lead_discovery_response(_payload(candidate_id="other"), candidate_id="cand-1")


def test_parser_rejects_non_absolute_or_unsafe_urls() -> None:
    for bad in ("javascript:alert(1)", "/relative/path", "ftp://example.com/x"):
        with pytest.raises(ValueError):
            parse_lead_discovery_response(
                _payload(discovered_urls=[bad]), candidate_id="cand-1"
            )


def test_parser_rejects_oversized_lists() -> None:
    with pytest.raises(ValueError):
        parse_lead_discovery_response(
            _payload(discovered_urls=[f"https://example.com/{i}" for i in range(6)]),
            candidate_id="cand-1",
        )


def test_parser_dedupes_and_allows_empty_assets() -> None:
    parsed = parse_lead_discovery_response(
        _payload(
            discovered_urls=["https://example.com/a", "https://example.com/a"],
            domains=["example.com", "EXAMPLE.com"],
            organizations=[],
            primary_source_hints=[],
            warnings=[],
        ),
        candidate_id="cand-1",
    )
    assert parsed.discovered_urls == ("https://example.com/a",)
    assert parsed.domains == ("example.com",)
    assert parsed.organizations == ()


class _FakeGateway:
    provider_profile = "openai"

    def __init__(self, payload: Any, status: str = "completed") -> None:
        self.payload = payload
        self.status = status
        self.calls: list[dict[str, Any]] = []

    def complete_structured(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        value = None
        reason = ""
        if self.status == "completed":
            value = kwargs["parse"](self.payload)
        else:
            reason = "model_call_failed"
        return SimpleNamespace(status=self.status, value=value, audits=(), reason=reason)


def test_discoverer_returns_typed_discovery_and_uses_lead_purpose() -> None:
    gateway = _FakeGateway(_payload())
    result = RuntimeLeadDiscoverer(gateway).discover(
        run_id="run-1",
        candidate=_candidate(),
        content="Bank of England publishes the Bank Rate at ...",
    )
    assert result.status == "completed"
    assert result.discovery is not None
    assert result.discovery.domains == ("bankofengland.co.uk",)
    assert gateway.calls[0]["purpose"] == "research_lead_discovery"
    assert gateway.calls[0]["max_tokens"] == 700


def test_discoverer_fails_closed_on_empty_content_without_model_call() -> None:
    gateway = _FakeGateway(_payload())
    result = RuntimeLeadDiscoverer(gateway).discover(
        run_id="run-1",
        candidate=_candidate(),
        content="   ",
    )
    assert result.status == "unavailable"
    assert result.reason == "empty_read_content"
    assert gateway.calls == []


def test_discoverer_reports_unavailable_on_model_failure() -> None:
    gateway = _FakeGateway(_payload(), status="unavailable")
    result = RuntimeLeadDiscoverer(gateway).discover(
        run_id="run-1",
        candidate=_candidate(),
        content="page text",
    )
    assert result.status == "unavailable"
    assert result.discovery is None


def test_lead_scheduling_is_deterministic_and_budget_bounded() -> None:
    lead = _ranked(eligibility="lead_only", intents=(GapSearchIntent.PRIMARY,))
    assert is_schedulable_lead(lead, lead_budget_available=True, gap_needs_primary=True)
    assert not is_schedulable_lead(
        lead, lead_budget_available=False, gap_needs_primary=True
    )
    assert not is_schedulable_lead(
        lead, lead_budget_available=True, gap_needs_primary=False
    )


def test_rejected_and_eligible_candidates_are_never_lead_scheduled() -> None:
    rejected = _ranked(eligibility="rejected", intents=(GapSearchIntent.PRIMARY,))
    eligible = _ranked(eligibility="eligible", intents=(GapSearchIntent.PRIMARY,))
    assert not is_schedulable_lead(
        rejected, lead_budget_available=True, gap_needs_primary=True
    )
    assert not is_schedulable_lead(
        eligible, lead_budget_available=True, gap_needs_primary=True
    )


def test_lead_scheduling_requires_primary_provenance_or_verification_intent() -> None:
    discovery_only = _ranked(
        eligibility="lead_only", intents=(GapSearchIntent.DISCOVERY,)
    )
    assert not is_schedulable_lead(
        discovery_only, lead_budget_available=True, gap_needs_primary=True
    )
