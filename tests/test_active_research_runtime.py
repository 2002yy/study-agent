from __future__ import annotations

from collections import Counter
from collections.abc import Callable
from collections.abc import Mapping
from json import dumps as _json_dumps
from json import loads
from pathlib import Path
from types import SimpleNamespace
from threading import Event, Thread
from time import perf_counter
from typing import Any

from dataclasses import replace

import pytest


from src.application.active_research_runtime import (
    ACTIVE_RESEARCH_BRIEF_KEY,
    ACTIVE_RESEARCH_COVERED_CLUSTERS_KEY,
    ACTIVE_RESEARCH_METRICS_KEY,
    ACTIVE_RESEARCH_READ_PLAN_KEY,
    ACTIVE_RESEARCH_WAVE_BASELINE_KEY,
    ActiveResearchRuntimeExecutor,
    RuntimePlannedQuery,
    _append_gap_queries,
    _restore_completed_read_targets,
)
from src.application.research_web_lookup_dispatch import (
    _dispatch_state,
    ClaimEngineDispatchWebLookupService,
)
from src.api.routes.chat_routes import _research_progress
from src.domain.runtime_entities import WebLookupRun
from src.infrastructure.sqlite.database import RuntimeDatabase
from src.repositories.web_lookup_repository import WebLookupRepository
from src.web.research.active_adapter import ActiveResearchGateway
from src.web.research.claim_planner import ClaimBootstrapResult, RuntimeClaimPlanner
from src.web.research.contracts import (
    EvidenceGap,
    EvidenceRequirement,
    ResearchBudget,
    ResearchState,
    ResearchClaim,
    ResearchQuestion,
    build_research_state,
)
from src.web.research.model_gateway import ResearchModelGateway
from src.web.research.runtime import CLAIM_ENGINE_RUNTIME_CONTEXT_KEY, ResearchRuntimeCursor
from src.web.research.state import attach_claim_engine_state


def _active_context(*, policy_allowed: bool = True) -> dict[str, Any]:
    state = build_research_state(
        mode="active",
        questions=(),
        claims=(),
        evidence=(),
        evidence_links=(),
        source_clusters=(),
        gaps=(),
        conflict_gaps=(),
        budget=ResearchBudget(
            max_candidates=20,
            max_reads=8,
            soft_timeout_seconds=45,
            hard_timeout_seconds=60,
            max_total_chars=16000,
        ),
        reference_date="2026-08-27",
        known_evidence_ids=(),
    )
    return attach_claim_engine_state(
        {
            "source_truth_version": 2,
            "run_attempt": 0,
            "external_data_policy": {
                "web_allowed": policy_allowed,
                "reason": "allowed" if policy_allowed else "web_disabled_by_user",
            },
        },
        state,
        known_evidence_ids=(),
    )


class _StructuredClient:
    def __init__(
        self,
        *,
        on_call: Callable[[int], None] | None = None,
        malformed_extraction: bool = False,
        claims_count: int = 1,
    ) -> None:
        self.chat = SimpleNamespace(completions=self)
        self.calls: list[dict[str, Any]] = []
        self.on_call = on_call
        self.malformed_extraction = malformed_extraction
        self.claims_count = claims_count

    def with_options(self, **kwargs: Any) -> "_StructuredClient":
        assert kwargs == {"max_retries": 0}
        return self

    def create(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        if self.on_call is not None:
            self.on_call(len(self.calls))
        system = str(kwargs["messages"][0]["content"])
        request = loads(str(kwargs["messages"][1]["content"]))
        if "claim planner" in system:
            question = str(request["question"])
            supporting_claims: list[dict[str, str]] = []
            if self.claims_count > 1:
                critical_anchor = "verified current release date"
                supporting_anchor = "current release date"
                if critical_anchor not in question or supporting_anchor not in question:
                    raise AssertionError(
                        "multi-claim fixture requires two distinct question anchors"
                    )
                supporting_claims.append(
                    {
                        "question_anchor": supporting_anchor,
                        "kind": "factual",
                        "policy_profile": "current_fact",
                    }
                )
            else:
                critical_anchor = question if len(question) <= 160 else question[:160].rstrip()
            payload = {
                "schema_version": "research-runtime-claim-plan-v1",
                "critical_claim": {
                    "question_anchor": critical_anchor,
                    "kind": "factual",
                    "policy_profile": "current_fact",
                },
                "supporting_claims": supporting_claims,
            }
        elif "search candidates" in system:
            payload = {
                "schema_version": "candidate-assessment-v1",
                "assessments": [
                    {
                        "candidate_id": item["candidate_id"],
                        "relevance": "answer_relevant",
                        "relevance_confidence": 0.98,
                        "source_role": (
                            "primary" if index == 0 else "independent_secondary"
                        ),
                        "source_role_confidence": 0.95,
                        "expected_gain_signals": [
                            "new_primary" if index == 0 else "new_independent_cluster"
                        ],
                    }
                    for index, item in enumerate(request["candidates"])
                ],
            }
        else:
            # H7: anchors must differ per claim AND exist in the read excerpt
            # (the strict parser rejects anchors absent from the excerpt), and
            # the fake output must be deterministic per claim input.
            claim_text = str(request["claim_text"])
            if claim_text == "current release date":
                locator = "2026-08-01"
                anchored_spans = ["2026-08-01"]
            else:
                locator = "release date"
                anchored_spans = ["release date"]
            payload = {
                "schema_version": "research-evidence-extraction-v1",
                "candidate_id": (
                    "model_minted_candidate"
                    if self.malformed_extraction
                    else request["candidate_id"]
                ),
                "claim_id": request["claim_id"],
                "source_role": request["source_role"],
                "source_cluster_id": request["source_cluster_id"],
                "relation": "supports",
                "strength": 0.95,
                "locator": locator,
                "anchored_spans": anchored_spans,
                "caveats": [],
                "published_at": request["published_at"],
            }
        content = __import__("json").dumps(payload)
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content=content),
                    finish_reason="stop",
                )
            ],
            usage=SimpleNamespace(
                prompt_tokens=10,
                completion_tokens=10,
                total_tokens=20,
            ),
        )


class _SearchBackend:
    def __init__(self) -> None:
        self.calls = 0

    def search_exact(
        self,
        query: str,
        *,
        max_results: int = 5,
    ) -> dict[str, Any]:
        del query, max_results
        self.calls += 1
        results = [
            {
                "title": "Primary release",
                "url": "https://official.example/release",
                "snippet": "Verified release announcement",
                "published_at": "2026-08-01",
                "provider": "searxng",
            },
            {
                "title": "Independent verification",
                "url": "https://independent.example/report",
                "snippet": "Independent verification of the date",
                "published_at": "2026-08-02",
                "provider": "bing_rss",
            },
        ]
        return {
            "status": "ok",
            "reason": "results_found",
            "results": results,
            "providers_attempted": ["searxng", "bing_rss", "duckduckgo_html"],
            "provider_errors": [],
            "provider_audits": [],
            "provider_outcomes": [],
            "searched_at": "2026-08-27T00:00:00+00:00",
        }


class _EmptySearchBackend:
    def __init__(self) -> None:
        self.calls = 0

    def search_exact(
        self,
        query: str,
        *,
        max_results: int = 5,
    ) -> dict[str, Any]:
        del query, max_results
        self.calls += 1
        return {
            "status": "empty",
            "reason": "no_results",
            "results": [],
            "providers_attempted": ["searxng"],
            "provider_errors": [],
            "provider_audits": [],
            "provider_outcomes": [],
            "searched_at": "2026-08-29T00:00:00+00:00",
        }


class _UnavailableSearchBackend:
    def search_exact(
        self,
        query: str,
        *,
        max_results: int = 5,
    ) -> dict[str, Any]:
        del query, max_results
        return {
            "status": "unavailable",
            "reason": "providers_failed",
            "results": [],
            "providers_attempted": ["searxng"],
            "provider_errors": ["searxng:provider_timeout"],
            "provider_audits": [],
            "provider_outcomes": [],
            "searched_at": "2026-09-01T00:00:00+00:00",
        }


class _FloodSearchBackend:
    """Return a full pool of candidates on the first query (B5-H2)."""

    def __init__(self) -> None:
        self.calls = 0

    def search_exact(
        self,
        query: str,
        *,
        max_results: int = 5,
    ) -> dict[str, Any]:
        del query, max_results
        self.calls += 1
        results = [
            {
                "title": f"Flood result {index}",
                "url": f"https://flood.example/{self.calls}-{index}",
                "snippet": f"Flood snippet {index}",
                "published_at": "2026-08-01",
                "provider": "searxng",
            }
            for index in range(20)
        ]
        return {
            "status": "ok",
            "reason": "results_found",
            "results": results,
            "providers_attempted": ["searxng"],
            "provider_errors": [],
            "provider_audits": [],
            "provider_outcomes": [],
            "searched_at": "2026-08-27T00:00:00+00:00",
        }


class _ProvenanceSearchBackend:
    """Claim A queries return shared+a-only; claim B queries shared+b-only (B5-H3)."""

    def __init__(self) -> None:
        self.calls = 0

    def search_exact(
        self,
        query: str,
        *,
        max_results: int = 5,
    ) -> dict[str, Any]:
        del query, max_results
        self.calls += 1
        urls = (
            ["https://shared.example/source", "https://a-only.example/source"]
            if self.calls <= 2
            else ["https://shared.example/source", "https://b-only.example/source"]
        )
        results = [
            {
                "title": f"Result {url}",
                "url": url,
                "snippet": "Verified release announcement",
                "published_at": "2026-08-01",
                "provider": "searxng",
            }
            for url in urls
        ]
        return {
            "status": "ok",
            "reason": "results_found",
            "results": results,
            "providers_attempted": ["searxng"],
            "provider_errors": [],
            "provider_audits": [],
            "provider_outcomes": [],
            "searched_at": "2026-08-27T00:00:00+00:00",
        }


class _ReadGateway:
    def __init__(self, on_read: Callable[[], None] | None = None) -> None:
        self.on_read = on_read
        self.calls = 0

    def read(self, url: str, *, max_chars: int = 6000) -> dict[str, Any]:
        self.calls += 1
        if self.on_read is not None:
            self.on_read()
        return {
            "ok": True,
            "url": url,
            "title": "Read source",
            "content": "Verified fact: The release date is 2026-08-01."[:max_chars],
        }


class _RaisingReadGateway:
    def read(self, url: str, *, max_chars: int = 6000) -> dict[str, Any]:
        del url, max_chars
        raise TimeoutError("private reader detail")


class _PrimaryRoleClient(_StructuredClient):
    """Same fake as the suite default, but every candidate is assessed as
    primary/eligible - so a fresh cluster is always schedulable instead of
    being held back as lead_only by the H9 predicate."""

    def create(self, **kwargs: Any) -> Any:
        system = str(kwargs["messages"][0]["content"])
        if "search candidates" in system:
            request = loads(str(kwargs["messages"][1]["content"]))
            payload = {
                "schema_version": "candidate-assessment-v1",
                "assessments": [
                    {
                        "candidate_id": item["candidate_id"],
                        "relevance": "answer_relevant",
                        "relevance_confidence": 0.98,
                        "source_role": "primary",
                        "source_role_confidence": 0.95,
                        "expected_gain_signals": ["new_primary"],
                    }
                    for item in request["candidates"]
                ],
            }
            content = _json_dumps(payload)
            return SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(content=content),
                        finish_reason="stop",
                    )
                ],
                usage=SimpleNamespace(
                    prompt_tokens=10,
                    completion_tokens=10,
                    total_tokens=20,
                ),
            )
        return super().create(**kwargs)


class _TrackingRepository(WebLookupRepository):
    def __init__(self, database: RuntimeDatabase) -> None:
        super().__init__(database)
        self.visible_stages: list[str] = []

    def set_stage(
        self,
        run_id: str,
        *,
        stage: str,
        operation_id: str,
    ) -> WebLookupRun:
        self.visible_stages.append(stage)
        return super().set_stage(run_id, stage=stage, operation_id=operation_id)


def _service(
    repository: WebLookupRepository,
    client: _StructuredClient,
    *,
    search_backend: Any | None = None,
    read_gateway: Any | None = None,
    monotonic: Callable[[], float] = perf_counter,
) -> ClaimEngineDispatchWebLookupService:
    def gateway_factory() -> ActiveResearchGateway:
        return ActiveResearchGateway(
            search_backend=search_backend or _SearchBackend(),
            read_gateway=read_gateway or _ReadGateway(),
        )

    def runtime_factory(
        repo: WebLookupRepository,
        gateway: ActiveResearchGateway,
    ) -> ActiveResearchRuntimeExecutor:
        model = ResearchModelGateway(
            client=client,
            model_name="test-model",
            timeout_seconds=20,
        )
        return ActiveResearchRuntimeExecutor(
            repo,
            gateway,
            model_gateway=model,
            monotonic=monotonic,
        )

    return ClaimEngineDispatchWebLookupService(
        repository,
        active_gateway_factory=gateway_factory,
        active_runtime_factory=runtime_factory,
    )


def test_active_single_wave_builds_strict_evidence_and_passes_gate(tmp_path: Any) -> None:
    repository = _TrackingRepository(RuntimeDatabase(tmp_path / "active.sqlite"))
    run = repository.create(
        WebLookupRun(
            id="run_active_single_wave",
            query="What is the verified current release date?",
            stage="planned",
            status="pending",
            research_context=_active_context(),
            max_items=5,
        )
    )
    client = _StructuredClient()

    completed = _service(repository, client).execute(run.id, raise_on_error=True)

    assert completed.status == "completed"
    assert completed.provider_status == "found"
    assert completed.stop_reason == "evidence_gate_pass"
    assert len(completed.items) == 2
    assert len(completed.selected_sources) == 2
    assert all(item["read_status"] == "read" for item in completed.selected_sources)
    assert all(
        item["extraction"]["status"] == "eligible"
        for item in completed.selected_sources
    )
    brief = completed.research_context[ACTIVE_RESEARCH_BRIEF_KEY]
    assert brief["gate_status"] == "pass"
    assert brief["conditional_wording_required"] is False
    assert len(brief["eligible_evidence"]) == 2
    assert brief["open_critical_claim_ids"] == []
    assert "Search results" not in completed.source_block
    metrics = completed.research_context[ACTIVE_RESEARCH_METRICS_KEY]
    assert metrics["candidate_count"] == 2
    assert metrics["read_count"] == 2
    assert metrics["cluster_count"] == 2
    assert all(attempt.get("provider_audit") for attempt in completed.query_attempts)
    runtime = completed.research_context["claim_engine_runtime"]
    assert runtime["inflight_model_call"] is None
    assert runtime["inflight_external_call"] is None
    assert len(runtime["model_calls"]) == len(client.calls)
    assert client.calls
    assert all(1.0 <= float(call["timeout"]) <= 20.0 for call in client.calls)
    assert {
        tuple(candidate["providers"])
        for candidate in runtime["candidates"]
    } == {("searxng",), ("bing_rss",)}
    assert repository.visible_stages == ["searching", "assessing", "reading", "gating"]
    progress = _research_progress(completed)
    assert progress["candidate_count"] == 2
    assert progress["read_count"] == 2
    assert progress["cluster_count"] == 2
    assert progress["open_critical_gap_count"] == 0
    assert progress["gate_status"] == "pass"


def test_active_model_policy_denial_fails_closed_before_external_call(tmp_path: Any) -> None:
    repository = WebLookupRepository(RuntimeDatabase(tmp_path / "deny.sqlite"))
    run = repository.create(
        WebLookupRun(
            id="run_active_policy_deny",
            query="Research this",
            stage="planned",
            status="pending",
            research_context=_active_context(policy_allowed=False),
        )
    )
    client = _StructuredClient()

    failed = _service(repository, client).execute(run.id)

    assert failed.status == "failed"
    assert failed.provider_status == "unavailable"
    assert failed.stop_reason == "claim_planning_blocked_by_policy"
    assert client.calls == []
    audits = failed.research_context["claim_engine_policy_audits"]
    assert audits[-1]["status"] == "blocked_by_policy"
    cursor = ResearchRuntimeCursor.from_dict(
        failed.research_context[CLAIM_ENGINE_RUNTIME_CONTEXT_KEY]
    )
    assert cursor.schema_version == "research-runtime-v2"
    assert [failure.code for failure in cursor.failures] == ["policy_blocked"]
    assert cursor.failures[0].detail == "blocked_by_policy"
    assert cursor.failures[0].failure_id


