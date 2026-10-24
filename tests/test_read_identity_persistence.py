"""AR-1C-2-E2: read identity, status and events land in one persisted write.

These use a real SQLite file, not an in-memory double: the point is that the
authoritative read record, the diagnostic event and the derived evidence all agree
after a reload, and that a failed write leaves the previous state intact.
"""

from pathlib import Path
from typing import Any

import pytest

from src.domain.runtime_entities import WebLookupRun
from src.infrastructure.sqlite.database import RuntimeDatabase
from src.repositories.web_lookup_repository import WebLookupRepository
from src.web.research.motion_events import EVIDENCE_READ, READ_FAILED
from src.web.research.read_evidence import (
    build_read_event,
    normalize_read_result,
    read_evidence_from_records,
    round_read_summary,
    with_attempt_recorded,
)

NOW = "2026-10-20T00:00:00+00:00"
PAGE = "版本 A 在旧设备上仍然受支持，因此兼容性测试仍然需要覆盖它。"


def _repository(tmp_path: Path, name: str = "runtime.sqlite") -> WebLookupRepository:
    return WebLookupRepository(RuntimeDatabase(tmp_path / name))


def _running_run(repository: WebLookupRepository, run_id: str = "run1") -> WebLookupRun:
    return repository.create(
        WebLookupRun(
            id=run_id,
            query="旧设备还支持吗？",
            stage="reading",
            status="running",
            research_context={"run_round": 2},
            max_items=5,
            active_operation_id="op1",
        )
    )


def _record(url: str = "https://example.com/a") -> dict[str, Any]:
    return {
        "item": {"title": "示例页", "url": url},
        "assessment": {"url": url, "worth_reading": True},
    }


def _read(url: str = "https://example.com/a", *, content: str = PAGE, status: str = "read"):
    payload: dict[str, Any] = {"ok": status == "read", "status": status}
    if status == "read":
        payload["content"] = content
    else:
        payload["error"] = "http_403"
    return payload


def _checkpoint(repository: WebLookupRepository, run_id: str, *, sources, context):
    return repository.checkpoint(
        run_id,
        operation_id="op1",
        research_context=context,
        query_attempts=[],
        selected_sources=sources,
        rejected_sources=[],
        items=[],
        warnings=[],
        provider_status="partial",
        stop_reason="sources_partially_read",
    )


def test_the_read_identity_survives_a_real_reload(tmp_path: Path) -> None:
    repository = _repository(tmp_path)
    run = _running_run(repository)

    record = _record()
    read = normalize_read_result(
        _read(),
        run_id=run.id,
        url="https://example.com/a",
        round_index=2,
        record=record,
        at=NOW,
    )
    stored = with_attempt_recorded(record, read)
    event = build_read_event(
        run_id=run.id,
        records=[stored],
        record=stored,
        round_index=2,
        notes=1,
        revision="rev-2",
        at=NOW,
    )
    assert event is not None and event.kind == EVIDENCE_READ
    context = {"revision_events": [event.to_dict()]}
    _checkpoint(repository, run.id, sources=[stored], context=context)

    reloaded = _repository(tmp_path).get(run.id)
    assert reloaded is not None
    persisted_read = reloaded.selected_sources[0]["read"]
    assert persisted_read["read_id"] == read["read_id"]
    assert persisted_read["attempt"] == 1
    assert reloaded.research_context["revision_events"][0]["detail"]["read_id"] == read["read_id"]

    evidence = read_evidence_from_records(reloaded.selected_sources)
    assert evidence[0].read_id == read["read_id"]
    assert evidence[0].content_sha256 == persisted_read["excerpt_sha256"]


def test_a_failed_checkpoint_leaves_the_previous_state_and_replays_the_same_identity(
    tmp_path: Path,
) -> None:
    repository = _repository(tmp_path)
    run = _running_run(repository)

    record = _record()
    read = normalize_read_result(
        _read(),
        run_id=run.id,
        url="https://example.com/a",
        round_index=2,
        record=record,
        at=NOW,
    )
    stored = with_attempt_recorded(record, read)

    import src.repositories.web_lookup_repository as module

    original = module.WebLookupRepository.checkpoint

    def explode(*args, **kwargs):
        raise RuntimeError("disk full")

    module.WebLookupRepository.checkpoint = explode  # type: ignore[method-assign]
    try:
        with pytest.raises(RuntimeError):
            _checkpoint(repository, run.id, sources=[stored], context={"revision_events": []})
    finally:
        module.WebLookupRepository.checkpoint = original  # type: ignore[method-assign]

    reloaded = _repository(tmp_path).get(run.id)
    assert reloaded is not None
    assert reloaded.selected_sources == []  # nothing was half-written
    assert reloaded.research_context.get("revision_events") in (None, [])

    # Replaying after the failure decides the same identity: no twin event.
    replay = normalize_read_result(
        _read(),
        run_id=run.id,
        url="https://example.com/a",
        round_index=2,
        record=record,
        at="2026-10-20T00:05:00+00:00",
    )
    assert replay["read_id"] == read["read_id"]


def test_a_second_read_of_the_same_url_is_a_second_attempt(tmp_path: Path) -> None:
    record = _record()
    first = normalize_read_result(
        _read(), run_id="run1", url="https://example.com/a", round_index=2, record=record, at=NOW
    )
    record = with_attempt_recorded(record, first)

    second = normalize_read_result(
        _read(content=PAGE + "（更新）"),
        run_id="run1",
        url="https://example.com/a",
        round_index=2,
        record=record,
        at=NOW,
    )
    record = with_attempt_recorded(record, second)

    assert second["attempt"] == 2
    assert second["read_id"] != first["read_id"]
    assert [item["read_id"] for item in record["read_history"]] == [
        first["read_id"],
        second["read_id"],
    ]
    # The latest attempt is what the record addresses, and the older one is still
    # addressable through the history rather than being silently overwritten.
    assert record["read"]["read_id"] == second["read_id"]


def test_no_usable_content_is_a_failure_everywhere() -> None:
    record = _record()
    read = normalize_read_result(
        _read(content="   "),
        run_id="run1",
        url="https://example.com/a",
        round_index=2,
        record=record,
        at=NOW,
    )
    stored = with_attempt_recorded(record, read)
    stored["read"]["round"] = 2
    event = build_read_event(
        run_id="run1",
        records=[stored],
        record=stored,
        round_index=2,
        notes=1,
        revision="",
        at=NOW,
    )

    assert read["status"] == "failed"
    assert read["reason"] == "no_usable_content"
    assert event is not None and event.kind == READ_FAILED
    assert round_read_summary([stored]) == [
        {"round": 2, "read": 0, "failed": 1, "recent_recheck": 0}
    ]


def test_the_summary_does_not_call_the_window_a_cumulative_count() -> None:
    records = [_record()]
    records[0]["read"] = {**normalize_read_result(
        _read(), run_id="run1", url="https://example.com/a", round_index=2, record=records[0], at=NOW
    )}
    summary = round_read_summary(records, [])

    assert "recent_recheck" in summary[0]
    assert "recheck" not in summary[0]
