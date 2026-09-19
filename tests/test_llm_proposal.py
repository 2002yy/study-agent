"""§45 Tier-2 LLM proposal: trigger, verification and provenance contracts."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from src.web.research.llm_proposal import (
    DISCOVERY_METHOD_LLM_PROPOSED,
    LLM_PROPOSAL_ENV,
    MAX_PROPOSALS,
    build_proposal_payload,
    llm_proposal_enabled,
    parse_proposal_response,
    proposal_messages,
    tier1_miss_reason,
)


@dataclass
class _Assessment:
    relevance: str = "topic_only"


def test_flag_defaults_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(LLM_PROPOSAL_ENV, raising=False)
    assert llm_proposal_enabled() is False
    monkeypatch.setenv(LLM_PROPOSAL_ENV, "on")
    assert llm_proposal_enabled() is True


def test_parser_is_strict_and_https_only() -> None:
    payload = {
        "urls": [
            "https://docs.docker.com/docker-hub/usage/pulls/",
            "http://insecure.example/",
            "not-a-url",
            "https://docs.docker.com/docker-hub/usage/pulls/",
            "https://a.example/",
            "https://b.example/",
        ]
    }
    urls = parse_proposal_response(payload)
    assert urls[0] == "https://docs.docker.com/docker-hub/usage/pulls/"
    assert len(urls) == MAX_PROPOSALS
    assert all(url.startswith("https://") for url in urls)
    with pytest.raises(ValueError):
        parse_proposal_response({"urls": "nope"})
    with pytest.raises(ValueError):
        parse_proposal_response(["not-an-object"])


def test_miss_reason_requires_candidates_and_no_relevant_one() -> None:
    assert (
        tier1_miss_reason(assessments={}, candidate_ids=[])
        == "no_candidates"
    )
    assessments = {"c1": _Assessment("topic_only")}
    assert (
        tier1_miss_reason(assessments=assessments, candidate_ids=["c1"])
        == "no_answer_relevant_candidate"
    )
    assessments = {"c1": _Assessment("answer_relevant")}
    assert tier1_miss_reason(assessments=assessments, candidate_ids=["c1"]) == ""


def test_messages_carry_the_claim_only() -> None:
    messages = proposal_messages("Docker pull limits")
    assert messages[0]["role"] == "system"
    assert "https" in messages[0]["content"]
    assert build_proposal_payload("x") == {"claim": "x"}


# ---------------------------------------------------------------------------
# Runtime step: Tier-1 hit must not trigger; miss proposes + verifies.
# ---------------------------------------------------------------------------


def _runtime_cursor():
    from src.web.research.runtime import (
        ResearchRuntimeCursor,
        RuntimeCandidate,
        RuntimePlannedQuery,
    )

    candidates = (
        RuntimeCandidate(
            id="candidate_search_1",
            url="https://www.docker.com/",
            title="Docker",
            query_ids=("q1",),
            first_seen_rank=0,
        ),
    )
    return ResearchRuntimeCursor(
        candidates=candidates,
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
        text="Docker Hub pull-rate limits",
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
        reference_date="2026-09-19",
        known_evidence_ids=(),
    )
    return state, claim


class _Gateway:
    def __init__(self, urls: list[str]) -> None:
        self.urls = urls
        self.calls = 0

    def complete_structured(self, **kwargs):
        self.calls += 1
        from src.web.research.model_gateway import ResearchModelResult

        return ResearchModelResult(
            status="completed", value=list(self.urls), audits=()
        )


def test_tier1_hit_never_calls_the_model(monkeypatch: pytest.MonkeyPatch) -> None:
    from src.application.active_research_runtime import _tier2_proposal_step

    monkeypatch.setenv(LLM_PROPOSAL_ENV, "on")
    state, claim = _runtime_state_and_claim()
    gateway = _Gateway(["https://docs.docker.com/docker-hub/usage/pulls/"])
    assessments = {"candidate_search_1": _Assessment("answer_relevant")}
    cursor = _tier2_proposal_step(
        cursor=_runtime_cursor(),
        state=state,
        claim=claim,
        assessments=assessments,
        model_gateway=gateway,
        read_fn=lambda url, *, max_chars: {"ok": True, "content": "x"},
        context={},
        run_id="run_1",
        wave_index=1,
        timeout_seconds=5.0,
        proposed_claim_ids=[],
    )
    assert gateway.calls == 0
    assert len(cursor.candidates) == 1


def test_tier1_miss_proposes_verifies_and_adds_with_provenance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.application.active_research_runtime import _tier2_proposal_step

    monkeypatch.setenv(LLM_PROPOSAL_ENV, "on")
    state, claim = _runtime_state_and_claim()
    target = "https://docs.docker.com/docker-hub/usage/pulls/"
    gateway = _Gateway([target, "https://docs.docker.com/broken/"])
    assessments = {"candidate_search_1": _Assessment("topic_only")}
    reads: list[str] = []

    def read_fn(url: str, *, max_chars: int) -> dict:
        reads.append(url)
        if "broken" in url:
            return {"ok": False, "error": "http_404"}
        return {"ok": True, "content": "pull limits", "title": "Pull usage and limits"}

    context: dict = {}
    cursor = _tier2_proposal_step(
        cursor=_runtime_cursor(),
        state=state,
        claim=claim,
        assessments=assessments,
        model_gateway=gateway,
        read_fn=read_fn,
        context=context,
        run_id="run_1",
        wave_index=1,
        timeout_seconds=5.0,
        proposed_claim_ids=[],
    )
    assert gateway.calls == 1
    assert reads == [target, "https://docs.docker.com/broken/"]
    added = [item for item in cursor.candidates if item.discovery_method == DISCOVERY_METHOD_LLM_PROPOSED]
    assert len(added) == 1
    assert added[0].url == target
    assert added[0].query_ids == ("q1",)
    record = context["claim_engine_metrics"]["tier2_proposal"][-1]
    assert record["tier1_miss_reason"] == "no_answer_relevant_candidate"
    assert record["verified"] == [target]
    assert len(record["dropped"]) == 1
    assert record["dropped"][0]["url"] == "https://docs.docker.com/broken/"
    assert record["dropped"][0]["reason"] == "read_failed"
    assert context["claim_engine_metrics"]["orchestration_model_calls"] == 1


def test_missing_api_never_repeats_for_the_same_claim(monkeypatch: pytest.MonkeyPatch) -> None:
    from src.application.active_research_runtime import _tier2_proposal_step

    monkeypatch.setenv(LLM_PROPOSAL_ENV, "on")
    state, claim = _runtime_state_and_claim()
    gateway = _Gateway(["https://docs.docker.com/docker-hub/usage/pulls/"])
    proposed: list[str] = ["claim_1"]
    _tier2_proposal_step(
        cursor=_runtime_cursor(),
        state=state,
        claim=claim,
        assessments={},
        model_gateway=gateway,
        read_fn=lambda url, *, max_chars: {"ok": True, "content": "x"},
        context={},
        run_id="run_1",
        wave_index=2,
        timeout_seconds=5.0,
        proposed_claim_ids=proposed,
    )
    assert gateway.calls == 0


def test_flag_off_never_calls_the_model(monkeypatch: pytest.MonkeyPatch) -> None:
    from src.application.active_research_runtime import _tier2_proposal_step

    monkeypatch.delenv(LLM_PROPOSAL_ENV, raising=False)
    state, claim = _runtime_state_and_claim()
    gateway = _Gateway(["https://docs.docker.com/docker-hub/usage/pulls/"])
    _tier2_proposal_step(
        cursor=_runtime_cursor(),
        state=state,
        claim=claim,
        assessments={},
        model_gateway=gateway,
        read_fn=lambda url, *, max_chars: {"ok": True, "content": "x"},
        context={},
        run_id="run_1",
        wave_index=1,
        timeout_seconds=5.0,
        proposed_claim_ids=[],
    )
    assert gateway.calls == 0
