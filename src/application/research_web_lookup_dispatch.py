"""Per-run search dispatch for the Research Quality Claim Engine.

The durable ``WebLookupRun`` remains the source of rollout truth. This module
only selects the search gateway for one execution: absent, shadow, corrupt, or
otherwise unverifiable Claim Engine state keeps the legacy gateway; a fully
validated ``active`` state gets the research-only multi-provider gateway.

The existing ``WebLookupService`` still owns the execution loop. A narrow
repository proxy enriches its already-authoritative query-attempt checkpoints
with bounded provider audit metadata from ``ActiveResearchGateway``. It never
writes a second run state and never treats audit metadata as evidence.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from src.application.web_lookup_service import WebLookupGateway, WebLookupService
from src.application.active_research_runtime import ActiveResearchRuntimeExecutor
from src.domain.evidence import build_evidence_snapshot
from src.domain.runtime_entities import WebLookupRun
from src.repositories.web_lookup_repository import WebLookupRepository
from src.web.research.active_adapter import ActiveResearchGateway
from src.web.research.state import ClaimEngineLoadResult, load_claim_engine_state
from src.web.research.contracts import ResearchState

_PROVIDER_AUDIT_SCHEMA_VERSION = "research-provider-audit-v1"
ActiveGatewayFactory = Callable[[], ActiveResearchGateway]
ActiveRuntimeFactory = Callable[
    [WebLookupRepository, ActiveResearchGateway], ActiveResearchRuntimeExecutor
]


class _AuditedRepositoryProxy:
    """Delegate repository operations while enriching authoritative attempts."""

    def __init__(
        self,
        repository: WebLookupRepository,
        gateway: Any,
        *,
        initial_attempt_count: int = 0,
    ) -> None:
        self._repository = repository
        self._gateway = gateway
        self._audits_by_attempt_index: dict[int, dict[str, Any]] = {}
        self._attempt_count = max(0, int(initial_attempt_count))

    def __getattr__(self, name: str) -> Any:
        return getattr(self._repository, name)

    def checkpoint(
        self,
        run_id: str,
        *,
        operation_id: str,
        research_context: dict[str, Any],
        query_attempts: list[dict[str, Any]],
        selected_sources: list[dict[str, Any]],
        rejected_sources: list[dict[str, Any]],
        items: list[dict[str, Any]],
        warnings: list[str],
        provider_status: str = "",
        stop_reason: str = "",
        answer_confidence: str = "",
    ) -> WebLookupRun:
        return self._repository.checkpoint(
            run_id,
            operation_id=operation_id,
            research_context=research_context,
            query_attempts=self._audited_attempts(query_attempts),
            selected_sources=selected_sources,
            rejected_sources=rejected_sources,
            items=items,
            warnings=warnings,
            provider_status=provider_status,
            stop_reason=stop_reason,
            answer_confidence=answer_confidence,
        )

    def complete(
        self,
        run_id: str,
        *,
        items: list[dict[str, Any]],
        source_block: str,
        warnings: list[str],
        research_context: dict[str, Any] | None = None,
        query_attempts: list[dict[str, Any]] | None = None,
        selected_sources: list[dict[str, Any]] | None = None,
        rejected_sources: list[dict[str, Any]] | None = None,
        provider_status: str = "",
        stop_reason: str = "",
        answer_confidence: str = "",
        operation_id: str | None = None,
        final_status: str | None = None,
    ) -> WebLookupRun:
        attempts = (
            self._audited_attempts(query_attempts)
            if query_attempts is not None
            else None
        )
        return self._repository.complete(
            run_id,
            items=items,
            source_block=source_block,
            warnings=warnings,
            research_context=research_context,
            query_attempts=attempts,
            selected_sources=selected_sources,
            rejected_sources=rejected_sources,
            provider_status=provider_status,
            stop_reason=stop_reason,
            answer_confidence=answer_confidence,
            operation_id=operation_id,
            final_status=final_status,
        )

    def fail(
        self,
        run_id: str,
        error: str,
        *,
        research_context: dict[str, Any] | None = None,
        query_attempts: list[dict[str, Any]] | None = None,
        provider_status: str = "provider_failed",
        stop_reason: str = "providers_failed",
        operation_id: str | None = None,
    ) -> WebLookupRun:
        attempts = (
            self._audited_attempts(query_attempts)
            if query_attempts is not None
            else None
        )
        return self._repository.fail(
            run_id,
            error,
            research_context=research_context,
            query_attempts=attempts,
            provider_status=provider_status,
            stop_reason=stop_reason,
            operation_id=operation_id,
        )

    def _pending_search_audits(self) -> list[dict[str, Any] | None]:
        drain = getattr(self._gateway, "drain_search_audits", None)
        if callable(drain):
            return list(drain())
        audit = self._gateway.last_search_audit()
        return [dict(audit)] if audit is not None else []

    def _audited_attempts(
        self,
        query_attempts: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        attempts = [dict(item) for item in query_attempts]
        pending = self._pending_search_audits()
        new_attempt_count = max(0, len(attempts) - self._attempt_count)
        if pending:
            bind_count = min(len(pending), new_attempt_count)
            start = len(attempts) - bind_count
            for offset, audit in enumerate(pending[-bind_count:] if bind_count else []):
                if audit is None:
                    continue
                self._audits_by_attempt_index[start + offset] = {
                    "schema_version": _PROVIDER_AUDIT_SCHEMA_VERSION,
                    **dict(audit),
                }
        self._attempt_count = len(attempts)
        for index, saved_audit in self._audits_by_attempt_index.items():
            if index >= len(attempts):
                continue
            attempt = dict(attempts[index])
            attempt["provider_audit"] = dict(saved_audit)
            attempts[index] = attempt
        return attempts


class ClaimEngineDispatchWebLookupService(WebLookupService):
    """Use active search only for one fully validated active Claim Engine run."""

    def __init__(
        self,
        repository: WebLookupRepository,
        gateway: WebLookupGateway | None = None,
        planner: Any = None,
        *,
        active_gateway_factory: ActiveGatewayFactory | None = None,
        active_runtime_factory: ActiveRuntimeFactory | None = None,
    ) -> None:
        super().__init__(repository, gateway=gateway, planner=planner)
        self._active_gateway_factory = active_gateway_factory or ActiveResearchGateway
        self._active_runtime_factory = active_runtime_factory or (
            lambda repository, gateway: ActiveResearchRuntimeExecutor(
                repository,
                gateway,
            )
        )

    def execute(
        self,
        run_id: str,
        *,
        raise_on_error: bool = False,
        stale_after_seconds: int = 120,
    ) -> WebLookupRun:
        run = self.get(run_id)
        active_state = _dispatch_state(run)
        if active_state is None:
            return super().execute(
                run_id,
                raise_on_error=raise_on_error,
                stale_after_seconds=stale_after_seconds,
            )

        active_gateway = self._active_gateway_factory()
        active_runtime = self._active_runtime_factory(
            self.repository,
            active_gateway,
        )
        return active_runtime.execute(
            run_id,
            initial_state=active_state,
            raise_on_error=raise_on_error,
            stale_after_seconds=stale_after_seconds,
        )


def _dispatch_mode(run: WebLookupRun) -> str:
    return "active" if _dispatch_state(run) is not None else "legacy"


def claim_engine_load(run: WebLookupRun) -> ClaimEngineLoadResult:
    """The single Claim Engine load authority, shared with Deep-2 admission.

    The dispatcher treats "absent" and "present but unusable" the same way - both fall back to
    the legacy service - which is a downgrade Deep-2 must never allow. Exposing the load result
    lets Deep separate those cases before dispatching without duplicating the validation.
    """

    known_evidence_ids = _known_research_evidence_ids(run)
    return load_claim_engine_state(
        run.research_context,
        known_evidence_ids=known_evidence_ids,
    )


def _dispatch_state(run: WebLookupRun) -> ResearchState | None:
    loaded = claim_engine_load(run)
    if loaded.available and loaded.effective_mode == "active":
        return loaded.state
    return None


def _known_research_evidence_ids(run: WebLookupRun) -> tuple[str, ...]:
    snapshot = build_evidence_snapshot(
        rag={
            "research_sources": {
                "run_id": run.id,
                "provider_status": run.provider_status,
                "source_truth_version": int(
                    run.research_context.get("source_truth_version") or 0
                ),
                "selected_sources": run.selected_sources,
                "rejected_sources": run.rejected_sources,
            }
        }
    )
    return tuple(ref.id for ref in snapshot.refs)


__all__ = ["ClaimEngineDispatchWebLookupService"]
