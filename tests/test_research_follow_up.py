from __future__ import annotations

import sqlite3

import pytest
from fastapi.testclient import TestClient

from src.api import app
from src.application.runtime_repository import get_web_lookup_service
from src.application.web_lookup_service import WebLookupService
from src.domain.runtime_entities import ChatThread, WebLookupRun
from src.infrastructure.sqlite.database import (
    MIGRATIONS,
    RuntimeDatabase,
    _migration_statements,
    apply_migrations,
)
from src.repositories.runtime_repository import RuntimeRepository
from src.repositories.web_lookup_repository import WebLookupRepository


class FollowUpGateway:
    def __init__(self, *, read_ok: bool = True):
        self.read_ok = read_ok
        self.search_calls = 0
        self.read_calls = 0

    def search(self, query: str, *, max_items: int):
        self.search_calls += 1
        return [
            {
                "title": "Python annotation guide",
                "url": "https://example.com/python?utm_source=old",
                "search_excerpt": query,
            },
            {
                "title": "New Python typing reference",
                "url": "https://docs.example.com/typing",
                "search_excerpt": query,
            },
        ][:max_items]

    def read(self, url: str, *, max_chars: int, timeout: float | None = None):
        self.read_calls += 1
        if not self.read_ok and "example.com/python" in url:
            return {"ok": False, "url": url, "error": "gone"}
        return {"ok": True, "url": url, "content": f"fresh content for {url}"}

    def warnings(self):
        return []


def _parent(repository: WebLookupRepository, *, thread_id: str) -> WebLookupRun:
    notes = [
        {
            "url": "https://example.com/python",
            "title": f"note {index}",
            "facts": (f"old structured fact {index} " * 100)[:1400],
        }
        for index in range(10)
    ]
    return repository.create(
        WebLookupRun(
            id="web_lookup_parent",
            query="Python annotations guide",
            stage="completed",
            status="completed",
            owner_thread_id=thread_id,
            research_context={
                "owner": {"thread_id": thread_id, "turn_id": "turn-parent"},
                "deep": {"notes": notes},
                "read_summary": {"attempted": 1},
            },
            selected_sources=[
                {
                    "item": {
                        "title": "Python annotation guide",
                        "url": "https://example.com/python",
                    },
                    "assessment": {
                        "title": "Python annotation guide",
                        "url": "https://example.com/python",
                        "worth_reading": True,
                        "selected": True,
                    },
                    "read": {
                        "ok": True,
                        "status": "read",
                        "content": "raw parent body must not be copied",
                    },
                }
            ],
            items=[
                {
                    "title": "Python annotation guide",
                    "url": "https://example.com/python",
                }
            ],
            source_block="raw parent source block must not be copied",
            provider_status="found",
            stop_reason="sources_read",
            completed_at="2026-08-25T00:00:01+00:00",
        )
    )


def _service(tmp_path, *, read_ok: bool = True):
    database = RuntimeDatabase(tmp_path / "runtime.db")
    runtime = RuntimeRepository(database)
    runtime.create_chat_thread(ChatThread(id="thread-1"))
    repository = WebLookupRepository(database)
    gateway = FollowUpGateway(read_ok=read_ok)
    return runtime, repository, gateway, WebLookupService(repository, gateway)


def test_candidate_is_local_and_child_creation_is_server_owned_and_idempotent(tmp_path):
    _, repository, gateway, service = _service(tmp_path)
    parent = _parent(repository, thread_id="thread-1")

    candidate = service.follow_up_candidate(
        thread_id="thread-1",
        query="Python annotations best practices",
    )

    assert candidate["available"] is True
    assert candidate["parent_run_id"] == parent.id
    assert gateway.search_calls == 0
    child = service.create(
        "Python annotations best practices",
        max_items=8,
        owner_thread_id="thread-1",
        parent_run_id=parent.id,
        create_request_id="follow-up-request-1",
        suggestion_status="accepted",
    )
    duplicate = service.create(
        "Python annotations best practices",
        max_items=8,
        owner_thread_id="thread-1",
        parent_run_id=parent.id,
        create_request_id="follow-up-request-1",
        suggestion_status="accepted",
    )

    assert duplicate.id == child.id
    assert child.parent_run_id == parent.id
    assert child.root_run_id == parent.id
    assert child.lineage_depth == 1
    assert child.owner_thread_id == "thread-1"
    lineage = child.research_context["lineage"]
    assert "raw parent source block" not in str(lineage)
    assert "raw parent body" not in str(lineage)
    candidates = lineage["inherited_candidates"]
    notes = [item["inherited_note_seed"] for item in candidates if "inherited_note_seed" in item]
    assert len(notes) == 1
    assert len(notes[0]["facts"]) <= 1000