def test_unavailable_search_projects_canonical_outcome_and_failure(tmp_path: Any) -> None:
    repository = WebLookupRepository(RuntimeDatabase(tmp_path / "search-failure.sqlite"))
    run = repository.create(
        WebLookupRun(
            id="run_active_search_failure",
            query="Research unavailable providers",
            stage="planned",
            status="pending",
            research_context=_active_context(),
        )
    )

    completed = _service(
        repository,
        _StructuredClient(),
        search_backend=_UnavailableSearchBackend(),
    ).execute(run.id, raise_on_error=True)

    cursor = ResearchRuntimeCursor.from_dict(
        completed.research_context[CLAIM_ENGINE_RUNTIME_CONTEXT_KEY]
    )
    assert cursor.query_outcomes
    assert all(item.error_code == "search_failed" for item in cursor.query_outcomes)
    search_failures = [item for item in cursor.failures if item.code == "search_failed"]
    assert search_failures
    assert all(item.detail == "providers_failed" for item in search_failures)
    assert all(item.provider_code == "searxng:provider_timeout" for item in search_failures)
    assert len({item.failure_id for item in search_failures}) == len(search_failures)


def test_failed_read_projects_canonical_outcome_and_failure(tmp_path: Any) -> None:
    repository = WebLookupRepository(RuntimeDatabase(tmp_path / "read-failure.sqlite"))
    run = repository.create(
        WebLookupRun(
            id="run_active_read_failure",
            query="Research reader failures",
            stage="planned",
            status="pending",
            research_context=_active_context(),
        )
    )

    completed = _service(
        repository,
        _StructuredClient(),
        read_gateway=_RaisingReadGateway(),
    ).execute(run.id, raise_on_error=True)

    cursor = ResearchRuntimeCursor.from_dict(
        completed.research_context[CLAIM_ENGINE_RUNTIME_CONTEXT_KEY]
    )
    assert cursor.read_outcomes
    assert all(item.error_code == "read_failed" for item in cursor.read_outcomes)
    read_failures = [item for item in cursor.failures if item.code == "read_failed"]
    assert read_failures
    assert all(item.detail == "TimeoutError" for item in read_failures)
    assert all(item.exception_type == "TimeoutError" for item in read_failures)
    assert len({item.failure_id for item in read_failures}) == len(read_failures)


def _two_gap_state(*, same_claim_text: bool = False) -> Any:
    question = ResearchQuestion(id="question_1", question_surface="Compare releases")
    requirement = EvidenceRequirement(
        source_roles=("primary", "independent_secondary"),
        min_independent_sources=2,
        requires_primary_source=True,
    )
    claims = (
        ResearchClaim(
            id="claim_1",
            question_id=question.id,
            text="Alpha framework current release",
            kind="factual",
            priority="critical",
            state="searching",
            evidence_requirement=requirement,
        ),
        ResearchClaim(
            id="claim_2",
            question_id=question.id,
            text=(
                "Alpha framework current release"
                if same_claim_text
                else "Beta framework current release"
            ),
            kind="factual",
            priority="critical",
            state="searching",
            evidence_requirement=requirement,
        ),
    )
    gaps = (
        EvidenceGap(
            id="gap_1",
            claim_id="claim_1",
            gap_type="missing_primary",
            desired_source_role="primary",
            priority="critical",
        ),
        EvidenceGap(
            id="gap_2",
            claim_id="claim_2",
            gap_type="missing_primary",
            desired_source_role="primary",
            priority="critical",
        ),
    )
    return build_research_state(
        mode="active",
        questions=(question,),
        claims=claims,
        evidence=(),
        evidence_links=(),
        source_clusters=(),
        gaps=gaps,
        conflict_gaps=(),
        budget=ResearchBudget(
            max_candidates=20,
            max_reads=8,
            soft_timeout_seconds=45,
            hard_timeout_seconds=60,
            max_total_chars=16000,
        ),
        reference_date="2026-08-29",
        known_evidence_ids=(),
    )


def test_two_gap_wave_appends_four_unique_queries_per_gap_once() -> None:
    state = _two_gap_state()

    first_wave = _append_gap_queries(ResearchRuntimeCursor(), state)
    second_wave = _append_gap_queries(first_wave, state)

    assert Counter(query.gap_id for query in first_wave.planned_queries) == {
        "gap_1": 4,
        "gap_2": 4,
    }
    assert len(first_wave.planned_queries) == 8
    assert len({query.id for query in first_wave.planned_queries}) == 8
    assert second_wave.planned_queries == first_wave.planned_queries


def test_semantic_query_dedupe_still_saturates_each_active_gap(tmp_path: Any) -> None:
    state = _two_gap_state(same_claim_text=True)
    context = attach_claim_engine_state(
        _active_context(),
        state,
        known_evidence_ids=(),
    )
    repository = _TrackingRepository(RuntimeDatabase(tmp_path / "active-gaps.sqlite"))
    run = repository.create(
        WebLookupRun(
            id="run_active_gap_saturation",
            query="Compare identical research surfaces",
            stage="planned",
            status="pending",
            research_context=context,
            max_items=5,
        )
    )
    search = _EmptySearchBackend()
    client = _StructuredClient()

    completed = _service(repository, client, search_backend=search).execute(
        run.id,
        raise_on_error=True,
    )

    assert completed.status == "partial"
    assert completed.stop_reason == "evidence_saturated"
    cursor = ResearchRuntimeCursor.from_dict(
        completed.research_context[CLAIM_ENGINE_RUNTIME_CONTEXT_KEY]
    )
    assert cursor.wave_index == 3
    assert cursor.active_gap_ids == ("gap_1", "gap_2")
    assert cursor.no_gain_batches_by_gap == {"gap_1": 3, "gap_2": 3}
    assert cursor.no_gain_batches_by_claim == {"claim_1": 3, "claim_2": 3}
    assert len(cursor.gain_history) == 3
    assert all(item["substantive_gain"] is False for item in cursor.gain_history)
    assert len(cursor.planned_queries) == 4
    assert len({item.query.casefold() for item in cursor.planned_queries}) == 4
    assert search.calls == 4
    assert client.calls == []


def test_malformed_extraction_never_becomes_evidence_and_resume_skips_calls(
    tmp_path: Any,
) -> None:
    repository = WebLookupRepository(RuntimeDatabase(tmp_path / "malformed.sqlite"))
    run = repository.create(
        WebLookupRun(
            id="run_active_malformed_extraction",
            query="What is the verified current release date?",
            stage="planned",
            status="pending",
            research_context=_active_context(),
        )
    )
    client = _StructuredClient(malformed_extraction=True)

    partial = _service(repository, client).execute(run.id, raise_on_error=True)

    assert partial.status == "partial"
    assert partial.provider_status == "insufficient"
    assert partial.stop_reason == "evidence_saturated"
    assert partial.items == []
    assert all(item["read_status"] == "read" for item in partial.selected_sources)
    assert all(
        list((item.get("extractions") or {}).values())[0]["status"] == "extractor_failed"
        for item in partial.selected_sources
    )
    partial_brief = partial.research_context[ACTIVE_RESEARCH_BRIEF_KEY]
    assert partial_brief["gate_status"] in {"block", "partial"}
    assert partial_brief["conditional_wording_required"] is True
    assert "只能使用条件化措辞" in partial.source_block
    assert partial.research_context[ACTIVE_RESEARCH_BRIEF_KEY]["eligible_evidence"] == []

    resumed_client = _StructuredClient(on_call=lambda _index: (_ for _ in ()).throw(AssertionError("model call repeated")))
    resumed_search = _SearchBackend()
    resumed_read = _ReadGateway()
    resumed = _service(
        repository,
        resumed_client,
        search_backend=resumed_search,
        read_gateway=resumed_read,
    ).execute(run.id, raise_on_error=True)

    assert resumed.status == "partial"
    assert resumed.stop_reason == "evidence_saturated"
    assert resumed_client.calls == []
    assert resumed_read.calls == 0


def test_model_crash_after_success_before_semantic_persist_recovers_via_new_attempt(
    tmp_path: Any,
) -> None:
    """B5-H1: a completed model audit must never persist without its semantic result.

    A crash between the model audit callback and the semantic-result checkpoint
    leaves the durable truth as an inflight call, so recovery resolves through
    interrupted_unknown with a bounded new attempt instead of raising
    "completed model call cannot remain inflight".
    """
    repository = _TrackingRepository(RuntimeDatabase(tmp_path / "active_crash.sqlite"))
    run = repository.create(
        WebLookupRun(
            id="run_active_crash_semantic_persist",
            query="What is the verified current release date?",
            stage="planned",
            status="pending",
            research_context=_active_context(),
            max_items=5,
        )
    )
    client = _StructuredClient()

    class _CrashAfterModelSuccessPlanner(RuntimeClaimPlanner):
        def __init__(self, inner: RuntimeClaimPlanner, repo: WebLookupRepository) -> None:
            self._inner = inner
            self._repo = repo
            self.calls = 0

        def plan(self, **kwargs: Any) -> ClaimBootstrapResult:
            self.calls += 1
            bootstrap = self._inner.plan(**kwargs)
            if self.calls == 1:
                # The model succeeded and the audit callback ran; before the
                # semantic result is persisted the durable truth must still be
                # an inflight call with no completed audit.
                durable = self._repo.get(run.id)
                assert durable is not None
                cursor = ResearchRuntimeCursor.from_dict(
                    durable.research_context[CLAIM_ENGINE_RUNTIME_CONTEXT_KEY]
                )
                assert cursor.inflight_model_call is not None
                assert cursor.model_calls == ()
                # Simulate the process dying: fail the run through its real
                # owner so the executor fallback short-circuits and the durable
                # state stays at the last checkpoint (the inflight marker).
                self._repo.fail(
                    run.id,
                    "simulated crash before semantic persist",
                    operation_id=durable.active_operation_id,
                )
                raise RuntimeError("simulated crash before semantic persist")
            return bootstrap

    model = ResearchModelGateway(
        client=client,
        model_name="test-model",
        timeout_seconds=20,
    )
    # Shared across execute() calls so the crash triggers exactly once.
    crash_planner = _CrashAfterModelSuccessPlanner(
        RuntimeClaimPlanner(model),
        repository,
    )

    def runtime_factory(
        repo: WebLookupRepository,
        gateway: ActiveResearchGateway,
    ) -> ActiveResearchRuntimeExecutor:
        return ActiveResearchRuntimeExecutor(
            repo,
            gateway,
            model_gateway=model,
            claim_planner=crash_planner,
        )

    service = ClaimEngineDispatchWebLookupService(
        repository,
        active_gateway_factory=lambda: ActiveResearchGateway(
            search_backend=_SearchBackend(),
            read_gateway=_ReadGateway(),
        ),
        active_runtime_factory=runtime_factory,
    )

    with pytest.raises(RuntimeError, match="simulated crash"):
        service.execute(run.id, raise_on_error=True)

    crashed = repository.get(run.id)
    assert crashed is not None
    # The wrapper intentionally failed the run to short-circuit the executor
    # fallback; the H1 invariant is that the durable cursor still holds the
    # inflight marker with no completed audit.
    crashed_cursor = ResearchRuntimeCursor.from_dict(
        crashed.research_context[CLAIM_ENGINE_RUNTIME_CONTEXT_KEY]
    )
    assert crashed_cursor.inflight_model_call is not None
    assert crashed_cursor.model_calls == ()

    recovered = service.execute(run.id, raise_on_error=True)

    assert recovered.status == "completed"
    cursor = ResearchRuntimeCursor.from_dict(
        recovered.research_context[CLAIM_ENGINE_RUNTIME_CONTEXT_KEY]
    )
    assert cursor.inflight_model_call is None
    assert any(
        item.code == "claim_planning_failed"
        and item.detail == "interrupted_unknown"
        for item in cursor.failures
    )
    planning_audits = [
        item
        for item in cursor.model_calls
        if item.logical_call_id.startswith("research_claim_plan")
    ]
    assert len(planning_audits) == 1
    assert planning_audits[0].status == "completed"
    assert planning_audits[0].attempt == 2
    assert planning_audits[0].call_id.endswith(":attempt:2")
    assert any(
        item.code == "claim_planning_failed"
        and item.detail == "interrupted_unknown"
        and item.item_id.endswith(":attempt:1")
        for item in cursor.failures
    )
    assert len({item.call_id for item in cursor.model_calls}) == len(cursor.model_calls)


def test_crash_after_extraction_preserves_wave_baseline_and_gain(tmp_path: Any) -> None:
    class _CrashAfterExtractionRepository(_TrackingRepository):
        def __init__(self, database: RuntimeDatabase) -> None:
            super().__init__(database)
            self.crashed = False

        def checkpoint(self, run_id: str, **kwargs: Any) -> WebLookupRun:
            persisted = super().checkpoint(run_id, **kwargs)
            if self.crashed:
                return persisted
            has_eligible_extraction = any(
                isinstance(record.get("extractions"), dict)
                and any(
                    isinstance(detail, dict) and detail.get("status") == "eligible"
                    for detail in record["extractions"].values()
                )
                for record in kwargs["selected_sources"]
            )
            cursor = ResearchRuntimeCursor.from_dict(
                persisted.research_context[CLAIM_ENGINE_RUNTIME_CONTEXT_KEY]
            )
            if has_eligible_extraction and not cursor.gain_history:
                self.crashed = True
                assert persisted.active_operation_id
                self.fail(
                    run_id,
                    "simulated crash after extraction",
                    operation_id=persisted.active_operation_id,
                )
                raise RuntimeError("simulated crash after extraction")
            return persisted

    repository = _CrashAfterExtractionRepository(
        RuntimeDatabase(tmp_path / "active-extraction-crash.sqlite")
    )
    run = repository.create(
        WebLookupRun(
            id="run_active_extraction_crash",
            query="What is the verified current release date?",
            stage="planned",
            status="pending",
            research_context=_active_context(),
            max_items=5,
        )
    )
    client = _StructuredClient()
    search = _SearchBackend()
    reader = _ReadGateway()
    service = _service(
        repository,
        client,
        search_backend=search,
        read_gateway=reader,
    )

    with pytest.raises(RuntimeError, match="simulated crash after extraction"):
        service.execute(run.id, raise_on_error=True)

    crashed = repository.get(run.id)
    assert crashed is not None
    baseline = crashed.research_context[ACTIVE_RESEARCH_WAVE_BASELINE_KEY]
    assert baseline["evidence"] == []
    crashed_state = _dispatch_state(crashed)
    assert crashed_state is not None
    assert len(crashed_state.evidence) == 1
    crashed_cursor = ResearchRuntimeCursor.from_dict(
        crashed.research_context[CLAIM_ENGINE_RUNTIME_CONTEXT_KEY]
    )
    assert crashed_cursor.wave_index == 1
    assert crashed_cursor.wave_id == f"research_wave:{run.id}:1"
    assert crashed_cursor.gain_history == ()
    search_calls = search.calls
    read_calls = reader.calls

    recovered = service.execute(run.id, raise_on_error=True)

    assert recovered.status == "completed"
    cursor = ResearchRuntimeCursor.from_dict(
        recovered.research_context[CLAIM_ENGINE_RUNTIME_CONTEXT_KEY]
    )
    assert len(cursor.gain_history) == 1
    assert cursor.gain_history[0]["substantive_gain"] is True
    assert "new_eligible_evidence" in cursor.gain_history[0]["gain_reasons"]
    assert search.calls == search_calls
    assert reader.calls == read_calls
    assert len({item.id for item in cursor.planned_queries}) == len(
        cursor.planned_queries
    )


