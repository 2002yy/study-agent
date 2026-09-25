"""§143-RS read-site selector regressions.

Covers the frozen read-site contract (docs/PROJECT_STATUS.md §143.158-§143.160):
no hint -> default chain unchanged; explicit hint + both gates + ready -> the
specialist runs first and only usable content short-circuits; anything else
falls back to the original inline default chain. Transport records intent on the
run context only.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
RUNTIME_TEST = REPO_ROOT / "tests" / "test_active_research_runtime.py"

from src.application import active_research_runtime as runtime  # noqa: E402
from src.application.reader_hint_routing import (  # noqa: E402
    EXPLICIT_HINTS_ENABLED_ENV,
    JS_RENDER,
    SESSION_STATE,
)
from src.web.research.chain_executor import ChainStepResult  # noqa: E402


def _load_test_module():
    spec = importlib.util.spec_from_file_location("_art_selector", RUNTIME_TEST)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ART = _load_test_module()


# ------------------------------------------------------------- pure decision

def test_no_hint_is_default(monkeypatch) -> None:
    monkeypatch.delenv(EXPLICIT_HINTS_ENABLED_ENV, raising=False)
    route = runtime.read_site_hint_route({})
    assert route["route"] == "default"
    assert route["hint_honored"] is True
    assert route["requested_reader_capabilities"] == []


def test_hint_with_flag_off_is_default(monkeypatch) -> None:
    monkeypatch.delenv(EXPLICIT_HINTS_ENABLED_ENV, raising=False)
    route = runtime.read_site_hint_route({"reader_capabilities": [JS_RENDER]})
    assert route["route"] == "default"
    assert route["hint_honored"] is False
    assert route["reason"] == "hints_disabled"


def test_hint_ready_routes_specialist(monkeypatch) -> None:
    monkeypatch.setenv(EXPLICIT_HINTS_ENABLED_ENV, "1")
    monkeypatch.setenv("CRAWL4AI_SPECIALIST_ENABLED", "1")
    monkeypatch.setenv("CRAWL4AI_PYTHON", str(Path(__file__)))
    monkeypatch.setenv("RESEARCH_WIGOLO_ESCALATION", "browser")
    route = runtime.read_site_hint_route({"reader_capabilities": [JS_RENDER]})
    assert route["route"] == "specialist"
    assert route["hint_honored"] is True


def test_session_hint_without_inputs_is_unsatisfied(monkeypatch) -> None:
    monkeypatch.setenv(EXPLICIT_HINTS_ENABLED_ENV, "1")
    monkeypatch.setenv("CRAWL4AI_SPECIALIST_ENABLED", "1")
    monkeypatch.setenv("CRAWL4AI_PYTHON", str(Path(__file__)))
    monkeypatch.setenv("RESEARCH_WIGOLO_ESCALATION", "browser")
    route = runtime.read_site_hint_route({"reader_capabilities": [SESSION_STATE]})
    assert route["route"] == "unsatisfied"
    assert route["reason"] == "session_inputs_missing"


# ------------------------------------------------- deterministic execute()

def _hint_context(*capabilities: str, session_id: str = "") -> dict:
    context = ART._active_context()
    context["reader_capabilities"] = list(capabilities)
    context["reader_capabilities_source"] = "REQUEST_FIELD"
    if session_id:
        context["reader_session_id"] = session_id
    return context


def _run_with_hint(monkeypatch, tmp_path, *, capabilities, specialist):
    monkeypatch.setenv(EXPLICIT_HINTS_ENABLED_ENV, "1")
    monkeypatch.setenv("CRAWL4AI_SPECIALIST_ENABLED", "1")
    monkeypatch.setenv("CRAWL4AI_PYTHON", str(Path(__file__)))
    monkeypatch.setenv("RESEARCH_WIGOLO_ESCALATION", "browser")
    monkeypatch.setenv("WIGOLO_RERANKER", "off")

    monkeypatch.setattr(
        "src.web.research.crawl4ai_specialist.invoke_crawl4ai_specialist",
        specialist,
    )

    repository = ART._TrackingRepository(ART.RuntimeDatabase(tmp_path / "selector.sqlite"))
    run = repository.create(
        ART.WebLookupRun(
            id="run_selector",
            query="What is the verified current release date?",
            stage="planned",
            status="pending",
            research_context=_hint_context(*capabilities),
            max_items=5,
        )
    )
    service = ART._cutover_service(
        repository,
        ART._StructuredClient(),
        read_gateway=ART._ShortNativeReadGateway(text="z" * 1200),
        escalation_backend=ART._CutoverEscalationBackend("y" * 1200),
    )
    return service.execute(run.id, raise_on_error=True)


def _usable_specialist(*, url, **kwargs):
    return {
        "specialist_available": True,
        "actual_backend": "crawl4ai_browser",
        "usable_content": True,
        "unavailable_reason": "",
        "terminal_outcome": "success",
        "latency_ms": 12.0,
        "result": ChainStepResult(
            backend="crawl4ai_browser",
            retrieval_state="success",
            attempted=True,
            usable_content=True,
            content="z" * 1200,
            adequacy_reason="ok",
        ),
    }


def _unusable_specialist(*, url, **kwargs):
    return {
        "specialist_available": False,
        "actual_backend": "",
        "usable_content": False,
        "unavailable_reason": "worker_crash",
        "terminal_outcome": "",
        "latency_ms": 0.0,
        "result": None,
    }


def test_usable_specialist_short_circuits_default_chain(monkeypatch, tmp_path) -> None:
    called = {"run_chain": 0}
    original = runtime.run_chain

    def spy_run_chain(*args, **kwargs):
        called["run_chain"] += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(runtime, "run_chain", spy_run_chain)
    completed = _run_with_hint(
        monkeypatch, tmp_path, capabilities=[JS_RENDER], specialist=_usable_specialist
    )

    rows = ART._chain_rows(completed)
    assert rows, "the read site must record its decision"
    assert all(
        [step["backend"] for step in row["steps"]] == ["crawl4ai_browser"] for row in rows
    )
    assert called["run_chain"] == 0, "usable specialist must skip the default chain"
    specialist_rows = completed.research_context[ART.ACTIVE_RESEARCH_METRICS_KEY][
        "read_site_specialist"
    ]
    assert specialist_rows and specialist_rows[0]["hint_honored"] is True
    assert specialist_rows[0]["specialist_usable"] is True
    assert specialist_rows[0]["fallback_used"] is False


def test_unusable_specialist_falls_back_to_default_chain(monkeypatch, tmp_path) -> None:
    called = {"run_chain": 0}
    original = runtime.run_chain

    def spy_run_chain(*args, **kwargs):
        called["run_chain"] += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(runtime, "run_chain", spy_run_chain)
    completed = _run_with_hint(
        monkeypatch, tmp_path, capabilities=[JS_RENDER], specialist=_unusable_specialist
    )

    assert called["run_chain"] > 0, "an unusable specialist must fall back to default"
    rows = ART._chain_rows(completed)
    assert rows
    assert all(
        [step["backend"] for step in row["steps"]][0] == "native_http" for row in rows
    )
    specialist_rows = completed.research_context[ART.ACTIVE_RESEARCH_METRICS_KEY][
        "read_site_specialist"
    ]
    assert specialist_rows
    # specialist executed but delivered nothing usable -> not honored as content,
    # recorded as a fallback (per §143.159 precise semantics)
    assert specialist_rows[0]["specialist_attempted"] is True
    assert specialist_rows[0]["specialist_usable"] is False
    assert specialist_rows[0]["fallback_used"] is True


# ------------------------------------------------------------- transport

def test_create_records_explicit_hint_on_context(tmp_path) -> None:
    from src.application.web_lookup_service import WebLookupService

    repository = ART._TrackingRepository(ART.RuntimeDatabase(tmp_path / "hint.sqlite"))
    run = WebLookupService(repository).create(
        "What is the verified release date?",
        reader_capabilities=[JS_RENDER],
    )
    context = run.research_context
    assert context["reader_capabilities"] == [JS_RENDER]
    assert context["reader_capabilities_source"] == "REQUEST_FIELD"


def test_create_rejects_unknown_capability(tmp_path) -> None:
    from src.application.reader_hint_routing import ReaderHintError
    from src.application.web_lookup_service import WebLookupService

    repository = ART._TrackingRepository(ART.RuntimeDatabase(tmp_path / "hint2.sqlite"))
    with pytest.raises(ReaderHintError):
        WebLookupService(repository).create("q", reader_capabilities=["PDF"])
