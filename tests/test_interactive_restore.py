import json
from dataclasses import dataclass

import pytest

from src.interactive_restore import (
    RestoreRequest,
    STATUS_CONFLICT,
    STATUS_EXHAUSTED,
    STATUS_NOT_FOUND,
    STATUS_RESTORED,
    locate_restore_source,
    resolve_interactive_restore,
    restore_context_block,
    restore_record,
)


@dataclass
class Turn:
    id: str
    assistant_message: str
    status: str = "completed"


class Repository:
    def __init__(self, thread_id="chat_restore", turns=()):
        self.thread_id = thread_id
        self.turns = list(turns)

    def get_chat_thread(self, thread_id):
        return object() if thread_id == self.thread_id else None

    def list_chat_turns(self, thread_id):
        return self.turns if thread_id == self.thread_id else []


def block(revision=1, identifier="java-reference", html=None, title="Java 引用关系"):
    return (
        "说明\n\n```study-ui\n"
        + json.dumps(
            {
                "type": "interactive",
                "id": identifier,
                "revision": revision,
                "title": title,
                "summary": "引用共享与重新赋值实验",
                "html": html or f"<div>rv{revision}</div>" + "x" * 400,
            },
            ensure_ascii=False,
        )
        + "\n```"
    )


def three_versions():
    return [
        Turn("turn-v1", block(1)),
        Turn("turn-v2", block(2)),
        Turn("turn-v3", block(3)),
    ]


def test_restores_v1_after_v3_and_derives_the_next_revision():
    turns = three_versions()

    outcome = locate_restore_source(turns, RestoreRequest("java-reference", 1))

    assert outcome.status == STATUS_RESTORED
    assert outcome.turn_id == "turn-v1"
    assert outcome.html is not None and "rv1" in outcome.html
    assert outcome.next_revision == 4  # V1 -> V4, never a second V2
    assert "expected_new_revision: 4" in restore_context_block(outcome)


def test_the_source_is_read_from_every_saved_turn_not_the_recent_window():
    turns = [Turn("turn-old", block(1))]
    turns += [Turn(f"turn-{index}", "没有界面的回答") for index in range(30)]
    turns += [Turn("turn-new", block(31))]

    outcome = locate_restore_source(turns, RestoreRequest("java-reference", 1))

    assert outcome.status == STATUS_RESTORED
    assert outcome.turn_id == "turn-old"
    assert outcome.next_revision == 32


def test_two_different_sources_for_one_identity_are_a_conflict():
    turns = [
        Turn("turn-a", block(1, html="<div>first</div>" + "x" * 400)),
        Turn("turn-b", block(1, html="<div>second</div>" + "y" * 400)),
    ]

    outcome = locate_restore_source(turns, RestoreRequest("java-reference", 1))

    assert outcome.status == STATUS_CONFLICT
    assert outcome.html is None
    block_text = restore_context_block(outcome)
    assert "无法确定基线" in block_text
    assert "不得凭摘要" in block_text


def test_an_identical_duplicate_is_not_a_conflict():
    same = block(1)
    turns = [Turn("turn-a", same), Turn("turn-b", same)]

    outcome = locate_restore_source(turns, RestoreRequest("java-reference", 1))

    assert outcome.status == STATUS_RESTORED


def test_a_missing_version_fails_explicitly_instead_of_falling_back():
    outcome = locate_restore_source(three_versions(), RestoreRequest("java-reference", 9))

    assert outcome.status == STATUS_NOT_FOUND
    assert restore_record(outcome)["expected_new_revision"] is None
    text = restore_context_block(outcome)
    assert "必须明确告诉用户无法恢复" in text
    assert "不得凭摘要、记忆或其它版本重建" in text


def test_an_unfinished_turn_is_not_a_source():
    turns = [Turn("turn-v1", block(1), status="streaming")]

    outcome = locate_restore_source(turns, RestoreRequest("java-reference", 1))

    assert outcome.status == STATUS_NOT_FOUND


def test_another_thread_cannot_lend_its_source():
    repository = Repository(thread_id="chat_other", turns=three_versions())

    outcome = resolve_interactive_restore(
        repository, "chat_restore", RestoreRequest("java-reference", 1)
    )

    assert outcome.status == STATUS_NOT_FOUND
    assert "会话不存在或不可访问" in outcome.detail


def test_a_thread_without_saved_turns_fails_closed():
    outcome = resolve_interactive_restore(Repository(turns=[]), "chat_restore", RestoreRequest("java-reference", 1))

    assert outcome.status == STATUS_NOT_FOUND


def test_the_derived_revision_stops_at_the_protocol_ceiling():
    turns = [Turn("turn-1", block(1)), Turn("turn-999", block(999))]

    outcome = locate_restore_source(turns, RestoreRequest("java-reference", 1))

    assert outcome.status == STATUS_EXHAUSTED
    assert "无法再派生新版本" in outcome.detail


def test_the_context_block_carries_the_source_and_forbids_other_versions():
    outcome = locate_restore_source(three_versions(), RestoreRequest("java-reference", 2))

    text = restore_context_block(outcome)

    assert "component_id: java-reference" in text
    assert "base_revision: 2" in text
    assert "expected_new_revision: 4" in text
    assert "<div>rv2</div>" in text
    assert "<div>rv1</div>" not in text
    assert "<div>rv3</div>" not in text
    assert "不输出补丁" in text


def test_the_route_record_never_contains_the_source():
    outcome = locate_restore_source(three_versions(), RestoreRequest("java-reference", 1))

    record = restore_record(outcome)

    assert record["component_id"] == "java-reference"
    assert record["source_turn_id"] == "turn-v1"
    assert "html" not in record
    assert "<div>" not in json.dumps(record)


def test_the_saved_turns_are_not_rewritten():
    turns = three_versions()
    before = [(turn.id, turn.assistant_message) for turn in turns]

    locate_restore_source(turns, RestoreRequest("java-reference", 1))

    assert [(turn.id, turn.assistant_message) for turn in turns] == before


@pytest.mark.parametrize(
    "payload",
    [
        None,
        {},
        {"id": "", "revision": 1},
        {"id": "has space", "revision": 1},
        {"id": "x", "revision": 0},
        {"id": "x", "revision": 1000},
        {"id": "x", "revision": True},
        {"id": "x", "revision": "1"},
    ],
)
def test_invalid_restore_payloads_are_refused(payload):
    assert RestoreRequest.from_payload(payload) is None


def test_a_valid_restore_payload_keeps_only_identity():
    request = RestoreRequest.from_payload(
        {"id": "java-reference", "revision": 2, "html": "<script>bad</script>"}
    )

    assert request == RestoreRequest("java-reference", 2)


def test_the_http_request_maps_identity_onto_the_command():
    from src.api.models.chat import ChatRequest
    from src.api.routes.chat_routes import _chat_command

    request = ChatRequest(
        user_input="在这个版本上继续改",
        session_id="thread-a",
        interactive_restore={"id": "java-reference", "revision": 1},
    )

    command = _chat_command(request, None)

    assert command.interactive_restore == {"id": "java-reference", "revision": 1}


def test_the_http_request_rejects_a_bad_restore_identity():
    from pydantic import ValidationError

    from src.api.models.chat import ChatRequest

    with pytest.raises(ValidationError):
        ChatRequest(
            user_input="继续",
            interactive_restore={"id": "not valid id", "revision": 1},
        )
