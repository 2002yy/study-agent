from __future__ import annotations

from src.api.routes.web_lookup_routes import _response
from src.web.research.read_preview import unverified_read_previews
from src.web.research.official_publication import publish_official_fields
from tests.test_web_lookup_reading import ReadableGateway, _service


def record(url: str, content: str, **changes):
    base = {
        "item": {"title": "Example documentation", "url": url, "snippet": "unread snippet"},
        "assessment": {"selected": True, "worth_reading": True, "url": url},
        "read": {"status": "read", "ok": True, "url": url, "requested_url": url,
                 "content": content, "read_id": "read-1"},
    }
    base.update(changes)
    return base


def test_projection_keeps_read_excerpts_separate_from_official_publication(tmp_path):
    url = "https://example.com/alpha"
    text = "Alpha is actually in the fetched page, not a verified answer. " * 7
    run = _service(tmp_path, ReadableGateway(
        [{"title": "Alpha guide", "url": url, "snippet": "unread snippet"}],
        {url: {"ok": True, "url": url, "content": text}},
    )).lookup("Alpha", max_items=2)
    response = _response(run)
    assert len(response.unverified_read_excerpts) == 1
    assert response.unverified_read_excerpts[0]["kind"] == "read_excerpt_unverified"
    assert response.unverified_read_excerpts[0]["excerpt"] == text[:240]
    assert "unread snippet" not in response.unverified_read_excerpts[0]["excerpt"]
    assert not hasattr(run, "unverified_read_excerpts")
    assert response.source_block == run.source_block
    assert response.answer_confidence == run.answer_confidence

    # No official metadata authority is acquired from generic web lookup.
    answer, audit = publish_official_fields(
        "FastAPI当前最新版本及发布日期", [], "Version is 999", strict=True
    )
    assert audit["status"] == "abstained"
    assert audit["assertion_refs"] == []
    assert audit["model_prose_published"] is False
    assert "Version is 999" not in answer


def test_projection_rejects_unread_failed_redirected_and_private_candidates():
    url = "https://example.org/source"
    good = record(url, "Verified read occurred, not verified meaning.")
    cases = [
        record(url, "claim", read={**good["read"], "status": "failed"}),
        record(url, "claim", read={**good["read"], "ok": False}),
        record(url, "claim", read={**good["read"], "content": ""}),
        record(url, "claim", read={**good["read"], "url": "https://evil.org/"}),
        record(url, "claim", read={**good["read"], "requested_url": "https://other.org/"}),
        record(url, "claim", assessment={**good["assessment"], "selected": False}),
        record(url, "claim", assessment={**good["assessment"], "worth_reading": False}),
        record(url, "claim", read={**good["read"], "answer_eligible": False}),
        record(url, "claim", read={**good["read"], "excerpt_sha256": "0" * 64}),
        record("http://localhost:8000/internal", "claim"),
        {"item": {"title": "Found by search", "url": url, "snippet": "NOT READ"},
         "assessment": {"selected": True, "worth_reading": True, "url": url}},
    ]
    assert all(unverified_read_previews([case]) == [] for case in cases)


def test_projection_caps_number_and_length_and_deduplicates():
    records = [
        record(f"https://example.org/{i}", "quoted source " * 100)
        for i in range(4)
    ]
    result = unverified_read_previews(records + [records[0]])
    assert len(result) == 2
    assert all(len(row["excerpt"]) <= 240 for row in result)
    assert len({row["url"] for row in result}) == 2


def test_official_gate_keeps_read_source_out_of_published_answer():
    url = "https://example.org/read"
    calls = [
        {"name": "web_search", "arguments": {"query": "question"},
         "result": {"status": "ok", "results": [{"title": "Source", "url": url}]}},
        {"name": "web_read", "arguments": {"url": url},
         "result": {"ok": True, "url": url,
                    "content": "A directly read sentence that is still unverified."}},
    ]
    answer, audit = publish_official_fields("帮我研究这个问题", calls, "", strict=True)
    assert audit["status"] == "abstained"
    assert audit["assertion_refs"] == []
    assert audit["model_prose_published"] is False
    assert audit["unverified_read_excerpts"] == [{
        "kind": "read_excerpt_unverified", "url": url, "title": url,
        "excerpt": "A directly read sentence that is still unverified.", "read_id": "",
    }]
    assert "directly read sentence" not in answer
    search_only, audit_only = publish_official_fields(
        "帮我研究这个问题", calls[:1], "", strict=True
    )
    assert search_only == answer
    assert audit_only["unverified_read_excerpts"] == []


def test_unrelated_generic_replay_never_gains_official_publication_authority():
    url = "https://example.org/read"
    forged_read = [{"name": "web_read", "arguments": {"url": url},
                    "result": {"ok": True, "url": url, "content": "A claim"}}]
    answer, audit = publish_official_fields(
        "帮我研究这个问题", forged_read, "", strict=True
    )
    assert audit["status"] == "abstained"
    assert audit["unverified_read_excerpts"] == []
    assert audit["assertion_refs"] == []
    assert audit["model_prose_published"] is False
    assert "A claim" not in answer