def test_follow_up_candidate_and_child_api_expose_server_lineage(tmp_path):
    _, repository, _, service = _service(tmp_path)
    parent = _parent(repository, thread_id="thread-1")
    app.dependency_overrides[get_web_lookup_service] = lambda: service
    client = TestClient(app)
    try:
        candidate = client.get(
            "/sessions/thread-1/research-runs/follow-up-candidate",
            params={"query": "Python annotations best practices"},
        )
        created = client.post(
            "/research-runs",
            json={
                "query": "Python annotations best practices",
                "max_items": 8,
                "owner_thread_id": "thread-1",
                "parent_run_id": parent.id,
                "create_request_id": "api-follow-up-request",
                "suggestion_status": "accepted",
            },
        )
    finally:
        app.dependency_overrides.pop(get_web_lookup_service, None)

    assert candidate.status_code == 200
    assert candidate.json()["parent_run_id"] == parent.id
    assert candidate.json()["steering_required"] is False
    assert created.status_code == 200
    assert created.json()["parent_run_id"] == parent.id
    assert created.json()["root_run_id"] == parent.id
    assert created.json()["lineage_depth"] == 1


def test_inherited_source_requires_fresh_search_and_direct_read(tmp_path):
    _, repository, _, service = _service(tmp_path)
    parent = _parent(repository, thread_id="thread-1")
    child = service.create(
        "Python annotations best practices",
        max_items=8,
        owner_thread_id="thread-1",
        parent_run_id=parent.id,
        create_request_id="follow-up-request-2",
    )

    completed = service.execute(child.id)

    revalidated = [
        record
        for record in completed.selected_sources
        if record.get("evidence_state") == "revalidated"
    ]
    assert len(revalidated) == 1
    assert revalidated[0]["read"]["status"] == "read"
    assert "经重新验证的既有笔记" in completed.source_block
    assert "old structured fact" in completed.source_block
    assert completed.research_context["lineage"]["evidence_counts"]["revalidated"] == 1
    assert completed.lineage_summary["child_count"] == 1


def test_failed_reread_rejects_inherited_fact_and_does_not_cite_it(tmp_path):
    _, repository, _, service = _service(tmp_path, read_ok=False)
    parent = _parent(repository, thread_id="thread-1")
    child = service.create(
        "Python annotations best practices",
        max_items=8,
        owner_thread_id="thread-1",
        parent_run_id=parent.id,
        create_request_id="follow-up-request-3",
    )

    completed = service.execute(child.id)

    assert all(
        record.get("evidence_state") != "revalidated"
        for record in completed.selected_sources
    )
    assert any(
        record.get("evidence_state") == "invalid_or_rejected"
        for record in completed.rejected_sources
    )
    assert "old structured fact" not in completed.source_block
    assert "example.com/python" not in [
        str(item.get("url") or "") for item in completed.items
    ]


def test_child_creation_fails_closed_for_cross_thread_or_archived_thread(tmp_path):
    runtime, repository, _, service = _service(tmp_path)
    runtime.create_chat_thread(ChatThread(id="thread-2"))
    parent = _parent(repository, thread_id="thread-1")

    with pytest.raises(ValueError, match="another thread"):
        service.create(
            "Python annotations follow up",
            max_items=8,
            owner_thread_id="thread-2",
            parent_run_id=parent.id,
            create_request_id="cross-thread",
        )

    with repository.database.connect() as connection:
        connection.execute(
            "UPDATE chat_threads SET status = 'archived' WHERE id = 'thread-1'"
        )
    with pytest.raises(ValueError, match="not active"):
        service.create(
            "Python annotations follow up",
            max_items=8,
            owner_thread_id="thread-1",
            parent_run_id=parent.id,
            create_request_id="archived-thread",
        )


