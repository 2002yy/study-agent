from dataclasses import replace
from hashlib import sha256
from types import SimpleNamespace

from fastapi.testclient import TestClient

from src.api.app import app
from src.application.research_presentation import (
    research_presentation,
    research_run_block,
    research_run_event,
)
from src.domain.runtime_entities import WebLookupRun
from src.web.research.standard_binding_projection import journal_work_key
from tests.test_deep_publication import _audit_result
from src.web.research.runtime import ResearchRuntimeCursor, attach_runtime_cursor
from src.api.routes.chat_routes import _research_progress
import pytest


def run(**kwargs):
    return WebLookupRun(
        id="r1",
        query="q",
        owner_thread_id="s1",
        research_context={"owner": {"thread_id": "s1", "turn_id": "t1"}},
        **kwargs,
    )


@pytest.mark.parametrize(
    "value, expected",
    [(None, None), (0, 0), (1, 1), (-1, None), (True, None), ("1", None)],
)
def test_legacy_progress_missing_or_invalid_counters_are_unknown(value, expected):
    item = replace(
        run(), research_context={"claim_engine_metrics": {"read_count": value}}
    )
    progress = _research_progress(item)
    assert progress["read_count"] == expected
    assert progress["candidate_count"] is None
    assert progress["cluster_count"] is None
    assert progress["open_critical_gap_count"] is None


def test_missing_counters_and_unread_source_never_become_verified():
    item = run(
        selected_sources=[{"item": {"title": "候选", "url": "https://example.com/a"}}]
    )
    block = research_run_block(item)
    assert block["tier"] == "lookup"
    assert block["read_count"] is None
    assert block["sources"][0]["read_status"] == "unknown"
    assert block["publication_status"] == "observation_only"
    assert "body" not in str(block)
    assert research_run_block(item)["block_id"] == block["block_id"]
    assert (
        research_run_block(replace(item, version=item.version + 1))["revision"]
        == item.version + 1
    )
    assert research_run_event(item)["snapshot_kind"] == "run"
    assert research_run_event(item)["turn_updated_at"] is None


def test_deep_phase_and_wave_come_from_validated_runtime_cursor():
    context = attach_runtime_cursor(
        {}, ResearchRuntimeCursor(phase="reading", round_index=2)
    )
    context["deep"] = {"round_index": 99}
    item = replace(run(stage="deep_handoff"), research_context=context)
    block = research_run_block(item)
    assert block["research_phase"] == "reading"
    assert block["wave"] == 0  # Real wave marker, not a guessed round counter.
    context["claim_engine_runtime"]["schema_version"] = "unknown"
    assert research_run_block(item)["wave"] is None
    assert research_run_block(run(stage="standard_handoff"))["read_count"] is None


def test_existing_deep_mode_and_owned_turn_counters_are_presented_without_guessing():
    item = replace(run(), research_context={"research_mode": "deep"})
    assert research_run_block(item)["tier"] == "deep"
    assert research_run_block(item)["wave"] is None
    tools = {
        "run_id": item.id,
        "read_count": 4,
        "candidate_count": 8,
        "recovery": {"mode": "lookup"},
    }
    lookup = run()
    assert research_run_block(lookup, tools)["read_count"] == 4
    assert research_run_block(item, tools)["candidate_count"] == 8
    assert (
        research_run_block(item, {**tools, "run_id": "foreign"})["read_count"] is None
    )
    legacy = replace(
        item,
        research_context={"research_mode": "deep", "read_summary": {"successful": 4}},
    )
    assert (
        research_run_block(legacy, {"run_id": item.id, "read_count": 0})["read_count"]
        == 4
    )
    assert (
        research_run_block(item, {"run_id": item.id, "read_count": 0})[
            "candidate_count"
        ]
        is None
    )


def test_sources_are_bounded_deduped_and_dangerous_links_omitted():
    sources = [
        {"item": {"title": "来源", "url": url}, "read_status": "read"}
        for url in (
            "javascript:alert(1)",
            "https://user:pass@example.com/",
            "https://example.com/a",
            "https://example.com/a",
            "https://example.com/\nsecret",
        )
    ]
    block = research_run_block(run(selected_sources=sources))
    assert len(block["sources"]) == 1
    assert block["sources"][0]["url"] == "https://example.com/a"
    bounded = research_run_block(
        run(
            selected_sources=[
                {"item": {"url": f"https://example.com/{i}"}} for i in range(30)
            ]
        )
    )
    assert bounded["sources_truncated"] and len(bounded["sources"]) == 20


