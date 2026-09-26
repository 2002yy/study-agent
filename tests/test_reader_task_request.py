"""§143-P1 external request-surface binding regressions."""

from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]

from src.application import reader_hint_routing as phr  # noqa: E402
from src.application.reader_hint_routing import (  # noqa: E402
    JS_RENDER,
    SESSION_STATE,
    ROUTE_DEFAULT,
    ROUTE_SPECIALIST,
    ReaderHintError,
)
from src.application.reader_task_request import (  # noqa: E402
    HINT_SOURCE_REQUEST_FIELD,
    HINT_SOURCE_TASK_MANIFEST,
    HINT_SOURCE_UI_TOGGLE,
    ReaderRequestError,
    from_request_field,
    from_task_manifest,
    from_ui_toggle,
    parse_reader_task_request,
    run_reader_task,
)

MODULE = REPO_ROOT / "src" / "application" / "reader_task_request.py"


# ----------------------------------------------------------- no-hint equivalence

def test_absent_none_and_empty_are_all_no_hint() -> None:
    for raw in ({}, {"reader_capabilities": None}, {"reader_capabilities": []}):
        request = from_request_field(raw)
        assert request.reader_capabilities == frozenset()


def test_valid_values_map_one_to_one() -> None:
    assert from_request_field({"reader_capabilities": ["JS_RENDER"]}).reader_capabilities == {
        JS_RENDER
    }
    assert from_request_field(
        {"reader_capabilities": ["SESSION_STATE"], "setup_url": "http://s/start"}
    ).reader_capabilities == {SESSION_STATE}
    assert from_task_manifest({"reader_capabilities": ["JS_RENDER"]}).reader_capabilities == {
        JS_RENDER
    }


# ------------------------------------------------------------------- validation

def test_unknown_external_value_is_rejected() -> None:
    with pytest.raises(ReaderHintError):
        from_request_field({"reader_capabilities": ["PDF"]})
    with pytest.raises(ReaderHintError):
        from_request_field({"reader_capabilities": ["BROWSER_GENERIC"]})


def test_bare_string_is_rejected() -> None:
    with pytest.raises(ReaderHintError):
        from_request_field({"reader_capabilities": "JS_RENDER"})


def test_wrong_type_is_rejected() -> None:
    with pytest.raises(ReaderHintError):
        from_request_field({"reader_capabilities": [1]})
    with pytest.raises(ReaderRequestError):
        parse_reader_task_request("not-a-mapping", hint_source=HINT_SOURCE_REQUEST_FIELD)  # type: ignore[arg-type]


def test_session_state_requires_companion_inputs() -> None:
    with pytest.raises(ReaderRequestError):
        from_request_field({"reader_capabilities": ["SESSION_STATE"]})
    # present companion input is accepted
    request = from_request_field(
        {"reader_capabilities": ["SESSION_STATE"], "session_id": "s1"}
    )
    assert request.session_id == "s1"


# -------------------------------------------------------------- hint provenance

def test_adapter_assigns_closed_hint_source() -> None:
    assert from_request_field({}).hint_source == HINT_SOURCE_REQUEST_FIELD
    assert from_task_manifest({}).hint_source == HINT_SOURCE_TASK_MANIFEST
    assert from_ui_toggle({}).hint_source == HINT_SOURCE_UI_TOGGLE


def test_caller_cannot_spoof_hint_source() -> None:
    with pytest.raises(ReaderRequestError):
        from_request_field({"reader_capabilities": ["JS_RENDER"], "hint_source": "PLANNER"})


def test_unknown_hint_source_is_rejected() -> None:
    with pytest.raises(ReaderRequestError):
        parse_reader_task_request({}, hint_source="SOMETHING_ELSE")


def test_canonical_request_is_immutable() -> None:
    request = from_request_field({"reader_capabilities": ["JS_RENDER"]})
    with pytest.raises(dataclasses.FrozenInstanceError):
        request.reader_capabilities = frozenset()  # type: ignore[misc]


def test_no_auto_derivation_from_url_or_content() -> None:
    src = MODULE.read_text(encoding="utf-8")
    code = src.split('"""', 2)[2] if src.count('"""') >= 2 else src
    for forbidden in ("content_type", "url.endswith", ".pdf", "search_excerpt"):
        assert forbidden not in code, forbidden


# --------------------------------------------------------------- routing wiring

@pytest.fixture()
def readers(monkeypatch):
    calls = {"default": 0, "specialist": 0}

    def default_reader(*, url, **kwargs):
        calls["default"] += 1
        return {"backend_path": ["native_http"]}

    def specialist_reader(*, url, **kwargs):
        calls["specialist"] += 1
        return {
            "specialist_available": True,
            "actual_backend": "crawl4ai_browser",
            "usable_content": True,
            "unavailable_reason": "",
        }

    monkeypatch.setattr(phr, "_DEFAULT_READER", default_reader)
    monkeypatch.setattr(phr, "_SPECIALIST_READER", specialist_reader)
    return calls


def test_no_hint_external_request_preserves_existing_execution(readers) -> None:
    out = run_reader_task(from_request_field({"url": "u"}), hints_enabled=True)
    assert out["route"] == ROUTE_DEFAULT
    assert readers == {"default": 1, "specialist": 0}


