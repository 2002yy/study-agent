from dataclasses import replace
import json
import time

import pytest

from src.web.model_driven_planning import normalize_tasks
from src.web.semantic_recovery import ResearchEpisode, ResearchSemanticSession
from tests.test_semantic_recovery import agent, Completion, ORIGINAL


def session(raw):
    return ResearchSemanticSession(
        lambda **kwargs: json.dumps(raw),
        deadline=time.monotonic() + 20,
        should_cancel=lambda: False,
    )


def episode():
    return ResearchEpisode(
        "run",
        "thread",
        "Original conditions: 2024 vs 2025; fixed budget.",
        [{"id": "rq-existing", "question": "Existing unresolved obligation"}],
        source_run_id="run",
    )


def test_natural_tasks_without_ids_are_kept_fine_grained_and_exact_dedup_has_provenance():
    tasks = [
        {"question": "Morning admission for pedestrians?"},
        {"question": "Evening admission for pedestrians?"},
        {"question": "Morning admission for pedestrians?"},
    ]
    rqs, queries, trace = normalize_tasks(
        tasks, task_id="owner", previous=[], preserve_previous=False
    )
    assert len(rqs) == 2
    assert rqs[0]["id"] != rqs[1]["id"]
    assert (
        trace["proposal_mapping"][0]["rq_id"] == trace["proposal_mapping"][2]["rq_id"]
    )
    assert len(queries) == 2
    assert (
        normalize_tasks(
            tasks[::-1], task_id="owner", previous=[], preserve_previous=False
        )[0]
        == rqs
    )


def test_search_sharing_preserves_both_rq_links_without_extra_unique_queries():
    rqs, queries, trace = normalize_tasks(
        [
            {"question": "What caused the change?", "query": "public change history"},
            {"question": "When was the change?", "query": "public change history"},
        ],
        task_id="owner",
        previous=[],
        preserve_previous=False,
    )
    assert len(rqs) == len(queries) == 2
    assert len({row["query"] for row in queries}) == 1
    assert {row["rq_id"] for row in queries} == {row["id"] for row in rqs}
    assert not trace["deferred_rq_ids"]


def test_more_tasks_than_search_proposals_are_preserved_not_silently_discarded():
    tasks = [
        {"question": f"Independent requested aspect {index}?"} for index in range(13)
    ]
    rqs, queries, trace = normalize_tasks(
        tasks, task_id="owner", previous=[], preserve_previous=False
    )
    assert len(rqs) == 13 and len(queries) == 5
    assert len(trace["deferred_rq_ids"]) == len(trace["deferred_queries"]) == 8
    assert not trace["publication_authority"]


@pytest.mark.parametrize(
    "tasks",
    [
        [{"question": "q", "id": "model-owned"}],
        [{"question": "q", "authority": "approved"}],
        [{"question": "q", "query": "file:///private"}],
        [{"question": "q", "query": "site:10.0.0.1 secrets"}],
        [{"question": "q", "query": "http://localhost/secret"}],
        [{"question": ""}],
        [],
        [{"question": str(i)} for i in range(25)],
    ],
)
def test_invalid_or_privileged_proposals_cannot_be_adapted_into_tasks(tasks):
    with pytest.raises(ValueError):
        normalize_tasks(tasks, task_id="owner", previous=[], preserve_previous=False)


def test_owner_isolation_and_continuation_preserve_original_ids_and_conditions():
    prior = episode()
    planner = session(
        {
            "intent": "REFINE_RESEARCH",
            "tasks": [{"question": "A new narrower follow-up?"}],
        }
    )
    decision = planner.plan(
        prior, "Refine the original", new_task_id="new-run", active_task_exists=True
    )
    assert prior.questions[0] in decision.unresolved_questions
    assert prior.original_question.endswith("fixed budget.")
    trace = planner.events[0]["planning"]
    assert trace["owner_task_id"] == prior.task_id
    rqs, _, _ = normalize_tasks(
        [{"question": "Same question?"}],
        task_id="other",
        previous=[],
        preserve_previous=False,
    )
    changed, _, _ = normalize_tasks(
        [{"question": "Same question?"}],
        task_id="owner",
        previous=[],
        preserve_previous=False,
    )
    assert rqs[0]["id"] != changed[0]["id"]


def test_legacy_episode_and_new_larger_episode_round_trip_without_reassigning_ids():
    prior = episode()
    assert ResearchEpisode.parse(prior.to_dict(), thread_id="thread") == prior
    rqs, _, _ = normalize_tasks(
        [{"question": f"Aspect {i}?"} for i in range(13)],
        task_id="run",
        previous=[],
        preserve_previous=False,
    )
    updated = replace(prior, questions=rqs)
    assert ResearchEpisode.parse(updated.to_dict(), thread_id="thread").questions == rqs


