"""Exact official heading records; neither TOC nor upload metadata binds a date."""

from copy import deepcopy
import hashlib

import pytest

from src.web.research import official_resolver as resolver
from src.web.research.evidence_binding import document_from_read
from src.web.research.fastapi_release import BASE_URL, selected_version
from src.web.research.official_publication import publish_official_fields
from src.web.research_recovery import recover_public_research, recovery_summary
from src.web.tool_gateway import GeneralWebGateway
from tests.test_official_source_quality import metadata

URL = BASE_URL + "?version=0.115.0"
QUERY = "FastAPI 0.115.0 发布日期和版本号"


def page(
    record='<h2 id="01150-2024-09-17">0.115.0 (2024-09-17)</h2>',
    *,
    title="Release Notes - FastAPI",
):
    return (
        f"<html><head><title>{title}</title></head><body><nav>0.115.0 (1900-01-01)</nav>"
        f"<article><h1>Release Notes</h1>{record}</article></body></html>"
    ).encode()


def test_precise_date_request_prioritizes_heading_not_package_upload():
    plan = resolver.official_plan(QUERY)
    assert plan.urls[0] == URL
    assert BASE_URL in plan.urls  # old durable resolver candidates remain admissible
    assert (
        resolver.official_plan("FastAPI当前最新版本及发布日期")
        .urls[0]
        .startswith("https://pypi.org/")
    )


@pytest.mark.parametrize(
    "query",
    [
        "FastAPI 0.115 发布日期",
        "FastAPI 0.115.0rc1 发布日期",
        "FastAPI 0.115.0+local 发布日期",
        "FastAPI 0.115.0.1 发布日期",
    ],
)
def test_inexact_intent_does_not_generate_a_stable_date_selector(query):
    plan = resolver.official_plan(query)
    assert not plan or all(selected_version(url) is None for url in plan.urls)


@pytest.mark.parametrize(
    "url",
    [
        BASE_URL,
        BASE_URL + "?version=0.115",
        BASE_URL + "?version=0.115.0&other=1",
        "http://127.0.0.1/release-notes/?version=0.115.0",
        "https://fastapi.tiangolo.com.evil.test/release-notes/?version=0.115.0",
    ],
)
def test_selector_is_exact_public_registry_address(url):
    assert selected_version(url) is None


def test_old_version_heading_is_found_beyond_recent_notes_and_spans_rehash():
    payload = page(
        '<h2 id="01430-2026-10-08">0.143.0 (2026-10-08)</h2>'
        + "<p>"
        + "recent content " * 1000
        + "</p>"
        + '<h2 id="01150-2024-09-17">0.115.0 (2024-09-17)</h2>'
    )
    bindings = {}
    fields = resolver._fields(URL, payload, source_bindings=bindings)
    assert fields == {
        "project": "FastAPI",
        "version": "0.115.0",
        "release_date": "2024-09-17",
    }
    proof = bindings["release_date"]
    doc = document_from_read(proof["read_id"], BASE_URL, payload)
    assert proof["decoded_payload_sha256"] == hashlib.sha256(payload).hexdigest()
    assert (
        proof["source_content_sha256"] == hashlib.sha256(doc.text.encode()).hexdigest()
    )
    start, end = proof["source_span"]
    assert doc.text[start:end] == proof["quote"] == "0.115.0 (2024-09-17)"
    assert start > 6000
    assert proof["record_url"] == BASE_URL + "#01150-2024-09-17"


@pytest.mark.parametrize(
    "record",
    [
        '<h2 id="01151-2024-09-18">0.115.1 (2024-09-18)</h2>',
        "<p>0.115.0 (2024-09-17)</p>",
        '<h2 id="01150-2024-09-17">0.115.0 uploaded on 2024-09-17</h2>',
        '<h2 id="01150-2024-09-17">0.115.0 updated on 2024-09-17</h2>',
        '<h2 id="01150-2024-09-17">0.115.0 (2024-09-17, 2024-09-18)</h2>',
        '<h2 id="01150-2024-02-30">0.115.0 (2024-02-30)</h2>',
        "<h2>0.115.0 (2024-09-17)</h2>",
        '<h2 id="01150-2024-09-17">0.115.0 (2024-09-17)</h2>' * 2,
        '<h2 id="01150-2024-09-17">0.115.0 (2024-09-17)</h2><h2 id="01150-2024-09-18">0.115.0 (2024-09-18)</h2>',
    ],
)
def test_missing_adjacent_ambiguous_or_non_release_records_fail_closed(record):
    with pytest.raises(ValueError):
        resolver._fields(URL, page(record))


def test_wrong_product_is_not_repaired_from_similar_version():
    with pytest.raises(ValueError, match="identity_mismatch"):
        resolver._fields(URL, page(title="Release Notes - OtherProject"))


def test_native_path_uses_one_read_and_preserves_original_publication_gate(monkeypatch):
    metadata(monkeypatch, page())
    gateway = GeneralWebGateway()
    monkeypatch.setattr(
        gateway,
        "search_exact",
        lambda *a, **k: pytest.fail("verified record needs no rescue"),
    )
    calls = recover_public_research(gateway, QUERY)
    assert recovery_summary(calls)["reads"] == 1
    assert not any(call["name"] == "web_search" for call in calls)
    result = next(call["result"] for call in calls if call["name"] == "web_read")
    plan = resolver.official_plan(QUERY)
    assert resolver.verified_release_identity(plan, URL, result)
    answer, audit = publish_official_fields(
        QUERY, calls, "Unsupported performance recommendation"
    )
    assert "2024-09-17" in answer and "recommendation" not in answer
    assert audit["model_prose_published"] is False
    assert (
        next(ref for ref in audit["assertion_refs"] if ref["field"] == "release_date")[
            "source_binding"
        ]["quote"]
        == "0.115.0 (2024-09-17)"
    )


@pytest.mark.parametrize("tamper", ["hash", "span", "version", "transport"])
def test_native_publication_rejects_corrupt_record(monkeypatch, tamper):
    metadata(monkeypatch, page())
    result = resolver.read_official_metadata(URL, timeout=1, max_chars=6000)
    value = deepcopy(result)
    if tamper == "hash":
        value["content_sha256"] = "0" * 64
    elif tamper == "version":
        value["source_version"] = "0.115.1"
    elif tamper == "transport":
        value["transport_sha256"] = "missing"
    else:
        for field in value["official_fields"]:
            field["start"] = -1
    calls = [{"name": "web_read", "arguments": {"url": URL}, "result": value}]
    answer, audit = publish_official_fields(QUERY, calls, "2024-09-17")
    assert audit["status"] == "abstained"
    assert "2024-09-17" not in answer


def test_bounded_native_reader_does_not_publish_truncated_fields(monkeypatch):
    metadata(monkeypatch, page())
    assert resolver.read_official_metadata(URL, timeout=1, max_chars=10)["ok"] is False
