"""Production executor for one bounded active Claim Engine research wave.

The existing WebLookupRepository remains the operation and persistence owner.
This executor composes the previously delivered claim, query, candidate,
assessment, ranking, scheduling, reading, extraction and Evidence Gate
components without changing off/shadow/legacy execution.
"""

from __future__ import annotations

import hashlib
import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from functools import partial
from math import isfinite
import re
import sys
import time
from typing import Any, cast
from urllib.parse import urlsplit

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
from src.web.research.candidate_ranking import RankedCandidate
from src.web.research.claim_planner import RuntimeClaimPlanner
from src.web.research.deeper_targeting import (
    GapHint,
    gap_from_extraction,
    rank_targeting_candidates,
    targeted_query_terms,
)
from src.web.research.deep_runtime import (
    SEED_DISCOVERY_METHOD,
    DeepIntegrityError,
    deep_preflight,
    SEED_FINAL_BACKEND,
    SEED_PROVIDER,
    content_available_ids,
    effective_deep_base_elapsed,
    load_execution_envelope,
    load_seed,
    materialization_provenance,
    materialized_content,
    seed_candidate_identity,
    seed_sources_by_url,
)
from src.web.research.page_intent import (
    infer_page_intent,
    query_variants,
)
from src.web.research.contracts import (
    EvidenceGap,
    ResearchClaim,
    ResearchState,
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
from src.web.research.evidence_gain import GapBatchDelta
from src.web.research.failure_contracts import ResearchFailureCode
from src.web.research.gap_planner import (
    GapQueryBatch,
    GapSearchIntent,
    PlannedGapQuery,
    plan_gap_queries,
    query_terms,
)
from src.web.research.model_gateway import (
    MAX_RESEARCH_MODEL_ATTEMPTS as MAX_RESEARCH_MODEL_ATTEMPTS,
    ResearchModelGateway,
)
from src.web.research.phase_budget import FINALIZATION_RESERVE_SECONDS
from src.web.research.runtime import (
    _ExternalAttemptBudgetExhausted as _ExternalAttemptBudgetExhausted,
    _ModelAttemptBudgetExhausted as _ModelAttemptBudgetExhausted,
    _assessment_call_suffix as _assessment_call_suffix,
    _attempt_number as _attempt_number,
    _extraction_call_suffix as _extraction_call_suffix,
    _is_interrupted_failure as _is_interrupted_failure,
    _model_attempt_start as _model_attempt_start,
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
    RuntimePlannedQuery,
    RuntimeReadOutcome,
    attach_runtime_cursor,
    begin_external_attempt,
    finish_external_attempt,
    load_runtime_cursor,
    recover_interrupted_external_attempt,
    recover_interrupted_model_attempt,
)
from src.web.research.scheduler import (
    ReadSchedulingCancelled,
    _restore_completed_read_targets as _restore_completed_read_targets,
    is_schedulable_lead,
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
from src.web.research.read_escalation import (
    TIER_BROWSER,
    charge_http_envelope,
    reset_http_envelope,
    reset_run_envelope,
    set_escalation_runtime_context,
)
from src.web.research.timing_ledger import (
    ACTIVE_RESEARCH_METRICS_KEY,
    RuntimePhaseTiming,
    TimedGateway,
    TimingLedger,
    _record_checkpoint_timing,
)
from src.web.research.health_breaker import (
    NATIVE_HTTP_BACKEND,
    PerRunBreaker,
    breaker_policy_from_env,
    deadline_preflight,
    host_of,
    read_breaker_enabled,
)
from src.web.research.failure_taxonomy import (
    classify,
)
from src.web.research.chain_executor import (
    ChainAttemptRequest,
    ChainStepResult,
    run_chain,
)
from src.web.research.wigolo_http_executor import (
    WIGOLO_HTTP_BACKEND,
    WigoloHttpBackendExecutor,
)
from src.web.research.read_adequacy import classify_reader_result
from src.web.research.read_retry import (
    error_signature,
    make_window_admission,
    read_retry_mode,
    read_with_bounded_retry,
)
from src.web.research.selection_trace import SelectionTraceCollector
from src.web.research.atomic_routing import (
    atomic_routing_enabled,
    route_missing_atomic_claims,
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
    _pending_active_steering_ids as _pending_active_steering_ids,
    _steering_ids_for_claim as _steering_ids_for_claim,
    _unapplied_steering_blocks_completion as _unapplied_steering_blocks_completion,
)
from src.application.research_stop_gate import (
    ResearchStopGate,
    ResearchStopSignal,
)
from src.application.research_runtime_checkpoint import (
    ActiveRuntimeCheckpointSession,
    updated_runtime_budget,
)
from src.application.research_runtime_result_buffers import (
    ActiveResearchResultBuffers,
    upsert_source_record,
)
from src.application.research_runtime_source_evidence_context import (
    ReadSourceEvidenceContext,
)
from src.application.research_runtime_evidence_acceptance import (
    ExtractedEvidenceAcceptanceContext,
)
from src.application.research_runtime_extraction_failure import (
    ExtractionFailureContext,
)
from src.application.research_runtime_model_policy import (
    ACTIVE_RESEARCH_POLICY_AUDITS_KEY,
    RuntimeModelPolicyContext,
)
from src.application.research_runtime_model_attempt_context import (
    ActiveModelAttemptContext,
)
from src.application.research_runtime_steering_context import ActiveResearchSteeringContext
from src.application.research_runtime_wave_settlement import (
    ActiveWaveSettlementContext,
    ActiveWaveSettlementHandoff,
    ActiveWaveSettlementSnapshot,
)
from src.application.research_runtime_wave_baseline import (
    ACTIVE_RESEARCH_WAVE_BASELINE_KEY as ACTIVE_RESEARCH_WAVE_BASELINE_KEY,
    ActiveWaveBaselineContext,
)
from src.application.research_runtime_wave_progress import ActiveWaveProgressContext
from src.application.research_runtime_failure_projection import (
    with_appended_runtime_failure,
)
from src.application.research_runtime_search_outcomes import ActiveSearchOutcomeContext
from src.application.research_runtime_read_attempt_context import ActiveReadAttemptContext
from src.application.research_runtime_read_scheduling import ActiveReadDispatchContext
from src.application.research_runtime_read_execution import ActiveReadExecutionContext
from src.application.research_runtime_read_plan_context import FairReadPlanContext
from src.application.research_runtime_read_budget_context import ReadWaveBudgetContext
from src.application.research_runtime_read_quota_context import ReadWaveQuotaContext
from src.application.research_runtime_read_coverage import (
    ACTIVE_RESEARCH_COVERED_CLUSTERS_KEY as ACTIVE_RESEARCH_COVERED_CLUSTERS_KEY,
    merge_covered_clusters,
)
from src.application.research_runtime_read_observation import ActiveReadObservationContext
from src.application.research_runtime_read_projection import project_read_chain
from src.application.research_runtime_read_site import (
    ActiveReadSiteContext,
    READ_SITE_HINT_ROUTE_DEFAULT as READ_SITE_HINT_ROUTE_DEFAULT,
    READ_SITE_HINT_ROUTE_SPECIALIST as READ_SITE_HINT_ROUTE_SPECIALIST,
    read_site_hint_route as read_site_hint_route,
    record_read_site_specialist as record_read_site_specialist,
    specialist_chain_run as specialist_chain_run,
)
from src.application.research_runtime_budget_clock import ResearchBudgetClock
from src.application.research_selection_observability import (
    ResearchSelectionTraceContext,
    record_selection_authority,
)
from src.application.research_runtime_live_values import ActiveRuntimeLiveValues
from src.application.research_runtime_assessment_results import (
    ACTIVE_RESEARCH_ASSESSMENTS_KEY as ACTIVE_RESEARCH_ASSESSMENTS_KEY,
    ACTIVE_RESEARCH_ASSESSMENT_INPUTS_KEY as ACTIVE_RESEARCH_ASSESSMENT_INPUTS_KEY,
    ActiveAssessmentResultContext,
    assessment_store as _assessment_store,
    record_assessment_result,
)
from src.application.research_runtime_discovery_diagnostics import (
    ActiveDiscoveryDiagnosticsContext,
)
from src.application.research_runtime_late_tail_diagnostics import (
    LateTailDiagnosticsContext,
)
from src.application.research_runtime_fetch_retry_observation import (
    _accumulate_fetch_metrics as _accumulate_fetch_metrics,
    _inventory_fetch_with_retry as _inventory_fetch_with_retry,
)
from src.application.research_runtime_search_execution import (
    ActiveSearchQueryExecution,
    _lead_hints_for_claim as _lead_hints_for_claim,
)
from src.application.research_runtime_execution_guard import (
    ActiveResearchCancelled,
    ActiveResearchExecutionGuard,
    HardResearchBudgetReached as _HardBudgetReached,
)
from src.application.research_runtime_publication import ActiveResearchPublisher
from src.application.research_runtime_window_diagnostics import ResearchWindowDiagnostics
from src.application.active_research_evidence_projection import (
    _bounded_retrieval_policy as _bounded_retrieval_policy,
    _bounded_text,
    _source_record,
    _evidence_brief,
    _state_after_gate,
)
from src.application.research_runtime_read_observability import (
    _record_atomic_routing_decisions,
    _record_atomic_routing_extractions,
    _record_backend_health as _record_backend_health,
    _record_escalation_diagnostics as _record_escalation_diagnostics,
    _record_read_chain_decision,
    _record_read_history,
    _record_read_timing as _record_read_timing,
)

ACTIVE_RESEARCH_READ_PLAN_KEY = "claim_engine_read_plan"
ACTIVE_RESEARCH_BRIEF_KEY = "claim_engine_evidence_brief"
TIER2_PROPOSED_CLAIMS_KEY = "tier2_proposed_claim_ids"
DOMAIN_TARGETED_CLAIMS_KEY = "domain_targeted_claim_ids"
MAX_DOMAIN_TARGETED_CANDIDATES = 3
MAX_DOMAIN_TARGETED_SEARCH_FETCHES = 3
DOMAIN_TARGETED_MIN_SECONDS_LEFT = 12.0
CANDIDATE_ASSESSMENT_WINDOW_MAX_CANDIDATES = 2
# §69/B1-T5 R1': a discovery channel can only admit candidates *after* the
# initial assessment window was frozen for the wave, which made them
# unreachable for the read plan (not_in_rank_window). The late-admission
# assessment tail is an independent, claim-scoped entry (<=2/claim/wave) for
# exactly those candidates: no selector call, no eviction, and it still obeys
# the global window and model-call budget. A wave may therefore assess up to
# 2 (initial window) + 2 (late tail) = 4 candidates.
LATE_TAIL_MAX_CANDIDATES = 2
# §71A/F1 frozen 3.0s (was 8.0, a conservative bootstrap value).
#
# Semantics (frozen): the floor is an **assessment-viability guard**, not a
# downstream-completion reservation. It only answers "is it still worth
# starting the assessment?" - ranking, the read scheduler and the evidence
# chain decide the rest, and must not have that decision pre-empted here.
#
# Evidence: post-§71A-1 assessment cost measured at 0.89-1.14s over eight clean
# replays (3.0 gives ~2.6-3.4x headroom even at the slowest observation), and
# 3.0/4.0/8.0 were behaviourally identical on every clean sample - they differ
# only in the 3s < remaining < 4s band, where 4.0 has no evidence for refusing
# work that costs about a second. Higher floors buy false negatives, not
# correctness. RESEARCH_LATE_TAIL_FLOOR_SECONDS still overrides for experiments.
LATE_TAIL_MIN_SECONDS_LEFT = 3.0
LATE_TAIL_FLOOR_ENV = "RESEARCH_LATE_TAIL_FLOOR_SECONDS"


def late_tail_floor_seconds() -> float:
    """Late-tail admission floor (seconds left in the window).

    Assessment-viability guard: it decides whether an assessment can still be
    started, not whether the whole late-read chain can complete. Overridable for
    experiments only; the frozen default is LATE_TAIL_MIN_SECONDS_LEFT.
    """

    raw = os.getenv(LATE_TAIL_FLOOR_ENV)
    try:
        value = float(raw) if raw is not None and raw != "" else LATE_TAIL_MIN_SECONDS_LEFT
    except (TypeError, ValueError):
        value = LATE_TAIL_MIN_SECONDS_LEFT
    return max(1.0, min(value, 60.0))

PolicyCheck = Callable[[Mapping[str, Any], str], bool]


#: §143-B0: the explicit reader chain is the only authority that may execute a
#: reader. ``native_http`` runs the plain read (the adapter no longer escalates);
#: ``wigolo_http`` is the A2d-3 executor carrying the shared B2 guards.
#: ``wigolo_browser`` is deliberately not enabled.
#:
#: Promoted from a function-local name so the chain is a stable, importable
#: contract rather than an implementation detail of ``execute()``.
ACTIVE_READER_CHAIN: tuple[str, str] = (NATIVE_HTTP_BACKEND, WIGOLO_HTTP_BACKEND)


GatewayRead = Callable[..., Mapping[str, Any]]


def build_read_chain_executors(
    *,
    source_limit: int,
    gateway_read: GatewayRead,
    escalation_backend: Any,
    hard_seconds_left: Callable[[], float],
) -> dict[str, Any]:
    """§143-B0: the single implementation authority for reader executors.

    Both ``ActiveResearchRuntimeExecutor.execute()`` and the narrow measurement
    entry call **this** function, so a measurement can never observe a
    hand-rolled "equivalent" of the production default.

    Mechanical extraction of the former nested ``read_chain_executors``: the
    captured runtime closures are now explicit parameters. No behaviour change.
    """

    def _native(target: str) -> Mapping[str, Any]:
        return gateway_read(target, max_chars=source_limit)

    return {
        NATIVE_HTTP_BACKEND: NativeHttpBackendExecutor(read_fn=_native),
        WIGOLO_HTTP_BACKEND: WigoloHttpBackendExecutor(
            backend=escalation_backend,
            max_chars=source_limit,
            hard_seconds_left=hard_seconds_left,
            charge_envelope=charge_http_envelope,
        ),
    }


def build_production_gateway_read(
    *,
    gateway: Any,
    accepts_timeout: bool,
    get_context: Callable[[], dict[str, Any]],
    research_seconds_left: Callable[[], float],
    hard_seconds_left: Callable[[], float],
    wave_index: Callable[[], int],
    on_phase_start: Callable[[str], None] | None = None,
    on_phase_end: Callable[[str], None] | None = None,
    on_retry: Callable[..., None] | None = None,
) -> Callable[..., dict[str, Any]]:
    """§143-B0.1: the single implementation authority for production read semantics.

    Both ``ActiveResearchRuntimeExecutor.execute()`` and the narrow measurement
    entry build their ``gateway_read`` through **this** function, so a
    measurement can never observe a hand-rolled "equivalent" of the production
    read path.

    Everything with behavioural meaning is owned here, not by callers:

    * metrics/context sequencing (``retrieval_attempt_seq``);
    * escalation runtime context (``set_escalation_runtime_context``);
    * the bounded retry policy (§48/§49) including the ``window_aware``
      admission and deadline-preserving retry suppression;
    * the research-window / finalization reserve that bounds the read timeout.

    Callers only inject low-level, production-owned dependencies: the
    underlying ``gateway`` fetch, the research clock, the telemetry/context
    cursor and the current wave index. Observation hooks (phase timing, retry
    ledger) are optional and never change control flow. No caller may pass a
    ``gateway_read``; the read function is created here and nowhere else.
    """

    def gateway_read(url: str, *, max_chars: int) -> dict[str, Any]:
        """Read a page through the shared production read semantics."""

        def _inner(target: str) -> Mapping[str, Any]:
            # §71B/B1: stamp per-read scalars so the adapter-side escalation
            # outcome carries the attempt order and the headroom at start.
            context = get_context()
            metrics_for_seq = context.setdefault(ACTIVE_RESEARCH_METRICS_KEY, {})
            seq = int(metrics_for_seq.get("retrieval_attempt_seq") or 0) + 1
            metrics_for_seq["retrieval_attempt_seq"] = seq
            set_escalation_runtime_context(
                attempt_seq=seq,
                research_seconds_left=research_seconds_left(),
                hard_seconds_left=hard_seconds_left(),
            )
            if accepts_timeout:
                return (
                    gateway.read(
                        target,
                        max_chars=max_chars,
                        timeout=min(
                            READ_TIMEOUT_CAP_SECONDS,
                            max(0.0, research_seconds_left()),
                        ),
                    )
                    or {}
                )
            return gateway.read(target, max_chars=max_chars) or {}

        mode = read_retry_mode()
        if on_phase_start is not None:
            on_phase_start("read")

        def _with_escalation_ledger(payload: dict[str, Any]) -> dict[str, Any]:
            escalation = payload.get("escalation")
            if isinstance(escalation, Mapping):
                _record_escalation_diagnostics(
                    get_context(), escalation, wave_index=int(wave_index())
                )
            return payload

        try:
            if mode == "off":
                return _with_escalation_ledger(dict(_inner(url)))
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
                # F2-O1b B: deadline-preserving retry suppression - a retry
                # is only issued when its wait plus the last attempt's own
                # cost still fit the remaining research window.
                remaining_seconds=research_seconds_left,
            )
            _accumulate_fetch_metrics(
                get_context(), "read_retry", payload.get("read_retry")
            )
            _retry_diag = payload.get("read_retry")
            if isinstance(_retry_diag, Mapping) and on_retry is not None:
                on_retry(
                    wait_ms=float(_retry_diag.get("retry_backoff_ms") or 0.0),
                    fetch_ms=float(_retry_diag.get("retry_fetch_ms") or 0.0),
                )
            return _with_escalation_ledger(payload)
        finally:
            if on_phase_end is not None:
                on_phase_end("read")

    return gateway_read


def run_single_read_measurement(
    *,
    url: str,
    source_limit: int,
    gateway: Any,
    escalation_backend: Any,
    get_context: Callable[[], dict[str, Any]],
    research_seconds_left: Callable[[], float],
    hard_seconds_left: Callable[[], float],
    accepts_timeout: bool = False,
    wave_index: Callable[[], int] | None = None,
    candidate_id: str = "f2-measurement",
    outer_attempt_number: int = 1,
) -> tuple[Any, tuple[Any, ...]]:
    """§143-B0/B0.1: the narrow measurement entry.

    Executes exactly one frozen read target through the **same** production
    primitives that ``ActiveResearchRuntimeExecutor.execute()`` uses:
    :func:`build_production_gateway_read` + :func:`build_read_chain_executors`
    + :func:`run_chain` with :data:`ACTIVE_READER_CHAIN`.

    It deliberately does **not** call ``execute()`` and never starts discovery,
    planning or synthesis. It carries no routing, deadline or budget logic of
    its own, and it accepts **no** ``gateway_read``: read semantics live only in
    the shared production primitive above, so a caller cannot inject a
    hand-rolled read path.

    Returns ``(chain_run, recorded_steps)`` where ``recorded_steps`` is the real
    ``record_outcome`` event sequence - the authoritative source of the backend
    path.
    """

    gateway_read = build_production_gateway_read(
        gateway=gateway,
        accepts_timeout=accepts_timeout,
        get_context=get_context,
        research_seconds_left=research_seconds_left,
        hard_seconds_left=hard_seconds_left,
        wave_index=(lambda: 0) if wave_index is None else wave_index,
    )
    executors = build_read_chain_executors(
        source_limit=source_limit,
        gateway_read=gateway_read,
        escalation_backend=escalation_backend,
        hard_seconds_left=hard_seconds_left,
    )
    recorded: list[Any] = []
    chain_run = run_chain(
        candidate_id=candidate_id,
        url=url,
        host=host_of(url),
        outer_attempt_number=outer_attempt_number,
        chain=ACTIVE_READER_CHAIN,
        executors=executors,
        record_outcome=recorded.append,
    )
    return chain_run, tuple(recorded)


# Multimodal Reader v1 read-site seam (docs/PROJECT_STATUS.md §144.15).
# The read site never invents visual metadata: the caller/operator declares it on
# the run context, exactly like every other injected read seam. The declaration
# is JSON-safe; the fetch seams are module-level indirections so tests can inject
# fakes without a real runtime (same pattern as reader_hint_routing).
VISUAL_METADATA_BY_URL_KEY = "visual_metadata_by_url"

#: Injected visual seams (operator / test). ``None`` -> no fetch, fail-closed.
_VISUAL_IMAGE_FETCHER: Any = None
_VISUAL_IMAGE_DESTINATION: Any = None
#: ``None`` -> build from the real G14-c gate (off unless the operator enables it).
_VISUAL_VISION_ADAPTER: Any = None


def _default_visual_fetcher() -> Any:
    """The real, SSRF-aware fetcher (§144.16). Still gated by max_vision_calls."""

    from src.web.research.visual_image_http import default_image_fetcher

    return default_image_fetcher()


def _default_visual_destination() -> Any:
    """A bounded temp cache dir; the caller never sees the bytes."""

    from src.web.research.visual_image_fetch import default_image_destination

    return default_image_destination()


def _read_visual_evidence_for_candidate(
    *,
    context: dict[str, Any],
    state: ResearchState,
    canonical_url: str,
) -> list[dict[str, Any]]:
    """Declared visual metadata -> bounded visual units (default-inert).

    Returns ``[]`` without any side effect when the operator has not enabled any
    vision call, so the default production trace is unchanged. A visual failure
    is swallowed: a successful text read must never become a failure because of
    the visual side, and the visual audit stays additional observability.

    The declaration is keyed by canonical URL: it must be decidable *before* the
    run, and it is never derived from the page.
    """

    try:
        from src.web.research.visual_read_budget import (
            configured_max_vision_calls,
        )

        if configured_max_vision_calls() == 0:
            return []
        declared = context.get(VISUAL_METADATA_BY_URL_KEY)
        if not isinstance(declared, Mapping):
            return []
        payload = declared.get(canonical_url)
        if payload is None:
            return []
        from src.application.research_visual_read import read_visual_evidence

        if isinstance(payload, Mapping):
            read_payload = {
                "visual_metadata": payload.get("visual_metadata") or [],
            }
            required_units = tuple(payload.get("required_units") or ())
        else:
            read_payload = {"visual_metadata": payload}
            required_units = ()
        result = read_visual_evidence(
            read_payload=read_payload,
            required_units=required_units,
            state=state,
            context=context,
            fetcher=_VISUAL_IMAGE_FETCHER or _default_visual_fetcher(),
            destination_dir=_VISUAL_IMAGE_DESTINATION or _default_visual_destination(),
            adapter=_VISUAL_VISION_ADAPTER,
        )
    except Exception:  # noqa: BLE001 - the visual side must never break a read
        return []

    metrics = context.setdefault(ACTIVE_RESEARCH_METRICS_KEY, {})
    if isinstance(metrics, dict):
        entries = metrics.get("visual_reads")
        if not isinstance(entries, list):
            entries = []
        entries.append(
            {
                "canonical_url": str(canonical_url),
                "vision_calls": int(result.vision_calls),
                "outcomes": [item.to_dict() for item in result.outcomes],
            }
        )
        metrics["visual_reads"] = entries[-60:]
    return [unit.to_dict() for unit in result.units]


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

        # Deep-2 §54: check the durable facts before taking the operation, so an already
        # corrupted Deep child never even reaches a running state. The second preflight after
        # acquisition closes the window in between.
        _pre_ok, _pre_reason = deep_preflight(existing.research_context)
        if not _pre_ok:
            raise DeepIntegrityError(f"Deep preflight failed: {_pre_reason}")

        operation_id = new_id("rqce_active")
        run = self.repository.begin_operation(
            run_id,
            operation_id=operation_id,
            stage="planned",
            stale_after_seconds=stale_after_seconds,
        )
        live = ActiveRuntimeLiveValues(state=initial_state, context=dict(run.research_context))
        discovery_diagnostics = ActiveDiscoveryDiagnosticsContext(live)
        live.context["run_attempt"] = int(live.context.get("run_attempt") or 0) + 1
        # Deep-2: durable seed bytes by canonical URL. Empty for every non-Deep run, so the
        # ordinary path is untouched. The seed is data, never semantic authority.
        # Deep-2 §54: the service validated at admission, but this context was reloaded
        # afterwards. Re-establish the durable Deep facts before any model or network work so a
        # tampered envelope or seed cannot be carried into a research run. Non-Deep runs have no
        # envelope and pass through untouched.
        _deep_ok, _deep_reason = deep_preflight(live.context)
        if not _deep_ok:
            raise DeepIntegrityError(f"Deep preflight failed: {_deep_reason}")
        deep_seed_by_url = _deep_seed_urls(live.context)
        cursor_result = load_runtime_cursor(live.context)
        loaded_cursor = cursor_result.cursor
        if cursor_result.available and loaded_cursor is not None:
            live.cursor = loaded_cursor
        else:
            live.cursor = ResearchRuntimeCursor()
        live.cursor = recover_interrupted_model_attempt(live.cursor)
        live.cursor = recover_interrupted_external_attempt(live.cursor)
        query_attempts = list(run.query_attempts)
        selected_sources = [dict(item) for item in run.selected_sources]
        rejected_sources = [dict(item) for item in run.rejected_sources]
        warnings = list(run.warnings)
        results = ActiveResearchResultBuffers(
            query_attempts=query_attempts,
            selected_sources=selected_sources,
            rejected_sources=rejected_sources,
            warnings=warnings,
        )
        source_evidence = ReadSourceEvidenceContext(
            results=results,
            visual_reader=_read_visual_evidence_for_candidate,
        )
        evidence_acceptance = ExtractedEvidenceAcceptanceContext(
            run_id=run_id, live=live, results=results
        )
        extraction_failures = ExtractionFailureContext(live)
        known_evidence_ids = partial(results.known_evidence_ids, run_id)
        publisher = ActiveResearchPublisher(
            repository=self.repository,
            run_id=run_id,
            operation_id=operation_id,
            buffers=results,
        )
        execution_started = self.monotonic()
        # Deep-2: the Deep tier owns its own budget window, so wall time since Deep admission
        # counts even across a crash. A non-Deep run has no envelope and is unchanged.
        deep_envelope = load_execution_envelope(live.context)
        base_elapsed = effective_deep_base_elapsed(
            durable_elapsed_seconds=live.state.budget.elapsed_seconds,
            envelope=deep_envelope,
            now=_deep_wall_now(self.utc_now),
        )
        budget_clock = ResearchBudgetClock(
            monotonic=self.monotonic,
            execution_started=execution_started,
            base_elapsed=base_elapsed,
            current_hard_seconds=live.hard_timeout_seconds,
            model_timeout_cap_seconds=self.model_timeout_cap_seconds,
            reserve_seconds=RESEARCH_WINDOW_RESERVE_SECONDS,
        )
        elapsed = budget_clock.elapsed
        elapsed_ms = budget_clock.elapsed_ms
        research_seconds_left = budget_clock.research_seconds_left
        remaining_timeout = budget_clock.remaining_timeout
        execution_guard = ActiveResearchExecutionGuard(
            repository=self.repository,
            run_id=run_id,
            operation_id=operation_id,
            elapsed=elapsed,
        )
        ensure_active = execution_guard.ensure_active
        research_window_diagnostics = ResearchWindowDiagnostics(
            reserve_seconds=RESEARCH_WINDOW_RESERVE_SECONDS
        )
        model_policy = RuntimeModelPolicyContext(
            policy_check=self.policy_check,
            utc_now=self.utc_now,
        )
        checkpoint_session = ActiveRuntimeCheckpointSession(
            repository=self.repository,
            run_id=run_id,
            operation_id=operation_id,
            live=live,
            results=results,
            elapsed=elapsed,
            elapsed_ms=elapsed_ms,
        )

        def checkpoint(*, stage: str | None = None) -> WebLookupRun:
            diagnostics: dict[str, Any] = {}
            _checkpoint_started = elapsed_ms()
            try:
                return checkpoint_session.checkpoint(
                    stage=stage,
                    diagnostics=diagnostics,
                )
            finally:
                timing_ledger.record_checkpoint(elapsed_ms() - _checkpoint_started)
                _record_checkpoint_timing(
                    live.context,
                    diagnostics,
                    wall_ms=elapsed_ms() - _checkpoint_started,
                    stage=stage,
                    caller=_checkpoint_caller(),
                    phase=timing_ledger.current_phase(),
                )

        # §71B2: the HTTP envelope is per-run; a fresh run starts full.
        reset_http_envelope()
        # §111 A3-1R: each active execution tier gets its own run-scoped
        # envelope, reset exactly once per run. The browser tier is reset even
        # though it is not in the active chain yet, so activation cannot
        # inherit a spent ledger.
        reset_run_envelope(TIER_BROWSER)

        # F2-S1: wave-scoped exclusive timing ledger (observation only).
        timing_ledger = TimingLedger(elapsed_ms)
        timed_gateway = TimedGateway(self.model_gateway, timing_ledger, elapsed_ms)
        steering_context = ActiveResearchSteeringContext(
            repository=self.repository,
            run_id=run_id,
            utc_now=self.utc_now,
            elapsed_ms=elapsed_ms,
            timing_ledger=timing_ledger,
        )

        # §96 A1a: per-run (backend, host) health breaker. Diagnostic switch,
        # off by default, so the A0/F2 baselines stay valid. It never switches
        # backends, never changes a timeout and never touches retry policy.
        breaker = (
            PerRunBreaker(policy=breaker_policy_from_env())
            if read_breaker_enabled()
            else None
        )
        read_attempt_context = ActiveReadAttemptContext(
            breaker=breaker,
            escalation_recorder=_record_escalation_diagnostics,
        )

        # §143-B0: ACTIVE_READER_CHAIN is now a module-level contract
        # (see the definition above), so the chain has a single authority.

        read_dispatch = ActiveReadDispatchContext(
            breaker=breaker,
            available_backends=ACTIVE_READER_CHAIN,
            research_seconds_left=research_seconds_left,
        )

        read_site_context = ActiveReadSiteContext(
            hard_seconds_left=budget_clock.hard_seconds_left
        )

        phase_timing = RuntimePhaseTiming(ledger=timing_ledger, now=self.monotonic)
        read_observation = ActiveReadObservationContext(
            current_context=live.current_context,
            current_cursor=live.current_cursor,
            phase_timing=phase_timing,
            timing_ledger=timing_ledger,
        )

        # §143-B0.1: read semantics come from the shared production primitive,
        # so execute() and the narrow measurement entry cannot drift apart.
        gateway_read = build_production_gateway_read(
            gateway=self.gateway,
            accepts_timeout=self.read_gateway_accepts_timeout,
            get_context=read_observation.current_context,
            research_seconds_left=research_seconds_left,
            hard_seconds_left=budget_clock.hard_seconds_left,
            wave_index=read_observation.wave_index,
            on_phase_start=read_observation.phase_start,
            on_phase_end=read_observation.phase_end,
            on_retry=read_observation.retry,
        )
        read_execution = ActiveReadExecutionContext(
            gateway=self.gateway,
            gateway_read=gateway_read,
            hard_seconds_left=budget_clock.hard_seconds_left,
            dispatch=read_dispatch,
            read_site=read_site_context,
            executor_factory=build_read_chain_executors,
            chain_runner=run_chain,
        )

        model_attempt_context = ActiveModelAttemptContext.for_live_values(
            live,
            ensure_active=ensure_active,
            ensure_budget=execution_guard.ensure_budget,
            checkpoint=checkpoint,
        )
        on_model_started = model_attempt_context.started
        # B5-H1: finish stays in memory until the caller checkpoints the
        # semantic result. A crash first leaves durable inflight for recovery.
        on_model_finished = model_attempt_context.finished

        wave_handoff = ActiveWaveSettlementHandoff.for_live_values(live)
        wave_baseline_context = ActiveWaveBaselineContext(
            live=live, actionable_gaps=_ordered_gaps
        )
        wave_progress_context = ActiveWaveProgressContext(
            live=live,
            gap_provenance=_wave_gap_provenance,
            max_research_waves=MAX_RESEARCH_WAVES,
        )

        def settle_completed_wave(
            snapshot: ActiveWaveSettlementSnapshot,
        ) -> None:
            """Keep the checkpoint caller label and its original side-effect order."""
            wave_handoff.bind(snapshot)
            try:
                checkpoint()
            finally:
                wave_handoff.refresh_after_checkpoint(snapshot)

        wave_settlement_context = ActiveWaveSettlementContext(
            steering=steering_context,
            ensure_active=ensure_active,
            elapsed=elapsed,
            checkpoint=settle_completed_wave,
            results=results,
            run_id=run_id,
            actionable_gaps=_ordered_gaps,
            publisher=publisher,
            max_research_waves=MAX_RESEARCH_WAVES,
        )

        try:
            ensure_active()
            checkpoint()

            # Bootstrap an empty active state through the audited model boundary.
            if not live.state.claims:
                live.cursor = replace(live.cursor, phase="planning")
                checkpoint(stage="planned")
                categories = ("public_research_question", "research_time_context")
                if not model_policy.allowed(live.context, "research_claim_planning", categories):
                    live.cursor = with_appended_runtime_failure(
                        live.cursor, live.context,
                        "policy_blocked",
                        "planning",
                        logical_call_id=f"policy:research_claim_planning:{run_id}",
                        item_id="research_claim_planning",
                        detail="blocked_by_policy",
                    )
                    return self._terminal_unavailable(
                        context=live.context,
                        cursor=live.cursor,
                        state=live.state,
                        publisher=publisher,
                        reason="claim_planning_blocked_by_policy",
                    )
                planning_logical_call_id = f"research_claim_plan:{run.id}:1"
                try:
                    planning_attempt_start = model_attempt_context.next_attempt_number(
                        planning_logical_call_id
                    )
                except _ModelAttemptBudgetExhausted:
                    live.cursor = with_appended_runtime_failure(
                        live.cursor, live.context,
                        "model_attempts_exhausted",
                        "planning",
                        logical_call_id=planning_logical_call_id,
                        item_id="research_claim_planning",
                        detail="model_call_attempts_exhausted",
                    )
                    checkpoint()
                    return self._terminal_unavailable(
                        context=live.context,
                        cursor=live.cursor,
                        state=live.state,
                        publisher=publisher,
                        reason="claim_plan_unavailable",
                    )
                bootstrap = self.claim_planner.plan(
                    run_id=run_id,
                    question=run.query,
                    reference_date=live.state.reference_date or _utc_date(),
                    budget=live.state.budget,
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
                    live.cursor = with_appended_runtime_failure(
                        live.cursor, live.context,
                        planning_code,
                        "planning",
                        logical_call_id=f"research_claim_plan:{run.id}:1",
                        detail=planning_reason,
                    )
                    checkpoint()
                    return self._terminal_unavailable(
                        context=live.context,
                        cursor=live.cursor,
                        state=live.state,
                        publisher=publisher,
                        reason="claim_plan_unavailable",
                    )
                live.state = bootstrap.state
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
            selection_trace_context = ResearchSelectionTraceContext.from_context(
                live.context
            )
            selection_trace = selection_trace_context.trace
            search_outcomes = ActiveSearchOutcomeContext(
                live=live,
                results=results,
                run_id=run_id,
                operation_id=operation_id,
                trace=selection_trace,
            )
            while True:                # Research Window Deadline Hardening: the research window is an
                # absolute boundary. Once it is exhausted the tail belongs to
                # finalization (Gate, answer synthesis, claim binding,
                # serialization), so no new wave starts.
                if budget_clock.research_window_exhausted():
                    research_window_diagnostics.record_end(
                        live.context,
                        hard_seconds=live.state.budget.hard_timeout_seconds,
                        elapsed=elapsed,
                        exhausted=True,
                    )
                    checkpoint()
                    raise _HardBudgetReached
                if live.cursor.wave_index == 0:
                    live.cursor = replace(live.cursor, wave_index=1)
                    live.context = steering_context.refresh(live.context)
                    if _pending_active_steering_ids(live.context):
                        execution_guard.ensure_budget(live.state)
                        live.state, live.context, _applied_ids = steering_context.apply_pending(
                            state=live.state,
                            context=live.context,
                            wave_index=1,
                            known_evidence_ids=known_evidence_ids,
                        )
                    checkpoint()
                wave_id = f"research_wave:{run_id}:{live.cursor.wave_index}"
                timing_ledger.start_wave(live.cursor.wave_index)

                # A crash after gain/saturation persisted but before terminal
                # settlement must not account the same wave twice.
                if len(live.cursor.gain_history) >= live.cursor.wave_index:
                    gate = evaluate_evidence_gate(live.state)
                    brief = _evidence_brief(live.state, gate, selected_sources)
                    live.context[ACTIVE_RESEARCH_BRIEF_KEY] = brief
                    research_window_diagnostics.record_end(
                        live.context,
                        hard_seconds=live.state.budget.hard_timeout_seconds,
                        elapsed=elapsed,
                        exhausted=budget_clock.research_window_exhausted(),
                    )
                    checkpoint()
                    settled = wave_handoff.settle(wave_settlement_context, gate, brief)
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
                if wave_baseline_context.begin_if_needed(wave_id):
                    checkpoint()
                wave_baseline = wave_baseline_context.restore()
                # Semantic query identity is stable across waves. Re-entering a
                # wave or reaching a later wave must not re-search the same text;
                # no new query space is handled as a no-gain batch by Saturation.
                live.cursor = _append_gap_queries(live.cursor, live.state)
                # Deep-2: seed candidates must join the pool after this wave's queries exist,
                # because claim selection is driven by planned-query intersection, and before
                # the first search, so a search duplicate can merge into the same candidate.
                live.cursor = _bind_deep_seed_candidates(
                    live.cursor,
                    live.state,
                    seed_by_url=deep_seed_by_url,
                    max_candidates=live.state.budget.max_candidates,
                    trace=selection_trace,
                )
                live.cursor = replace(live.cursor, phase="searching")
                checkpoint(stage="searching")

                if self._required(run_id).stage != "searching":
                    self.repository.set_stage(
                        run_id,
                        stage="searching",
                        operation_id=operation_id,
                    )

                # Search every still-pending planned query until the shared hard budget.
                for planned in live.cursor.planned_queries:
                    if planned.id in live.cursor.completed_query_ids:
                        continue
                    ensure_active()
                    if elapsed() >= live.state.budget.hard_timeout_seconds:
                        break
                    # B5-H2: once the candidate pool is full, further external
                    # searches can only burn shared budget on results that would
                    # be dropped by the pool cap, so stop before any external call.
                    if len(live.cursor.candidates) >= live.state.budget.max_candidates:
                        break
                    try:
                        attempt = _attempt_number(live.cursor, planned.id)
                    except _ExternalAttemptBudgetExhausted:
                        search_outcomes.record_exhausted(planned)
                        checkpoint()
                        continue
                    marker = RuntimeExternalAttemptStart(
                        call_id=f"research_search:{run_id}:{planned.id}:attempt:{attempt}",
                        purpose="search",
                        item_id=planned.id,
                        attempt=attempt,
                        started_at=self.utc_now(),
                    )
                    live.cursor = begin_external_attempt(live.cursor, marker)
                    checkpoint()

                    # The attempt-start checkpoint above owns recovery. The
                    # search context only binds live inputs for this one call;
                    # it cannot account, checkpoint or publish an attempt.
                    search_execution = ActiveSearchQueryExecution(
                        gateway=self.gateway,
                        monotonic=self.monotonic,
                        hard_seconds_left=budget_clock.hard_seconds_left,
                        reserve_seconds=RESEARCH_WINDOW_RESERVE_SECONDS,
                        phase_timing=phase_timing,
                        context=live.context,
                        claim_id=str(getattr(planned, "claim_id", "") or ""),
                        cursor=live.cursor,
                    )

                    one_query = _gap_query_batch(planned)
                    try:
                        batch_result = execute_candidate_pool_batch(
                            one_query,
                            search_exact=search_execution.search_exact,
                            should_cancel=lambda: self.repository.cancel_requested(
                                run_id, operation_id=operation_id
                            ),
                            results_per_query=5,
                            max_candidates=live.state.budget.max_candidates,
                            trace=selection_trace,
                        )
                    finally:
                        live.cursor = finish_external_attempt(live.cursor, call_id=marker.call_id)
                        checkpoint()
                    ensure_active()
                    search_outcomes.record_batch(
                        planned,
                        batch_result,
                        call_id=marker.call_id,
                        provider_audit=search_execution.audit,
                    )
                    checkpoint()

                live.cursor = replace(live.cursor, phase="assessing")
                checkpoint(stage="assessing")

                # Strict semantic assessment and role-aware ranking, one claim at a time.
                assessment_results = ActiveAssessmentResultContext.for_live(
                    live, selection_trace
                )
                for claim in _ordered_claims(live.state):
                    claim_candidates = _candidates_for_claim(live.cursor, claim.id)
                    if not claim_candidates:
                        continue
                    saved_ranked = assessment_results.restore_claim(claim.id)
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
                        max_reads=live.state.budget.max_reads,
                        excluded_candidate_ids=frozenset(
                            {*live.cursor.completed_read_ids, *saved_candidate_ids}
                        ),
                        trace=selection_trace,
                        context=live.context,
                        live_context=live.current_context,
                        model_gateway=timed_gateway,
                        run_id=run_id,
                        wave_index=live.cursor.wave_index,
                        timeout_seconds=remaining_timeout(),
                        now_ms=elapsed_ms,
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
                    execution_guard.ensure_budget(live.state)
                    categories = ("public_research_claim", "public_candidate_metadata")
                    assessment_logical_call_id = (
                        f"research_candidate_assessment:{run_id}:{claim.id}:1"
                        f"{_assessment_call_suffix(live.cursor, claim.id, candidate_ids)}"
                    )
                    if not model_policy.allowed(
                        live.context, "research_candidate_assessment", categories
                    ):
                        live.cursor = with_appended_runtime_failure(
                            live.cursor, live.context,
                            "policy_blocked",
                            "assessing",
                            logical_call_id=f"policy:{assessment_logical_call_id}",
                            item_id=claim.id,
                            detail="blocked_by_policy",
                        )
                        checkpoint()
                        continue
                    try:
                        assessment_attempt_start = model_attempt_context.next_attempt_number(
                            assessment_logical_call_id
                        )
                    except _ModelAttemptBudgetExhausted:
                        # Both attempts for this exact durable assessment may
                        # already have failed before the process exited. Resume
                        # that claim through the normal unavailable/no-gain path;
                        # attempt exhaustion is not a whole-runtime failure and
                        # must never create a third physical model call.
                        live.cursor = with_appended_runtime_failure(
                            live.cursor, live.context,
                            "model_attempts_exhausted",
                            "assessing",
                            logical_call_id=assessment_logical_call_id,
                            item_id=claim.id,
                            detail="model_call_attempts_exhausted",
                        )
                        checkpoint()
                        continue
                    phase_timing.begin("assessment")
                    try:
                        assessed = self.candidate_assessor.assess(
                            run_id=run_id,
                            claim=claim,
                            candidates=candidates,
                            assignments=assessment_assignments,
                            reference_date=live.state.reference_date,
                            timeout_seconds=remaining_timeout(),
                            on_attempt_started=on_model_started,
                            on_attempt_finished=on_model_finished,
                            call_id_suffix=_assessment_call_suffix(
                                live.cursor, claim.id, candidate_ids
                            ),
                            attempt_start=assessment_attempt_start,
                        )
                    finally:
                        phase_timing.end("assessment", context=live.context)
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
                        live.cursor = with_appended_runtime_failure(
                            live.cursor, live.context,
                            assessment_code,
                            "assessing",
                            logical_call_id=assessment_logical_call_id,
                            item_id=claim.id,
                            detail=assessment_reason,
                        )
                        checkpoint()
                        continue
                    merged_assessments = assessment_results.record_completed(
                        claim=claim,
                        claim_candidates=claim_candidates,
                        previous_ranked=saved_ranked,
                        new_assessments=assessed.assessments,
                    )
                    # §45 Tier-2 (default off): when Tier-1 produced candidates
                    # but none is answer-relevant, one bounded proposal call may
                    # add reader-verified candidates with llm_proposed provenance.
                    proposed_claim_ids = live.context.setdefault(
                        TIER2_PROPOSED_CLAIMS_KEY, []
                    )
                    if isinstance(proposed_claim_ids, list):
                        phase_timing.begin("tier2_proposal")
                        live.cursor = _tier2_proposal_step(
                            cursor=live.cursor,
                            state=live.state,
                            claim=claim,
                            assessments=merged_assessments,
                            model_gateway=timed_gateway,
                            read_fn=gateway_read,
                            context=live.context,
                            run_id=run_id,
                            wave_index=live.cursor.wave_index,
                            timeout_seconds=remaining_timeout(),
                            proposed_claim_ids=proposed_claim_ids,
                            live_context=live.current_context,
                        )
                        phase_timing.end("tier2_proposal", context=live.context)
                    # §63 Tier-1.5 (default off): official-domain site search
                    # as a second, deterministic discovery channel.
                    targeted_claim_ids = live.context.setdefault(
                        DOMAIN_TARGETED_CLAIMS_KEY, []
                    )
                    if isinstance(targeted_claim_ids, list):
                        phase_timing.begin("domain_targeted")
                        live.cursor = _domain_targeted_step(
                            cursor=live.cursor,
                            state=live.state,
                            claim=claim,
                            assessments=merged_assessments,
                            model_gateway=timed_gateway,
                            fetch_text=_inventory_fetch_with_retry,
                            read_fn=gateway_read,
                            context=live.context,
                            run_id=run_id,
                            wave_index=live.cursor.wave_index,
                            timeout_seconds=remaining_timeout(),
                            targeted_claim_ids=targeted_claim_ids,
                            seconds_left=research_seconds_left,
                            live_context=live.current_context,
                            now_ms=elapsed_ms,
                        )
                        phase_timing.end("domain_targeted", context=live.context)
                    # §69/B1-T5 R1': discovery channels can only admit after
                    # this wave's window was frozen; give those late candidates
                    # their own bounded assessment entry so the read plan can
                    # actually see them.
                    phase_timing.begin("late_tail")
                    live.cursor = _late_admission_tail(
                        cursor=live.cursor,
                        state=live.state,
                        claim=claim,
                        context=live.context,
                        run_id=run_id,
                        wave_index=live.cursor.wave_index,
                        max_reads=live.state.budget.max_reads,
                        assessor=self.candidate_assessor,
                        policy_context=model_policy,
                        on_model_started=on_model_started,
                        on_model_finished=on_model_finished,
                        phase_begin=phase_timing.begin,
                        phase_end=lambda phase: phase_timing.end(phase, context=live.context),
                        remaining_timeout=remaining_timeout,
                        research_seconds_left=research_seconds_left,
                        trace=selection_trace,
                        claim_rankings=assessment_results.claim_rankings,
                        stored_assessments=assessment_results.stored_assessments,
                        assessed_inputs=assessment_results.assessed_inputs,
                        now_ms=elapsed_ms,
                        deadline_seconds=(
                            live.state.budget.hard_timeout_seconds
                            - RESEARCH_WINDOW_RESERVE_SECONDS
                        ),
                        live_context=live.current_context,
                    )
                    phase_timing.end("late_tail", context=live.context)
                    checkpoint()

                live.cursor = replace(live.cursor, phase="ranking")
                # F2-S1: the ranking/planning block gets its own span
                phase_timing.begin("ranking")
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
                completed_read = set(live.cursor.completed_read_ids)
                # Covered clusters are run-level CUMULATIVE durable truth. The
                # durable map is read back, merged with every claim bound to a
                # successfully read source, and written back - never rebuilt
                # from scratch and overwritten. One physical read serves
                # multiple claims (H3), but a source record's assessment only
                # names the claim that triggered the read; the record's
                # extraction map holds every claim actually bound to it, so
                # coverage must merge the owner claim AND all extraction-map
                # keys, or a secondary claim forgets the cluster (H8).
                covered_clusters_by_claim = merge_covered_clusters(
                    live.context, selected_sources
                )
                # Deep-2 §29/§7: bytes already durable - fetched by a reader chain or
                # materialized from a seed - must not be planned for a physical read at all.
                # Skipping them later in the read loop would still have consumed a scheduler
                # read slot that an unread candidate needed.
                content_available = content_available_ids(
                    completed_read, selected_sources
                )
                rankings_for_plan = {
                    claim_id: tuple(
                        ranked_candidate
                        for ranked_candidate in ranked
                        if ranked_candidate.candidate.id not in content_available
                    )
                    for claim_id, ranked in assessment_results.claim_rankings.items()
                }
                phase_timing.end("ranking", context=live.context)
                physical_reads, extraction_targets = _fair_read_plan(
                    live.state,
                    rankings_for_plan,
                    covered_cluster_ids_by_claim=covered_clusters_by_claim,
                    trace=selection_trace,
                    diagnostics=live.context.setdefault(
                        ACTIVE_RESEARCH_METRICS_KEY, {}
                    ),
                )
                # Already-read candidates whose extraction crashed mid-wave
                # stay extractable on resume, but physical reuse never bypasses
                # per-claim eligibility. Rebuild each binding from that claim's
                # own full ranking and shared scheduler predicate; the
                # per-claim extraction prior skips work already finished.
                # Reuse never grants another claim eligibility: every restored binding is
                # rebuilt from that claim's own ranking.
                extraction_targets = _restore_completed_read_targets(
                    extraction_targets,
                    completed_read_ids=set(content_available),
                    rankings=assessment_results.claim_rankings,
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
                        for link in live.state.evidence_links
                        if link.relation == "supports"
                    )
                    extraction_targets, routing_records = route_missing_atomic_claims(
                        extraction_targets,
                        claims=live.state.claims,
                        supported_claim_ids=supported_ids,
                        read_candidate_ids=routing_read_ids,
                    )
                    routed_pairs = {
                        (str(record["read_artifact_id"]), claim_id)
                        for record in routing_records
                        for claim_id in record.get("routed_claim_ids") or []
                    }
                    _record_atomic_routing_decisions(
                        live.context,
                        wave_index=live.cursor.wave_index,
                        records=routing_records,
                    )
                live.context[ACTIVE_RESEARCH_READ_PLAN_KEY] = {
                    "physical_reads": physical_reads,
                    "extraction_targets": extraction_targets,
                }
                live.cursor = replace(
                    live.cursor,
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
                read_quota = ReadWaveQuotaContext.restore(
                    budget_reads_used=live.state.budget.reads_used,
                    context=live.context,
                    selected_sources=selected_sources,
                )
                read_budget = ReadWaveBudgetContext(
                    live=live, quota=read_quota, elapsed=elapsed
                )
                read_loop_stop_reason = ""
                dispatched_read_ids: set[str] = set()
                for plan_item in physical_reads:
                    candidate_id = plan_item["candidate_id"]
                    if candidate_id in content_available:
                        try:
                            selection_trace.note_already_read(
                                _candidate_by_id(live.cursor, candidate_id).canonical_url
                            )
                        except ValueError:
                            pass
                        continue
                    ensure_active()
                    if deep_seed_by_url:
                        try:
                            _deep_candidate = _candidate_by_id(live.cursor, candidate_id)
                        except ValueError:
                            _deep_candidate = None
                        _seed_source = (
                            deep_seed_by_url.get(_deep_candidate.canonical_url)
                            if _deep_candidate is not None
                            else None
                        )
                        if _seed_source is not None:
                            # Local materialization is not a physical read: it must not be
                            # blocked by the read slot, only by the hard window and the
                            # character budget.
                            if research_seconds_left() <= 0:
                                read_loop_stop_reason = "research_window_closed"
                                break
                            _materialized = _deep_seed_materialization(
                                candidate=_deep_candidate,
                                plan_item=plan_item,
                                seed_source=_seed_source,
                                source_limit=read_quota.remaining_chars(
                                    max_total_chars=live.state.budget.max_total_chars
                                ),
                                selected_sources=selected_sources,
                            )
                            if _materialized is not None:
                                read_quota.charge_materialization(
                                    str((_materialized.get("read") or {}).get("content") or "")
                                )
                                # 0 reads_used: no physical read happened.
                                live.state = read_budget.project()
                                _record_read_history(live.context, live.cursor.read_outcomes)
                                checkpoint()
                            continue
                    if read_quota.exhausted(
                        max_reads=live.state.budget.max_reads,
                        max_total_chars=live.state.budget.max_total_chars,
                    ):
                        read_loop_stop_reason = "read_budget_exhausted"
                        break
                    if research_seconds_left() < MIN_READ_SECONDS:
                        # The window cannot absorb a useful read; stop starting
                        # reads instead of overrunning the finalization reserve.
                        # §96 A1a: this single gate is also recorded in the A0
                        # vocabulary (a policy skip that is never a judgement
                        # about the URL and never feeds breaker health). The
                        # reader's own timeout is already window-capped, so no
                        # second, stricter requirement is added here.
                        read_loop_stop_reason = "research_window_closed"
                        research_window_diagnostics.record_skip(
                            live.context,
                            "read_skipped_insufficient_research_window"
                        )
                        try:
                            _deadline_candidate = _candidate_by_id(live.cursor, candidate_id)
                        except ValueError:
                            break
                        _record_read_timing(
                            live.context,
                            candidate=_deadline_candidate,
                            wave_index=live.cursor.wave_index,
                            status="skipped",
                            wall_ms=0.0,
                            chars=0,
                            raw_read=_deadline_skip_payload(
                                _deadline_candidate.url,
                                deadline_preflight(
                                    remaining_seconds=research_seconds_left(),
                                    timeout_seconds=MIN_READ_SECONDS,
                                    reserve_seconds=0.0,
                                ),
                            ),
                        )
                        break
                    execution_guard.ensure_budget(live.state)
                    candidate = _candidate_by_id(live.cursor, candidate_id)
                    source_limit = read_quota.source_limit(
                        max_total_chars=live.state.budget.max_total_chars
                    )
                    # §100 A2c: pre-attempt scheduling. A candidate whose only
                    # reader is currently unavailable is not planned at all this
                    # wave - no attempt, and no read outcome, because nothing was
                    # read.
                    scheduling = read_dispatch.schedule(
                        candidate=candidate,
                        read_outcomes=live.cursor.read_outcomes,
                        context=live.context,
                    )
                    if scheduling is not None and not scheduling.executable:
                        continue
                    # §105 A2d-4: one candidate, one outer read-slot, an explicit
                    # chain of backends. ``run_chain`` schedules, executes, records
                    # each real attempt and routes; the runtime only projects the
                    # result. Nothing here escalates behind the chain's back.
                    try:
                        attempt = _attempt_number(live.cursor, candidate_id)
                    except _ExternalAttemptBudgetExhausted:
                        live.cursor = with_appended_runtime_failure(
                            live.cursor, live.context,
                            "read_failed",
                            "reading",
                            logical_call_id=(
                                f"research_read:{run_id}:{candidate_id}:attempts_exhausted"
                            ),
                            item_id=candidate_id,
                            detail="external_attempts_exhausted",
                        )
                        live.cursor = replace(
                            live.cursor,
                            read_outcomes=(
                                *live.cursor.read_outcomes,
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
                        results.upsert_selected_source(record)
                        _record_read_history(live.context, live.cursor.read_outcomes)
                        checkpoint()
                        continue
                    # §143-RS: an explicit hint may select the specialist first.
                    # With no hint (or any gate/health failure) the original
                    # inline default block below runs unchanged.
                    chain_run, chain_steps = read_execution.run_candidate(
                        context=live.context,
                        candidate=candidate,
                        source_limit=source_limit,
                        outer_attempt_number=attempt,
                        read_outcomes=live.cursor.read_outcomes,
                    )
                    # §105 A2d-4: the chain's own decision, recorded even when it
                    # executed nothing (a scheduling/policy skip), so the
                    # explicit path is observable without a new ledger.
                    _record_read_chain_decision(
                        live.context,
                        candidate_id=candidate_id,
                        chain_run=chain_run,
                        chain_steps=chain_steps,
                    )
                    if not chain_steps:
                        # A policy/scheduling skip: no backend ran, so there is no
                        # attempt, no outcome and no source - only the scheduling
                        # provenance the metrics already carry (§104).
                        selection_trace.note_read(
                            candidate.canonical_url, dispatched=False
                        )
                        continue
                    selection_trace.note_read(candidate.canonical_url, dispatched=True)
                    dispatched_read_ids.add(candidate_id)
                    ensure_active()
                    read_attempt_context.record_chain_attempts(
                        live.cursor,
                        live.context,
                        candidate=candidate,
                        chain_steps=chain_steps,
                        run_id=run_id,
                        attempt_number=attempt,
                        utc_now=self.utc_now,
                        on_cursor_change=live.set_cursor,
                        research_seconds_left=research_seconds_left,
                        hard_timeout_seconds=live.state.budget.hard_timeout_seconds,
                        elapsed=elapsed,
                    )
                    ensure_active()
                    # The candidate has content if *any* backend produced a
                    # usable read. Prefer the adequate attempt (the legacy
                    # escalation replaced a short read with the adequate one),
                    # else the last non-empty attempt.
                    projection = project_read_chain(
                        candidate=candidate,
                        plan_item=plan_item,
                        chain_steps=chain_steps,
                        source_limit=source_limit,
                    )
                    ok, content = projection.ok, projection.content
                    if ok:
                        read_quota.charge_read(content)
                    record = projection.record
                    # Multimodal Reader v1 (default-inert): publish the source
                    # first, then enrich that same record only on text success.
                    source_evidence.record_projection(
                        record,
                        ok=ok,
                        context=live.context,
                        state=live.state,
                        canonical_url=candidate.canonical_url,
                    )
                    live.state = read_budget.project()
                    # §98 A2a: the single lifecycle view is diagnostics only;
                    # candidate_resolution remains the pure state authority.
                    _record_read_history(
                        live.context, live.cursor.read_outcomes, include_resolution=True
                    )
                    checkpoint()

                if read_loop_stop_reason:
                    # Observed loop-level stop: every planned candidate after the
                    # break shares the same recorded cause; none of them was
                    # dispatched, and the run never reconsiders them this wave.
                    for plan_item in physical_reads:
                        leftover_id = plan_item["candidate_id"]
                        if leftover_id in dispatched_read_ids:
                            continue
                        if leftover_id in live.cursor.completed_read_ids:
                            continue
                        try:
                            leftover_url = _candidate_by_id(
                                live.cursor, leftover_id
                            ).canonical_url
                        except ValueError:
                            continue
                        selection_trace.note_read(
                            leftover_url,
                            dispatched=False,
                            skip_reason=read_loop_stop_reason,
                        )
                selection_trace_context.flush(live.context)

                # Slice 1: bounded lead discovery. A lead read is a discovery
                # action, never an evidence read: it runs strictly after the
                # evidence reads, at most one per wave and at most
                # MAX_LEAD_READS_PER_RUN per run, and it spends the same shared
                # read/model budget. Its output can never become eligible
                # evidence (separate typed contract).
                discovery_before_lead = wave_progress_context.capture_before_lead()
                lead_budget_available = (
                    len(live.cursor.lead_read_ids) < MAX_LEAD_READS_PER_RUN
                )
                lead_plan = _lead_read_plan(
                    live.state,
                    assessment_results.claim_rankings,
                    completed_read_ids=live.cursor.completed_read_ids,
                    lead_read_ids=live.cursor.lead_read_ids,
                    lead_budget_available=lead_budget_available,
                    seed_backed_ids=frozenset(
                        item.id for item in live.cursor.candidates if item.url in deep_seed_by_url
                    )
                    if deep_seed_by_url
                    else frozenset(),
                )
                if not lead_plan:
                    discovery_diagnostics.bump_lead(
                        "insufficient_budget"
                        if not lead_budget_available
                        else "no_lead_candidate",
                    )
                for lead_item in lead_plan:
                    if len(live.cursor.lead_read_ids) >= MAX_LEAD_READS_PER_RUN:
                        break
                    if read_quota.exhausted(
                        max_reads=live.state.budget.max_reads,
                        max_total_chars=live.state.budget.max_total_chars,
                    ):
                        break
                    if research_seconds_left() < MIN_READ_SECONDS:
                        # Bounded lead reads obey the same shared window as
                        # evidence reads; an exhausted window starts none.
                        research_window_diagnostics.record_skip(
                            live.context,
                            "lead_read_skipped_insufficient_research_window"
                        )
                        break
                    lead_candidate = lead_item["candidate"]
                    lead_candidate_id = lead_candidate.id
                    ensure_active()
                    execution_guard.ensure_budget(live.state)
                    lead_source_limit = read_quota.source_limit(
                        max_total_chars=live.state.budget.max_total_chars
                    )
                    lead_attempt = _attempt_number(
                        live.cursor, f"lead:{lead_candidate_id}"
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
                    live.cursor = begin_external_attempt(live.cursor, lead_marker)
                    discovery_diagnostics.bump_lead("lead_read_started")
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
                        live.cursor = finish_external_attempt(
                            live.cursor, call_id=lead_marker.call_id
                        )
                        checkpoint()
                    ensure_active()
                    lead_content = str(
                        raw_lead_read.get("content")
                        or raw_lead_read.get("readme")
                        or ""
                    )[:lead_source_limit]
                    live.cursor = replace(
                        live.cursor,
                        lead_read_ids=(*live.cursor.lead_read_ids, lead_candidate_id),
                    )
                    if not (
                        raw_lead_read.get("ok") is True and lead_content.strip()
                    ):
                        live.cursor = with_appended_runtime_failure(
                            live.cursor, live.context,
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
                        discovery_diagnostics.bump_lead("lead_read_failed")
                        checkpoint()
                        continue
                    read_quota.charge_read(lead_content)
                    live.state = read_budget.project()
                    checkpoint()
                    lead_categories = (
                        "public_research_candidate_metadata",
                        "bounded_public_page_excerpt",
                    )
                    if not model_policy.allowed(
                        live.context, "research_lead_discovery", lead_categories
                    ):
                        live.cursor = with_appended_runtime_failure(
                            live.cursor, live.context,
                            "policy_blocked",
                            "reading",
                            logical_call_id=(
                                f"policy:research_lead_discovery:{lead_candidate_id}"
                            ),
                            item_id=lead_candidate_id,
                            detail="blocked_by_policy",
                        )
                        discovery_diagnostics.bump_lead("policy_blocked")
                        checkpoint()
                        continue
                    phase_timing.begin("discovery")
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
                        phase_timing.end("discovery", context=live.context)
                    ensure_active()
                    if (
                        discovery.status == "completed"
                        and discovery.discovery is not None
                    ):
                        discovery_diagnostics.bump_lead("lead_discovery_succeeded")
                        live.cursor = replace(
                            live.cursor,
                            lead_discoveries=(
                                *live.cursor.lead_discoveries,
                                discovery.discovery.to_dict(),
                            ),
                        )
                        # Slice 2A: lead-discovered URLs re-enter the pool as
                        # ordinary candidates (canonical-URL identity, run-level
                        # cap, depth 1). They get no eligibility privilege.
                        parent_candidate = next(
                            (
                                item
                                for item in live.cursor.candidates
                                if item.id == lead_candidate_id
                            ),
                            None,
                        )
                        discovered, discovery_stats = (
                            _lead_discovered_candidates(
                                live.cursor.candidates,
                                discovery.discovery,
                                parent=parent_candidate,
                                max_candidates=live.state.budget.max_candidates,
                                discovered_so_far=sum(
                                    1
                                    for item in live.cursor.candidates
                                    if item.discovery_method == "lead_url"
                                ),
                            )
                            if parent_candidate is not None
                            else ((), {})
                        )
                        for stats_key, stats_value in discovery_stats.items():
                            if stats_key != "added" and stats_value:
                                discovery_diagnostics.bump_lead(
                                    stats_key, int(stats_value)
                                )
                        if discovered:
                            live.cursor = replace(
                                live.cursor,
                                candidates=(*live.cursor.candidates, *discovered),
                            )
                            discovery_diagnostics.bump_lead(
                                "discovered_candidate_added",
                                len(discovered),
                            )
                            discovery_diagnostics.record_lead_candidate_ids()
                    else:
                        discovery_diagnostics.bump_lead("lead_discovery_failed")
                        live.cursor = with_appended_runtime_failure(
                            live.cursor, live.context,
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

                live.cursor = replace(live.cursor, phase="extracting")
                checkpoint(stage="reading")

                # A successful read is not evidence until strict extraction validates.
                # B5-H3: extraction targets bind (candidate_id, claim_id) pairs, so
                # one physical read can serve multiple claims.
                claims_by_id = {claim.id: claim for claim in live.state.claims}
                for extraction_target in extraction_targets:
                    candidate_id = extraction_target["candidate_id"]
                    claim_id = extraction_target["claim_id"]
                    source_record = results.admit_extraction_target(candidate_id, claim_id)
                    if source_record is None:
                        continue
                    ensure_active()
                    execution_guard.ensure_budget(live.state)
                    extraction_categories = (
                        "public_research_claim",
                        "public_candidate_metadata",
                        "bounded_public_page_excerpt",
                    )
                    extraction_logical_call_id = (
                        f"research_evidence_extract:{run_id}:{claim_id}:{candidate_id}:1"
                        f"{_extraction_call_suffix(live.cursor, candidate_id, claim_id)}"
                    )
                    if not model_policy.allowed(
                        live.context, "research_evidence_extraction", extraction_categories
                    ):
                        extraction_failures.record(
                            source_record=source_record,
                            claim_id=claim_id,
                            candidate_id=candidate_id,
                            reason="blocked_by_policy",
                            failure_code="policy_blocked",
                            logical_call_id=f"policy:{extraction_logical_call_id}",
                        )
                        checkpoint()
                        continue
                    candidate = _candidate_by_id(live.cursor, candidate_id)
                    claim = claims_by_id[extraction_target["claim_id"]]
                    read = cast(Mapping[str, Any], source_record["read"])
                    try:
                        extraction_attempt_start = model_attempt_context.next_attempt_number(
                            extraction_logical_call_id
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
                        extraction_failures.record(
                            source_record=source_record,
                            claim_id=claim_id,
                            candidate_id=candidate_id,
                            reason="model_call_attempts_exhausted",
                            failure_code="model_attempts_exhausted",
                            logical_call_id=extraction_logical_call_id,
                        )
                        checkpoint()
                        continue
                    phase_timing.begin("extraction")
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
                                live.cursor, candidate_id, claim_id
                            ),
                            attempt_start=extraction_attempt_start,
                        )
                    finally:
                        phase_timing.end("extraction", context=live.context)
                    ensure_active()
                    if extracted.status != "completed" or extracted.extraction is None:
                        extraction_reason = extracted.reason or "extractor_unavailable"
                        extraction_code: ResearchFailureCode = (
                            "model_attempts_exhausted"
                            if extraction_reason == "model_call_attempts_exhausted"
                            else "extraction_failed"
                        )
                        extraction_failures.record(
                            source_record=source_record,
                            claim_id=claim_id,
                            candidate_id=candidate_id,
                            reason=extraction_reason,
                            failure_code=extraction_code,
                            logical_call_id=extraction_logical_call_id,
                        )
                        checkpoint()
                        continue
                    link = extracted.extraction
                    evidence_id = evidence_acceptance.accept(
                        record=source_record,
                        candidate_id=candidate_id,
                        claim_id=claim_id,
                        link=link,
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
                            for item in live.cursor.evidence_lead_followups
                            if int(item.get("wave_index") or 0) == live.cursor.wave_index
                        )
                        remaining_seconds = budget_clock.hard_seconds_left()
                        if (
                            wave_followups >= MAX_EVIDENCE_LEAD_FOLLOWUPS_PER_WAVE
                            or len(live.cursor.evidence_lead_followups)
                            >= MAX_EVIDENCE_LEAD_FOLLOWUPS_PER_RUN
                        ):
                            discovery_diagnostics.bump_lead(
                                "evidence_lead_followup_cap_reached"
                            )
                        elif (
                            remaining_seconds
                            < EVIDENCE_LEAD_FOLLOWUP_MIN_REMAINING_SECONDS
                        ):
                            discovery_diagnostics.bump_lead(
                                "evidence_lead_followup_skipped_insufficient_budget",
                            )
                        elif (
                            claim_support_topology(live.state, claim)[0]
                            >= claim.evidence_requirement.min_independent_sources
                        ):
                            discovery_diagnostics.bump_lead(
                                "evidence_lead_followup_no_support_gap"
                            )
                        else:
                            discovery_diagnostics.bump_lead(
                                "evidence_lead_followup_started"
                            )
                            parent_candidate = next(
                                (
                                    item
                                    for item in live.cursor.candidates
                                    if item.id == candidate_id
                                ),
                                None,
                            )
                            keywords = tuple(
                                token.casefold()
                                for token in query_terms(claim.text)
                            )[:8]
                            if gap is None:
                                discovery_diagnostics.bump_lead(
                                    "deeper_targeting_gap_unavailable"
                                )
                                intent = None
                                variants: tuple[str, ...] = ()
                            else:
                                discovery_diagnostics.bump_lead(
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
                                    live.cursor.candidates,
                                    page_url=candidate.url,
                                    content=str(read.get("content") or ""),
                                    parent=parent_candidate,
                                    keywords=keywords,
                                    max_candidates=live.state.budget.max_candidates,
                                    gap=gap,
                                )
                                if parent_candidate is not None
                                else ((), {"no_deeper_url": 1})
                            )
                            for stats_key, stats_value in followup_stats.items():
                                if stats_key != "added" and stats_value:
                                    discovery_diagnostics.bump_lead(
                                        f"evidence_lead_{stats_key}",
                                        int(stats_value),
                                    )
                            if discovered:
                                live.cursor = replace(
                                    live.cursor,
                                    candidates=(*live.cursor.candidates, *discovered),
                                )
                                discovery_diagnostics.bump_lead(
                                    "evidence_lead_candidate_added",
                                    len(discovered),
                                )
                            live.cursor = replace(
                                live.cursor,
                                evidence_lead_followups=(
                                    *live.cursor.evidence_lead_followups,
                                    {
                                        # The durable cursor record keeps its frozen
                                        # shape (the codec strictly validates these
                                        # keys). §36A diagnostics go to metrics
                                        # below, so no runtime contract changes.
                                        "wave_index": live.cursor.wave_index,
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
                            discovery_diagnostics.record_targeting(
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
                    _record_atomic_routing_extractions(
                        live.context,
                        wave_index=live.cursor.wave_index,
                        routed_pairs=routed_pairs,
                        selected_sources=selected_sources,
                    )

                live.cursor = replace(live.cursor, phase="gating")
                phase_timing.begin("gating")
                checkpoint(stage="gating")
                gate = evaluate_evidence_gate(live.state)
                live.state = _state_after_gate(live.state, gate)
                brief = _evidence_brief(live.state, gate, selected_sources)
                live.context[ACTIVE_RESEARCH_BRIEF_KEY] = brief
                # §45 funnel: proposal -> added -> assessed -> read ->
                # extracted -> gate-eligible, per llm_proposed candidate.
                _record_tier2_funnel(live.context, live.cursor, brief, selected_sources)
                phase_timing.end("gating", context=live.context)
                checkpoint()

                # Gain/saturation projection is resume-safe and bounded. The
                # physical checkpoint still follows at this original boundary.
                wave_progress_context.record_after_gate(
                    baseline=wave_baseline,
                    gate=gate,
                    before_lead=discovery_before_lead,
                )
                checkpoint()
                research_window_diagnostics.record_end(
                    live.context,
                    hard_seconds=live.state.budget.hard_timeout_seconds,
                    elapsed=elapsed,
                    exhausted=budget_clock.research_window_exhausted(),
                )
                checkpoint()
                timing_ledger.end_wave()
                timing_ledger.flush_into(live.context)
                settled = wave_handoff.settle(wave_settlement_context, gate, brief)
                if settled is not None:
                    return settled
        except (ActiveResearchCancelled, CandidatePoolCancelled, ReadSchedulingCancelled):
            # B5-H1: persist the in-memory cursor so a cancel that lands after
            # on_model_finished records the cleared inflight marker and any
            # completed audit; the cancelled run is terminal and never resumes.
            try:
                live.context = steering_context.refresh(live.context)
                live.context, _late_ids = steering_context.mark_late(
                    live.context, reason="user_cancelled"
                )
                checkpoint()
            except Exception:
                pass
            return self.repository.finish_cancel(run_id, operation_id=operation_id)
        except _HardBudgetReached:
            live.state = updated_runtime_budget(
                live.state, live.cursor, elapsed_seconds=elapsed()
            )
            live.context = steering_context.refresh(live.context)
            live.context, _late_ids = steering_context.mark_late(
                live.context, reason="hard_budget_exhausted"
            )
            research_window_diagnostics.record_end(
                live.context,
                hard_seconds=live.state.budget.hard_timeout_seconds,
                elapsed=elapsed,
                exhausted=budget_clock.research_window_exhausted(),
            )
            checkpoint()
            checkpoint()
            gate = evaluate_evidence_gate(live.state)
            brief = _evidence_brief(live.state, gate, selected_sources)
            live.context[ACTIVE_RESEARCH_BRIEF_KEY] = brief
            # §63/§50 acceptance accounting: the run can stop here (budget
            # exhaustion) before the per-wave gating block, so record the
            # discovery funnel on this path too; it only joins metrics.
            _record_tier2_funnel(live.context, live.cursor, brief, selected_sources)
            # F2-S1: close the open wave and publish the timeline
            timing_ledger.end_wave()
            timing_ledger.flush_into(live.context)
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
                    has_evidence=bool(live.state.evidence),
                    unapplied_steering_blocks_completion=(
                        _unapplied_steering_blocks_completion(live.context)
                    ),
                )
            )
            return publisher.complete(
                context=live.context,
                stop=stop,
                brief=brief,
                answer_confidence="partial" if live.state.evidence else "none",
            )
        except Exception as exc:
            latest = self._required(run_id)
            if latest.status != "running" or latest.active_operation_id != operation_id:
                if raise_on_error:
                    raise
                return latest
            live.cursor = with_appended_runtime_failure(
                live.cursor, live.context,
                "runtime_internal_failed",
                live.cursor.phase,
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
                    has_evidence=bool(live.state.evidence),
                    unavailable_reason="active_runtime_unavailable",
                )
            )
            if live.state.evidence:
                result = publisher.complete(
                    context=live.context,
                    stop=stop,
                    state_for_exception=live.state,
                    extra_warning="active research became unavailable",
                    answer_confidence="partial",
                    final_status="partial",
                )
            else:
                result = publisher.fail(context=live.context, stop=stop)
            if raise_on_error:
                raise
            return result

    def _terminal_unavailable(
        self,
        *,
        context: dict[str, Any],
        cursor: ResearchRuntimeCursor,
        state: ResearchState,
        publisher: ActiveResearchPublisher,
        reason: str,
    ) -> WebLookupRun:
        context = attach_runtime_cursor(context, replace(cursor, phase="unavailable"))
        context = attach_claim_engine_state(
            context,
            state,
            known_evidence_ids=publisher.buffers.known_evidence_ids(publisher.run_id),
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
        return publisher.fail(context=context, stop=stop)

    def _required(self, run_id: str) -> WebLookupRun:
        run = self.repository.get(run_id)
        if run is None:
            raise ValueError(f"WebLookupRun not found: {run_id}")
        return run


def _default_policy_check(context: Mapping[str, Any], purpose: str) -> bool:
    del purpose
    policy = context.get("external_data_policy")
    return isinstance(policy, Mapping) and policy.get("web_allowed") is True


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


def _deep_seed_urls(context: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    """Canonical URL -> durable seed source. Empty for a non-Deep run."""

    return seed_sources_by_url(load_seed(context))


def _deep_wall_now(clock: Callable[[], str]) -> datetime:
    """The injected clock as a timezone-aware datetime.

    The runtime's ``utc_now`` is typed ``Callable[[], str]``, so it is parsed here rather than
    assumed to be a datetime. A malformed value falls back to real UTC rather than failing a
    research run over a clock format.
    """

    try:
        value = datetime.fromisoformat(str(clock()))
    except ValueError:
        return datetime.now(timezone.utc)
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _deep_actionable_query_bindings(
    cursor: ResearchRuntimeCursor, state: ResearchState
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Query ids and intents belonging to this wave's actionable claims.

    A seed candidate must be bound to the same planned queries a searched candidate would be,
    otherwise ``_candidates_for_claim`` never selects it for assessment.
    """

    actionable = {gap.claim_id for gap in _ordered_gaps(state)}
    if not actionable:
        return ((), ())
    relevant = [item for item in cursor.planned_queries if item.claim_id in actionable]
    return (
        tuple(dict.fromkeys(item.id for item in relevant)),
        tuple(dict.fromkeys(item.intent for item in relevant)),
    )


def _bind_deep_seed_candidates(
    cursor: ResearchRuntimeCursor,
    state: ResearchState,
    *,
    seed_by_url: Mapping[str, dict[str, Any]],
    max_candidates: int,
    trace: SelectionTraceCollector | None = None,
) -> ResearchRuntimeCursor:
    """Expose durable seed bytes as ordinary candidates for this wave's actionable claims.

    Deliberately not marked as completed reads: the assessment window excludes
    ``cursor.completed_read_ids``, so a pre-marked seed would lose assessment, ranking and
    eligibility entirely. The seed only becomes content later, when the scheduler actually
    selects it for a claim.
    """

    if not seed_by_url:
        return cursor
    query_ids, intents = _deep_actionable_query_bindings(cursor, state)
    if not query_ids:
        return cursor

    merged = list(cursor.candidates)
    by_url = {item.url: index for index, item in enumerate(merged)}
    for order, url in enumerate(sorted(seed_by_url)):
        index = by_url.get(url)
        if index is not None:
            current = merged[index]
            merged[index] = replace(
                current,
                query_ids=tuple(dict.fromkeys((*current.query_ids, *query_ids))),
                intents=tuple(dict.fromkeys((*current.intents, *intents))),
                providers=tuple(dict.fromkeys((*current.providers, SEED_PROVIDER))),
            )
            continue
        if len(merged) >= max_candidates:
            if trace is not None:
                trace.note_cap_excluded(url, stage="deep_seed_bind")
            continue
        by_url[url] = len(merged)
        merged.append(
            RuntimeCandidate(
                id=seed_candidate_identity(url),
                url=url,
                title=url,
                snippet="",
                source=SEED_DISCOVERY_METHOD,
                published_at="",
                query_ids=query_ids,
                intents=intents,
                providers=(SEED_PROVIDER,),
                first_seen_rank=len(merged),
                discovery_method=SEED_DISCOVERY_METHOD,
                discovery_depth=0,
            )
        )
    return replace(cursor, candidates=tuple(merged))


def _deep_seed_materialization(
    *,
    candidate: Any,
    plan_item: Mapping[str, Any],
    seed_source: Mapping[str, Any],
    source_limit: int,
    selected_sources: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """Build the local-materialization source record, or None when nothing can be charged.

    No gateway call, no reader chain, no external attempt marker: this is not a physical read,
    so it neither spends a read slot nor records a retrieval state.
    """

    content = materialized_content(seed_source, source_limit=source_limit)
    if not content:
        return None
    record = _source_record(
        candidate,
        plan_item,
        raw_read={
            "ok": True,
            "status": "read",
            "url": candidate.url,
            "content": content,
        },
        final_backend=SEED_FINAL_BACKEND,
        retrieval_attempts=[],
    )
    record["materialization"] = materialization_provenance(
        seed_source=seed_source,
        materialized_content=content,
        full_body_length=len(str(seed_source.get("content") or "")),
    )
    upsert_source_record(selected_sources, record)
    return record


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
    live_context: Callable[[], dict[str, Any]] | None = None,
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
    _count_orchestration_call(
        live_context() if live_context is not None else context,
        "research_url_proposal",
    )

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
    metrics = (
        live_context() if live_context is not None else context
    ).setdefault(ACTIVE_RESEARCH_METRICS_KEY, {})
    if isinstance(metrics, dict):
        records = metrics.get("tier2_proposal")
        if not isinstance(records, list):
            records = []
        records.append(record)
        metrics["tier2_proposal"] = records[-40:]
    if not new_items:
        return cursor
    return replace(cursor, candidates=(*cursor.candidates, *new_items))


def _late_admission_tail(
    *,
    cursor: ResearchRuntimeCursor,
    state: ResearchState,
    claim: ResearchClaim,
    context: dict[str, Any],
    run_id: str,
    wave_index: int,
    max_reads: int,
    assessor: Any,
    policy_context: RuntimeModelPolicyContext,
    on_model_started: Any,
    on_model_finished: Any,
    phase_begin: Any,
    phase_end: Any,
    remaining_timeout: Any,
    research_seconds_left: Any,
    trace: SelectionTraceCollector | None,
    claim_rankings: dict[str, tuple[Any, ...]],
    stored_assessments: dict[str, list[dict[str, Any]]],
    assessed_inputs: dict[str, list[str]],
    now_ms: Any = None,
    deadline_seconds: float = 0.0,
    live_context: Any = None,
) -> ResearchRuntimeCursor:
    """§69/B1-T5 R1': assess this wave's late-admitted candidates.

    Scope is deliberately narrow: candidates that a discovery channel admitted
    in THIS wave after the initial assessment window was frozen, for THIS claim,
    capped at ``LATE_TAIL_MAX_CANDIDATES`` and selected with the same
    cluster-diverse deterministic rule as the initial window. It never calls the
    selection authority, never evicts an existing ranking entry, and never
    bypasses the assessment contract - a late candidate reaches
    ``claim_rankings`` only with a completed, validated assessment. The tail
    obeys the same time and model-call budgets as everything else; when they are
    gone it records why it was skipped.
    """

    observation = LateTailDiagnosticsContext(
        context=context,
        current_context=live_context,
        now_ms=now_ms,
        deadline_seconds=deadline_seconds,
    )
    metrics = observation.metrics()
    if not isinstance(metrics, Mapping):
        return cursor
    late_ids: list[str] = []
    observation.begin(claim_id=claim.id, wave_index=wave_index)
    for entry in metrics.get("domain_targeted") or []:
        if not isinstance(entry, Mapping):
            continue
        if str(entry.get("claim_id") or "") != claim.id:
            continue
        if int(entry.get("wave_index") or 0) != int(wave_index):
            continue
        for candidate_id in entry.get("added_candidate_ids") or []:
            text_id = str(candidate_id)
            if text_id and text_id not in late_ids:
                late_ids.append(text_id)
    try:
        observation.phase(f"decided:{len(late_ids)}")
        if not late_ids:
            observation.finish(outcome="no_late_ids")
            return cursor

        record: dict[str, Any] = {
            "claim_id": claim.id,
            "wave_index": int(wave_index),
            "late_candidate_ids": list(late_ids),
            "selected_ids": [],
            "assessed_ids": [],
            "selector_calls": 0,
            "assessment_calls": 0,
            "skipped_reason": "",
            "ranked_after": 0,
            "seconds_left": round(float(research_seconds_left()), 3),
            "t_admitted_ms": None,
            "t_tail_selected_ms": None,
            "t_tail_gate_ms": None,
        }
        for domain_record in metrics.get("domain_targeted") or []:
            if (
                isinstance(domain_record, Mapping)
                and str(domain_record.get("claim_id") or "") == claim.id
                and int(domain_record.get("wave_index") or 0) == int(wave_index)
            ):
                admitted_ms = domain_record.get("t_admitted_ms")
                if isinstance(admitted_ms, (int, float)):
                    record["t_admitted_ms"] = float(admitted_ms)
                for key in ("t_started_ms", "t_proposal_ms"):
                    value = domain_record.get(key)
                    if isinstance(value, (int, float)):
                        record[key] = float(value)
                break

        already_ranked = {
            item.candidate.id for item in claim_rankings.get(claim.id, ())
        }
        excluded = frozenset({*cursor.completed_read_ids, *already_ranked})
        claim_candidates = _candidates_for_claim(cursor, claim.id)
        late_items = tuple(
            item
            for item in claim_candidates
            if item.id in set(late_ids) and item.id not in excluded
        )
        if not late_items:
            record["skipped_reason"] = "no_late_candidates"
            observation.store(record)
            return cursor

        clusters = cluster_candidate_sources(claim_candidates)
        assignments = {item.candidate_id: item for item in clusters.assignments}
        selected = _bounded_assessment_candidates(
            late_items,
            assignments=assignments,
            max_reads=min(int(max_reads), LATE_TAIL_MAX_CANDIDATES),
            excluded_candidate_ids=frozenset(),
            trace=None,
        )
        record["selected_ids"] = [item.id for item in selected]
        if now_ms:
            record["t_tail_selected_ms"] = round(float(now_ms()), 1)
        observation.phase(f"selected:{len(selected)}")
        if not selected:
            record["skipped_reason"] = "no_read_slot_for_claim"
            observation.store(record)
            return cursor

        floor_seconds = late_tail_floor_seconds()
        record["floor_seconds"] = floor_seconds
        if float(research_seconds_left()) < floor_seconds:
            record["skipped_reason"] = "time_budget_exhausted"
            observation.store(record)
            return cursor

        categories = ("public_research_claim", "public_candidate_metadata")
        if not policy_context.allowed(
            observation.live(), "research_candidate_assessment", categories
        ):
            record["skipped_reason"] = "policy_blocked"
            observation.store(record)
            return cursor

        candidate_ids = tuple(sorted(item.id for item in selected))
        logical_call_id = (
            f"research_candidate_assessment:{run_id}:{claim.id}:late"
            f"{_assessment_call_suffix(cursor, claim.id, candidate_ids)}"
        )
        try:
            attempt_start = _model_attempt_start(cursor, logical_call_id)
        except _ModelAttemptBudgetExhausted:
            record["skipped_reason"] = "model_call_budget_exceeded"
            observation.store(record)
            return cursor

        assessment_assignments = {item.id: assignments[item.id] for item in selected}
        observation.phase("assessing")
        phase_begin("assessment")
        try:
            assessed = assessor.assess(
                run_id=run_id,
                claim=claim,
                candidates=selected,
                assignments=assessment_assignments,
                reference_date=state.reference_date,
                timeout_seconds=remaining_timeout(),
                on_attempt_started=on_model_started,
                on_attempt_finished=on_model_finished,
                call_id_suffix=_assessment_call_suffix(
                    cursor, claim.id, candidate_ids
                ),
                attempt_start=attempt_start,
            )
        finally:
            phase_end("assessment")
        record["assessment_calls"] = 1
        if assessed.status != "completed" or not assessed.assessments:
            record["skipped_reason"] = (
                "model_call_budget_exceeded"
                if str(getattr(assessed, "reason", "") or "") == "model_call_attempts_exhausted"
                else "assessment_failed"
            )
            observation.store(record)
            return cursor

        _merged, ranked = record_assessment_result(
            claim=claim,
            claim_candidates=claim_candidates,
            previous_ranked=claim_rankings.get(claim.id, ()),
            new_assessments=assessed.assessments,
            claim_rankings=claim_rankings,
            stored_assessments=stored_assessments,
            assessed_inputs=assessed_inputs,
            context=context,
            trace=trace,
        )
        record["assessed_ids"] = sorted(assessed.assessments)
        record["ranked_after"] = len(ranked)
        observation.store(record)
        return cursor
    except BaseException as exc:  # noqa: BLE001 - re-raised below
        observation.finish(outcome=f"aborted:{type(exc).__name__}")
        raise

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
    live_context: Callable[[], dict[str, Any]] | None = None,
    now_ms: Any = None,
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
    # §65/B1-T1 trigger repair: the legacy predicate only fires once a read has
    # completed, so a claim whose Tier-1 candidates never become readable can
    # never reach Tier-1.5 (the uv deadlock). The second entry is deliberately
    # narrow and counter-only: Tier-1 has had a full wave for THIS claim, and
    # this claim still has zero completed reads. It cannot fire in the first
    # wave (no racing Tier-1 scheduling) and never consults run-level reads.
    tier1_wave_consumed = int(wave_index) >= 2 and any(
        query.claim_id == claim.id for query in cursor.planned_queries
    )
    no_viable_read_path = tier1_wave_consumed and claim_completed_reads == 0
    if not miss_reason and not no_viable_read_path:
        return cursor
    miss_reason = miss_reason or "no_viable_read_path"
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
        # §70/B5-S1 diagnostics: event timestamps for the B1 critical path.
        "t_started_ms": round(float(now_ms()), 1) if now_ms else None,
        "t_proposal_ms": None,
        "t_admitted_ms": None,
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
    targets: list[Any] = []
    if result is not None:
        status = str(getattr(result, "status", ""))
        record["call_status"] = status or "unknown"
        if status == "completed":
            targets = list(result.value or [])
    record["targets"] = [target.to_record() for target in targets]
    accepted = [target for target in targets if target.accepted]
    record["rejected_targets"] = [
        target.to_record() for target in targets if not target.accepted
    ]
    record["domains"] = [target.host for target in accepted]
    _count_orchestration_call(
        live_context() if live_context is not None else context,
        "research_domain_proposal",
    )
    if now_ms:
        record["t_proposal_ms"] = round(float(now_ms()), 1)

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
                text, _final_url, _content_type, reason = fetch_text(
                    sitemap_url,
                    context=live_context() if live_context is not None else context,
                    remaining_seconds=seconds_left,
                )
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
                        child_text, _f, _c, child_reason = fetch_text(
                            child,
                            context=live_context() if live_context is not None else context,
                            remaining_seconds=seconds_left,
                        )
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
    if now_ms and record.get("added_candidate_ids"):
        record["t_admitted_ms"] = round(float(now_ms()), 1)
    record["stages"] = {
        "domain_proposed": len(record["domains"]),
        "inventory_fetched": inventory_fetches,
        "links_ranked": len(record["links_found"]),
        "verification_attempted": record["verification_reads"],
        "verification_succeeded": len(record["verified"]),
        "candidate_admitted": len(record["added_candidate_ids"]),
    }
    metrics = (
        live_context() if live_context is not None else context
    ).setdefault(ACTIVE_RESEARCH_METRICS_KEY, {})
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
    live_context: Callable[[], dict[str, Any]] | None = None,
    model_gateway: Any,
    run_id: str,
    wave_index: int,
    timeout_seconds: float | None,
    now_ms: Any = None,
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

    # A model-start checkpoint may replace the enclosing run context while
    # TimedGateway is executing. Record counts/diagnostics on the live context.
    metric_context = live_context() if live_context is not None else context
    _count_orchestration_call(
        metric_context,
        "research_selection_authority",
        calls=1 if limit > 0 and ordered else 0,
    )
    metrics = metric_context.setdefault(ACTIVE_RESEARCH_METRICS_KEY, {})
    if isinstance(metrics, dict):
        record_selection_authority(
            metrics,
            claim_id=claim.id,
            candidates=ordered,
            excluded_candidate_ids=excluded_candidate_ids,
            window_limit=limit,
            wave_index=wave_index,
            orchestration_model_call=1 if (limit > 0 and ordered) else 0,
            diagnostics=diagnostics,
            now_ms=now_ms,
        )
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


def _fair_read_plan(
    state: ResearchState,
    rankings: Mapping[str, tuple[RankedCandidate, ...]],
    *,
    covered_cluster_ids_by_claim: Mapping[str, set[str]] | None = None,
    trace: SelectionTraceCollector | None = None,
    diagnostics: dict[str, Any] | None = None,
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    """Preserve fair-read planning behind a per-plan mutable state owner.

    Physical reads spend the shared budget once per candidate; extraction
    targets retain every eligible (candidate, claim) binding, with conflict
    reserve reclaimed only when no conflict is open.
    """
    return FairReadPlanContext(
        state=state,
        rankings=rankings,
        covered_cluster_ids_by_claim=covered_cluster_ids_by_claim,
        trace=trace,
        diagnostics=diagnostics,
    ).build(_ordered_claims(state))


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
    seed_backed_ids: frozenset[str] = frozenset(),
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
                # Deep-2 §43: a seed-backed candidate is never read as a lead. Deep-2 v1 does
                # not implement seed lead-discovery, so its bytes must not be fetched here.
                or candidate_id in seed_backed_ids
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


def _domain_of(url: str) -> str:
    try:
        return (urlsplit(str(url or "")).netloc or "").casefold()
    except ValueError:
        return ""


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


def _candidate_by_id(cursor: ResearchRuntimeCursor, candidate_id: str) -> CandidatePoolItem:
    for item in cursor.candidates:
        if item.id == candidate_id:
            return _candidate_item(item)
    raise ValueError(f"unknown runtime candidate: {candidate_id}")


def _checkpoint_caller() -> str:
    """F2-O4a: the function that asked for this checkpoint.

    Recorded from the live frame instead of threading a new keyword through
    every one of the ~25 call sites, so the characterisation adds no behavioural
    edit to the run loop. Diagnostics only.
    """

    try:
        frame = sys._getframe(2)  # 0 = this helper, 1 = checkpoint(), 2 = caller
    except Exception:
        return ""
    return str(getattr(frame.f_code, "co_name", "") or "")[:60]


def _native_monotonic_ms() -> float:
    return time.monotonic() * 1000.0


@dataclass
class NativeHttpBackendExecutor:
    """§105 A2d-4 explicit ``native_http`` chain step: a plain read, no escalation.

    It is the first reader in the active chain and it deliberately does **not**
    escalate: the adapter it calls is a plain delegation and the second backend
    is a separate chain step the executor has no knowledge of. It performs one
    attempt, reports it as a :class:`ChainStepResult` and never writes an
    outcome, lifecycle or evidence.
    """

    read_fn: Any = None
    now_ms: Callable[[], float] = _native_monotonic_ms
    name: str = NATIVE_HTTP_BACKEND
    calls: int = field(default=0, init=False)

    def execute(self, request: ChainAttemptRequest) -> ChainStepResult:
        started = self.now_ms()
        try:
            payload = self.read_fn(request.url)
        except Exception as exc:  # noqa: BLE001 - a backend never raises upward
            payload = {"ok": False, "error": type(exc).__name__, "content": ""}
        wall_ms = max(0.0, self.now_ms() - started)
        payload = payload if isinstance(payload, Mapping) else {}
        self.calls += 1
        return _project_native_step(payload, wall_ms)


def _project_native_step(payload: Mapping[str, Any], wall_ms: float) -> ChainStepResult:
    """Canonical projection of one native read payload (no authority)."""

    outcome = _classify_read_outcome(payload)
    adequacy = classify_reader_result(payload)
    raw_content = str(payload.get("content") or "")
    # Parity with the legacy read: "usable" is a non-empty successful read, not
    # the adequacy shape. The shape only decides whether to try another backend.
    usable = bool(payload.get("ok") is True and raw_content.strip())
    retry = payload.get("read_retry")
    retry = retry if isinstance(retry, Mapping) else {}
    fetch_ms = (
        float(retry.get("retry_fetch_ms") or 0.0) if retry else float(wall_ms)
    )
    return ChainStepResult(
        backend=NATIVE_HTTP_BACKEND,
        retrieval_state=outcome.state,
        attempted=True,
        usable_content=usable,
        content=raw_content if usable else "",
        adequacy_reason=adequacy.shape,
        cost={
            "latency_ms": round(float(wall_ms), 1),
            "fetch_ms": round(fetch_ms, 1),
            "backoff_ms": round(float(retry.get("retry_backoff_ms") or 0.0), 1),
            "attempts": int(retry.get("attempts") or 1),
            "retries": int(retry.get("retries") or 0),
            "attempts_detail": [
                dict(item)
                for item in (retry.get("attempts_detail") or [])
                if isinstance(item, Mapping)
            ][:4],
            "chars": len(str(payload.get("content") or "")),
            "error_signature": error_signature(payload),
            "error": str(payload.get("error") or payload.get("error_code") or ""),
            "raw_state": str(outcome.state),
        },
        policy={
            "attempted": True,
            "skip_reason": "",
            "backend": NATIVE_HTTP_BACKEND,
        },
    )


def _classify_read_outcome(raw_read: Mapping[str, Any]) -> Any:
    """§94 A0: canonical state for one production reader payload.

    The §71C-3a adequacy shape carries the content-level truth, while the raw
    error string carries the transport truth; ``classify`` decides precedence, so
    the runtime never re-derives taxonomy here.
    """

    payload = raw_read if isinstance(raw_read, Mapping) else {}
    adequacy = classify_reader_result(payload)
    detail = str(payload.get("error") or payload.get("error_code") or "")
    escalation = payload.get("escalation")
    http_status = None
    if isinstance(escalation, Mapping):
        candidate = escalation.get("http_status")
        if isinstance(candidate, int):
            http_status = candidate
    return classify(
        backend=NATIVE_HTTP_BACKEND,
        raw_state="ok" if payload.get("ok") is True else "read_failed",
        detail=detail,
        http_status=http_status,
        adequacy_shape=adequacy.shape,
    )


def _deadline_skip_payload(url: str, decision: Any) -> dict[str, Any]:
    """Reader-shaped payload for a read refused by the remaining window."""

    return {
        "ok": False,
        "status": "failed",
        "url": url,
        "error": "insufficient_remaining_window",
        "content": "",
        "retrieval_state": "budget_exhausted",
        "retrieval_policy": decision.to_policy_dict(),
    }


def _count_orchestration_call(
    context: dict[str, Any], purpose: str, *, calls: int = 1
) -> None:
    """§65 accounting: count orchestration model calls by purpose.

    The qualification contract caps *all* model calls, so a B1 run can starve
    the rest of the pipeline without discovery itself failing. Recording the
    purpose split (planner / selector / domain proposal / url proposal / lead
    discovery ...) makes that failure mode visible instead of mixing it into a
    single number.
    """

    if calls <= 0:
        return
    metrics = context.setdefault(ACTIVE_RESEARCH_METRICS_KEY, {})
    if not isinstance(metrics, dict):
        return
    metrics["orchestration_model_calls"] = int(
        metrics.get("orchestration_model_calls") or 0
    ) + int(calls)
    by_purpose = metrics.get("orchestration_model_calls_by_purpose")
    if not isinstance(by_purpose, dict):
        by_purpose = {}
    by_purpose[purpose] = int(by_purpose.get(purpose) or 0) + int(calls)
    metrics["orchestration_model_calls_by_purpose"] = by_purpose


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
