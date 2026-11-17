"""Window diagnostics may observe budgets, but may not settle or extend them."""

from __future__ import annotations

from src.application.research_runtime_window_diagnostics import (
    ResearchWindowDiagnostics,
)
from src.web.research.timing_ledger import ACTIVE_RESEARCH_METRICS_KEY


def test_window_end_keeps_two_monotonic_samples_and_original_metrics() -> None:
    diagnostics = ResearchWindowDiagnostics(reserve_seconds=12.0)
    context: dict = {}
    samples = iter((48.1256, 48.1334))
    seen: list[str] = []

    def elapsed() -> float:
        seen.append("elapsed")
        return next(samples)

    diagnostics.record_end(
        context, hard_seconds=60.0, elapsed=elapsed, exhausted=True
    )

    assert seen == ["elapsed", "elapsed"]
    assert context[ACTIVE_RESEARCH_METRICS_KEY]["research_window"] == {
        "reserve_seconds": 12.0,
        "hard_seconds": 60.0,
        "deadline_elapsed": 48.0,
        "research_elapsed_seconds": 48.126,
        "remaining_after_research_seconds": 11.867,
        "exhausted": True,
    }


def test_window_diagnostics_never_hold_or_overwrite_rebound_context() -> None:
    diagnostics = ResearchWindowDiagnostics(reserve_seconds=12.0)
    first: dict = {}
    second: dict = {}

    diagnostics.record_end(
        first, hard_seconds=60.0, elapsed=lambda: 2.0, exhausted=False
    )
    diagnostics.record_end(
        second, hard_seconds=90.0, elapsed=lambda: 6.0, exhausted=True
    )

    assert first[ACTIVE_RESEARCH_METRICS_KEY]["research_window"]["hard_seconds"] == 60
    assert second[ACTIVE_RESEARCH_METRICS_KEY]["research_window"]["hard_seconds"] == 90
    assert first[ACTIVE_RESEARCH_METRICS_KEY]["research_window"]["exhausted"] is False
    assert second[ACTIVE_RESEARCH_METRICS_KEY]["research_window"]["exhausted"] is True


def test_window_skip_reuses_counter_and_resets_invalid_legacy_shape() -> None:
    diagnostics = ResearchWindowDiagnostics(reserve_seconds=12.0)
    context = {
        ACTIVE_RESEARCH_METRICS_KEY: {
            "research_window_skips": {"read": 2, "legacy": None}
        }
    }

    diagnostics.record_skip(context, "read")
    diagnostics.record_skip(context, "legacy")
    diagnostics.record_skip(context, "lead")
    skips = context[ACTIVE_RESEARCH_METRICS_KEY]["research_window_skips"]
    assert skips == {"read": 3, "legacy": 1, "lead": 1}

    context[ACTIVE_RESEARCH_METRICS_KEY]["research_window_skips"] = "legacy"
    diagnostics.record_skip(context, "read")
    assert context[ACTIVE_RESEARCH_METRICS_KEY]["research_window_skips"] == {
        "read": 1
    }