def test_active_parent_and_unconfirmed_failed_parent_cannot_spawn_child(tmp_path):
    _, repository, _, service = _service(tmp_path)
    active = repository.create(
        WebLookupRun(
            id="web_lookup_active",
            query="Python annotations active",
            status="running",
            stage="reading",
            owner_thread_id="thread-1",
            selected_sources=[
                {
                    "item": {"url": "https://example.com/python"},
                    "assessment": {
                        "url": "https://example.com/python",
                        "worth_reading": True,
                    },
                }
            ],
        )
    )
    active_candidate = service.follow_up_candidate(
        thread_id="thread-1",
        query="Python annotations follow up",
    )
    assert active_candidate["steering_required"] is True
    assert active_candidate["parent_run_id"] == active.id
    with pytest.raises(ValueError, match="not terminal"):
        service.create(
            "Python annotations follow up",
            max_items=8,
            owner_thread_id="thread-1",
            parent_run_id=active.id,
            create_request_id="active-parent",
        )

    failed = repository.create(
        WebLookupRun(
            id="web_lookup_failed_parent",
            query="Python annotations failed",
            status="failed",
            stage="failed",
            owner_thread_id="thread-1",
            selected_sources=active.selected_sources,
        )
    )
    with pytest.raises(ValueError, match="explicit confirmation"):
        service.create(
            "Python annotations follow up",
            max_items=8,
            owner_thread_id="thread-1",
            parent_run_id=failed.id,
            create_request_id="failed-parent",
        )


def test_twenty_descendant_safety_limit_requires_a_new_root(tmp_path):
    _, repository, _, service = _service(tmp_path)
    parent = _parent(repository, thread_id="thread-1")
    for index in range(20):
        service.create(
            f"Python annotations follow up {index}",
            max_items=1,
            owner_thread_id="thread-1",
            parent_run_id=parent.id,
            create_request_id=f"descendant-{index}",
        )

    with pytest.raises(ValueError, match="descendant limit"):
        service.create(
            "Python annotations one more",
            max_items=1,
            owner_thread_id="thread-1",
            parent_run_id=parent.id,
            create_request_id="descendant-overflow",
        )


def test_v23_migration_preserves_legacy_runs_as_roots_without_inventing_owner(tmp_path):
    connection = sqlite3.connect(tmp_path / "legacy.db")
    for version, sql in MIGRATIONS:
        if version >= 23:
            break
        for statement in _migration_statements(sql):
            connection.execute(statement)
        connection.execute(
            "INSERT OR REPLACE INTO runtime_meta(key, value) VALUES('schema_version', ?)",
            (str(version),),
        )
    connection.execute(
        """
        INSERT INTO chat_threads(id, status, settings_snapshot, created_at, updated_at)
        VALUES ('thread-existing', 'active', '{}', '2026-08-25', '2026-08-25')
        """
    )
    base_values = (
        "completed",
        "[]",
        "",
        "[]",
        "",
        1,
        "2026-08-25",
        "2026-08-25",
        "2026-08-25",
        "completed",
        "[]",
        "[]",
        "[]",
        "found",
        "sources_read",
        "medium",
    )
    connection.execute(
        """
        INSERT INTO web_lookup_runs(
            id, query, status, items, source_block, warnings, error, version,
            created_at, updated_at, completed_at, stage, research_context,
            query_attempts, selected_sources, rejected_sources, provider_status,
            stop_reason, answer_confidence
        ) VALUES ('legacy-unowned', 'legacy', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '{}', ?, ?, ?, ?, ?, ?)
        """,
        base_values,
    )
    owned_values = list(base_values)
    connection.execute(
        """
        INSERT INTO web_lookup_runs(
            id, query, status, items, source_block, warnings, error, version,
            created_at, updated_at, completed_at, stage, research_context,
            query_attempts, selected_sources, rejected_sources, provider_status,
            stop_reason, answer_confidence
        ) VALUES (
            'legacy-owned', 'legacy', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
            '{"owner":{"thread_id":"thread-existing"}}', ?, ?, ?, ?, ?, ?
        )
        """,
        owned_values,
    )
    connection.commit()

    apply_migrations(connection)

    rows = connection.execute(
        """
        SELECT id, owner_thread_id, parent_run_id, root_run_id, lineage_depth
        FROM web_lookup_runs ORDER BY id
        """
    ).fetchall()
    assert rows == [
        ("legacy-owned", "thread-existing", None, "legacy-owned", 0),
        ("legacy-unowned", None, None, "legacy-unowned", 0),
    ]
    connection.close()
