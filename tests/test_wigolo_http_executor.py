"""§103 P2-A2d-3 old/new Wigolo HTTP execution parity.

The explicit ``wigolo_http`` executor must behave exactly like the legacy hidden
escalation. Parity here is not "two implementations happen to agree" - both ask
the same ``wigolo_http_execution_plan`` - but these tests pin that the shared
truth actually reaches both entry points identically.
"""

from __future__ import annotations

import io
from typing import Any

import pytest

from src.web.research.chain_executor import ChainAttemptRequest, run_chain
from src.web.research.read_adequacy import ADEQUATE_SHAPE
from src.web.research.read_escalation import (
    charge_http_envelope,
    escalate_read,
    http_envelope_spent_ms,
    reset_http_envelope,
)
from src.web.research.retrieval_backends import RawReadArtifact
from src.web.research.wigolo_http_executor import WigoloHttpBackendExecutor

INADEQUATE = {
    "ok": True,
    "content": "short",
    "url": "https://x.example/a",
}
GOOD_TEXT = "A" * 1200


class _FakeWigoloHttp:
    """Deterministic stand-in for the Wigolo HTTP backend."""

    def __init__(
        self,
        *,
        content: str = GOOD_TEXT,
        latency_ms: float = 120.0,
        preflight: str = "ready",
        raises: Exception | None = None,
        raw_state: str = "",
        cache_hit: bool | None = False,
        rendered: bool | None = False,
    ) -> None:
        self.name = "wigolo_http"
        self.content = content
        self.latency_ms = latency_ms
        self._preflight = preflight
        self.raises = raises
        self.raw_state = raw_state
        self.cache_hit = cache_hit
        self.rendered = rendered
        self.requests: list[Any] = []

    def preflight(self) -> str:
        return self._preflight

    def fetch(self, request: Any) -> RawReadArtifact:
        self.requests.append(request)
        if self.raises is not None:
            raise self.raises
        return RawReadArtifact(
            url=request.url,
            content=self.content,
            content_type="text/html",
            retrieval_mode="http",
            backend=self.name,
            latency_ms=self.latency_ms,
            bytes=len(self.content.encode("utf-8")),
            rendered=self.rendered,
            cache_hit=self.cache_hit,
            external_metadata={
                "state": self.raw_state,
                "title": "T",
                "max_chars_requested": request.max_chars,
            },
        )


def _legacy(
    backend: _FakeWigoloHttp,
    *,
    hard_seconds_left: float | None,
    max_chars: int = 6000,
) -> tuple[Any, Any]:
    payload, outcome = escalate_read(
        url="https://x.example/a",
        current=INADEQUATE,
        http_backend=backend,
        metrics_provider=None,
        max_chars=max_chars,
        research_seconds_left=(lambda: 40.0),
        hard_seconds_left=(lambda: hard_seconds_left),
    )
    return payload, outcome


def _explicit(
    backend: _FakeWigoloHttp,
    *,
    hard_seconds_left: float | None,
    max_chars: int = 6000,
) -> Any:
    executor = WigoloHttpBackendExecutor(
        backend=backend,
        max_chars=max_chars,
        hard_seconds_left=(lambda: hard_seconds_left),
        charge_envelope=charge_http_envelope,
    )
    return executor.execute(
        ChainAttemptRequest(
            candidate_id="c1",
            url="https://x.example/a",
            host="x.example",
            backend="wigolo_http",
            chain_step=1,
            outer_attempt_number=17,
        )
    )


def _canonical_legacy_state(outcome: Any) -> str:
    """Map a legacy escalation outcome into the canonical vocabulary.

    The parity gate compares *semantics*. The two entry points intentionally
    speak different dialects - legacy uses the §71B invocation words ("ok",
    "unsupported"), the explicit executor uses the A0 canonical words
    ("success", "budget_exhausted") - so the comparison normalises both sides.
    """

    from src.web.research.failure_taxonomy import (
        UNKNOWN_STATE,
        from_invocation_state,
        from_read_adequacy,
    )

    if not outcome.attempted:
        if outcome.reason in (
            "hard_headroom_insufficient",
            "run_envelope_exhausted",
        ):
            return "budget_exhausted"
        return UNKNOWN_STATE
    if outcome.state in ("ok", "empty"):
        return from_read_adequacy(outcome.shape_after).state
    return from_invocation_state(outcome.state).state


