"""Frozen Lookup controls: strategy and publication, not new site parsing."""
from dataclasses import replace
import hashlib

import pytest

from src.application.chat_service import ChatCommand
from src.news import article_fetcher
from src.web.research_recovery import LOOKUP_BUDGET, recover_public_research, recovery_summary
from src.web.tool_gateway import GeneralWebGateway
from tests.test_chat_service import _service
from tests.test_official_source_quality import fastapi_payload, metadata
from tests.test_opus_version_binding import INTRO, payload
from tests.test_research_recovery import Gateway, item


POSITIVES = [
    ("fastapi", "FastAPI当前最新版本及发布日期", fastapi_payload(), {"version", "distribution_uploaded_at"}),
    ("sqlite", "SQLite 3.53.4发布变化", b'<h2>SQLite Release 3.53.4 On 2026-07-24</h2><ol><li>Target change</li></ol>', {"version", "changes"}),
    ("arxiv", "Attention Is All You Need作者及首次提交日期", b'<meta name="citation_title" content="Attention Is All You Need"><meta name="citation_arxiv_id" content="1706.03762"><meta name="citation_author" content="Source Author"><div class="submission-history">[v1] Mon, 12 Jun 2017 17:57:34 UTC</div>', {"authors", "first_submission"}),
    ("python", "Python 3.14什么时候发布", b'<h1>Python 3.14.0</h1><p>Release date: Oct. 7, 2025</p>', {"version", "release_date"}),
    ("opus", "Opus 5.5是什么", payload(), {"version", "official_positioning"}),
]


def saved_exit(tmp_path, query, calls):
    service, repository = _service(tmp_path)
    service.dependencies = replace(service.dependencies, chat=lambda *_a, **_k: pytest.fail("deterministic publication must not generate prose"))
    prepared = service.start_turn(ChatCommand(user_input=query, thread_id="lookup-qualification"))
    prepared = replace(prepared, route={**prepared.route, "task_contract": {"task_intent": "research"}},
                       rag={**prepared.rag, "web_tools": {"enabled": True, "calls": calls}})
    service.generate(prepared)
    saved = repository.get_chat_turn(prepared.turn.id)
    audit = saved.rag_snapshot["official_field_publication"]
    assert audit["answer_generation_calls"] == 0
    assert not audit["model_prose_published"]
    assert audit["published_answer_sha256"] == hashlib.sha256(saved.assistant_message.encode()).hexdigest()
    return saved, audit


@pytest.mark.parametrize("case_id,query,body,required", POSITIVES, ids=[row[0] for row in POSITIVES])
def test_supported_official_lookup_stops_and_saves_bound_fields(monkeypatch, tmp_path, case_id, query, body, required):
    metadata(monkeypatch, body)
    gateway = GeneralWebGateway()
    monkeypatch.setattr(gateway, "search_exact", lambda *_a, **_k: pytest.fail("sufficient official evidence must stop"))
    calls = recover_public_research(gateway, query)
    summary = recovery_summary(calls)
    assert summary["mode"] == "lookup" and summary["reads"] == 1
    assert summary["target_coverage"]["covered"] == summary["target_coverage"]["required"]
    assert not any(call["name"] == "web_search" for call in calls)
    assert summary["limits"]["reads"] == 3 and summary["limits"]["hard_seconds"] == 30
    saved, audit = saved_exit(tmp_path, query, calls)
    assert audit["status"] == "field_backed"
    assert required <= {ref["field"] for ref in audit["assertion_refs"]}
    if case_id == "fastapi":
        assert "PyPI 包首次上传时间" in saved.assistant_message
    if case_id == "opus":
        assert INTRO in saved.assistant_message and "Old capability" not in saved.assistant_message


@pytest.mark.parametrize("case_id", ["adjacent_python", "nav_only_opus", "wrong_body", "tampered_binding", "missing_date"])
def test_unsafe_or_missing_target_field_is_never_published(monkeypatch, tmp_path, case_id):
    query = "Python 3.14什么时候发布"
    body = POSITIVES[3][2]
    if case_id == "adjacent_python":
        body = body.replace(b"3.14.0", b"3.13.0")
    elif case_id == "nav_only_opus":
        query = "Opus 5.5是什么"
        body = payload().replace(b"<button>claude-opus-5-5</button>", b"<nav>claude-opus-5-5</nav>")
    elif case_id == "wrong_body":
        query = "Opus 5.5是什么"
        body = payload(heading="Claude Opus 5.1", model_id="claude-opus-5-1")
    elif case_id == "missing_date":
        body = b"<h1>Python 3.14.0</h1><p>No release date provided.</p>"
    metadata(monkeypatch, body)
    gateway = GeneralWebGateway()
    monkeypatch.setattr(gateway, "search_exact", lambda *_a, **_k: {"status": "empty", "results": []})
    calls = recover_public_research(gateway, query)
    assert recovery_summary(calls)["reads"] <= 3
    if case_id == "tampered_binding":
        result = next(call["result"] for call in calls if call["name"] == "web_read")
        result["content_sha256"] = "0" * 64
        for field in result["official_fields"]:
            field["start"] += 1
    saved, audit = saved_exit(tmp_path, query, calls)
    if case_id == "missing_date":
        # Partial known fields are safe but do not pass requested-field coverage.
        assert "release_date" not in {ref["field"] for ref in audit["assertion_refs"]}
        assert "2025-10-07" not in saved.assistant_message
    else:
        assert audit["status"] == "abstained" and not audit["assertion_refs"]