def test_full_candidate_pool_stops_pending_external_searches(tmp_path: Any) -> None:
    """B5-H2: a full candidate pool must stop pending external searches.

    The first query fills the pool to its frozen cap (20); the second planned
    query would only burn shared budget on results the pool would drop, so it
    must be skipped before any external call is issued.
    """
    repository = _TrackingRepository(RuntimeDatabase(tmp_path / "active_flood.sqlite"))
    run = repository.create(
        WebLookupRun(
            id="run_active_flood_pool",
            query="What is the verified current release date?",
            stage="planned",
            status="pending",
            research_context=_active_context(),
            max_items=5,
        )
    )
    client = _StructuredClient()
    search = _FloodSearchBackend()

    completed = _service(repository, client, search_backend=search).execute(
        run.id,
        raise_on_error=True,
    )

    # The flood data collapses into a single candidate cluster, so the gate
    # legitimately settles partial; the H2 assertions are the search stop and
    # the pool cap, not the gate outcome.
    assert completed.status == "partial"
    assert completed.stop_reason == "evidence_saturated"
    assert search.calls == 1
    cursor = ResearchRuntimeCursor.from_dict(
        completed.research_context[CLAIM_ENGINE_RUNTIME_CONTEXT_KEY]
    )
    assert len(cursor.candidates) == 20
    assert len(cursor.completed_query_ids) == 1


def test_one_physical_read_serves_multiple_claims(tmp_path: Any) -> None:
    """B5-H3: deduplicate reads, not claim-evidence bindings.

    Claim A and claim B queries both discover shared.example/source; the
    candidate's provenance merges (query_ids from both claims) and the source
    must be read once while evidence is extracted for both claims.
    """
    repository = _TrackingRepository(RuntimeDatabase(tmp_path / "active_multiclaim.sqlite"))
    run = repository.create(
        WebLookupRun(
            id="run_active_multiclaim_read",
            query="What is the verified current release date?",
            stage="planned",
            status="pending",
            research_context=_active_context(),
            max_items=5,
        )
    )
    client = _StructuredClient(claims_count=2)
    search = _ProvenanceSearchBackend()

    completed = _service(repository, client, search_backend=search).execute(
        run.id,
        raise_on_error=True,
    )

    cursor = ResearchRuntimeCursor.from_dict(
        completed.research_context[CLAIM_ENGINE_RUNTIME_CONTEXT_KEY]
    )
    queries_by_claim: dict[str, set[str]] = {}
    for query in cursor.planned_queries:
        queries_by_claim.setdefault(query.claim_id, set()).add(query.id)
    assert len(queries_by_claim) == 2

    shared = next(
        item for item in cursor.candidates if item.url == "https://shared.example/source"
    )
    # Provenance merge: the shared candidate carries query ids from both claims.
    assert all(
        queries_by_claim[claim_id] & set(shared.query_ids)
        for claim_id in queries_by_claim
    )

    # Exactly one physical read for the shared source.
    shared_reads = [
        outcome for outcome in cursor.read_outcomes if outcome.candidate_id == shared.id
    ]
    assert len(shared_reads) == 1
    assert shared_reads[0].status == "success"
    shared_evidence_id = shared_reads[0].evidence_id
    assert shared_evidence_id

    # Extraction targets: (shared, claimA) and (shared, claimB), bound once each.
    plan = completed.research_context[ACTIVE_RESEARCH_READ_PLAN_KEY]
    shared_targets = [
        item for item in plan["extraction_targets"] if item["candidate_id"] == shared.id
    ]
    assert len(shared_targets) == 2
    assert {item["claim_id"] for item in shared_targets} == set(queries_by_claim)
    shared_physical = [
        item for item in plan["physical_reads"] if item["candidate_id"] == shared.id
    ]
    assert len(shared_physical) == 1

    # One server-owned evidence identity, linked from both claims.
    persisted = repository.get(run.id)
    assert persisted is not None
    state = _dispatch_state(persisted)
    assert state is not None
    links = [
        link for link in state.evidence_links if link.evidence_id == shared_evidence_id
    ]
    assert {link.claim_id for link in links} == set(queries_by_claim)

    record = next(
        item
        for item in completed.selected_sources
        if item["candidate_id"] == shared.id
    )
    assert set((record.get("extractions") or {})) == set(queries_by_claim)

    # H7: each claim row keeps its own anchor on the shared evidence.
    brief_rows = completed.research_context[ACTIVE_RESEARCH_BRIEF_KEY][
        "eligible_evidence"
    ]
    rows_by_claim = {
        row["claim_id"]: row
        for row in brief_rows
        if row["evidence_id"] == shared_evidence_id
    }
    assert len(rows_by_claim) == 2
    state = _dispatch_state(repository.get(run.id))
    assert state is not None
    anchors = {}
    for claim in state.claims:
        row = rows_by_claim[claim.id]
        if claim.text == "current release date":
            assert row["locator"] == "2026-08-01"
            assert row["anchored_spans"] == ["2026-08-01"]
            anchors[claim.id] = (row["locator"], tuple(row["anchored_spans"]))
        else:
            assert row["locator"] == "release date"
            assert row["anchored_spans"] == ["release date"]
            anchors[claim.id] = (row["locator"], tuple(row["anchored_spans"]))
    assert len(set(anchors.values())) == 2


def test_active_cancel_during_claim_planning_settles_durably(tmp_path: Any) -> None:
    repository = WebLookupRepository(RuntimeDatabase(tmp_path / "cancel-model.sqlite"))
    run = repository.create(
        WebLookupRun(
            id="run_cancel_model",
            query="Research this",
            stage="planned",
            status="pending",
            research_context=_active_context(),
        )
    )
    client = _StructuredClient(on_call=lambda _index: repository.request_cancel(run.id))

    cancelled = _service(repository, client).execute(run.id, raise_on_error=True)

    _assert_cancelled(cancelled)


def test_active_cancel_during_search_settles_durably(tmp_path: Any) -> None:
    repository = WebLookupRepository(RuntimeDatabase(tmp_path / "cancel-search.sqlite"))
    run = repository.create(
        WebLookupRun(
            id="run_cancel_search",
            query="Research this",
            stage="planned",
            status="pending",
            research_context=_active_context(),
        )
    )

    class CancellingSearch(_SearchBackend):
        def search_exact(self, query: str, *, max_results: int = 5) -> dict[str, Any]:
            repository.request_cancel(run.id)
            return super().search_exact(query, max_results=max_results)

    cancelled = _service(
        repository,
        _StructuredClient(),
        search_backend=CancellingSearch(),
    ).execute(run.id, raise_on_error=True)

    _assert_cancelled(cancelled)


def test_active_cancel_during_read_settles_durably(tmp_path: Any) -> None:
    repository = WebLookupRepository(RuntimeDatabase(tmp_path / "cancel-read.sqlite"))
    run = repository.create(
        WebLookupRun(
            id="run_cancel_read",
            query="Research this",
            stage="planned",
            status="pending",
            research_context=_active_context(),
        )
    )
    reader = _ReadGateway(on_read=lambda: repository.request_cancel(run.id))

    cancelled = _service(
        repository,
        _StructuredClient(),
        read_gateway=reader,
    ).execute(run.id, raise_on_error=True)

    _assert_cancelled(cancelled)


def test_active_cancel_during_extraction_settles_durably(tmp_path: Any) -> None:
    repository = WebLookupRepository(RuntimeDatabase(tmp_path / "cancel-extract.sqlite"))
    run = repository.create(
        WebLookupRun(
            id="run_cancel_extract",
            query="Research this",
            stage="planned",
            status="pending",
            research_context=_active_context(),
        )
    )
    client = _StructuredClient(
        on_call=lambda index: repository.request_cancel(run.id) if index == 3 else None
    )

    cancelled = _service(repository, client).execute(run.id, raise_on_error=True)

    _assert_cancelled(cancelled)


def _assert_cancelled(run: WebLookupRun) -> None:
    assert run.status == "cancelled"
    assert run.stage == "cancelled"
    assert run.stop_reason == "user_cancelled"
    runtime = run.research_context["claim_engine_runtime"]
    assert runtime["inflight_model_call"] is None
    assert runtime["inflight_external_call"] is None


@pytest.mark.parametrize(
    ("blocked_stage", "declared_timeout_seconds"),
    [("model", 20.0), ("provider", 8.0), ("reader", 10.0)],
)
def test_slow_active_stage_cancel_settles_within_call_timeout_plus_one(
    tmp_path: Any,
    blocked_stage: str,
    declared_timeout_seconds: float,
) -> None:
    repository = WebLookupRepository(
        RuntimeDatabase(tmp_path / f"slow-{blocked_stage}.sqlite")
    )
    run = repository.create(
        WebLookupRun(
            id=f"run_slow_{blocked_stage}",
            query="Research this",
            stage="planned",
            status="pending",
            research_context=_active_context(),
        )
    )
    entered = Event()
    release = Event()

    def block() -> None:
        entered.set()
        assert release.wait(timeout=2.0)

    client = _StructuredClient(
        on_call=(lambda index: block() if blocked_stage == "model" and index == 1 else None)
    )

    class BlockingSearch(_SearchBackend):
        def search_exact(self, query: str, *, max_results: int = 5) -> dict[str, Any]:
            if blocked_stage == "provider":
                block()
            return super().search_exact(query, max_results=max_results)

    reader = _ReadGateway(on_read=block if blocked_stage == "reader" else None)
    service = _service(
        repository,
        client,
        search_backend=BlockingSearch(),
        read_gateway=reader,
    )
    results: list[WebLookupRun] = []
    worker = Thread(
        target=lambda: results.append(service.execute(run.id, raise_on_error=True)),
        daemon=True,
    )
    worker.start()
    assert entered.wait(timeout=3.0)

    registered_at = perf_counter()
    repository.request_cancel(run.id)
    assert not release.wait(timeout=0.12)
    release.set()
    worker.join(timeout=3.0)
    settle_seconds = perf_counter() - registered_at

    assert not worker.is_alive()
    assert len(results) == 1
    _assert_cancelled(results[0])
    assert settle_seconds <= declared_timeout_seconds + 1.0
    print(
        f"B5_SLOW_CANCEL stage={blocked_stage} "
        f"settle_seconds={settle_seconds:.3f} "
        f"bound_seconds={declared_timeout_seconds + 1.0:.1f}"
    )

def test_read_plan_cluster_diversity_spans_reusable_and_fresh() -> None:
    """B5-H8: fresh selections must skip clusters the claim already covers.

    Wave 1 binds the reusable shared candidate (cluster X) to claim_B; wave 2
    must skip the fresh same-cluster candidate Q without wasting the slot, and
    still take R (cluster Y).
    """
    from src.application.active_research_runtime import _fair_read_plan
    from src.web.research.candidate_assessment import CandidateSemanticAssessment
    from src.web.research.candidate_pool import CandidatePoolItem
    from src.web.research.candidate_ranking import RankedCandidate
    from src.web.research.contracts import (
        EvidenceRequirement,
        ResearchClaim,
        ResearchQuestion,
    )

    question = ResearchQuestion(id="q1", question_surface="question")
    question_tuple = (question,)

    def claim(claim_id: str) -> ResearchClaim:
        return ResearchClaim(
            id=claim_id,
            question_id="q1",
            text="claim",
            kind="factual",
            priority="critical",
            state="pending",
            evidence_requirement=EvidenceRequirement(),
        )

    def ranked(candidate_id: str, cluster_id: str, rank: int) -> RankedCandidate:
        candidate = CandidatePoolItem(
            id=candidate_id,
            canonical_url=f"https://x.example/{candidate_id}",
            url=f"https://x.example/{candidate_id}",
            title=candidate_id,
            snippet="",
            source="",
            published_at="",
            query_ids=("q1",),
            intents=(),
            providers=("searxng",),
            first_seen_rank=rank,
        )
        assessment = CandidateSemanticAssessment(
            candidate_id=candidate_id,
            relevance="answer_relevant",
            relevance_confidence=0.9,
            source_role="primary",
            source_role_confidence=0.9,
            cluster_id=cluster_id,
            expected_gain_signals=("new_primary",),
            freshness_score=0.5,
            estimated_read_cost=1.0,
        )
        return RankedCandidate(
            candidate=candidate,
            assessment=assessment,
            rank=rank,
            eligibility="eligible",
            reason_codes=(),
            new_cluster=False,
            expected_information_gain=1,
        )

    state = build_research_state(
        mode="active",
        questions=question_tuple,
        claims=(claim("claim_A"), claim("claim_B")),
        evidence=(),
        evidence_links=(),
        source_clusters=(),
        gaps=(),
        conflict_gaps=(),
        budget=ResearchBudget(
            max_candidates=20,
            max_reads=8,
            soft_timeout_seconds=45,
            hard_timeout_seconds=60,
            max_total_chars=16000,
        ),
        reference_date="2026-08-28",
        known_evidence_ids=(),
    )
    rankings = {
        "claim_A": (ranked("P", "cluster_X", 1),),
        "claim_B": (
            ranked("P", "cluster_X", 1),
            ranked("Q", "cluster_X", 2),
            ranked("R", "cluster_Y", 3),
        ),
    }

    physical, targets = _fair_read_plan(state, rankings)

    b_pairs = {
        (item["candidate_id"], item["cluster_id"])
        for item in targets
        if item["claim_id"] == "claim_B"
    }
    assert ("P", "cluster_X") in b_pairs
    # H8: Q shares cluster X with the already-bound P, so it must be skipped
    # while R (cluster Y) still fills the slot.
    assert ("Q", "cluster_X") not in b_pairs
    assert ("R", "cluster_Y") in b_pairs
    assert "Q" not in {item["candidate_id"] for item in physical}

    # Later-wave planning removes the already-read P from fresh rankings, but
    # must still seed claim B with P's persisted cluster X. Q is therefore
    # skipped and the independent cluster Y candidate R is selected.
    later_physical, later_targets = _fair_read_plan(
        state,
        {
            "claim_B": (
                ranked("Q", "cluster_X", 2),
                ranked("R", "cluster_Y", 3),
            )
        },
        covered_cluster_ids_by_claim={"claim_B": {"cluster_X"}},
    )
    later_pairs = {
        (item["candidate_id"], item["cluster_id"])
        for item in later_targets
        if item["claim_id"] == "claim_B"
    }
    assert ("Q", "cluster_X") not in later_pairs
    assert ("R", "cluster_Y") in later_pairs
    assert {item["candidate_id"] for item in later_physical} == {"R"}


