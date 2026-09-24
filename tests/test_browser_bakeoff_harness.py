"""§110 P2-A3-1: the bakeoff harness and its result artifact.

These tests drive the real frozen ``chain_executor.run_chain`` with stub
executors, so the routing decisions under test are the production ones. No
daemon, no browser, no network.

The two things that matter here:

* ``static_control`` never starts a browser, even though one is available;
* a rendered wall is reported as an honest canonical failure, never as content.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Mapping

import pytest
import re

from src.web.research.browser_bakeoff import (
    BAKEOFF_CLASSES,
    BROWSER_CHAIN_MAX_LENGTH,
    BrowserBakeoffContractError,
    CLASS_ANTI_BOT,
    CLASS_CAPABILITY_DEMAND,
    CLASS_DOCUMENT_HEAVY,
    CLASS_JS_SHELL,
    CLASS_SESSION_REQUIRED,
    CLASS_SPA_DELAYED_RENDER,
    CLASS_STATIC_CONTROL,
    bakeoff_result_document,
    build_bakeoff_result,
    validate_bakeoff_result,
)
from src.web.research.chain_executor import ChainStepResult
from src.web.research.read_adequacy import ADEQUATE_SHAPE, SHORT_CHAR_THRESHOLD
from src.web.research.wigolo_browser_executor import WIGOLO_BROWSER_BACKEND

from tools.run_browser_bakeoff import BAKEOFF_CHAIN, measure_fixture

ADEQUATE = "release date " + ("y" * (SHORT_CHAR_THRESHOLD + 400))
NATIVE_HTTP = "native_http"
WIGOLO_HTTP = "wigolo_http"

PRODUCTION_MODULES = (
    "src/application/active_research_runtime.py",
    "src/web/research/active_adapter.py",
    "src/web/research/chain_executor.py",
    "src/web/research/progressive_routing.py",
    "src/web/research/candidate_resolution.py",
    "src/web/research/wigolo_http_executor.py",
    "src/web/research/wigolo_backend.py",
)


class _StubExecutor:
    """A backend whose single attempt is scripted by the test."""

    def __init__(self, name: str, result: Callable[[Any], ChainStepResult]) -> None:
        self.name = name
        self._result = result
        self.calls: list[Any] = []

    def execute(self, request: Any) -> ChainStepResult:
        self.calls.append(request)
        return self._result(request)


def _step(
    backend: str,
    state: str,
    *,
    usable: bool = False,
    content: str = "",
    adequacy: str = "",
    latency_ms: float = 100.0,
    extra: Mapping[str, Any] | None = None,
) -> ChainStepResult:
    cost: dict[str, Any] = {
        "latency_ms": latency_ms,
        "fetch_ms": latency_ms,
        "bytes": len(content.encode("utf-8")),
        "content_type": "text/markdown",
        "rendered": backend == WIGOLO_BROWSER_BACKEND,
        "cache_hit": False,
        "honesty_downgrade": "",
    }
    cost.update(extra or {})
    return ChainStepResult(
        backend=backend,
        retrieval_state=state,
        attempted=True,
        usable_content=usable,
        content=content if usable else "",
        adequacy_reason=adequacy,
        cost=cost,
        policy={"attempted": True, "skip_reason": "", "backend": backend},
    )


def _executors(
    *,
    native: ChainStepResult,
    http: ChainStepResult,
    browser: ChainStepResult,
) -> dict[str, _StubExecutor]:
    return {
        NATIVE_HTTP: _StubExecutor(NATIVE_HTTP, lambda request: native),
        WIGOLO_HTTP: _StubExecutor(WIGOLO_HTTP, lambda request: http),
        WIGOLO_BROWSER_BACKEND: _StubExecutor(
            WIGOLO_BROWSER_BACKEND, lambda request: browser
        ),
    }


def _measure(
    category: str,
    *,
    native: ChainStepResult,
    http: ChainStepResult | None = None,
    browser: ChainStepResult | None = None,
) -> tuple[dict[str, Any], dict[str, _StubExecutor]]:
    executors = _executors(
        native=native,
        # The plain HTTP tier could not settle the candidate in every rescue
        # class, which is why the browser is reached at all.
        http=http or _step(WIGOLO_HTTP, "connect_failure"),
        browser=browser
        or _step(
            WIGOLO_BROWSER_BACKEND,
            "success",
            usable=True,
            content=ADEQUATE,
            adequacy=ADEQUATE_SHAPE,
        ),
    )
    row = measure_fixture(
        backend=WIGOLO_BROWSER_BACKEND,
        fixture_id=f"{category}:stub",
        category=category,
        url="https://example.test/page",
        executors=executors,
        cold=True,
    )
    return row, executors


def _native_for_category(category: str) -> ChainStepResult:
    """A native read that makes this class's capability demand the deciding one."""

    if category == CLASS_STATIC_CONTROL:
        return _step(
            NATIVE_HTTP, "success", usable=True, content=ADEQUATE, adequacy=ADEQUATE_SHAPE
        )
    return _step(NATIVE_HTTP, "anti_bot")


