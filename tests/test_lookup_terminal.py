"""Terminal contract controls; no automatic production tier switch."""
from copy import deepcopy
import hashlib
import json

import pytest

from src.web.research.lookup_terminal import decide_lookup_terminal, load_standard_handoff
from src.web.research_recovery import recover_public_research
from src.web.tool_gateway import GeneralWebGateway
from tests.test_official_source_quality import metadata

QUERY = "Python 3.14什么时候发布"
URL = "https://realpython.com/python314-new-features/"


def relevant_calls():
    body = "Python 3.14 language discussion; the release date still needs a bound source."
    return [{"name": "web_search", "arguments": {"query": QUERY},
             "result": {"status": "ok", "results": [{"url": URL, "title": "Python 3.14"}]}},
            {"name": "web_read", "arguments": {"url": URL},
             "result": {"url": URL, "ok": True, "content": body,
                        "content_sha256": hashlib.sha256(body.encode()).hexdigest(),
                        "answer_eligible": True, "related_rq_ids": ["rq-date"],
                        "adequacy_reason": "related_to_rq_not_claim_support"}},
            {"name": "research_recovery", "arguments": {"query": QUERY},
             "result": {"query": QUERY, "mode": "lookup", "status": "read_backed",
                        "reads": 2, "searches": 2, "elapsed_seconds": 0.3, "question_coverage": {
                            "kind": "relevance_only", "related": ["rq-date"]}}}]


def decide(calls, **kwargs):
    return decide_lookup_terminal(QUERY, calls, requested_fields=("release_date",),
                                  requested_rq_ids=("rq-date",), allow_standard=True, **kwargs)


@pytest.mark.parametrize("include_date", [True, False])
def test_verified_requires_requested_fields_not_any_publication_ref(monkeypatch, include_date):
    html = b"<h1>Python 3.14.0</h1>"
    if include_date:
        html += b"<p>Release date: Oct. 7, 2025</p>"
    metadata(monkeypatch, html)
    calls = recover_public_research(GeneralWebGateway(), QUERY)
    decision = decide(calls)
    assert decision.state == ("VERIFIED" if include_date else "SAFE_ABSTAIN")
    assert decision.handoff is None


def test_escalation_preserves_sources_gap_and_budget_without_authority():
    calls = relevant_calls()
    original = deepcopy(calls)
    decision = decide(calls)
    assert decision.state == "ESCALATE_STANDARD"
    handoff = decision.handoff
    assert handoff["known"] == [] and handoff["unresolved_fields"] == ["release_date"]
    assert handoff["publication_authority"] is False
    assert handoff["attempted"] == original
    assert handoff["lookup_budget"]["reads"] == 2
    assert load_standard_handoff(json.loads(json.dumps(handoff))) == handoff
    # Reusing a snapshot is pure; no search/read is dispatched or counted twice.
    assert load_standard_handoff(handoff) == handoff and calls == original
    calls[1]["result"]["content"] = "Changed after handoff"
    assert handoff["usable_sources"][0]["result"]["content"] != calls[1]["result"]["content"]


@pytest.mark.parametrize("reason", ["unknown_relevance", "wrong_rq", "tampered_body", "no_source",
                                  "cancelled", "deadline", "wrong_mode", "wrong_query", "unrelated"])
def test_unqualified_failures_do_not_escalate(reason):
    calls = relevant_calls()
    read = calls[1]["result"]
    summary = calls[-1]["result"]
    if reason == "unknown_relevance":
        read.pop("adequacy_reason")
    elif reason == "wrong_rq":
        read["related_rq_ids"] = ["invented-rq"]
    elif reason == "tampered_body":
        read["content"] += "tampered"
    elif reason == "no_source":
        calls = calls[-1:]
    elif reason == "unrelated":
        read["answer_eligible"] = False
    elif reason == "cancelled":
        summary["status"] = "cancelled"
    elif reason == "deadline":
        summary["status"] = "deadline_exhausted"
    elif reason == "wrong_mode":
        summary["mode"] = "standard"
    else:
        summary["query"] = "another question"
    result = decide(calls)
    assert result.state == "SAFE_ABSTAIN" and result.handoff is None


@pytest.mark.parametrize("flag", ["identity_conflict", "contradiction", "cancelled"])
def test_deterministic_conflicts_and_cancellation_stop(flag):
    assert decide(relevant_calls(), **{flag: True}).state == "SAFE_ABSTAIN"


def test_tier_permission_is_required():
    result = decide_lookup_terminal(QUERY, relevant_calls(), requested_fields=("release_date",),
                                    requested_rq_ids=("rq-date",))
    assert result.state == "SAFE_ABSTAIN" and result.reason == "standard_not_enabled"


@pytest.mark.parametrize("key,value", [("reads", 4), ("reads", True), ("searches", 3),
                                       ("elapsed_seconds", 31), ("elapsed_seconds", float("nan"))])
def test_missing_or_exceeded_lookup_budget_prevents_escalation(key, value):
    calls = relevant_calls()
    calls[-1]["result"][key] = value
    assert decide(calls).state == "SAFE_ABSTAIN"


def test_digest_recalculation_cannot_change_bound_source_snapshot():
    from src.web.research.lookup_terminal import _digest

    handoff = decide(relevant_calls()).handoff
    handoff.pop("payload_sha256")
    handoff["usable_sources"] = []
    handoff["payload_sha256"] = _digest(handoff)
    with pytest.raises(ValueError, match="verified source snapshot"):
        load_standard_handoff(handoff)


@pytest.mark.parametrize("field", ["schema_version", "usable_sources", "attempted", "publication_authority"])
def test_changed_handoff_is_rejected(field):
    handoff = decide(relevant_calls()).handoff
    handoff[field] = "tampered"
    with pytest.raises(ValueError, match="schema or digest"):
        load_standard_handoff(handoff)