def test_read_plan_uses_persisted_conflicts_and_backfills_major_slots() -> None:
    """Persisted conflict truth releases reserve, and covered clusters do not
    consume a major claim's one-item wave before an independent backfill."""
    from src.application.active_research_runtime import _fair_read_plan
    from src.web.research.candidate_assessment import CandidateSemanticAssessment
    from src.web.research.candidate_pool import CandidatePoolItem
    from src.web.research.candidate_ranking import RankedCandidate
    from src.domain.evidence import ClaimEvidenceLinkV1
    from src.web.research.contracts import (
        ConflictGap,
        EvidenceCluster,
        ResearchClaimEvidenceLink,
        ResearchEvidence,
    )

    question = ResearchQuestion(id="q1", question_surface="question")

    def claim(claim_id: str, priority: Any) -> ResearchClaim:
        return ResearchClaim(
            id=claim_id,
            question_id="q1",
            text="claim",
            kind="factual",
            priority=priority,
            state="pending",
            evidence_requirement=EvidenceRequirement(),
        )

    def ranked(candidate_id: str, cluster_id: str, rank: int) -> Any:
        candidate = CandidatePoolItem(
            id=candidate_id,
            canonical_url=f"https://x.example/{candidate_id}",
            url=f"https://x.example/{candidate_id}",
            title=candidate_id,
            snippet="",
            source="",
            published_at="",
            query_ids=("q1",),
            intents=(),
            providers=("searxng",),
            first_seen_rank=rank,
        )
        return RankedCandidate(
            candidate=candidate,
            assessment=CandidateSemanticAssessment(
                candidate_id=candidate_id,
                relevance="answer_relevant",
                relevance_confidence=0.9,
                source_role="primary",
                source_role_confidence=0.9,
                cluster_id=cluster_id,
                # Deliberately no new_contradiction: the persisted conflict,
                # not a prediction on this candidate, must release reserve.
                expected_gain_signals=("new_primary",),
                freshness_score=0.5,
                estimated_read_cost=1.0,
            ),
            rank=rank,
            eligibility="eligible",
            reason_codes=(),
            new_cluster=False,
            expected_information_gain=1,
        )

    conflict_claim = claim("claim_conflict", "critical")
    conflict_evidence = (
        ResearchEvidence(
            evidence_id="ev_support",
            locator="support",
            anchored_spans=("support",),
            lifecycle_status="read",
            extraction_status="eligible",
        ),
        ResearchEvidence(
            evidence_id="ev_contradict",
            locator="contradict",
            anchored_spans=("contradict",),
            lifecycle_status="read",
            extraction_status="eligible",
        ),
    )
    conflict_links = (
        ResearchClaimEvidenceLink(
            link=ClaimEvidenceLinkV1(
                claim_id=conflict_claim.id,
                evidence_id="ev_support",
                support_type="supports",
                confidence=0.9,
            ),
            source_role="primary",
            source_cluster_id="evidence_cluster_support",
        ),
        ResearchClaimEvidenceLink(
            link=ClaimEvidenceLinkV1(
                claim_id=conflict_claim.id,
                evidence_id="ev_contradict",
                support_type="contradicts",
                confidence=0.9,
            ),
            source_role="independent_secondary",
            source_cluster_id="evidence_cluster_contradict",
        ),
    )
    conflict_state = build_research_state(
        mode="active",
        questions=(question,),
        claims=(conflict_claim,),
        evidence=conflict_evidence,
        evidence_links=conflict_links,
        source_clusters=(
            EvidenceCluster(
                id="evidence_cluster_support",
                evidence_ids=("ev_support",),
            ),
            EvidenceCluster(
                id="evidence_cluster_contradict",
                evidence_ids=("ev_contradict",),
            ),
        ),
        gaps=(),
        conflict_gaps=(
            ConflictGap(
                id="conflict_1",
                claim_id=conflict_claim.id,
                supporting_evidence_ids=("ev_support",),
                contradicting_evidence_ids=("ev_contradict",),
                state="open",
            ),
        ),
        budget=ResearchBudget(
            max_candidates=20,
            max_reads=6,
            reads_used=4,
            soft_timeout_seconds=45,
            hard_timeout_seconds=60,
            max_total_chars=16000,
        ),
        reference_date="2026-08-30",
        known_evidence_ids=("ev_support", "ev_contradict"),
    )
    conflict_physical, _ = _fair_read_plan(
        conflict_state,
        {conflict_claim.id: (ranked("conflict-source", "cluster_C", 1),)},
    )
    assert {item["candidate_id"] for item in conflict_physical} == {
        "conflict-source"
    }

    major_claim = claim("claim_major", "major")
    major_state = build_research_state(
        mode="active",
        questions=(question,),
        claims=(major_claim,),
        evidence=(),
        evidence_links=(),
        source_clusters=(),
        gaps=(),
        conflict_gaps=(),
        budget=ResearchBudget(
            max_candidates=20,
            max_reads=8,
            soft_timeout_seconds=45,
            hard_timeout_seconds=60,
            max_total_chars=16000,
        ),
        reference_date="2026-08-30",
        known_evidence_ids=(),
    )
    major_physical, major_targets = _fair_read_plan(
        major_state,
        {
            major_claim.id: (
                ranked("Q", "cluster_X", 1),
                ranked("R", "cluster_Y", 2),
            )
        },
        covered_cluster_ids_by_claim={major_claim.id: {"cluster_X"}},
    )
    assert {item["candidate_id"] for item in major_physical} == {"R"}
    assert {item["candidate_id"] for item in major_targets} == {"R"}


def _load_smoke_module() -> Any:
    import importlib.util

    path = Path(__file__).resolve().parents[1] / "tools" / "run_research_active_smoke.py"
    spec = importlib.util.spec_from_file_location("run_research_active_smoke", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_smoke_searxng_success_requires_ok_results() -> None:
    """B5-H6: attempted is not success; only a successful result-bearing
    searxng outcome proves the real-SearXNG smoke ran against SearXNG."""
    module = _load_smoke_module()

    success = [
        {
            "provider_audit": {
                "provider_outcomes": [
                    {"provider": "searxng", "status": "ok", "result_count": 3}
                ]
            }
        }
    ]
    assert module._searxng_success(success) is True

    failed_but_attempted = [
        {
            "provider_audit": {
                "provider_outcomes": [
                    {"provider": "searxng", "status": "failed", "result_count": 0},
                    {"provider": "bing_rss", "status": "ok", "result_count": 5},
                ]
            }
        }
    ]
    assert module._searxng_success(failed_but_attempted) is False

    ok_but_empty = [
        {
            "provider_audit": {
                "provider_outcomes": [
                    {"provider": "searxng", "status": "ok", "result_count": 0}
                ]
            }
        }
    ]
    assert module._searxng_success(ok_but_empty) is False

def test_reusable_candidates_obey_scheduler_eligibility() -> None:
    """B5-H9: reusable candidates obey the same eligibility predicate as fresh.

    Claim B ranks the already-read shared candidate X as lead_only without any
    provenance-grade gain signal: it must not be bound to claim B even though
    its physical read exists, while a legitimate fresh Y is still selected and
    a lead_only candidate carrying a gain signal (Z) is not rejected.
    """
    from src.application.active_research_runtime import _fair_read_plan
    from src.web.research.candidate_assessment import CandidateSemanticAssessment
    from src.web.research.candidate_pool import CandidatePoolItem
    from src.web.research.candidate_ranking import RankedCandidate
    from src.web.research.contracts import (
        EvidenceRequirement,
        ResearchClaim,
        ResearchQuestion,
    )

    question = ResearchQuestion(id="q1", question_surface="question")

    def claim(claim_id: str) -> ResearchClaim:
        return ResearchClaim(
            id=claim_id,
            question_id="q1",
            text="claim",
            kind="factual",
            priority="critical",
            state="pending",
            evidence_requirement=EvidenceRequirement(),
        )

    def ranked(
        candidate_id: str,
        cluster_id: str,
        rank: int,
        *,
        eligibility: str = "eligible",
        signals: tuple[str, ...] = ("new_primary",),
    ) -> RankedCandidate:
        candidate = CandidatePoolItem(
            id=candidate_id,
            canonical_url=f"https://x.example/{candidate_id}",
            url=f"https://x.example/{candidate_id}",
            title=candidate_id,
            snippet="",
            source="",
            published_at="",
            query_ids=("q1",),
            intents=(),
            providers=("searxng",),
            first_seen_rank=rank,
        )
        assessment = CandidateSemanticAssessment(
            candidate_id=candidate_id,
            relevance="answer_relevant",
            relevance_confidence=0.9,
            source_role="primary",
            source_role_confidence=0.9,
            cluster_id=cluster_id,
            expected_gain_signals=signals,
            freshness_score=0.5,
            estimated_read_cost=1.0,
        )
        return RankedCandidate(
            candidate=candidate,
            assessment=assessment,
            rank=rank,
            eligibility=eligibility,
            reason_codes=(),
            new_cluster=False,
            expected_information_gain=1,
        )

    state = build_research_state(
        mode="active",
        questions=(question,),
        claims=(claim("claim_A"), claim("claim_B")),
        evidence=(),
        evidence_links=(),
        source_clusters=(),
        gaps=(),
        conflict_gaps=(),
        budget=ResearchBudget(
            max_candidates=20,
            max_reads=8,
            soft_timeout_seconds=45,
            hard_timeout_seconds=60,
            max_total_chars=16000,
        ),
        reference_date="2026-08-28",
        known_evidence_ids=(),
    )
    rankings = {
        "claim_A": (ranked("X", "cluster_X", 1),),
        "claim_B": (
            ranked("X", "cluster_X", 1, eligibility="lead_only", signals=()),
            ranked("Y", "cluster_Y", 2),
            ranked("Z", "cluster_Z", 3, eligibility="lead_only", signals=("new_primary",)),
        ),
    }

    physical, targets = _fair_read_plan(state, rankings)

    b_pairs = {
        (item["candidate_id"], item["cluster_id"])
        for item in targets
        if item["claim_id"] == "claim_B"
    }
    # H9: X is lead_only without gain signals, so it must not be bound to
    # claim B even though it was already physically read for claim A.
    assert ("X", "cluster_X") not in b_pairs
    # The legitimate fresh candidate fills the wave; lead_only with a gain
    # signal (Z) stays schedulable in the next wave.
    assert ("Y", "cluster_Y") in b_pairs
    assert ("Z", "cluster_Z") in b_pairs
    assert "X" not in {item["candidate_id"] for item in physical if item["claim_id"] == "claim_B"}


@pytest.mark.parametrize(
    ("eligibility", "signals"),
    [
        ("rejected", ()),
        ("lead_only", ()),
    ],
)
def test_restored_read_binding_rechecks_per_claim_eligibility(
    eligibility: str,
    signals: tuple[str, ...],
) -> None:
    from src.web.research.candidate_assessment import CandidateSemanticAssessment
    from src.web.research.candidate_pool import CandidatePoolItem
    from src.web.research.candidate_ranking import RankedCandidate

    candidate = CandidatePoolItem(
        id="shared",
        canonical_url="https://x.example/shared",
        url="https://x.example/shared",
        title="shared",
        snippet="",
        source="",
        published_at="",
        query_ids=("q1",),
        intents=(),
        providers=("searxng",),
        first_seen_rank=1,
    )

    def ranked(
        *,
        role: str,
        cluster: str,
        item_eligibility: str,
        item_signals: tuple[str, ...],
    ) -> RankedCandidate:
        return RankedCandidate(
            candidate=candidate,
            assessment=CandidateSemanticAssessment(
                candidate_id=candidate.id,
                relevance="answer_relevant",
                relevance_confidence=0.9,
                source_role=role,
                source_role_confidence=0.9,
                cluster_id=cluster,
                expected_gain_signals=item_signals,
                freshness_score=0.5,
                estimated_read_cost=1.0,
            ),
            rank=1,
            eligibility=item_eligibility,
            reason_codes=(),
            new_cluster=False,
            expected_information_gain=1,
        )

    restored = _restore_completed_read_targets(
        [],
        completed_read_ids={candidate.id},
        rankings={
            "claim_A": (
                ranked(
                    role="primary",
                    cluster="cluster_A",
                    item_eligibility="eligible",
                    item_signals=("new_primary",),
                ),
            ),
            "claim_B": (
                ranked(
                    role="community",
                    cluster="cluster_B",
                    item_eligibility=eligibility,
                    item_signals=signals,
                ),
            ),
        },
    )

    assert restored == [
        {
            "candidate_id": "shared",
            "claim_id": "claim_A",
            "cluster_id": "cluster_A",
            "source_role": "primary",
        }
    ]


def test_major_claim_saturates_after_two_no_gain_waves(tmp_path: Any) -> None:
    """Frozen rule: non-critical claims saturate after exactly two no-gain
    waves - the optional third batch is a critical/conflict privilege only."""
    question = ResearchQuestion(id="question_1", question_surface="Compare releases")
    requirement = EvidenceRequirement(
        source_roles=("primary", "independent_secondary"),
        min_independent_sources=2,
        requires_primary_source=True,
    )
    claim = ResearchClaim(
        id="claim_major",
        question_id=question.id,
        text="Alpha framework current release",
        kind="factual",
        priority="major",
        state="searching",
        evidence_requirement=requirement,
    )
    gap = EvidenceGap(
        id="gap_major",
        claim_id=claim.id,
        gap_type="missing_evidence",
        desired_source_role="primary",
        priority="major",
        state="open",
    )
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
        reference_date="2026-08-28",
        known_evidence_ids=(),
    )
    context = attach_claim_engine_state(_active_context(), state, known_evidence_ids=())
    repository = _TrackingRepository(RuntimeDatabase(tmp_path / "active-major.sqlite"))
    run = repository.create(
        WebLookupRun(
            id="run_active_major_saturation",
            query="Alpha framework current release",
            stage="planned",
            status="pending",
            research_context=context,
            max_items=5,
        )
    )
    search = _EmptySearchBackend()
    client = _StructuredClient()

    completed = _service(repository, client, search_backend=search).execute(
        run.id,
        raise_on_error=True,
    )

    assert completed.status == "partial"
    assert completed.stop_reason == "evidence_saturated"
    cursor = ResearchRuntimeCursor.from_dict(
        completed.research_context[CLAIM_ENGINE_RUNTIME_CONTEXT_KEY]
    )
    assert cursor.wave_index == 2
    assert cursor.no_gain_batches_by_claim == {"claim_major": 2}
    assert cursor.no_gain_batches_by_gap == {"gap_major": 2}
    assert len(cursor.gain_history) == 2


def test_deferred_context_gap_does_not_block_critical_saturation(tmp_path: Any) -> None:
    question = ResearchQuestion(id="question_1", question_surface="Compare releases")
    requirement = EvidenceRequirement(
        source_roles=("primary", "independent_secondary"),
        min_independent_sources=2,
        requires_primary_source=True,
    )
    critical = ResearchClaim(
        id="claim_critical",
        question_id=question.id,
        text="Alpha framework current release",
        kind="factual",
        priority="critical",
        state="searching",
        evidence_requirement=requirement,
    )
    context_claim = ResearchClaim(
        id="claim_context",
        question_id=question.id,
        text="Historical background",
        kind="factual",
        priority="context",
        state="searching",
        evidence_requirement=requirement,
    )
    gaps = (
        EvidenceGap(
            id="gap_critical",
            claim_id=critical.id,
            gap_type="missing_evidence",
            desired_source_role="primary",
            priority="critical",
            state="open",
        ),
        EvidenceGap(
            id="gap_context",
            claim_id=context_claim.id,
            gap_type="missing_context",
            desired_source_role="independent_secondary",
            priority="context",
            state="open",
        ),
    )
    state = build_research_state(
        mode="active",
        questions=(question,),
        claims=(critical, context_claim),
        evidence=(),
        evidence_links=(),
        source_clusters=(),
        gaps=gaps,
        conflict_gaps=(),
        budget=ResearchBudget(
            max_candidates=20,
            max_reads=8,
            soft_timeout_seconds=45,
            hard_timeout_seconds=60,
            max_total_chars=16000,
        ),
        reference_date="2026-08-30",
        known_evidence_ids=(),
    )
    context = attach_claim_engine_state(_active_context(), state, known_evidence_ids=())
    repository = _TrackingRepository(RuntimeDatabase(tmp_path / "active-context-gap.sqlite"))
    run = repository.create(
        WebLookupRun(
            id="run_active_context_gap_saturation",
            query="Alpha framework current release",
            stage="planned",
            status="pending",
            research_context=context,
            max_items=5,
        )
    )
    search = _EmptySearchBackend()

    completed = _service(
        repository,
        _StructuredClient(),
        search_backend=search,
    ).execute(run.id, raise_on_error=True)

    assert completed.status == "partial"
    assert completed.stop_reason == "evidence_saturated"
    cursor = ResearchRuntimeCursor.from_dict(
        completed.research_context[CLAIM_ENGINE_RUNTIME_CONTEXT_KEY]
    )
    assert cursor.wave_index == 3
    assert cursor.no_gain_batches_by_claim == {"claim_critical": 3}
    assert cursor.no_gain_batches_by_gap == {"gap_critical": 3}
    assert cursor.active_gap_ids == ("gap_critical",)
    final_state = _dispatch_state(completed)
    assert final_state is not None
    deferred = next(gap for gap in final_state.gaps if gap.id == "gap_context")
    assert deferred.state == "open"


