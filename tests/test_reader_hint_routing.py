"""§143-P1 explicit reader-capability hint routing regressions.

Locks the frozen contract without needing a real runtime or worker: the default
and specialist readers are injected fakes.
"""

from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]

from src.application import reader_hint_routing as phr  # noqa: E402
from src.application.active_research_runtime import ACTIVE_READER_CHAIN  # noqa: E402
from src.application.reader_hint_routing import (  # noqa: E402
    ALLOWED_READER_CAPABILITIES,
    EXPLICIT_HINTS_ENABLED_ENV,
    JS_RENDER,
    SESSION_STATE,
    ROUTE_DEFAULT,
    ROUTE_SPECIALIST,
    ROUTE_SPECIALIST_FALLBACK,
    ROUTE_UNSATISFIED,
    ReaderHintError,
    explicit_reader_hints_enabled,
    parse_reader_capabilities,
    resolve_reader_route,
    run_reader_with_hints,
)

MODULE = REPO_ROOT / "src" / "application" / "reader_hint_routing.py"


# ----------------------------------------------------------------- validation

def test_only_two_capabilities_are_allowed() -> None:
    assert ALLOWED_READER_CAPABILITIES == {JS_RENDER, SESSION_STATE}


def test_parse_accepts_valid_and_dedupes() -> None:
    assert parse_reader_capabilities(None) == ()
    assert parse_reader_capabilities([]) == ()
    assert parse_reader_capabilities(["JS_RENDER", "JS_RENDER", "SESSION_STATE"]) == (
        JS_RENDER,
        SESSION_STATE,
    )


def test_unknown_capability_is_a_validation_error() -> None:
    with pytest.raises(ReaderHintError):
        parse_reader_capabilities(["PDF"])
    with pytest.raises(ReaderHintError):
        parse_reader_capabilities(["BROWSER_GENERIC"])
    with pytest.raises(ReaderHintError):
        parse_reader_capabilities(["js_render"])  # case-sensitive vocabulary


def test_bare_string_is_rejected() -> None:
    with pytest.raises(ReaderHintError):
        parse_reader_capabilities("JS_RENDER")


def test_non_iterable_is_rejected() -> None:
    with pytest.raises(ReaderHintError):
        parse_reader_capabilities(123)


# -------------------------------------------------------------- route decision

def _route(caps, *, enabled=True, config_ok=True, session=False):
    return resolve_reader_route(
        caps,
        hints_enabled=enabled,
        specialist_config_ok=config_ok,
        session_inputs_present=session,
    )


def test_no_hint_is_p0_p4_equivalent() -> None:
    result = _route([])
    assert result["route"] == ROUTE_DEFAULT
    assert result["hint_honored"] is True
    assert result["reason"] == "no_hint"


def test_hint_with_flag_off_has_zero_routing_effect() -> None:
    result = _route([JS_RENDER], enabled=False)
    assert result["route"] == ROUTE_DEFAULT
    assert result["hint_honored"] is False
    assert result["reason"] == "hints_disabled"


def test_session_hint_without_inputs_is_unsatisfied() -> None:
    result = _route([SESSION_STATE], session=False)
    assert result["route"] == ROUTE_UNSATISFIED
    assert result["reason"] == "session_inputs_missing"


def test_session_hint_with_inputs_is_routable() -> None:
    result = _route([SESSION_STATE], session=True)
    assert result["route"] == ROUTE_SPECIALIST


def test_hint_with_specialist_config_missing_falls_back() -> None:
    result = _route([JS_RENDER], config_ok=False)
    assert result["route"] == ROUTE_DEFAULT
    assert result["hint_honored"] is False
    assert result["reason"] == "specialist_unavailable"


def test_hint_with_everything_ready_routes_specialist() -> None:
    result = _route([JS_RENDER, SESSION_STATE], session=True)
    assert result["route"] == ROUTE_SPECIALIST
    assert result["hint_honored"] is True


# ------------------------------------------------------------- run composition

