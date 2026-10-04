from __future__ import annotations

from dataclasses import replace
import hashlib
import json

import pytest

from src.application.chat_service import ChatCommand, answer_validation_active
from src.web.research import official_resolver as resolver
from src.web.research.candidate_funnel import candidate_funnel
from src.web.research.official_publication import publish_official_fields
from src.web.research_recovery import recover_public_research, recovery_summary
from src.web.tool_gateway import GeneralWebGateway
from tests.test_chat_service import _service


def metadata(monkeypatch, payload: bytes):
    class Response:
        headers = {}

        def __init__(self, url):
            self.url = url

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def read(self, limit):
            assert limit == 2_000_001
            return payload

    class Opener:
        def open(self, request, timeout):
            assert timeout <= 10
            return Response(request.full_url)

    monkeypatch.setattr(resolver, "build_opener", lambda *args: Opener())


@pytest.mark.parametrize("query,entity", [("FastAPI当前最新版本及发布日期", "fastapi"),
    ("SQLite最新版本变化", "sqlite"), ("Python 3.14什么时候发布", "python"),
    ("Attention Is All You Need作者及首次提交日期", "arxiv"), ("opus5.5是什么", "opus")])
def test_official_routing_accepts_original_language_without_global_search(query, entity):
    assert resolver.official_plan(query).entity == entity
    assert resolver.official_plan("FastAPI与SQLite版本比较") is None


def fastapi_payload():
    return json.dumps({"info": {"name": "fastapi", "version": "0.136.3"},
                       "urls": [{"upload_time_iso_8601": "2026-10-01T12:00:00Z"}]}).encode()


def test_native_official_success_never_calls_search_and_closes_funnel(monkeypatch):
    metadata(monkeypatch, fastapi_payload())
    gateway = GeneralWebGateway()
    monkeypatch.setattr(gateway, "search_exact", lambda *args, **kwargs: pytest.fail("official success must not search"))
    calls = recover_public_research(gateway, "FastAPI当前最新版本及发布日期")
    summary = recovery_summary(calls)
    assert calls[0]["name"] == "research_recovery"
    assert any(call["name"] == "official_resolve" for call in calls)
    assert summary["reads"] == 1
    assert not any(call["name"] == "web_search" for call in calls)
    funnel = candidate_funnel(calls, summary["candidate_dispositions"])
    assert funnel["attempted_reads"] == 1
    assert not funnel["gate_failures"]
    answer, audit = publish_official_fields("FastAPI当前最新版本及发布日期", calls, "invented features")
    assert "0.136.3" in answer and "invented features" not in answer
    assert audit["assertion_refs"] and not audit["model_prose_published"]


def test_sqlite_parser_never_copies_the_previous_release():
    payload = b'<h3>2026-10-01 (3.99.0)</h3><ol><li>Current change</li></ol><h3>2026-09-01 (3.98.0)</h3><ol><li>Old change</li></ol>'
    fields = resolver._fields("https://sqlite.org/changes.html", payload)
    assert fields["version"] == "3.99.0"
    assert fields["changes"] == "Current change"


def test_requested_sqlite_version_uses_its_own_release_record():
    plan = resolver.official_plan("SQLite 3.53.4发布变化")
    assert plan.urls == ("https://sqlite.org/releaselog/3_53_4.html",)
    fields = resolver._fields(plan.urls[0], b'<h2>SQLite Release 3.53.4 On 2026-07-24</h2><ol><li>One change</li></ol>')
    assert fields["version"] == "3.53.4" and fields["release_date"] == "2026-07-24"


def test_arxiv_metadata_does_not_guess_missing_authors():
    fields = resolver._fields("https://arxiv.org/abs/1706.03762", b'<meta name="citation_title" content="Attention Is All You Need"><meta name="citation_date" content="2017/06/12">')
    assert "authors" not in fields
    assert fields["citation_date"] == "2017/06/12"


