"""Real SDK serialization with an offline HTTP transport, not model quality."""

import json
from dataclasses import replace

import pytest
import httpx
from openai import OpenAI

from src import llm_client
from src.application.chat_service import ChatCommand, ChatDependencies, ChatService
from src.mode_manager import RuntimeModes
from tests.test_chat_attachment_binding import _context, _ready
from tests.test_session_attachments import _PNG_BYTES


@pytest.mark.parametrize("kind", ["text", "image_description"])
def test_plain_multiturn_attachment_reaches_sdk_wire(tmp_path, monkeypatch, kind):
    repo, attachments = _context(tmp_path)
    if kind == "text":
        ready = _ready(attachments)
        expected_material = "attention and memory"
    else:
        expected_material = "OFFLINE_VISION_DESCRIPTION_17"
        attachments.vision_describer = lambda path: expected_material
        ready = attachments.upload(
            "thread-a", "diagram.png", _PNG_BYTES, content_type="image/png"
        )
    import src.application.runtime_repository as runtime_repository

    monkeypatch.setattr(
        runtime_repository, "get_session_attachment_service", lambda: attachments
    )
    for key, value in {
        "LLM_PROVIDER_PROFILE": "deepseek",
        "DEEPSEEK_API_KEY": "offline-fake",
        "DEEPSEEK_MODEL_FLASH_NAME": "deepseek-flash",
        "DEEPSEEK_MODEL_PRO_NAME": "deepseek-flash",
        "DEEPSEEK_BASE_URL": "https://offline.invalid/v1",
        "STUDY_AGENT_SETTLEMENT_ADMISSION": "0",
    }.items():
        monkeypatch.setenv(key, value)
    captured = []

    def respond(request):
        captured.append(json.loads(request.read()))
        return httpx.Response(
            200,
            json={
                "id": "offline",
                "object": "chat.completion",
                "created": 0,
                "model": "deepseek-flash",
                "choices": [
                    {
                        "index": 0,
                        "message": {
                            "role": "assistant",
                            "content": "FIRST_ANSWER_MARKER",
                        },
                        "finish_reason": "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": 10,
                    "completion_tokens": 10,
                    "total_tokens": 20,
                },
            },
        )

    with httpx.Client(transport=httpx.MockTransport(respond)) as http:
        sdk = OpenAI(
            api_key="offline-fake",
            base_url="https://offline.invalid/v1",
            http_client=http,
            max_retries=0,
        )
        monkeypatch.setattr(llm_client, "get_client", lambda **kw: sdk)
        deps = replace(
            ChatDependencies(),
            load_runtime_modes=lambda: RuntimeModes(performance_mode="fast"),
            read_memory_bundle=lambda _: {},
        )
        service = ChatService(repo, deps)
        common = dict(
            thread_id="thread-a",
            selected_role="nahida",
            selected_mode="普通",
            selected_model="flash",
            performance_mode="fast",
            context_mode="none",
            rag_enabled=False,
        )
        first = service.start_turn(
            ChatCommand(
                user_input="请记住约束 ORIGINAL_LIMIT_42，解释附件。",
                attachment_refs=[
                    {
                        "attachment_id": ready.id,
                        "content_hash": ready.content_hash,
                        "filename": ready.filename,
                    }
                ],
                **common,
            )
        )
        service.generate(first)
        second = service.start_turn(
            ChatCommand(
                user_input="保留之前约束，再加入 NEW_LIMIT_7。",
                chat_history=[
                    {"role": "user", "content": first.turn.user_message},
                    {
                        "role": "assistant",
                        "content": repo.get_chat_turn(first.turn.id).assistant_message,
                    },
                ],
                **common,
            )
        )
        service.generate(second)
    assert len(captured) == 2
    first_wire = json.dumps(captured[0]["messages"], ensure_ascii=False)
    second_wire = json.dumps(captured[1]["messages"], ensure_ascii=False)
    assert expected_material in first_wire
    assert (
        "image_url" not in first_wire
    )  # main chat receives extracted text, not pixels
    assert "ORIGINAL_LIMIT_42" in second_wire
    assert "FIRST_ANSWER_MARKER" in second_wire
    assert "NEW_LIMIT_7" in second_wire