# ---------------------------------------------------------------------------
# The static-control guard
# ---------------------------------------------------------------------------


def test_static_control_never_starts_the_browser() -> None:
    """A browser is available; the plain chain settles the page; it stays idle."""

    row, executors = _measure(
        CLASS_STATIC_CONTROL,
        native=_step(NATIVE_HTTP, "success", usable=True, content=ADEQUATE, adequacy=ADEQUATE_SHAPE),
    )

    assert row["browser_called"] is False
    assert executors[WIGOLO_BROWSER_BACKEND].calls == []
    assert executors[WIGOLO_HTTP].calls == []
    assert row["usable_content"] is True
    assert row["outcome_state"] == "success"
    assert row["chain_action"] == "resolve"
    assert row["category"] == CLASS_STATIC_CONTROL


def test_static_control_does_not_start_the_browser_even_on_a_bad_native_read() -> None:
    """Not_found is terminal: the browser must not be used as a rescue."""

    row, executors = _measure(
        CLASS_STATIC_CONTROL,
        native=_step(NATIVE_HTTP, "not_found"),
    )

    assert row["browser_called"] is False
    assert executors[WIGOLO_BROWSER_BACKEND].calls == []
    assert row["usable_content"] is False
    assert row["outcome_state"] == "not_found"


# ---------------------------------------------------------------------------
# Capability-driven invocation
# ---------------------------------------------------------------------------


def test_a_transport_failure_uses_the_http_tier_before_the_browser() -> None:
    """A state the plain http tier *can* serve still goes through it first."""

    row, executors = _measure(
        CLASS_JS_SHELL,
        native=_step(NATIVE_HTTP, "reset"),
        http=_step(WIGOLO_HTTP, "connect_failure"),
        browser=_step(WIGOLO_BROWSER_BACKEND, "success", usable=True, content=ADEQUATE, adequacy=ADEQUATE_SHAPE),
    )

    assert row["browser_called"] is True
    assert [step["backend"] for step in row["attempts"]] == [
        NATIVE_HTTP,
        WIGOLO_HTTP,
        WIGOLO_BROWSER_BACKEND,
    ]
    assert len(row["attempts"]) <= BROWSER_CHAIN_MAX_LENGTH
    assert row["usable_content"] is True
    assert row["outcome_state"] == "success"
    assert row["browser_state"] == "success"
    assert row["browser_usable"] is True


def test_a_shell_page_skips_the_non_rendering_http_tier() -> None:
    """§111 A3-1R capability truth: js_render is the browser tier's alone."""

    row, executors = _measure(
        CLASS_JS_SHELL,
        native=_step(NATIVE_HTTP, "shell_page", usable=True, content="enable javascript", adequacy="js_shell"),
        browser=_step(WIGOLO_BROWSER_BACKEND, "success", usable=True, content=ADEQUATE, adequacy=ADEQUATE_SHAPE),
    )

    assert executors[WIGOLO_HTTP].calls == [], (
        "a js_render demand must not be sent to a reader that never renders"
    )
    assert [step["backend"] for step in row["attempts"]] == [
        NATIVE_HTTP,
        WIGOLO_BROWSER_BACKEND,
    ]


def test_anti_bot_skips_the_http_tier_it_cannot_serve() -> None:
    """``wigolo_http`` has no ``anti_bot_recovery``; routing must not call it."""

    row, executors = _measure(
        CLASS_ANTI_BOT,
        native=_step(NATIVE_HTTP, "anti_bot"),
        browser=_step(WIGOLO_BROWSER_BACKEND, "success", usable=True, content=ADEQUATE, adequacy=ADEQUATE_SHAPE),
    )

    assert executors[WIGOLO_HTTP].calls == [], "the HTTP tier cannot serve anti_bot"
    assert [step["backend"] for step in row["attempts"]] == [
        NATIVE_HTTP,
        WIGOLO_BROWSER_BACKEND,
    ]
    assert row["browser_called"] is True


@pytest.mark.parametrize(
    ("category", "native_state"),
    [
        (CLASS_SPA_DELAYED_RENDER, "invalid_content"),
        (CLASS_DOCUMENT_HEAVY, "invalid_content"),
    ],
)
def test_other_rescue_classes_reach_the_browser(category: str, native_state: str) -> None:
    row, executors = _measure(
        category,
        native=_step(NATIVE_HTTP, native_state, usable=True, adequacy="short_doc"),
        browser=_step(WIGOLO_BROWSER_BACKEND, "success", usable=True, content=ADEQUATE, adequacy=ADEQUATE_SHAPE),
    )
    assert row["browser_called"] is True
    assert row["usable_content"] is True


