from __future__ import annotations

import hashlib

from src.web.research.candidate_funnel import candidate_funnel


def search(url="https://example.org/release"):
    return {"name": "web_search", "result": {"status": "ok", "results": [
        {"url": url, "title": "Release", "providers": ["searxng"]}]}}


def read(*, final="https://example.org/canonical", eligible=True, digest=None):
    result = {"url": final, "ok": True, "content": "release body", "method": "local_trafilatura",
              "answer_eligible": eligible}
    if digest is not None:
        result["content_sha256"] = digest
    return {"name": "web_read", "arguments": {"url": "https://example.org/release"}, "result": result}


def test_missing_decisions_fail_the_zero_read_gate():
    result = candidate_funnel([search()], [])
    assert result["attempted_reads"] == 0
    assert result["gate_failures"][0]["gate"] == "G0-1"


def test_terminal_skip_explains_zero_reads_without_claiming_evidence():
    result = candidate_funnel([search()], [{"candidate_id": "https://example.org/release",
                                           "state": "filtered", "reason": "not_worth_reading"}])
    assert result["gate_failures"] == []
    assert result["candidates"][0]["skip_reason"] == "not_worth_reading"
    assert result["evidence_adopted"] == 0


def test_redirect_adoption_binds_candidate_read_and_actual_body_span():
    result = candidate_funnel([search(), read()], [])
    row = result["candidates"][0]
    assert result["gate_failures"] == []
    assert row["provider_rank"] == 1
    assert row["attempted_backends"] == ["local_trafilatura"]
    assert row["scheduled_count"] == row["read_attempt_count"] == 1
    ref = row["evidence_refs"][0]
    assert ref["read_call_index"] == 1
    assert ref["final_url"].endswith("/canonical")
    assert ref["source_span"] == [0, len("release body")]
    assert ref["content_sha256"] == hashlib.sha256(b"release body").hexdigest()
    assert result["cited"] is None
    assert result["formal_support_assessed"] is False


def test_repeated_dispatch_is_a_gate_failure():
    result = candidate_funnel([search(), read(), read()], [])
    assert result["gate_failures"][0]["gate"] == "G0-2"


def test_rejected_body_and_tampered_digest_cannot_be_counted_as_adopted():
    rejected = candidate_funnel([search(), read(eligible=False)], [])
    assert rejected["read_usable"] == 1
    assert rejected["evidence_adopted"] == 0
    tampered = candidate_funnel([search(), read(digest="bad")], [])
    assert tampered["evidence_adopted"] == 0
    assert tampered["gate_failures"][0]["gate"] == "G0-4"


def test_invalid_url_is_an_explicit_skip_and_provider_duplicates_remain_visible():
    result = candidate_funnel([search("http://127.0.0.1/private")], [])
    assert result["candidates"][0]["skip_reason"] == "unsupported_url"
    assert result["gate_failures"] == []
    duplicate = candidate_funnel([search(), search(), read()], [])
    assert duplicate["candidate_count"] == 1
    assert len(duplicate["candidates"][0]["provider_ranks"]) == 2
