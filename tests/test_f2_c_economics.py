"""§143-C economics regressions (pure functions; no browser/network).

Locks the frozen contract before any C data is produced:
* only three signal classes are allowed (P0 zero-fetch / P1 costed metadata /
  P2 post-default);
* the rule set is finite and preregistered;
* evaluation is a decision vector (recall / FP / material / unresolved / wall),
  with the strict gate ``ESSENTIAL recall == 1.0 and NONE FP == 0``;
* labels are the closed §143-B verdict, never re-derived here.
"""

from __future__ import annotations

from tools.run_f2_c_economics import (  # noqa: E402
    C_LABELS,
    RULES,
    _is_document_path,
    _is_js_path,
    _is_pdf_path,
    _is_session_path,
    _pareto_front,
    _path_of,
    evaluate_rule,
    passes_gate,
)

ALLOWED_CLASSES = {"P0_zero_fetch", "P1_metadata_costed", "P2_post_default"}


def test_rule_set_is_finite_preregistered_and_class_bounded() -> None:
    assert len(RULES) == 11
    for rule in RULES:
        assert rule["signal_class"] in ALLOWED_CLASSES, rule["name"]
        assert callable(rule["match"])
    names = [r["name"] for r in RULES]
    assert len(names) == len(set(names))


def test_url_signal_helpers() -> None:
    assert _path_of("http://127.0.0.1:8793/report.pdf") == "/report.pdf"
    assert _path_of("/session/check") == "/session/check"
    assert _is_pdf_path("/report.pdf") is True
    assert _is_pdf_path("/structured-spec.html") is False
    assert _is_js_path("/spa-delayed.html") is True
    assert _is_js_path("/structured-spec.html") is False
    assert _is_session_path("/session/check") is True
    assert _is_document_path("/document-mixed.html") is True


#: Synthetic contexts mirroring the frozen cohort's real signal values.
def _contexts() -> dict:
    return {
        "simple_static": {
            "path": "/structured-spec.html",
            "content_type": "text/html; charset=utf-8",
            "default": {"terminal_outcome": "resolve", "backend_path": ["native_http"], "steps": []},
        },
        "technical_docs": {
            "path": "/code-docs.html",
            "content_type": "text/html; charset=utf-8",
            "default": {"terminal_outcome": "resolve", "backend_path": ["native_http"], "steps": []},
        },
        "js_heavy": {
            "path": "/spa-delayed.html",
            "content_type": "text/html; charset=utf-8",
            "default": {
                "terminal_outcome": "resolve",
                "backend_path": ["native_http"],
                "steps": [{"adequacy_reason": "ok", "retrieval_state": "success"}],
            },
        },
        "session_sensitive": {
            "path": "/session/check",
            "content_type": "text/html; charset=utf-8",
            "default": {
                "terminal_outcome": "resolve",
                "backend_path": ["native_http", "wigolo_http"],
                "steps": [{"adequacy_reason": "ok", "retrieval_state": "success"}],
            },
        },
        "selected_pdf": {
            "path": "/report.pdf",
            "content_type": "application/pdf",
            "default": {
                "terminal_outcome": "resolve",
                "backend_path": ["native_http", "wigolo_http"],
                "steps": [],
            },
        },
        "document_path": {
            "path": "/document-mixed.html",
            "content_type": "text/html; charset=utf-8",
            "default": {"terminal_outcome": "resolve", "backend_path": ["native_http"], "steps": []},
        },
    }


def _latency() -> dict:
    base = {
        "probe_median_wall_ms": 1.0,
        "probe_p95_wall_ms": 2.0,
        "default_median_wall_ms": 1.0,
        "default_p95_wall_ms": 2.0,
        "specialist_median_wall_ms": 200.0,
        "specialist_p95_wall_ms": 250.0,
    }
    return {category: dict(base) for category in _contexts()}


def test_essential_target_rule_meets_the_strict_gate() -> None:
    contexts = _contexts()
    rule = next(r for r in RULES if r["name"] == "p0_essential_targets")
    result = evaluate_rule(rule, contexts, C_LABELS, _latency())
    assert result["essential_recall"] == 1.0
    assert result["none_false_positives"] == []
    assert result["gate_pass"] is True
    # MATERAL is a weaker positive tier: not captured by the essential rule
    assert result["material_capture"] == []


def test_p0_extension_pdf_captures_material_only() -> None:
    contexts = _contexts()
    rule = next(r for r in RULES if r["name"] == "p0_ext_pdf")
    result = evaluate_rule(rule, contexts, C_LABELS, _latency())
    assert result["material_capture"] == ["selected_pdf"]
    assert result["essential_recall"] == 0.0
    assert result["gate_pass"] is False


def test_document_rule_is_reported_as_no_current_gain_not_none() -> None:
    contexts = _contexts()
    rule = next(r for r in RULES if r["name"] == "p0_path_document")
    result = evaluate_rule(rule, contexts, C_LABELS, _latency())
    assert result["unresolved_no_gain_escalation"] == ["document_path"]
    assert result["none_false_positives"] == []


def test_p1_adds_probe_cost_to_incremental_wall() -> None:
    contexts = _contexts()
    rule = next(r for r in RULES if r["name"] == "p1_ct_pdf")
    result = evaluate_rule(rule, contexts, C_LABELS, _latency())
    # specialist 200 + probe 1
    assert result["incremental_wall_ms_by_triggered"]["selected_pdf"] == 201.0


def test_false_positive_wall_cost_is_measured_on_none_rules() -> None:
    contexts = _contexts()
    # a deliberately over-broad (preregistered) rule to exercise the FP path
    over_broad = {
        "name": "test_over_broad",
        "signal_class": "P0_zero_fetch",
        "signal": "test",
        "match": lambda ctx: True,
    }
    result = evaluate_rule(over_broad, contexts, C_LABELS, _latency())
    assert set(result["none_false_positives"]) == {"simple_static", "technical_docs"}
    assert result["false_positive_wall_cost_ms"] == 200.0
    assert result["gate_pass"] is False


def test_pareto_front_excludes_dominated_rules() -> None:
    results = [
        {"name": "a", "essential_recall": 1.0, "none_false_positives": [], "false_positive_wall_cost_ms": 0.0},
        {"name": "b", "essential_recall": 1.0, "none_false_positives": ["x"], "false_positive_wall_cost_ms": 10.0},
        {"name": "c", "essential_recall": 0.5, "none_false_positives": [], "false_positive_wall_cost_ms": 0.0},
    ]
    assert "a" in _pareto_front(results)
    assert "b" not in _pareto_front(results)
    assert "c" not in _pareto_front(results)


def test_labels_match_the_closed_b_verdict() -> None:
    assert C_LABELS == {
        "simple_static": "NONE",
        "technical_docs": "NONE",
        "js_heavy": "ESSENTIAL",
        "session_sensitive": "ESSENTIAL",
        "selected_pdf": "MATERIAL",
        "document_path": "UNRESOLVED_FOR_TASK",
    }


def test_gate_definition_is_strict() -> None:
    assert passes_gate(
        {"essential_recall": 1.0, "essential_missed": [], "none_false_positives": []}
    )
    assert not passes_gate(
        {"essential_recall": 1.0, "essential_missed": [], "none_false_positives": ["x"]}
    )
    assert not passes_gate(
        {"essential_recall": 0.5, "essential_missed": ["js_heavy"], "none_false_positives": []}
    )
