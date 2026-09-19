"""§63 tier-1.5 domain-targeted retrieval: parsing, patterns, extraction, step."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from src.web.research.domain_targeted import (
    DISCOVERY_METHOD_DOMAIN_TARGETED,
    DOMAIN_TARGETED_ENV,
    build_search_query,
    claim_search_terms,
    domain_targeted_enabled,
    extract_candidate_links,
    parse_domain_proposal,
    site_search_urls,
)

SEARCH_HTML = """
<html><body>
<a href="https://docs.docker.com/docker-hub/usage/pulls/">Pull usage and limits</a>
<a href="/docker-hub/usage/">Usage</a>
<a href="https://docs.docker.com/manuals/">Manuals</a>
<a href="https://other.example/pull-limits">External</a>
<a href="#fragment">Frag</a>
<a href="mailto:x@y.z">Mail</a>
<a href="/docker-hub/usage/pulls/">Duplicate</a>
</body></html>
"""


def test_flag_defaults_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(DOMAIN_TARGETED_ENV, raising=False)
    assert domain_targeted_enabled() is False
    monkeypatch.setenv(DOMAIN_TARGETED_ENV, "on")
    assert domain_targeted_enabled() is True


def test_domain_parser_is_strict_and_bounded() -> None:
    assert parse_domain_proposal(
        {"domains": ["https://docs.docker.com/docker-hub/", "docs.docker.com", "bad", "example.org"]}
    ) == ["docs.docker.com", "example.org"]
    with pytest.raises(ValueError):
        parse_domain_proposal({"domains": "nope"})
    with pytest.raises(ValueError):
        parse_domain_proposal(["not-an-object"])


def test_search_query_uses_significant_terms() -> None:
    terms = claim_search_terms(
        "What pull-rate limits apply to unauthenticated Docker Hub users?"
    )
    assert "pull-rate" in terms
    assert "the" not in terms
    assert build_search_query("What pull-rate limits apply?") == "pull-rate limits apply"


def test_site_search_urls_are_deterministic_patterns() -> None:
    urls = site_search_urls("docs.docker.com", "pull rate limits")
    assert urls[0] == "https://docs.docker.com/search/?q=pull+rate+limits"
    assert len(urls) == 3
    assert site_search_urls("bad", "q") == []


def test_anchor_extraction_filters_scores_and_bounds() -> None:
    links = extract_candidate_links(
        SEARCH_HTML,
        domain="docs.docker.com",
        terms=["pull", "limits", "usage"],
        page_url="https://docs.docker.com/search/?q=x",
    )
    assert links[0] == "https://docs.docker.com/docker-hub/usage/pulls"
    assert "https://other.example/pull-limits" not in links
    assert all("mailto" not in url for url in links)
    assert len(links) == len(set(links))
    assert len(links) <= 5


# ---------------------------------------------------------------------------
# Runtime step with injected collaborators.
# ---------------------------------------------------------------------------


def _quote_response_terms() -> list[str]:
    return ["pull", "limits", "usage"]


def _runtime_state_and_claim():
    from src.web.research.contracts import (
        EvidenceGap,
        EvidenceRequirement,
        ResearchBudget,
        ResearchClaim,
        ResearchQuestion,
    )
    from src.web.research.state import build_research_state

    question = ResearchQuestion(id="q1", question_surface="q")
    claim = ResearchClaim(
        id="claim_1",
        question_id="q1",
        text="Docker Hub pull-rate limits for unauthenticated users",
        kind="factual",
        priority="critical",
        state="pending",
        evidence_requirement=EvidenceRequirement(),
    )
    gap = EvidenceGap(id="gap_1", claim_id="claim_1", gap_type="missing_fact")
    state = build_research_state(
        mode="active",
        questions=(question,),
        claims=(claim,),
        evidence=(),
        evidence_links=(),
        source_clusters=(),
        gaps=(gap,),
        conflict_gaps=(),
        budget=ResearchBudget(
            max_candidates=20,
            max_reads=8,
            soft_timeout_seconds=45,
            hard_timeout_seconds=60,
            max_total_chars=16000,
        ),
        reference_date="2026-09-21",
        known_evidence_ids=(),
    )
    return state, claim


def _runtime_cursor():
    from src.web.research.runtime import (
        ResearchRuntimeCursor,
        RuntimeCandidate,
        RuntimePlannedQuery,
        RuntimeReadOutcome,
    )

    return ResearchRuntimeCursor(
        candidates=(
            RuntimeCandidate(
                id="candidate_search_1",
                url="https://www.docker.com/",
                title="Docker",
                query_ids=("q1",),
                first_seen_rank=0,
            ),
        ),
        read_outcomes=(
            RuntimeReadOutcome(candidate_id="candidate_search_1", status="success"),
        ),
        planned_queries=(
            RuntimePlannedQuery(
                id="q1",
                gap_id="gap_1",
                claim_id="claim_1",
                intent="fact",
                query="docker pull limits",
            ),
        ),
    )


@dataclass
class _Diagnostics:
    relevance: str = "topic_only"


class _Gateway:
    def __init__(self, domains: list[str]) -> None:
        self.domains = domains
        self.calls = 0

    def complete_structured(self, **kwargs):
        from src.web.research.model_gateway import ResearchModelResult

        self.calls += 1
        return ResearchModelResult(status="completed", value=list(self.domains), audits=())


def test_step_adds_verified_domain_targeted_candidate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.application.active_research_runtime import _domain_targeted_step

    monkeypatch.setenv(DOMAIN_TARGETED_ENV, "on")
    state, claim = _runtime_state_and_claim()
    gateway = _Gateway(["docs.docker.com"])
    target = "https://docs.docker.com/docker-hub/usage/pulls"

    def fetch_html(url: str):
        if "search" in url or "?s=" in url:
            return SEARCH_HTML, url, "text/html", ""
        return "", "", "", "unexpected"

    reads: list[str] = []

    def read_fn(url: str, *, max_chars: int):
        reads.append(url)
        if url == target:
            return {"ok": True, "content": "pull limits", "title": "Pull usage and limits"}
        return {"ok": False, "error": "unsafe_or_empty_url"}

    context: dict = {}
    cursor = _domain_targeted_step(
        cursor=_runtime_cursor(),
        state=state,
        claim=claim,
        assessments={"candidate_search_1": _Diagnostics("topic_only")},
        model_gateway=gateway,
        fetch_html=fetch_html,
        read_fn=read_fn,
        context=context,
        run_id="run_1",
        wave_index=1,
        timeout_seconds=5.0,
        targeted_claim_ids=[],
    )
    assert gateway.calls == 1
    added = [
        item
        for item in cursor.candidates
        if item.discovery_method == DISCOVERY_METHOD_DOMAIN_TARGETED
    ]
    assert [item.url for item in added] == [target]
    record = context["claim_engine_metrics"]["domain_targeted"][-1]
    assert record["domains"] == ["docs.docker.com"]
    assert record["verified"] == [target]
    assert any(row["reason"] == "read_failed" for row in record["dropped"])
    assert context["claim_engine_metrics"]["orchestration_model_calls"] == 1


def _state_with_support(claim_id: str):
    from src.domain.evidence import ClaimEvidenceLinkV1
    from src.web.research.contracts import (
        EvidenceCluster,
        EvidenceGap,
        EvidenceRequirement,
        ResearchBudget,
        ResearchClaim,
        ResearchClaimEvidenceLink,
        ResearchEvidence,
        ResearchQuestion,
    )
    from src.web.research.state import build_research_state

    question = ResearchQuestion(id="q1", question_surface="q")
    claim = ResearchClaim(
        id=claim_id,
        question_id="q1",
        text="Docker Hub pull-rate limits for unauthenticated users",
        kind="factual",
        priority="critical",
        state="pending",
        evidence_requirement=EvidenceRequirement(),
    )
    gap = EvidenceGap(id="gap_1", claim_id=claim_id, gap_type="missing_fact")
    return build_research_state(
        mode="active",
        questions=(question,),
        claims=(claim,),
        evidence=(
            ResearchEvidence(
                evidence_id="ev_x",
                locator="pull limits",
                anchored_spans=("pull limits",),
                lifecycle_status="read",
                extraction_status="eligible",
            ),
        ),
        evidence_links=(
            ResearchClaimEvidenceLink(
                link=ClaimEvidenceLinkV1(
                    claim_id=claim_id,
                    evidence_id="ev_x",
                    support_type="supports",
                    confidence=0.9,
                ),
                source_role="primary",
                source_cluster_id="c1",
            ),
        ),
        source_clusters=(EvidenceCluster(id="c1", evidence_ids=("ev_x",)),),
        gaps=(gap,),
        conflict_gaps=(),
        budget=ResearchBudget(
            max_candidates=20,
            max_reads=8,
            soft_timeout_seconds=45,
            hard_timeout_seconds=60,
            max_total_chars=16000,
        ),
        reference_date="2026-09-21",
        known_evidence_ids=("ev_x",),
    )


def test_step_is_silent_when_support_exists(monkeypatch: pytest.MonkeyPatch) -> None:
    from src.application.active_research_runtime import _domain_targeted_step

    monkeypatch.setenv(DOMAIN_TARGETED_ENV, "on")
    state = _state_with_support("claim_1")
    claim = state.claims[0]
    gateway = _Gateway(["docs.docker.com"])
    cursor = _domain_targeted_step(
        cursor=_runtime_cursor(),
        state=state,
        claim=claim,
        assessments={},
        model_gateway=gateway,
        fetch_html=lambda url: (SEARCH_HTML, url, "text/html", ""),
        read_fn=lambda url, *, max_chars: {"ok": True, "content": "x"},
        context={},
        run_id="run_1",
        wave_index=2,
        timeout_seconds=5.0,
        targeted_claim_ids=[],
    )
    assert gateway.calls == 0
    assert len(cursor.candidates) == 1


def test_step_never_runs_twice_for_the_same_claim(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.application.active_research_runtime import _domain_targeted_step

    monkeypatch.setenv(DOMAIN_TARGETED_ENV, "on")
    state, claim = _runtime_state_and_claim()
    gateway = _Gateway(["docs.docker.com"])
    _domain_targeted_step(
        cursor=_runtime_cursor(),
        state=state,
        claim=claim,
        assessments={},
        model_gateway=gateway,
        fetch_html=lambda url: (SEARCH_HTML, url, "text/html", ""),
        read_fn=lambda url, *, max_chars: {"ok": True, "content": "x"},
        context={},
        run_id="run_1",
        wave_index=1,
        timeout_seconds=5.0,
        targeted_claim_ids=["claim_1"],
    )
    assert gateway.calls == 0
