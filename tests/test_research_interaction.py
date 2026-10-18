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


def test_incorporated_but_unexecuted_receipt_is_applied_not_late_or_executing():
    context = {
        "research_mode": "deep",
        "deep": {
            "steering": [
                {"id": "s1", "content": "new scope", "incorporated_in_round": 2, "executed_in_round": None},
            ]
        },
    }
    # Entered the authoritative plan but never ran: applied, never "executing".
    assert [item["status"] for item in interaction_event(run(research_context=context))["steering"]] == ["applied"]
    terminal = interaction_event(run(research_context=context, status="partial"))
    assert [item["status"] for item in terminal["steering"]] == ["applied"]


def deep_read_run(**overrides):
    """One successful read whose note is attributed to a plan question."""
    question = "compare；新增研究目标：再考虑 Agent 自动编辑"
    excerpt = "该工具的脚本接口支持批量重命名图层、导出 PNG，并保留 PSD 图层样式。"
    record = {
        "assessment": {"url": "https://example.org/automation", "worth_reading": True},
        "item": {"url": "https://example.org/automation"},
        "read": {
            "status": "read",
            "ok": "true",
            "url": "https://example.org/automation",
            "requested_url": "https://example.org/automation",
            "content": excerpt,
        },
    }
    deep = {
        "steering": [
            {"id": "s1", "content": "再考虑 Agent 自动编辑", "incorporated_in_round": 2,
             "executed_in_round": 2, "task_id": "steer_s1", "kind": "addition"},
        ],
        "plan": [
            {"task_id": "steer_s1", "sub_question": question, "status": "done", "round": 2,
             "steering_ids": ["s1"]},
            {"task_id": "superseded", "sub_question": "old question", "status": "superseded",
             "steering_ids": ["s1"]},
        ],
        "notes": [{"url": "https://example.org/automation", "title": "自动化接口文档",
                   "facts": excerpt, "sub_question": question}],
    }
    return run(
        research_context={"research_mode": "deep", "deep": deep},
        selected_sources=[record],
        **overrides,
    )


def test_supplement_receipt_shows_the_questions_it_added_and_the_sources_read():
    projected = interaction_event(deep_read_run())
    receipt = projected["steering"][0]
    assert receipt["status"] == "executing"
    # Only the target the supplement added, never a restatement of the question.
    assert receipt["effects"]["questions"] == [{"text": "再考虑 Agent 自动编辑", "created": True}]
    assert receipt["effects"]["sources"] == [
        {"title": "自动化接口文档", "url": "https://example.org/automation"}
    ]


def test_a_plan_task_that_predates_the_supplement_is_never_called_new():
    """Only the creator of a task (steering_ids[0]) may read as a new check."""
    question = "compare；新增研究目标：再考虑 Agent 自动编辑"
    excerpt = "该工具的脚本接口支持批量重命名图层、导出 PNG，并保留 PSD 图层样式。"
    deep = {
        "steering": [{"id": "s2", "content": "再考虑 Agent 自动编辑",
                      "incorporated_in_round": 3, "executed_in_round": 3}],
        "plan": [{"task_id": "steer_s1", "sub_question": question, "status": "done", "round": 2,
                  "steering_ids": ["s1", "s2"]}],
        "notes": [{"url": "https://example.org/automation", "title": "自动化接口文档",
                   "facts": excerpt, "sub_question": question}],
    }
    record = {
        "assessment": {"url": "https://example.org/automation", "worth_reading": True},
        "item": {"url": "https://example.org/automation"},
        "read": {"status": "read", "ok": "true", "url": "https://example.org/automation",
                 "requested_url": "https://example.org/automation", "content": excerpt},
    }
    receipt = interaction_event(run(
        research_context={"research_mode": "deep", "deep": deep},
        selected_sources=[record],
    ))["steering"][0]
    # Shared with a pre-existing check: the full question, and no novelty claim.
    assert receipt["effects"]["questions"] == [{"text": question, "created": False}]
    assert receipt["effects"]["sources"] == [
        {"title": "自动化接口文档", "url": "https://example.org/automation"}
    ]


def test_a_correction_appended_to_an_existing_task_is_not_a_new_check():
    deep = {
        "steering": [{"id": "s2", "content": "不是 A 是 B", "kind": "correction",
                      "incorporated_in_round": 3, "executed_in_round": 3}],
        "plan": [{"task_id": "t1", "sub_question": "B 的兼容范围", "status": "done", "round": 2,
                  "steering_ids": ["s1", "s2"]}],
    }
    receipt = interaction_event(run(research_context={"research_mode": "deep", "deep": deep}))["steering"][0]
    assert receipt["effects"]["questions"] == [{"text": "B 的兼容范围", "created": False}]


def test_supplement_that_never_reached_the_plan_has_no_effects_field():
    context = {
        "research_mode": "deep",
        "deep": {"steering": [{"id": "s1", "content": "new condition",
                               "incorporated_in_round": None}]},
    }
    receipt = interaction_event(run(research_context=context))["steering"][0]
    # An empty projection is the honest answer; no placeholder question is invented.
    assert "effects" not in receipt


def test_effects_stay_bounded_and_skip_superseded_or_unread_material():
    long_question = "q" * 300
    deep = {
        "steering": [{"id": "s1", "content": "c", "incorporated_in_round": 2, "executed_in_round": 2}],
        "plan": [
            {"task_id": f"t{i}", "sub_question": f"question-{i}-{long_question}", "status": "done",
             "steering_ids": ["s1"]}
            for i in range(4)
        ],
    }
    projected = interaction_event(run(research_context={"research_mode": "deep", "deep": deep}))
    effects = projected["steering"][0]["effects"]
    assert len(effects["questions"]) == 2
    assert effects["questions"][0]["text"].startswith("question-0-")
    assert all(item["created"] is True for item in effects["questions"])
    assert all(len(item["text"]) <= 160 for item in effects["questions"])
    # No successful read backs any of these questions, so no source is claimed.
    assert effects["sources"] == []
    # Two plan tasks truncated to the same text are one question, not two.
    duplicate = {"steering": deep["steering"],
                 "plan": [{"task_id": "a", "sub_question": long_question, "status": "done",
                           "steering_ids": ["s1"]},
                          {"task_id": "b", "sub_question": long_question + "x", "status": "done",
                           "steering_ids": ["s1"]}]}
    assert len(interaction_event(run(research_context={"research_mode": "deep",
                                                      "deep": duplicate}))["steering"][0]["effects"]["questions"]) == 1


def test_effects_never_grant_evidence_or_answer_authority():
    projected = interaction_event(deep_read_run())
    receipt = projected["steering"][0]
    assert set(receipt["effects"]) == {"questions", "sources"}
    assert set(receipt["effects"]["questions"][0]) == {"text", "created"}
    assert set(receipt["effects"]["sources"][0]) == {"title", "url"}
    assert "evidence" not in projected
    assert "support" not in str(projected["steering"])


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
    # A configuration-driven recompute is a legal supplement target now that the
    # bounded compute tools exist; arbitrary code stays refused.
    assert steering_intent("按新配置重算") == {"kind": "recompute"}


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
