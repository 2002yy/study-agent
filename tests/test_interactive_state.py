import json

import pytest
from fastapi.testclient import TestClient

from src.api import app
from src.application.runtime_repository import get_interactive_state_repository
from src.infrastructure.sqlite.database import RuntimeDatabase
from src.repositories.interactive_state_repository import (
    MAX_STATE_CHARS,
    InteractiveStateRepository,
    state_size,
)
from src.repositories.runtime_repository import RuntimeRepository


def seeded(tmp_path):
    path = tmp_path / "runtime.db"
    RuntimeRepository(RuntimeDatabase(path)).ensure_chat_thread("chat_state")
    return InteractiveStateRepository(RuntimeDatabase(path))


def test_a_snapshot_is_saved_and_read_back(tmp_path):
    repository = seeded(tmp_path)
    state = {"step": 7, "variables": {"a": 1, "b": 2}}

    saved = repository.upsert("chat_state", "java-reference", 3, state)

    assert saved.revision == 3
    snapshot = repository.get("chat_state", "java-reference")
    assert snapshot is not None
    assert snapshot.state == state
    assert snapshot.revision == 3


def test_the_latest_snapshot_wins_and_keeps_its_revision(tmp_path):
    repository = seeded(tmp_path)

    repository.upsert("chat_state", "java-reference", 3, {"step": 1})
    repository.upsert("chat_state", "java-reference", 4, {"step": 2})

    snapshot = repository.get("chat_state", "java-reference")
    assert snapshot is not None
    assert snapshot.revision == 4
    assert snapshot.state == {"step": 2}


def test_a_missing_component_has_no_snapshot(tmp_path):
    repository = seeded(tmp_path)

    assert repository.get("chat_state", "never-saved") is None


def test_another_thread_cannot_read_the_snapshot(tmp_path):
    repository = seeded(tmp_path)
    repository.upsert("chat_state", "java-reference", 1, {"step": 1})

    assert repository.get("chat_other", "java-reference") is None


def test_state_larger_than_the_bridge_limit_is_refused(tmp_path):
    repository = seeded(tmp_path)

    with pytest.raises(ValueError):
        repository.upsert(
            "chat_state", "java-reference", 1, {"blob": "x" * MAX_STATE_CHARS}
        )


def test_a_non_object_state_is_refused(tmp_path):
    repository = seeded(tmp_path)

    with pytest.raises(ValueError):
        repository.upsert("chat_state", "java-reference", 1, ["not", "an", "object"])  # type: ignore[arg-type]


def test_state_size_is_compact_json_length():
    assert state_size({"a": 1}) == len(json.dumps({"a": 1}, separators=(",", ":")))


def test_the_route_saves_and_reads_a_snapshot(tmp_path):
    repository = seeded(tmp_path)
    app.dependency_overrides[get_interactive_state_repository] = lambda: repository
    client = TestClient(app)
    try:
        saved = client.put(
            "/sessions/chat_state/interactive-state",
            json={
                "component_id": "java-reference",
                "revision": 3,
                "state": {"step": 7},
            },
        )
        loaded = client.get("/sessions/chat_state/interactive-state/java-reference")
    finally:
        app.dependency_overrides.pop(get_interactive_state_repository, None)

    assert saved.status_code == 200
    assert saved.json()["state"] == {"step": 7}
    assert loaded.status_code == 200
    assert loaded.json()["revision"] == 3


def test_the_route_refuses_an_unknown_session(tmp_path):
    repository = seeded(tmp_path)
    app.dependency_overrides[get_interactive_state_repository] = lambda: repository
    client = TestClient(app)
    try:
        response = client.put(
            "/sessions/chat_missing/interactive-state",
            json={"component_id": "java-reference", "revision": 1, "state": {}},
        )
    finally:
        app.dependency_overrides.pop(get_interactive_state_repository, None)

    assert response.status_code == 404


def test_the_route_refuses_state_above_the_limit(tmp_path):
    repository = seeded(tmp_path)
    app.dependency_overrides[get_interactive_state_repository] = lambda: repository
    client = TestClient(app)
    try:
        response = client.put(
            "/sessions/chat_state/interactive-state",
            json={
                "component_id": "java-reference",
                "revision": 1,
                "state": {"blob": "x" * MAX_STATE_CHARS},
            },
        )
    finally:
        app.dependency_overrides.pop(get_interactive_state_repository, None)

    assert response.status_code == 422


def test_the_route_rejects_an_invalid_component_identity(tmp_path):
    repository = seeded(tmp_path)
    app.dependency_overrides[get_interactive_state_repository] = lambda: repository
    client = TestClient(app)
    try:
        response = client.put(
            "/sessions/chat_state/interactive-state",
            json={"component_id": "bad id", "revision": 1, "state": {}},
        )
    finally:
        app.dependency_overrides.pop(get_interactive_state_repository, None)

    assert response.status_code == 422
