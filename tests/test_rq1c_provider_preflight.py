from __future__ import annotations

from typing import Any

import tools.run_rq1c_provider_preflight as preflight


class _FakeSearch:
    def __init__(self, outcomes: list[dict[str, Any]], degraded: tuple[str, ...] = ()) -> None:
        self._outcomes = outcomes
        self._degraded = degraded

    def _provider_enabled(self, provider: str) -> bool:
        return True

    def search_exact(self, query: str, *, max_results: int = 5) -> dict[str, Any]:
        return {
            "status": "partial",
            "reason": "results_with_provider_failures",
            "provider_audits": [],
            "provider_outcomes": list(self._outcomes),
        }

    def degraded_providers(self) -> tuple[str, ...]:
        return self._degraded


def _outcome(provider: str, status: str, result_count: int, reason: str = "") -> dict[str, Any]:
    return {
        "provider": provider,
        "status": status,
        "reason": reason,
        "attempts": 1,
        "result_count": result_count,
    }


def test_preflight_reports_degraded_when_only_some_providers_bear_results(
    monkeypatch,
) -> None:
    fake = _FakeSearch(
        [
            _outcome("searxng", "failed", 0, "challenge"),
            _outcome("bing_rss", "ok", 5, "results_found"),
            _outcome("duckduckgo_html", "failed", 0, "timeout"),
        ],
        degraded=("searxng", "duckduckgo_html"),
    )
    monkeypatch.setattr(preflight, "ResearchProviderSearch", lambda: fake)
    monkeypatch.setattr(preflight, "load_dotenv", lambda *a, **k: None)

    artifact = preflight.run_preflight(output_path=None)

    assert artifact["decision"] == "degraded"
    assert artifact["result_bearing_providers"] == ["bing_rss"]
    assert artifact["degraded_providers"] == ["searxng", "duckduckgo_html"]


def test_preflight_reports_unqualified_when_no_provider_bears_results(
    monkeypatch,
) -> None:
    fake = _FakeSearch(
        [
            _outcome("searxng", "failed", 0, "challenge"),
            _outcome("bing_rss", "failed", 0, "timeout"),
            _outcome("duckduckgo_html", "skipped", 0, "skipped_insufficient_budget"),
        ]
    )
    monkeypatch.setattr(preflight, "ResearchProviderSearch", lambda: fake)
    monkeypatch.setattr(preflight, "load_dotenv", lambda *a, **k: None)

    artifact = preflight.run_preflight(output_path=None)

    assert artifact["decision"] == "unqualified"
    assert artifact["result_bearing_providers"] == []
