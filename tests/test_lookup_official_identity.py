"""Reader-owned release identity and scheduler integrity regressions."""
import copy

import pytest

from src.web.research import official_resolver as resolver
from src.web.research_recovery import recover_public_research
from src.web.tool_evidence import evidence_tool_calls
from src.web.tool_gateway import GeneralWebGateway
from tests.test_official_source_quality import fastapi_payload, metadata


QUERY = "SQLite 3.53.4发布变化"
DATA = b'<h2>SQLite Release 3.53.4 On 2026-07-24</h2><ol><li>Target change</li></ol>'


def native_result(monkeypatch):
    metadata(monkeypatch, DATA)
    plan = resolver.official_plan(QUERY)
    result = resolver.read_official_metadata(plan.urls[0], timeout=1, max_chars=6000)
    return plan, result


def test_exact_native_release_identity_is_sufficient(monkeypatch):
    plan, result = native_result(monkeypatch)
    assert resolver.verified_release_identity(plan, plan.urls[0], result)
    metadata(monkeypatch, fastapi_payload())
    plan = resolver.official_plan("FastAPI 0.136.3发布版本")
    result = resolver.read_official_metadata(plan.urls[0], timeout=1, max_chars=6000)
    assert resolver.verified_release_identity(plan, plan.urls[0], result)


@pytest.mark.parametrize("mutation", ["flag_only", "content_digest", "transport_digest", "wrong_url", "wrong_source_version",
                                     "field_span", "field_value", "duplicate_field", "failed_read", "wrong_method"])
def test_candidate_flags_or_tampered_native_identity_are_not_proof(monkeypatch, mutation):
    plan, native = native_result(monkeypatch)
    result = copy.deepcopy(native)
    if mutation == "flag_only":
        result = {"identity_verified": True}
    elif mutation == "content_digest":
        result["content_sha256"] = "0" * 64
    elif mutation == "transport_digest":
        result["transport_sha256"] = "invalid"
    elif mutation == "wrong_url":
        result["url"] = "https://sqlite.org/releaselog/3_53_3.html"
    elif mutation == "wrong_source_version":
        result["source_version"] = "3.53.3"
    elif mutation == "field_span":
        result["official_fields"][0]["start"] += 1
    elif mutation == "field_value":
        result["official_fields"][1]["value"] = "3.53.3"
    elif mutation == "duplicate_field":
        result["official_fields"].append(result["official_fields"][0])
    elif mutation == "failed_read":
        result["ok"] = False
    else:
        result["method"] = "candidate_guess"
    assert not resolver.verified_release_identity(plan, plan.urls[0], result)


def test_recovery_does_not_replace_invalid_reader_digest_with_its_own(monkeypatch):
    _, native = native_result(monkeypatch)
    native["content_sha256"] = "0" * 64
    gateway = GeneralWebGateway()
    monkeypatch.setattr(gateway, "read", lambda *_a, **_k: copy.deepcopy(native))
    monkeypatch.setattr(gateway, "search_exact", lambda *_a, **_k: {"status": "empty", "results": []})
    calls = recover_public_research(gateway, QUERY)
    read = next(call["result"] for call in calls if call["name"] == "web_read")
    assert read["content_sha256"] == "0" * 64 and read["answer_eligible"] is False
    assert evidence_tool_calls(calls) == []