def _comparable(legacy: tuple[Any, Any]) -> dict[str, Any]:
    payload, outcome = legacy
    return {
        "attempted": bool(outcome.attempted),
        "deny_reason": "" if outcome.attempted else outcome.reason,
        "canonical_state": _canonical_legacy_state(outcome),
        "effective_timeout": outcome.effective_timeout_seconds or None,
        "usable": bool(
            outcome.attempted and outcome.shape_after == ADEQUATE_SHAPE
        ),
        "content_len": int(outcome.chars_after or 0),
    }


def _comparable_new(result: Any) -> dict[str, Any]:
    return {
        "attempted": bool(result.attempted),
        "deny_reason": "" if result.attempted else result.adequacy_reason,
        "canonical_state": result.retrieval_state,
        "effective_timeout": result.cost.get("effective_timeout_seconds") or None,
        "usable": bool(result.usable_content),
        "content_len": len(result.content),
    }


@pytest.fixture(autouse=True)
def _escalation_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RESEARCH_WIGOLO_ESCALATION", "http")
    monkeypatch.delenv("RESEARCH_WIGOLO_HTTP_MIN_HARD_SECONDS_LEFT", raising=False)
    monkeypatch.delenv("RESEARCH_WIGOLO_HTTP_RUN_ENVELOPE_SECONDS", raising=False)
    reset_http_envelope()


def _both(
    backend_factory, *, hard_seconds_left: float | None, pre_charge_ms: float = 0.0
):
    """Run both entry points with a fresh backend and envelope each.

    ``pre_charge_ms`` simulates envelope already spent earlier in the run, so the
    envelope-exhaustion and timeout-clamp cases can be compared fairly.
    """

    reset_http_envelope()
    if pre_charge_ms:
        charge_http_envelope(pre_charge_ms)
    legacy_backend = backend_factory()
    legacy = _legacy(legacy_backend, hard_seconds_left=hard_seconds_left)
    legacy_debit = http_envelope_spent_ms()

    reset_http_envelope()
    if pre_charge_ms:
        charge_http_envelope(pre_charge_ms)
    new_backend = backend_factory()
    new = _explicit(new_backend, hard_seconds_left=hard_seconds_left)
    new_debit = http_envelope_spent_ms()
    return legacy, legacy_debit, new, new_debit


# --------------------------------------------------------------- parity matrix


def test_parity_success() -> None:
    legacy, legacy_debit, new, new_debit = _both(
        _FakeWigoloHttp, hard_seconds_left=40.0
    )
    assert _comparable(legacy) == _comparable_new(new)
    assert _comparable_new(new)["usable"] is True
    assert legacy_debit == new_debit == 120.0


def test_parity_low_hard_seconds() -> None:
    legacy, legacy_debit, new, new_debit = _both(
        _FakeWigoloHttp, hard_seconds_left=1.0
    )
    old, fresh = _comparable(legacy), _comparable_new(new)
    assert old["attempted"] is False and fresh["attempted"] is False
    assert old["deny_reason"] == fresh["deny_reason"] == "hard_headroom_insufficient"
    # Legacy calls it "unsupported"; the explicit executor maps it to the
    # canonical budget state. Both mean "we did not try".
    assert legacy[1].state == "unsupported"
    assert fresh["canonical_state"] == "budget_exhausted"
    assert legacy_debit == new_debit == 0.0


def test_parity_envelope_exhausted() -> None:
    legacy, legacy_debit, new, new_debit = _both(
        _FakeWigoloHttp, hard_seconds_left=40.0, pre_charge_ms=3000.0
    )
    old, fresh = _comparable(legacy), _comparable_new(new)
    assert old["attempted"] is False and fresh["attempted"] is False
    assert old["deny_reason"] == fresh["deny_reason"] == "run_envelope_exhausted"
    assert legacy_debit == new_debit == 3000.0  # unchanged: nothing was spent


