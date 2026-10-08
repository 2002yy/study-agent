"""Saved resolver addresses remain candidates, never evidence or publication."""

from copy import deepcopy

import pytest

from src.web.research.standard_plan import (
    PLAN_SCHEMA,
    discovered_urls,
    initial_actions,
    validate_plan,
)

QUERY = "FastAPI 0.136.0 发布日期和版本号"
NOTES = "https://fastapi.tiangolo.com/release-notes/"
PYPI = "https://pypi.org/pypi/fastapi/0.136.0/json"


def handoff():
    return {
        "query": QUERY,
        "payload_sha256": "saved-handoff-hash",
        "unresolved_fields": ["release_date"],
        "known": [{"field": "version", "value": "0.136.0"}],
        "publication_authority": False,
        "usable_sources": [{"arguments": {"url": PYPI}}],
        "attempted": [
            {
                "name": "official_resolve",
                "arguments": {
                    "query": QUERY,
                    "recovery_stage": "official_resolver",
                    "max_results": 5,
                    "rq_ids": [],
                },
                "result": {
                    "status": "ok",
                    "reason": "known_official_addresses_not_search_results",
                    "results": [{"url": PYPI}, {"url": NOTES}],
                },
            }
        ],
    }


def proposal(saved, url=NOTES):
    return {
        "schema": PLAN_SCHEMA,
        "query": saved["query"],
        "handoff_sha256": saved["payload_sha256"],
        "gaps": [{"field": "release_date", "queries": [], "candidate_urls": [url]}],
    }


def test_saved_exact_resolver_candidate_enters_plan_without_becoming_evidence():
    saved = handoff()
    original = deepcopy(saved)
    assert discovered_urls(saved) == {PYPI, NOTES}
    plan = validate_plan(proposal(saved), saved)
    actions = initial_actions(plan, saved)
    assert [(a["target"], a["origin"]) for a in actions] == [
        (PYPI, "lookup"),
        (NOTES, "candidate"),
    ]
    assert saved == original
    assert saved["publication_authority"] is False
    assert saved["unresolved_fields"] == ["release_date"]
    assert [f["field"] for f in saved["known"]] == ["version"]


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/private",
        "http://192.168.1.1/private",
        "file:///C:/private",
        "https://pypi.org/pypi/fastapi/0.135.0/json",
        "https://pypi.org/pypi/sqlite/0.136.0/json",
        "https://fastapi.tiangolo.com/invented",
        "https://fastapi.tiangolo.com.evil.example/release-notes/",
    ],
)
def test_resolver_cannot_launder_private_wrong_identity_or_invented_address(url):
    saved = handoff()
    saved["attempted"][0]["result"]["results"] = [{"url": url}]
    assert url not in discovered_urls(saved)
    with pytest.raises(ValueError, match="undiscovered URLs"):
        validate_plan(proposal(saved, url), saved)


@pytest.mark.parametrize(
    "target,key,value",
    [
        ("arguments", "query", "FastAPI 0.135.0 发布日期和版本号"),
        ("arguments", "recovery_stage", "generic_search"),
        ("result", "status", "partial"),
        ("result", "reason", "untrusted_model_suggestion"),
        ("result", "results", [{"url": NOTES, "policy_allowed": False}]),
        ("result", "results", "malformed"),
    ],
)
def test_only_matching_successful_registry_resolver_contract_is_admitted(
    target, key, value
):
    saved = handoff()
    saved["attempted"][0][target][key] = value
    assert discovered_urls(saved) == {PYPI}
    with pytest.raises(ValueError, match="undiscovered URLs"):
        validate_plan(proposal(saved), saved)


def test_current_registry_address_not_saved_is_not_silently_added():
    saved = handoff()
    saved["attempted"] = []
    assert discovered_urls(saved) == {PYPI}
    with pytest.raises(ValueError, match="undiscovered URLs"):
        validate_plan(proposal(saved), saved)
