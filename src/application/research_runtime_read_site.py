"""Explicit read-site specialist selection and provenance for one active run.

The default reader chain remains the sole fallback authority.  This module
does not schedule reads, append attempts, or persist a checkpoint.  The caller
passes its current context each time, since recovery/steering may rebind it.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from src.web.research.candidate_pool import CandidatePoolItem
from src.web.research.chain_executor import ChainStepResult
from src.application.research_runtime_read_site_observability import (
    record_read_site_specialist,
)


READ_SITE_HINT_ROUTE_DEFAULT = "default"
READ_SITE_HINT_ROUTE_SPECIALIST = "specialist"


def read_site_hint_route(context: Mapping[str, Any]) -> dict[str, Any]:
    """Pure decision over an explicit reader-capability hint at the read site."""

    capabilities = context.get("reader_capabilities")
    if not capabilities:
        return {
            "route": READ_SITE_HINT_ROUTE_DEFAULT,
            "hint_honored": True,
            "reason": "",
            "requested_reader_capabilities": [],
        }
    try:
        from src.application.reader_hint_routing import (
            explicit_reader_hints_enabled,
            resolve_reader_route,
        )
        from src.web.research.crawl4ai_specialist import crawl4ai_specialist_status
    except Exception:  # pragma: no cover - defensive fail-closed
        return {
            "route": READ_SITE_HINT_ROUTE_DEFAULT,
            "hint_honored": False,
            "reason": "specialist_unavailable",
            "requested_reader_capabilities": list(capabilities),
        }
    try:
        return resolve_reader_route(
            capabilities,
            hints_enabled=explicit_reader_hints_enabled(),
            specialist_config_ok=bool(crawl4ai_specialist_status().get("config_ok")),
            session_inputs_present=bool(
                context.get("reader_session_id") or context.get("reader_setup_url")
            ),
        )
    except Exception:
        return {
            "route": READ_SITE_HINT_ROUTE_DEFAULT,
            "hint_honored": False,
            "reason": "invalid_hint",
            "requested_reader_capabilities": list(capabilities),
        }


def specialist_chain_run(
    *, candidate_id: str, step: ChainStepResult, outer_attempt_number: int
) -> Any:
    """Normalise one specialist step into the standard ``ChainRun`` contract.

    Downstream scheduling/evidence/synthesis must never learn a specialist-only
    data type; only the content's origin changes.
    """

    from src.web.research.chain_executor import ChainRun, ChainStep

    chain_step = ChainStep(
        chain_step=0,
        outer_attempt_number=outer_attempt_number,
        backend=str(step.backend),
        retrieval_state=str(step.retrieval_state),
        attempted=bool(step.attempted),
        usable_content=bool(step.usable_content),
    )
    return ChainRun(
        candidate_id=candidate_id,
        steps=(chain_step,),
        action="resolve",
        reason="specialist_usable_content",
        final_state=str(step.retrieval_state),
        terminal=True,
        usable_content=True,
        attempted_backends=(str(step.backend),),
        content=str(step.content or ""),
    )


@dataclass(frozen=True, slots=True)
class ActiveReadSiteContext:
    """Bind only the run's time source, never a rebound research context."""

    hard_seconds_left: Callable[[], float]

    def try_specialist(
        self,
        context: dict[str, Any],
        candidate: CandidatePoolItem,
        source_limit: int,
    ) -> ChainStepResult | None:
        """Try an explicit specialist; non-usable results fall back to default."""

        route = read_site_hint_route(context)
        if route.get("route") != READ_SITE_HINT_ROUTE_SPECIALIST:
            if route.get("requested_reader_capabilities"):
                record_read_site_specialist(
                    context,
                    route=route,
                    specialist=None,
                    hint_source=str(context.get("reader_capabilities_source") or ""),
                )
            return None
        from src.web.research.crawl4ai_specialist import (
            invoke_crawl4ai_specialist,
        )

        specialist = invoke_crawl4ai_specialist(
            url=candidate.url,
            mode="browser",
            max_chars=source_limit,
            session_id=context.get("reader_session_id") or None,
            setup_url=context.get("reader_setup_url") or None,
            hard_seconds_left=self.hard_seconds_left,
            candidate_id=str(candidate.id),
        )
        record_read_site_specialist(
            context,
            route=route,
            specialist=specialist,
            hint_source=str(context.get("reader_capabilities_source") or ""),
        )
        step = specialist.get("result")
        if step is not None and bool(getattr(step, "usable_content", False)):
            return step
        return None
