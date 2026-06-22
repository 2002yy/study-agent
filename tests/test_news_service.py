from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

import pytest

from src.application.news_service import NewsDependencies


def test_news_run_pipeline_persists_server_owned_stage_data(runtime_test_context):
    service = runtime_test_context.news_service
    service.dependencies = NewsDependencies(
        search=lambda query, max_items: [{"title": query, "rank": max_items}],
        enrich=lambda items, **kwargs: [{**items[0], "article_text": "full"}],
        digest=lambda items, **kwargs: (
            "digest",
            "source block",
            {"total": len(items)},
            ["warning"],
        ),
        discuss=lambda digest, **kwargs: (
            "【纳西妲】\nA\n\n【三月七】\nB\n\n【刻晴】\nC\n\n【流萤】\nD",
            "ignored",
        ),
        load_runtime_modes=lambda: SimpleNamespace(
            profile=SimpleNamespace(
                safe_mode=False,
                allow_article_network_read=True,
                article_network_read_reason="",
            )
        ),
    )

    created = service.create("AI")
    searched = service.search(created.id, max_items=5)
    enriched = service.enrich(
        searched.id,
        max_articles=3,
        max_chars_per_article=5000,
        safe_mode=False,
    )
    digested = service.digest(
        searched.id, performance_mode="fast", selected_model="flash"
    )
    discussed = service.discuss(
        searched.id,
        group_thread_id=None,
        interaction_mode="standard",
        performance_mode="fast",
        selected_model="flash",
    )

    assert searched.id.startswith("news_")
    assert enriched.stage == "enriched" and enriched.items[0]["article_text"] == "full"
    assert digested.stage == "digested" and digested.source_block == "source block"
    assert discussed.stage == "discussed" and discussed.status == "completed"
    assert discussed.group_thread_id
    messages = runtime_test_context.group_repository.list_messages(
        discussed.group_thread_id
    )
    assert [message.message_type for message in messages] == [
        "news_source",
        "news_discussion",
        "news_discussion",
        "news_discussion",
        "news_discussion",
    ]


def test_failed_news_stage_can_retry_from_same_stage(runtime_test_context):
    service = runtime_test_context.news_service
    service.dependencies = replace(
        service.dependencies,
        search=lambda query, max_items: [{"title": query}],
    )
    created = service.create("retry")
    searched = service.search(created.id, max_items=2)

    def fail_digest(*args, **kwargs):
        raise RuntimeError("provider down")

    service.dependencies = replace(service.dependencies, digest=fail_digest)
    with pytest.raises(RuntimeError, match="provider down"):
        service.digest(searched.id, performance_mode="fast", selected_model="flash")
    failed = service.get(searched.id)
    assert failed.stage == "searched"
    assert failed.status == "failed"
    assert failed.active_operation_id is None

    service.dependencies = replace(
        service.dependencies,
        digest=lambda items, **kwargs: ("retry digest", "source", {}, []),
    )
    retried = service.digest(
        searched.id, performance_mode="fast", selected_model="flash"
    )
    assert retried.stage == "digested"
    assert retried.error == ""


def test_failed_search_keeps_created_run_id_and_can_retry(runtime_test_context):
    service = runtime_test_context.news_service
    created = service.create("retry search")
    service.dependencies = replace(
        service.dependencies,
        search=lambda query, max_items: (_ for _ in ()).throw(
            RuntimeError("search provider down")
        ),
    )

    with pytest.raises(RuntimeError, match="search provider down"):
        service.search(created.id, max_items=2)

    failed = service.get(created.id)
    assert failed.stage == "created"
    assert failed.status == "failed"
    assert failed.active_operation_id is None

    service.dependencies = replace(
        service.dependencies,
        search=lambda query, max_items: [{"title": query, "rank": max_items}],
    )
    retried = service.search(created.id, max_items=3)
    assert retried.id == created.id
    assert retried.stage == "searched"
    assert retried.items == [{"title": "retry search", "rank": 3}]