def test_parity_effective_timeout_is_clamped_by_the_envelope() -> None:
    legacy, _, new, _ = _both(
        _FakeWigoloHttp, hard_seconds_left=40.0, pre_charge_ms=1500.0
    )
    old, fresh = _comparable(legacy), _comparable_new(new)
    assert old["effective_timeout"] == fresh["effective_timeout"] == 1.5


def test_parity_effective_timeout_is_clamped_by_hard_headroom(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # 2.0s of hard budget, above the (lowered) MIN_HARD floor and below the
    # 3.0s envelope: the hard budget is the binding constraint.
    monkeypatch.setenv("RESEARCH_WIGOLO_HTTP_MIN_HARD_SECONDS_LEFT", "1.0")
    legacy, _, new, _ = _both(_FakeWigoloHttp, hard_seconds_left=2.0)
    old, fresh = _comparable(legacy), _comparable_new(new)
    assert old["effective_timeout"] == fresh["effective_timeout"] == 2.0


def test_parity_request_args() -> None:
    reset_http_envelope()
    legacy_backend = _FakeWigoloHttp()
    _legacy(legacy_backend, hard_seconds_left=40.0)
    reset_http_envelope()
    new_backend = _FakeWigoloHttp()
    _explicit(new_backend, hard_seconds_left=40.0)

    old_request = legacy_backend.requests[0]
    new_request = new_backend.requests[0]
    assert old_request.url == new_request.url
    assert old_request.max_chars == new_request.max_chars
    assert old_request.timeout_seconds == new_request.timeout_seconds


def test_parity_provider_unavailable_fails_closed() -> None:
    legacy, legacy_debit, new, new_debit = _both(
        lambda: _FakeWigoloHttp(preflight="unavailable"), hard_seconds_left=40.0
    )
    old, fresh = _comparable(legacy), _comparable_new(new)
    assert old["attempted"] is False and fresh["attempted"] is False
    # Legacy says "backend_unavailable"; A0's skip vocabulary is deliberately
    # coarser, so the equivalent is the policy skip reason plus the detail.
    assert old["deny_reason"] == "backend_unavailable"
    assert new.policy["skip_reason"] == "preflight"
    assert "unavailable" in new.adequacy_reason
    assert legacy_debit == new_debit == 0.0


def test_parity_disabled_capability_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("RESEARCH_WIGOLO_ESCALATION", "off")
    legacy, legacy_debit, new, new_debit = _both(
        _FakeWigoloHttp, hard_seconds_left=40.0
    )
    assert legacy[1].attempted is False
    assert legacy[1].reason == "disabled"
    assert new.attempted is False
    assert new.policy["skip_reason"] == "disabled"
    assert legacy_debit == new_debit == 0.0


def test_parity_transport_failure() -> None:
    legacy, _, new, _ = _both(
        lambda: _FakeWigoloHttp(raises=TimeoutError("boom")),
        hard_seconds_left=40.0,
    )
    old, fresh = _comparable(legacy), _comparable_new(new)
    assert old["attempted"] is True and fresh["attempted"] is True
    assert old["usable"] is False and fresh["usable"] is False
    # Legacy reports the raw state; the explicit executor projects canonically.
    assert legacy[1].state == "transport_error"
    assert fresh["canonical_state"] == "timeout"


def test_parity_short_response_is_not_usable() -> None:
    legacy, _, new, _ = _both(
        lambda: _FakeWigoloHttp(content="tiny"), hard_seconds_left=40.0
    )
    old, fresh = _comparable(legacy), _comparable_new(new)
    assert old["usable"] is False and fresh["usable"] is False
    assert fresh["canonical_state"] == "invalid_content"
    assert new.adequacy_reason == "short_doc"


def test_parity_empty_response() -> None:
    legacy, _, new, _ = _both(
        lambda: _FakeWigoloHttp(content="", raw_state="empty"),
        hard_seconds_left=40.0,
    )
    old, fresh = _comparable(legacy), _comparable_new(new)
    assert old["usable"] is False and fresh["usable"] is False


def test_parity_cache_and_rendered_flags_survive() -> None:
    reset_http_envelope()
    backend = _FakeWigoloHttp(cache_hit=True, rendered=False)
    result = _explicit(backend, hard_seconds_left=40.0)
    assert result.cost["cache_hit"] is True
    assert result.cost["rendered"] is False
    assert result.cost["bytes"] == len(GOOD_TEXT.encode("utf-8"))
    assert result.cost["content_type"] == "text/html"


# --------------------------------------------------------------- one budget truth


def test_both_entry_points_ask_the_same_plan() -> None:
    from src.web.research.read_escalation import wigolo_http_execution_plan

    plan = wigolo_http_execution_plan(
        hard_seconds_left=1.0, envelope_remaining_ms=3000.0
    )
    assert plan.allowed is False
    assert plan.deny_reason == "hard_headroom_insufficient"
    assert plan.deny_layer == "hard_headroom"
    # The explicit executor's skip carries the same reason.
    result = _explicit(_FakeWigoloHttp(), hard_seconds_left=1.0)
    assert result.adequacy_reason == plan.deny_reason
    assert result.policy["skip_reason"] == "insufficient_remaining_window"
    assert result.policy["attempted"] is False


def test_the_executor_never_touches_outcomes_or_lifecycle() -> None:
    """It returns a result; the chain executor owns history and routing."""

    result = _explicit(_FakeWigoloHttp(), hard_seconds_left=40.0)
    payload = result.to_dict()
    assert "candidate_id" not in payload
    assert "chain_step" not in payload
    from src.web.research.retrieval_backends import FORBIDDEN_AUTHORITY_FIELDS

    assert not set(payload).intersection(FORBIDDEN_AUTHORITY_FIELDS)


def test_the_executor_plugs_into_run_chain() -> None:
    """The A2d-2 skeleton can drive it as a real second chain step."""

    from src.web.research.chain_executor import ChainStepResult

    class _Native:
        name = "native_http"

        def execute(self, request: ChainAttemptRequest) -> ChainStepResult:
            # §111 A3-1R: a transport-shaped state the plain http tier can serve
            # (shell_page needs js_render, which it no longer claims).
            return ChainStepResult(
                backend="native_http", retrieval_state="reset"
            )

    reset_http_envelope()
    executor = WigoloHttpBackendExecutor(
        backend=_FakeWigoloHttp(),
        max_chars=6000,
        hard_seconds_left=(lambda: 40.0),
        charge_envelope=charge_http_envelope,
    )
    recorded: list[ChainStepResult] = []
    run = run_chain(
        candidate_id="c1",
        url="https://x.example/a",
        host="x.example",
        outer_attempt_number=3,
        chain=("native_http", "wigolo_http"),
        executors={"native_http": _Native(), "wigolo_http": executor},
        record_outcome=recorded.append,
    )
    assert [step.backend for step in run.steps] == ["native_http", "wigolo_http"]
    assert [step.chain_step for step in run.steps] == [0, 1]
    assert run.action == "resolve"
    assert run.usable_content is True
    assert [item.backend for item in recorded] == ["native_http", "wigolo_http"]
    assert {step.outer_attempt_number for step in run.steps} == {3}


# --------------------------------------------------------------- production cutover


def test_production_runs_the_explicit_wigolo_executor() -> None:
    """§105 A2d-4: the runtime wires the explicit executor into its chain."""

    text = io.open(
        "src/application/active_research_runtime.py", encoding="utf-8", errors="ignore"
    ).read()
    assert "WigoloHttpBackendExecutor(" in text
    assert "run_chain(" in text


def test_the_legacy_escalation_is_no_longer_the_production_wigolo_entry() -> None:
    """The hidden path is retired: production no longer calls ``escalate_read``."""

    text = io.open(
        "src/web/research/active_adapter.py", encoding="utf-8", errors="ignore"
    ).read()
    assert "escalate_read" not in text


def test_the_active_chain_enables_wigolo_http_but_not_the_browser() -> None:
    """A2d-4 enables ``native_http -> wigolo_http``; the browser stays for A3."""

    text = io.open(
        "src/application/active_research_runtime.py", encoding="utf-8", errors="ignore"
    ).read()
    assert "ACTIVE_READER_CHAIN = (NATIVE_HTTP_BACKEND, WIGOLO_HTTP_BACKEND)" in text
    # the declared chain names exactly two backends; the browser is not one
    chain = text.split("ACTIVE_READER_CHAIN = (", 1)[1].split(")", 1)[0]
    assert "wigolo_browser" not in chain
