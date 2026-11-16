import asyncio
import threading
from concurrent.futures import ThreadPoolExecutor

from fastapi.testclient import TestClient

from src.api import app
from src.infrastructure.sqlite.database import RuntimeDatabase
from src.repositories.runtime_repository import RuntimeRepository
from tests.test_chat_stream_cancellation import _service


def test_cancelled_interactive_draft_stays_interrupted_after_session_reload(
    runtime_test_context,
    tmp_path,
):
    emitted = threading.Event()
    draft = '```study-ui\n{"type":"interactive","id":"draft","revision":1,"title":"draft","summary":"draft","html":"<html><body>unverified</body></html>"}\n```'

    async def tokens(*args, **kwargs):
        yield draft
        emitted.set()
        await asyncio.sleep(20)
        yield "LATE_COMPLETION_MUST_NOT_APPEAR"

    service = _service(runtime_test_context, tokens)
    with TestClient(app) as client, ThreadPoolExecutor(max_workers=1) as pool:
        response_future = pool.submit(
            client.post,
            "/chat/stream",
            json={
                "user_input": "show interactive page",
                "session_id": "cancel-refresh",
                "turn_id": "cancel-refresh-turn",
                "operation_id": "cancel-refresh-op",
                "selected_role": "nahida",
                "selected_mode": "普通",
                "selected_model": "flash",
            },
        )
        assert emitted.wait(10), "provider never yielded its draft"
        turn = service.repository.get_chat_turn("cancel-refresh-turn")
        cancelled = client.post(
            f"/chat/turns/{turn.id}/cancel",
            json={"expected_operation_id": turn.operation_id},
        )
        assert cancelled.status_code == 200
        assert cancelled.json()["outcome"] == "accepted"
        stream = response_future.result(timeout=10)
        assert "event: cancelled" in stream.text
        assert "event: done" not in stream.text
        status = client.get(f"/chat/turns/{turn.id}/status").json()
        assert status["status"] == "interrupted"
        assert status["assistant_message"] == draft
    # New client request reads the durable session projection after stream exit.
    with TestClient(app) as reloaded:
        response = reloaded.get("/sessions/cancel-refresh")
        assert response.status_code == 200
        messages = response.json()["messages"]
        assistant = [item for item in messages if item["role"] == "assistant"]
        assert len(assistant) == 1
        assert assistant[0]["turnStatus"] == "interrupted"
        assert assistant[0]["content"] == draft
        assert "LATE_COMPLETION" not in response.text

    reopened = RuntimeRepository(
        RuntimeDatabase(tmp_path / "api-runtime" / "runtime.db")
    )
    persisted = reopened.get_chat_turn("cancel-refresh-turn")
    assert persisted.status == "interrupted"
    assert persisted.assistant_message == draft
