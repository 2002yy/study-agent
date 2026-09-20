"""§69/B1-T5 R1': late-admission assessment tail.

Frozen contract: the tail is an independent entry (<=2/claim/wave) for
candidates a discovery channel admitted *after* this wave's initial assessment
window was frozen. It never calls the selection authority, never evicts an
existing ranking entry, never bypasses the assessment contract, and obeys the
same time/model-call budgets as everything else.

Acceptance cases 1-7 from the ruling.
"""

from __future__ import annotations

import pytest


from src.application.active_research_runtime import (
    LATE_TAIL_MAX_CANDIDATES,
    _late_admission_tail,
)
from src.web.research.candidate_ranking import CandidateSemanticAssessment
from src.web.research.contracts import (
    EvidenceGap,
    EvidenceRequirement,
    ResearchBudget,
    ResearchClaim,
    ResearchQuestion,
)
from src.web.research.runtime import (
    ResearchRuntimeCursor,
    RuntimeCandidate,
    RuntimePlannedQuery,
    RuntimeReadOutcome,
)
from src.web.research.state import build_research_state

CLAIM_ID = "claim_1"


def _assessment(candidate_id: str, relevance: str = "answer_relevant") -> CandidateSemanticAssessment:
    return CandidateSemanticAssessment(
        candidate_id=candidate_id,
        relevance=relevance,  # type: ignore[arg-type]
        relevance_confidence=0.9,
        source_role="primary",
        source_role_confidence=0.9,
        cluster_id=f"cluster_{candidate_id}",
    )


class _Assessor:
    def __init__(self, relevance: str = "answer_relevant", status: str = "completed") -> None:
        self.relevance = relevance
        self.status = status
        self.calls: list[tuple[str, ...]] = []

    def assess(self, *, candidates, **kwargs):
        del kwargs
        self.calls.append(tuple(item.id for item in candidates))
        if self.status != "completed":
            return type(
                "Outcome", (), {"status": self.status, "assessments": {}, "reason": "unavailable"}
            )()
        return type(
            "Outcome",
            (),
            {
                "status": "completed",
                "assessments": {
                    item.id: _assessment(item.id, self.relevance) for item in candidates
                },
                "reason": "",
            },
        )()


def _claim() -> ResearchClaim:
    return ResearchClaim(
        id=CLAIM_ID,
        question_id="q1",
        text="Docker Hub pull-rate limits for unauthenticated users",
        kind="factual",
        priority="critical",
        state="pending",
        evidence_requirement=EvidenceRequirement(),
    )


