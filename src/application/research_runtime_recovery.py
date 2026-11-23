"""Hydrate one active execution from the run returned by operation acquisition."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from src.application.research_runtime_live_values import ActiveRuntimeLiveValues
from src.application.research_runtime_result_buffers import ActiveResearchResultBuffers
from src.domain.runtime_entities import WebLookupRun
from src.web.research.contracts import ResearchState
from src.web.research.deep_runtime import (
    DeepIntegrityError,
    deep_preflight,
    load_seed,
    seed_sources_by_url,
)
from src.web.research.runtime import (
    load_runtime_cursor,
    recover_interrupted_external_attempt,
    recover_interrupted_model_attempt,
)


def require_intact_deep_inputs(context: Mapping[str, Any]) -> None:
    ok, reason = deep_preflight(context)
    if not ok:
        raise DeepIntegrityError(f"Deep preflight failed: {reason}")


@dataclass(frozen=True, slots=True)
class ActiveResearchRecovery:
    live: ActiveRuntimeLiveValues
    results: ActiveResearchResultBuffers
    deep_seed_by_url: dict[str, dict[str, Any]]

    @classmethod
    def from_run(
        cls, run: WebLookupRun, initial_state: ResearchState
    ) -> ActiveResearchRecovery:
        live = ActiveRuntimeLiveValues(
            state=initial_state, context=dict(run.research_context)
        )
        live.context["run_attempt"] = int(live.context.get("run_attempt") or 0) + 1
        # Recheck the acquired snapshot before decoding seeds or attempts.
        require_intact_deep_inputs(live.context)
        deep_seed_by_url = seed_sources_by_url(load_seed(live.context))
        loaded = load_runtime_cursor(live.context)
        if loaded.available and loaded.cursor is not None:
            live.cursor = loaded.cursor
        live.cursor = recover_interrupted_model_attempt(live.cursor)
        live.cursor = recover_interrupted_external_attempt(live.cursor)
        return cls(live, ActiveResearchResultBuffers.from_run(run), deep_seed_by_url)