def test_wave_limit_exhausted_is_not_fake_saturation(tmp_path: Any) -> None:
    """P1: hitting the MAX_RESEARCH_WAVES ceiling must persist the honest
    wave_limit_exhausted reason, never evidence_saturated or
    evidence_budget_exhausted (regression for the truth bug).

    The claim is critical (saturation threshold 3), so one no-gain wave leaves
    it unsaturated; monkeypatching MAX_RESEARCH_WAVES=1 forces the ceiling to
    terminate while the claim genuinely has no_gain_batches == 1.
    """
    import src.application.active_research_runtime as art_mod

    question = ResearchQuestion(id="question_1", question_surface="Compare releases")
    requirement = EvidenceRequirement(
        source_roles=("primary", "independent_secondary"),
        min_independent_sources=2,
        requires_primary_source=True,
    )
    claim = ResearchClaim(
        id="claim_wave_limit",
        question_id=question.id,
        text="Alpha framework current release",
        kind="factual",
        priority="critical",
        state="searching",
        evidence_requirement=requirement,
    )
    gap = EvidenceGap(
        id="gap_wave_limit",
        claim_id=claim.id,
        gap_type="missing_evidence",
        desired_source_role="primary",
        priority="critical",
        state="open",
    )
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
        reference_date="2026-08-28",
        known_evidence_ids=(),
    )
    context = attach_claim_engine_state(_active_context(), state, known_evidence_ids=())
    repository = _TrackingRepository(RuntimeDatabase(tmp_path / "active-wavelimit.sqlite"))
    run = repository.create(
        WebLookupRun(
            id="run_active_wave_limit",
            query="Alpha framework current release",
            stage="planned",
            status="pending",
            research_context=context,
            max_items=5,
        )
    )
    search = _EmptySearchBackend()
    client = _StructuredClient()

    original_limit = art_mod.MAX_RESEARCH_WAVES
    art_mod.MAX_RESEARCH_WAVES = 1
    try:
        completed = _service(repository, client, search_backend=search).execute(
            run.id,
            raise_on_error=True,
        )
    finally:
        art_mod.MAX_RESEARCH_WAVES = original_limit

    assert completed.status == "partial"
    assert completed.stop_reason == "wave_limit_exhausted"
    assert completed.stop_reason != "evidence_saturated"
    assert completed.stop_reason != "evidence_budget_exhausted"
    assert completed.answer_confidence == "none"  # empty evidence
    cursor = ResearchRuntimeCursor.from_dict(
        completed.research_context[CLAIM_ENGINE_RUNTIME_CONTEXT_KEY]
    )
    assert cursor.wave_index == 1
    assert cursor.no_gain_batches_by_claim == {"claim_wave_limit": 1}
    from src.web.research.evidence_gain import SaturationState, saturated_claim_ids

    assert "claim_wave_limit" not in saturated_claim_ids(
        SaturationState(no_gain_batches_by_claim=dict(cursor.no_gain_batches_by_claim))
    )


def test_hard_budget_precedes_wave_limit_after_external_call(tmp_path: Any) -> None:
    import src.application.active_research_runtime as art_mod

    class _Clock:
        def __init__(self) -> None:
            self.value = 0.0

        def __call__(self) -> float:
            return self.value

    clock = _Clock()

    class _DeadlineCrossingSearch(_EmptySearchBackend):
        def search_exact(
            self,
            query: str,
            *,
            max_results: int = 5,
        ) -> dict[str, Any]:
            result = super().search_exact(query, max_results=max_results)
            clock.value = 61.0
            return result

    state = _two_gap_state()
    context = attach_claim_engine_state(_active_context(), state, known_evidence_ids=())
    repository = _TrackingRepository(RuntimeDatabase(tmp_path / "active-hard-budget.sqlite"))
    run = repository.create(
        WebLookupRun(
            id="run_active_hard_budget_precedence",
            query="Compare releases",
            stage="planned",
            status="pending",
            research_context=context,
            max_items=5,
        )
    )

    original_limit = art_mod.MAX_RESEARCH_WAVES
    art_mod.MAX_RESEARCH_WAVES = 1
    try:
        completed = _service(
            repository,
            _StructuredClient(),
            search_backend=_DeadlineCrossingSearch(),
            monotonic=clock,
        ).execute(run.id, raise_on_error=True)
    finally:
        art_mod.MAX_RESEARCH_WAVES = original_limit

    assert completed.status == "partial"
    assert completed.stop_reason == "evidence_budget_exhausted"
    assert completed.stop_reason != "wave_limit_exhausted"
    assert completed.stop_reason != "evidence_saturated"
    hard_budget_cursor = ResearchRuntimeCursor.from_dict(
        completed.research_context[CLAIM_ENGINE_RUNTIME_CONTEXT_KEY]
    )
    assert all(
        failure.code != "runtime_internal_failed"
        for failure in hard_budget_cursor.failures
    )


def test_resume_restores_missing_claim_binding_after_extraction_crash(
    tmp_path: Any,
) -> None:
    """P1-C batch 2: a shared source read once for two claims, with claim A's
    extraction completed and claim B's crashed, must restore the (candidate,
    claim B) binding on resume - never drop it because the candidate's
    physical read already completed."""
    repository = _TrackingRepository(RuntimeDatabase(tmp_path / "active-multiclaim-crash.sqlite"))
    run = repository.create(
        WebLookupRun(
            id="run_active_multiclaim_crash",
            query="What is the verified current release date?",
            stage="planned",
            status="pending",
            research_context=_active_context(),
            max_items=5,
        )
    )

    class _CrashOnSecondExtraction:
        def __init__(self, inner: Any) -> None:
            self._inner = inner
            self.calls = 0

        def extract(self, **kwargs: Any) -> Any:
            self.calls += 1
            result = self._inner.extract(**kwargs)
            if self.calls == 2:
                raise RuntimeError("simulated extraction crash")
            return result

    from src.web.research.model_gateway import ResearchModelGateway as _RMG
    from src.web.research.active_semantics import RuntimeEvidenceExtractor as _REE

    crashing_model = _RMG(client=_StructuredClient(claims_count=2), model_name="test-model", timeout_seconds=20)
    crashing_extractor = _CrashOnSecondExtraction(_REE(crashing_model))

    def crashing_runtime_factory(
        repo: WebLookupRepository,
        gateway: ActiveResearchGateway,
    ) -> ActiveResearchRuntimeExecutor:
        return ActiveResearchRuntimeExecutor(
            repo,
            gateway,
            model_gateway=crashing_model,
            evidence_extractor=crashing_extractor,
        )

    service = ClaimEngineDispatchWebLookupService(
        repository,
        active_gateway_factory=lambda: ActiveResearchGateway(
            search_backend=_ProvenanceSearchBackend(),
            read_gateway=_ReadGateway(),
        ),
        active_runtime_factory=crashing_runtime_factory,
    )

    with pytest.raises(RuntimeError, match="simulated extraction crash"):
        service.execute(run.id, raise_on_error=True)

    resumed_client = _StructuredClient(claims_count=2)
    resumed = _service(repository, resumed_client, search_backend=_ProvenanceSearchBackend()).execute(
        run.id, raise_on_error=True
    )

    assert resumed.status in {"completed", "partial"}
    state = _dispatch_state(repository.get(run.id))
    assert state is not None
    linked_claims = {link.claim_id for link in state.evidence_links}
    assert len(linked_claims) == 2
    shared_record = next(
        item
        for item in resumed.selected_sources
        if len((item.get("extractions") or {})) >= 2
    )
    assert set((shared_record.get("extractions") or {})) == linked_claims

    # Logical call identity must not drift across the crash/resume boundary:
    # the crashed extraction re-runs under the SAME logical_call_id with
    # attempt 2 (the wrapper crash lands in the executor exception fallback,
    # so the durable failure is canonical runtime_internal_failed with the
    # Python type in exception_type; a process-level crash produces a
    # stage-specific canonical code with interrupted_unknown detail instead).
    # Physical call ids stay unique.
    cursor = ResearchRuntimeCursor.from_dict(
        resumed.research_context[CLAIM_ENGINE_RUNTIME_CONTEXT_KEY]
    )
    assert any(
        failure.code == "runtime_internal_failed"
        and failure.exception_type == "RuntimeError"
        for failure in cursor.failures
    )
    extraction_calls = [
        call
        for call in cursor.model_calls
        if "research_evidence_extract" in call.logical_call_id
    ]
    attempts_by_logical: dict[str, list[int]] = {}
    for call in extraction_calls:
        attempts_by_logical.setdefault(call.logical_call_id, []).append(call.attempt)
    retried = [
        (logical, attempts)
        for logical, attempts in attempts_by_logical.items()
        if attempts == [1, 2]
    ]
    assert retried, f"expected an extraction retried as attempt 2: {attempts_by_logical}"
    assert len({call.call_id for call in cursor.model_calls}) == len(
        cursor.model_calls
    )

def test_assessment_identity_stable_across_crash_resume(tmp_path: Any) -> None:
    """P1-C batch 2: an assessment that crashes after the provider call but
    before the semantic result is durable must resume under the SAME logical
    call identity with attempt 2 (candidate fingerprint canonical)."""
    repository = _TrackingRepository(RuntimeDatabase(tmp_path / "active-assess-crash.sqlite"))
    run = repository.create(
        WebLookupRun(
            id="run_active_assess_crash",
            query="What is the verified current release date?",
            stage="planned",
            status="pending",
            research_context=_active_context(),
            max_items=5,
        )
    )

    class _CrashOnFirstAssessment:
        def __init__(self, inner: Any) -> None:
            self._inner = inner
            self.calls = 0

        def assess(self, **kwargs: Any) -> Any:
            self.calls += 1
            result = self._inner.assess(**kwargs)
            if self.calls == 1:
                raise RuntimeError("simulated assessment crash")
            return result

    from src.web.research.model_gateway import ResearchModelGateway as _RMG2
    from src.web.research.active_semantics import RuntimeCandidateAssessor as _RCA

    crashing_model = _RMG2(
        client=_StructuredClient(), model_name="test-model", timeout_seconds=20
    )
    crashing_assessor = _CrashOnFirstAssessment(_RCA(crashing_model))

    def crashing_runtime_factory(
        repo: WebLookupRepository,
        gateway: ActiveResearchGateway,
    ) -> ActiveResearchRuntimeExecutor:
        return ActiveResearchRuntimeExecutor(
            repo,
            gateway,
            model_gateway=crashing_model,
            candidate_assessor=crashing_assessor,
        )

    service = ClaimEngineDispatchWebLookupService(
        repository,
        active_gateway_factory=lambda: ActiveResearchGateway(
            search_backend=_SearchBackend(),
            read_gateway=_ReadGateway(),
        ),
        active_runtime_factory=crashing_runtime_factory,
    )

    with pytest.raises(RuntimeError, match="simulated assessment crash"):
        service.execute(run.id, raise_on_error=True)

    resumed = _service(repository, _StructuredClient()).execute(
        run.id,
        raise_on_error=True,
    )
    assert resumed.status in {"completed", "partial"}

    cursor = ResearchRuntimeCursor.from_dict(
        resumed.research_context[CLAIM_ENGINE_RUNTIME_CONTEXT_KEY]
    )
    assessment_calls = [
        call
        for call in cursor.model_calls
        if "research_candidate_assessment" in call.logical_call_id
    ]
    attempts_by_logical: dict[str, list[int]] = {}
    for call in assessment_calls:
        attempts_by_logical.setdefault(call.logical_call_id, []).append(call.attempt)
    retried = [
        attempts
        for attempts in attempts_by_logical.values()
        if attempts == [1, 2]
    ]
    assert retried, f"expected assessment retried as attempt 2: {attempts_by_logical}"
    assert len({call.call_id for call in cursor.model_calls}) == len(
        cursor.model_calls
    )


def test_resume_after_exhausted_assessment_stays_claim_local(tmp_path: Any) -> None:
    """Two durable failed attempts must resume as claim-unavailable/no-gain.

    The same logical assessment is never called a third time and its exhausted
    ceiling must not escape into the whole-run active_runtime_unavailable path.
    """

    class _AssessmentFailingClient(_StructuredClient):
        def create(self, **kwargs: Any) -> Any:
            system = str(kwargs["messages"][0]["content"])
            if "search candidates" in system:
                self.calls.append(kwargs)
                raise RuntimeError("simulated assessment provider failure")
            return super().create(**kwargs)

    class _CrashAfterAssessmentUnavailableRepository(_TrackingRepository):
        def __init__(self, database: RuntimeDatabase) -> None:
            super().__init__(database)
            self.crashed = False

        def checkpoint(self, run_id: str, **kwargs: Any) -> WebLookupRun:
            persisted = super().checkpoint(run_id, **kwargs)
            if self.crashed:
                return persisted
            cursor = ResearchRuntimeCursor.from_dict(
                persisted.research_context[CLAIM_ENGINE_RUNTIME_CONTEXT_KEY]
            )
            exhausted = [
                call
                for call in cursor.model_calls
                if "research_candidate_assessment" in call.logical_call_id
                and call.status == "attempt_failed"
            ]
            if len(exhausted) == 2 and any(
                failure.phase == "assessing"
                and failure.code == "model_attempts_exhausted"
                for failure in cursor.failures
            ):
                self.crashed = True
                assert persisted.active_operation_id
                self.fail(
                    run_id,
                    "simulated process exit after assessment exhaustion",
                    operation_id=persisted.active_operation_id,
                )
                raise RuntimeError("simulated assessment exhaustion crash")
            return persisted

    repository = _CrashAfterAssessmentUnavailableRepository(
        RuntimeDatabase(tmp_path / "active-assessment-exhausted.sqlite")
    )
    run = repository.create(
        WebLookupRun(
            id="run_active_assessment_exhausted",
            query="What is the verified current release date?",
            stage="planned",
            status="pending",
            research_context=_active_context(),
            max_items=5,
        )
    )
    failing_client = _AssessmentFailingClient()
    with pytest.raises(RuntimeError, match="assessment exhaustion crash"):
        _service(repository, failing_client).execute(run.id, raise_on_error=True)

    crashed = repository.get(run.id)
    assert crashed is not None
    crashed_cursor = ResearchRuntimeCursor.from_dict(
        crashed.research_context[CLAIM_ENGINE_RUNTIME_CONTEXT_KEY]
    )
    exhausted_calls = [
        call
        for call in crashed_cursor.model_calls
        if "research_candidate_assessment" in call.logical_call_id
    ]
    assert [call.attempt for call in exhausted_calls] == [1, 2]
    exhausted_logical_call_id = exhausted_calls[0].logical_call_id
    assert all(
        call.logical_call_id == exhausted_logical_call_id
        for call in exhausted_calls
    )

    resumed = _service(repository, _StructuredClient()).execute(
        run.id,
        raise_on_error=True,
    )

    assert resumed.stop_reason != "active_runtime_unavailable"
    resumed_cursor = ResearchRuntimeCursor.from_dict(
        resumed.research_context[CLAIM_ENGINE_RUNTIME_CONTEXT_KEY]
    )
    same_logical_calls = [
        call
        for call in resumed_cursor.model_calls
        if call.logical_call_id == exhausted_logical_call_id
    ]
    assert [call.attempt for call in same_logical_calls] == [1, 2]
    assert any(
        failure.code == "model_attempts_exhausted"
        and failure.item_id == crashed_cursor.failures[-1].item_id
        for failure in resumed_cursor.failures
    )
    assert len({call.call_id for call in resumed_cursor.model_calls}) == len(
        resumed_cursor.model_calls
    )