def test_standard_sources_require_durable_body_hash_and_do_not_publish_values():
    url, body = "https://example.com/price", "price 0.20"
    digest = sha256(body.encode()).hexdigest()
    ledger = {
        "schema": "standard-dispatch-journal-v1",
        "new_reads": 1,
        "entries": {
            journal_work_key("read", url): {
                "state": "completed",
                "result": {"content": body},
            }
        },
        "research": {
            "observations": [
                {
                    "kind": "read",
                    "target": url,
                    "readable": True,
                    "content_sha256": digest,
                }
            ],
            "result": {
                "gap_states": {
                    "price": {
                        "research_state": "SOURCE_ACQUIRED",
                        "support_status": "NOT_EVALUATED",
                    }
                },
                "model_price": 0.2,
                "publication_authority": True,
            },
        },
    }
    context = {"owner": {"turn_id": "t1"}, "standard": ledger}
    item = replace(run(stage="standard_handoff"), research_context=context)
    block = research_run_block(item)
    assert block["tier"] == "standard" and block["read_count"] == 1
    assert block["sources"][0]["content_sha256"] == digest
    assert block["gaps"][0]["support_status"] == "NOT_EVALUATED"
    assert "0.20" not in str(block) and "model_price" not in str(block)
    ledger["entries"][journal_work_key("read", url)]["result"]["content"] = "changed"
    assert research_run_block(item)["sources"] == []


def test_deep_audit_is_observation_only_and_cross_owner_records_are_removed():
    turn = SimpleNamespace(
        id="t1",
        thread_id="s1",
        rag_snapshot={
            "deep_publication": {
                "dispatch_status": "audited",
                "publication_authority": True,
                "candidate": "SECRET CANDIDATE",
            }
        },
    )
    good = run(stage="deep_handoff")
    result = research_presentation(
        turn, [good, replace(good, id="wrong", owner_thread_id="other")]
    )
    assert len(result["blocks"]) == 1 and result["blocks"][0]["tier"] == "deep"
    assert result["audit_status"] is None and result["publication_authority"] is False
    assert result["audit_integrity"] == "invalid"
    assert "SECRET" not in str(result)
    assert (
        research_presentation(
            turn, [replace(good, research_context={"owner": {"turn_id": "other"}})]
        )["blocks"]
        == []
    )


def test_recorded_audit_uses_deep4a_read_only_integrity_authority():
    digest = "a" * 64
    publication = {
        "schema_version": "deep-publication-v1",
        "dispatch_status": "audited",
        "publication_authority": False,
        "owner": {"thread_id": "s1", "turn_id": "t1", "child_run_id": "child"},
        "source": {
            key: digest
            for key in (
                "deep_terminal_sha256",
                "child_terminal_sha256",
                "source_run_sha256",
            )
        },
        "result": _audit_result("child", digest),
    }
    turn = SimpleNamespace(
        id="t1", thread_id="s1", rag_snapshot={"deep_publication": publication}
    )
    result = research_presentation(turn, [run(stage="deep_handoff")])
    assert result["audit_integrity"] == "valid" and result["audit_status"] == "audited"
    assert result["publication_authority"] is False
    publication["result"]["judge_authority"] = "answer_model"
    assert research_presentation(turn, [run()])["audit_status"] is None


def test_snapshot_endpoint_is_read_only_and_checks_session_turn_pair(
    runtime_test_context,
):
    client = TestClient(app)
    reply = client.post("/chat", json={"user_input": "hello"}).json()
    sid, tid = reply["session_id"], reply["turn_id"]
    repo = runtime_test_context.repository
    before = repo.get_chat_turn(tid)
    row = replace(
        run(),
        id="endpoint-run",
        owner_thread_id=sid,
        research_context={"owner": {"thread_id": sid, "turn_id": tid}},
    )
    runtime_test_context.web_lookup_repository.create(row)
    response = client.get(f"/sessions/{sid}/turns/{tid}/research-presentation")
    assert response.status_code == 200
    assert response.json()["snapshot_kind"] == "turn"
    assert response.json()["turn_updated_at"] == before.updated_at
    assert response.json()["blocks"][0]["run_id"] == "endpoint-run"
    assert repo.get_chat_turn(tid) == before
    assert (
        client.get(f"/sessions/other/turns/{tid}/research-presentation").status_code
        == 404
    )