def test_planner_uses_one_call_and_records_original_raw_proposals():
    raw = {
        "tasks": [{"question": "A mechanism not literally written in the original?"}]
    }
    planner = session(raw)
    result = planner.plan(
        episode(),
        "Compare technologies under the original conditions",
        new_task_id="fresh",
        active_task_exists=False,
    )
    assert len(planner.events) == 1
    assert json.loads(planner.events[0]["raw_output"]) == raw
    assert result.unresolved_questions[0]["id"].startswith("rq-")
    assert result.unresolved_questions[0]["question"] == raw["tasks"][0]["question"]


def test_retry_without_original_episode_is_not_new_research():
    with pytest.raises(ValueError, match="retry_without_active_episode"):
        session({"tasks": [{"question": "Unrelated invented topic?"}]}).plan(
            episode(), "再查查", new_task_id="fresh", active_task_exists=False
        )


@pytest.mark.parametrize("remaining, expected", [(60, 20), (2, 2)])
def test_planning_window_is_bounded_by_remaining_research_deadline(remaining, expected):
    observed = []

    def completion(**kwargs):
        observed.append(kwargs["timeout"])
        return json.dumps({"tasks": [{"question": "A bounded natural question?"}]})

    planner = ResearchSemanticSession(
        completion, deadline=time.monotonic() + remaining, should_cancel=lambda: False
    )
    planner.plan(
        episode(), "New question", new_task_id="fresh", active_task_exists=False
    )
    assert expected - 0.5 < observed[0] <= expected


@pytest.mark.parametrize(
    "purpose, cap",
    [
        ("research_task_planning", 2800),
        ("research_turn_interpretation", 1400),
        ("research_body_relevance", 1400),
    ],
)
def test_only_b_planning_uses_the_authorized_larger_output_cap(
    monkeypatch, purpose, cap
):
    from src.web.semantic_recovery import configured_completion
    import src.llm_client as client

    calls = []
    monkeypatch.setattr(
        client, "research_structured_output_capabilities", lambda: ("json_object", None)
    )
    monkeypatch.setattr(
        client, "chat", lambda *args, **kwargs: calls.append(kwargs) or "{}"
    )
    configured_completion(messages=[], timeout=2, task_name=purpose)
    assert calls[0]["max_tokens"] == cap
    assert calls[0]["timeout"] == 2
    assert calls[0]["request_max_retries"] == 0


def test_runtime_does_not_invoke_legacy_planner_and_new_process_restores_ids(
    tmp_path, monkeypatch
):
    def forbidden(*args, **kwargs):
        raise AssertionError("legacy interpreter invoked")

    monkeypatch.setattr(ResearchSemanticSession, "interpret", forbidden)
    runtime, service, _, model = agent(tmp_path)
    trace = runtime.resolve(ORIGINAL, owner_thread_id="thread-1", history_allowed=True)
    assert trace.to_dict()["semantics"]["decision_admitted"]
    before = service.active_semantic_episode("thread-1")
    restored_runtime, restored_service, _, _ = agent(tmp_path, completion=Completion())
    assert (
        restored_service.active_semantic_episode("thread-1").questions
        == before.questions
    )
    next_trace = restored_runtime.resolve(
        "再查查", owner_thread_id="thread-1", history_allowed=True
    )
    assert next_trace.to_dict()["semantics"]["decision_admitted"]
    assert (
        restored_service.active_semantic_episode("thread-1").questions
        == before.questions
    )
    assert [purpose for purpose, _ in model.inputs].count("research_task_planning") == 1


def test_actual_planning_time_is_credited_once_without_more_search_read_budget(
    tmp_path, monkeypatch
):
    import src.tools.persistent_web_agent as runtime_module
    from src.web.research_recovery import recovery_budget

    captured = []

    def recovery(gateway, query, **kwargs):
        captured.append(kwargs)
        return []

    monkeypatch.setattr(runtime_module, "recover_public_research", recovery)
    runtime, _, _, _ = agent(tmp_path)
    trace = runtime.resolve(ORIGINAL, owner_thread_id="thread-1", history_allowed=True)
    info = trace.to_dict()["semantics"]["time_budget"]
    base = recovery_budget(ORIGINAL)
    assert captured[0]["budget"] == base
    assert 0 <= info["credited_seconds"] <= 20
    assert info["credited_seconds"] == min(20, info["planning_elapsed_seconds"])
    assert info["total_hard_seconds"] == base.hard_seconds + 20
    assert captured[0]["started_at"] == info["research_started"]
    assert captured[0]["answer_deadline"] == trace.answer_deadline
    assert trace.answer_deadline <= info["research_started"] + base.hard_seconds