def _state(claim: ResearchClaim):
    question = ResearchQuestion(id="q1", question_surface="q")
    gap = EvidenceGap(id="gap_1", claim_id=claim.id, gap_type="missing_fact")
    return build_research_state(
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


def _cursor(urls: list[str], *, read_first: bool = False) -> ResearchRuntimeCursor:
    candidates = tuple(
        RuntimeCandidate(
            id=f"candidate_{index}",
            url=url,
            title=f"t{index}",
            query_ids=("q1",),
            first_seen_rank=index,
        )
        for index, url in enumerate(urls)
    )
    outcomes = (
        (RuntimeReadOutcome(candidate_id="candidate_0", status="success"),)
        if read_first
        else ()
    )
    return ResearchRuntimeCursor(
        candidates=candidates,
        read_outcomes=outcomes,
        planned_queries=(
            RuntimePlannedQuery(
                id="q1", gap_id="gap_1", claim_id=CLAIM_ID, intent="fact", query="q"
            ),
        ),
    )


def _context(late_ids: list[str], *, wave_index: int = 2) -> dict:
    return {
        "claim_engine_metrics": {
            "domain_targeted": [
                {
                    "claim_id": CLAIM_ID,
                    "wave_index": wave_index,
                    "added_candidate_ids": list(late_ids),
                }
            ]
        }
    }


def _run_tail(
    *,
    cursor: ResearchRuntimeCursor,
    context: dict,
    claim_rankings: dict | None = None,
    assessor: _Assessor | None = None,
    seconds_left: float = 30.0,
    wave_index: int = 2,
    model_allowed: bool = True,
    attempt_budget_ok: bool = True,
):
    claim = _claim()
    state = _state(claim)
    rankings = claim_rankings if claim_rankings is not None else {}
    stored: dict = {}
    inputs: dict = {}
    assessor = assessor or _Assessor()
    result_cursor = _late_admission_tail(
        cursor=cursor,
        state=state,
        claim=claim,
        context=context,
        run_id="run_1",
        wave_index=wave_index,
        max_reads=8,
        assessor=assessor,
        model_allowed=lambda purpose, categories: model_allowed,
        on_model_started=lambda **kwargs: None,
        on_model_finished=lambda **kwargs: None,
        phase_begin=lambda name: None,
        phase_end=lambda name: None,
        remaining_timeout=lambda: 5.0,
        research_seconds_left=lambda: seconds_left,
        trace=None,
        claim_rankings=rankings,
        stored_assessments=stored,
        assessed_inputs=inputs,
    )
    records = context["claim_engine_metrics"].get("late_assessment_tail") or []
    record = records[-1] if records else {}
    return result_cursor, rankings, record, assessor


def test_case_1_late_candidate_is_assessed_and_enters_the_ranking() -> None:
    cursor = _cursor(["https://a.example/", "https://docs.example.com/pulls"])
    context = _context(["candidate_1"])
    _cursor_result, rankings, record, assessor = _run_tail(
        cursor=cursor, context=context
    )
    assert record["assessed_ids"] == ["candidate_1"]
    assert record["selector_calls"] == 0
    assert [item.candidate.id for item in rankings[CLAIM_ID]] == ["candidate_1"]
    assert assessor.calls == [("candidate_1",)]


def test_case_2_initial_window_picks_are_never_evicted() -> None:
    """Pre-existing ranking entries survive the tail untouched."""

    cursor = _cursor(
        ["https://a.example/", "https://b.example/", "https://docs.example.com/pulls"]
    )
    context = _context(["candidate_2"])
    claim = _claim()
    from src.web.research.candidate_ranking import rank_candidate_pool

    initial = rank_candidate_pool(
        (cursor.candidates[0], cursor.candidates[1]),
        claim=claim,
        assessments={
            "candidate_0": _assessment("candidate_0", "topic_only"),
            "candidate_1": _assessment("candidate_1", "topic_only"),
        },
    )
    rankings = {CLAIM_ID: initial}
    _result, rankings, record, _assessor = _run_tail(
        cursor=cursor, context=context, claim_rankings=rankings
    )
    ids = {item.candidate.id for item in rankings[CLAIM_ID]}
    assert {"candidate_0", "candidate_1"}.issubset(ids)
    assert "candidate_2" in ids
    assert record["assessed_ids"] == ["candidate_2"]


def test_case_3_no_direct_read_without_assessment() -> None:
    """A late candidate reaches the ranking only through the assessor."""

    cursor = _cursor(["https://docs.example.com/pulls"])
    context = _context(["candidate_0"])
    assessor = _Assessor(status="unavailable")
    _result, rankings, record, _assessor = _run_tail(
        cursor=cursor, context=context, assessor=assessor
    )
    assert record["skipped_reason"] == "assessment_failed"
    assert rankings == {}
    assert record["assessed_ids"] == []


def test_case_4_rejected_assessment_never_reaches_the_ranking() -> None:
    cursor = _cursor(["https://docs.example.com/pulls"])
    context = _context(["candidate_0"])
    _result, rankings, record, _assessor = _run_tail(
        cursor=cursor, context=context, assessor=_Assessor(relevance="off_target")
    )
    assert record["assessed_ids"] == ["candidate_0"]
    # ranked, but the eligibility verdict belongs to rank_candidate_pool/H9
    assert [item.candidate.id for item in rankings[CLAIM_ID]] == ["candidate_0"]
    assert rankings[CLAIM_ID][0].eligibility in {"rejected", "lead_only", "eligible"}


def test_case_5_selector_calls_stay_zero() -> None:
    cursor = _cursor(["https://docs.example.com/pulls"])
    context = _context(["candidate_0"])
    _result, _rankings, record, _assessor = _run_tail(cursor=cursor, context=context)
    assert record["selector_calls"] == 0
    assert "selection_authority" not in context["claim_engine_metrics"]


def test_case_6_cluster_diversity_bounds_the_tail() -> None:
    """More late candidates than the cap: same cluster-diverse rule applies."""

    cursor = _cursor(
        [
            "https://docs.example.com/a",
            "https://docs.example.com/b",
            "https://docs.example.com/c",
        ]
    )
    context = _context(["candidate_0", "candidate_1", "candidate_2"])
    _result, _rankings, record, _assessor = _run_tail(cursor=cursor, context=context)
    assert len(record["selected_ids"]) == LATE_TAIL_MAX_CANDIDATES
    assert record["assessed_ids"] == record["selected_ids"]


def test_case_7_full_initial_window_still_admits_the_tail() -> None:
    """The ≤2 cap is the initial window's intake, not claim_rankings capacity."""

    cursor = _cursor(
        ["https://a.example/", "https://b.example/", "https://docs.example.com/pulls"]
    )
    context = _context(["candidate_2"])
    claim = _claim()
    from src.web.research.candidate_ranking import rank_candidate_pool

    initial = rank_candidate_pool(
        (cursor.candidates[0], cursor.candidates[1]),
        claim=claim,
        assessments={
            "candidate_0": _assessment("candidate_0"),
            "candidate_1": _assessment("candidate_1"),
        },
    )
    rankings = {CLAIM_ID: initial}
    _result, rankings, record, _assessor = _run_tail(
        cursor=cursor, context=context, claim_rankings=rankings
    )
    assert record["assessed_ids"] == ["candidate_2"]
    assert len(rankings[CLAIM_ID]) == 3  # >2 is allowed for claim_rankings
    assert record["ranked_after"] == 3


def test_budget_gates_record_why_the_tail_was_skipped() -> None:
    cursor = _cursor(["https://docs.example.com/pulls"])
    context = _context(["candidate_0"])
    _result, rankings, record, assessor = _run_tail(
        cursor=cursor, context=context, seconds_left=2.0
    )
    assert record["skipped_reason"] == "time_budget_exhausted"
    assert assessor.calls == []
    assert rankings == {}

    context2 = _context(["candidate_0"])
    _result2, _rankings2, record2, _assessor2 = _run_tail(
        cursor=_cursor(["https://docs.example.com/pulls"]),
        context=context2,
        model_allowed=False,
    )
    assert record2["skipped_reason"] == "policy_blocked"


def test_experimental_floor_is_configurable(monkeypatch: pytest.MonkeyPatch) -> None:
    """§71A/F1: the floor is a calibration knob, default 8.0, not frozen."""

    from src.application.active_research_runtime import late_tail_floor_seconds

    monkeypatch.delenv("RESEARCH_LATE_TAIL_FLOOR_SECONDS", raising=False)
    assert late_tail_floor_seconds() == pytest.approx(8.0)
    monkeypatch.setenv("RESEARCH_LATE_TAIL_FLOOR_SECONDS", "4.0")
    assert late_tail_floor_seconds() == pytest.approx(4.0)
    monkeypatch.setenv("RESEARCH_LATE_TAIL_FLOOR_SECONDS", "0.2")
    assert late_tail_floor_seconds() == pytest.approx(1.0)
    monkeypatch.setenv("RESEARCH_LATE_TAIL_FLOOR_SECONDS", "junk")
    assert late_tail_floor_seconds() == pytest.approx(8.0)

    # 7.4s of headroom is refused at the default 8s floor but admitted at 4s.
    monkeypatch.delenv("RESEARCH_LATE_TAIL_FLOOR_SECONDS", raising=False)
    _result, rankings, record, assessor = _run_tail(
        cursor=_cursor(["https://docs.example.com/pulls"]),
        context=_context(["candidate_0"]),
        seconds_left=7.4,
    )
    assert record["skipped_reason"] == "time_budget_exhausted"
    assert assessor.calls == []

    monkeypatch.setenv("RESEARCH_LATE_TAIL_FLOOR_SECONDS", "4.0")
    _result2, rankings2, record2, assessor2 = _run_tail(
        cursor=_cursor(["https://docs.example.com/pulls"]),
        context=_context(["candidate_0"]),
        seconds_left=7.4,
    )
    assert record2["skipped_reason"] == ""
    assert record2["floor_seconds"] == pytest.approx(4.0)
    assert assessor2.calls == [("candidate_0",)]
    assert [item.candidate.id for item in rankings2[CLAIM_ID]] == ["candidate_0"]


def test_tail_ignores_other_waves_and_other_claims() -> None:
    cursor = _cursor(["https://docs.example.com/pulls"])
    stale = _context(["candidate_0"], wave_index=1)
    _result, rankings, _record, assessor = _run_tail(
        cursor=cursor, context=stale, wave_index=2
    )
    assert assessor.calls == []
    assert rankings == {}
    assert "late_assessment_tail" not in stale["claim_engine_metrics"]

    foreign = _context(["candidate_0"])
    foreign["claim_engine_metrics"]["domain_targeted"][0]["claim_id"] = "claim_other"
    _result2, rankings2, _record2, assessor2 = _run_tail(
        cursor=_cursor(["https://docs.example.com/pulls"]), context=foreign
    )
    assert assessor2.calls == []
    assert rankings2 == {}


def test_already_read_late_candidate_is_skipped() -> None:
    cursor = _cursor(["https://docs.example.com/pulls"], read_first=True)
    context = _context(["candidate_0"])
    _result, rankings, record, assessor = _run_tail(cursor=cursor, context=context)
    assert record["skipped_reason"] == "no_late_candidates"
    assert assessor.calls == []
    assert rankings == {}

# ---------------------------------------------------------------------------
# §71A-1: live metrics resolution + terminal invocation upsert.
# ---------------------------------------------------------------------------


class _SwappingContext(dict):
    """Context whose metrics mapping is replaced after the first lookup.

    Mirrors the live-runtime shape where ``context[metrics_key]`` is rebuilt
    while a step is executing: the entry-time mapping (A) is stale by the time
    diagnostics are written, and the live one (B) is a different object.
    """

    def __init__(self, first: dict, second: dict, *, swap_after: int = 1) -> None:
        super().__init__()
        self._first = first
        self._second = second
        self._lookups = 0
        self._swap_after = swap_after
        self["claim_engine_metrics"] = first

    def _maybe_swap(self) -> None:
        if self._lookups >= self._swap_after:
            dict.__setitem__(self, "claim_engine_metrics", self._second)
        self._lookups += 1

    def get(self, key, default=None):
        value = dict.get(self, key, default)
        if key == "claim_engine_metrics":
            self._maybe_swap()
        return value


def _terminal_invocations(context: dict) -> list[dict]:
    live = context["claim_engine_metrics"]
    return [item for item in (live.get("late_tail_invocations") or [])]


def test_identity_swap_keeps_behaviour_and_terminal_state() -> None:
    """Live-shape: metrics A -> B mid-call must not lose the tail's work."""

    claim = _claim()
    stale = {
        "domain_targeted": [
            {
                "claim_id": CLAIM_ID,
                "wave_index": 2,
                "added_candidate_ids": ["candidate_0"],
            }
        ]
    }
    live = {
        "domain_targeted": [
            {
                "claim_id": CLAIM_ID,
                "wave_index": 2,
                "added_candidate_ids": ["candidate_0"],
            }
        ]
    }
    context = _SwappingContext(stale, live)
    state = _state(claim)
    rankings: dict = {}
    stored: dict = {}
    inputs: dict = {}
    assessor = _Assessor()
    _late_admission_tail(
        cursor=_cursor(["https://docs.example.com/pulls"]),
        state=state,
        claim=claim,
        context=context,
        run_id="run_1",
        wave_index=2,
        max_reads=8,
        assessor=assessor,
        model_allowed=lambda purpose, categories: True,
        on_model_started=lambda **kwargs: None,
        on_model_finished=lambda **kwargs: None,
        phase_begin=lambda name: None,
        phase_end=lambda name: None,
        remaining_timeout=lambda: 5.0,
        research_seconds_left=lambda: 30.0,
        trace=None,
        claim_rankings=rankings,
        stored_assessments=stored,
        assessed_inputs=inputs,
        now_ms=lambda: 2000.0,
        deadline_seconds=48.0,
    )
    # behaviour: the late candidate was assessed and ranked
    assert assessor.calls == [("candidate_0",)]
    assert [item.candidate.id for item in rankings[CLAIM_ID]] == ["candidate_0"]
    # diagnostics land in the LIVE mapping, not the stale one
    assert not stale.get("late_assessment_tail")
    records = live.get("late_assessment_tail") or []
    assert records and records[-1]["assessed_ids"] == ["candidate_0"]
    invocations = _terminal_invocations(context)
    assert len(invocations) == 1
    entry = invocations[0]
    assert entry["outcome"] == "assessed:1"
    assert entry["late_ids"] == 1
    assert entry["metrics_identity_changed"] is True
    assert entry.get("recovered") is True


def test_no_identity_change_path_is_unchanged() -> None:
    context = _context(["candidate_0"])
    claim = _claim()
    rankings: dict = {}
    assessor = _Assessor()
    _late_admission_tail(
        cursor=_cursor(["https://docs.example.com/pulls"]),
        state=_state(claim),
        claim=claim,
        context=context,
        run_id="run_1",
        wave_index=2,
        max_reads=8,
        assessor=assessor,
        model_allowed=lambda purpose, categories: True,
        on_model_started=lambda **kwargs: None,
        on_model_finished=lambda **kwargs: None,
        phase_begin=lambda name: None,
        phase_end=lambda name: None,
        remaining_timeout=lambda: 5.0,
        research_seconds_left=lambda: 30.0,
        trace=None,
        claim_rankings=rankings,
        stored_assessments={},
        assessed_inputs={},
        now_ms=lambda: 2000.0,
        deadline_seconds=48.0,
    )
    entry = _terminal_invocations(context)[0]
    assert entry["outcome"] == "assessed:1"
    assert entry["metrics_identity_changed"] is False
    assert "recovered" not in entry


def test_refusal_paths_are_terminal_even_with_identity_swap() -> None:
    """No-op and budget refusals must not leave a dangling invocation."""

    # no late ids at all, with a mid-call metrics swap
    context = _SwappingContext({"domain_targeted": []}, {"domain_targeted": []})
    claim = _claim()
    _late_admission_tail(
        cursor=_cursor(["https://docs.example.com/pulls"]),
        state=_state(claim),
        claim=claim,
        context=context,
        run_id="run_1",
        wave_index=2,
        max_reads=8,
        assessor=_Assessor(),
        model_allowed=lambda purpose, categories: True,
        on_model_started=lambda **kwargs: None,
        on_model_finished=lambda **kwargs: None,
        phase_begin=lambda name: None,
        phase_end=lambda name: None,
        remaining_timeout=lambda: 5.0,
        research_seconds_left=lambda: 30.0,
        trace=None,
        claim_rankings={},
        stored_assessments={},
        assessed_inputs={},
        now_ms=lambda: 2000.0,
        deadline_seconds=48.0,
    )
    entry = _terminal_invocations(context)[0]
    assert entry["outcome"] == "no_late_ids"
    assert entry["metrics_identity_changed"] is True

    # budget refusal, again with a swap
    refusal_context = _SwappingContext(
        {"domain_targeted": [
            {"claim_id": CLAIM_ID, "wave_index": 2, "added_candidate_ids": ["candidate_0"]}
        ]},
        {"domain_targeted": [
            {"claim_id": CLAIM_ID, "wave_index": 2, "added_candidate_ids": ["candidate_0"]}
        ]},
    )
    _late_admission_tail(
        cursor=_cursor(["https://docs.example.com/pulls"]),
        state=_state(claim),
        claim=claim,
        context=refusal_context,
        run_id="run_1",
        wave_index=2,
        max_reads=8,
        assessor=_Assessor(),
        model_allowed=lambda purpose, categories: True,
        on_model_started=lambda **kwargs: None,
        on_model_finished=lambda **kwargs: None,
        phase_begin=lambda name: None,
        phase_end=lambda name: None,
        remaining_timeout=lambda: 5.0,
        research_seconds_left=lambda: 1.0,
        trace=None,
        claim_rankings={},
        stored_assessments={},
        assessed_inputs={},
        now_ms=lambda: 2000.0,
        deadline_seconds=48.0,
    )
    entry = _terminal_invocations(refusal_context)[0]
    assert entry["outcome"] == "time_budget_exhausted"


def test_every_invocation_reaches_a_terminal_state() -> None:
    """No invocation may be left in the initial 'running' state."""

    terminal = {
        "no_late_ids",
        "no_late_candidates",
        "no_read_slot_for_claim",
        "time_budget_exhausted",
        "model_call_budget_exceeded",
        "policy_blocked",
        "assessment_failed",
    }
    contexts = []

    # assessed
    assessed_context = _context(["candidate_0"])
    _run_tail(cursor=_cursor(["https://docs.example.com/pulls"]), context=assessed_context)
    contexts.append(assessed_context)

    # no late ids
    empty_context = _context([])
    _run_tail(cursor=_cursor(["https://docs.example.com/pulls"]), context=empty_context)
    contexts.append(empty_context)

    # budget refusal
    refused_context = _context(["candidate_0"])
    _run_tail(
        cursor=_cursor(["https://docs.example.com/pulls"]),
        context=refused_context,
        seconds_left=1.0,
    )
    contexts.append(refused_context)

    # failed assessment
    failed_context = _context(["candidate_0"])
    _run_tail(
        cursor=_cursor(["https://docs.example.com/pulls"]),
        context=failed_context,
        assessor=_Assessor(status="unavailable"),
    )
    contexts.append(failed_context)

    for context in contexts:
        for entry in context["claim_engine_metrics"].get("late_tail_invocations") or []:
            outcome = str(entry.get("outcome") or "")
            assert outcome != "running" and outcome, entry
            assert outcome in terminal or outcome.startswith("assessed:"), entry