def test_lookup_deadline_preserves_reserve_and_does_not_read_late_candidate(tmp_path):
    clock = [0.0]

    class DelayedGateway(Gateway):
        def search_exact(self, query, **kwargs):
            result = super().search_exact(query, **kwargs)
            clock[0] = 21
            return result

    gateway = DelayedGateway([[item("late", title="public topic")]], {})
    query = "public topic"
    calls = recover_public_research(gateway, query, budget=LOOKUP_BUDGET, monotonic=lambda: clock[0])
    assert recovery_summary(calls)["stop_reason"] == "DEADLINE_EXHAUSTED"
    assert gateway.reads == []
    saved, audit = saved_exit(tmp_path, query, calls)
    assert audit["status"] == "abstained" and not audit["assertion_refs"]


def test_local_reader_failure_uses_second_backend_without_claiming_field_support(monkeypatch):
    url = "https://example.org/lookup-reader-control"
    monkeypatch.setattr(article_fetcher, "_ARTICLE_CACHE", {})
    monkeypatch.setattr(article_fetcher, "_fetch_html_payload", lambda *_a, **_k: ("", url, "text/html", ""))
    attempted = []

    def second_reader(*_args, **_kwargs):
        attempted.append("second_reader")
        return "Read-backend recovery control text", "firecrawl_test_transport"

    monkeypatch.setattr(article_fetcher, "_try_firecrawl", second_reader)
    monkeypatch.setattr(article_fetcher, "_try_jina", lambda *_a, **_k: pytest.fail("successful second reader must stop"))
    result = GeneralWebGateway().read(url, timeout=1)
    assert result["ok"] and result["content"] == "Read-backend recovery control text"
    assert attempted == ["second_reader"]
    assert "official_fields" not in result


def test_official_first_url_timeout_recovers_a_body_but_does_not_invent_fields(tmp_path):
    gateway = Gateway([[item("rescue")]], {"overview": TimeoutError("official_timeout"),
        "rescue": "Claude Opus 5.5 release details."})
    gateway.supports_official_metadata = True
    calls = recover_public_research(gateway, "Opus 5.5是什么")
    assert recovery_summary(calls)["reads"] == 2
    assert recovery_summary(calls)["status"] == "read_backed"
    assert len(gateway.queries) == 1
    _, audit = saved_exit(tmp_path, "Opus 5.5是什么", calls)
    # Usable rescue prose does not satisfy bound-field coverage. This remains
    # a qualification gap, rather than permission to publish model memory.
    assert audit["status"] == "abstained" and not audit["assertion_refs"]


@pytest.mark.parametrize("scenario", ["empty_first", "all_reads_unusable", "all_candidates_rejected"])
def test_lookup_recovery_and_exhaustion_are_bounded_and_safe(tmp_path, scenario):
    candidates = [item("first"), item("second")]
    bodies = {"first": "", "second": "Claude Opus 5.5 release details."}
    if scenario == "all_reads_unusable":
        bodies = {key: TimeoutError("reader_unavailable") for key in bodies}
    elif scenario == "all_candidates_rejected":
        candidates = [{"title": "Claude Opus 5.5", "url": "http://127.0.0.1/private"}]
        bodies = {}
    gateway = Gateway([candidates, []], bodies)
    calls = recover_public_research(gateway, "Opus 5.5是什么")
    summary = recovery_summary(calls)
    assert summary["mode"] == "lookup" and len(gateway.queries) <= 2 and len(gateway.reads) <= 3
    if scenario == "empty_first":
        assert len(gateway.reads) == 2 and summary["status"] == "read_backed"
    else:
        assert summary["status"] != "read_backed"
    if scenario == "all_candidates_rejected":
        assert gateway.reads == []
    _, audit = saved_exit(tmp_path, "Opus 5.5是什么", calls)
    assert audit["status"] == "abstained" and not audit["assertion_refs"]
