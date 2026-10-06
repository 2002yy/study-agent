"""Saved-parent admission and reuse controls; no automatic Standard agent loop."""

from dataclasses import replace
from datetime import datetime, timedelta

import pytest

from src.application.chat_service import ChatCommand
from src.application.standard_handoff import admit_standard_handoff
from src.domain.runtime_entities import WebLookupRun
from src.repositories.web_lookup_repository import WebLookupRepository
from tests.test_chat_service import _service
from tests.test_lookup_terminal import QUERY, deterministic_trace


@pytest.fixture
def saved_parent(tmp_path):
    service, repository = _service(tmp_path)
    runs = WebLookupRepository(repository.database)

    service.dependencies = replace(
        service.dependencies,
        resolve_web_tools=lambda *_a, **_k: deterministic_trace(),
        chat=lambda *_a, **_k: pytest.fail("no answer model"),
    )
    prepared = service.start_turn(
        ChatCommand(user_input=QUERY, thread_id="standard-parent")
    )
    service.generate(prepared)
    parent = repository.get_chat_turn(prepared.turn.id)
    runs.create(
        WebLookupRun(
            id="source-run",
            query=QUERY,
            status="completed",
            owner_thread_id=parent.thread_id,
            research_context={
                "owner": {"thread_id": parent.thread_id, "turn_id": parent.id}
            },
        )
    )
    created = datetime.fromisoformat(parent.created_at)
    return repository, runs, parent, created


def admit(saved_parent, **kwargs):
    repository, runs, parent, created = saved_parent
    return admit_standard_handoff(
        repository,
        runs,
        parent_turn_id=parent.id,
        thread_id=kwargs.get("thread_id", parent.thread_id),
        overall_deadline=kwargs.get("deadline", created + timedelta(seconds=90)),
        now=kwargs.get("now", created + timedelta(seconds=3)),
    )


class Gateway:
    def __init__(self):
        self.reads = self.queries = 0

    def read(self, url, **_kwargs):
        self.reads += 1
        return {"ok": True, "url": url, "content": "new body; no support authority"}

    def search_exact(self, query, **_kwargs):
        self.queries += 1
        return {"status": "ok", "results": []}


def test_real_saved_handoff_reuses_source_without_new_dispatch_or_charge(saved_parent):
    context = admit(saved_parent)
    gateway = Gateway()
    source = context.handoff["usable_sources"][0]
    url = source["arguments"]["url"]
    body = context.read(gateway, url, now=context.admitted_at)
    body["content"] = "mutated copy"
    again = context.read(gateway, url, now=context.admitted_at)
    assert again == source["result"]
    assert context.new_reads == gateway.reads == 0 and context.reused_reads == 2
    assert context.handoff["publication_authority"] is False
    query = next(
        call["arguments"]["query"]
        for call in context.handoff["attempted"]
        if call["name"] == "web_search"
    )
    context.search(gateway, query, now=context.admitted_at)
    assert context.new_queries == gateway.queries == 0


@pytest.mark.parametrize("kind", ["reads", "queries"])
def test_new_work_is_bounded_and_repeated_work_is_cached(saved_parent, kind):
    context = admit(saved_parent)
    gateway = Gateway()
    limit = 5 if kind == "reads" else 4
    method = context.read if kind == "reads" else context.search
    for index in range(limit):
        target = (
            f"https://example.com/source/{index}"
            if kind == "reads"
            else f"gap query {index}"
        )
        method(gateway, target, now=context.admitted_at)
        method(gateway, target, now=context.admitted_at)
    with pytest.raises(ValueError, match="budget exhausted"):
        method(gateway, "new uncached work", now=context.admitted_at)
    assert getattr(gateway, kind) == limit