def test_adjacent_opus_version_and_unverified_fields_are_not_publishable(monkeypatch):
    metadata(monkeypatch, fastapi_payload())
    calls = recover_public_research(GeneralWebGateway(), "FastAPI当前最新版本及发布日期")
    body = next(call["result"] for call in calls if call["name"] == "web_read")
    body["official_fields"][1]["value"] = "9.99.99"
    answer, audit = publish_official_fields("FastAPI当前最新版本及发布日期", calls, "9.99.99")
    assert "9.99.99" not in answer
    answer, audit = publish_official_fields("opus5.5是什么", calls, "Opus 5.5 is fastest")
    assert audit["status"] == "abstained"
    assert "fastest" not in answer


def test_official_gate_is_on_the_actual_chat_and_sqlite_exit(monkeypatch, tmp_path):
    metadata(monkeypatch, fastapi_payload())
    calls = recover_public_research(GeneralWebGateway(), "FastAPI当前最新版本及发布日期")
    service, repository = _service(tmp_path)
    prepared = service.start_turn(ChatCommand(user_input="FastAPI当前最新版本及发布日期", thread_id="official"))
    prepared = replace(prepared, rag={**prepared.rag, "web_tools": {"enabled": True, "calls": calls}})
    assert answer_validation_active(prepared)
    completed = service.complete_turn(prepared, "Unsupported invented feature 999")
    restored = repository.get_chat_turn(completed.id)
    assert "999" not in restored.assistant_message
    assert "0.136.3" in restored.assistant_message
    assert restored.rag_snapshot["official_field_publication"]["published_answer_sha256"] == hashlib.sha256(restored.assistant_message.encode()).hexdigest()


def test_generic_research_without_bound_claims_abstains_and_never_generates_prose(tmp_path):
    service, repository = _service(tmp_path)
    prepared = service.start_turn(ChatCommand(user_input="最近的研究结论", thread_id="generic-gate"))
    prepared = replace(prepared, route={**prepared.route, "task_contract": {"task_intent": "research"}},
                       rag={**prepared.rag, "web_tools": {"enabled": True, "calls": []}})
    service.dependencies = replace(service.dependencies, chat=lambda *args, **kwargs: pytest.fail("unbound model prose must not be generated"))
    assert list(service.stream(prepared)) == []
    answer = service.generate(prepared)
    restored = repository.get_chat_turn(prepared.turn.id)
    assert "逐事实支持" in answer
    assert restored.rag_snapshot["official_field_publication"]["status"] == "abstained"
    assert restored.rag_snapshot["official_field_publication"]["answer_generation_calls"] == 0


@pytest.mark.parametrize("action", ["interrupt_turn", "fail_turn"])
def test_interrupted_official_turn_cannot_persist_a_model_prefix(tmp_path, action):
    service, repository = _service(tmp_path)
    prepared = service.start_turn(ChatCommand(user_input="FastAPI当前最新版本及发布日期", thread_id="official-partial"))
    prepared = replace(prepared, rag={**prepared.rag, "web_tools": {"enabled": True, "calls": []}})
    result = getattr(service, action)(prepared, "Unverified model prefix")
    assert repository.get_chat_turn(result.id).assistant_message == ""


def test_partial_commit_uses_server_gate_and_cannot_inject_official_prose(tmp_path):
    service, repository = _service(tmp_path)
    prepared = service.start_turn(ChatCommand(user_input="FastAPI当前最新版本及发布日期", thread_id="partial-gate"))
    repository.update_chat_turn(prepared.turn.id, assistant_message="", status="streaming",
                                rag_snapshot={"web_tools": {"enabled": True}})
    stored, _ = service.commit_partial_turn(
        thread_id=prepared.turn.thread_id, turn_id=prepared.turn.id,
        operation_id=prepared.turn.operation_id or "", user_input="client replacement",
        assistant_message="Unverified client prose", role="auto", mode="auto", model="auto",
        route_snapshot={}, rag_snapshot={}, conversation_instruction="",
    )
    assert stored.assistant_message == ""