def test_extraction_attempt_exhaustion_crash_is_claim_local(tmp_path: Any) -> None:
    """P1 round-4: process death right after extraction attempt 2 finished
    (durable state = attempt 1 audit + attempt 2 inflight, nothing more) must
    resume as claim-local extractor_failed - never a third physical attempt,
    never a whole-runtime active_runtime_unavailable."""

    class _SimulatedProcessDeath(BaseException):
        pass

    repository = _TrackingRepository(RuntimeDatabase(tmp_path / "active-extract-exhaust.sqlite"))
    run = repository.create(
        WebLookupRun(
            id="run_active_extract_exhaust",
            query="What is the verified current release date?",
            stage="planned",
            status="pending",
            research_context=_active_context(),
            max_items=5,
        )
    )

    from src.web.research.model_gateway import ResearchModelGateway as _RMG3
    from src.web.research.active_semantics import RuntimeEvidenceExtractor as _REE3

    class _PerAttemptClient:
        """Extraction attempt 1 is malformed (strict parser rejects it), every
        later call is valid - so the gateway retries the target extraction
        exactly once."""

        def __init__(self, malformed: _StructuredClient, healthy: _StructuredClient) -> None:
            self.chat = SimpleNamespace(completions=self)
            self._malformed = malformed
            self._healthy = healthy
            self.extraction_attempts = 0

        def with_options(self, **kwargs: Any) -> "_PerAttemptClient":
            self._malformed.with_options(**kwargs)
            self._healthy.with_options(**kwargs)
            return self

        def create(self, **kwargs: Any) -> Any:
            system = str(kwargs["messages"][0]["content"])
            if system.startswith("You extract one bounded evidence link"):
                self.extraction_attempts += 1
                if self.extraction_attempts == 1:
                    return self._malformed.create(**kwargs)
            return self._healthy.create(**kwargs)

    crash_model = _RMG3(
        client=_PerAttemptClient(
            _StructuredClient(claims_count=2, malformed_extraction=True),
            _StructuredClient(claims_count=2),
        ),
        model_name="test-model",
        timeout_seconds=20,
    )

    class _CrashAfterAttemptTwoFinished:
        def __init__(self, inner: Any) -> None:
            self._inner = inner
            self.crashed = False

        def extract(self, **kwargs: Any) -> Any:
            original_finished = kwargs.get("on_attempt_finished")

            def crash_finished(audit: Any) -> None:
                if original_finished is not None:
                    original_finished(audit)
                if not self.crashed and getattr(audit, "attempt", None) == 2:
                    self.crashed = True
                    raise _SimulatedProcessDeath(
                        "simulated process death after extraction attempt 2 finished"
                    )

            return self._inner.extract(
                **{**kwargs, "on_attempt_finished": crash_finished}
            )

    crash_extractor = _CrashAfterAttemptTwoFinished(_REE3(crash_model))

    def crash_runtime_factory(
        repo: WebLookupRepository,
        gateway: ActiveResearchGateway,
    ) -> ActiveResearchRuntimeExecutor:
        return ActiveResearchRuntimeExecutor(
            repo,
            gateway,
            model_gateway=crash_model,
            evidence_extractor=crash_extractor,
        )

    crash_service = ClaimEngineDispatchWebLookupService(
        repository,
        active_gateway_factory=lambda: ActiveResearchGateway(
            search_backend=_SearchBackend(),
            read_gateway=_ReadGateway(),
        ),
        active_runtime_factory=crash_runtime_factory,
    )

    # Execute 1: attempt 1 malformed -> gateway retries attempt 2 (valid) ->
    # on_attempt_finished(attempt 2) finishes the in-memory model call and then
    # raises a BaseException, which no except Exception checkpoint persists.
    # The durable window is exactly: attempt 1 audit + attempt 2 inflight.
    with pytest.raises(BaseException, match="simulated process death"):
        crash_service.execute(run.id, raise_on_error=True)

    # Assertion 1: crash 前 durable inflight == target attempt 2, attempt 1
    # audit durable, attempt 2 audit NOT durable, binding not yet failed.
    crashed_run = repository.get(run.id)
    crashed_cursor = ResearchRuntimeCursor.from_dict(
        crashed_run.research_context[CLAIM_ENGINE_RUNTIME_CONTEXT_KEY]
    )
    assert crashed_cursor.inflight_model_call is not None
    assert crashed_cursor.inflight_model_call.attempt == 2
    target_logical_id = crashed_cursor.inflight_model_call.logical_call_id
    assert target_logical_id.startswith("research_evidence_extract:")
    crashed_extraction_calls = [
        call
        for call in crashed_cursor.model_calls
        if call.logical_call_id == target_logical_id
    ]
    assert [call.attempt for call in crashed_extraction_calls] == [1]
    assert not any(
        isinstance(prior, Mapping) and prior.get("status") == "extractor_failed"
        for record in crashed_run.selected_sources
        for prior in (record.get("extractions") or {}).values()
    )

    # Simulate the operator restarting the worker after the process died: mark
    # the crashed operation stale so begin_operation accepts the resume via
    # recoverable_running (a BaseException never runs the dispatch cleanup).
    with repository.database.connect() as connection:
        row = connection.execute(
            "SELECT research_context FROM web_lookup_runs WHERE id = ?",
            (run.id,),
        ).fetchone()
        assert row is not None
        stale_context = loads(str(row[0]))
        stale_context.setdefault("operation", {})["active_operation_started_at"] = (
            "2000-01-01T00:00:00+00:00"
        )
        connection.execute(
            "UPDATE web_lookup_runs SET research_context = ? WHERE id = ?",
            (_json_dumps(stale_context), run.id),
        )

    # Execute 2 (resume): recover_interrupted_model_attempt -> attempt 2 ->
    # interrupted_unknown -> the extraction loop refuses a third attempt and
    # the round-4 local catch settles the binding claim-local.
    resumed_client = _StructuredClient(claims_count=2)
    resumed = _service(
        repository,
        resumed_client,
        search_backend=_SearchBackend(),
    ).execute(run.id, raise_on_error=True)

    resumed_cursor = ResearchRuntimeCursor.from_dict(
        resumed.research_context[CLAIM_ENGINE_RUNTIME_CONTEXT_KEY]
    )
    # Assertion 2: resume 后存在 interrupted_unknown(target attempt 2)。
    recovered_item = f"{target_logical_id}:attempt:2"
    assert [
        failure.item_id
        for failure in resumed_cursor.failures
            if failure.code == "extraction_failed"
            and failure.detail == "interrupted_unknown"
            and failure.item_id == recovered_item
    ] == [recovered_item]

    # Assertion 3: 不存在 attempt 3（model_calls 无 target attempt 2/3 审计、
    # failures 无 :attempt:3、物理 extraction 调用不再发生）。
    target_audits = [
        call
        for call in resumed_cursor.model_calls
        if call.logical_call_id == target_logical_id
    ]
    assert [call.attempt for call in target_audits] == [1]
    assert not any(call.attempt >= 3 for call in target_audits)
    assert not any(
        failure.item_id.startswith(f"{target_logical_id}:attempt:3")
        for failure in resumed_cursor.failures
    )


    # Assertion 4: target binding extractor_failed / model_call_attempts_exhausted。
    resumed_state = _dispatch_state(resumed)
    assert resumed_state is not None
    failed_bindings = [
        (claim_id, prior)
        for record in resumed.selected_sources
        for claim_id, prior in (record.get("extractions") or {}).items()
        if isinstance(prior, Mapping)
        and prior.get("reason") == "model_call_attempts_exhausted"
    ]
    assert len(failed_bindings) == 1
    assert failed_bindings[0][1] == {
        "status": "extractor_failed",
        "reason": "model_call_attempts_exhausted",
    }

    # Assertion 5: 另一 claim/binding 成功继续（该 (candidate, claim) 对不再
    # 被物理提取，其他 binding 正常 eligible 并产生 evidence）。
    target_claim_id = target_logical_id.split(":")[2]
    target_candidate_id = target_logical_id.split(":")[3]
    physical_extractions = [
        call
        for call in resumed_client.calls
        if str(call["messages"][0]["content"]).startswith(
            "You extract one bounded evidence link"
        )
    ]
    assert physical_extractions
    assert not any(
        loads(str(call["messages"][1]["content"]))["candidate_id"]
        == target_candidate_id
        and loads(str(call["messages"][1]["content"]))["claim_id"]
        == target_claim_id
        for call in physical_extractions
    )
    assert any(
        isinstance(prior, Mapping) and prior.get("status") == "eligible"
        for record in resumed.selected_sources
        for prior in (record.get("extractions") or {}).values()
    )
    linked_claims = {link.claim_id for link in resumed_state.evidence_links}
    assert linked_claims

    # Assertion 6: terminal stop_reason != active_runtime_unavailable。
    assert resumed.status in {"completed", "partial"}
    assert resumed.stop_reason != "active_runtime_unavailable"
def test_covered_clusters_are_cumulative_across_waves(
    tmp_path: Any,
) -> None:
    """P2 round-4: covered-cluster truth must be run-level cumulative, never
    the previous wave's read plan (which is overwritten every wave).

    W1 reads wave-1.example/a (cluster X), W2 reads wave-2.example/a
    (cluster Y), W3 offers wave-1.example/b (rank 1, repeat cluster X) and
    wave-3.example/a (rank 2, fresh cluster Z). The scheduler must backfill Z -
    the repeated-cluster candidate never enters a physical read again.
    """
    import src.application.active_research_runtime as art_mod
    from src.web.research.gap_planner import GapSearchIntent

    question = ResearchQuestion(id="question_1", question_surface="Compare releases")
    requirement = EvidenceRequirement(
        source_roles=("primary", "independent_secondary"),
        min_independent_sources=2,
        requires_primary_source=True,
    )
    claim = ResearchClaim(
        id="claim_major",
        question_id=question.id,
        text="Alpha framework current release",
        kind="factual",
        priority="major",
        state="searching",
        evidence_requirement=requirement,
    )
    gap = EvidenceGap(
        id="gap_major",
        claim_id=claim.id,
        gap_type="missing_evidence",
        desired_source_role="primary",
        priority="major",
        state="open",
    )
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
        reference_date="2026-08-28",
        known_evidence_ids=(),
    )
    context = attach_claim_engine_state(_active_context(), state, known_evidence_ids=())
    repository = _TrackingRepository(
        RuntimeDatabase(tmp_path / "active-cluster-cumulative.sqlite")
    )
    run = repository.create(
        WebLookupRun(
            id="run_active_cluster_cumulative",
            query="Alpha framework current release",
            stage="planned",
            status="pending",
            research_context=context,
            max_items=5,
        )
    )

    class _WaveClusterSearchBackend:
        def __init__(self) -> None:
            self.calls = 0

        def search_exact(
            self,
            query: str,
            *,
            max_results: int = 5,
        ) -> dict[str, Any]:
            del max_results
            self.calls += 1
            if "wave-1" in query:
                urls = ["https://wave-1.example/a"]
            elif "wave-2" in query:
                urls = ["https://wave-2.example/a"]
            elif "wave-3" in query:
                urls = [
                    "https://wave-1.example/b",
                    "https://wave-3.example/a",
                ]
            else:
                urls = []
            return {
                "status": "ok",
                "reason": "results_found",
                "results": [
                    {
                        "title": f"Result {index}",
                        "url": url,
                        "snippet": "Verified release announcement",
                        "published_at": "2026-08-01",
                        "provider": "searxng",
                    }
                    for index, url in enumerate(urls)
                ],
                "providers_attempted": ["searxng"],
                "provider_errors": [],
                "provider_audits": [],
                "provider_outcomes": [],
                "searched_at": "2026-08-27T00:00:00+00:00",
            }

    def _novel_wave_query(
        cursor: ResearchRuntimeCursor,
        research_state: ResearchState,
    ) -> ResearchRuntimeCursor:
        wave = cursor.wave_index
        query_text = f"wave-{wave}-cluster-probe"
        if any(item.query.casefold() == query_text for item in cursor.planned_queries):
            return cursor
        open_gap = next(
            item
            for item in research_state.gaps
            if item.state in {"open", "searching"}
        )
        runtime_query = RuntimePlannedQuery(
            id=f"wave-{wave}-cluster-query",
            gap_id=open_gap.id,
            claim_id=open_gap.claim_id,
            intent=GapSearchIntent.DISCOVERY.value,
            query=query_text,
            desired_source_role=open_gap.desired_source_role,
        )
        return replace(
            cursor,
            planned_queries=(*cursor.planned_queries, runtime_query),
        )

    original_append = art_mod._append_gap_queries
    art_mod._append_gap_queries = _novel_wave_query

    try:
        completed = _service(
            repository,
            _PrimaryRoleClient(),
            search_backend=_WaveClusterSearchBackend(),
        ).execute(run.id, raise_on_error=True)
    finally:
        art_mod._append_gap_queries = original_append

    assert completed.status in {"completed", "partial"}
    assert completed.stop_reason != "active_runtime_unavailable"
    cursor = ResearchRuntimeCursor.from_dict(
        completed.research_context[CLAIM_ENGINE_RUNTIME_CONTEXT_KEY]
    )
    assert cursor.wave_index >= 3

    url_by_id = {
        item.id: item.url
        for item in cursor.candidates
    }
    candidate_a = next(
        candidate_id
        for candidate_id, url in url_by_id.items()
        if url == "https://wave-1.example/a"
    )
    candidate_b = next(
        candidate_id
        for candidate_id, url in url_by_id.items()
        if url == "https://wave-2.example/a"
    )
    candidate_c = next(
        candidate_id
        for candidate_id, url in url_by_id.items()
        if url == "https://wave-1.example/b"
    )
    candidate_d = next(
        candidate_id
        for candidate_id, url in url_by_id.items()
        if url == "https://wave-3.example/a"
    )

    successful = {
        outcome.candidate_id
        for outcome in cursor.read_outcomes
        if outcome.status == "success"
    }
    assert {candidate_a, candidate_b, candidate_d} <= successful
    assert candidate_c not in successful

    # cluster X (wave-1.example) 只有一次 physical read。
    read_cluster_counts = Counter(
        str(record["assessment"]["source_cluster_id"])
        for record in completed.selected_sources
        if record.get("read_status") == "read"
        and isinstance(record.get("assessment"), Mapping)
        and record["assessment"].get("source_cluster_id")
    )
    cluster_x = next(
        str(record["assessment"]["source_cluster_id"])
        for record in completed.selected_sources
        if record.get("read_status") == "read"
        and isinstance(record.get("assessment"), Mapping)
        and str((record.get("read") or {}).get("url")) == "https://wave-1.example/a"
    )
    assert read_cluster_counts[cluster_x] == 1

    # White-box: the run-level cumulative covered-cluster truth is durable
    # under its own context key (the read plan alone is overwritten every wave
    # and can never be the coverage source).
    covered_durable = completed.research_context.get(
        ACTIVE_RESEARCH_COVERED_CLUSTERS_KEY
    )
    assert isinstance(covered_durable, Mapping)
    clusters_by_url = {
        str((record.get("read") or {}).get("url")): str(
            record["assessment"]["source_cluster_id"]
        )
        for record in completed.selected_sources
        if record.get("read_status") == "read"
        and isinstance(record.get("assessment"), Mapping)
    }
    cluster_y = clusters_by_url["https://wave-2.example/a"]
    cluster_z = clusters_by_url["https://wave-3.example/a"]
    assert set(covered_durable.get("claim_major", [])) == {
        cluster_x,
        cluster_y,
        cluster_z,
    }