@pytest.mark.parametrize(
    "failure", ["thread", "deadline_reset", "expired", "clock_rewind"]
)
def test_wrong_owner_or_clock_is_rejected(saved_parent, failure):
    _, _, _, created = saved_parent
    kwargs = (
        {"thread_id": "another-thread"}
        if failure == "thread"
        else {"deadline": created + timedelta(seconds=91)}
        if failure == "deadline_reset"
        else {"now": created + timedelta(seconds=91)}
        if failure == "expired"
        else {"now": created - timedelta(seconds=1)}
    )
    with pytest.raises(ValueError):
        admit(saved_parent, **kwargs)


@pytest.mark.parametrize("cancelled", [True, False])
def test_cancel_and_deadline_prevent_even_cached_dispatch(saved_parent, cancelled):
    context = admit(saved_parent)
    gateway = Gateway()
    url = context.handoff["usable_sources"][0]["arguments"]["url"]
    now = context.admitted_at if cancelled else context.deadline
    with pytest.raises(ValueError):
        context.read(gateway, url, now=now, cancelled=cancelled)
    assert gateway.reads == context.new_reads == context.reused_reads == 0


@pytest.mark.parametrize(
    "failure", ["missing", "thread", "turn", "cancelled", "running", "query"]
)
def test_source_run_requires_matching_durable_owner(saved_parent, monkeypatch, failure):
    _, runs, _, _ = saved_parent
    source = runs.get("source-run")
    changes = {
        "thread": {"owner_thread_id": "unrelated-thread"},
        "turn": {
            "research_context": {
                "owner": {"thread_id": "standard-parent", "turn_id": "wrong-turn"}
            }
        },
        "cancelled": {"cancel_requested_at": source.created_at},
        "running": {"status": "running"},
        "query": {"query": "unrelated query"},
    }
    candidate = None if failure == "missing" else replace(source, **changes[failure])
    monkeypatch.setattr(runs, "get", lambda _id: candidate)
    with pytest.raises(ValueError, match="source run"):
        admit(saved_parent)


@pytest.mark.parametrize("failure", ["digest", "terminal", "cancelled", "owner"])
def test_saved_parent_admission_fails_closed(saved_parent, failure):
    from copy import deepcopy

    repository, _, parent, _ = saved_parent
    snapshot = deepcopy(parent.rag_snapshot)
    if failure == "digest":
        snapshot["lookup_terminal"]["handoff"]["query"] = "tampered"
    elif failure == "terminal":
        snapshot["lookup_terminal"]["state"] = "VERIFIED"
    elif failure == "owner":
        snapshot["lookup_terminal"]["owner"]["turn_id"] = "wrong-parent"
    else:
        repository.upsert_chat_turn(replace(parent, status="pending"))
        outcome, _ = repository.request_turn_cancel(
            parent.id, expected_operation_id=parent.operation_id
        )
        assert outcome == "accepted"
    repository.upsert_chat_turn(replace(parent, rag_snapshot=snapshot))
    with pytest.raises(ValueError):
        admit(saved_parent)


@pytest.mark.parametrize("kind", ["reads", "queries"])
def test_failed_dispatch_still_consumes_new_budget(saved_parent, kind):
    context = admit(saved_parent)

    class FailedGateway:
        def read(self, *_args, **_kwargs):
            raise OSError("offline")

        search_exact = read

    method = context.read if kind == "reads" else context.search
    limit = 5 if kind == "reads" else 4
    for _ in range(limit):
        with pytest.raises(OSError):
            method(FailedGateway(), "same failed target", now=context.admitted_at)
    with pytest.raises(ValueError, match="budget exhausted"):
        method(FailedGateway(), "same failed target", now=context.admitted_at)
    assert getattr(context, "new_" + kind) == limit


@pytest.mark.parametrize("clock", ["deadline", "now"])
def test_naive_clock_is_not_an_admission_authority(saved_parent, clock):
    _, _, _, created = saved_parent
    with pytest.raises(ValueError, match="clock"):
        admit(saved_parent, **{clock: created.replace(tzinfo=None)})
