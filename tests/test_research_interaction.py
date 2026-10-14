"""Process display and actual, non-cancelling mid-run input regression tests."""

from types import SimpleNamespace

import pytest

from src.web.research.research_interaction import interaction_event, steering_supported


def run(**overrides):
    values = dict(
        id="run1",
        status="running",
        stage="reading",
        research_context={},
        query_attempts=[{}],
        selected_sources=[{}],
    )
    return SimpleNamespace(**(values | overrides))


def test_only_consuming_executors_advertise_steering():
    assert not steering_supported({"research_mode": "standard"})
    assert steering_supported({"research_mode": "deep"})
    assert steering_supported({"claim_engine": {"mode": "active"}})


def test_receipts_distinguish_waiting_applied_and_terminal_unapplied():
    context = {
        "research_mode": "deep",
        "deep": {
            "steering": [
                {"id": "s1", "content": "new condition", "incorporated_in_round": None},
                {
                    "id": "s2",
                    "content": "other",
                    "incorporated_in_round": 2,
                    "executed_in_round": 2,
                },
            ]
        },
    }
    projected = interaction_event(run(research_context=context))
    assert [item["status"] for item in projected["steering"]] == [
        "pending",
        "executing",
    ]
    terminal = interaction_event(run(research_context=context, status="partial"))
    assert [item["status"] for item in terminal["steering"]] == ["late", "applied"]


def test_narration_ids_survive_repeated_polling_and_never_declare_support():
    projected = interaction_event(run())
    assert interaction_event(run()) == projected
    assert "读取成功仍不代表" in projected["narration"][-1]["text"]
    assert "source_block" not in projected
    assert "evidence" not in projected


def test_durable_deep_steps_are_bounded_and_preserved():
    context = {
        "deep": {"steps": [{"at": str(i), "text": f"step {i}"} for i in range(30)]}
    }
    result = interaction_event(run(research_context=context))
    assert len(result["narration"]) == 12
    assert any(item["text"] == "step 29" for item in result["narration"])


def test_ordinary_run_cannot_accept_an_unconsumable_queue(tmp_path):
    from src.application.web_lookup_service import WebLookupService
    from src.infrastructure.sqlite.database import RuntimeDatabase
    from src.repositories.web_lookup_repository import WebLookupRepository

    service = WebLookupService(
        WebLookupRepository(RuntimeDatabase(tmp_path / "runtime.db")), object()
    )
    created = service.create("a query")
    with pytest.raises(ValueError, match="does not support"):
        service.steer(created.id, content="extra condition")
    assert "deep" not in service.get(created.id).research_context


def test_queue_survives_a_stale_checkpoint_and_is_idempotent(tmp_path):
    from src.application.web_lookup_service import WebLookupService
    from src.infrastructure.sqlite.database import RuntimeDatabase
    from src.repositories.web_lookup_repository import WebLookupRepository

    repository = WebLookupRepository(RuntimeDatabase(tmp_path / "runtime.db"))
    service = WebLookupService(repository, object())
    created = service.create("first task", owner_thread_id="thread1")
    operation = service.begin_tool_trace(created.id)
    stale = service.get(created.id)
    repository.queue_followup(created.id, content="second task", request_id="queue1")
    repository.queue_followup(created.id, content="second task", request_id="queue1")
    repository.checkpoint(
        created.id,
        operation_id=operation,
        research_context=stale.research_context,
        query_attempts=[],
        selected_sources=[],
        rejected_sources=[],
        items=[],
        warnings=[],
    )
    pending = repository.pending_followups("thread1")
    assert len(pending) == 1
    assert pending[0]["content"] == "second task"
    assert repository.pending_followups("other_thread") == []
    with pytest.raises(ValueError, match="matching turn"):
        repository.complete_followup(created.id, request_id="queue1", turn_id="missing")


def test_unconfirmed_queue_delivery_is_not_reexecuted_after_restore(tmp_path):
    from src.application.web_lookup_service import WebLookupService
    from src.infrastructure.sqlite.database import RuntimeDatabase
    from src.repositories.web_lookup_repository import WebLookupRepository

    database = RuntimeDatabase(tmp_path / "runtime.db")
    repository = WebLookupRepository(database)
    service = WebLookupService(repository, object())
    created = service.create("first task", owner_thread_id="thread1")
    repository.queue_followup(created.id, content="second task", request_id="queue1")
    with database.connect() as connection:
        connection.execute(
            "INSERT INTO chat_threads(id, status, created_at, updated_at) VALUES ('thread1','active','now','now')"
        )
        connection.execute(
            "INSERT INTO chat_turns(id, thread_id, user_message, status, created_at, updated_at) VALUES ('turn_queue1','thread1','second task','completed','now','now')"
        )
    assert repository.pending_followups("thread1") == []
    finished = repository.complete_followup(
        created.id, request_id="queue1", turn_id="turn_queue1"
    )
    assert finished.research_context["conversation_queue"][0]["status"] == "completed"


def test_user_task_requirements_reach_synthesis_without_becoming_evidence():
    from src.web.research.research_interaction import steering_answer_instruction
    from src.web.tool_evidence import evidence_tool_calls

    calls = [
        {
            "name": "research_steering",
            "result": {
                "authority": "user_task_requirements_not_evidence",
                "effective_query": "RTX 5060",
                "entries": [{"content": "不是 4060，是 5060", "executed": False}],
            },
        }
    ]
    instruction = steering_answer_instruction(calls, "original instruction")
    assert "original instruction" in instruction
    assert "RTX 5060" in instruction
    assert "本轮未执行" in instruction
    assert evidence_tool_calls(calls) == []


def test_source_scope_and_compute_are_not_silently_treated_as_keywords():
    from src.web.research.steering_plan import steering_intent

    for message in [
        "只看官方资料",
        "用 Python 重算",
        "停止研究",
        "回答完再给我一个表格",
    ]:
        with pytest.raises(ValueError):
            steering_intent(message)
    assert steering_intent("刚才是 5060，不是 4060") == {
        "kind": "correction",
        "old": "4060",
        "new": "5060",
    }


def test_steering_request_retries_do_not_duplicate_work_or_accept_other_content(tmp_path):
    from src.application.web_lookup_service import WebLookupService
    from src.infrastructure.sqlite.database import RuntimeDatabase
    from src.repositories.web_lookup_repository import WebLookupRepository

    service = WebLookupService(WebLookupRepository(RuntimeDatabase(tmp_path / "runtime.db")), object())
    created = service.create("a query", research_mode="deep")
    first = service.steer(created.id, content="add a comparison", request_id="request1")
    repeated = service.steer(created.id, content="add a comparison", request_id="request1")
    assert repeated.research_context["deep"]["steering"] == first.research_context["deep"]["steering"]
    with pytest.raises(ValueError, match="another message"):
        service.steer(created.id, content="different", request_id="request1")
    service.cancel(created.id)
    with pytest.raises(ValueError):
        service.steer(created.id, content="late input", request_id="request2")