def test_flag_off_accepts_field_but_does_not_route(readers) -> None:
    out = run_reader_task(
        from_request_field({"url": "u", "reader_capabilities": ["JS_RENDER"]}),
        hints_enabled=False,
    )
    assert out["route"] == ROUTE_DEFAULT
    assert out["hint_honored"] is False
    assert out["hint_unhonored_reason"] == "hints_disabled"
    assert out["requested_reader_capabilities"] == [JS_RENDER]
    assert out["hint_source"] == HINT_SOURCE_REQUEST_FIELD
    assert readers == {"default": 1, "specialist": 0}


def test_js_hint_routes_specialist_via_request_field(readers) -> None:
    out = run_reader_task(
        from_request_field({"url": "u", "reader_capabilities": ["JS_RENDER"]}),
        hints_enabled=True,
        specialist_config_ok=True,
    )
    assert out["route"] == ROUTE_SPECIALIST
    assert readers == {"default": 0, "specialist": 1}


def test_manifest_hint_maps_one_to_one(readers) -> None:
    request = from_task_manifest({"url": "u", "reader_capabilities": ["JS_RENDER"]})
    assert request.hint_source == HINT_SOURCE_TASK_MANIFEST
    out = run_reader_task(request, hints_enabled=True, specialist_config_ok=True)
    assert out["hint_source"] == HINT_SOURCE_TASK_MANIFEST
    assert out["route"] == ROUTE_SPECIALIST


# --------------------------------------------- operator e2e (explicit env only)

def test_operator_e2e_real_request_specialist_and_fallback(monkeypatch) -> None:
    """Real request -> P1 -> Crawl4AI, and the recorded fallback path."""

    import subprocess
    import sys
    import time
    import urllib.request

    from src.application.reader_hint_routing import explicit_reader_hints_enabled
    from src.web.research.crawl4ai_specialist import configured_python

    if not configured_python():
        pytest.skip("CRAWL4AI_PYTHON not set; operator-provided e2e only")

    monkeypatch.setenv("CRAWL4AI_SPECIALIST_ENABLED", "1")
    monkeypatch.setenv("EXPLICIT_READER_HINTS_ENABLED", "1")
    monkeypatch.setenv("RESEARCH_WIGOLO_ESCALATION", "browser")
    monkeypatch.setenv("WIGOLO_RERANKER", "off")
    assert explicit_reader_hints_enabled() is True

    from tools.run_f2_paired import (
        FIXTURE,
        _allow_local_fixture_reads,
    )
    from src.web.research.active_adapter import (
        ActiveResearchGateway,
        read_gateway_accepts_timeout,
    )
    from src.web.research.crawl4ai_specialist import reset_crawl4ai_specialist

    port = 8802
    server = subprocess.Popen(
        [sys.executable, "-u", "-X", "utf8", str(FIXTURE), "--port", str(port)],
        cwd=str(REPO_ROOT),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    base = f"http://127.0.0.1:{port}"
    ready = False
    deadline = time.time() + 20
    while time.time() < deadline:
        try:
            urllib.request.urlopen(f"{base}/structured-spec.html", timeout=2).read(8)
            ready = True
            break
        except Exception:
            time.sleep(0.3)
    if not ready:
        server.terminate()
        pytest.skip("fixture server not ready")

    _allow_local_fixture_reads()
    gateway = ActiveResearchGateway()
    default_kwargs = {
        "source_limit": 20000,
        "gateway": gateway,
        "escalation_backend": gateway.escalation_backend(),
        "get_context": lambda: {},
        "research_seconds_left": lambda: 45.0,
        "hard_seconds_left": lambda: 60.0,
        "accepts_timeout": read_gateway_accepts_timeout(gateway),
        "wave_index": lambda: 0,
        "candidate_id": "p1-e2e",
    }
    try:
        # 1) real specialist path
        request = from_request_field(
            {
                "url": f"{base}/structured-spec.html",
                "reader_capabilities": ["JS_RENDER"],
            }
        )
        out = run_reader_task(
            request,
            hints_enabled=True,
            specialist_config_ok=True,
            default_kwargs=default_kwargs,
            specialist_kwargs={"mode": "browser", "max_chars": 20000},
        )
        assert out["route"] == ROUTE_SPECIALIST
        assert out["hint_honored"] is True
        assert out["actual_backend_path"] == ["crawl4ai_browser"]
        assert out["specialist"]["terminal_outcome"]

        # 2) fallback path when the specialist is not configured
        fallback = run_reader_task(
            request,
            hints_enabled=True,
            specialist_config_ok=False,
            default_kwargs=default_kwargs,
        )
        assert fallback["route"] == ROUTE_DEFAULT
        assert fallback["hint_honored"] is False
        assert fallback["hint_unhonored_reason"] == "specialist_unavailable"
        assert fallback["actual_backend_path"] == ["native_http"]
    finally:
        reset_crawl4ai_specialist()
        server.terminate()
        try:
            server.wait(timeout=5)
        except Exception:
            server.kill()