def test_covered_clusters_preserved_for_shared_read_claims(
    tmp_path: Any,
) -> None:
    """P2 round-4 follow-up: a physical read shared by two claims must record
    coverage for BOTH claims - never only the assessment owner claim.

    W1 reads shared.example/p (cluster X) bound to claim_a AND claim_b (H3).
    W2 offers claim_b: shared.example/q (rank 1, repeat cluster X) and
    fresh.example/r (rank 2, fresh cluster Y). claim_b must remember X and
    backfill R - Q must never enter a physical read, and cluster X is read
    exactly once."""
    import src.application.active_research_runtime as art_mod
    from src.web.research.gap_planner import GapSearchIntent

    question = ResearchQuestion(id="question_1", question_surface="Compare releases")
    requirement = EvidenceRequirement(
        source_roles=("primary", "independent_secondary"),
        min_independent_sources=2,
        requires_primary_source=True,
    )
    claim_a = ResearchClaim(
        id="claim_a",
        question_id=question.id,
        text="Alpha framework current release",
        kind="factual",
        priority="major",
        state="searching",
        evidence_requirement=requirement,
    )
    claim_b = ResearchClaim(
        id="claim_b",
        question_id=question.id,
        text="Alpha framework release announcement",
        kind="factual",
        priority="major",
        state="searching",
        evidence_requirement=requirement,
    )
    gap_a = EvidenceGap(
        id="gap_a",
        claim_id=claim_a.id,
        gap_type="missing_evidence",
        desired_source_role="primary",
        priority="major",
        state="open",
    )
    gap_b = EvidenceGap(
        id="gap_b",
        claim_id=claim_b.id,
        gap_type="missing_evidence",
        desired_source_role="primary",
        priority="major",
        state="open",
    )
    state = build_research_state(
        mode="active",
        questions=(question,),
        claims=(claim_a, claim_b),
        evidence=(),
        evidence_links=(),
        source_clusters=(),
        gaps=(gap_a, gap_b),
        conflict_gaps=(),
        budget=ResearchBudget(
            max_candidates=20,
            max_reads=8,
            soft_timeout_seconds=45,
            hard_timeout_seconds=60,
            max_total_chars=16000,
        ),
        reference_date="2026-08-28",
        known_evidence_ids=(),
    )
    context = attach_claim_engine_state(_active_context(), state, known_evidence_ids=())
    repository = _TrackingRepository(
        RuntimeDatabase(tmp_path / "active-shared-coverage.sqlite")
    )
    run = repository.create(
        WebLookupRun(
            id="run_active_shared_coverage",
            query="Alpha framework current release",
            stage="planned",
            status="pending",
            research_context=context,
            max_items=5,
        )
    )

    class _SharedCoverageSearchBackend:
        def search_exact(
            self,
            query: str,
            *,
            max_results: int = 5,
        ) -> dict[str, Any]:
            del max_results
            if "wave-1-probe" in query:
                urls = ["https://shared.example/p"]
            elif "wave-2-probe-gap_b" in query:
                urls = ["https://shared.example/q", "https://fresh.example/r"]
            else:
                urls = []
            return {
                "status": "ok",
                "reason": "results_found",
                "results": [
                    {
                        "title": f"Result {index}",
                        "url": url,
                        "snippet": "Verified release announcement",
                        "published_at": "2026-08-01",
                        "provider": "searxng",
                    }
                    for index, url in enumerate(urls)
                ],
                "providers_attempted": ["searxng"],
                "provider_errors": [],
                "provider_audits": [],
                "provider_outcomes": [],
                "searched_at": "2026-08-27T00:00:00+00:00",
            }

    def _novel_wave_query(
        cursor: ResearchRuntimeCursor,
        research_state: ResearchState,
    ) -> ResearchRuntimeCursor:
        wave = cursor.wave_index
        appended: list[RuntimePlannedQuery] = []
        for open_gap in (
            item
            for item in research_state.gaps
            if item.state in {"open", "searching"}
        ):
            query_text = f"wave-{wave}-probe-{open_gap.id}"
            if any(item.query.casefold() == query_text for item in cursor.planned_queries):
                continue
            appended.append(
                RuntimePlannedQuery(
                    id=f"wave-{wave}-probe-{open_gap.id}-query",
                    gap_id=open_gap.id,
                    claim_id=open_gap.claim_id,
                    intent=GapSearchIntent.DISCOVERY.value,
                    query=query_text,
                    desired_source_role=open_gap.desired_source_role,
                )
            )
        if not appended:
            return cursor
        return replace(
            cursor,
            planned_queries=(*cursor.planned_queries, *appended),
        )

    original_append = art_mod._append_gap_queries
    art_mod._append_gap_queries = _novel_wave_query
    try:
        completed = _service(
            repository,
            _PrimaryRoleClient(),
            search_backend=_SharedCoverageSearchBackend(),
        ).execute(run.id, raise_on_error=True)
    finally:
        art_mod._append_gap_queries = original_append

    assert completed.status in {"completed", "partial"}
    assert completed.stop_reason != "active_runtime_unavailable"
    cursor = ResearchRuntimeCursor.from_dict(
        completed.research_context[CLAIM_ENGINE_RUNTIME_CONTEXT_KEY]
    )
    assert cursor.wave_index >= 3

    url_by_id = {item.id: item.url for item in cursor.candidates}
    candidate_p = next(
        candidate_id
        for candidate_id, url in url_by_id.items()
        if url == "https://shared.example/p"
    )
    candidate_q = next(
        candidate_id
        for candidate_id, url in url_by_id.items()
        if url == "https://shared.example/q"
    )
    candidate_r = next(
        candidate_id
        for candidate_id, url in url_by_id.items()
        if url == "https://fresh.example/r"
    )

    successful = {
        outcome.candidate_id
        for outcome in cursor.read_outcomes
        if outcome.status == "success"
    }
    assert candidate_p in successful
    assert candidate_r in successful
    assert candidate_q not in successful

    # cluster X (shared.example) 只读一次：Q 的重复 cluster 候选永不物理读。
    read_cluster_counts = Counter(
        str(record["assessment"]["source_cluster_id"])
        for record in completed.selected_sources
        if record.get("read_status") == "read"
        and isinstance(record.get("assessment"), Mapping)
        and record["assessment"].get("source_cluster_id")
    )
    cluster_x = next(
        str(record["assessment"]["source_cluster_id"])
        for record in completed.selected_sources
        if record.get("read_status") == "read"
        and isinstance(record.get("assessment"), Mapping)
        and str((record.get("read") or {}).get("url")) == "https://shared.example/p"
    )
    assert read_cluster_counts[cluster_x] == 1

    # 共享 read 的两个 claim 都必须记住 cluster X（白盒）。
    covered_durable = completed.research_context.get(
        ACTIVE_RESEARCH_COVERED_CLUSTERS_KEY
    )
    assert isinstance(covered_durable, Mapping)
    assert cluster_x in set(
        str(cluster) for cluster in covered_durable.get("claim_a", [])
    )
    assert cluster_x in set(
        str(cluster) for cluster in covered_durable.get("claim_b", [])
    )

def test_stop_gate_reconstructs_persisted_decision_from_durable_truth(
    tmp_path: Any,
) -> None:
    """P1-C batch 3 acceptance: after a terminal run, re-deriving the settle
    signals purely from durable truth (persisted cursor + state) and running
    them through ResearchStopGate yields exactly the persisted stop reason -
    the same decision a crash/resume settlement would make."""
    import src.application.active_research_runtime as art_mod
    from src.application.research_stop_gate import (
        ResearchStopGate,
        ResearchStopSignal,
    )
    from src.web.research.evidence_gain import SaturationState, saturated_claim_ids
    from src.web.research.state import CLAIM_ENGINE_CONTEXT_KEY
    from src.web.research.evidence_gate import evaluate_evidence_gate

    state = _two_gap_state(same_claim_text=True)
    context = attach_claim_engine_state(
        _active_context(),
        state,
        known_evidence_ids=(),
    )
    repository = _TrackingRepository(RuntimeDatabase(tmp_path / "active-gate-rebuild.sqlite"))
    run = repository.create(
        WebLookupRun(
            id="run_active_gate_rebuild",
            query="Compare identical research surfaces",
            stage="planned",
            status="pending",
            research_context=context,
            max_items=5,
        )
    )
    completed = _service(
        repository,
        _StructuredClient(),
        search_backend=_EmptySearchBackend(),
    ).execute(run.id, raise_on_error=True)

    assert completed.status == "partial"
    assert completed.stop_reason == "evidence_saturated"

    raw_context = completed.research_context
    cursor = ResearchRuntimeCursor.from_dict(
        raw_context[CLAIM_ENGINE_RUNTIME_CONTEXT_KEY]
    )
    raw_state = raw_context[CLAIM_ENGINE_CONTEXT_KEY]
    rebuilt_state = ResearchState.from_dict(
        raw_state,
        known_evidence_ids=tuple(
            item["evidence_id"]
            for item in raw_state.get("evidence", [])
            if isinstance(item, Mapping)
            and isinstance(item.get("evidence_id"), str)
        ),
    )

    open_gap_claims = {
        gap.claim_id for gap in art_mod._ordered_gaps(rebuilt_state)
    }
    extra_batch_claims = {
        claim.id
        for claim in rebuilt_state.claims
        if claim.priority == "critical"
    } | {conflict.claim_id for conflict in rebuilt_state.conflict_gaps}
    saturated_claims = set(
        saturated_claim_ids(
            SaturationState(
                no_gain_batches_by_claim=dict(
                    cursor.no_gain_batches_by_claim
                )
            ),
            extra_batch_eligible_claim_ids=extra_batch_claims,
        )
    )
    gate = evaluate_evidence_gate(rebuilt_state)
    decision = ResearchStopGate.evaluate(
        ResearchStopSignal(
            gate_pass=gate.status == "pass",
            hard_budget_exhausted=(
                rebuilt_state.budget.elapsed_seconds
                >= rebuilt_state.budget.hard_timeout_seconds
            ),
            has_actionable_gaps=bool(open_gap_claims),
            all_actionable_saturated=bool(open_gap_claims)
            and open_gap_claims <= saturated_claims,
            wave_limit_reached=cursor.wave_index >= art_mod.MAX_RESEARCH_WAVES,
            has_evidence=bool(rebuilt_state.evidence),
        )
    )
    assert decision.decision == "partial"
    assert decision.reason == completed.stop_reason == "evidence_saturated"

def test_pending_steering_forces_next_wave_and_applies_exactly_once(
    tmp_path: Any,
) -> None:
    """P1-C batch 3 / steering 1A+2A: a pending user direction arriving after
    wave 1 must stop the run from finishing on the pre-steering graph and be
    applied exactly once at the next wave boundary, producing one server-owned
    user claim and one critical gap."""
    from src.web.research.steering import active_steering_entries
    from src.web.research.state import CLAIM_ENGINE_CONTEXT_KEY

    state = _two_gap_state()
    context = attach_claim_engine_state(_active_context(), state, known_evidence_ids=())
    repository = _TrackingRepository(RuntimeDatabase(tmp_path / "active-steering-apply.sqlite"))
    run = repository.create(
        WebLookupRun(
            id="run_active_steering_apply",
            query="Compare releases",
            stage="planned",
            status="pending",
            research_context=context,
            max_items=5,
        )
    )
    injected = {"done": False}

    def _inject(index: int) -> None:
        if index == 1 and not injected["done"]:
            injected["done"] = True
            assert repository.append_steering(
                run.id,
                content="Focus on the 2026 release notes",
            ) is not None

    completed = _service(
        repository,
        _StructuredClient(on_call=_inject),
        search_backend=_SearchBackend(),
    ).execute(run.id, raise_on_error=True)

    assert completed.status in {"completed", "partial"}
    entries = active_steering_entries(completed.research_context)
    assert len(entries) == 1
    assert entries[0]["status"] == "applied"
    assert entries[0]["applied_wave"] is not None
    assert entries[0]["applied_wave"] >= 2
    assert entries[0]["late_reason"] == ""
    assert entries[0]["claim_id"].startswith("claim_steering_")

    raw_state = completed.research_context[CLAIM_ENGINE_CONTEXT_KEY]
    rebuilt = ResearchState.from_dict(
        raw_state,
        known_evidence_ids=tuple(
            item["evidence_id"]
            for item in raw_state.get("evidence", [])
            if isinstance(item, Mapping)
            and isinstance(item.get("evidence_id"), str)
        ),
    )
    user_claims = [item for item in rebuilt.claims if item.created_by == "user"]
    assert len(user_claims) == 1
    assert user_claims[0].priority == "critical"
    assert user_claims[0].created_reason == "active_steering:" + entries[0]["id"]
    assert any(item.gap_type == "user_steering" for item in rebuilt.gaps)
    assert any(
        item.id == entries[0]["gap_id"] and item.claim_id == entries[0]["claim_id"]
        for item in rebuilt.gaps
    )


def test_pending_steering_goes_late_when_hard_budget_exhausted(
    tmp_path: Any,
) -> None:
    """P1-C batch 3 / steering 1A: once the 60s hard budget is exhausted a
    pending steering is marked late/unapplied and the run keeps the honest
    evidence_budget_exhausted terminal truth - never an implicit extension."""
    from src.web.research.steering import active_steering_entries

    class _Clock:
        def __init__(self) -> None:
            self.value = 0.0

        def __call__(self) -> float:
            return self.value

    clock = _Clock()

    class _DeadlineCrossingSearch(_EmptySearchBackend):
        def search_exact(
            self,
            query: str,
            *,
            max_results: int = 5,
        ) -> dict[str, Any]:
            result = super().search_exact(query, max_results=max_results)
            clock.value = 61.0
            if not injected["done"]:
                injected["done"] = True
                assert repository.append_steering(
                    run.id,
                    content="Too late to apply",
                ) is not None
            return result

    state = _two_gap_state()
    context = attach_claim_engine_state(_active_context(), state, known_evidence_ids=())
    repository = _TrackingRepository(RuntimeDatabase(tmp_path / "active-steering-late.sqlite"))
    run = repository.create(
        WebLookupRun(
            id="run_active_steering_late",
            query="Compare releases",
            stage="planned",
            status="pending",
            research_context=context,
            max_items=5,
        )
    )
    injected = {"done": False}

    completed = _service(
        repository,
        _StructuredClient(),
        search_backend=_DeadlineCrossingSearch(),
        monotonic=clock,
    ).execute(run.id, raise_on_error=True)

    assert completed.status == "partial"
    assert completed.stop_reason == "evidence_budget_exhausted"
    entries = active_steering_entries(completed.research_context)
    assert len(entries) == 1
    assert entries[0]["status"] == "late"
    assert entries[0]["applied_wave"] is None
    assert entries[0]["claim_id"] == ""
    assert entries[0]["late_reason"] == "hard_budget_exhausted"


def test_apply_pending_steering_is_idempotent_for_same_entry() -> None:
    """P1-C batch 3 / steering 3A acceptance: a crash/resume that re-runs the
    apply step must never create a second user claim or gap for one entry."""
    import src.application.active_research_runtime as art_mod
    from src.web.research.steering import append_active_steering

    state = _two_gap_state()
    context = attach_claim_engine_state(_active_context(), state, known_evidence_ids=())
    context = append_active_steering(
        context,
        entry_id="steering_1",
        content="Focus on the 2026 release notes",
        received_at="2026-08-31T00:00:00+00:00",
    )
    context = append_active_steering(
        context,
        entry_id="steering_2",
        content="Also check the announcement page",
        received_at="2026-08-31T00:00:01+00:00",
    )
    first_state, first_context, first_ids = art_mod._apply_pending_active_steering(
        state,
        context,
        run_id="run_id",
        wave_index=2,
        applied_at="2026-08-31T00:00:02+00:00",
        known_evidence_ids=(),
    )
    second_state, second_context, second_ids = art_mod._apply_pending_active_steering(
        first_state,
        first_context,
        run_id="run_id",
        wave_index=2,
        applied_at="2026-08-31T00:00:02+00:00",
        known_evidence_ids=(),
    )
    assert first_ids == ("steering_1", "steering_2")
    assert second_ids == ()
    assert second_state == first_state
    assert second_context == first_context
    user_claims = [item for item in first_state.claims if item.created_by == "user"]
    assert len(user_claims) == 2

