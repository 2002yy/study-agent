"""§110 P2-A3-1 explicit ``wigolo_browser`` backend executor.

A3 asks which ``BrowserBackend`` should be the production rendered reader. This
module is the Wigolo side of that comparison: a :class:`BackendExecutor` for the
``wigolo_browser`` capability that the chain can invoke as one step.

What makes it a *browser* backend, not a renamed HTTP one
--------------------------------------------------------

The step is only reached when the frozen routing already decided the plain
chain cannot settle the candidate, and it declares the capabilities that
decision can demand: ``js_render``, ``session``, ``anti_bot_recovery`` and
``pdf`` (declared once, in ``progressive_routing.DEFAULT_BACKENDS``).

The executor has **no routing authority**. It never inspects a URL to decide
whether a browser "might be useful": that would recreate a second routing
authority behind the chain's back. It runs when it is invoked and reports what
happened.

Honest failure
--------------

A rendered login wall or challenge interstitial is not content. The projection
therefore applies the **frozen** A0 marker table to a bounded prefix of the
rendered text and downgrades a matched page to ``login_required`` /
``anti_bot`` / ``shell_page`` with ``usable_content=False``. No new marker or
capability word is introduced: the bridge below is asserted against
``failure_taxonomy.classify`` in the tests.

Budget
------

The browser tier reuses the same shared B2 truth as ``wigolo_http``
(:func:`read_escalation.wigolo_http_execution_plan`), so the A3-0 unified budget
(3.0s hard floor, 3.0s envelope, 1.0s timeout floor) is enforced by one
implementation rather than two that happen to agree.

Scope
-----

It never records an outcome, never touches candidate lifecycle, never routes and
never writes evidence, support or the Gate. It is production-inert: nothing in
the runtime, the adapter or the chain registers it, and
``ACTIVE_READER_CHAIN`` does not contain ``wigolo_browser``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Mapping

from src.web.research.chain_executor import ChainAttemptRequest, ChainStepResult
from src.web.research.failure_taxonomy import (
    SKIP_REASON_DISABLED,
    SKIP_REASON_INSUFFICIENT_WINDOW,
    SKIP_REASON_PREFLIGHT,
    UNKNOWN_STATE,
    classify,
    from_invocation_state,
    from_read_adequacy,
    state_for_text,
)
from src.web.research.read_adequacy import ADEQUATE_SHAPE, classify_reader_result
from src.web.research.read_escalation import (
    ESCALATION_BROWSER,
    escalation_mode,
    wigolo_http_execution_plan,
)
from src.web.research.retrieval_backends import RawReadArtifact, ReadRequest

WIGOLO_BROWSER_BACKEND = "wigolo_browser"

#: How much of the rendered text the honesty check may look at. A wall or
#: interstitial announces itself at the top; scanning the whole document would
#: let an unrelated mention deep in an article masquerade as a challenge.
HONESTY_PREFIX_CHARS = 4000

#: The only canonical states a rendered page may be downgraded to. These are
#: the frozen content-judgement states that a *renderable* page can exhibit.
HONESTY_DOWNGRADES: frozenset[str] = frozenset(
    {"login_required", "anti_bot", "shell_page"}
)

#: Bridge from a detected state back to a frozen marker literal, so the outcome
#: is still produced by ``failure_taxonomy.classify`` rather than hand-built.
#: ``tests/test_wigolo_browser_executor.py`` asserts each entry round-trips.
HONESTY_DETAIL: Mapping[str, str] = {
    "login_required": "login required",
    "anti_bot": "captcha",
    "shell_page": "enable javascript",
}


def rendered_content_judgement(text: str) -> str:
    """Canonical state for a rendered page, or ``""`` when it looks like content.

    Uses the frozen marker table (``failure_taxonomy.state_for_text``); this
    function invents no marker of its own.
    """

    prefix = str(text or "")[:HONESTY_PREFIX_CHARS].lower()
    if not prefix:
        return ""
    state = state_for_text(prefix)
    return state if state in HONESTY_DOWNGRADES else ""


def _skip_result(
    backend: str,
    *,
    state: str,
    skip_reason: str,
    detail: str,
    adequacy_reason: str = "",
    cost: Mapping[str, Any] | None = None,
) -> ChainStepResult:
    """A policy skip: the browser was never started, so nothing may be claimed."""

    outcome = classify(
        backend=backend,
        raw_state=state,
        detail=detail,
        skip_reason=skip_reason,
        attempted=False,
    )
    return ChainStepResult(
        backend=backend,
        retrieval_state=outcome.state,
        attempted=False,
        usable_content=False,
        content="",
        adequacy_reason=adequacy_reason or detail,
        cost=dict(cost or {}),
        policy=outcome.to_policy_dict(),
    )


@dataclass
class WigoloBrowserBackendExecutor:
    """One explicit ``wigolo_browser`` attempt, under the shared B2 guards."""

    backend: Any = None
    max_chars: int = 0
    hard_seconds_left: Callable[[], float] | None = None
    charge_envelope: Callable[[float], None] | None = None
    mode: Callable[[], str] | None = None
    name: str = WIGOLO_BROWSER_BACKEND
    calls: int = field(default=0, init=False)

    def _mode(self) -> str:
        if self.mode is not None:
            return str(self.mode())
        return escalation_mode()

    def execute(self, request: ChainAttemptRequest) -> ChainStepResult:
        backend_name = self.name

        # 1. Capability availability: configuration, not health. The browser
        #    tier is opt-in twice (mode *and* its own flag), and that flag is
        #    enforced by the backend's own preflight below.
        if self._mode() != ESCALATION_BROWSER:
            return _skip_result(
                backend_name,
                state=UNKNOWN_STATE,
                skip_reason=SKIP_REASON_DISABLED,
                detail="browser_tier_disabled",
            )
        if self.backend is None:
            return _skip_result(
                backend_name,
                state=UNKNOWN_STATE,
                skip_reason=SKIP_REASON_PREFLIGHT,
                detail="backend_unavailable",
            )

        # 2. The shared B2 budget truth, evaluated *now* - a scheduler that
        #    found this backend eligible does not authorise the call, because
        #    the plain chain may have spent the budget in between.
        plan = wigolo_http_execution_plan(
            hard_seconds_left=(
                self.hard_seconds_left() if self.hard_seconds_left else None
            )
        )
        if not plan.allowed:
            return _skip_result(
                backend_name,
                state="budget_exhausted",
                skip_reason=SKIP_REASON_INSUFFICIENT_WINDOW,
                detail=plan.deny_reason,
                adequacy_reason=plan.deny_reason,
                cost={
                    "deny_layer": plan.deny_layer,
                    "hard_headroom": plan.hard_headroom,
                    "envelope_remaining_ms": round(plan.envelope_remaining_ms, 1),
                    "effective_timeout_seconds": round(
                        plan.effective_timeout_seconds, 3
                    ),
                },
            )

        # 3. Fail closed on an unavailable or misconfigured provider.
        preflight = getattr(self.backend, "preflight", None)
        preflight_status = ""
        if callable(preflight):
            preflight_status = str(preflight() or "")
            if preflight_status != "ready":
                return _skip_result(
                    backend_name,
                    state=UNKNOWN_STATE,
                    skip_reason=SKIP_REASON_PREFLIGHT,
                    detail=f"preflight:{preflight_status}",
                    cost={"preflight": preflight_status},
                )

        # 4. The one real attempt.
        self.calls += 1
        effective_timeout = round(plan.effective_timeout_seconds, 3)
        try:
            artifact = self.backend.fetch(
                ReadRequest(
                    url=request.url,
                    max_chars=self.max_chars or 0,
                    timeout_seconds=effective_timeout or None,
                )
            )
        except Exception as exc:  # noqa: BLE001 - a backend must never raise upward
            self._charge(0.0)
            outcome = classify(
                backend=backend_name,
                raw_state="transport_error",
                detail=f"{type(exc).__name__}",
            )
            return ChainStepResult(
                backend=backend_name,
                retrieval_state=outcome.state,
                attempted=True,
                usable_content=False,
                content="",
                cost={
                    "effective_timeout_seconds": effective_timeout,
                    "preflight": preflight_status,
                    "error_type": type(exc).__name__,
                    "fetch_ms": 0.0,
                },
                policy={"attempted": True, "skip_reason": "", "backend": backend_name},
            )

        if artifact is None:
            return ChainStepResult(
                backend=backend_name,
                retrieval_state=UNKNOWN_STATE,
                attempted=True,
                usable_content=False,
                content="",
                cost={"effective_timeout_seconds": effective_timeout, "fetch_ms": 0.0},
                policy={"attempted": True, "skip_reason": "", "backend": backend_name},
            )

        # 5. The attempt is charged whether it succeeded or not.
        self._charge(float(artifact.latency_ms or 0.0))
        return self._project(request, artifact, effective_timeout, preflight_status)

    # ------------------------------------------------------------------ helpers

    def _charge(self, latency_ms: float) -> None:
        if self.charge_envelope is not None:
            self.charge_envelope(float(latency_ms))

    def _project(
        self,
        request: ChainAttemptRequest,
        artifact: RawReadArtifact,
        effective_timeout: float,
        preflight_status: str,
    ) -> ChainStepResult:
        """Canonical projection of one rendered artifact (no authority)."""

        metadata = artifact.external_metadata or {}
        payload = {
            "ok": artifact.usable,
            "content": artifact.content,
            "title": str(metadata.get("title") or ""),
            "url": artifact.url or request.url,
            "method": artifact.retrieval_mode,
            "backend": str(self.name),
        }
        adequacy = classify_reader_result(payload)
        raw_state = str(metadata.get("state") or "")

        # Honest failure first: a rendered wall is not content.
        judgement = rendered_content_judgement(artifact.content) if artifact.usable else ""
        if judgement:
            outcome = classify(
                backend=str(self.name),
                raw_state="",
                detail=HONESTY_DETAIL[judgement],
                adequacy_shape="",
            )
        elif artifact.usable:
            outcome = from_read_adequacy(adequacy.shape, backend=str(self.name))
        else:
            outcome = from_invocation_state(
                raw_state or "empty",
                backend=str(self.name),
                detail=raw_state or "empty_content",
            )

        usable = bool(
            artifact.usable
            and adequacy.shape == ADEQUATE_SHAPE
            and not judgement
        )
        return ChainStepResult(
            backend=str(self.name),
            retrieval_state=outcome.state,
            attempted=True,
            usable_content=usable,
            content=artifact.content if usable else "",
            adequacy_reason=judgement or adequacy.shape,
            cost={
                "latency_ms": round(float(artifact.latency_ms or 0.0), 1),
                # The whole call is network/render wait, not local work (§107).
                "fetch_ms": round(float(artifact.latency_ms or 0.0), 1),
                "bytes": int(artifact.bytes or 0),
                "content_type": str(artifact.content_type or ""),
                "cache_hit": artifact.cache_hit,
                "rendered": artifact.rendered,
                "effective_timeout_seconds": effective_timeout,
                "preflight": preflight_status,
                "raw_state": raw_state,
                "tier": str(metadata.get("tier") or ""),
                "http_status": metadata.get("http_status"),
                "provider_backend": str(artifact.backend or ""),
                # Only reported when the provider actually says so.
                "cold_start_ms": metadata.get("cold_start_ms"),
                "render_ms": metadata.get("render_ms"),
                "honesty_downgrade": judgement,
            },
            policy={
                "attempted": True,
                "skip_reason": "",
                "breaker_state": "",
                "backend": str(self.name),
            },
        )


__all__ = [
    "HONESTY_DETAIL",
    "HONESTY_DOWNGRADES",
    "HONESTY_PREFIX_CHARS",
    "WIGOLO_BROWSER_BACKEND",
    "WigoloBrowserBackendExecutor",
    "rendered_content_judgement",
]