def test_safe_mode_skip_is_persisted_on_news_run(runtime_test_context):
    service = runtime_test_context.news_service
    service.dependencies = replace(
        service.dependencies,
        search=lambda query, max_items: [{"title": query}],
    )
    created = service.create("safe")
    searched = service.search(created.id, max_items=2)

    skipped = service.enrich(
        searched.id,
        max_articles=6,
        max_chars_per_article=5000,
        safe_mode=True,
    )

    assert skipped.stage == "enrich_skipped"
    assert skipped.safe_mode is True
    assert skipped.warnings[-1] == "safe_mode"


def test_group_news_bundle_rolls_back_source_when_discussion_insert_fails(
    runtime_test_context, monkeypatch
):
    repository = runtime_test_context.group_repository
    service = runtime_test_context.group_service
    thread = service.create_thread(title="Atomic News")
    original = repository._insert_message
    calls = 0

    def fail_second(connection, message):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("simulated insert failure")
        return original(connection, message)

    monkeypatch.setattr(repository, "_insert_message", fail_second)
    with pytest.raises(OSError, match="simulated insert failure"):
        service.append_news_bundle(
            thread_id=thread.id,
            source_block="source",
            discussion="【纳西妲】\nreply",
            news_run_id="news-atomic",
        )

    assert repository.list_messages(thread.id) == []
    assert repository.get_thread(thread.id).active_operation_id is None


def test_group_news_bundle_is_idempotent_by_news_run(runtime_test_context):
    service = runtime_test_context.group_service
    thread = service.create_thread(title="Idempotent News")

    for _ in range(2):
        service.append_news_bundle(
            thread_id=thread.id,
            source_block="source",
            discussion="【纳西妲】\nreply",
            news_run_id="news-idempotent",
        )

    messages = runtime_test_context.group_repository.list_messages(thread.id)
    assert [message.content for message in messages] == ["source", "reply"]
    assert runtime_test_context.group_repository.get_thread(thread.id).unread_count == 1

    another = service.create_thread(title="Another")
    with pytest.raises(ValueError, match="another Group thread"):
        service.append_news_bundle(
            thread_id=another.id,
            source_block="source",
            discussion="【纳西妲】\nreply",
            news_run_id="news-idempotent",
        )


def test_news_discuss_retry_uses_reserved_group_after_completion_crash(
    runtime_test_context, monkeypatch
):
    service = runtime_test_context.news_service
    service.dependencies = replace(
        service.dependencies,
        search=lambda query, max_items: [{"title": query}],
        digest=lambda items, **kwargs: ("digest", "source", {}, []),
        discuss=lambda digest, **kwargs: ("【纳西妲】\nreply", "ignored"),
    )
    created = service.create("reserved target")
    searched = service.search(created.id, max_items=1)
    service.digest(searched.id, performance_mode="fast", selected_model="flash")
    target = runtime_test_context.group_service.create_thread(title="Reserved")
    repository = runtime_test_context.news_repository
    original_complete = repository.complete_operation
    crashed = False

    def crash_before_news_completion(*args, **kwargs):
        nonlocal crashed
        if kwargs.get("stage") == "discussed" and not crashed:
            crashed = True
            raise RuntimeError("crash after Group commit")
        return original_complete(*args, **kwargs)

    monkeypatch.setattr(repository, "complete_operation", crash_before_news_completion)
    with pytest.raises(RuntimeError, match="crash after Group commit"):
        service.discuss(
            searched.id,
            group_thread_id=target.id,
            interaction_mode="standard",
            performance_mode="fast",
            selected_model="flash",
        )

    failed = service.get(searched.id)
    assert failed.stage == "digested"
    assert failed.group_thread_id == target.id

    retried = service.discuss(
        searched.id,
        group_thread_id=None,
        interaction_mode="standard",
        performance_mode="fast",
        selected_model="flash",
    )
    assert retried.group_thread_id == target.id
    messages = runtime_test_context.group_repository.list_messages(target.id)
    assert [message.content for message in messages] == ["source", "reply"]
