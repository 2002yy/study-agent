from __future__ import annotations

import json
from pathlib import Path

from tools import run_research_quality_live_observation as live_tool


class _Gateway:
    def search_detailed(self, query: str, *, max_results: int):
        return {
            "status": "ok",
            "reason": "results_found",
            "attempted_queries": [query],
            "providers_attempted": ["test-provider"],
            "provider_errors": [],
            "results": [
                {
                    "title": "FastAPI project license official source",
                    "url": "https://example.test/official",
                    "source": "test-provider",
                    "snippet": "must not be persisted",
                }
            ][:max_results],
        }

    def read(self, url: str, *, max_chars: int, timeout: float | None = None):
        return {
            "ok": True,
            "url": url,
            "content": "private page body must not be persisted"[:max_chars],
            "backend": "test-reader",
        }


def test_live_observation_records_bounded_metadata_without_page_bodies(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(live_tool, "GeneralWebGateway", _Gateway)
    output = tmp_path / "observation.json"

    artifact = live_tool.run_live_observation(
        cases_path=live_tool.DEFAULT_CASES,
        output_path=output,
        max_results=1,
        max_reads=1,
        max_chars=1000,
        selected_case_ids={"trap-simple-factual-live"},
    )

    assert artifact["summary"]["search_ok_cases"] == 1
    assert artifact["summary"]["cases_with_successful_read"] == 1
    restored = json.loads(output.read_text(encoding="utf-8"))
    serialized = json.dumps(restored, ensure_ascii=False)
    assert "private page body" not in serialized
    assert "must not be persisted" not in serialized
    assert restored["cases"][0]["reads"][0]["content_chars"] > 0
    assert restored["scope"]["produces_shadow_decision"] is False
