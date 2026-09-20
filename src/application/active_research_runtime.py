"""Production executor for one bounded active Claim Engine research wave.

The existing WebLookupRepository remains the operation and persistence owner.
This executor composes the previously delivered claim, query, candidate,
assessment, ranking, scheduling, reading, extraction and Evidence Gate
components without changing off/shadow/legacy execution.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Mapping
from dataclasses import replace
from datetime import datetime, timezone
from math import ceil, isfinite
import re
import time
from typing import Any, cast
from urllib.parse import urlsplit

from src.domain.evidence import ClaimEvidenceLinkV1, build_evidence_snapshot
from src.domain.runtime_entities import WebLookupRun, new_id
from src.repositories.web_lookup_repository import WebLookupRepository
from src.web.research.active_adapter import (
    ActiveResearchGateway,
    read_gateway_accepts_timeout,
)
from src.web.research.active_semantics import (
    CANDIDATE_ASSESSMENT_TIMEOUT_SECONDS,
    RuntimeCandidateAssessor,
    RuntimeEvidenceExtractor,
)
from src.web.research.candidate_pool import (
    CandidatePoolCancelled,
    CandidatePoolItem,
    execute_candidate_pool_batch,
)
from src.web.research.candidate_ranking import (
    CandidateSemanticAssessment,
    RankedCandidate,
    rank_candidate_pool,
)
from src.web.research.claim_planner import RuntimeClaimPlanner
from src.web.research.deeper_targeting import (
    AUTHORITY_OFFICIAL,
    AUTHORITY_TUTORIAL,
    GapHint,
    authority_class,
    gap_from_extraction,
    rank_targeting_candidates,
    target_path_hit,
    targeted_query_terms,
)
from src.web.research.discovery_observability import record_search_call
from src.web.research.page_intent import (
    PageIntent,
    infer_page_intent,
    query_variants,
    selection_reason,
)
from src.web.research.contracts import (
    EvidenceCluster,
    EvidenceGap,
    EvidenceRequirement,
    ResearchBrief,
    ResearchClaim,
    ResearchClaimEvidenceLink,
    ResearchEvidence,
    ResearchState,
    ResearchTraceEvent,
    build_research_state,
)
from src.web.research.evidence_gate import (
    EvidenceGateResult,
    claim_support_topology,
    evaluate_evidence_gate,
    evidence_link_eligibility,
)
from src.web.research.lead_discovery import (
    LeadDiscoveryPayload,
    RuntimeLeadDiscoverer,
)
from src.news.url_normalizer import canonicalize_url
from src.web.research.evidence_gain import (
    GapBatchDelta,
    SaturationState,
    evaluate_evidence_gain,
    saturated_claim_ids,
    update_saturation,
)
from src.web.research.failure_contracts import ResearchFailureCode
from src.web.research.gap_planner import (
    GapQueryBatch,
    GapSearchIntent,
    PlannedGapQuery,
    plan_gap_queries,
    query_terms,
)
from src.web.research.model_gateway import (
    MAX_RESEARCH_MODEL_ATTEMPTS,
    ResearchModelAttemptStart,
    ResearchModelCallAudit,
    ResearchModelGateway,
)
from src.web.research.phase_budget import FINALIZATION_RESERVE_SECONDS
from src.web.research.runtime import (
    EVIDENCE_LEAD_FOLLOWUP_MIN_REMAINING_SECONDS,
    MAX_EVIDENCE_LEAD_FOLLOWUPS_PER_RUN,
    MAX_EVIDENCE_LEAD_FOLLOWUPS_PER_WAVE,
    MAX_LEAD_DISCOVERED_CANDIDATES_PER_RUN,
    MAX_LEAD_DISCOVERY_DEPTH,
    MAX_LEAD_READS_PER_RUN,
    MAX_RESEARCH_WAVES,
    ResearchRuntimeCursor,
    RuntimeCandidate,
    RuntimeExternalAttemptStart,
    RuntimePhase,
    RuntimePlannedQuery,
    RuntimeQueryOutcome,
    RuntimeReadOutcome,
    append_runtime_failure,
    attach_runtime_cursor,
    begin_external_attempt,
    begin_model_attempt,
    build_runtime_failure,
    finish_external_attempt,
    finish_model_attempt,
    load_runtime_cursor,
    recover_interrupted_external_attempt,
    recover_interrupted_model_attempt,
    runtime_failure_id,
    runtime_failure_id_unattached,
)
from src.web.research.scheduler import (
    ReadSchedulerPolicy,
    ReadSchedulingCancelled,
    is_schedulable_candidate,
    is_schedulable_lead,
    plan_read_wave,
)
from src.web.research.llm_proposal import (
    DISCOVERY_METHOD_LLM_PROPOSED,
    build_proposal_payload,
    llm_proposal_enabled,
    parse_proposal_response,
    proposal_messages,
    tier1_miss_reason,
)
from src.web.research.domain_targeted import (
    DISCOVERY_METHOD_DOMAIN_TARGETED,
    MAX_DOMAINS,
    MAX_LINKS_PER_INVENTORY,
    MAX_RANK_TERMS,
    claim_search_terms,
    domain_proposal_messages,
    domain_proposal_payload,
    domain_targeted_enabled,
    parse_domain_proposal,
    parse_sitemap,
    prioritise_sitemap_children,
    rank_domain_urls,
    sitemap_urls,
)
from src.web.research.read_retry import (
    make_window_admission,
    read_retry_mode,
    read_with_bounded_retry,
)
from src.web.research.selection_trace import SelectionTraceCollector
from src.web.research.atomic_routing import (
    atomic_routing_enabled,
    route_missing_atomic_claims,
)
from src.web.research.grounded_excerpts import (
    ANSWER_SHAPE_CONTRACT,
    EXCERPT_MAX_CHARS,
    EXCERPT_TOTAL_CHARS,
    grounded_excerpt,
    grounded_input_enabled,
)
from src.web.research.selection_authority import (
    SELECTION_AUTHORITY_MODEL,
    SelectionAuthorityDiagnostics,
    select_candidates_with_model,
    selection_authority_mode,
)
from src.web.research.source_cluster import (
    CandidateClusterAssignment,
    cluster_candidate_sources,
)
from src.web.research.state import attach_claim_engine_state
from src.web.research.steering import (
    ACTIVE_RESEARCH_STEERING_KEY,
    active_steering_entries,
    merge_active_steering_context,
)
from src.application.research_stop_gate import (
    ResearchStopGate,
    ResearchStopSignal,
)

ACTIVE_RESEARCH_ASSESSMENTS_KEY = "claim_engine_assessments"
ACTIVE_RESEARCH_ASSESSMENT_INPUTS_KEY = "claim_engine_assessment_inputs"
ACTIVE_RESEARCH_WAVE_BASELINE_KEY = "claim_engine_wave_baseline"
ACTIVE_RESEARCH_READ_PLAN_KEY = "claim_engine_read_plan"
ACTIVE_RESEARCH_COVERED_CLUSTERS_KEY = "claim_engine_covered_clusters"
ACTIVE_RESEARCH_BRIEF_KEY = "claim_engine_evidence_brief"
ACTIVE_RESEARCH_METRICS_KEY = "claim_engine_metrics"
TIER2_PROPOSED_CLAIMS_KEY = "tier2_proposed_claim_ids"
DOMAIN_TARGETED_CLAIMS_KEY = "domain_targeted_claim_ids"
MAX_DOMAIN_TARGETED_CANDIDATES = 3
MAX_DOMAIN_TARGETED_SEARCH_FETCHES = 3
DOMAIN_TARGETED_MIN_SECONDS_LEFT = 12.0
ACTIVE_RESEARCH_POLICY_AUDITS_KEY = "claim_engine_policy_audits"
CANDIDATE_ASSESSMENT_WINDOW_MAX_CANDIDATES = 2

PolicyCheck = Callable[[Mapping[str, Any], str], bool]


class ActiveResearchCancelled(RuntimeError):
    pass


class _ModelAttemptBudgetExhausted(RuntimeError):
    pass


class _ExternalAttemptBudgetExhausted(RuntimeError):
    pass


# Deadline-aware provider policy: the search stage must not consume the entire
# shared hard budget. This tail is reserved for downstream assessment/read/
# answer so a degraded provider cannot starve the rest of the bounded run.
#
# Research Window Deadline Hardening: ONE reserve is the single source of truth
# for every phase (search / assessment / read / extraction / discovery). It is a
# safety reserve - deliberately NOT a calibrated action cost. Real finalization
# cost is recorded in ``metrics.research_window`` so a later batch can calibrate
# it from paired runs instead of guessing.
RESEARCH_WINDOW_RESERVE_SECONDS = FINALIZATION_RESERVE_SECONDS

# Reader side of the same invariant: a page read may never start (or overrun)
# outside the shared research window. ``READ_TIMEOUT_CAP_SECONDS`` mirrors the
# reader's own default network timeout; the effective timeout is the smaller of
# that cap and the remaining research window.
READ_TIMEOUT_CAP_SECONDS = 10.0
MIN_READ_SECONDS = 1.0


class ActiveResearchRuntimeExecutor:
    """Execute one active run under the durable WebLookupRun owner."""

    def __init__(
        self,
        repository: WebLookupRepository,
        gateway: ActiveResearchGateway,
        *,
        model_gateway: ResearchModelGateway | None = None,
        claim_planner: RuntimeClaimPlanner | None = None,
        candidate_assessor: RuntimeCandidateAssessor | None = None,
        evidence_extractor: RuntimeEvidenceExtractor | None = None,
        lead_discoverer: RuntimeLeadDiscoverer | None = None,
        policy_check: PolicyCheck | None = None,
        monotonic: Callable[[], float] = time.monotonic,
        utc_now: Callable[[], str] | None = None,
        model_timeout_cap_seconds: float = 20.0,
        candidate_assessment_timeout_cap_seconds: float = (
            CANDIDATE_ASSESSMENT_TIMEOUT_SECONDS
        ),
    ) -> None:
        self.repository = repository
        self.gateway = gateway
        if isinstance(model_timeout_cap_seconds, bool):
            raise ValueError("model timeout cap must be positive")
        try:
            model_timeout_cap = float(model_timeout_cap_seconds)
        except (TypeError, ValueError) as exc:
            raise ValueError("model timeout cap must be positive") from exc
        if not isfinite(model_timeout_cap) or model_timeout_cap <= 0:
            raise ValueError("model timeout cap must be positive")
        self.model_timeout_cap_seconds = model_timeout_cap
        shared_model = model_gateway or ResearchModelGateway(timeout_seconds=20.0)
        self.model_gateway = shared_model
        self.claim_planner = claim_planner or RuntimeClaimPlanner(shared_model)
        self.candidate_assessor = candidate_assessor or RuntimeCandidateAssessor(
        shared_model,
        timeout_cap_seconds=candidate_assessment_timeout_cap_seconds,
    )
        self.evidence_extractor = evidence_extractor or RuntimeEvidenceExtractor(shared_model)
        self.lead_discoverer = lead_discoverer or RuntimeLeadDiscoverer(shared_model)
        self.policy_check = policy_check or _default_policy_check
        self.monotonic = monotonic
        self.utc_now = utc_now or _utc_now
        self.read_gateway_accepts_timeout = read_gateway_accepts_timeout(gateway)

    def execute(
        self,
        run_id: str,
        *,
        initial_state: ResearchState,
        raise_on_error: bool = False,
        stale_after_seconds: int = 120,
    ) -> WebLookupRun:
        existing = self._required(run_id)
        if initial_state.mode != "active":
            raise ValueError("active runtime requires active Claim Engine state")
        if existing.status == "completed" and existing.provider_status == "found":
            raise ValueError(f"WebLookupRun is already complete: {run_id}")

        operation_id = new_id("rqce_active")
        run = self.repository.begin_operation(
            run_id,
            operation_id=operation_id,
            stage="planned",
            stale_after_seconds=stale_after_seconds,
        )
        context = dict(run.research_context)
        context["run_attempt"] = int(context.get("run_attempt") or 0) + 1
        state = initial_state
        cursor_result = load_runtime_cursor(context)
        loaded_cursor = cursor_result.cursor
        cursor: ResearchRuntimeCursor
        if cursor_result.available and loaded_cursor is not None:
            cursor = loaded_cursor
        else:
            cursor = ResearchRuntimeCursor()
        cursor = recover_interrupted_model_attempt(cursor)
        cursor = recover_interrupted_external_attempt(cursor)
        query_attempts = list(run.query_attempts)
        selected_sources = [dict(item) for item in run.selected_sources]
        rejected_sources = [dict(item) for item in run.rejected_sources]
        warnings = list(run.warnings)
        execution_started = self.monotonic()
        base_elapsed = state.budget.elapsed_seconds

        def elapsed() -> float:
            return base_elapsed + max(0.0, self.monotonic() - execution_started)

        def update_budget(*, reads_used: int | None = None) -> None:
            nonlocal state
            state = replace(
                state,
                budget=replace(
                    state.budget,
                    candidates_used=min(len(cursor.candidates), state.budget.max_candidates),
                    reads_used=(state.budget.reads_used if reads_used is None else reads_used),
                    elapsed_seconds=elapsed(),
                ),
            )

        def ensure_active() -> None:
            if self.repository.cancel_requested(run_id, operation_id=operation_id):
                raise ActiveResearchCancelled("active research cancelled")

        def known_evidence_ids() -> tuple[str, ...]:
            snapshot = _evidence_snapshot(run_id, selected_sources, rejected_sources)
            return tuple(ref.id for ref in snapshot.refs)

        def checkpoint(*, stage: str | None = None) -> WebLookupRun:
            nonlocal context
            if stage is not None and self._required(run_id).stage != stage:
                self.repository.set_stage(
                    run_id,
                    stage=stage,
                    operation_id=operation_id,
                )
            update_budget()
            context = attach_runtime_cursor(context, cursor)
            context = attach_claim_engine_state(
                context,
                state,
                known_evidence_ids=known_evidence_ids(),
            )
            _update_metrics(context, state, cursor)
            persisted = self.repository.checkpoint(
                run_id,
                operation_id=operation_id,
                research_context=context,
                query_attempts=query_attempts,
                selected_sources=selected_sources,
                rejected_sources=rejected_sources,
                items=_eligible_items(selected_sources),
                warnings=_dedupe(warnings),
                provider_status="",
                stop_reason="",
                answer_confidence="",
            )
            # The repository may have merged a steering entry that arrived
            # concurrently with this checkpoint.  Keep the executor's local
            # copy aligned so the next wave boundary can consume it.
            context = dict(persisted.research_context)
            return persisted

        def refresh_steering() -> None:
            nonlocal context
            context = merge_active_steering_context(
                context,
                self._required(run_id).research_context,
            )

        def apply_pending_steering(*, wave_index: int) -> tuple[str, ...]:
            nonlocal context, state
            state, context, applied_ids = _apply_pending_active_steering(
                state,
                context,
                run_id=run_id,
                wave_index=wave_index,
                applied_at=self.utc_now(),
                known_evidence_ids=known_evidence_ids(),
            )
            return applied_ids

        def mark_pending_steering_late(reason: str) -> tuple[str, ...]:
            nonlocal context
            context, late_ids = _mark_pending_active_steering_late(
                context,
                reason=reason,
            )
            return late_ids

        def remaining_timeout() -> float:
            return max(
        1.0,
        min(
            self.model_timeout_cap_seconds,
            research_seconds_left(),
        ),
    )

        def research_seconds_left() -> float:
            """Seconds left in the research window (finalization reserve kept)."""

            return (
                state.budget.hard_timeout_seconds
                - RESEARCH_WINDOW_RESERVE_SECONDS
                - elapsed()
            )

        def research_window_exhausted() -> bool:
            return research_seconds_left() <= 0.0

        def record_research_window(exhausted: bool) -> None:
            """Phase telemetry: when research ended and how much tail remained."""

            metrics = context.setdefault(ACTIVE_RESEARCH_METRICS_KEY, {})
            metrics["research_window"] = {
                "reserve_seconds": RESEARCH_WINDOW_RESERVE_SECONDS,
                "hard_seconds": state.budget.hard_timeout_seconds,
                "deadline_elapsed": round(
                    state.budget.hard_timeout_seconds
                    - RESEARCH_WINDOW_RESERVE_SECONDS,
                    3,
                ),
                "research_elapsed_seconds": round(elapsed(), 3),
                "remaining_after_research_seconds": round(
                    state.budget.hard_timeout_seconds - elapsed(), 3
                ),
                "exhausted": exhausted,
            }
            checkpoint()

        def read_timeout_seconds() -> float:
            """Reader deadline: a page read may never outlive the window."""

            return min(READ_TIMEOUT_CAP_SECONDS, max(0.0, research_seconds_left()))

        def record_research_window_skip(key: str) -> None:
            """Count work the exhausted research window refused to start."""

            metrics = context.setdefault(ACTIVE_RESEARCH_METRICS_KEY, {})
            skips = metrics.get("research_window_skips")
            if not isinstance(skips, dict):
                skips = {}
                metrics["research_window_skips"] = skips
            skips[key] = int(skips.get(key) or 0) + 1

        phase_started: dict[str, float] = {}

        def phase_begin(phase: str) -> None:
            """Start timing one research phase (telemetry only)."""

            phase_started[phase] = self.monotonic()

        def phase_end(phase: str) -> None:
            """Accumulate wall-clock seconds per research phase (telemetry only).

            Paired performance attribution needs the research window split into
            search / assessment / read / extraction / discovery, so a later batch
            can price one action instead of guessing a constant. This never
            changes control flow: it only adds to ``metrics.phase_seconds``.
            """

            started = phase_started.pop(phase, None)
            if started is None:
                return
            metrics = context.setdefault(ACTIVE_RESEARCH_METRICS_KEY, {})
            phases = metrics.get("phase_seconds")
            if not isinstance(phases, dict):
                phases = {}
                metrics["phase_seconds"] = phases
            entry = phases.get(phase)
            if not isinstance(entry, dict):
                entry = {"seconds": 0.0, "calls": 0}
                phases[phase] = entry
            entry["seconds"] = round(
                float(entry.get("seconds") or 0.0)
                + max(0.0, self.monotonic() - started),
                6,
            )
            entry["calls"] = int(entry.get("calls") or 0) + 1

        def gateway_read(url: str, *, max_chars: int) -> dict[str, Any]:
            """Read a page, forwarding the shared deadline when supported.

            §48/§49 diagnostic (default off): bounded fetch-layer retries wrap
            the read here, where the research window is visible, so the
            ``window_aware`` mode can refuse a retry that would eat the
            finalization reserve. Success-path behaviour and content semantics
            are unchanged.
            """

            def _inner(target: str) -> Mapping[str, Any]:
                if self.read_gateway_accepts_timeout:
                    return (
                        self.gateway.read(
                            target,
                            max_chars=max_chars,
                            timeout=read_timeout_seconds(),
                        )
                        or {}
                    )
                return self.gateway.read(target, max_chars=max_chars) or {}

            mode = read_retry_mode()
            phase_begin("read")
            try:
                if mode == "off":
                    return dict(_inner(url))
                admission = None
                if mode == "window_aware":
                    # §50/B2: the same formula-based admission policy as the
                    # inventory channel; only the metrics channel differs.
                    admission = make_window_admission(
                        remaining_seconds=research_seconds_left
                    )
                payload = read_with_bounded_retry(
                    url,
                    read_fn=_inner,
                    admission=admission,
                    diagnostics_key="read_retry",
                )
                _accumulate_fetch_metrics(
                    context, "read_retry", payload.get("read_retry")
                )
                return payload
            finally:
                phase_end("read")

        def fetch_text(url: str) -> tuple[str, str, str, str]:
            """§63 inventory fetch (XML/JSON/HTML) for the domain-targeted channel.

            §50/B2: transient fetch failures are retried under the *same*
            window-aware admission policy as page reads, but accounted
            separately (``inventory_fetch``) so inventory I/O never
            contaminates read-retry statistics.
            """

            return _inventory_fetch_with_retry(
                url,
                context=context,
                remaining_seconds=research_seconds_left,
            )

        def ensure_budget() -> None:
            if elapsed() >= state.budget.hard_timeout_seconds:
                raise _HardBudgetReached

        def model_allowed(purpose: str, categories: tuple[str, ...]) -> bool:
            allowed = bool(self.policy_check(context, purpose))
            audits = [
                dict(item)
                for item in context.get(ACTIVE_RESEARCH_POLICY_AUDITS_KEY, [])
                if isinstance(item, Mapping)
            ]
            audits.append(
                {
                    "call_id": f"policy:{purpose}:{len(audits) + 1}",
                    "purpose": purpose,
                    "status": "allowed" if allowed else "blocked_by_policy",
                    "data_categories": list(categories),
                    "checked_at": self.utc_now(),
                }
            )
            context[ACTIVE_RESEARCH_POLICY_AUDITS_KEY] = audits[-100:]
            return allowed

        def on_model_started(marker: ResearchModelAttemptStart) -> None:
            nonlocal cursor
            ensure_active()
            ensure_budget()
            cursor = begin_model_attempt(cursor, marker)
            checkpoint()

        def on_model_finished(audit: ResearchModelCallAudit) -> None:
            nonlocal cursor
            # B5-H1 crash-consistency: keep the completed audit in memory only.
            # The caller persists it together with the semantic result in the
            # next checkpoint, so a crash before that checkpoint leaves the
            # durable truth as an inflight call that recovery resolves through
            # interrupted_unknown with a bounded new attempt instead of a
            # completed call_id that can never re-enter inflight.
            cursor = finish_model_attempt(cursor, audit)
            ensure_active()

        def _append_failure(
            code: ResearchFailureCode,
            phase: RuntimePhase,
            *,
            logical_call_id: str = "",
            item_id: str = "",
            detail: str = "",
            provider_code: str = "",
            exception_type: str = "",
            attempt_id: str = "",
        ) -> None:
            nonlocal cursor
            durable_attempt_id = attempt_id or f"run-attempt:{context['run_attempt']}"
            failure_id = (
                runtime_failure_id(logical_call_id=logical_call_id, code=code)
                if logical_call_id
                else runtime_failure_id_unattached(
                    phase=phase,
                    item_id=item_id,
                    attempt_id=durable_attempt_id,
                    code=code,
                )
            )
            failure = build_runtime_failure(
                failure_id=failure_id,
                code=code,
                phase=phase,
                item_id=item_id,
                detail=detail,
                provider_code=provider_code,
                exception_type=exception_type,
                attempt_id=durable_attempt_id,
            )
            cursor = replace(
                cursor,
                failures=append_runtime_failure(cursor.failures, failure),
            )

        def settle_completed_wave(
            gate: EvidenceGateResult,
            brief: Mapping[str, Any],
        ) -> WebLookupRun | None:
            """Advance or finish one gain-accounted wave exactly once."""

            nonlocal cursor
            ensure_active()
            refresh_steering()
            pending = _pending_active_steering_ids(context)
            hard_exhausted = elapsed() >= state.budget.hard_timeout_seconds
            wave_exhausted = cursor.wave_index >= MAX_RESEARCH_WAVES
            if pending and (hard_exhausted or wave_exhausted):
                mark_pending_steering_late(
                    "hard_budget_exhausted"
                    if hard_exhausted
                    else "wave_limit_reached"
                )
                checkpoint()
            elif pending:
                # A pending user direction invalidates completion computed from
                # the pre-steering graph.  Apply it exactly once and advance to
                # the next bounded wave without mutating the user's budget.
                next_wave = cursor.wave_index + 1
                apply_pending_steering(wave_index=next_wave)
                cursor = replace(
                    cursor,
                    wave_index=next_wave,
                    wave_id="",
                    active_gap_ids=(),
                    phase="searching",
                )
                checkpoint()
                return None
            # Settlement must use the same actionable scope as planning.
            # Context gaps are deliberately deferred by _ordered_gaps(); they
            # therefore cannot keep an otherwise saturated active run alive.
            open_gap_claims = {gap.claim_id for gap in _ordered_gaps(state)}
            extra_batch_claims = {
                claim.id for claim in state.claims if claim.priority == "critical"
            } | {conflict.claim_id for conflict in state.conflict_gaps}
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

            # P1-C batch 3: the single stop truth lives in ResearchStopGate.
            # The executor derives durable signals and never decides a stop
            # reason itself; the frozen priority (gate pass > hard budget >
            # no actionable gaps > saturation > wave ceiling > continue) is
            # locked inside the gate.  Whether a late steering blocks the old
            # graph's gate pass is recomputed from the merged durable context
            # (steering status=late is durable truth), never from the return
            # value of this invocation's mark call - a crash between the late
            # checkpoint and the terminal complete must resume to the same
            # decision.
            unapplied_steering = _unapplied_steering_blocks_completion(context)
            stop = ResearchStopGate.evaluate(
                ResearchStopSignal(
                    gate_pass=gate.status == "pass",
                    hard_budget_exhausted=(
                        hard_exhausted
                    ),
                    has_actionable_gaps=(
                        bool(open_gap_claims) or unapplied_steering
                    ),
                    all_actionable_saturated=bool(open_gap_claims)
                    and open_gap_claims <= saturated_claims,
                    wave_limit_reached=wave_exhausted,
                    has_evidence=bool(state.evidence),
                    unapplied_steering_blocks_completion=unapplied_steering,
                )
            )
            if stop.decision == "continue":
                cursor = replace(
                    cursor,
                    wave_index=cursor.wave_index + 1,
                    wave_id="",
                    active_gap_ids=(),
                    phase="searching",
                )
                checkpoint()
                return None

            cursor = replace(
                cursor,
                phase="completed" if stop.decision == "success" else "unavailable",
            )
            checkpoint()
            return self.repository.complete(
                run_id,
                operation_id=operation_id,
                items=_eligible_items(selected_sources),
                source_block=_format_evidence_brief(brief),
                warnings=_dedupe(warnings),
                research_context=context,
                query_attempts=query_attempts,
                selected_sources=selected_sources,
                rejected_sources=rejected_sources,
                provider_status=stop.provider_status,
                stop_reason=stop.reason,
                answer_confidence=stop.answer_confidence,
                final_status=stop.final_status,
            )

        try:
            ensure_active()
            checkpoint()

            # Bootstrap an empty active state through the audited model boundary.
            if not state.claims:
                cursor = replace(cursor, phase="planning")
                checkpoint(stage="planned")
                categories = ("public_research_question", "research_time_context")
                if not model_allowed("research_claim_planning", categories):
                    _append_failure(
                        "policy_blocked",
                        "planning",
                        logical_call_id=f"policy:research_claim_planning:{run_id}",
                        item_id="research_claim_planning",
                        detail="blocked_by_policy",
                    )
                    return self._terminal_unavailable(
                        run_id,
                        operation_id=operation_id,
                        context=context,
                        cursor=cursor,
                        state=state,
                        query_attempts=query_attempts,
                        selected_sources=selected_sources,
                        rejected_sources=rejected_sources,
                        warnings=warnings,
                        reason="claim_planning_blocked_by_policy",
                    )
                planning_logical_call_id = f"research_claim_plan:{run.id}:1"
                try:
                    planning_attempt_start = _model_attempt_start(
                        cursor,
                        planning_logical_call_id,
                    )
                except _ModelAttemptBudgetExhausted:
                    _append_failure(
                        "model_attempts_exhausted",
                        "planning",
                        logical_call_id=planning_logical_call_id,
                        item_id="research_claim_planning",
                        detail="model_call_attempts_exhausted",
                    )
                    checkpoint()
                    return self._terminal_unavailable(
                        run_id,
                        operation_id=operation_id,
                        context=context,
                        cursor=cursor,
                        state=state,
                        query_attempts=query_attempts,
                        selected_sources=selected_sources,
                        rejected_sources=rejected_sources,
                        warnings=warnings,
                        reason="claim_plan_unavailable",
                    )
                bootstrap = self.claim_planner.plan(
                    run_id=run_id,
                    question=run.query,
                    reference_date=state.reference_date or _utc_date(),
                    budget=state.budget,
                    mode="active",
                    timeout_seconds=remaining_timeout(),
                    on_attempt_started=on_model_started,
                    on_attempt_finished=on_model_finished,
                    attempt_start=planning_attempt_start,
                )
                ensure_active()
                if not bootstrap.completed or bootstrap.state is None:
                    planning_reason = bootstrap.reason or "claim_plan_unavailable"
                    planning_code: ResearchFailureCode = (
                        "model_attempts_exhausted"
                        if planning_reason == "model_call_attempts_exhausted"
                        else "claim_planning_failed"
                    )
                    _append_failure(
                        planning_code,
                        "planning",
                        logical_call_id=f"research_claim_plan:{run.id}:1",
                        detail=planning_reason,
                    )
                    checkpoint()
                    return self._terminal_unavailable(
                        run_id,
                        operation_id=operation_id,
                        context=context,
                        cursor=cursor,
                        state=state,
                        query_attempts=query_attempts,
                        selected_sources=selected_sources,
                        rejected_sources=rejected_sources,
                        warnings=warnings,
                        reason="claim_plan_unavailable",
                    )
                state = bootstrap.state
                # B5-H1: persist the completed model audit together with the
                # semantic result it produced (single checkpoint boundary).
                checkpoint()

            # P1-C batch 2: bounded multi-wave loop. Each wave durably plans
            # queries for the still-open gaps, searches, assesses, reads,
            # extracts and gates; the frozen Evidence Gain / Saturation
            # contracts decide whether another wave runs. Every wave boundary
            # is checkpointed, and a crash resumes inside the durable wave
            # (completed queries/reads/extractions are never repeated).
            # §37B-selection: diagnostic provenance only. The collector records
            # decisions the existing pipeline already makes; it never changes
            # ordering, budgets or the cursor, and its payload lives in the run
            # metrics (resume-safe hydration from a previous process payload).
            raw_metrics = context.get(ACTIVE_RESEARCH_METRICS_KEY)
            previous_trace = (
                raw_metrics.get("selection_trace")
                if isinstance(raw_metrics, Mapping)
                else None
            )
            selection_trace = SelectionTraceCollector.from_payload(previous_trace)
            while True:                # Research Window Deadline Hardening: the research window is an
                # absolute boundary. Once it is exhausted the tail belongs to
                # finalization (Gate, answer synthesis, claim binding,
                # serialization), so no new wave starts.
                if research_window_exhausted():
                    record_research_window(exhausted=True)
                    raise _HardBudgetReached
                if cursor.wave_index == 0:
                    cursor = replace(cursor, wave_index=1)
                    refresh_steering()
                    if _pending_active_steering_ids(context):
                        ensure_budget()
                        apply_pending_steering(wave_index=1)
                    checkpoint()
                wave_id = f"research_wave:{run_id}:{cursor.wave_index}"

                # A crash after gain/saturation persisted but before terminal
                # settlement must not account the same wave twice.
                if len(cursor.gain_history) >= cursor.wave_index:
                    gate = evaluate_evidence_gate(state)
                    brief = _evidence_brief(state, gate, selected_sources)
                    context[ACTIVE_RESEARCH_BRIEF_KEY] = brief
                    record_research_window(
                        exhausted=research_window_exhausted()
                    )
                    settled = settle_completed_wave(gate, brief)
                    if settled is not None:
                        return settled
                    continue

                # Wave start marker (durable): freeze the wave identity, the
                # gaps this wave decided to attempt (handled-truth, even when
                # the planner only produces duplicate queries or search finds
                # nothing new), and the baseline state snapshot the wave's
                # Evidence Gain will be evaluated against. Crash after this
                # checkpoint resumes the same wave with an intact baseline, so
                # extraction persisted before a crash can never be lost to a
                # reset baseline (no false no-gain).
                if cursor.wave_id != wave_id:
                    active_gap_ids = tuple(gap.id for gap in _ordered_gaps(state))
                    cursor = replace(
                        cursor,
                        wave_id=wave_id,
                        active_gap_ids=active_gap_ids,
                    )
                    context[ACTIVE_RESEARCH_WAVE_BASELINE_KEY] = state.to_dict()
                    checkpoint()
                baseline_raw = context.get(ACTIVE_RESEARCH_WAVE_BASELINE_KEY)
                if not isinstance(baseline_raw, Mapping):
                    raise ValueError("active wave baseline is unavailable")
                wave_baseline = ResearchState.from_dict(
                    baseline_raw,
                    known_evidence_ids=tuple(
                        item["evidence_id"]
                        for item in baseline_raw.get("evidence", [])
                        if isinstance(item, Mapping)
                        and isinstance(item.get("evidence_id"), str)
                    ),
                )
                # Semantic query identity is stable across waves. Re-entering a
                # wave or reaching a later wave must not re-search the same text;
                # no new query space is handled as a no-gain batch by Saturation.
                cursor = _append_gap_queries(cursor, state)
                cursor = replace(cursor, phase="searching")
                checkpoint(stage="searching")

                if self._required(run_id).stage != "searching":
                    self.repository.set_stage(
                        run_id,
                        stage="searching",
                        operation_id=operation_id,
                    )

                # Search every still-pending planned query until the shared hard budget.
                for planned in cursor.planned_queries:
                    if planned.id in cursor.completed_query_ids:
                        continue
                    ensure_active()
                    if elapsed() >= state.budget.hard_timeout_seconds:
                        break
                    # B5-H2: once the candidate pool is full, further external
                    # searches can only burn shared budget on results that would
                    # be dropped by the pool cap, so stop before any external call.
                    if len(cursor.candidates) >= state.budget.max_candidates:
                        break
                    try:
                        attempt = _attempt_number(cursor, planned.id)
                    except _ExternalAttemptBudgetExhausted:
                        _append_failure(
                            "search_failed",
                            "searching",
                            logical_call_id=(
                                f"research_search:{run_id}:{planned.id}:attempts_exhausted"
                            ),
                            item_id=planned.id,
                            detail="external_attempts_exhausted",
                        )
                        cursor = replace(
                            cursor,
                            query_outcomes=(
                                *cursor.query_outcomes,
                                RuntimeQueryOutcome(
                                    query_id=planned.id,
                                    status="unavailable",
                                    result_count=0,
                                    error_code="search_failed",
                                ),
                            ),
                        )
                        query_attempts.append(
                            {
                                "query": planned.query,
                                "query_id": planned.id,
                                "intent": planned.intent,
                                "status": "unavailable",
                                "reason": "external_attempts_exhausted",
                                "result_count": 0,
                                "providers_attempted": [],
                                "provider_errors": [],
                                "run_attempt": context["run_attempt"],
                                "operation_id": operation_id,
                                "influenced_by_steering": bool(
                                    _steering_ids_for_claim(context, planned.claim_id)
                                ),
                                "steering_ids": list(
                                    _steering_ids_for_claim(context, planned.claim_id)
                                ),
                            }
                        )
                        checkpoint()
                        continue
                    marker = RuntimeExternalAttemptStart(
                        call_id=f"research_search:{run_id}:{planned.id}:attempt:{attempt}",
                        purpose="search",
                        item_id=planned.id,
                        attempt=attempt,
                        started_at=self.utc_now(),
                    )
                    cursor = begin_external_attempt(cursor, marker)
                    checkpoint()

                    audit: dict[str, Any] | None = None

                    def search_exact(query: str, *, max_results: int = 5) -> Mapping[str, Any]:
                        nonlocal audit
                        # Deadline-aware provider policy: reserve the tail of the
                        # shared hard budget for assessment/read/answer so a
                        # degraded provider cannot consume the entire budget.
                        remaining = state.budget.hard_timeout_seconds - elapsed()
                        search_deadline = self.monotonic() + max(
                            0.0,
                            remaining - RESEARCH_WINDOW_RESERVE_SECONDS,
                        )
                        try:
                            phase_begin("search")
                            payload = self.gateway.search_detailed(
                                query,
                                max_items=max_results,
                                deadline=search_deadline,
                            )
                            audit = self.gateway.last_search_audit()
                            # §37A observability (diagnostic only): record the
                            # actually-issued query and the provider's bounded
                            # results. This never changes search behaviour,
                            # ordering, budgets or eligibility.
                            _search_intent, _search_variants = _deeper_targeting_inputs(
                                context
                            )
                            record_search_call(
                                context,
                                metrics_key=ACTIVE_RESEARCH_METRICS_KEY,
                                slot_index=_search_discovery_slot(context),
                                query=query,
                                claim_id=str(getattr(planned, "claim_id", "") or ""),
                                intent=_search_intent,
                                variants=_search_variants,
                                hint_terms=_lead_hints_for_claim(
                                    cursor,
                                    str(getattr(planned, "claim_id", "") or ""),
                                )[1],
                                results=(
                                    payload.get("results")
                                    if isinstance(payload, Mapping)
                                    else ()
                                ),
                            )
                            return payload
                        finally:
                            phase_end("search")

                    one_query = _gap_query_batch(planned)
                    try:
                        batch_result = execute_candidate_pool_batch(
                            one_query,
                            search_exact=search_exact,
                            should_cancel=lambda: self.repository.cancel_requested(
                                run_id, operation_id=operation_id
                            ),
                            results_per_query=5,
                            max_candidates=state.budget.max_candidates,
                            trace=selection_trace,
                        )
                    finally:
                        cursor = finish_external_attempt(cursor, call_id=marker.call_id)
                        checkpoint()
                    ensure_active()
                    outcome = batch_result.outcomes[0]
                    if outcome.status == "unavailable":
                        _append_failure(
                            "search_failed",
                            "searching",
                            logical_call_id=marker.call_id,
                            item_id=planned.id,
                            detail=outcome.reason or "search_unavailable",
                            provider_code=";".join(outcome.provider_errors),
                            attempt_id=marker.call_id,
                        )
                    cursor = replace(
                        cursor,
                        query_outcomes=(
                            *cursor.query_outcomes,
                            RuntimeQueryOutcome(
                                query_id=planned.id,
                                status=_runtime_query_status(outcome.status),
                                result_count=outcome.result_count,
                                providers=outcome.providers_attempted,
                                error_code=(
                                    "search_failed"
                                    if outcome.status == "unavailable"
                                    else ""
                                ),
                            ),
                        ),
                        candidates=_merge_runtime_candidates(
                            cursor.candidates,
                            batch_result.candidates,
                            max_candidates=state.budget.max_candidates,
                            trace=selection_trace,
                        ),
                    )
                    query_attempts.append(
                        {
                            "query": planned.query,
                            "query_id": planned.id,
                            "intent": planned.intent,
                            "status": outcome.status,
                            "reason": outcome.reason,
                            "result_count": outcome.result_count,
                            "providers_attempted": list(outcome.providers_attempted),
                            "provider_errors": list(outcome.provider_errors),
                            "run_attempt": context["run_attempt"],
                            "operation_id": operation_id,
                            "influenced_by_steering": bool(
                                _steering_ids_for_claim(context, planned.claim_id)
                            ),
                            "steering_ids": list(
                                _steering_ids_for_claim(context, planned.claim_id)
                            ),
                            **({"provider_audit": {"schema_version": "research-provider-audit-v1", **audit}} if audit else {}),
                        }
                    )
                    checkpoint()

                cursor = replace(cursor, phase="assessing")
                checkpoint(stage="assessing")

                # Strict semantic assessment and role-aware ranking, one claim at a time.
                stored_assessments = _assessment_store(context)
                assessed_inputs = _assessment_inputs_store(context)
                claim_rankings: dict[str, tuple[RankedCandidate, ...]] = {}
                for claim in _ordered_claims(state):
                    claim_candidates = _candidates_for_claim(cursor, claim.id)
                    if not claim_candidates:
                        continue
                    saved = stored_assessments.get(claim.id)
                    saved_ranked = (
                        tuple(_ranked_from_dict(item) for item in saved)
                        if isinstance(saved, list) and saved
                        else ()
                    )
                    if saved_ranked:
                        claim_rankings[claim.id] = saved_ranked
                    saved_candidate_ids = {
                        item.candidate.id for item in saved_ranked
                    }
                    clusters = cluster_candidate_sources(claim_candidates)
                    assignments = {item.candidate_id: item for item in clusters.assignments}
                    for claim_candidate in claim_candidates:
                        assignment = assignments.get(claim_candidate.id)
                        selection_trace.note_pool_entered(
                            claim_candidate.canonical_url,
                            pool_class=str(
                                getattr(assignment, "cluster_id", "") or ""
                            ),
                        )
                    candidates = _select_assessment_window(
                        claim_candidates,
                        claim=claim,
                        assignments=assignments,
                        max_reads=state.budget.max_reads,
                        excluded_candidate_ids=frozenset(
                            {*cursor.completed_read_ids, *saved_candidate_ids}
                        ),
                        trace=selection_trace,
                        context=context,
                        model_gateway=self.model_gateway,
                        run_id=run_id,
                        wave_index=cursor.wave_index,
                        timeout_seconds=remaining_timeout(),
                    )
                    if not candidates:
                        continue
                    assessment_assignments = {
                        item.id: assignments[item.id] for item in candidates
                    }
                    candidate_ids = tuple(sorted(item.id for item in candidates))
                    # Assess only a new, unread cluster-diverse window. Prior
                    # rankings remain durable inputs for scheduling and crash
                    # recovery; successful later windows are merged and
                    # reranked instead of replacing those bindings.
                    ensure_budget()
                    categories = ("public_research_claim", "public_candidate_metadata")
                    assessment_logical_call_id = (
                        f"research_candidate_assessment:{run_id}:{claim.id}:1"
                        f"{_assessment_call_suffix(cursor, claim.id, candidate_ids)}"
                    )
                    if not model_allowed("research_candidate_assessment", categories):
                        _append_failure(
                            "policy_blocked",
                            "assessing",
                            logical_call_id=f"policy:{assessment_logical_call_id}",
                            item_id=claim.id,
                            detail="blocked_by_policy",
                        )
                        checkpoint()
                        continue
                    try:
                        assessment_attempt_start = _model_attempt_start(
                            cursor,
                            assessment_logical_call_id,
                        )
                    except _ModelAttemptBudgetExhausted:
                        # Both attempts for this exact durable assessment may
                        # already have failed before the process exited. Resume
                        # that claim through the normal unavailable/no-gain path;
                        # attempt exhaustion is not a whole-runtime failure and
                        # must never create a third physical model call.
                        _append_failure(
                            "model_attempts_exhausted",
                            "assessing",
                            logical_call_id=assessment_logical_call_id,
                            item_id=claim.id,
                            detail="model_call_attempts_exhausted",
                        )
                        checkpoint()
                        continue
                    phase_begin("assessment")
                    try:
                        assessed = self.candidate_assessor.assess(
                            run_id=run_id,
                            claim=claim,
                            candidates=candidates,
                            assignments=assessment_assignments,
                            reference_date=state.reference_date,
                            timeout_seconds=remaining_timeout(),
                            on_attempt_started=on_model_started,
                            on_attempt_finished=on_model_finished,
                            call_id_suffix=_assessment_call_suffix(
                                cursor, claim.id, candidate_ids
                            ),
                            attempt_start=assessment_attempt_start,
                        )
                    finally:
                        phase_end("assessment")
                    ensure_active()
                    if assessed.status != "completed" or not assessed.assessments:
                        assessment_reason = (
                            assessed.reason or "candidate_assessment_unavailable"
                        )
                        assessment_code: ResearchFailureCode = (
                            "model_attempts_exhausted"
                            if assessment_reason == "model_call_attempts_exhausted"
                            else "assessment_failed"
                        )
                        _append_failure(
                            assessment_code,
                            "assessing",
                            logical_call_id=assessment_logical_call_id,
                            item_id=claim.id,
                            detail=assessment_reason,
                        )
                        checkpoint()
                        continue
                    merged_assessments = {
                        item.candidate.id: item.assessment for item in saved_ranked
                    }
                    merged_assessments.update(assessed.assessments)
                    ranked_candidates = tuple(
                        item
                        for item in claim_candidates
                        if item.id in merged_assessments
                    )
                    ranked = rank_candidate_pool(
                        ranked_candidates,
                        claim=claim,
                        assessments=merged_assessments,
                    )
                    for rank_position, ranked_item in enumerate(ranked, start=1):
                        selection_trace.note_scheduler_rank(
                            ranked_item.candidate.canonical_url,
                            rank=rank_position,
                        )
                    claim_rankings[claim.id] = ranked
                    stored_assessments[claim.id] = [item.to_dict() for item in ranked]
                    assessed_inputs[claim.id] = sorted(merged_assessments)
                    context[ACTIVE_RESEARCH_ASSESSMENTS_KEY] = stored_assessments
                    context[ACTIVE_RESEARCH_ASSESSMENT_INPUTS_KEY] = assessed_inputs
                    # §45 Tier-2 (default off): when Tier-1 produced candidates
                    # but none is answer-relevant, one bounded proposal call may
                    # add reader-verified candidates with llm_proposed provenance.
                    proposed_claim_ids = context.setdefault(
                        TIER2_PROPOSED_CLAIMS_KEY, []
                    )
                    if isinstance(proposed_claim_ids, list):
                        cursor = _tier2_proposal_step(
                            cursor=cursor,
                            state=state,
                            claim=claim,
                            assessments=merged_assessments,
                            model_gateway=self.model_gateway,
                            read_fn=gateway_read,
                            context=context,
                            run_id=run_id,
                            wave_index=cursor.wave_index,
                            timeout_seconds=remaining_timeout(),
                            proposed_claim_ids=proposed_claim_ids,
                        )
                    # §63 Tier-1.5 (default off): official-domain site search
                    # as a second, deterministic discovery channel.
                    targeted_claim_ids = context.setdefault(
                        DOMAIN_TARGETED_CLAIMS_KEY, []
                    )
                    if isinstance(targeted_claim_ids, list):
                        cursor = _domain_targeted_step(
                            cursor=cursor,
                            state=state,
                            claim=claim,
                            assessments=merged_assessments,
                            model_gateway=self.model_gateway,
                            fetch_text=fetch_text,
                            read_fn=gateway_read,
                            context=context,
                            run_id=run_id,
                            wave_index=cursor.wave_index,
                            timeout_seconds=remaining_timeout(),
                            targeted_claim_ids=targeted_claim_ids,
                            seconds_left=research_seconds_left,
                        )
                    checkpoint()

                cursor = replace(cursor, phase="ranking")
                checkpoint(stage="assessing")

                # P1-C batch 2: the read plan is recomputed at the start of every
                # wave (deterministic from the current rankings); candidates whose
                # physical read already completed are skipped by the read loop via
                # completed_read_ids, so recomputation is resume-safe.
                # P1-C batch 2: the read plan is recomputed at the start of
                # every wave from the full rankings. PHYSICAL reads exclude
                # candidates whose read already completed (otherwise a later
                # wave re-selects the same already-read top candidates and
                # never reads anything new); extraction targets keep every
                # (candidate, claim) binding so an already-read candidate whose
                # extraction crashed mid-wave is re-extracted on resume (the
                # per-claim prior status skips completed extractions).
                # P1-C batch 2: the read plan is recomputed at the start of
                # every wave from the rankings MINUS candidates whose physical
                # read already completed (otherwise a later wave re-selects the
                # same already-read top candidates and never reads anything new).
                # Extraction targets additionally keep already-read candidates
                # whose extraction crashed mid-wave so resume re-extracts them
                # (per-claim prior status skips completed extractions).
                completed_read = set(cursor.completed_read_ids)
                # Covered clusters are run-level CUMULATIVE durable truth. The
                # durable map is read back, merged with every claim bound to a
                # successfully read source, and written back - never rebuilt
                # from scratch and overwritten. One physical read serves
                # multiple claims (H3), but a source record's assessment only
                # names the claim that triggered the read; the record's
                # extraction map holds every claim actually bound to it, so
                # coverage must merge the owner claim AND all extraction-map
                # keys, or a secondary claim forgets the cluster (H8).
                raw_covered = context.get(ACTIVE_RESEARCH_COVERED_CLUSTERS_KEY)
                covered_clusters_by_claim: dict[str, set[str]] = {}
                if isinstance(raw_covered, Mapping):
                    for claim_id, cluster_ids in raw_covered.items():
                        if isinstance(cluster_ids, (list, tuple, set)):
                            covered_clusters_by_claim[str(claim_id)] = {
                                str(item) for item in cluster_ids
                            }
                for covered_record in selected_sources:
                    if covered_record.get("read_status") != "read":
                        continue
                    assessment = covered_record.get("assessment")
                    if not isinstance(assessment, Mapping):
                        continue
                    bound_cluster = assessment.get("source_cluster_id")
                    if not bound_cluster:
                        continue
                    bound_claims: set[str] = set()
                    owner_claim = assessment.get("claim_id")
                    if owner_claim:
                        bound_claims.add(str(owner_claim))
                    extraction_map = covered_record.get("extractions")
                    if isinstance(extraction_map, Mapping):
                        bound_claims.update(
                            str(item)
                            for item in extraction_map
                            if isinstance(item, str)
                        )
                    for claim_id in bound_claims:
                        covered_clusters_by_claim.setdefault(
                            claim_id, set()
                        ).add(str(bound_cluster))
                context[ACTIVE_RESEARCH_COVERED_CLUSTERS_KEY] = {
                    claim_id: sorted(cluster_ids)
                    for claim_id, cluster_ids in sorted(
                        covered_clusters_by_claim.items()
                    )
                }
                rankings_for_plan = {
                    claim_id: tuple(
                        ranked_candidate
                        for ranked_candidate in ranked
                        if ranked_candidate.candidate.id not in completed_read
                    )
                    for claim_id, ranked in claim_rankings.items()
                }
                physical_reads, extraction_targets = _fair_read_plan(
                    state,
                    rankings_for_plan,
                    covered_cluster_ids_by_claim=covered_clusters_by_claim,
                    trace=selection_trace,
                    diagnostics=context.setdefault(
                        ACTIVE_RESEARCH_METRICS_KEY, {}
                    ),
                )
                # Already-read candidates whose extraction crashed mid-wave
                # stay extractable on resume, but physical reuse never bypasses
                # per-claim eligibility. Rebuild each binding from that claim's
                # own full ranking and shared scheduler predicate; the
                # per-claim extraction prior skips work already finished.
                extraction_targets = _restore_completed_read_targets(
                    extraction_targets,
                    completed_read_ids=completed_read,
                    rankings=claim_rankings,
                )
                # §39 atomic routing (default off): a read artifact also serves
                # factual claims that still lack support, bounded per read and
                # per wave. Comparison/analytical claims are never routed: their
                # support belongs to synthesis over atomic facts, never to a
                # single-page extraction.
                routed_pairs: set[tuple[str, str]] = set()
                if atomic_routing_enabled():
                    routing_read_ids = frozenset(
                        str(record.get("candidate_id") or "")
                        for record in selected_sources
                        if str(record.get("read_status") or "") == "read"
                    )
                    supported_ids = frozenset(
                        link.claim_id
                        for link in state.evidence_links
                        if link.relation == "supports"
                    )
                    extraction_targets, routing_records = route_missing_atomic_claims(
                        extraction_targets,
                        claims=state.claims,
                        supported_claim_ids=supported_ids,
                        read_candidate_ids=routing_read_ids,
                    )
                    routed_pairs = {
                        (str(record["read_artifact_id"]), claim_id)
                        for record in routing_records
                        for claim_id in record.get("routed_claim_ids") or []
                    }
                    routing_metrics = context.setdefault(
                        ACTIVE_RESEARCH_METRICS_KEY, {}
                    )
                    if isinstance(routing_metrics, dict):
                        existing_routing = routing_metrics.get("atomic_routing")
                        existing_routing = (
                            existing_routing
                            if isinstance(existing_routing, list)
                            else []
                        )
                        for record in routing_records:
                            existing_routing.append(
                                {"wave_index": cursor.wave_index, **record}
                            )
                        routing_metrics["atomic_routing"] = existing_routing[-60:]
                context[ACTIVE_RESEARCH_READ_PLAN_KEY] = {
                    "physical_reads": physical_reads,
                    "extraction_targets": extraction_targets,
                }
                cursor = replace(
                    cursor,
                    phase="reading",
                    planned_read_ids=tuple(item["candidate_id"] for item in physical_reads),
                )
                checkpoint(stage="reading")

                if self._required(run_id).stage != "reading":
                    self.repository.set_stage(
                        run_id,
                        stage="reading",
                        operation_id=operation_id,
                    )

                # Read and checkpoint each selected source under the shared character budget.
                used_chars = sum(
                    int(item.get("content_chars") or 0)
                    for item in context.get(ACTIVE_RESEARCH_METRICS_KEY, {}).get("reads", [])
                    if isinstance(item, Mapping)
                )
                successful_reads = state.budget.reads_used
                read_loop_stop_reason = ""
                dispatched_read_ids: set[str] = set()
                for plan_item in physical_reads:
                    candidate_id = plan_item["candidate_id"]
                    if candidate_id in cursor.completed_read_ids:
                        try:
                            selection_trace.note_already_read(
                                _candidate_by_id(cursor, candidate_id).canonical_url
                            )
                        except ValueError:
                            pass
                        continue
                    ensure_active()
                    if successful_reads >= state.budget.max_reads or used_chars >= state.budget.max_total_chars:
                        read_loop_stop_reason = "read_budget_exhausted"
                        break
                    if research_seconds_left() < MIN_READ_SECONDS:
                        # The window cannot absorb a useful read; stop starting
                        # reads instead of overrunning the finalization reserve.
                        read_loop_stop_reason = "research_window_closed"
                        record_research_window_skip(
                            "read_skipped_insufficient_research_window"
                        )
                        break
                    ensure_budget()
                    candidate = _candidate_by_id(cursor, candidate_id)
                    source_limit = min(6000, state.budget.max_total_chars - used_chars)
                    try:
                        attempt = _attempt_number(cursor, candidate_id)
                    except _ExternalAttemptBudgetExhausted:
                        _append_failure(
                            "read_failed",
                            "reading",
                            logical_call_id=(
                                f"research_read:{run_id}:{candidate_id}:attempts_exhausted"
                            ),
                            item_id=candidate_id,
                            detail="external_attempts_exhausted",
                        )
                        cursor = replace(
                            cursor,
                            read_outcomes=(
                                *cursor.read_outcomes,
                                RuntimeReadOutcome(
                                    candidate_id=candidate_id,
                                    status="failed",
                                    error_code="read_failed",
                                ),
                            ),
                        )
                        record = _source_record(
                            candidate,
                            plan_item,
                            raw_read={
                                "ok": False,
                                "status": "failed",
                                "url": candidate.url,
                                "error": "external_attempts_exhausted",
                                "content": "",
                            },
                        )
                        _upsert_source(selected_sources, record)
                        context.setdefault(ACTIVE_RESEARCH_METRICS_KEY, {})["reads"] = [
                            outcome.to_dict() for outcome in cursor.read_outcomes
                        ]
                        checkpoint()
                        continue
                    marker = RuntimeExternalAttemptStart(
                        call_id=f"research_read:{run_id}:{candidate_id}:attempt:{attempt}",
                        purpose="read",
                        item_id=candidate_id,
                        attempt=attempt,
                        started_at=self.utc_now(),
                    )
                    selection_trace.note_read(candidate.canonical_url, dispatched=True)
                    dispatched_read_ids.add(candidate_id)
                    cursor = begin_external_attempt(cursor, marker)
                    checkpoint()
                    read_exception_type = ""
                    try:
                        raw_read = gateway_read(candidate.url, max_chars=source_limit)
                    except Exception as exc:
                        read_exception_type = type(exc).__name__
                        raw_read = {
                            "ok": False,
                            "status": "failed",
                            "url": candidate.url,
                            "error": type(exc).__name__,
                        }
                    finally:
                        cursor = finish_external_attempt(cursor, call_id=marker.call_id)
                        checkpoint()
                    ensure_active()
                    content = str(raw_read.get("content") or raw_read.get("readme") or "")[:source_limit]
                    ok = bool(raw_read.get("ok") is True and content.strip())
                    status = "success" if ok else "failed"
                    if not ok:
                        _append_failure(
                            "read_failed",
                            "reading",
                            logical_call_id=marker.call_id,
                            item_id=candidate_id,
                            detail=_bounded_text(
                                raw_read.get("error") or "read_failed", 2000
                            ),
                            provider_code=_bounded_text(
                                raw_read.get("error_code"), 200
                            ),
                            exception_type=read_exception_type,
                            attempt_id=marker.call_id,
                        )
                    if ok:
                        successful_reads += 1
                        used_chars += len(content)
                    cursor = replace(
                        cursor,
                        read_outcomes=(
                            *cursor.read_outcomes,
                            RuntimeReadOutcome(
                                candidate_id=candidate_id,
                                status=status,
                                content_chars=len(content) if ok else 0,
                                error_code="" if ok else "read_failed",
                            ),
                        ),
                    )
                    record = _source_record(
                        candidate,
                        plan_item,
                        raw_read={**raw_read, "content": content, "status": "read" if ok else "failed"},
                    )
                    _upsert_source(selected_sources, record)
                    update_budget(reads_used=successful_reads)
                    context.setdefault(ACTIVE_RESEARCH_METRICS_KEY, {})["reads"] = [
                        outcome.to_dict() for outcome in cursor.read_outcomes
                    ]
                    checkpoint()

                if read_loop_stop_reason:
                    # Observed loop-level stop: every planned candidate after the
                    # break shares the same recorded cause; none of them was
                    # dispatched, and the run never reconsiders them this wave.
                    for plan_item in physical_reads:
                        leftover_id = plan_item["candidate_id"]
                        if leftover_id in dispatched_read_ids:
                            continue
                        if leftover_id in cursor.completed_read_ids:
                            continue
                        try:
                            leftover_url = _candidate_by_id(
                                cursor, leftover_id
                            ).canonical_url
                        except ValueError:
                            continue
                        selection_trace.note_read(
                            leftover_url,
                            dispatched=False,
                            skip_reason=read_loop_stop_reason,
                        )
                _flush_selection_trace(context, selection_trace)

                # Slice 1: bounded lead discovery. A lead read is a discovery
                # action, never an evidence read: it runs strictly after the
                # evidence reads, at most one per wave and at most
                # MAX_LEAD_READS_PER_RUN per run, and it spends the same shared
                # read/model budget. Its output can never become eligible
                # evidence (separate typed contract).
                discovery_assets_before_lead = sum(
                    1
                    for item in cursor.candidates
                    if _is_discovery_candidate(item)
                )
                discoveries_before_lead = len(cursor.lead_discoveries)
                followups_before_lead = len(cursor.evidence_lead_followups)
                lead_budget_available = (
                    len(cursor.lead_read_ids) < MAX_LEAD_READS_PER_RUN
                )
                lead_plan = _lead_read_plan(
                    state,
                    claim_rankings,
                    completed_read_ids=cursor.completed_read_ids,
                    lead_read_ids=cursor.lead_read_ids,
                    lead_budget_available=lead_budget_available,
                )
                if not lead_plan:
                    _bump_lead_metric(
                        context,
                        "insufficient_budget"
                        if not lead_budget_available
                        else "no_lead_candidate",
                    )
                for lead_item in lead_plan:
                    if len(cursor.lead_read_ids) >= MAX_LEAD_READS_PER_RUN:
                        break
                    if (
                        successful_reads >= state.budget.max_reads
                        or used_chars >= state.budget.max_total_chars
                    ):
                        break
                    if research_seconds_left() < MIN_READ_SECONDS:
                        # Bounded lead reads obey the same shared window as
                        # evidence reads; an exhausted window starts none.
                        record_research_window_skip(
                            "lead_read_skipped_insufficient_research_window"
                        )
                        break
                    lead_candidate = lead_item["candidate"]
                    lead_candidate_id = lead_candidate.id
                    ensure_active()
                    ensure_budget()
                    lead_source_limit = min(
                        6000, state.budget.max_total_chars - used_chars
                    )
                    lead_attempt = _attempt_number(
                        cursor, f"lead:{lead_candidate_id}"
                    )
                    lead_marker = RuntimeExternalAttemptStart(
                        call_id=(
                            f"research_lead_read:{run_id}:{lead_candidate_id}"
                            f":attempt:{lead_attempt}"
                        ),
                        purpose="read",
                        item_id=f"lead:{lead_candidate_id}",
                        attempt=lead_attempt,
                        started_at=self.utc_now(),
                    )
                    cursor = begin_external_attempt(cursor, lead_marker)
                    _bump_lead_metric(context, "lead_read_started")
                    checkpoint()
                    lead_read_exception = ""
                    try:
                        raw_lead_read = gateway_read(
                            lead_candidate.url, max_chars=lead_source_limit
                        )
                    except Exception as exc:
                        lead_read_exception = type(exc).__name__
                        raw_lead_read = {
                            "ok": False,
                            "status": "failed",
                            "url": lead_candidate.url,
                            "error": type(exc).__name__,
                        }
                    finally:
                        cursor = finish_external_attempt(
                            cursor, call_id=lead_marker.call_id
                        )
                        checkpoint()
                    ensure_active()
                    lead_content = str(
                        raw_lead_read.get("content")
                        or raw_lead_read.get("readme")
                        or ""
                    )[:lead_source_limit]
                    cursor = replace(
                        cursor,
                        lead_read_ids=(*cursor.lead_read_ids, lead_candidate_id),
                    )
                    if not (
                        raw_lead_read.get("ok") is True and lead_content.strip()
                    ):
                        _append_failure(
                            "read_failed",
                            "reading",
                            logical_call_id=lead_marker.call_id,
                            item_id=lead_candidate_id,
                            detail=_bounded_text(
                                raw_lead_read.get("error") or "lead_read_failed",
                                2000,
                            ),
                            exception_type=lead_read_exception,
                            attempt_id=lead_marker.call_id,
                        )
                        _bump_lead_metric(context, "lead_read_failed")
                        checkpoint()
                        continue
                    successful_reads += 1
                    used_chars += len(lead_content)
                    update_budget(reads_used=successful_reads)
                    checkpoint()
                    lead_categories = (
                        "public_research_candidate_metadata",
                        "bounded_public_page_excerpt",
                    )
                    if not model_allowed(
                        "research_lead_discovery", lead_categories
                    ):
                        _append_failure(
                            "policy_blocked",
                            "reading",
                            logical_call_id=(
                                f"policy:research_lead_discovery:{lead_candidate_id}"
                            ),
                            item_id=lead_candidate_id,
                            detail="blocked_by_policy",
                        )
                        _bump_lead_metric(context, "policy_blocked")
                        checkpoint()
                        continue
                    phase_begin("discovery")
                    try:
                        discovery = self.lead_discoverer.discover(
                            run_id=run_id,
                            candidate=lead_candidate,
                            content=lead_content,
                            timeout_seconds=remaining_timeout(),
                            on_attempt_started=on_model_started,
                            on_attempt_finished=on_model_finished,
                        )
                    finally:
                        phase_end("discovery")
                    ensure_active()
                    if (
                        discovery.status == "completed"
                        and discovery.discovery is not None
                    ):
                        _bump_lead_metric(context, "lead_discovery_succeeded")
                        cursor = replace(
                            cursor,
                            lead_discoveries=(
                                *cursor.lead_discoveries,
                                discovery.discovery.to_dict(),
                            ),
                        )
                        # Slice 2A: lead-discovered URLs re-enter the pool as
                        # ordinary candidates (canonical-URL identity, run-level
                        # cap, depth 1). They get no eligibility privilege.
                        parent_candidate = next(
                            (
                                item
                                for item in cursor.candidates
                                if item.id == lead_candidate_id
                            ),
                            None,
                        )
                        discovered, discovery_stats = (
                            _lead_discovered_candidates(
                                cursor.candidates,
                                discovery.discovery,
                                parent=parent_candidate,
                                max_candidates=state.budget.max_candidates,
                                discovered_so_far=sum(
                                    1
                                    for item in cursor.candidates
                                    if item.discovery_method == "lead_url"
                                ),
                            )
                            if parent_candidate is not None
                            else ((), {})
                        )
                        for stats_key, stats_value in discovery_stats.items():
                            if stats_key != "added" and stats_value:
                                _bump_lead_metric(
                                    context, stats_key, int(stats_value)
                                )
                        if discovered:
                            cursor = replace(
                                cursor,
                                candidates=(*cursor.candidates, *discovered),
                            )
                            _bump_lead_metric(
                                context,
                                "discovered_candidate_added",
                                len(discovered),
                            )
                            context.setdefault(
                                ACTIVE_RESEARCH_METRICS_KEY, {}
                            )["lead_discovered_candidate_ids"] = [
                                item.id
                                for item in cursor.candidates
                                if item.discovery_method == "lead_url"
                            ]
                    else:
                        _bump_lead_metric(context, "lead_discovery_failed")
                        _append_failure(
                            "extraction_failed",
                            "reading",
                            logical_call_id=(
                                f"research_lead_discovery:{run_id}"
                                f":{lead_candidate_id}:1"
                            ),
                            item_id=lead_candidate_id,
                            detail=discovery.reason
                            or "lead_discovery_unavailable",
                        )
                    checkpoint()

                cursor = replace(cursor, phase="extracting")
                checkpoint(stage="reading")

                # A successful read is not evidence until strict extraction validates.
                # B5-H3: extraction targets bind (candidate_id, claim_id) pairs, so
                # one physical read can serve multiple claims.
                claims_by_id = {claim.id: claim for claim in state.claims}
                for extraction_target in extraction_targets:
                    candidate_id = extraction_target["candidate_id"]
                    claim_id = extraction_target["claim_id"]
                    source_record = _source_by_candidate(selected_sources, candidate_id)
                    if source_record is None or _read_status(source_record) != "read":
                        continue
                    extractions = source_record.setdefault("extractions", {})
                    prior = extractions.get(claim_id)
                    if isinstance(prior, Mapping) and prior.get("status") in {"eligible", "extractor_failed"}:
                        continue
                    legacy = source_record.get("extraction")
                    if (
                        prior is None
                        and isinstance(legacy, Mapping)
                        and legacy.get("status") in {"eligible", "extractor_failed"}
                        and legacy.get("claim_id") == claim_id
                    ):
                        continue
                    ensure_active()
                    ensure_budget()
                    extraction_categories = (
                        "public_research_claim",
                        "public_candidate_metadata",
                        "bounded_public_page_excerpt",
                    )
                    extraction_logical_call_id = (
                        f"research_evidence_extract:{run_id}:{claim_id}:{candidate_id}:1"
                        f"{_extraction_call_suffix(cursor, candidate_id, claim_id)}"
                    )
                    if not model_allowed("research_evidence_extraction", extraction_categories):
                        extractions[claim_id] = {"status": "extractor_failed", "reason": "blocked_by_policy"}
                        _append_failure(
                            "policy_blocked",
                            "extracting",
                            logical_call_id=f"policy:{extraction_logical_call_id}",
                            item_id=candidate_id,
                            detail="blocked_by_policy",
                        )
                        checkpoint()
                        continue
                    candidate = _candidate_by_id(cursor, candidate_id)
                    claim = claims_by_id[extraction_target["claim_id"]]
                    read = cast(Mapping[str, Any], source_record["read"])
                    try:
                        extraction_attempt_start = _model_attempt_start(
                            cursor,
                            extraction_logical_call_id,
                        )
                    except _ModelAttemptBudgetExhausted:
                        # Both durable attempts for this exact (candidate,
                        # claim) extraction may already have failed before the
                        # process exited (the inflight attempt 2 becomes
                        # interrupted_unknown on resume). Treat it as claim-
                        # local extraction failure: mark the binding
                        # extractor_failed, record the failure, checkpoint and
                        # continue the wave - never a whole-runtime failure and
                        # never a third physical model call.
                        extractions[claim_id] = {
                            "status": "extractor_failed",
                            "reason": "model_call_attempts_exhausted",
                        }
                        _append_failure(
                            "model_attempts_exhausted",
                            "extracting",
                            logical_call_id=extraction_logical_call_id,
                            item_id=candidate_id,
                            detail="model_call_attempts_exhausted",
                        )
                        checkpoint()
                        continue
                    phase_begin("extraction")
                    try:
                        extracted = self.evidence_extractor.extract(
                            run_id=run_id,
                            claim=claim,
                            candidate=candidate,
                            source_role=extraction_target["source_role"],
                            source_cluster_id=extraction_target["cluster_id"],
                            content=str(read.get("content") or ""),
                            timeout_seconds=remaining_timeout(),
                            on_attempt_started=on_model_started,
                            on_attempt_finished=on_model_finished,
                            call_id_suffix=_extraction_call_suffix(
                                cursor, candidate_id, claim_id
                            ),
                            attempt_start=extraction_attempt_start,
                        )
                    finally:
                        phase_end("extraction")
                    ensure_active()
                    if extracted.status != "completed" or extracted.extraction is None:
                        extraction_reason = extracted.reason or "extractor_unavailable"
                        extractions[claim_id] = {
                            "status": "extractor_failed",
                            "reason": extraction_reason,
                        }
                        extraction_code: ResearchFailureCode = (
                            "model_attempts_exhausted"
                            if extraction_reason == "model_call_attempts_exhausted"
                            else "extraction_failed"
                        )
                        _append_failure(
                            extraction_code,
                            "extracting",
                            logical_call_id=extraction_logical_call_id,
                            item_id=candidate_id,
                            detail=extraction_reason,
                        )
                        checkpoint()
                        continue
                    link = extracted.extraction
                    extraction_summary = {
                        "status": "eligible",
                        "claim_id": link.claim_id,
                        "relation": link.relation,
                        "strength": link.strength,
                        "locator": link.locator,
                        "anchored_spans": list(link.anchored_spans),
                        "caveats": list(link.caveats),
                        "source_role": link.source_role,
                        "source_cluster_id": link.source_cluster_id,
                        "published_at": link.published_at,
                    }
                    extractions[claim_id] = dict(extraction_summary)
                    # Keep the singular field as a backward-compatible summary of
                    # the first eligible extraction for existing consumers.
                    current_summary = source_record.get("extraction")
                    if not (
                        isinstance(current_summary, Mapping)
                        and current_summary.get("status") == "eligible"
                    ):
                        source_record["extraction"] = extraction_summary
                    evidence_id = _evidence_id_for_record(run_id, source_record, selected_sources, rejected_sources)
                    state = _add_extracted_evidence(state, evidence_id=evidence_id, link=link)
                    cursor = replace(
                        cursor,
                        read_outcomes=tuple(
                            replace(outcome, evidence_id=evidence_id)
                            if outcome.candidate_id == candidate_id
                            else outcome
                            for outcome in cursor.read_outcomes
                        ),
                    )
                    checkpoint()

                    # Evidence Lead Follow-up: relation="lead" means the page
                    # did not answer the claim but points somewhere better.
                    # Consume the ALREADY-READ content (never re-read, no model
                    # call) and feed bounded discovery input. Admission is strict
                    # and shares the frozen read/model/time budget.
                    # §36A: "qualifies" rows join the trigger when the extractor
                    # named a usable anchor/locator plus a missing-fact caveat,
                    # and the caveat is turned into a positive deeper-page target.
                    if link.relation in {"lead", "qualifies"}:
                        gap = gap_from_extraction(
                            relation=link.relation,
                            locator=link.locator,
                            anchored_spans=link.anchored_spans,
                            caveats=link.caveats,
                            source_url=candidate.url,
                            source_role=link.source_role,
                        )
                        wave_followups = sum(
                            1
                            for item in cursor.evidence_lead_followups
                            if int(item.get("wave_index") or 0) == cursor.wave_index
                        )
                        remaining_seconds = (
                            state.budget.hard_timeout_seconds - elapsed()
                        )
                        if (
                            wave_followups >= MAX_EVIDENCE_LEAD_FOLLOWUPS_PER_WAVE
                            or len(cursor.evidence_lead_followups)
                            >= MAX_EVIDENCE_LEAD_FOLLOWUPS_PER_RUN
                        ):
                            _bump_lead_metric(
                                context, "evidence_lead_followup_cap_reached"
                            )
                        elif (
                            remaining_seconds
                            < EVIDENCE_LEAD_FOLLOWUP_MIN_REMAINING_SECONDS
                        ):
                            _bump_lead_metric(
                                context,
                                "evidence_lead_followup_skipped_insufficient_budget",
                            )
                        elif (
                            claim_support_topology(state, claim)[0]
                            >= claim.evidence_requirement.min_independent_sources
                        ):
                            _bump_lead_metric(
                                context, "evidence_lead_followup_no_support_gap"
                            )
                        else:
                            _bump_lead_metric(
                                context, "evidence_lead_followup_started"
                            )
                            parent_candidate = next(
                                (
                                    item
                                    for item in cursor.candidates
                                    if item.id == candidate_id
                                ),
                                None,
                            )
                            keywords = tuple(
                                token.casefold()
                                for token in query_terms(claim.text)
                            )[:8]
                            if gap is None:
                                _bump_lead_metric(
                                    context, "deeper_targeting_gap_unavailable"
                                )
                                intent = None
                                variants: tuple[str, ...] = ()
                            else:
                                _bump_lead_metric(
                                    context,
                                    f"deeper_targeting_{gap.targeting_strategy}",
                                )
                                # §36B slice 1: infer the kind of page that would
                                # carry the fact and derive bounded query variants.
                                # These are discovery hints allocated inside the
                                # existing follow-up slots - no budget growth.
                                intent = infer_page_intent(
                                    claim_terms=keywords,
                                    missing_fact_terms=gap.missing_fact_terms,
                                )
                                variants = query_variants(
                                    subject_terms=keywords,
                                    missing_fact_terms=gap.missing_fact_terms,
                                    intent=intent,
                                )
                            discovered, followup_stats = (
                                _evidence_lead_followup_candidates(
                                    cursor.candidates,
                                    page_url=candidate.url,
                                    content=str(read.get("content") or ""),
                                    parent=parent_candidate,
                                    keywords=keywords,
                                    max_candidates=state.budget.max_candidates,
                                    gap=gap,
                                )
                                if parent_candidate is not None
                                else ((), {"no_deeper_url": 1})
                            )
                            for stats_key, stats_value in followup_stats.items():
                                if stats_key != "added" and stats_value:
                                    _bump_lead_metric(
                                        context,
                                        f"evidence_lead_{stats_key}",
                                        int(stats_value),
                                    )
                            if discovered:
                                cursor = replace(
                                    cursor,
                                    candidates=(*cursor.candidates, *discovered),
                                )
                                _bump_lead_metric(
                                    context,
                                    "evidence_lead_candidate_added",
                                    len(discovered),
                                )
                            cursor = replace(
                                cursor,
                                evidence_lead_followups=(
                                    *cursor.evidence_lead_followups,
                                    {
                                        # The durable cursor record keeps its frozen
                                        # shape (the codec strictly validates these
                                        # keys). §36A diagnostics go to metrics
                                        # below, so no runtime contract changes.
                                        "wave_index": cursor.wave_index,
                                        "evidence_id": evidence_id,
                                        "source_candidate_id": candidate_id,
                                        "method": (
                                            "evidence_lead_url"
                                            if discovered
                                            else "no_deeper_url"
                                        ),
                                        "added_candidate_ids": [
                                            item.id for item in discovered
                                        ],
                                        # The observed page domain is audit
                                        # only; it may become a site: constraint
                                        # only when this page's server-owned
                                        # role is primary (the evidence owner).
                                        "hint_domain": _domain_of(candidate.url),
                                        "trusted_primary_domain": (
                                            _domain_of(candidate.url)
                                            if link.source_role == "primary"
                                            else ""
                                        ),
                                        # The obstacle is searched positively:
                                        # claim subject first, then the missing
                                        # fact's own terms (never the negation).
                                        # §36B may add page-intent terms, still
                                        # bounded, still inside this slot.
                                        "hint_terms": list(
                                            (
                                                variants[0].split()
                                                if variants
                                                else targeted_query_terms(gap, keywords)
                                            )[:4]
                                            if gap is not None
                                            else keywords[:4]
                                        ),
                                    },
                                ),
                            )
                            _record_deeper_targeting(
                                context,
                                gap=gap,
                                source_url=candidate.url,
                                selected_url=(discovered[0].url if discovered else ""),
                                selected_depth=(
                                    discovered[0].discovery_depth
                                    if discovered
                                    else 0
                                ),
                                intent=intent,
                                variants=variants,
                            )
                            checkpoint()

                if routed_pairs:
                    # §39 observability: what the routed extractions returned,
                    # per read artifact and claim, so a routed-but-not-supported
                    # outcome is distinguishable from a never-routed one.
                    routing_metrics = context.setdefault(ACTIVE_RESEARCH_METRICS_KEY, {})
                    if isinstance(routing_metrics, dict):
                        observed = routing_metrics.get("atomic_routing_extractions")
                        observed = observed if isinstance(observed, list) else []
                        for routed_candidate_id, routed_claim_id in sorted(routed_pairs):
                            routed_source = _source_by_candidate(
                                selected_sources, routed_candidate_id
                            )
                            if routed_source is None:
                                continue
                            routed_extraction = (
                                routed_source.get("extractions") or {}
                            ).get(routed_claim_id)
                            if not isinstance(routed_extraction, Mapping):
                                continue
                            observed.append(
                                {
                                    "wave_index": cursor.wave_index,
                                    "read_artifact_id": routed_candidate_id,
                                    "origin_claim_id": "",
                                    "claim_id": routed_claim_id,
                                    "status": str(routed_extraction.get("status") or ""),
                                    "relation": str(routed_extraction.get("relation") or ""),
                                    "source_cluster_id": str(
                                        routed_extraction.get("source_cluster_id") or ""
                                    ),
                                }
                            )
                        routing_metrics["atomic_routing_extractions"] = observed[-60:]

                cursor = replace(cursor, phase="gating")
                checkpoint(stage="gating")
                gate = evaluate_evidence_gate(state)
                state = _state_after_gate(state, gate)
                brief = _evidence_brief(state, gate, selected_sources)
                context[ACTIVE_RESEARCH_BRIEF_KEY] = brief
                # §45 funnel: proposal -> added -> assessed -> read ->
                # extracted -> gate-eligible, per llm_proposed candidate.
                _record_tier2_funnel(context, cursor, brief, selected_sources)
                checkpoint()

                # P1-C batch 2: wave-level Evidence Gain + Saturation using the
                # frozen contracts. target gaps = the gaps frozen at wave start
                # (active_gap_ids) — handled means "this wave's strategy ran
                # for the gap", whether or not the planner found new queries or
                # search produced anything new. The gain baseline is the
                # durable wave-start snapshot, so extraction persisted before a
                # crash is never lost to a reset baseline.
                handled_gap_ids = tuple(cursor.active_gap_ids)
                handled_claim_ids = tuple(
                    dict.fromkeys(
                        gap.claim_id
                        for gap in state.gaps
                        if gap.id in set(handled_gap_ids)
                    )
                )
                gain = evaluate_evidence_gain(
                    wave_baseline,
                    state,
                    target_gap_ids=handled_gap_ids,
                    gain_provenance_by_gap=_wave_gap_provenance(
                        cursor, state, gate, handled_gap_ids
                    ),
                )
                saturation = update_saturation(
                    SaturationState(
                        no_gain_batches_by_claim=dict(cursor.no_gain_batches_by_claim),
                        no_gain_batches_by_gap=dict(cursor.no_gain_batches_by_gap),
                    ),
                    gain,
                    handled_claim_ids=handled_claim_ids,
                    handled_gap_ids=handled_gap_ids,
                )
                # Slice 3: explicit progress axes. Evidence progress is the
                # frozen gain contract; discovery progress is new candidate /
                # hint material produced by a bounded lead read. Discovery
                # progress only DELAYS saturation for this batch - it never
                # creates evidence gain and never resets the accumulated
                # no-gain history (so weak leads cannot endlessly extend a run).
                evidence_progress = bool(gain.substantive_gain)
                discovered_candidates_after = sum(
                    1
                    for item in cursor.candidates
                    if _is_discovery_candidate(item)
                )
                new_discovery_payloads = cursor.lead_discoveries[
                    discoveries_before_lead:
                ]
                new_discovery_assets = any(
                    bool(payload.get("discovered_urls"))
                    or bool(payload.get("domains"))
                    or bool(payload.get("organizations"))
                    or bool(payload.get("primary_source_hints"))
                    for payload in new_discovery_payloads
                    if isinstance(payload, Mapping)
                )
                discovery_progress = (
                    discovered_candidates_after > discovery_assets_before_lead
                    or new_discovery_assets
                    or any(
                        str(item.get("hint_domain") or "")
                        for item in cursor.evidence_lead_followups[
                            followups_before_lead:
                        ]
                        if isinstance(item, Mapping)
                    )
                )
                no_gain_incremented = not (evidence_progress or discovery_progress)
                if no_gain_incremented:
                    cursor = replace(
                        cursor,
                        gain_history=(*cursor.gain_history, gain.to_dict()),
                        no_gain_batches_by_claim=dict(
                            saturation.no_gain_batches_by_claim
                        ),
                        no_gain_batches_by_gap=dict(
                            saturation.no_gain_batches_by_gap
                        ),
                    )
                else:
                    cursor = replace(
                        cursor,
                        gain_history=(*cursor.gain_history, gain.to_dict()),
                    )
                wave_metrics = context.setdefault(ACTIVE_RESEARCH_METRICS_KEY, {})
                wave_progress = wave_metrics.get("wave_progress")
                if not isinstance(wave_progress, list):
                    wave_progress = []
                wave_progress.append(
                    {
                        "wave_index": cursor.wave_index,
                        "evidence_progress": evidence_progress,
                        "discovery_progress": discovery_progress,
                        "discovered_candidates_added": max(
                            0,
                            discovered_candidates_after
                            - discovery_assets_before_lead,
                        ),
                        "no_gain_incremented": no_gain_incremented,
                    }
                )
                wave_metrics["wave_progress"] = wave_progress[-MAX_RESEARCH_WAVES:]
                checkpoint()
                record_research_window(exhausted=research_window_exhausted())
                settled = settle_completed_wave(gate, brief)
                if settled is not None:
                    return settled
        except (ActiveResearchCancelled, CandidatePoolCancelled, ReadSchedulingCancelled):
            # B5-H1: persist the in-memory cursor so a cancel that lands after
            # on_model_finished records the cleared inflight marker and any
            # completed audit; the cancelled run is terminal and never resumes.
            try:
                refresh_steering()
                mark_pending_steering_late("user_cancelled")
                checkpoint()
            except Exception:
                pass
            return self.repository.finish_cancel(run_id, operation_id=operation_id)
        except _HardBudgetReached:
            update_budget()
            refresh_steering()
            mark_pending_steering_late("hard_budget_exhausted")
            record_research_window(exhausted=research_window_exhausted())
            checkpoint()
            gate = evaluate_evidence_gate(state)
            brief = _evidence_brief(state, gate, selected_sources)
            context[ACTIVE_RESEARCH_BRIEF_KEY] = brief
            checkpoint()
            # P1-C batch 3: the stop truth comes from the gate; the frozen
            # exception-path confidence ("partial" if evidence else "none")
            # is preserved exactly as in 533b60c7. The late steering blocks
            # the old graph's gate pass via the durable recomputed signal,
            # so a crash after the late checkpoint resumes to the same
            # evidence_budget_exhausted decision.
            stop = ResearchStopGate.evaluate(
                ResearchStopSignal(
                    gate_pass=gate.status == "pass",
                    hard_budget_exhausted=True,
                    has_actionable_gaps=True,
                    all_actionable_saturated=False,
                    wave_limit_reached=False,
                    has_evidence=bool(state.evidence),
                    unapplied_steering_blocks_completion=(
                        _unapplied_steering_blocks_completion(context)
                    ),
                )
            )
            return self.repository.complete(
                run_id,
                operation_id=operation_id,
                items=_eligible_items(selected_sources),
                source_block=_format_evidence_brief(brief),
                warnings=_dedupe(warnings),
                research_context=context,
                query_attempts=query_attempts,
                selected_sources=selected_sources,
                rejected_sources=rejected_sources,
                provider_status=stop.provider_status,
                stop_reason=stop.reason,
                answer_confidence=(
                    "partial" if state.evidence else "none"
                ),
                final_status=stop.final_status,
            )
        except Exception as exc:
            latest = self._required(run_id)
            if latest.status != "running" or latest.active_operation_id != operation_id:
                if raise_on_error:
                    raise
                return latest
            _append_failure(
                "runtime_internal_failed",
                cursor.phase,
                item_id=run_id,
                detail="active_runtime_exception",
                exception_type=type(exc).__name__,
            )
            try:
                checkpoint()
            except Exception:
                pass
            # P1-C batch 3: the canonical stop reason comes from the gate;
            # the frozen evidence-shaped finish (complete vs fail) is kept.
            stop = ResearchStopGate.evaluate(
                ResearchStopSignal(
                    gate_pass=False,
                    hard_budget_exhausted=False,
                    has_actionable_gaps=True,
                    all_actionable_saturated=False,
                    wave_limit_reached=False,
                    has_evidence=bool(state.evidence),
                    unavailable_reason="active_runtime_unavailable",
                )
            )
            if state.evidence:
                result = self.repository.complete(
                    run_id,
                    operation_id=operation_id,
                    items=_eligible_items(selected_sources),
                    source_block=_format_evidence_brief(
                        _evidence_brief(state, None, selected_sources)
                    ),
                    warnings=_dedupe([*warnings, "active research became unavailable"]),
                    research_context=context,
                    query_attempts=query_attempts,
                    selected_sources=selected_sources,
                    rejected_sources=rejected_sources,
                    provider_status=stop.provider_status,
                    stop_reason=stop.reason,
                    answer_confidence="partial",
                    final_status="partial",
                )
            else:
                result = self.repository.fail(
                    run_id,
                    "active research unavailable",
                    research_context=context,
                    query_attempts=query_attempts,
                    provider_status=stop.provider_status,
                    stop_reason=stop.reason,
                    operation_id=operation_id,
                )
            if raise_on_error:
                raise
            return result

    def _terminal_unavailable(
        self,
        run_id: str,
        *,
        operation_id: str,
        context: dict[str, Any],
        cursor: ResearchRuntimeCursor,
        state: ResearchState,
        query_attempts: list[dict[str, Any]],
        selected_sources: list[dict[str, Any]],
        rejected_sources: list[dict[str, Any]],
        warnings: list[str],
        reason: str,
    ) -> WebLookupRun:
        context = attach_runtime_cursor(context, replace(cursor, phase="unavailable"))
        context = attach_claim_engine_state(
            context,
            state,
            known_evidence_ids=tuple(
                ref.id for ref in _evidence_snapshot(run_id, selected_sources, rejected_sources).refs
            ),
        )
        # P1-C batch 3: the canonical stop reason flows through the gate.
        stop = ResearchStopGate.evaluate(
            ResearchStopSignal(
                gate_pass=False,
                hard_budget_exhausted=False,
                has_actionable_gaps=True,
                all_actionable_saturated=False,
                wave_limit_reached=False,
                has_evidence=bool(state.evidence),
                unavailable_reason=reason,
            )
        )
        return self.repository.fail(
            run_id,
            "active research unavailable",
            research_context=context,
            query_attempts=query_attempts,
            provider_status=stop.provider_status,
            stop_reason=stop.reason,
            operation_id=operation_id,
        )

    def _required(self, run_id: str) -> WebLookupRun:
        run = self.repository.get(run_id)
        if run is None:
            raise ValueError(f"WebLookupRun not found: {run_id}")
        return run


class _HardBudgetReached(Exception):
    pass


def _default_policy_check(context: Mapping[str, Any], purpose: str) -> bool:
    del purpose
    policy = context.get("external_data_policy")
    return isinstance(policy, Mapping) and policy.get("web_allowed") is True


def _pending_active_steering_ids(context: Mapping[str, Any]) -> tuple[str, ...]:
    return tuple(
        str(item["id"])
        for item in active_steering_entries(context)
        if item.get("status") == "pending"
    )


def _unapplied_steering_blocks_completion(context: Mapping[str, Any]) -> bool:
    """Durable signal: a steering marked late against the exhausted hard or
    wave budget invalidates completion computed from the pre-steering graph.

    Recomputed from the merged durable context on every settlement (including
    a crash/resume), never taken from this invocation's mark return value.
    User-cancelled late entries stay owned by the cancellation lifecycle and
    do not participate in StopGate truth.
    """

    return any(
        item.get("status") == "late"
        and item.get("late_reason") in {"hard_budget_exhausted", "wave_limit_reached"}
        for item in active_steering_entries(context)
    )


def _steering_ids_for_claim(
    context: Mapping[str, Any],
    claim_id: str,
) -> tuple[str, ...]:
    return tuple(
        str(item["id"])
        for item in active_steering_entries(context)
        if item.get("status") == "applied" and item.get("claim_id") == claim_id
    )


def _steering_graph_ids(entry_id: str) -> tuple[str, str]:
    digest = hashlib.sha256(entry_id.encode("utf-8")).hexdigest()[:24]
    return f"claim_steering_{digest}", f"gap_steering_{digest}"


def _apply_pending_active_steering(
    state: ResearchState,
    context: Mapping[str, Any],
    *,
    run_id: str,
    wave_index: int,
    applied_at: str,
    known_evidence_ids: tuple[str, ...],
) -> tuple[ResearchState, dict[str, Any], tuple[str, ...]]:
    """Map pending metadata into one user claim and critical gap per entry."""

    entries = active_steering_entries(context)
    pending = [item for item in entries if item.get("status") == "pending"]
    if not pending:
        return state, dict(context), ()
    if not state.questions:
        raise ValueError("active steering requires a planned research question")

    question_id = state.questions[0].id
    claims = list(state.claims)
    gaps = list(state.gaps)
    trace = list(state.trace)
    claim_ids = {item.id for item in claims}
    gap_ids = {item.id for item in gaps}
    next_sequence = max((item.sequence for item in trace), default=0) + 1
    applied_ids: list[str] = []

    for entry in entries:
        if entry.get("status") != "pending":
            continue
        entry_id = str(entry["id"])
        claim_id, gap_id = _steering_graph_ids(entry_id)
        if claim_id not in claim_ids:
            claims.append(
                ResearchClaim(
                    id=claim_id,
                    question_id=question_id,
                    text=str(entry.get("content") or "")[:2000],
                    kind="research_question",
                    priority="critical",
                    state="unresolved",
                    evidence_requirement=EvidenceRequirement(
                        min_independent_sources=1,
                        requires_successful_read=True,
                    ),
                    created_by="user",
                    created_reason=f"active_steering:{entry_id}",
                )
            )
            claim_ids.add(claim_id)
            trace.append(
                ResearchTraceEvent(
                    sequence=next_sequence,
                    timestamp=applied_at,
                    run_id=run_id,
                    event_type="claim_created",
                    reason="active_steering_applied",
                    claim_id=claim_id,
                )
            )
            next_sequence += 1
        if gap_id not in gap_ids:
            gaps.append(
                EvidenceGap(
                    id=gap_id,
                    claim_id=claim_id,
                    gap_type="user_steering",
                    priority="critical",
                    state="open",
                )
            )
            gap_ids.add(gap_id)
            trace.append(
                ResearchTraceEvent(
                    sequence=next_sequence,
                    timestamp=applied_at,
                    run_id=run_id,
                    event_type="gap_created",
                    reason="active_steering_applied",
                    claim_id=claim_id,
                    gap_id=gap_id,
                )
            )
            next_sequence += 1
        entry.update(
            {
                "status": "applied",
                "applied_wave": wave_index,
                "applied_at": applied_at,
                "claim_id": claim_id,
                "gap_id": gap_id,
                "late_reason": "",
            }
        )
        applied_ids.append(entry_id)

    updated_state = build_research_state(
        mode=state.mode,
        questions=state.questions,
        claims=claims,
        evidence=state.evidence,
        evidence_links=state.evidence_links,
        source_clusters=state.source_clusters,
        gaps=gaps,
        conflict_gaps=state.conflict_gaps,
        budget=state.budget,
        trace=trace,
        brief=None,
        reference_date=state.reference_date,
        known_evidence_ids=known_evidence_ids,
    )
    updated_context = dict(context)
    updated_context[ACTIVE_RESEARCH_STEERING_KEY] = entries
    return updated_state, updated_context, tuple(applied_ids)


def _mark_pending_active_steering_late(
    context: Mapping[str, Any],
    *,
    reason: str,
) -> tuple[dict[str, Any], tuple[str, ...]]:
    entries = active_steering_entries(context)
    late_ids: list[str] = []
    for entry in entries:
        if entry.get("status") != "pending":
            continue
        entry.update(
            {
                "status": "late",
                "applied_wave": None,
                "applied_at": None,
                "claim_id": "",
                "gap_id": "",
                "late_reason": reason,
            }
        )
        late_ids.append(str(entry["id"]))
    updated = dict(context)
    if entries:
        updated[ACTIVE_RESEARCH_STEERING_KEY] = entries
    return updated, tuple(late_ids)


def _ordered_claims(state: ResearchState) -> tuple[ResearchClaim, ...]:
    order = {"critical": 0, "major": 1, "context": 2}
    return tuple(sorted(state.claims, key=lambda claim: (order[claim.priority], claim.id)))


def _ordered_gaps(state: ResearchState) -> tuple[EvidenceGap, ...]:
    claim_priority = {claim.id: claim.priority for claim in state.claims}
    order = {"critical": 0, "major": 1, "context": 2}
    return tuple(
        sorted(
            (
                gap
                for gap in state.gaps
                if gap.state in {"open", "searching"}
                and claim_priority.get(gap.claim_id) != "context"
            ),
            key=lambda gap: (order[claim_priority[gap.claim_id]], gap.id),
        )
    )


def _runtime_query(query: PlannedGapQuery) -> RuntimePlannedQuery:
    return RuntimePlannedQuery(
        id=query.id,
        gap_id=query.gap_id,
        claim_id=query.claim_id,
        intent=query.intent.value,
        query=query.query,
        desired_source_role=query.desired_source_role,
    )


def _append_gap_queries(
    cursor: ResearchRuntimeCursor,
    state: ResearchState,
) -> ResearchRuntimeCursor:
    """Append one wave's novel semantic queries exactly once.

    Query IDs and normalized text stay stable across waves. Wave/call/attempt
    identity belongs to the runtime markers, not to semantic query identity.
    """

    planned_text = {item.query.casefold() for item in cursor.planned_queries}
    planned_ids = {item.id for item in cursor.planned_queries}
    claims = {claim.id: claim for claim in state.claims}
    new_planned: list[RuntimePlannedQuery] = []
    for gap in _ordered_gaps(state):
        claim = claims[gap.claim_id]
        question_surface = next(
            (
                item.question_surface
                for item in state.questions
                if item.id == claim.question_id
            ),
            "",
        )
        trusted_domain, claim_hints = _lead_hints_for_claim(cursor, claim.id)
        batch = plan_gap_queries(
            gap,
            claim,
            reference_date=state.reference_date,
            source_hints=claim_hints,
            trusted_domain=trusted_domain,
            question=question_surface,
        )
        for item in batch.queries:
            runtime_query = _runtime_query(item)
            query_key = runtime_query.query.casefold()
            if query_key in planned_text:
                continue
            if runtime_query.id in planned_ids:
                # Same (gap, intent) re-planned with different wording (for
                # example a lead hint sharpened it): mint a deterministic
                # content-scoped id so the new query is not silently dropped.
                runtime_query = replace(
                    runtime_query,
                    id=(
                        f"{runtime_query.id}:"
                        f"{hashlib.sha256(runtime_query.query.encode('utf-8')).hexdigest()[:8]}"
                    ),
                )
                if runtime_query.id in planned_ids:
                    continue
            new_planned.append(runtime_query)
            planned_ids.add(runtime_query.id)
            planned_text.add(query_key)
    if not new_planned:
        return cursor
    return replace(
        cursor,
        planned_queries=tuple([*cursor.planned_queries, *new_planned])[:100],
    )


def _gap_query_batch(query: RuntimePlannedQuery) -> GapQueryBatch:
    planned = PlannedGapQuery(
        id=query.id,
        gap_id=query.gap_id,
        claim_id=query.claim_id,
        intent=GapSearchIntent(query.intent),
        query=query.query,
        desired_source_role=query.desired_source_role,
    )
    return GapQueryBatch(
        gap_id=query.gap_id,
        claim_id=query.claim_id,
        focused_surface=query.query,
        queries=(planned,),
    )


def _runtime_query_status(status: str) -> str:
    return status if status in {"ok", "empty", "unavailable"} else "unavailable"


def _merge_runtime_candidates(
    existing: tuple[RuntimeCandidate, ...],
    incoming: tuple[CandidatePoolItem, ...],
    *,
    max_candidates: int,
    trace: SelectionTraceCollector | None = None,
) -> tuple[RuntimeCandidate, ...]:
    merged = list(existing)
    by_url = {item.url: index for index, item in enumerate(merged)}
    for item in incoming:
        index = by_url.get(item.canonical_url)
        if index is not None:
            if trace is not None:
                trace.note_duplicate(item.canonical_url)
            current = merged[index]
            merged[index] = replace(
                current,
                title=item.title if len(item.title) > len(current.title) else current.title,
                snippet=item.snippet if len(item.snippet) > len(current.snippet) else current.snippet,
                query_ids=tuple(dict.fromkeys((*current.query_ids, *item.query_ids))),
                intents=tuple(dict.fromkeys((*current.intents, *(intent.value for intent in item.intents)))),
                providers=tuple(dict.fromkeys((*current.providers, *item.providers))),
            )
            continue
        if len(merged) >= max_candidates:
            if trace is not None:
                trace.note_cap_excluded(item.canonical_url, stage="runtime_merge")
            continue
        by_url[item.canonical_url] = len(merged)
        merged.append(
            RuntimeCandidate(
                id=item.id,
                url=item.canonical_url,
                title=item.title,
                snippet=item.snippet,
                source=item.source,
                published_at=item.published_at,
                query_ids=item.query_ids,
                intents=tuple(intent.value for intent in item.intents),
                providers=item.providers,
                first_seen_rank=item.first_seen_rank,
                parent_lead_candidate_id=item.parent_lead_candidate_id,
                discovery_method=item.discovery_method,
                discovery_depth=item.discovery_depth,
            )
        )
        if trace is not None:
            trace.note_materialized(item.canonical_url)
    return tuple(merged)


def _candidate_item(item: RuntimeCandidate) -> CandidatePoolItem:
    return CandidatePoolItem(
        id=item.id,
        canonical_url=item.url,
        url=item.url,
        title=item.title,
        snippet=item.snippet,
        source=item.source,
        published_at=item.published_at,
        query_ids=item.query_ids,
        intents=tuple(GapSearchIntent(value) for value in item.intents),
        providers=item.providers,
        first_seen_rank=item.first_seen_rank,
        parent_lead_candidate_id=item.parent_lead_candidate_id,
        discovery_method=item.discovery_method,
        discovery_depth=item.discovery_depth,
    )


def _candidates_for_claim(cursor: ResearchRuntimeCursor, claim_id: str) -> tuple[CandidatePoolItem, ...]:
    query_ids = {item.id for item in cursor.planned_queries if item.claim_id == claim_id}
    return tuple(
        _candidate_item(item)
        for item in cursor.candidates
        if query_ids.intersection(item.query_ids)
    )


def _tier2_proposal_step(
    *,
    cursor: ResearchRuntimeCursor,
    state: ResearchState,
    claim: ResearchClaim,
    assessments: Mapping[str, Any],
    model_gateway: Any,
    read_fn: Any,
    context: dict[str, Any],
    run_id: str,
    wave_index: int,
    timeout_seconds: float | None,
    proposed_claim_ids: list[str],
) -> ResearchRuntimeCursor:
    """§45 Tier-2: LLM URL proposal -> reader verification -> candidate.

    Runs only when Tier-1 produced candidates but none was assessed
    ``answer_relevant``, at most once per claim per run, and only with
    ``RESEARCH_LLM_PROPOSAL=on``. Proposed URLs never become evidence: a
    verified page is added as a candidate with
    ``discovery_method="llm_proposed"`` and must pass the same assessment,
    read, extraction and Gate path as any search-discovered candidate.
    """

    if not llm_proposal_enabled():
        return cursor
    if claim.id in proposed_claim_ids:
        return cursor
    claim_candidates = _candidates_for_claim(cursor, claim.id)
    claim_candidate_ids = {item.id for item in claim_candidates}
    # Frozen §45 contract: the read that unlocks Tier-2 must belong to THIS
    # claim, not just to the run.
    claim_completed_reads = sum(
        1
        for outcome in cursor.read_outcomes
        if outcome.candidate_id in claim_candidate_ids
    )
    miss_reason = tier1_miss_reason(
        assessments=assessments,
        candidate_ids=[item.id for item in claim_candidates],
        completed_read_count=claim_completed_reads,
        claim_has_support=any(
            link.claim_id == claim.id and link.relation == "supports"
            for link in state.evidence_links
        ),
    )
    if not miss_reason:
        return cursor
    proposed_claim_ids.append(claim.id)
    del proposed_claim_ids[50:]

    record: dict[str, Any] = {
        "wave_index": wave_index,
        "claim_id": claim.id,
        "tier1_miss_reason": miss_reason,
        "call_status": "",
        "proposed": [],
        "verified": [],
        "dropped": [],
        "added_candidate_ids": [],
        "verification_reads": 0,
    }
    extra_body: Mapping[str, Any] | None = None
    try:
        from src.llm_client import research_structured_output_capabilities

        provider_profile = str(getattr(model_gateway, "provider_profile", "") or "")
        _, thinking_off = research_structured_output_capabilities(provider_profile)
        extra_body = thinking_off
    except Exception:
        extra_body = None
    try:
        result = model_gateway.complete_structured(
            logical_call_id=f"research_url_proposal:{run_id}:{claim.id}:{wave_index}",
            purpose="research_url_proposal",
            messages=proposal_messages(claim.text),
            audit_payload=build_proposal_payload(claim.text),
            response_schema_version="research-url-proposal-v1",
            parse=parse_proposal_response,
            data_categories=("public_research_claim",),
            max_tokens=300,
            timeout_seconds=timeout_seconds,
            extra_body=extra_body,
        )
    except Exception as exc:  # diagnostics must never fail the run
        record["call_status"] = f"exception:{type(exc).__name__}"
        result = None
    if result is not None:
        status = str(getattr(result, "status", ""))
        record["call_status"] = status or "unknown"
        value = result.value if status == "completed" else None
        record["proposed"] = list(value or [])
    metrics = context.setdefault(ACTIVE_RESEARCH_METRICS_KEY, {})
    if isinstance(metrics, dict):
        metrics["orchestration_model_calls"] = int(
            metrics.get("orchestration_model_calls") or 0
        ) + 1

    existing_urls = {item.url for item in cursor.candidates}
    anchor_query_id = next(
        (
            query.id
            for query in cursor.planned_queries
            if query.claim_id == claim.id
        ),
        "",
    )
    new_items: list[RuntimeCandidate] = []
    for url in record["proposed"]:
        if url in existing_urls:
            record["dropped"].append({"url": url, "reason": "duplicate_candidate"})
            continue
        record["verification_reads"] += 1
        try:
            raw = read_fn(url, max_chars=1200) or {}
        except Exception as exc:
            raw = {"ok": False, "error": f"{type(exc).__name__}:{str(exc)[:80]}"}
        content = str(raw.get("content") or "")
        if raw.get("ok") is not True or not content.strip():
            record["dropped"].append(
                {
                    "url": url,
                    "reason": "read_failed",
                    "detail": str(raw.get("error") or raw.get("status") or "")[:120],
                }
            )
            continue
        title = str(raw.get("title") or url)[:300]
        candidate_id = (
            f"candidate_{hashlib.sha256(url.encode('utf-8')).hexdigest()[:16]}"
        )
        new_items.append(
            RuntimeCandidate(
                id=candidate_id,
                url=url,
                title=title,
                snippet="",
                source="llm_proposal",
                published_at="",
                query_ids=(anchor_query_id,) if anchor_query_id else (),
                intents=(),
                providers=("llm_proposal",),
                first_seen_rank=len(cursor.candidates) + len(new_items),
                discovery_method=DISCOVERY_METHOD_LLM_PROPOSED,
                discovery_depth=0,
            )
        )
        record["verified"].append(url)
        record["added_candidate_ids"].append(candidate_id)
        existing_urls.add(url)
    if isinstance(metrics, dict):
        records = metrics.get("tier2_proposal")
        if not isinstance(records, list):
            records = []
        records.append(record)
        metrics["tier2_proposal"] = records[-40:]
    if not new_items:
        return cursor
    return replace(cursor, candidates=(*cursor.candidates, *new_items))


def _domain_targeted_step(
    *,
    cursor: ResearchRuntimeCursor,
    state: ResearchState,
    claim: ResearchClaim,
    assessments: Mapping[str, Any],
    model_gateway: Any,
    fetch_text: Any,
    read_fn: Any,
    context: dict[str, Any],
    run_id: str,
    wave_index: int,
    timeout_seconds: float | None,
    targeted_claim_ids: list[str],
    seconds_left: Any,
) -> ResearchRuntimeCursor:
    """§63 Tier-1.5: official-domain site search -> verified candidates.

    Same state predicate and provenance discipline as Tier-2: at most one
    pass per claim per run, bounded fetches (domains x patterns) and bounded
    verifications, candidates tagged ``domain_targeted``. Nothing here can
    create evidence; the extractor and the Gate keep final authority.
    """

    if not domain_targeted_enabled():
        return cursor
    if claim.id in targeted_claim_ids:
        return cursor
    claim_candidates = _candidates_for_claim(cursor, claim.id)
    claim_candidate_ids = {item.id for item in claim_candidates}
    claim_completed_reads = sum(
        1
        for outcome in cursor.read_outcomes
        if outcome.candidate_id in claim_candidate_ids
    )
    miss_reason = tier1_miss_reason(
        assessments=assessments,
        candidate_ids=[item.id for item in claim_candidates],
        completed_read_count=claim_completed_reads,
        claim_has_support=any(
            link.claim_id == claim.id and link.relation == "supports"
            for link in state.evidence_links
        ),
    )
    if not miss_reason:
        return cursor
    targeted_claim_ids.append(claim.id)
    del targeted_claim_ids[50:]

    record: dict[str, Any] = {
        "wave_index": wave_index,
        "claim_id": claim.id,
        "tier1_miss_reason": miss_reason,
        "call_status": "",
        "domains": [],
        "search_urls": [],
        "links_found": [],
        "verified": [],
        "dropped": [],
        "added_candidate_ids": [],
        "verification_reads": 0,
    }
    extra_body: Mapping[str, Any] | None = None
    try:
        from src.llm_client import research_structured_output_capabilities

        provider_profile = str(getattr(model_gateway, "provider_profile", "") or "")
        _, thinking_off = research_structured_output_capabilities(provider_profile)
        extra_body = thinking_off
    except Exception:
        extra_body = None
    try:
        result = model_gateway.complete_structured(
            logical_call_id=f"research_domain_proposal:{run_id}:{claim.id}:{wave_index}",
            purpose="research_domain_proposal",
            messages=domain_proposal_messages(claim.text),
            audit_payload=domain_proposal_payload(claim.text),
            response_schema_version="research-domain-proposal-v1",
            parse=parse_domain_proposal,
            data_categories=("public_research_claim",),
            max_tokens=200,
            timeout_seconds=timeout_seconds,
            extra_body=extra_body,
        )
    except Exception as exc:  # diagnostics must never fail the run
        record["call_status"] = f"exception:{type(exc).__name__}"
        result = None
    if result is not None:
        status = str(getattr(result, "status", ""))
        record["call_status"] = status or "unknown"
        record["domains"] = list(result.value or []) if status == "completed" else []
    metrics = context.setdefault(ACTIVE_RESEARCH_METRICS_KEY, {})
    if isinstance(metrics, dict):
        metrics["orchestration_model_calls"] = int(
            metrics.get("orchestration_model_calls") or 0
        ) + 1

    # Ranking may use more terms than a prose query: the runtime claim text
    # led with generic words, so a 6-term cap dropped the subject entity
    # ("Docker Hub") before it could match the deep page.
    terms = claim_search_terms(claim.text, limit=MAX_RANK_TERMS)
    links: list[str] = []
    inventory_fetches = 0
    for domain in record["domains"][:MAX_DOMAINS]:
        domain_links: list[str] = []
        for sitemap_url in sitemap_urls(domain):
            if inventory_fetches >= MAX_DOMAIN_TARGETED_SEARCH_FETCHES:
                record["dropped"].append(
                    {"url": sitemap_url, "reason": "inventory_fetch_cap"}
                )
                break
            # §63 budget guard: an inventory fetch must never eat the research
            # window (five 12s timeouts once pushed a run to ~100s).
            if seconds_left() < DOMAIN_TARGETED_MIN_SECONDS_LEFT:
                record["dropped"].append(
                    {"url": sitemap_url, "reason": "skipped_by_window"}
                )
                continue
            inventory_fetches += 1
            record["search_urls"].append(sitemap_url)
            try:
                text, _final_url, _content_type, reason = fetch_text(sitemap_url)
            except Exception as exc:
                text, reason = "", f"exception:{type(exc).__name__}"
            if not text:
                record["dropped"].append(
                    {"url": sitemap_url, "reason": "inventory_fetch_failed", "detail": str(reason)[:120]}
                )
                continue
            kind, locations = parse_sitemap(text)
            record["inventory_kind"] = kind
            if kind == "index":
                for child in prioritise_sitemap_children(locations):
                    if inventory_fetches >= MAX_DOMAIN_TARGETED_SEARCH_FETCHES:
                        record["dropped"].append(
                            {"url": child, "reason": "inventory_fetch_cap"}
                        )
                        break
                    if seconds_left() < DOMAIN_TARGETED_MIN_SECONDS_LEFT:
                        record["dropped"].append(
                            {"url": child, "reason": "skipped_by_window"}
                        )
                        continue
                    inventory_fetches += 1
                    record["search_urls"].append(child)
                    try:
                        child_text, _f, _c, child_reason = fetch_text(child)
                    except Exception as exc:
                        child_text, child_reason = "", f"exception:{type(exc).__name__}"
                    if not child_text:
                        record["dropped"].append(
                            {"url": child, "reason": "inventory_fetch_failed", "detail": str(child_reason)[:120]}
                        )
                        continue
                    _child_kind, child_locations = parse_sitemap(child_text)
                    locations = [*locations, *child_locations]
            if locations:
                record["inventory_locations"] = len(locations)
                domain_links = rank_domain_urls(
                    locations, domain=domain, terms=terms
                )
                if domain_links:
                    break
        links.extend(domain_links)
    record["links_found"] = list(dict.fromkeys(links))[: MAX_LINKS_PER_INVENTORY * MAX_DOMAINS]

    existing_urls = {item.url for item in cursor.candidates}
    anchor_query_id = next(
        (query.id for query in cursor.planned_queries if query.claim_id == claim.id),
        "",
    )
    new_items: list[RuntimeCandidate] = []
    for url in record["links_found"]:
        if url in existing_urls:
            record["dropped"].append({"url": url, "reason": "duplicate_candidate"})
            continue
        if len(new_items) >= MAX_DOMAIN_TARGETED_CANDIDATES:
            record["dropped"].append({"url": url, "reason": "candidate_cap"})
            continue
        record["verification_reads"] += 1
        try:
            raw = read_fn(url, max_chars=1200) or {}
        except Exception as exc:
            raw = {"ok": False, "error": f"{type(exc).__name__}:{str(exc)[:80]}"}
        content = str(raw.get("content") or "")
        if raw.get("ok") is not True or not content.strip():
            record["dropped"].append(
                {
                    "url": url,
                    "reason": "read_failed",
                    "detail": str(raw.get("error") or raw.get("status") or "")[:120],
                }
            )
            continue
        title = str(raw.get("title") or url)[:300]
        candidate_id = (
            f"candidate_{hashlib.sha256(url.encode('utf-8')).hexdigest()[:16]}"
        )
        new_items.append(
            RuntimeCandidate(
                id=candidate_id,
                url=url,
                title=title,
                snippet="",
                source="domain_targeted",
                published_at="",
                query_ids=(anchor_query_id,) if anchor_query_id else (),
                intents=(),
                providers=("domain_targeted",),
                first_seen_rank=len(cursor.candidates) + len(new_items),
                discovery_method=DISCOVERY_METHOD_DOMAIN_TARGETED,
                discovery_depth=0,
            )
        )
        record["verified"].append(url)
        record["added_candidate_ids"].append(candidate_id)
        existing_urls.add(url)
    # §63/§50 acceptance accounting: discovery-side stages are counted here;
    # the downstream ladder (assessed -> read -> extracted -> gate) is joined
    # per candidate in metrics.discovery_funnel. Counters only, no heuristics.
    record["stages"] = {
        "domain_proposed": len(record["domains"]),
        "inventory_fetched": inventory_fetches,
        "links_ranked": len(record["links_found"]),
        "verification_attempted": record["verification_reads"],
        "verification_succeeded": len(record["verified"]),
        "candidate_admitted": len(record["added_candidate_ids"]),
    }
    if isinstance(metrics, dict):
        records = metrics.get("domain_targeted")
        if not isinstance(records, list):
            records = []
        records.append(record)
        metrics["domain_targeted"] = records[-40:]
    if not new_items:
        return cursor
    return replace(cursor, candidates=(*cursor.candidates, *new_items))


def _record_tier2_funnel(
    context: dict[str, Any],
    cursor: ResearchRuntimeCursor,
    brief: Mapping[str, Any],
    selected_sources: list[dict[str, Any]],
) -> None:
    """§45 funnel: proposal -> added -> assessed -> read -> extracted -> gate."""

    metrics = context.get(ACTIVE_RESEARCH_METRICS_KEY)
    if not isinstance(metrics, dict):
        return
    proposals: list[tuple[str, Mapping[str, Any]]] = []
    for key, method in (
        ("tier2_proposal", "llm_proposed"),
        ("domain_targeted", DISCOVERY_METHOD_DOMAIN_TARGETED),
    ):
        records = metrics.get(key)
        if isinstance(records, list):
            proposals.extend((method, record) for record in records if isinstance(record, Mapping))
    if not proposals:
        return
    assessment_store = _assessment_store(context)
    relevant_ids: set[str] = set()
    for ranked in assessment_store.values():
        if not isinstance(ranked, list):
            continue
        for row in ranked:
            if not isinstance(row, Mapping):
                continue
            assessment = row.get("assessment")
            candidate = row.get("candidate")
            if not isinstance(assessment, Mapping) or not isinstance(candidate, Mapping):
                continue
            if str(assessment.get("relevance") or "") == "answer_relevant":
                relevant_ids.add(str(candidate.get("id") or ""))
    completed_reads = set(cursor.completed_read_ids)
    extraction_by_candidate: dict[str, list[str]] = {}
    for source in selected_sources:
        if not isinstance(source, Mapping):
            continue
        candidate_id = str(source.get("candidate_id") or "")
        extractions = source.get("extractions")
        relations: list[str] = []
        if isinstance(extractions, Mapping):
            for summary in extractions.values():
                if isinstance(summary, Mapping):
                    relation = str(summary.get("relation") or "")
                    if relation:
                        relations.append(relation)
        extraction_by_candidate[candidate_id] = sorted(set(relations))
    eligible_ids = {
        str(row.get("evidence_id") or "")
        for row in brief.get("eligible_evidence") or []
        if isinstance(row, Mapping)
    }
    evidence_by_candidate = {
        outcome.candidate_id: outcome.evidence_id
        for outcome in cursor.read_outcomes
        if outcome.evidence_id
    }
    rows: list[dict[str, Any]] = []
    for method, record in proposals:
        for candidate_id in record.get("added_candidate_ids") or []:
            evidence_id = evidence_by_candidate.get(str(candidate_id), "")
            rows.append(
                {
                    "claim_id": record.get("claim_id"),
                    "candidate_id": candidate_id,
                    "discovery_method": method,
                    "proposed": True,
                    "assessed_answer_relevant": str(candidate_id) in relevant_ids,
                    "read": str(candidate_id) in completed_reads,
                    "extraction_relations": extraction_by_candidate.get(
                        str(candidate_id), []
                    ),
                    "gate_eligible": bool(evidence_id) and evidence_id in eligible_ids,
                }
            )
    metrics["discovery_funnel"] = {
        "proposed_candidates": len(rows),
        "by_discovery_method": {
            method: sum(1 for row in rows if row["discovery_method"] == method)
            for method in sorted({row["discovery_method"] for row in rows})
        },
        "assessed_answer_relevant": sum(
            1 for row in rows if row["assessed_answer_relevant"]
        ),
        "read": sum(1 for row in rows if row["read"]),
        "extracted_supports": sum(
            1 for row in rows if "supports" in row["extraction_relations"]
        ),
        "gate_eligible": sum(1 for row in rows if row["gate_eligible"]),
        "rows": rows,
    }


def _select_assessment_window(
    candidates: tuple[CandidatePoolItem, ...],
    *,
    claim: ResearchClaim,
    assignments: Mapping[str, CandidateClusterAssignment],
    max_reads: int,
    excluded_candidate_ids: frozenset[str],
    trace: SelectionTraceCollector | None,
    context: dict[str, Any],
    model_gateway: Any,
    run_id: str,
    wave_index: int,
    timeout_seconds: float | None,
) -> tuple[CandidatePoolItem, ...]:
    """§42 selector production contract; rules by default.

    ``RESEARCH_SELECTION_AUTHORITY=model`` gives the model a *preference*
    authority over the bounded assessment window: exactly **one** call per
    window (no app-level retry), a mechanical ``usable`` check, and - whenever
    the decision is unusable - the deterministic legacy window rerun on the
    **same original candidate pool**. The model can raise quality but can never
    reduce availability, and with the default flag nothing changes.

    The selector call is orchestration work: it is counted in
    ``metrics.orchestration_model_calls`` (and, under the qualification guard,
    in the global physical-call cap like any other gateway call); it performs
    no search, read, extraction or evidence work.
    """

    mode = selection_authority_mode()
    if mode != SELECTION_AUTHORITY_MODEL:
        return _bounded_assessment_candidates(
            candidates,
            assignments=assignments,
            max_reads=max_reads,
            excluded_candidate_ids=excluded_candidate_ids,
            trace=trace,
        )

    unread = tuple(
        item for item in candidates if item.id not in excluded_candidate_ids
    )
    limit = max(
        0,
        min(len(unread), int(max_reads), CANDIDATE_ASSESSMENT_WINDOW_MAX_CANDIDATES),
    )
    ordered = tuple(sorted(unread, key=lambda item: (item.first_seen_rank, item.id)))
    forbidden = frozenset(
        item.canonical_url
        for item in candidates
        if item.id in excluded_candidate_ids
    )
    diagnostics = SelectionAuthorityDiagnostics()
    final_items: tuple[CandidatePoolItem, ...] = ()
    if limit > 0 and ordered:
        model_name = ""
        try:
            from src.llm_client import get_model_name

            profile = str(getattr(model_gateway, "model_profile", "") or "flash")
            model_name = get_model_name(profile)  # type: ignore[arg-type]
        except Exception:
            model_name = ""
        picks, diagnostics = select_candidates_with_model(
            model_gateway=model_gateway,
            claim_text=claim.text,
            candidates=ordered,
            max_picks=limit,
            timeout_seconds=timeout_seconds,
            logical_call_id=(
                f"research_selection_authority:{run_id}:{claim.id}:{wave_index}:1"
            ),
            forbidden_urls=forbidden,
            model_name=model_name,
        )
        if diagnostics.usable and picks:
            picked_urls = set(picks)
            final_items = tuple(
                item for item in ordered if item.canonical_url in picked_urls
            )
            diagnostics.selection_source = "model"
            if trace is not None:
                for item in ordered:
                    trace.note_window(
                        item.canonical_url,
                        selected=item.canonical_url in picked_urls,
                        reason="model_selection_not_chosen",
                    )
    if not final_items:
        # Deterministic legacy fallback on the ORIGINAL pool - never on the
        # model's leftovers, so a failed model call cannot shrink the pool.
        diagnostics.fallback_invoked = True
        final_items = _bounded_assessment_candidates(
            candidates,
            assignments=assignments,
            max_reads=max_reads,
            excluded_candidate_ids=excluded_candidate_ids,
            trace=trace,
        )
        diagnostics.fallback_picks = [item.canonical_url for item in final_items]
        if diagnostics.selection_source != "model":
            diagnostics.selection_source = "legacy_fallback"
    diagnostics.final_picks = [item.canonical_url for item in final_items]
    diagnostics.enabled = True

    metrics = context.setdefault(ACTIVE_RESEARCH_METRICS_KEY, {})
    if isinstance(metrics, dict):
        metrics["orchestration_model_calls"] = int(
            metrics.get("orchestration_model_calls") or 0
        ) + (1 if limit > 0 and ordered else 0)
        records = metrics.get("selection_authority")
        if not isinstance(records, list):
            records = []
        records.append(
            {
                "wave_index": wave_index,
                "claim_id": claim.id,
                "window_limit": limit,
                "orchestration_model_call": 1 if (limit > 0 and ordered) else 0,
                **diagnostics.to_dict(),
            }
        )
        metrics["selection_authority"] = records[-40:]
    return final_items


def _bounded_assessment_candidates(
    candidates: tuple[CandidatePoolItem, ...],
    *,
    assignments: Mapping[str, CandidateClusterAssignment],
    max_reads: int,
    excluded_candidate_ids: frozenset[str] = frozenset(),
    trace: SelectionTraceCollector | None = None,
) -> tuple[CandidatePoolItem, ...]:
    """Select a stable, cluster-diverse semantic-assessment window.

    The candidate pool remains frozen at its existing cap. This window only
    bounds model input to candidates that could still become physical reads in
    the run, preferring one candidate per server-owned source cluster before
    filling remaining slots in discovery order.
    """
    unread = tuple(
        item for item in candidates if item.id not in excluded_candidate_ids
    )
    limit = max(
        0,
        min(
            len(unread),
            int(max_reads),
            CANDIDATE_ASSESSMENT_WINDOW_MAX_CANDIDATES,
        ),
    )
    if limit == 0:
        if trace is not None:
            for item in unread:
                trace.note_window(
                    item.canonical_url, selected=False, reason="window_limit_zero"
                )
        return ()
    ordered = tuple(sorted(unread, key=lambda item: (item.first_seen_rank, item.id)))
    selected: list[CandidatePoolItem] = []
    deferred: list[CandidatePoolItem] = []
    seen_clusters: set[str] = set()
    for candidate in ordered:
        assignment = assignments.get(candidate.id)
        cluster_id = str(getattr(assignment, "cluster_id", "") or candidate.id)
        if cluster_id in seen_clusters:
            deferred.append(candidate)
            continue
        seen_clusters.add(cluster_id)
        selected.append(candidate)
        if len(selected) == limit:
            break
    if len(selected) < limit:
        selected.extend(deferred[: limit - len(selected)])
    if trace is not None:
        selected_ids = {item.id for item in selected}
        deferred_ids = {item.id for item in deferred}
        for item in ordered:
            if item.id in selected_ids:
                continue
            # Record which existing branch excluded the candidate: never
            # reached before the window filled, or considered only in the
            # deferred (same-cluster) pool that the remaining slots capped.
            reason = (
                "cluster_represented_by_earlier_candidate"
                if item.id in deferred_ids
                else "window_limit_reached"
            )
            trace.note_window(item.canonical_url, selected=False, reason=reason)
    return tuple(selected)


def _assessment_store(context: dict[str, Any]) -> dict[str, Any]:
    raw = context.get(ACTIVE_RESEARCH_ASSESSMENTS_KEY)
    return {str(key): value for key, value in raw.items()} if isinstance(raw, Mapping) else {}


def _assessment_inputs_store(context: dict[str, Any]) -> dict[str, list[str]]:
    """P1-C batch 2: per-claim candidate-id sets the stored rankings cover."""
    raw = context.get(ACTIVE_RESEARCH_ASSESSMENT_INPUTS_KEY)
    if not isinstance(raw, Mapping):
        return {}
    inputs: dict[str, list[str]] = {}
    for key, value in raw.items():
        if isinstance(value, list):
            inputs[str(key)] = [str(item) for item in value]
    return inputs


def _wave_gap_provenance(
    cursor: ResearchRuntimeCursor,
    state: ResearchState,
    gate: EvidenceGateResult,
    handled_gap_ids: tuple[str, ...],
) -> dict[str, GapBatchDelta]:
    """P1-C batch 2: per-gap GapBatchDelta provenance for one wave.

    A gap's delta reports the evidence ids its planned queries' candidates
    actually produced (read outcomes carrying an evidence id), the lead-
    relation subset of those, and the gate-detected conflict gaps of the
    gap's claim. The evaluator only credits ids that truly caused a frozen
    gain reason, so over-reporting here fails closed.
    """
    query_to_gap = {query.id: query.gap_id for query in cursor.planned_queries}
    evidence_id_by_candidate = {
        outcome.candidate_id: outcome.evidence_id
        for outcome in cursor.read_outcomes
        if outcome.evidence_id
    }
    lead_evidence_ids = {
        link.evidence_id for link in state.evidence_links if link.relation == "lead"
    }
    conflicts_by_claim: dict[str, set[str]] = {}
    for conflict in gate.conflicts:
        conflicts_by_claim.setdefault(conflict.claim_id, set()).add(conflict.id)
    claim_by_gap = {gap.id: gap.claim_id for gap in state.gaps}

    deltas: dict[str, GapBatchDelta] = {}
    for gap_id in handled_gap_ids:
        claim_id = claim_by_gap.get(gap_id, "")
        produced_evidence: set[str] = set()
        produced_leads: set[str] = set()
        for candidate_id, evidence_id in evidence_id_by_candidate.items():
            try:
                candidate = _candidate_by_id(cursor, candidate_id)
            except ValueError:
                continue
            if any(query_to_gap.get(query_id) == gap_id for query_id in candidate.query_ids):
                produced_evidence.add(evidence_id)
                if evidence_id in lead_evidence_ids:
                    produced_leads.add(evidence_id)
        deltas[gap_id] = GapBatchDelta(
            gap_id=gap_id,
            produced_evidence_ids=tuple(sorted(produced_evidence)),
            produced_conflict_gap_ids=tuple(
                sorted(conflicts_by_claim.get(claim_id, set()))
            ),
            produced_provenance_lead_ids=tuple(sorted(produced_leads)),
        )
    return deltas


def _ranked_from_dict(raw: Mapping[str, Any]) -> RankedCandidate:
    candidate_raw = cast(Mapping[str, Any], raw["candidate"])
    assessment_raw = cast(Mapping[str, Any], raw["assessment"])
    candidate = CandidatePoolItem(
        id=str(candidate_raw["id"]),
        canonical_url=str(candidate_raw["canonical_url"]),
        url=str(candidate_raw["url"]),
        title=str(candidate_raw["title"]),
        snippet=str(candidate_raw.get("snippet") or ""),
        source=str(candidate_raw.get("source") or ""),
        published_at=str(candidate_raw.get("published_at") or ""),
        query_ids=tuple(str(item) for item in candidate_raw.get("query_ids", [])),
        intents=tuple(GapSearchIntent(str(item)) for item in candidate_raw.get("intents", [])),
        providers=tuple(str(item) for item in candidate_raw.get("providers", [])),
        first_seen_rank=int(candidate_raw.get("first_seen_rank") or 0),
    )
    assessment = CandidateSemanticAssessment(
        candidate_id=str(assessment_raw["candidate_id"]),
        relevance=cast(Any, str(assessment_raw["relevance"])),
        relevance_confidence=float(assessment_raw["relevance_confidence"]),
        source_role=str(assessment_raw["source_role"]),
        source_role_confidence=float(assessment_raw["source_role_confidence"]),
        cluster_id=str(assessment_raw["cluster_id"]),
        expected_gain_signals=tuple(str(item) for item in assessment_raw.get("expected_gain_signals", [])),
        freshness_score=float(assessment_raw.get("freshness_score") or 0.0),
        estimated_read_cost=float(assessment_raw.get("estimated_read_cost") or 1.0),
    )
    return RankedCandidate(
        candidate=candidate,
        assessment=assessment,
        rank=int(raw["rank"]),
        eligibility=cast(Any, str(raw["eligibility"])),
        reason_codes=tuple(str(item) for item in raw.get("reason_codes", [])),
        new_cluster=bool(raw.get("new_cluster")),
        expected_information_gain=int(raw.get("expected_information_gain") or 0),
    )


def _fair_read_plan(
    state: ResearchState,
    rankings: Mapping[str, tuple[RankedCandidate, ...]],
    *,
    covered_cluster_ids_by_claim: Mapping[str, set[str]] | None = None,
    trace: SelectionTraceCollector | None = None,
    diagnostics: dict[str, Any] | None = None,
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    """Return ``(physical_reads, extraction_targets)`` for the read stage.

    B5-H3: deduplicate reads, not claim-evidence bindings. Physical reads are
    unique per candidate and bounded by the shared read budget; extraction
    targets bind ``(candidate_id, claim_id)`` pairs so one physical read can
    serve evidence extraction for multiple claims. Read-budget exhaustion
    never blocks binding an already-planned candidate to another claim: the
    budget only limits new physical candidates, not extraction-only reuse.

    §41 Read Reserve Reclaim: the conflict reserve exists to protect conflict
    resolution. When no conflict gap is open, the unused reserve returns to
    ordinary scheduling **within the existing hard read budget** - the hard
    cap (``max_reads - reads_used``) and every ranking/eligibility rule stay
    exactly as they were. With an open conflict the behaviour is unchanged.
    """
    claims = {claim.id: claim for claim in state.claims}
    physical: list[dict[str, str]] = []
    targets: list[dict[str, str]] = []
    physical_ids: set[str] = set()
    target_pairs: set[tuple[str, str]] = set()
    # H8: cluster diversity must span every wave of a claim, including
    # selections already bound through reusable candidates, so the fresh
    # acceptance loop skips clusters this claim already covers.
    claim_clusters: dict[str, set[str]] = {
        claim_id: set(cluster_ids)
        for claim_id, cluster_ids in (covered_cluster_ids_by_claim or {}).items()
    }
    open_conflict_claim_ids = {
        conflict.claim_id
        for conflict in state.conflict_gaps
        if conflict.state in {"open", "searching"}
    }
    reserve = ceil(state.budget.max_reads / 3)
    if open_conflict_claim_ids:
        reclaimed = 0
        reclaim_reason = "open_conflicts_present"
    else:
        reclaimed = reserve
        reclaim_reason = "no_open_conflicts"
    normal_limit = max(
        0,
        state.budget.max_reads - state.budget.reads_used - reserve + reclaimed,
    )
    if diagnostics is not None:
        diagnostics["read_reserve"] = {
            "configured": reserve,
            "reclaimed": reclaimed,
            "reclaim_reason": reclaim_reason,
            "hard_cap": state.budget.max_reads,
            "reads_used": state.budget.reads_used,
        }

    def _bind(candidate_id: str, claim_id: str, item: RankedCandidate) -> None:
        pair = (candidate_id, claim_id)
        if pair in target_pairs:
            return
        target_pairs.add(pair)
        claim_clusters.setdefault(claim_id, set()).add(item.assessment.cluster_id)
        targets.append(
            {
                "candidate_id": candidate_id,
                "claim_id": claim_id,
                "cluster_id": item.assessment.cluster_id,
                "source_role": item.assessment.source_role,
            }
        )

    def schedule(claim_ids: list[str], wave_size: int, *, allow_reserve: bool = False) -> None:
        for claim_id in claim_ids:
            ranked = tuple(
                item
                for item in rankings.get(claim_id, ())
                if (item.candidate.id, claim_id) not in target_pairs
            )
            if not ranked:
                continue
            # Reusable candidates must obey the same scheduler eligibility
            # predicate as fresh ones (H9): lead_only candidates without a
            # provenance-grade gain signal are never schedulable, even when
            # their physical read already exists.
            reusable = tuple(
                item
                for item in ranked
                if item.candidate.id in physical_ids and is_schedulable_candidate(item)
            )
            # Remove clusters covered by a prior successful wave before the
            # bounded scheduler truncates the claim's wave. Otherwise a major
            # claim (wave size 1) can select covered Q(X), discard it later,
            # and lose the independent backfill R(Y) entirely.
            covered_clusters = claim_clusters.get(claim_id, set())
            fresh = tuple(
                item
                for item in ranked
                if item.candidate.id not in physical_ids
                and item.assessment.cluster_id not in covered_clusters
            )
            remaining = state.budget.max_reads - state.budget.reads_used - len(physical)
            budget_open = remaining > 0 and (allow_reserve or len(physical) < normal_limit)
            if trace is not None:
                fresh_ids = {item.candidate.id for item in fresh}
                for item in ranked:
                    if item.candidate.id in physical_ids or item.candidate.id in fresh_ids:
                        continue
                    # Observed exclusion: the claim's cluster coverage already
                    # contains this candidate's cluster before scheduling.
                    trace.note_scheduler(
                        item.candidate.canonical_url,
                        decision="rejected",
                        reason="covered_cluster",
                    )
                    trace.note_scheduler_rejected(
                        item.candidate.canonical_url, stage="covered_cluster"
                    )
                if not budget_open:
                    for item in fresh:
                        trace.note_scheduler_rejected(
                            item.candidate.canonical_url, stage="budget"
                        )

            conflict_open = claim_id in open_conflict_claim_ids or any(
                "new_contradiction" in item.assessment.expected_gain_signals
                for item in ranked
            )
            policy = ReadSchedulerPolicy(
                critical_wave_size=wave_size,
                major_wave_size=wave_size,
                context_wave_size=0,
            )
            fresh_selected: list[str] = []
            by_id: dict[str, RankedCandidate] = {}
            if budget_open and fresh:
                budget = replace(state.budget, reads_used=state.budget.reads_used + len(physical))
                plan = plan_read_wave(
                    fresh,
                    claim=claims[claim_id],
                    budget=budget,
                    policy=policy,
                    conflict_open=conflict_open,
                    # §41: the reserve is only held when a conflict gap is
                    # actually open; otherwise ordinary scheduling reclaims it
                    # within the same hard read budget.
                    preserve_conflict_reserve=(
                        not allow_reserve and bool(open_conflict_claim_ids)
                    ),
                )
                by_id = {item.candidate.id: item for item in fresh}
                fresh_selected = [
                    candidate_id
                    for candidate_id in plan.selected_candidate_ids
                    if candidate_id in by_id
                ]

            # Reusable bindings first (rank order, cluster-diverse within the
            # claim across waves); remaining wave slots go to new physical
            # reads, skipping clusters this claim already covers (H8) without
            # wasting slots on the skipped entries.
            slots = wave_size
            for item in reusable:
                if slots <= 0:
                    break
                if item.assessment.cluster_id in claim_clusters.get(claim_id, set()):
                    continue
                _bind(item.candidate.id, claim_id, item)
                slots -= 1
            for candidate_id in fresh_selected:
                if slots <= 0:
                    break
                item = by_id[candidate_id]
                if item.assessment.cluster_id in claim_clusters.get(claim_id, set()):
                    continue
                _bind(candidate_id, claim_id, item)
                if candidate_id not in physical_ids:
                    physical_ids.add(candidate_id)
                    physical.append(
                        {
                            "candidate_id": candidate_id,
                            "claim_id": claim_id,
                            "cluster_id": item.assessment.cluster_id,
                            "source_role": item.assessment.source_role,
                        }
                    )
                slots -= 1

    critical = [claim.id for claim in _ordered_claims(state) if claim.priority == "critical"]
    major = [claim.id for claim in _ordered_claims(state) if claim.priority == "major"]
    schedule(critical, 1)
    schedule(critical, 2)
    schedule(major, 1)
    conflict_claims = [
        claim.id
        for claim in _ordered_claims(state)
        if claim.priority != "context"
        and (
            claim.id in open_conflict_claim_ids
            or any(
                "new_contradiction" in item.assessment.expected_gain_signals
                for item in rankings.get(claim.id, ())
            )
        )
    ]
    schedule(conflict_claims, reserve, allow_reserve=True)
    read_cap = max(0, state.budget.max_reads - state.budget.reads_used)
    return physical[:read_cap], targets


def _claim_lacks_primary_evidence(
    state: ResearchState,
    claim: ResearchClaim,
) -> bool:
    """True when the claim has no Gate-eligible primary evidence yet.

    Used only to decide whether a bounded lead read is worth spending; it never
    changes evidence eligibility.
    """

    evidence_by_id = {evidence.evidence_id: evidence for evidence in state.evidence}
    for link in state.evidence_links:
        if link.claim_id != claim.id:
            continue
        if link.source_role != "primary":
            continue
        if evidence_link_eligibility(
            claim=claim,
            link=link,
            evidence=evidence_by_id.get(link.evidence_id),
            reference_date=state.reference_date,
        ):
            return False
    return True


def _claim_has_discovery_gap(state: ResearchState, claim: ResearchClaim) -> bool:
    """True when a bounded lead read could close an evidence-topology gap.

    Slice 4: primary support and independent-cluster coverage are orthogonal.
    A lead read is justified when either
    - primary support is missing (existing rule), or
    - independent support clusters are partially covered
      (``0 < eligible_clusters < required``).

    ``0 / N`` is deliberately NOT a discovery gap: that is basic evidence
    discovery/assessment, and spending bounded lead reads there is not
    justified. This predicate only gates scheduling; it never changes evidence
    eligibility or the Gate.
    """

    if _claim_lacks_primary_evidence(state, claim):
        return True
    clusters, required, _has_primary = claim_support_topology(state, claim)
    return 0 < clusters < required


def _lead_read_plan(
    state: ResearchState,
    claim_rankings: Mapping[str, tuple[RankedCandidate, ...]],
    *,
    completed_read_ids: tuple[str, ...],
    lead_read_ids: tuple[str, ...],
    lead_budget_available: bool,
) -> list[dict[str, Any]]:
    """At most one bounded lead read per wave, strictly below evidence reads.

    Deterministic v1 rule (see ``is_schedulable_lead``): ``lead_only`` +
    primary/provenance/verification intent + the claim still lacks primary
    evidence + lead budget available. ``rejected`` candidates are never read.
    """

    if not lead_budget_available:
        return []
    seen: set[str] = set()
    for claim in _ordered_claims(state):
        if claim.priority != "critical":
            continue
        if not _claim_has_discovery_gap(state, claim):
            continue
        for item in claim_rankings.get(claim.id, ()):
            candidate_id = item.candidate.id
            if (
                candidate_id in completed_read_ids
                or candidate_id in lead_read_ids
                or candidate_id in seen
            ):
                continue
            # Slice 2A depth guard: a lead-discovered candidate is never read as
            # a lead again, so lead -> lead -> lead recursion cannot happen.
            if item.candidate.discovery_depth >= MAX_LEAD_DISCOVERY_DEPTH:
                continue
            if is_schedulable_lead(
                item, lead_budget_available=True, gap_needs_primary=True
            ):
                return [
                    {
                        "candidate": item.candidate,
                        "claim_id": claim.id,
                        "source_role": item.assessment.source_role,
                        "cluster_id": item.assessment.cluster_id,
                    }
                ]
            seen.add(candidate_id)
    return []


def _lead_metrics(context: dict[str, Any]) -> dict[str, int]:
    """Bounded lead-discovery counters for the run audit (Slice 3B)."""

    metrics = context.setdefault(ACTIVE_RESEARCH_METRICS_KEY, {})
    state = metrics.get("lead_discovery")
    if not isinstance(state, dict):
        state = {}
        metrics["lead_discovery"] = state
    return state


def _bump_lead_metric(
    context: dict[str, Any], key: str, amount: int = 1
) -> None:
    state = _lead_metrics(context)
    state[key] = int(state.get(key) or 0) + max(0, int(amount))


def _deeper_targeting_inputs(
    context: dict[str, Any],
) -> tuple[PageIntent | None, tuple[str, ...]]:
    """Latest §36A/§36B discovery hints, for §37A observability only.

    The linkage from one issued query back to a specific follow-up is
    approximate on purpose: the durable cursor records keep their frozen shape,
    so observability reads the most recent diagnostics entry instead of adding a
    query-to-follow-up key. ``hint_terms`` at the search call site remain exact.
    """

    metrics = context.get(ACTIVE_RESEARCH_METRICS_KEY)
    if not isinstance(metrics, Mapping):
        return None, ()
    state = metrics.get("deeper_targeting")
    if not isinstance(state, Mapping):
        return None, ()
    recent = state.get("recent")
    if not isinstance(recent, list) or not recent:
        return None, ()
    latest = recent[-1]
    if not isinstance(latest, Mapping):
        return None, ()
    raw_intent = latest.get("page_intent")
    intent: PageIntent | None = None
    if isinstance(raw_intent, Mapping) and raw_intent.get("kind"):
        path_terms = raw_intent.get("path_terms")
        intent = PageIntent(
            kind=str(raw_intent.get("kind") or ""),
            path_terms=tuple(str(item) for item in (path_terms or []) if str(item)),
            matched_terms=tuple(
                str(item) for item in (raw_intent.get("matched_terms") or []) if str(item)
            ),
        )
    raw_variants = latest.get("query_variants")
    variants = (
        tuple(str(item) for item in raw_variants if str(item))
        if isinstance(raw_variants, list)
        else ()
    )
    return intent, variants


def _search_discovery_slot(context: dict[str, Any]) -> int:
    """Execution-order index of the next issued query (deterministic)."""

    metrics = context.get(ACTIVE_RESEARCH_METRICS_KEY)
    if not isinstance(metrics, Mapping):
        return 1
    state = metrics.get("search_discovery")
    if not isinstance(state, Mapping):
        return 1
    queries = state.get("queries")
    return len(queries) + 1 if isinstance(queries, list) else 1


def _flush_selection_trace(
    context: dict[str, Any], trace: SelectionTraceCollector
) -> None:
    """§37B-selection: publish the diagnostic payload into run metrics only.

    Never touches the runtime cursor; the payload is rebuilt (derived terminal
    reasons) on every flush, so later observations are reflected without
    re-deriving any selection decision.
    """

    if len(trace) == 0:
        return
    metrics = context.setdefault(ACTIVE_RESEARCH_METRICS_KEY, {})
    if isinstance(metrics, dict):
        metrics["selection_trace"] = trace.to_payload()


def _record_deeper_targeting(
    context: dict[str, Any],
    *,
    gap: GapHint | None,
    source_url: str,
    selected_url: str,
    selected_depth: int,
    intent: PageIntent | None = None,
    variants: tuple[str, ...] = (),
) -> None:
    """§36A/§36B diagnostics (audit only; never qualification semantics).

    Recorded in ``metrics["deeper_targeting"]`` instead of the durable cursor
    record on purpose: the cursor codec strictly validates the follow-up key set,
    and discovery provenance must not become part of the frozen runtime contract.
    """

    metrics = context.setdefault(ACTIVE_RESEARCH_METRICS_KEY, {})
    state = metrics.get("deeper_targeting")
    if not isinstance(state, dict):
        state = {"gap_unavailable": 0, "strategy_counts": {}, "recent": []}
        metrics["deeper_targeting"] = state
    if gap is None:
        state["gap_unavailable"] = int(state.get("gap_unavailable") or 0) + 1
    else:
        counts = state.get("strategy_counts")
        if not isinstance(counts, dict):
            counts = {}
            state["strategy_counts"] = counts
        key = gap.targeting_strategy
        counts[key] = int(counts.get(key) or 0) + 1
        if intent is not None:
            intent_counts = state.get("page_intent_counts")
            if not isinstance(intent_counts, dict):
                intent_counts = {}
                state["page_intent_counts"] = intent_counts
            intent_counts[intent.kind] = int(intent_counts.get(intent.kind) or 0) + 1
    recent = state.get("recent")
    if not isinstance(recent, list):
        recent = []
        state["recent"] = recent
    source_authority = gap.source_authority_class if gap else ""
    selected_authoritative = bool(
        gap is not None
        and selected_url
        and authority_class(selected_url) != AUTHORITY_TUTORIAL
        and (
            gap.source_authority_class == AUTHORITY_OFFICIAL
            or target_path_hit(selected_url)
        )
    )
    recent.append(
        {
            "followup_reason": (
                "missing_target_fact" if gap is not None else "lead_without_usable_gap"
            ),
            "source_candidate_url": str(source_url or "")[:300],
            "source_authority_class": source_authority,
            "targeting_strategy": gap.targeting_strategy if gap else "unspecified",
            "gap_hint": gap.to_dict() if gap else {},
            # §36B slice 1 diagnostics: what kind of page was inferred, which
            # bounded variants were derived, and which one fed the hints.
            "page_intent": intent.to_dict() if intent is not None else {},
            "query_variants": list(variants[:3]),
            "selected_query_variant": variants[0] if variants else "",
            "selection_reason": selection_reason(
                authoritative=selected_authoritative,
                title_match=0,
                intent_match=len(intent.path_terms) if intent is not None else 0,
            ),
            "selected_candidate_url": str(selected_url or "")[:300],
            "selected_candidate_depth": int(selected_depth or 0),
        }
    )
    del recent[:-8]


def _lead_hints_for_claim(
    cursor: ResearchRuntimeCursor, claim_id: str
) -> tuple[str, tuple[str, ...]]:
    """Return ``(trusted_domain, hints)`` for one claim.

    ``trusted_domain`` may become a ``site:`` constraint, and only two sources
    are trusted: a domain explicitly *discovered* by a lead read, or a page
    whose server-owned source role is ``primary`` (recorded as
    ``trusted_primary_domain``). A mere source domain - the page we happened to
    read - is never returned as trusted, because locking a follow-up search into
    a mirror/aggregator domain makes primary evidence unreachable.
    """

    claim_query_ids = {
        item.id for item in cursor.planned_queries if item.claim_id == claim_id
    }
    if not claim_query_ids:
        return "", ()
    candidates_by_id = {item.id: item for item in cursor.candidates}
    trusted = ""
    hints: list[str] = []
    for payload in cursor.lead_discoveries:
        parent_id = str(payload.get("source_candidate_id") or "")
        parent = candidates_by_id.get(parent_id)
        if parent is None or not claim_query_ids.intersection(parent.query_ids):
            continue
        if not trusted:
            domains = payload.get("domains")
            if isinstance(domains, list):
                trusted = next(
                    (str(domain).strip() for domain in domains if str(domain).strip()),
                    "",
                )
        for key in ("organizations", "primary_source_hints"):
            values = payload.get(key)
            if isinstance(values, list):
                hints.extend(str(value) for value in values)
    # Evidence-stage lead follow-ups contribute bounded terms; their domain is
    # trusted only when the read page's own role was primary.
    for followup in cursor.evidence_lead_followups:
        parent_id = str(followup.get("source_candidate_id") or "")
        parent = candidates_by_id.get(parent_id)
        if parent is None or not claim_query_ids.intersection(parent.query_ids):
            continue
        if not trusted:
            trusted = str(followup.get("trusted_primary_domain") or "")
        terms = followup.get("hint_terms")
        if isinstance(terms, list):
            hints.extend(str(term) for term in terms[:2])
    return trusted, tuple(dict.fromkeys(hint for hint in hints if hint))


def _domain_of(url: str) -> str:
    try:
        return (urlsplit(str(url or "")).netloc or "").casefold()
    except ValueError:
        return ""


def _is_discovery_candidate(item: RuntimeCandidate) -> bool:
    """Candidates produced by a bounded discovery path (Slice 2 + Follow-up)."""

    return item.discovery_method in {"lead_url", "evidence_lead_url"}


def _harvest_page_urls(
    content: str,
    *,
    page_url: str,
    keywords: tuple[str, ...],
    limit: int = 4,
) -> tuple[str, ...]:
    """Deterministic deeper-URL harvest from an already-read page (no re-read).

    Priority (frozen v1): same domain + claim keyword > same domain > keyword.
    Every URL still goes through ``canonicalize_url`` (safe URL / SSRF policy).
    """

    page_canonical = canonicalize_url(page_url)
    page_domain = _domain_of(page_canonical)
    lowered_keywords = tuple(
        keyword.casefold() for keyword in keywords if len(str(keyword)) >= 3
    )
    scored: list[tuple[tuple[int, int, int], str]] = []
    seen: set[str] = set()
    for raw in re.findall(r"https?://[^\s\"'<>)\]},;]+", str(content or "")):
        canonical = canonicalize_url(raw)
        if not canonical or canonical == page_canonical or canonical in seen:
            continue
        seen.add(canonical)
        same_domain = int(bool(page_domain) and _domain_of(canonical) == page_domain)
        keyword_hit = int(
            any(keyword in canonical.casefold() for keyword in lowered_keywords)
        )
        depth = int(urlsplit(canonical).path.count("/") > 1)
        scored.append(((same_domain, keyword_hit, depth), canonical))
    scored.sort(key=lambda item: (-item[0][0], -item[0][1], -item[0][2], item[1]))
    return tuple(item[1] for item in scored[:limit])


def _evidence_lead_followup_candidates(
    existing: tuple[RuntimeCandidate, ...],
    *,
    page_url: str,
    content: str,
    parent: RuntimeCandidate,
    keywords: tuple[str, ...],
    max_candidates: int,
    gap: GapHint | None = None,
) -> tuple[tuple[RuntimeCandidate, ...], dict[str, int]]:
    """Turn an evidence-stage ``lead`` into bounded discovery input.

    This never re-reads the page and never calls a model: it consumes the
    already-read content of the eligible evidence page. ``relation="lead"``
    stays a discovery signal only - it is never weak/partial support.

    §36A: when a gap hint is available the harvested URLs are ordered by
    authoritative-deep-page rank (``rank_targeting_candidates``); ordering is a
    discovery preference only and never decides relation/strength/eligibility.
    """

    stats = {
        "added": 0,
        "no_deeper_url": 0,
        "duplicate_url_rejected": 0,
        "depth_blocked": 0,
        "cap_exhausted": 0,
    }
    if parent.discovery_depth >= MAX_LEAD_DISCOVERY_DEPTH:
        stats["depth_blocked"] = 1
        return (), stats
    urls = _harvest_page_urls(content, page_url=page_url, keywords=keywords)
    if not urls:
        stats["no_deeper_url"] = 1
        return (), stats
    if gap is not None:
        urls = rank_targeting_candidates(
            urls,
            source_url=page_url,
            source_authority_class=gap.source_authority_class,
        )
    known_urls = {item.url for item in existing}
    added: list[RuntimeCandidate] = []
    for url in urls:
        if len(existing) + len(added) >= max_candidates:
            stats["cap_exhausted"] = 1
            break
        if url in known_urls:
            stats["duplicate_url_rejected"] += 1
            continue
        known_urls.add(url)
        added.append(
            RuntimeCandidate(
                id=new_id("candidate"),
                url=url,
                title=url,
                snippet="",
                source="evidence_lead",
                published_at="",
                query_ids=parent.query_ids,
                intents=parent.intents,
                providers=("evidence_lead",),
                first_seen_rank=0,
                parent_lead_candidate_id=parent.id,
                discovery_method="evidence_lead_url",
                discovery_depth=min(
                    MAX_LEAD_DISCOVERY_DEPTH, parent.discovery_depth + 1
                ),
            )
        )
    stats["added"] = len(added)
    return tuple(added), stats


def _lead_discovered_candidates(
    existing: tuple[RuntimeCandidate, ...],
    discovery: LeadDiscoveryPayload,
    *,
    parent: RuntimeCandidate,
    max_candidates: int,
    discovered_so_far: int,
) -> tuple[tuple[RuntimeCandidate, ...], dict[str, int]]:
    """Convert lead-discovered URLs into candidates with discovery provenance.

    Slice 2C: identity is the canonical URL. A URL already in the pool is never
    duplicated, and ``parent_lead_candidate_id`` is provenance, not identity.
    Slice 2D: the new candidate receives no privilege - it inherits the parent's
    query ids so the existing per-claim assessment path sees it, and assessment
    -> eligibility -> scheduler still decides everything.

    Returns ``(added_candidates, stats)`` where stats are bounded counters for
    the lead-discovery audit (added / duplicate / unsafe / cap_exhausted /
    depth_blocked).
    """

    stats = {
        "added": 0,
        "duplicate_url_rejected": 0,
        "unsafe_url_rejected": 0,
        "cap_exhausted": 0,
        "depth_blocked": 0,
    }
    if parent.discovery_depth >= MAX_LEAD_DISCOVERY_DEPTH:
        stats["depth_blocked"] = 1
        return (), stats
    remaining_run_budget = (
        MAX_LEAD_DISCOVERED_CANDIDATES_PER_RUN - discovered_so_far
    )
    if remaining_run_budget <= 0:
        stats["cap_exhausted"] = 1
        return (), stats
    known_urls = {item.url for item in existing}
    added: list[RuntimeCandidate] = []
    for raw_url in discovery.discovered_urls:
        if len(added) >= remaining_run_budget:
            stats["cap_exhausted"] = 1
            break
        if len(existing) + len(added) >= max_candidates:
            stats["cap_exhausted"] = 1
            break
        canonical = canonicalize_url(raw_url)
        if not canonical:
            stats["unsafe_url_rejected"] += 1
            continue
        if canonical in known_urls:
            stats["duplicate_url_rejected"] += 1
            continue
        known_urls.add(canonical)
        added.append(
            RuntimeCandidate(
                id=new_id("candidate"),
                url=canonical,
                title=canonical,
                snippet="",
                source="lead_discovery",
                published_at="",
                query_ids=parent.query_ids,
                intents=parent.intents,
                providers=("lead_discovery",),
                first_seen_rank=0,
                parent_lead_candidate_id=parent.id,
                discovery_method="lead_url",
                discovery_depth=min(
                    MAX_LEAD_DISCOVERY_DEPTH, parent.discovery_depth + 1
                ),
            )
        )
    stats["added"] = len(added)
    return tuple(added), stats


def _restore_completed_read_targets(
    extraction_targets: list[dict[str, str]],
    *,
    completed_read_ids: set[str],
    rankings: Mapping[str, tuple[RankedCandidate, ...]],
) -> list[dict[str, str]]:
    """Restore only eligible per-claim bindings for already-read candidates.

    Physical-read reuse never grants semantic eligibility to another claim.
    The binding is rebuilt from that claim's own RankedCandidate, including its
    own role and cluster, and must pass the scheduler's shared predicate.
    """

    restored = list(extraction_targets)
    targeted_pairs = {
        (item["candidate_id"], item["claim_id"]) for item in extraction_targets
    }
    for claim_id in sorted(rankings):
        for item in rankings[claim_id]:
            candidate_id = item.candidate.id
            pair = (candidate_id, claim_id)
            if (
                candidate_id not in completed_read_ids
                or pair in targeted_pairs
                or not is_schedulable_candidate(item)
            ):
                continue
            restored.append(
                {
                    "candidate_id": candidate_id,
                    "claim_id": claim_id,
                    "cluster_id": item.assessment.cluster_id,
                    "source_role": item.assessment.source_role,
                }
            )
            targeted_pairs.add(pair)
    return restored


def _read_plan_entries(raw: Any, keys: tuple[str, ...]) -> list[dict[str, str]]:
    if not isinstance(raw, list):
        return []
    return [
        {key: str(item[key]) for key in keys}
        for item in raw
        if isinstance(item, Mapping) and all(key in item for key in keys)
    ]


def _load_read_plan(context: Mapping[str, Any]) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    """Load the persisted read plan as ``(physical_reads, extraction_targets)``.

    v2 persists both lists explicitly; the v1 format stored a single list of
    claim-bound entries, which is converted so in-flight runs keep resuming.
    """
    raw = context.get(ACTIVE_RESEARCH_READ_PLAN_KEY)
    if isinstance(raw, Mapping):
        physical_keys = ("candidate_id", "claim_id", "cluster_id", "source_role")
        return (
            _read_plan_entries(raw.get("physical_reads"), physical_keys),
            _read_plan_entries(raw.get("extraction_targets"), physical_keys),
        )
    if isinstance(raw, list):
        physical_keys = ("candidate_id", "claim_id", "cluster_id", "source_role")
        entries = _read_plan_entries(raw, physical_keys)
        physical: list[dict[str, str]] = []
        seen: set[str] = set()
        for item in entries:
            if item["candidate_id"] not in seen:
                seen.add(item["candidate_id"])
                physical.append(item)
        return physical, entries
    return [], []


def _candidate_by_id(cursor: ResearchRuntimeCursor, candidate_id: str) -> CandidatePoolItem:
    for item in cursor.candidates:
        if item.id == candidate_id:
            return _candidate_item(item)
    raise ValueError(f"unknown runtime candidate: {candidate_id}")


def _source_record(
    candidate: CandidatePoolItem,
    plan: Mapping[str, str],
    *,
    raw_read: Mapping[str, Any],
) -> dict[str, Any]:
    read = {
        "ok": raw_read.get("ok") is True,
        "status": str(raw_read.get("status") or "failed"),
        "url": candidate.url,
        "title": _bounded_text(raw_read.get("title") or candidate.title, 500),
        "content": str(raw_read.get("content") or "")[:6000],
        "error": _bounded_text(raw_read.get("error"), 200),
    }
    record = {
        "candidate_id": candidate.id,
        "item": {
            "title": candidate.title,
            "url": candidate.url,
            "source": candidate.source,
            "published_at": candidate.published_at,
        },
        "assessment": {
            "title": candidate.title,
            "url": candidate.url,
            "selected": True,
            "worth_reading": True,
            "source_role": plan["source_role"],
            "source_cluster_id": plan["cluster_id"],
            "claim_id": plan["claim_id"],
            "providers": list(candidate.providers),
        },
        "read": read,
        "read_status": read["status"],
        "evidence_state": "new" if read["status"] == "read" else "invalid_or_rejected",
    }
    retry = raw_read.get("read_retry")
    if isinstance(retry, Mapping):
        # §48 diagnostics only: how many bounded fetch-layer retries the reader
        # spent before this result; never influences evidence semantics.
        record["read_retry"] = {
            "attempts": int(retry.get("attempts") or 0),
            "retries": int(retry.get("retries") or 0),
            "retry_reasons": [
                _bounded_text(item, 160) for item in (retry.get("retry_reasons") or [])
            ][:4],
        }
    return record


def _inventory_fetch_with_retry(
    url: str,
    *,
    context: dict[str, Any],
    remaining_seconds: Any,
    fetch: Any = None,
) -> tuple[str, str, str, str]:
    """§63 + §50/B2: bounded, window-aware inventory fetch for sitemaps.

    Shares the retry admission policy with page reads but keeps its own
    diagnostics channel (``inventory_fetch``) and its own payload adapter: the
    fetch layer raises on transport failures and returns a 4-tuple, while the
    retry loop speaks in ``{"ok": ...}`` mappings.
    """

    if fetch is None:
        from src.news.article_fetcher import _fetch_text_payload

        fetch = _fetch_text_payload

    def _inner(target: str) -> Mapping[str, Any]:
        try:
            text, final_url, content_type, reason = fetch(
                target, timeout=12, max_bytes=1_500_000
            )
        except Exception as exc:  # transport exceptions are retryable
            return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
        if not text:
            return {
                "ok": False,
                "reason": str(reason or "empty_response"),
                "content_type": content_type,
            }
        return {
            "ok": True,
            "text": text,
            "final_url": final_url,
            "content_type": content_type,
        }

    mode = read_retry_mode()
    if mode == "off":
        payload = dict(_inner(url))
    else:
        admission = None
        if mode == "window_aware":
            admission = make_window_admission(remaining_seconds=remaining_seconds)
        payload = read_with_bounded_retry(
            url,
            read_fn=_inner,
            admission=admission,
            diagnostics_key="inventory_fetch",
        )
        _accumulate_fetch_metrics(
            context, "inventory_fetch", payload.get("inventory_fetch")
        )
    if payload.get("ok") is True:
        return (
            str(payload.get("text") or ""),
            str(payload.get("final_url") or url),
            str(payload.get("content_type") or ""),
            "",
        )
    return (
        "",
        "",
        "",
        str(payload.get("error") or payload.get("reason") or "fetch_failed"),
    )


def _accumulate_fetch_metrics(
    context: dict[str, Any], key: str, diagnostics: Any
) -> None:
    """§50/B2: aggregate per-fetch retry diagnostics into run metrics.

    ``read_retry`` and ``inventory_fetch`` are accumulated under their own keys
    so the two I/O classes stay separable; both use the same retry policy.
    """

    if not isinstance(diagnostics, Mapping):
        return
    metrics = context.setdefault(ACTIVE_RESEARCH_METRICS_KEY, {})
    if not isinstance(metrics, dict):
        return
    entry = metrics.get(key)
    if not isinstance(entry, dict):
        entry = {
            "fetches": 0,
            "attempts": 0,
            "retries": 0,
            "skipped_due_to_budget": 0,
            "retry_reasons": [],
            "admission_reasons": [],
        }
        metrics[key] = entry
    entry["fetches"] = int(entry.get("fetches") or 0) + 1
    entry["attempts"] = int(entry.get("attempts") or 0) + int(
        diagnostics.get("attempts") or 0
    )
    entry["retries"] = int(entry.get("retries") or 0) + int(
        diagnostics.get("retries") or 0
    )
    entry["skipped_due_to_budget"] = int(
        entry.get("skipped_due_to_budget") or 0
    ) + int(diagnostics.get("skipped_due_to_budget") or 0)
    reasons = entry.get("retry_reasons")
    if not isinstance(reasons, list):
        reasons = []
    reasons.extend(
        str(item)[:160] for item in (diagnostics.get("retry_reasons") or [])[:4]
    )
    entry["retry_reasons"] = reasons[-8:]
    admission_reasons = entry.get("admission_reasons")
    if not isinstance(admission_reasons, list):
        admission_reasons = []
    admission_reasons.extend(
        str(item)[:80] for item in (diagnostics.get("admission_reasons") or [])[:4]
    )
    entry["admission_reasons"] = admission_reasons[-8:]


def _upsert_source(records: list[dict[str, Any]], record: dict[str, Any]) -> None:
    candidate_id = record.get("candidate_id")
    for index, current in enumerate(records):
        if current.get("candidate_id") == candidate_id:
            records[index] = record
            return
    records.append(record)


def _source_by_candidate(records: list[dict[str, Any]], candidate_id: str) -> dict[str, Any] | None:
    return next((item for item in records if item.get("candidate_id") == candidate_id), None)


def _read_status(record: Mapping[str, Any]) -> str:
    read = record.get("read")
    return str(read.get("status") or "") if isinstance(read, Mapping) else ""


def _evidence_snapshot(
    run_id: str,
    selected_sources: list[dict[str, Any]],
    rejected_sources: list[dict[str, Any]],
):
    return build_evidence_snapshot(
        rag={
            "research_sources": {
                "run_id": run_id,
                "provider_status": "found",
                "source_truth_version": 2,
                "selected_sources": selected_sources,
                "rejected_sources": rejected_sources,
            }
        }
    )


def _evidence_id_for_record(
    run_id: str,
    record: Mapping[str, Any],
    selected_sources: list[dict[str, Any]],
    rejected_sources: list[dict[str, Any]],
) -> str:
    item = record.get("item")
    url = str(item.get("url") or "") if isinstance(item, Mapping) else ""
    for ref in _evidence_snapshot(run_id, selected_sources, rejected_sources).refs:
        if ref.url == url and ref.lifecycle_status == "selected":
            return ref.id
    raise ValueError("server-owned evidence identity unavailable")


def _add_extracted_evidence(state: ResearchState, *, evidence_id: str, link: Any) -> ResearchState:
    evidence = {item.evidence_id: item for item in state.evidence}
    evidence[evidence_id] = ResearchEvidence(
        evidence_id=evidence_id,
        locator=link.locator,
        anchored_spans=link.anchored_spans,
        lifecycle_status="read",
        extraction_status="eligible",
        published_at=link.published_at,
    )
    links = {
        (item.claim_id, item.evidence_id, item.relation): item
        for item in state.evidence_links
    }
    key = (link.claim_id, evidence_id, link.relation)
    links[key] = ResearchClaimEvidenceLink(
        link=ClaimEvidenceLinkV1(
            claim_id=link.claim_id,
            evidence_id=evidence_id,
            support_type=link.relation,
            confidence=link.strength,
        ),
        source_role=link.source_role,
        source_cluster_id=link.source_cluster_id,
        locator=link.locator,
        caveats=link.caveats,
    )
    clusters: dict[str, EvidenceCluster] = {item.id: item for item in state.source_clusters}
    current = clusters.get(link.source_cluster_id)
    clusters[link.source_cluster_id] = EvidenceCluster(
        id=link.source_cluster_id,
        evidence_ids=tuple(dict.fromkeys((*((current.evidence_ids) if current else ()), evidence_id))),
        source_role=link.source_role,
        independence_key=(current.independence_key if current else link.source_cluster_id),
    )
    return build_research_state(
        mode=state.mode,
        questions=state.questions,
        claims=state.claims,
        evidence=evidence.values(),
        evidence_links=links.values(),
        source_clusters=clusters.values(),
        gaps=state.gaps,
        conflict_gaps=state.conflict_gaps,
        budget=state.budget,
        trace=state.trace,
        brief=state.brief,
        reference_date=state.reference_date,
        known_evidence_ids=evidence,
    )


def _state_after_gate(state: ResearchState, gate: EvidenceGateResult) -> ResearchState:
    open_claims = set(gate.open_critical_claims)
    claims = tuple(
        replace(
            claim,
            state=(
                "contested"
                if any(conflict.claim_id == claim.id for conflict in gate.conflicts)
                else "unresolved"
                if claim.id in open_claims
                else "satisfied"
                if claim.priority == "critical"
                else claim.state
            ),
        )
        for claim in state.claims
    )
    claims_by_id = {claim.id: claim for claim in state.claims}
    gaps = tuple(
        replace(
            gap,
            state=(
                "open"
                if gap.claim_id in open_claims
                else "resolved"
                if claims_by_id.get(gap.claim_id) is not None
                and claims_by_id[gap.claim_id].priority == "critical"
                else gap.state
            ),
        )
        for gap in state.gaps
    )
    brief = ResearchBrief(
        claim_ids=tuple(claim.id for claim in claims),
        unresolved_claim_ids=tuple(sorted(open_claims)),
        conflict_gap_ids=tuple(item.id for item in gate.conflicts),
        outline=("eligible_evidence", "claim_links", "conflicts", "open_gaps", "gate"),
    )
    known = tuple(item.evidence_id for item in state.evidence)
    return build_research_state(
        mode=state.mode,
        questions=state.questions,
        claims=claims,
        evidence=state.evidence,
        evidence_links=state.evidence_links,
        source_clusters=state.source_clusters,
        gaps=gaps,
        conflict_gaps=gate.conflicts,
        budget=state.budget,
        trace=state.trace,
        brief=brief,
        reference_date=state.reference_date,
        known_evidence_ids=known,
    )


def _evidence_brief(
    state: ResearchState,
    gate: EvidenceGateResult | None,
    selected_sources: list[dict[str, Any]],
) -> dict[str, Any]:
    records_by_id = {
        str(record.get("candidate_id")): record for record in selected_sources
    }
    grounded_input = grounded_input_enabled()
    excerpt_budget = EXCERPT_TOTAL_CHARS if grounded_input else 0
    evidence_rows: list[dict[str, Any]] = []
    for link in state.evidence_links:
        evidence = next((item for item in state.evidence if item.evidence_id == link.evidence_id), None)
        if evidence is None or evidence.extraction_status != "eligible":
            continue
        record = next(
            (
                item
                for item in records_by_id.values()
                if (
                    isinstance(item.get("extractions"), Mapping)
                    and isinstance(item["extractions"].get(link.claim_id), Mapping)
                    and str(item["extractions"][link.claim_id].get("locator") or "") == link.locator
                )
                or (
                    isinstance(item.get("extraction"), Mapping)
                    and item["extraction"].get("claim_id") == link.claim_id
                    and item["extraction"].get("locator") == link.locator
                )
            ),
            {},
        )
        item = record.get("item") if isinstance(record, Mapping) else {}
        # H7: ResearchEvidence is the source-level identity, so its
        # locator/spans are whatever the last extraction wrote; claim-specific
        # anchors live in record["extractions"][claim_id] and must win when
        # one physical read serves multiple claims.
        claim_anchor: Mapping[str, Any] | None = None
        if isinstance(record, Mapping):
            extractions_map = record.get("extractions")
            if isinstance(extractions_map, Mapping):
                detail = extractions_map.get(link.claim_id)
                if isinstance(detail, Mapping):
                    claim_anchor = detail
        anchors_source = claim_anchor if claim_anchor is not None else {}
        row = {
            "evidence_id": link.evidence_id,
            "claim_id": link.claim_id,
            "relation": link.relation,
            "strength": link.strength,
            "source_role": link.source_role,
            "source_cluster_id": link.source_cluster_id,
            "title": str(item.get("title") or "") if isinstance(item, Mapping) else "",
            "url": str(item.get("url") or "") if isinstance(item, Mapping) else "",
            "locator": str(
                anchors_source.get("locator") or link.locator or ""
            ),
            "anchored_spans": list(
                anchors_source.get("anchored_spans") or evidence.anchored_spans
            ),
            "published_at": evidence.published_at,
            "caveats": list(
                anchors_source.get("caveats") or link.caveats
            ),
        }
        # §40d grounded input (default off): attach a bounded excerpt from the
        # page that was actually read, preferring the anchor's surroundings.
        if grounded_input and excerpt_budget > 0:
            read_payload = record.get("read") if isinstance(record, Mapping) else {}
            content = (
                str(read_payload.get("content") or "")
                if isinstance(read_payload, Mapping)
                else ""
            )
            anchor = str(
                row["locator"]
                or (row["anchored_spans"][0] if row["anchored_spans"] else "")
            )
            excerpt = grounded_excerpt(
                content,
                anchor=anchor,
                max_chars=min(EXCERPT_MAX_CHARS, excerpt_budget),
            )
            if excerpt:
                row["excerpt"] = excerpt
                excerpt_budget -= len(excerpt)
        evidence_rows.append(row)
    return {
        "schema_version": "research-evidence-brief-v1",
        "gate_status": gate.status if gate else "unavailable",
        "gate_reasons": list(gate.reasons) if gate else ["active_runtime_unavailable"],
        # H5: the conclusion constraint is a first-class brief field so
        # downstream consumers never present an unqualified strong conclusion
        # unless the Evidence Gate actually passed.
        "conditional_wording_required": (gate is None or gate.status != "pass"),
        "eligible_evidence": evidence_rows,
        "claim_links": [item.to_dict() for item in state.evidence_links if item.evidence_id in {row["evidence_id"] for row in evidence_rows}],
        "unresolved_conflicts": [item.to_dict() for item in (gate.conflicts if gate else state.conflict_gaps)],
        "open_critical_claim_ids": list(gate.open_critical_claims) if gate else [claim.id for claim in state.claims if claim.priority == "critical"],
        "open_gap_ids": list(gate.gap_ids) if gate else [gap.id for gap in state.gaps if gap.state in {"open", "searching"}],
        "budget": state.budget.to_dict(),
        "answer_instruction": (
            "Use only eligible evidence. State unresolved gaps and conflicts. "
            "When gate_status is not pass, use conditional language and do not present a complete conclusion."
            + (" " + ANSWER_SHAPE_CONTRACT if grounded_input else "")
        ),
    }


def _format_evidence_brief(brief: Mapping[str, Any]) -> str:
    lines = [
        "研究证据简报（仅可使用下列已读取并通过提取校验的证据）",
        f"Evidence Gate: {brief.get('gate_status', 'unavailable')}",
    ]
    for row in brief.get("eligible_evidence", []):
        if not isinstance(row, Mapping):
            continue
        lines.append(
            f"- [{row.get('relation')}] claim={row.get('claim_id')} "
            f"source={row.get('title') or row.get('url')} "
            f"cluster={row.get('source_cluster_id')} strength={row.get('strength')}"
        )
        lines.append(f"  anchor: {row.get('locator')}")
        excerpt = str(row.get("excerpt") or "")
        if excerpt:
            lines.append(f"  excerpt: {excerpt}")
        if row.get("url"):
            lines.append(f"  url: {row.get('url')}")
    open_claims = brief.get("open_critical_claim_ids") or []
    conflicts = brief.get("unresolved_conflicts") or []
    if open_claims:
        lines.append("未闭合关键结论：" + ", ".join(str(item) for item in open_claims))
    if conflicts:
        lines.append("仍有未解决冲突；回答必须并列呈现冲突证据。")
    if brief.get("conditional_wording_required") is True:
        lines.append(
            "结论约束：研究尚未通过完整证据核验；只能使用条件化措辞，不得输出无保留强结论。"
        )
    lines.append(str(brief.get("answer_instruction") or ""))
    return "\n".join(lines)[:20000]


def _eligible_items(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        dict(record.get("item") or {})
        for record in records
        if isinstance(record.get("extraction"), Mapping)
        and record["extraction"].get("status") == "eligible"
    ]


def _update_metrics(
    context: dict[str, Any],
    state: ResearchState,
    cursor: ResearchRuntimeCursor,
) -> None:
    context[ACTIVE_RESEARCH_METRICS_KEY] = {
        **(
            dict(context.get(ACTIVE_RESEARCH_METRICS_KEY) or {})
            if isinstance(context.get(ACTIVE_RESEARCH_METRICS_KEY), Mapping)
            else {}
        ),
        "candidate_count": len(cursor.candidates),
        "read_count": sum(item.status == "success" for item in cursor.read_outcomes),
        "cluster_count": len(state.source_clusters),
        "open_critical_gap_count": sum(
            gap.state in {"open", "searching"}
            and any(claim.id == gap.claim_id and claim.priority == "critical" for claim in state.claims)
            for gap in state.gaps
        ),
        "phase": cursor.phase,
    }


def _attempt_number(cursor: ResearchRuntimeCursor, item_id: str) -> int:
    interrupted = sum(
        _is_interrupted_failure(failure) and item_id in failure.item_id
        for failure in cursor.failures
    )
    if interrupted >= 2:
        raise _ExternalAttemptBudgetExhausted(
            f"external attempts exhausted for item: {item_id}"
        )
    return 1 + interrupted


def _model_attempt_start(
    cursor: ResearchRuntimeCursor,
    logical_call_id: str,
) -> int:
    """P1-C batch 2: next attempt for a logical model operation.

    Derived from completed audits plus exact recovered call IDs for the SAME
    logical call. A process crash leaves no completed audit, so the durable
    A legacy interrupted_unknown code or canonical v2 interrupted_unknown
    detail is required to advance attempt 1 -> attempt 2.
    Once the frozen ceiling has been consumed, fail before another physical
    model call can reuse the last call ID.
    """
    previous = [
        call.attempt
        for call in cursor.model_calls
        if call.logical_call_id == logical_call_id
    ]
    recovered_prefix = f"{logical_call_id}:attempt:"
    for failure in cursor.failures:
        if not _is_interrupted_failure(failure) or not failure.item_id.startswith(
            recovered_prefix
        ):
            continue
        raw_attempt = failure.item_id[len(recovered_prefix) :]
        if raw_attempt.isdigit():
            previous.append(int(raw_attempt))
    last_attempt = max(previous, default=0)
    if last_attempt >= MAX_RESEARCH_MODEL_ATTEMPTS:
        raise _ModelAttemptBudgetExhausted(
            f"model attempts exhausted for logical call: {logical_call_id}"
        )
    return last_attempt + 1


def _is_interrupted_failure(failure: Any) -> bool:
    """Recognize legacy v1 and canonical v2 interruption records."""

    return failure.code == "interrupted_unknown" or (
        failure.detail == "interrupted_unknown" and bool(failure.attempt_id)
    )


def _assessment_call_suffix(
    cursor: ResearchRuntimeCursor,
    claim_id: str,
    candidate_ids: tuple[str, ...],
) -> str:
    """P1-C batch 2: pure semantic identity for one assessment operation.

    Wave + claim + sorted candidate fingerprint — never the audit log length —
    so a crash/resume re-runs the SAME logical operation (attempt layer then
    advances) instead of minting a new logical identity.
    """
    fingerprint = hashlib.sha256(
        "|".join(sorted(candidate_ids)).encode("utf-8")
    ).hexdigest()[:12]
    return f":{cursor.wave_id}:{claim_id}:{fingerprint}"


def _extraction_call_suffix(
    cursor: ResearchRuntimeCursor,
    candidate_id: str,
    claim_id: str,
) -> str:
    """P1-C batch 2: pure semantic identity for one extraction operation."""
    return f":{cursor.wave_id}:{candidate_id}:{claim_id}"


def _dedupe(values: list[str]) -> list[str]:
    return list(dict.fromkeys(str(value)[:500] for value in values if str(value).strip()))


def _bounded_text(value: Any, limit: int) -> str:
    return " ".join(str(value or "").split())[:limit]


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _utc_date() -> str:
    return datetime.now(timezone.utc).date().isoformat()


__all__ = [
    "ACTIVE_RESEARCH_ASSESSMENTS_KEY",
    "ACTIVE_RESEARCH_BRIEF_KEY",
    "ACTIVE_RESEARCH_METRICS_KEY",
    "ACTIVE_RESEARCH_POLICY_AUDITS_KEY",
    "ACTIVE_RESEARCH_READ_PLAN_KEY",
    "ActiveResearchCancelled",
    "ActiveResearchRuntimeExecutor",
]
