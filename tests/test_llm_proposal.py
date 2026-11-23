"""§45 Tier-2 LLM proposal: trigger, verification and provenance contracts."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, replace

import pytest

from src.application.active_research_runtime import TIER2_PROPOSED_CLAIMS_KEY, _tier2_proposal_step
from src.application.research_runtime_live_values import ActiveRuntimeLiveValues
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
    # Tier-1 has not been consumed yet: stay silent.
    assert (
        tier1_miss_reason(
            assessments={"c1": _Assessment("topic_only")},
            candidate_ids=["c1"],
            completed_read_count=0,
        )
        == ""
    )
    assessments = {"c1": _Assessment("topic_only")}
    assert (
        tier1_miss_reason(
            assessments=assessments,
            candidate_ids=["c1"],
            completed_read_count=1,
        )
        == "no_answer_relevant_candidate"
    )
    assessments = {"c1": _Assessment("answer_relevant")}
    assert (
        tier1_miss_reason(
            assessments=assessments,
            candidate_ids=["c1"],
            completed_read_count=1,
        )
        == ""
    )
    # A claim that already holds support never proposes.
    assert (
        tier1_miss_reason(
            assessments={"c1": _Assessment("topic_only")},
            candidate_ids=["c1"],
            completed_read_count=2,
            claim_has_support=True,
        )
        == ""
    )


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
        RuntimeReadOutcome,
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


def _verified_read(url: str, *, max_chars: int) -> dict:
    return {"ok": True, "content": "x"}


def _proposal_case(*, wave_index: int = 1):
    state, claim = _runtime_state_and_claim()
    return ActiveRuntimeLiveValues(
        state=state, cursor=replace(_runtime_cursor(), wave_index=wave_index)
    ), claim


def _propose(live, claim, gateway, assessments, *, read_fn=_verified_read):
    return _tier2_proposal_step(
        live=live,
        claim=claim,
        assessments=assessments,
        model_gateway=gateway,
        read_fn=read_fn,
        run_id="run_1",
        remaining_timeout=lambda: 5.0,
        proposed_claim_ids=live.context.setdefault(TIER2_PROPOSED_CLAIMS_KEY, []),
    )


@pytest.mark.parametrize("blocked_by", ["tier1_hit", "foreign_read", "already_proposed", "off"])
def test_proposal_admission_skips_without_model_or_read(
    monkeypatch: pytest.MonkeyPatch, blocked_by: str
) -> None:
    from src.web.research.runtime import RuntimeReadOutcome

    monkeypatch.setenv(LLM_PROPOSAL_ENV, "off" if blocked_by == "off" else "on")
    live, claim = _proposal_case(wave_index=2)
    gateway = _Gateway(["https://docs.docker.com/docker-hub/usage/pulls/"])
    assessments = {"candidate_search_1": _Assessment(
        "answer_relevant" if blocked_by == "tier1_hit" else "topic_only"
    )}
    if blocked_by == "foreign_read":
        live.cursor = replace(live.cursor, read_outcomes=(
            RuntimeReadOutcome(candidate_id="candidate_other_claim", status="success"),
        ))
    if blocked_by == "already_proposed":
        live.context[TIER2_PROPOSED_CLAIMS_KEY] = [claim.id]

    def unexpected_read(*args, **kwargs):
        pytest.fail("proposal admission must short-circuit before reads")

    cursor = _propose(live, claim, gateway, assessments, read_fn=unexpected_read)
    assert cursor is live.cursor
    assert gateway.calls == 0
    assert "claim_engine_metrics" not in live.context
    assert live.context[TIER2_PROPOSED_CLAIMS_KEY] == (
        [claim.id] if blocked_by == "already_proposed" else []
    )


def test_tier1_miss_proposes_verifies_and_adds_with_provenance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(LLM_PROPOSAL_ENV, "on")
    live, claim = _proposal_case()
    target = "https://docs.docker.com/docker-hub/usage/pulls/"
    gateway = _Gateway([target, "https://docs.docker.com/broken/"])
    assessments = {"candidate_search_1": _Assessment("topic_only")}
    reads: list[str] = []

    def read_fn(url: str, *, max_chars: int) -> dict:
        reads.append(url)
        assert max_chars == 1200
        if "broken" in url:
            return {"ok": False, "error": "http_404"}
        return {"ok": True, "content": "pull limits", "title": "Pull usage and limits"}

    cursor = _propose(live, claim, gateway, assessments, read_fn=read_fn)
    assert gateway.calls == 1
    assert reads == [target, "https://docs.docker.com/broken/"]
    added = [item for item in cursor.candidates if item.discovery_method == DISCOVERY_METHOD_LLM_PROPOSED]
    assert len(added) == 1
    assert added[0].url == target
    assert added[0].query_ids == ("q1",)
    metrics = live.context["claim_engine_metrics"]
    record = metrics["tier2_proposal"][-1]
    assert record["tier1_miss_reason"] == "no_answer_relevant_candidate"
    assert record["verified"] == [target]
    assert len(record["dropped"]) == 1
    assert record["dropped"][0]["url"] == "https://docs.docker.com/broken/"
    assert record["dropped"][0]["reason"] == "read_failed"
    assert metrics["orchestration_model_calls"] == 1


def test_tier2_records_model_and_verification_at_each_context_rebind(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(LLM_PROPOSAL_ENV, "on")
    live, claim = _proposal_case(wave_index=2)
    original = live.context
    after_model: dict = {}
    target = "https://docs.docker.com/docker-hub/usage/pulls/"

    class _RebindingGateway(_Gateway):
        def complete_structured(self, **kwargs):
            assert live.context[TIER2_PROPOSED_CLAIMS_KEY] == [claim.id]
            assert kwargs["logical_call_id"] == f"research_url_proposal:run_1:{claim.id}:2"
            assert kwargs["timeout_seconds"] == 5.0
            after_model.update(deepcopy(live.context))
            live.context = after_model
            return super().complete_structured(**kwargs)

    def read_fn(url: str, *, max_chars: int) -> dict:
        assert live.context is after_model
        assert after_model["claim_engine_metrics"]["orchestration_model_calls"] == 1
        live.context = deepcopy(after_model)
        return _verified_read(url, max_chars=max_chars)

    gateway = _RebindingGateway([target])
    assessments = {"candidate_search_1": _Assessment("topic_only")}
    _propose(live, claim, gateway, assessments, read_fn=read_fn)

    assert "claim_engine_metrics" not in original
    assert "tier2_proposal" not in after_model["claim_engine_metrics"]
    assert live.context["claim_engine_metrics"]["tier2_proposal"][0]["verified"] == [target]
    assert live.context[TIER2_PROPOSED_CLAIMS_KEY] == [claim.id]
    _propose(live, claim, gateway, assessments, read_fn=read_fn)
    assert gateway.calls == 1