def test_required_capabilities_come_from_the_frozen_contract() -> None:
    for category in BAKEOFF_CLASSES:
        row, _ = _measure(category, native=_native_for_category(category))
        assert row["required_capabilities"] == sorted(CLASS_CAPABILITY_DEMAND[category])


# ---------------------------------------------------------------------------
# Honest failure
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("wall_state", ["login_required", "anti_bot", "shell_page"])
def test_a_rendered_wall_is_reported_as_an_honest_failure(wall_state: str) -> None:
    row, _ = _measure(
        CLASS_SESSION_REQUIRED,
        native=_step(NATIVE_HTTP, "login_required"),
        browser=_step(WIGOLO_BROWSER_BACKEND, wall_state, extra={"honesty_downgrade": wall_state}),
    )

    assert row["browser_called"] is True
    assert row["browser_state"] == wall_state
    assert row["browser_usable"] is False
    assert row["usable_content"] is False
    assert row["failure_reason"]
    assert row["provenance_complete"] is True
    validate_bakeoff_result(row)


def test_the_browser_verdict_survives_a_later_failing_step() -> None:
    """The browser's honest classification must not be masked by the chain end."""

    row, _ = _measure(
        CLASS_ANTI_BOT,
        native=_step(NATIVE_HTTP, "anti_bot"),
        browser=_step(WIGOLO_BROWSER_BACKEND, "anti_bot"),
    )
    assert row["browser_state"] == "anti_bot"
    assert row["browser_usable"] is False
    assert row["usable_content"] is False


def test_session_required_accepts_an_honest_login_required() -> None:
    """The class allows ``usable_content_required=false``; a wall is the answer."""

    row, executors = _measure(
        CLASS_SESSION_REQUIRED,
        native=_step(NATIVE_HTTP, "login_required"),
        browser=_step(WIGOLO_BROWSER_BACKEND, "login_required"),
    )
    assert row["usable_content"] is False
    assert row["browser_state"] == "login_required"
    # No session-capable backend remains, so the chain ends without looping.
    assert row["chain_action"] == "exhaust"
    assert len(executors[WIGOLO_BROWSER_BACKEND].calls) == 1


# ---------------------------------------------------------------------------
# The result artifact
# ---------------------------------------------------------------------------


def test_measured_row_carries_the_fields_a3_3_compares() -> None:
    row, _ = _measure(
        CLASS_JS_SHELL,
        native=_step(NATIVE_HTTP, "reset", latency_ms=40.0),
        http=_step(WIGOLO_HTTP, "invalid_content", usable=True, adequacy="short_doc", latency_ms=300.0),
        browser=_step(WIGOLO_BROWSER_BACKEND, "success", usable=True, content=ADEQUATE, adequacy=ADEQUATE_SHAPE, latency_ms=900.0),
    )
    for field in (
        "backend",
        "fixture_id",
        "category",
        "required_capabilities",
        "browser_called",
        "browser_state",
        "browser_usable",
        "outcome_state",
        "usable_content",
        "chain_action",
        "chain_reason",
        "attempts",
        "wall_ms",
        "fetch_ms",
        "cold",
        "bytes",
        "content_type",
        "rendered",
        "cache_hit",
        "failure_reason",
        "provenance_complete",
        "budget_respected",
    ):
        assert field in row, field
    assert row["wall_ms"] == pytest.approx(40.0 + 300.0 + 900.0, abs=0.1)
    assert row["budget_respected"] is True
    assert row["cold"] is True
    assert row["rendered"] is True


def test_result_document_is_versioned_and_validated() -> None:
    row, _ = _measure(
        CLASS_STATIC_CONTROL,
        native=_step(NATIVE_HTTP, "success", usable=True, content=ADEQUATE, adequacy=ADEQUATE_SHAPE),
    )
    document = bakeoff_result_document([row], backend=WIGOLO_BROWSER_BACKEND)
    assert document["schema_version"] == "browser-bakeoff-result-v1"
    assert document["backend"] == WIGOLO_BROWSER_BACKEND
    assert len(document["results"]) == 1
    assert document["budget"]["run_envelope_seconds"] == 3.0


