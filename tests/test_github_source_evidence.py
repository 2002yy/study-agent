from __future__ import annotations

from types import SimpleNamespace

from src.application.github_source_evidence import (
    match_line_range,
    primary_symbol_for_range,
    summarize_commit_ci,
)


COMMIT_SHA = "a" * 40


def _symbol(name: str, start: int, end: int):
    return SimpleNamespace(
        qualified_name=name,
        evidence=SimpleNamespace(start_line=start, end_line=end),
    )


def test_match_line_range_finds_identifier_tokens_inside_wide_chunk():
    text = """class Example:\n    def other(self):\n        return 1\n\n    def prepare_chat_turn(self, message):\n        return message\n"""

    assert match_line_range(
        text=text,
        chunk_start_line=10,
        chunk_end_line=15,
        query="prepare chat turn",
    ) == (14, 14)


def test_match_line_range_falls_back_to_chunk_when_query_has_no_lexical_hit():
    assert match_line_range(
        text="def example():\n    return 1",
        chunk_start_line=20,
        chunk_end_line=21,
        query="completely unrelated",
    ) == (20, 21)


def test_primary_symbol_prefers_innermost_containing_symbol():
    symbols = [
        _symbol("Outer", 1, 20),
        _symbol("Outer.handle", 5, 12),
        _symbol("Outer.handle.inner", 8, 10),
    ]

    primary = primary_symbol_for_range(symbols, start_line=9, end_line=9)

    assert primary is not None
    assert primary.qualified_name == "Outer.handle.inner"


def test_primary_symbol_returns_none_when_match_is_outside_definitions():
    assert primary_symbol_for_range(
        [_symbol("Example.run", 5, 10)],
        start_line=2,
        end_line=2,
    ) is None


def test_ci_summary_requires_exact_commit_sha():
    result = summarize_commit_ci(
        {
            "ok": True,
            "commit_sha": "b" * 40,
            "check_runs": [
                {"name": "tests", "status": "completed", "conclusion": "success"}
            ],
        },
        commit_sha=COMMIT_SHA,
    )

    assert result["association"] == "unavailable"
    assert result["overall_status"] == "unknown"
    assert result["error"] == "commit_sha_mismatch"
    assert result["checks"] == []


def test_ci_summary_normalizes_success_failure_and_pending():
    success = summarize_commit_ci(
        {
            "ok": True,
            "commit_sha": COMMIT_SHA,
            "provider_status": "complete",
            "check_runs": [
                {
                    "name": "lint",
                    "status": "completed",
                    "conclusion": "success",
                    "details_url": "https://example/lint",
                },
                {
                    "name": "tests",
                    "status": "completed",
                    "conclusion": "success",
                    "details_url": "https://example/tests",
                },
            ],
        },
        commit_sha=COMMIT_SHA,
    )
    failure = summarize_commit_ci(
        {
            "ok": True,
            "commit_sha": COMMIT_SHA,
            "check_runs": [
                {"name": "tests", "status": "completed", "conclusion": "failure"},
            ],
        },
        commit_sha=COMMIT_SHA,
    )
    pending = summarize_commit_ci(
        {
            "ok": True,
            "commit_sha": COMMIT_SHA,
            "check_runs": [
                {"name": "tests", "status": "in_progress", "conclusion": ""},
            ],
        },
        commit_sha=COMMIT_SHA,
    )

    assert success["association"] == "verified_exact_sha"
    assert success["overall_status"] == "success"
    assert [item["name"] for item in success["checks"]] == ["lint", "tests"]
    assert failure["overall_status"] == "failure"
    assert pending["overall_status"] == "pending"


def test_ci_summary_uses_exact_sha_workflow_run_when_checks_are_absent():
    result = summarize_commit_ci(
        {
            "ok": True,
            "commit_sha": COMMIT_SHA,
            "workflow_runs": [
                {
                    "name": "CI",
                    "head_sha": COMMIT_SHA,
                    "status": "completed",
                    "conclusion": "success",
                    "url": "https://example/workflow",
                },
                {
                    "name": "wrong-sha",
                    "head_sha": "b" * 40,
                    "status": "completed",
                    "conclusion": "failure",
                },
            ],
        },
        commit_sha=COMMIT_SHA,
    )

    assert result["association"] == "verified_exact_sha"
    assert result["overall_status"] == "success"
    assert result["checks"] == [
        {
            "kind": "workflow_run",
            "name": "CI",
            "status": "completed",
            "conclusion": "success",
            "details_url": "https://example/workflow",
        }
    ]


def test_ci_summary_degrades_cleanly_for_provider_failure_and_no_runs():
    unavailable = summarize_commit_ci(
        {"ok": False, "status": "unavailable", "error": "github_http_403"},
        commit_sha=COMMIT_SHA,
    )
    empty = summarize_commit_ci(
        {"ok": True, "commit_sha": COMMIT_SHA, "check_runs": []},
        commit_sha=COMMIT_SHA,
    )

    assert unavailable["association"] == "unavailable"
    assert unavailable["error"] == "github_http_403"
    assert empty["association"] == "unavailable"
    assert empty["error"] == "no_ci_runs"