def test_checkpoint_race_merges_concurrent_steering_without_losing_mutation(
    tmp_path: Any,
) -> None:
    """P1-C batch 3 / steering 6A: when /steer bumps the version between the
    runtime read and its CAS checkpoint, the retry must reload the newest
    durable context, keep both the concurrent steering entry and the runtime
    mutation, and never raise a conflict."""
    from src.web.research.steering import active_steering_entries

    repository = WebLookupRepository(RuntimeDatabase(tmp_path / "steering-race.sqlite"))
    run = repository.create(
        WebLookupRun(
            id="run_steering_race",
            query="Compare releases",
            stage="planned",
            status="pending",
            research_context=_active_context(),
            max_items=5,
        )
    )
    run = repository.begin_operation(run.id, operation_id="op_race", stage="searching")
    stale_context = dict(run.research_context)
    stale_context["race_mutation"] = {"wave_baseline": True}
    assert repository.append_steering(run.id, content="concurrent steering") is not None
    checked = repository.checkpoint(
        run.id,
        operation_id="op_race",
        research_context=stale_context,
        query_attempts=[],
        selected_sources=[],
        rejected_sources=[],
        items=[],
        warnings=[],
        provider_status="",
        stop_reason="",
        answer_confidence="",
    )
    assert checked.research_context.get("race_mutation") == {"wave_baseline": True}
    entries = active_steering_entries(checked.research_context)
    assert len(entries) == 1
    assert entries[0]["content"] == "concurrent steering"
    assert entries[0]["status"] == "pending"


@pytest.mark.parametrize("crash_mode", ["before", "after"])
def test_steering_apply_crash_before_and_after_checkpoint_is_exactly_once(
    tmp_path: Any,
    crash_mode: str,
) -> None:
    """P1-C batch 3 / steering 6A: a crash either before the apply checkpoint
    (nothing durable) or after it (claim/gap + applied already durable) must
    resume to exactly one user claim and one user gap for the steering - never
    a second structural copy and never a silently re-applied entry."""
    from src.web.research.steering import active_steering_entries
    from src.web.research.state import CLAIM_ENGINE_CONTEXT_KEY

    class _SimulatedProcessDeath(BaseException):
        pass

    class _CrashOnApplyCheckpoint(WebLookupRepository):
        def __init__(self, database: Any) -> None:
            super().__init__(database)
            self.armed = True

        def checkpoint(
            self,
            run_id: str,
            *,
            operation_id: str,
            research_context: dict[str, Any],
            **kwargs: Any,
        ) -> Any:
            entries = active_steering_entries(research_context)
            if self.armed and any(
                item.get("status") == "applied" for item in entries
            ):
                self.armed = False
                if crash_mode == "before":
                    raise _SimulatedProcessDeath(
                        "crash before apply checkpoint"
                    )
                super().checkpoint(
                    run_id,
                    operation_id=operation_id,
                    research_context=research_context,
                    **kwargs,
                )
                raise _SimulatedProcessDeath("crash after apply checkpoint")
            return super().checkpoint(
                run_id,
                operation_id=operation_id,
                research_context=research_context,
                **kwargs,
            )

    repository = _CrashOnApplyCheckpoint(
        RuntimeDatabase(tmp_path / f"steering-crash-{crash_mode}.sqlite")
    )
    run = repository.create(
        WebLookupRun(
            id=f"run_steering_crash_{crash_mode}",
            query="What is the verified current release date?",
            stage="planned",
            status="pending",
            research_context=_active_context(),
            max_items=5,
        )
    )
    injected = {"done": False}

    def _inject(index: int) -> None:
        if index == 1 and not injected["done"]:
            injected["done"] = True
            assert repository.append_steering(
                run.id,
                content="exactly once",
            ) is not None

    with pytest.raises(_SimulatedProcessDeath):
        _service(
            repository,
            _StructuredClient(on_call=_inject),
        ).execute(run.id, raise_on_error=True)

    with repository.database.connect() as connection:
        row = connection.execute(
            "SELECT research_context FROM web_lookup_runs WHERE id = ?",
            (run.id,),
        ).fetchone()
        assert row is not None
        stale_context = loads(str(row[0]))
        stale_context.setdefault("operation", {})["active_operation_started_at"] = (
            "2000-01-01T00:00:00+00:00"
        )
        connection.execute(
            "UPDATE web_lookup_runs SET research_context = ? WHERE id = ?",
            (_json_dumps(stale_context), run.id),
        )

    completed = _service(
        repository,
        _StructuredClient(),
    ).execute(run.id, raise_on_error=True)

    assert completed.status in {"completed", "partial"}
    entries = active_steering_entries(completed.research_context)
    assert len(entries) == 1
    assert entries[0]["status"] == "applied"
    raw_state = completed.research_context[CLAIM_ENGINE_CONTEXT_KEY]
    rebuilt = ResearchState.from_dict(
        raw_state,
        known_evidence_ids=tuple(
            item["evidence_id"]
            for item in raw_state.get("evidence", [])
            if isinstance(item, Mapping)
            and isinstance(item.get("evidence_id"), str)
        ),
    )
    user_claims = [item for item in rebuilt.claims if item.created_by == "user"]
    assert len(user_claims) == 1
    assert user_claims[0].id == entries[0]["claim_id"]
    user_gaps = [item for item in rebuilt.gaps if item.gap_type == "user_steering"]
    assert len(user_gaps) == 1
    assert user_gaps[0].id == entries[0]["gap_id"]


def test_pending_steering_defers_gate_pass_to_next_wave(tmp_path: Any) -> None:
    """P1-C batch 3 / steering 6A + gate: with budget still available, a
    pending steering must stop the ResearchStopGate from completing a passed
    gate and be consumed at the next wave instead."""
    from src.web.research.steering import active_steering_entries
    from src.web.research.state import CLAIM_ENGINE_CONTEXT_KEY

    repository = _TrackingRepository(
        RuntimeDatabase(tmp_path / "steering-gatepass.sqlite")
    )
    run = repository.create(
        WebLookupRun(
            id="run_steering_gatepass",
            query="What is the verified current release date?",
            stage="planned",
            status="pending",
            research_context=_active_context(),
            max_items=5,
        )
    )
    injected = {"done": False}

    def _inject() -> None:
        if not injected["done"]:
            injected["done"] = True
            assert repository.append_steering(
                run.id,
                content="Also verify the announcement page",
            ) is not None

    completed = _service(
        repository,
        _StructuredClient(),
        read_gateway=_ReadGateway(on_read=_inject),
    ).execute(run.id, raise_on_error=True)

    assert completed.status in {"completed", "partial"}
    entries = active_steering_entries(completed.research_context)
    assert len(entries) == 1
    assert entries[0]["status"] == "applied"
    assert entries[0]["applied_wave"] is not None
    assert entries[0]["applied_wave"] >= 2
    raw_state = completed.research_context[CLAIM_ENGINE_CONTEXT_KEY]
    rebuilt = ResearchState.from_dict(
        raw_state,
        known_evidence_ids=tuple(
            item["evidence_id"]
            for item in raw_state.get("evidence", [])
            if isinstance(item, Mapping)
            and isinstance(item.get("evidence_id"), str)
        ),
    )
    assert len([item for item in rebuilt.claims if item.created_by == "user"]) == 1
    assert any(item.gap_type == "user_steering" for item in rebuilt.gaps)

@pytest.mark.parametrize("terminal", ["hard_budget_exhausted", "wave_limit_reached"])
def test_late_steering_terminal_crash_recomputes_same_stop_decision(
    tmp_path: Any,
    terminal: str,
) -> None:
    """P1-C batch 3 round-2 / steering 6A: the suppression of the old graph's
    gate pass by a late steering must be durable truth, recomputed by the
    StopGate on resume - never the return value of one mark call.

    Sequence: old graph reaches Gate PASS -> steering arrives -> terminal
    budget/wave ceiling -> steering marked late -> late checkpoint persisted
    -> simulated process death -> stale operation -> resume -> the same
    canonical stop decision must be recomputed (partial, never completed on
    the old graph), and the durable signal must reproduce it through the
    gate."""
    import src.application.active_research_runtime as art_mod
    from src.application.research_stop_gate import (
        ResearchStopGate,
        ResearchStopSignal,
    )
    from src.web.research.steering import active_steering_entries
    from src.web.research.state import CLAIM_ENGINE_CONTEXT_KEY
    from src.web.research.evidence_gate import evaluate_evidence_gate

    class _SimulatedProcessDeath(BaseException):
        pass

    class _Clock:
        def __init__(self) -> None:
            self.value = 0.0

        def __call__(self) -> float:
            return self.value

    clock = _Clock()

    class _CrashOnLateCheckpoint(WebLookupRepository):
        def __init__(self, database: Any) -> None:
            super().__init__(database)
            self.armed = True

        def checkpoint(
            self,
            run_id: str,
            *,
            operation_id: str,
            research_context: dict[str, Any],
            **kwargs: Any,
        ) -> Any:
            result = super().checkpoint(
                run_id,
                operation_id=operation_id,
                research_context=research_context,
                **kwargs,
            )
            entries = active_steering_entries(research_context)
            if self.armed and any(
                item.get("status") == "late" for item in entries
            ):
                self.armed = False
                raise _SimulatedProcessDeath("crash after late checkpoint")
            return result

    repository = _CrashOnLateCheckpoint(
        RuntimeDatabase(tmp_path / f"late-crash-{terminal}.sqlite")
    )
    run = repository.create(
        WebLookupRun(
            id=f"run_late_crash_{terminal}",
            query="What is the verified current release date?",
            stage="planned",
            status="pending",
            research_context=_active_context(),
            max_items=5,
        )
    )
    injected = {"done": False}

    def _inject() -> None:
        if not injected["done"]:
            injected["done"] = True
            if terminal == "hard_budget_exhausted":
                clock.value = 61.0
            assert repository.append_steering(
                run.id,
                content="Too late to apply",
            ) is not None

    original_limit = art_mod.MAX_RESEARCH_WAVES
    configured_limit = 1 if terminal == "wave_limit_reached" else original_limit
    art_mod.MAX_RESEARCH_WAVES = configured_limit
    try:
        with pytest.raises(_SimulatedProcessDeath):
            _service(
                repository,
                _StructuredClient(),
                read_gateway=_ReadGateway(on_read=_inject),
                monotonic=clock,
            ).execute(run.id, raise_on_error=True)

        with repository.database.connect() as connection:
            row = connection.execute(
                "SELECT research_context FROM web_lookup_runs WHERE id = ?",
                (run.id,),
            ).fetchone()
            assert row is not None
            stale_context = loads(str(row[0]))
            stale_context.setdefault("operation", {})["active_operation_started_at"] = (
                "2000-01-01T00:00:00+00:00"
            )
            connection.execute(
                "UPDATE web_lookup_runs SET research_context = ? WHERE id = ?",
                (_json_dumps(stale_context), run.id),
            )

        completed = _service(
            repository,
            _StructuredClient(),
            monotonic=clock,
        ).execute(run.id, raise_on_error=True)
    finally:
        art_mod.MAX_RESEARCH_WAVES = original_limit

    assert completed.status == "partial"
    # The late steering is itself an unapplied actionable direction. It blocks
    # completion on the old graph without being forged into the claim graph,
    # so the bounded terminal owner remains the exhausted hard/wave budget.
    expected_reason = (
        "evidence_budget_exhausted"
        if terminal == "hard_budget_exhausted"
        else "wave_limit_exhausted"
    )
    assert completed.stop_reason == expected_reason
    assert completed.stop_reason != "evidence_gate_pass"

    entries = active_steering_entries(completed.research_context)
    assert len(entries) == 1
    assert entries[0]["status"] == "late"
    assert entries[0]["late_reason"] == terminal
    assert entries[0]["claim_id"] == ""
    assert entries[0]["applied_wave"] is None

    raw_state = completed.research_context[CLAIM_ENGINE_CONTEXT_KEY]
    rebuilt = ResearchState.from_dict(
        raw_state,
        known_evidence_ids=tuple(
            item["evidence_id"]
            for item in raw_state.get("evidence", [])
            if isinstance(item, Mapping)
            and isinstance(item.get("evidence_id"), str)
        ),
    )
    assert not [item for item in rebuilt.claims if item.created_by == "user"]

    # Durable recomputation contract: the same signal rebuilt purely from
    # durable truth reproduces the persisted canonical stop reason.
    cursor = ResearchRuntimeCursor.from_dict(
        completed.research_context[CLAIM_ENGINE_RUNTIME_CONTEXT_KEY]
    )
    gate = evaluate_evidence_gate(rebuilt)
    rebuilt_signal = ResearchStopSignal(
        gate_pass=gate.status == "pass",
        hard_budget_exhausted=(
            clock.value >= rebuilt.budget.hard_timeout_seconds
        ),
        has_actionable_gaps=(
            bool(art_mod._ordered_gaps(rebuilt))
            or art_mod._unapplied_steering_blocks_completion(
                completed.research_context
            )
        ),
        all_actionable_saturated=False,
        wave_limit_reached=cursor.wave_index >= configured_limit,
        has_evidence=bool(rebuilt.evidence),
        unapplied_steering_blocks_completion=(
            art_mod._unapplied_steering_blocks_completion(
                completed.research_context
            )
        ),
    )
    assert ResearchStopGate.evaluate(rebuilt_signal).reason == expected_reason
    assert rebuilt_signal.unapplied_steering_blocks_completion is True

def test_v1_planning_attempt_exhaustion_is_classified_before_third_call(
    tmp_path: Any,
) -> None:
    from src.web.research.claim_planner import RUNTIME_CLAIM_PLAN_SCHEMA_VERSION
    from src.web.research.model_gateway import ResearchModelAttemptStart
    from src.web.research.runtime import (
        RESEARCH_RUNTIME_SCHEMA_VERSION_V1,
        attach_runtime_cursor,
        begin_model_attempt,
        recover_interrupted_model_attempt,
    )

    run_id = "run_active_v1_planning_exhaustion"
    logical_call_id = f"research_claim_plan:{run_id}:1"
    cursor = ResearchRuntimeCursor(
        phase="planning",
        schema_version=RESEARCH_RUNTIME_SCHEMA_VERSION_V1,
    )
    for attempt in (1, 2):
        marker = ResearchModelAttemptStart(
            call_id=f"{logical_call_id}:attempt:{attempt}",
            logical_call_id=logical_call_id,
            purpose="research_claim_planning",
            provider_profile="openai",
            model_profile="flash",
            model_name="test-model",
            attempt=attempt,
            started_at=f"2026-09-02T11:0{attempt}:00+00:00",
            response_schema_version=RUNTIME_CLAIM_PLAN_SCHEMA_VERSION,
            input_sha256="a" * 64,
            input_chars=12,
            data_categories=("user_question",),
            data_counts=(("user_question", 1),),
        )
        cursor = ResearchRuntimeCursor.from_dict(
            recover_interrupted_model_attempt(
                begin_model_attempt(cursor, marker)
            ).to_dict()
        )

    context = attach_runtime_cursor(_active_context(), cursor)
    repository = _TrackingRepository(
        RuntimeDatabase(tmp_path / "active-v1-planning-exhaustion.sqlite")
    )
    run = repository.create(
        WebLookupRun(
            id=run_id,
            query="What is the verified current release date?",
            stage="planned",
            status="pending",
            research_context=context,
            max_items=5,
        )
    )
    client = _StructuredClient()

    failed = _service(repository, client).execute(run.id, raise_on_error=True)

    assert failed.status == "failed"
    assert failed.provider_status == "unavailable"
    assert failed.stop_reason == "claim_plan_unavailable"
    assert client.calls == []
    resumed_cursor = ResearchRuntimeCursor.from_dict(
        failed.research_context[CLAIM_ENGINE_RUNTIME_CONTEXT_KEY]
    )
    planning_failures = [
        failure
        for failure in resumed_cursor.failures
        if failure.code == "model_attempts_exhausted"
        and failure.phase == "planning"
    ]
    assert len(planning_failures) == 1
    assert planning_failures[0].item_id == "research_claim_planning"
    assert not any(
        failure.code == "runtime_internal_failed"
        for failure in resumed_cursor.failures
    )
    assert not any(
        failure.item_id.startswith(f"{logical_call_id}:attempt:3")
        for failure in resumed_cursor.failures
    )