def _result(**overrides: Any) -> dict[str, Any]:
    base = build_bakeoff_result(
        backend=WIGOLO_BROWSER_BACKEND,
        fixture_id="js_shell:x",
        category=CLASS_JS_SHELL,
        required_capabilities=sorted(CLASS_CAPABILITY_DEMAND[CLASS_JS_SHELL]),
        browser_called=True,
        browser_state="success",
        browser_usable=True,
        outcome_state="success",
        usable_content=True,
        chain_action="resolve",
        chain_reason="usable_content",
        attempts=[{"backend": WIGOLO_BROWSER_BACKEND}],
        wall_ms=100.0,
        fetch_ms=100.0,
        cold=True,
        bytes=100,
        content_type="text/markdown",
        rendered=True,
        cache_hit=False,
        failure_reason="",
        provenance_complete=True,
        budget_respected=True,
    )
    base.update(overrides)
    return base


def test_validator_rejects_a_wall_reported_as_content() -> None:
    with pytest.raises(BrowserBakeoffContractError):
        validate_bakeoff_result(
            _result(
                outcome_state="login_required",
                usable_content=True,
                browser_state="login_required",
                browser_usable=False,
            )
        )


def test_validator_rejects_a_browser_wall_marked_usable() -> None:
    with pytest.raises(BrowserBakeoffContractError):
        validate_bakeoff_result(
            _result(browser_state="login_required", browser_usable=True)
        )


def test_validator_rejects_usable_content_without_success() -> None:
    with pytest.raises(BrowserBakeoffContractError):
        validate_bakeoff_result(
            _result(
                outcome_state="anti_bot",
                usable_content=True,
                browser_state="anti_bot",
                browser_usable=False,
            )
        )


def test_validator_rejects_a_browser_verdict_without_a_call() -> None:
    with pytest.raises(BrowserBakeoffContractError):
        validate_bakeoff_result(_result(browser_called=False))


def test_validator_rejects_a_call_without_a_browser_verdict() -> None:
    with pytest.raises(BrowserBakeoffContractError):
        validate_bakeoff_result(_result(browser_state="", browser_usable=False))


def test_validator_rejects_a_browser_call_on_the_static_control() -> None:
    with pytest.raises(BrowserBakeoffContractError):
        validate_bakeoff_result(
            _result(
                category=CLASS_STATIC_CONTROL,
                required_capabilities=[],
                browser_called=True,
            )
        )


def test_validator_rejects_a_non_canonical_state() -> None:
    with pytest.raises(BrowserBakeoffContractError):
        validate_bakeoff_result(_result(outcome_state="rendered_ok"))


def test_validator_rejects_a_capability_outside_the_frozen_vocabulary() -> None:
    with pytest.raises(BrowserBakeoffContractError):
        validate_bakeoff_result(_result(required_capabilities=["headless_chrome"]))


def test_validator_rejects_a_missing_field() -> None:
    broken = _result()
    broken.pop("budget_respected")
    with pytest.raises(BrowserBakeoffContractError):
        validate_bakeoff_result(broken)


# ---------------------------------------------------------------------------
# Production-inert
# ---------------------------------------------------------------------------


def test_harness_does_not_touch_the_production_chain() -> None:
    runtime = Path("src/application/active_research_runtime.py").read_text(
        encoding="utf-8"
    )
    chain_match = re.search(
        r"ACTIVE_READER_CHAIN(?:\s*:\s*[^=]+)?\s*=\s*\(([^)]*)\)", runtime
    )
    assert chain_match is not None, "the production reader chain must be declared"
    assert chain_match.group(1).strip() == "NATIVE_HTTP_BACKEND, WIGOLO_HTTP_BACKEND"
    assert "WigoloBrowserBackendExecutor" not in runtime
    assert BAKEOFF_CHAIN == (NATIVE_HTTP, WIGOLO_HTTP, WIGOLO_BROWSER_BACKEND)
    assert len(BAKEOFF_CHAIN) <= BROWSER_CHAIN_MAX_LENGTH


def test_no_production_module_imports_the_browser_executor() -> None:
    for module in PRODUCTION_MODULES:
        text = Path(module).read_text(encoding="utf-8")
        assert "wigolo_browser_executor" not in text, module
        assert "run_browser_bakeoff" not in text, module
        assert "crawl4ai" not in text, module


def test_run_bakeoff_refuses_an_unimplemented_backend(tmp_path: Any) -> None:
    from tools.run_browser_bakeoff import run_bakeoff

    with pytest.raises(SystemExit):
        run_bakeoff(
            backend="crawl4ai",
            manifest_path=Path("tests/fixtures/research_quality/browser_bakeoff_manifest.json"),
            base_url="http://127.0.0.1:3333",
            timeout=5.0,
        )


def test_run_bakeoff_refuses_an_unknown_backend() -> None:
    from tools.run_browser_bakeoff import run_bakeoff

    with pytest.raises(SystemExit):
        run_bakeoff(
            backend="not_a_backend",
            manifest_path=Path("tests/fixtures/research_quality/browser_bakeoff_manifest.json"),
            base_url="http://127.0.0.1:3333",
            timeout=5.0,
        )
