from __future__ import annotations

import json

from fastapi.testclient import TestClient

from src import memory_writer
from src.api import app
from src.application.memory_service import MemoryService, updates_hash
from src.application.runtime_repository import get_memory_service
from src.infrastructure.sqlite.database import RuntimeDatabase
from src.mode_manager import RuntimeModes
from src.repositories.memory_repository import MemoryRepository


WRITABLE = RuntimeModes(memory_mode="confirm_write", safe_mode=False)


def test_memory_run_preview_freezes_updates_and_hash(tmp_path, monkeypatch):
    target = tmp_path / "progress.md"
    monkeypatch.setitem(memory_writer.MEMORY_TARGETS, "progress", target)
    repository = MemoryRepository(RuntimeDatabase(tmp_path / "runtime.db"))
    service = MemoryService(repository)

    run = service.create(
        [{"target": "progress", "content": " frozen content "}],
        runtime_modes=WRITABLE,
    )

    assert run.updates == [
        {
            "target": "progress",
            "content": "frozen content",
            "append": True,
            "learner_pending": False,
        }
    ]
    assert run.updates_hash == updates_hash(run.updates)
    assert run.preview["updates"][0]["preview"].endswith("frozen content\n")


def test_memory_commit_uses_frozen_payload_and_blocks_database_tampering(
    tmp_path, monkeypatch
):
    target = tmp_path / "progress.md"
    monkeypatch.setitem(memory_writer.MEMORY_TARGETS, "progress", target)
    database = RuntimeDatabase(tmp_path / "runtime.db")
    repository = MemoryRepository(database)
    service = MemoryService(repository)
    run = service.create(
        [{"target": "progress", "content": "approved"}],
        runtime_modes=WRITABLE,
    )
    with database.connect() as connection:
        connection.execute(
            "UPDATE memory_runs SET updates = ? WHERE id = ?",
            (
                json.dumps(
                    [
                        {
                            "target": "progress",
                            "content": "tampered",
                            "append": True,
                            "learner_pending": False,
                        }
                    ]
                ),
                run.id,
            ),
        )

    committed = service.commit(run.id, runtime_modes=WRITABLE)

    assert committed.status == "blocked"
    assert committed.reason == "updates_hash_mismatch"
    assert not target.exists()


def test_memory_run_api_create_commit_restore_and_list(
    runtime_test_context, tmp_path, monkeypatch
):
    target = tmp_path / "progress.md"
    monkeypatch.setitem(memory_writer.MEMORY_TARGETS, "progress", target)
    monkeypatch.setattr(memory_writer, "load_runtime_modes", lambda: WRITABLE)
    service = runtime_test_context.memory_service
    original_create = service.create
    original_commit = service.commit
    service.create = lambda updates, **kwargs: original_create(  # type: ignore[method-assign]
        updates, runtime_modes=WRITABLE
    )
    service.commit = lambda run_id, **kwargs: original_commit(  # type: ignore[method-assign]
        run_id, runtime_modes=WRITABLE
    )
    app.dependency_overrides[get_memory_service] = lambda: service
    client = TestClient(app)

    created = client.post(
        "/memory-runs",
        json={"updates": [{"target": "progress", "content": "API frozen"}]},
    )
    assert created.status_code == 200
    run_id = created.json()["id"]

    committed = client.post(f"/memory-runs/{run_id}/commit")
    restored = client.get(f"/memory-runs/{run_id}")
    listed = client.get("/memory-runs")

    assert committed.status_code == 200
    assert committed.json()["status"] == "succeeded"
    assert restored.json()["updates_hash"] == created.json()["updates_hash"]
    assert run_id in [run["id"] for run in listed.json()["runs"]]
    assert "API frozen" in target.read_text(encoding="utf-8")