@pytest.fixture()
def readers(monkeypatch):
    calls: dict[str, list] = {"default": [], "specialist": []}

    def default_reader(*, url, **kwargs):
        calls["default"].append({"url": url, **kwargs})
        return {"backend_path": ["native_http"], "content": "default", "usable": True}

    def specialist_reader(*, url, session_id=None, setup_url=None, **kwargs):
        calls["specialist"].append(
            {"url": url, "session_id": session_id, "setup_url": setup_url, **kwargs}
        )
        return {
            "specialist_available": True,
            "actual_backend": "crawl4ai_browser",
            "usable_content": True,
            "unavailable_reason": "",
        }

    monkeypatch.setattr(phr, "_DEFAULT_READER", default_reader)
    monkeypatch.setattr(phr, "_SPECIALIST_READER", specialist_reader)
    return calls


def test_no_hint_calls_default_only(readers) -> None:
    out = run_reader_with_hints(url="u", reader_capabilities=None, hints_enabled=True)
    assert out["route"] == ROUTE_DEFAULT
    assert out["hint_honored"] is True
    assert len(readers["default"]) == 1 and not readers["specialist"]


def test_flag_off_calls_default_only(readers) -> None:
    out = run_reader_with_hints(
        url="u", reader_capabilities=[JS_RENDER], hints_enabled=False
    )
    assert out["route"] == ROUTE_DEFAULT
    assert out["hint_honored"] is False
    assert not readers["specialist"]


def test_hint_specialist_first_skips_default(readers) -> None:
    out = run_reader_with_hints(
        url="u",
        reader_capabilities=[JS_RENDER],
        hints_enabled=True,
        specialist_config_ok=True,
    )
    assert out["route"] == ROUTE_SPECIALIST
    assert out["hint_honored"] is True
    assert out["actual_backend_path"] == ["crawl4ai_browser"]
    assert len(readers["specialist"]) == 1 and not readers["default"]


def test_combined_hints_invoke_specialist_once(readers) -> None:
    run_reader_with_hints(
        url="u",
        reader_capabilities=[JS_RENDER, SESSION_STATE],
        session_id="s1",
        hints_enabled=True,
        specialist_config_ok=True,
    )
    assert len(readers["specialist"]) == 1


def test_unavailable_specialist_falls_back_and_records(readers, monkeypatch) -> None:
    def dead_specialist(*, url, **kwargs):
        return {
            "specialist_available": False,
            "actual_backend": "",
            "usable_content": False,
            "unavailable_reason": "worker_crash",
        }

    monkeypatch.setattr(phr, "_SPECIALIST_READER", dead_specialist)
    out = run_reader_with_hints(
        url="u",
        reader_capabilities=[JS_RENDER],
        hints_enabled=True,
        specialist_config_ok=True,
    )
    assert out["route"] == ROUTE_SPECIALIST_FALLBACK
    assert out["hint_honored"] is False
    assert out["hint_unhonored_reason"] == "worker_crash"
    assert out["actual_backend_path"] == ["native_http"]
    assert len(readers["default"]) == 1


def test_session_missing_inputs_does_no_read(readers) -> None:
    out = run_reader_with_hints(
        url="u",
        reader_capabilities=[SESSION_STATE],
        hints_enabled=True,
        specialist_config_ok=True,
    )
    assert out["route"] == ROUTE_UNSATISFIED
    assert not readers["default"] and not readers["specialist"]


# ------------------------------------------------------------- default env gate

def test_flag_defaults_to_off(monkeypatch) -> None:
    monkeypatch.delenv(EXPLICIT_HINTS_ENABLED_ENV, raising=False)
    assert explicit_reader_hints_enabled() is False


def test_default_chain_is_unchanged() -> None:
    assert ACTIVE_READER_CHAIN == ("native_http", "wigolo_http")


def test_no_auto_derivation_from_page_signals() -> None:
    """Structural: the module never builds a hint from URL/content/outcome."""

    src = MODULE.read_text(encoding="utf-8")
    code = src.split('"""', 2)[2] if src.count('"""') >= 2 else src
    for forbidden in (
        "content_type",
        "terminal_outcome",
        "url.endswith",
        ".pdf",
        "search_excerpt",
        "requests.get",
    ):
        # comments/docstrings already stripped; derive-names must not appear
        assert forbidden not in code, forbidden