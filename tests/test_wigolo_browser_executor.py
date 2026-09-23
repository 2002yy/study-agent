"""§110 P2-A3-1: the ``wigolo_browser`` backend executor.

These tests pin the browser side of the bakeoff: capability declaration, the
static-control guard (no routing authority of its own), honest failure for
walls and interstitials, the shared B2 budget, and the canonical projection.
No daemon and no browser is required.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

import pytest

from src.web.research.browser_bakeoff import FROZEN_CAPABILITIES
from src.web.research.chain_executor import ChainAttemptRequest
from src.web.research.failure_taxonomy import RETRIEVAL_STATES, classify
from src.web.research.progressive_routing import (
    CAP_ANTI_BOT_RECOVERY,
    CAP_JS_RENDER,
    CAP_PDF,
    CAP_SESSION,
    DEFAULT_BACKENDS,
    capability_registry,
)
from src.web.research.read_adequacy import SHORT_CHAR_THRESHOLD
from src.web.research.read_escalation import (
    ESCALATION_BROWSER,
    ESCALATION_OFF,
    charge_http_envelope,
    http_envelope_spent_ms,
    reset_http_envelope,
)
from src.web.research.retrieval_backends import RawReadArtifact
from src.web.research.wigolo_browser_executor import (
    HONESTY_DETAIL,
    HONESTY_DOWNGRADES,
    HONESTY_PREFIX_CHARS,
    WIGOLO_BROWSER_BACKEND,
    WigoloBrowserBackendExecutor,
    rendered_content_judgement,
)

RENDERED = "release date " + ("y" * (SHORT_CHAR_THRESHOLD + 400))


class _FakeBrowserBackend:
    """A deterministic stand-in for a browser-tier Wigolo backend."""

    name = "wigolo"

    def __init__(
        self,
        content: str = RENDERED,
        *,
        latency_ms: float = 850.0,
        preflight: str = "ready",
        content_type: str = "text/markdown",
        rendered: bool = True,
        cache_hit: bool | None = False,
        state: str = "",
        raises: BaseException | None = None,
    ) -> None:
        self.content = content
        self.latency_ms = latency_ms
        self.preflight_status = preflight
        self.content_type = content_type
        self.rendered = rendered
        self.cache_hit = cache_hit
        self.state = state
        self.raises = raises
        self.calls: list[Any] = []

    def preflight(self) -> str:
        return self.preflight_status

    def fetch(self, request: Any) -> RawReadArtifact:
        self.calls.append(request)
        if self.raises is not None:
            raise self.raises
        return RawReadArtifact(
            url=request.url,
            content=self.content,
            content_type=self.content_type,
            retrieval_mode="browser" if self.rendered else "http",
            backend="wigolo",
            latency_ms=self.latency_ms,
            bytes=len(self.content.encode("utf-8")),
            rendered=self.rendered,
            cache_hit=self.cache_hit,
            external_metadata={
                "state": self.state,
                "tier": "browser",
                "title": "Rendered page",
            },
        )


def _request(url: str = "https://example.test/page") -> ChainAttemptRequest:
    return ChainAttemptRequest(
        candidate_id="cand-1",
        url=url,
        host="example.test",
        backend=WIGOLO_BROWSER_BACKEND,
        chain_step=0,
        outer_attempt_number=1,
    )


@pytest.fixture(autouse=True)
def _fresh_envelope() -> Any:
    """The envelope is a run-scoped module global; isolate every test from it."""

    reset_http_envelope()
    yield
    reset_http_envelope()


def _executor(backend: Any = None, **kwargs: Any) -> WigoloBrowserBackendExecutor:
    params: dict[str, Any] = {
        "backend": backend,
        "max_chars": 20_000,
        "mode": lambda: ESCALATION_BROWSER,
    }
    params.update(kwargs)
    return WigoloBrowserBackendExecutor(**params)


# ---------------------------------------------------------------------------
# Capability declaration (no new vocabulary)
# ---------------------------------------------------------------------------


def test_browser_capability_is_declared_in_the_frozen_vocabulary() -> None:
    registry = capability_registry()
    declared = registry[WIGOLO_BROWSER_BACKEND].capabilities
    for capability in (CAP_JS_RENDER, CAP_SESSION, CAP_ANTI_BOT_RECOVERY, CAP_PDF):
        assert capability in declared, capability
    assert declared <= FROZEN_CAPABILITIES
    # A3-1 added no capability word.
    assert {item.name for item in DEFAULT_BACKENDS} == {
        "native_http",
        "wigolo_http",
        "wigolo_browser",
    }


def test_the_browser_needs_a_capability_no_other_backend_has() -> None:
    """Otherwise the browser could never be reached for a reason HTTP cannot serve."""

    registry = capability_registry()
    http_only = registry["wigolo_http"].capabilities
    browser_only = registry[WIGOLO_BROWSER_BACKEND].capabilities
    assert {CAP_SESSION, CAP_ANTI_BOT_RECOVERY, CAP_PDF} <= (browser_only - http_only)


# ---------------------------------------------------------------------------
# Honest failure: a wall is not content
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("state", sorted(HONESTY_DOWNGRADES))
def test_honesty_bridge_round_trips_through_the_frozen_classifier(state: str) -> None:
    """The downgrade must be produced by ``failure_taxonomy``, not hand-built."""

    outcome = classify(detail=HONESTY_DETAIL[state], adequacy_shape="")
    assert outcome.state == state


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Please log in to continue reading", "login_required"),
        ("Login required", "login_required"),
        ("Sign in to continue", "login_required"),
        ("Please complete the CAPTCHA to continue", "anti_bot"),
        ("Checking your browser before accessing", "anti_bot"),
        ("Just a moment...", "anti_bot"),
        ("You need to enable JavaScript to run this app", "shell_page"),
        ("<noscript>Please enable JavaScript</noscript>", "shell_page"),
        ("", ""),
        (RENDERED, ""),
        ("A long technical article about release dates and module systems.", ""),
    ],
)
def test_rendered_content_judgement(text: str, expected: str) -> None:
    assert rendered_content_judgement(text) == expected


def test_honesty_check_only_reads_a_bounded_prefix() -> None:
    """A late mention deep in an article must not masquerade as a challenge."""

    filler = "ordinary prose about software. " * 400
    assert len(filler) > HONESTY_PREFIX_CHARS
    assert rendered_content_judgement(filler + " please log in to continue") == ""
    assert rendered_content_judgement("please log in to continue " + filler) == "login_required"


@pytest.mark.parametrize(
    ("text", "expected_state"),
    [
        ("Please log in to continue", "login_required"),
        ("Please complete the CAPTCHA", "anti_bot"),
        ("You need to enable JavaScript", "shell_page"),
    ],
)
def test_a_rendered_wall_is_never_usable_content(text: str, expected_state: str) -> None:
    backend = _FakeBrowserBackend(text + ("\n" + ("z" * (SHORT_CHAR_THRESHOLD + 400))))
    result = _executor(backend).execute(_request())

    assert result.attempted is True
    assert result.retrieval_state == expected_state
    assert result.usable_content is False
    assert result.content == ""
    assert result.cost["honesty_downgrade"] == expected_state
    assert backend.calls, "the browser really ran; only the verdict is downgraded"


def test_a_normal_rendered_page_is_usable() -> None:
    result = _executor(_FakeBrowserBackend()).execute(_request())

    assert result.retrieval_state == "success"
    assert result.usable_content is True
    assert result.content.startswith("release date")
    assert result.cost["honesty_downgrade"] == ""


# ---------------------------------------------------------------------------
# Policy skips: the browser must not start
# ---------------------------------------------------------------------------


def test_disabled_tier_is_a_policy_skip_and_starts_nothing() -> None:
    backend = _FakeBrowserBackend()
    executor = _executor(backend, mode=lambda: ESCALATION_OFF)
    result = executor.execute(_request())

    assert result.attempted is False
    assert result.usable_content is False
    assert result.policy["skip_reason"] == "disabled"
    assert backend.calls == []
    assert executor.calls == 0


def test_missing_backend_is_a_preflight_skip() -> None:
    result = _executor(None).execute(_request())
    assert result.attempted is False
    assert result.policy["skip_reason"] == "preflight"


def test_unready_provider_is_a_preflight_skip() -> None:
    backend = _FakeBrowserBackend(preflight="unavailable")
    result = _executor(backend).execute(_request())
    assert result.attempted is False
    assert result.policy["skip_reason"] == "preflight"
    assert backend.calls == []


def test_insufficient_hard_headroom_is_a_budget_skip() -> None:
    backend = _FakeBrowserBackend()
    result = _executor(backend, hard_seconds_left=lambda: 1.0).execute(_request())

    assert result.attempted is False
    assert result.retrieval_state == "budget_exhausted"
    assert result.policy["skip_reason"] == "insufficient_remaining_window"
    assert result.cost["deny_layer"] == "hard_headroom"
    assert backend.calls == []


def test_exhausted_envelope_is_a_budget_skip() -> None:
    reset_http_envelope()
    charge_http_envelope(3_000.0)
    backend = _FakeBrowserBackend()
    result = _executor(backend, hard_seconds_left=lambda: 30.0).execute(_request())

    assert result.attempted is False
    assert result.retrieval_state == "budget_exhausted"
    assert result.cost["deny_layer"] == "envelope"
    assert backend.calls == []


# ---------------------------------------------------------------------------
# One real attempt: projection, cost, budget
# ---------------------------------------------------------------------------


def test_successful_attempt_reports_a_full_cost_record() -> None:
    result = _executor(_FakeBrowserBackend(latency_ms=850.0)).execute(_request())

    cost = result.cost
    assert cost["latency_ms"] == 850.0
    # the whole browser call is network/render wait, not local work (§107)
    assert cost["fetch_ms"] == 850.0
    assert cost["rendered"] is True
    assert cost["cache_hit"] is False
    assert cost["provider_backend"] == "wigolo"
    assert cost["tier"] == "browser"
    assert cost["bytes"] > 0
    assert cost["content_type"] == "text/markdown"
    assert cost["honesty_downgrade"] == ""


def test_provider_failure_projects_a_canonical_state() -> None:
    backend = _FakeBrowserBackend(content="", state="timeout")
    result = _executor(backend).execute(_request())

    assert result.attempted is True
    assert result.usable_content is False
    assert result.retrieval_state == "timeout"
    assert result.retrieval_state in RETRIEVAL_STATES


def test_provider_exception_never_escapes() -> None:
    backend = _FakeBrowserBackend(raises=RuntimeError("boom"))
    result = _executor(backend).execute(_request())

    assert result.attempted is True
    assert result.usable_content is False
    assert result.retrieval_state == "connect_failure"
    assert result.cost["error_type"] == "RuntimeError"


def test_envelope_is_charged_once_per_real_attempt_only() -> None:
    reset_http_envelope()
    executor = _executor(
        _FakeBrowserBackend(latency_ms=850.0),
        hard_seconds_left=lambda: 30.0,
        charge_envelope=charge_http_envelope,
    )
    executor.execute(_request())
    assert http_envelope_spent_ms() == pytest.approx(850.0, abs=1.0)

    skipped = _executor(
        _FakeBrowserBackend(preflight="unavailable"),
        charge_envelope=charge_http_envelope,
    )
    skipped.execute(_request())
    assert http_envelope_spent_ms() == pytest.approx(850.0, abs=1.0)


def test_effective_timeout_comes_from_the_shared_b2_plan() -> None:
    result = _executor(
        _FakeBrowserBackend(), hard_seconds_left=lambda: 30.0
    ).execute(_request())
    assert float(result.cost["effective_timeout_seconds"]) >= 1.0


# ---------------------------------------------------------------------------
# No routing authority of its own
# ---------------------------------------------------------------------------


def test_the_executor_does_not_import_a_routing_authority() -> None:
    """A second routing authority behind the chain's back is the failure mode."""

    source = Path("src/web/research/wigolo_browser_executor.py").read_text(
        encoding="utf-8"
    )
    imports = [
        line.strip()
        for line in source.splitlines()
        if line.lstrip().startswith(("from ", "import "))
    ]
    joined = "\n".join(imports)
    for forbidden in ("progressive_routing", "candidate_resolution", "schedulable_now"):
        assert forbidden not in joined, forbidden
    assert "run_chain" not in joined, "the executor is a step, not a chain runner"


def test_the_executor_never_inspects_the_url_to_decide() -> None:
    """It runs when invoked; it does not decide that a URL 'might need' a browser."""

    source = Path("src/web/research/wigolo_browser_executor.py").read_text(
        encoding="utf-8"
    )
    assert "urlparse" not in source
    assert "hostname" not in source
    assert "startswith" not in source


def test_projection_never_carries_authority_fields() -> None:
    result = _executor(_FakeBrowserBackend()).execute(_request())
    serialized: Mapping[str, Any] = result.to_dict()
    for forbidden in (
        "evidence",
        "support",
        "claim_id",
        "gate",
        "confidence",
        "answer",
    ):
        assert forbidden not in serialized
