"""Read telemetry projections must stay independent of scheduling decisions."""

from src.application.active_research_runtime import (
    _record_backend_health as legacy_record_backend_health,
)
from src.application.active_research_runtime import (
    _record_read_timing as legacy_record_read_timing,
)
from src.application.research_runtime_read_observability import (
    _record_backend_health,
    _record_read_timing,
)
from src.web.research.candidate_pool import CandidatePoolItem
from src.web.research.timing_ledger import ACTIVE_RESEARCH_METRICS_KEY


def _candidate() -> CandidatePoolItem:
    return CandidatePoolItem(
        id="candidate-1",
        canonical_url="https://example.test/read",
        url="https://example.test/read",
        title="Title",
        snippet="Snippet",
        source="search",
        published_at="",
        query_ids=(),
        intents=(),
        providers=(),
        first_seen_rank=0,
    )


def test_read_timing_preserves_backend_retry_components_and_legacy_import() -> None:
    assert legacy_record_read_timing is _record_read_timing
    context: dict = {}
    _record_read_timing(
        context,
        candidate=_candidate(),
        wave_index=3,
        status="failed",
        wall_ms=40.0,
        chars=0,
        raw_read={
            "read_retry": {
                "retry_fetch_ms": 20.0,
                "retry_backoff_ms": 5.0,
                "attempts": 2,
                "retries": 1,
                "attempts_detail": [{"index": i} for i in range(6)],
            },
            "escalation": {"latency_ms": 7.0},
            "retrieval_state": "failed",
            "retrieval_policy": {"attempted": True, "backend": "native_http"},
        },
        backend="native_http",
    )

    rows = context[ACTIVE_RESEARCH_METRICS_KEY]["read_timing"]
    assert len(rows) == 1
    row = rows[0]
    assert (row["candidate_id"], row["host"], row["wave_index"]) == (
        "candidate-1",
        "example.test",
        3,
    )
    assert (row["wall_ms"], row["fetch_ms"], row["backoff_ms"]) == (40.0, 20.0, 5.0)
    assert (row["local_ms"], row["escalation_ms"]) == (15.0, 7.0)
    assert (row["attempts"], row["retries"]) == (2, 1)
    assert len(row["attempts_detail"]) == 4
    assert row["retrieval_policy"]["attempted"] is True


def test_read_timing_keeps_80_entries_and_invalid_metrics_untouched() -> None:
    context = {ACTIVE_RESEARCH_METRICS_KEY: {"read_timing": [{"ordinal": i} for i in range(80)]}}
    _record_read_timing(
        context,
        candidate=_candidate(),
        wave_index=1,
        status="success",
        wall_ms=4,
        chars=12,
        raw_read={},
    )
    rows = context[ACTIVE_RESEARCH_METRICS_KEY]["read_timing"]
    assert len(rows) == 80
    assert rows[0] == {"ordinal": 1}
    assert rows[-1]["fetch_ms"] == 4.0

    invalid = {ACTIVE_RESEARCH_METRICS_KEY: "legacy-invalid"}
    _record_read_timing(
        invalid,
        candidate=_candidate(),
        wave_index=1,
        status="failed",
        wall_ms=0,
        chars=0,
        raw_read={},
    )
    assert invalid[ACTIVE_RESEARCH_METRICS_KEY] == "legacy-invalid"


def test_backend_health_snapshot_does_not_affect_reader_state() -> None:
    assert legacy_record_backend_health is _record_backend_health
    context: dict = {}
    _record_backend_health(context, None)
    assert context == {}

    class _Breaker:
        def snapshot(self):
            return {"native_http": {"state": "open"}}

    _record_backend_health(context, _Breaker())
    assert context[ACTIVE_RESEARCH_METRICS_KEY]["backend_health"] == {
        "native_http": {"state": "open"}
    }
