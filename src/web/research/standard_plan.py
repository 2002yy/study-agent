"""Standard research strategy proposals, never factual support or answers."""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from typing import Any
from urllib.parse import urlsplit

from src.web.research.official_resolver import official_plan
from src.web.tool_evidence import _public_url

PLAN_SCHEMA = "standard-research-plan-v1"
RESULT_SCHEMA = "standard-research-result-v1"


def discovered_urls(handoff: dict) -> set[str]:
    urls = {call["arguments"]["url"] for call in handoff["usable_sources"]}
    for call in handoff["attempted"]:
        if call["name"] == "web_search":
            urls.update(search_urls(call["result"], handoff["query"]))
        elif call["name"] == "official_resolve":
            urls.update(resolver_urls(call, handoff["query"]))
    return urls


def resolver_urls(call: dict, query: str) -> list[str]:
    """Carry saved registry candidates, without declaring their evidence identity."""
    arguments, result = call.get("arguments"), call.get("result")
    if not isinstance(arguments, dict) or not isinstance(result, dict):
        return []
    if (
        arguments.get("query") != query
        or arguments.get("recovery_stage") != "official_resolver"
        or result.get("status") != "ok"
        or result.get("reason") != "known_official_addresses_not_search_results"
        or not isinstance(result.get("results"), list)
    ):
        return []
    plan = official_plan(query)
    if plan is None:
        return []
    return list(
        dict.fromkeys(
            url
            for row in result["results"]
            if isinstance(row, dict)
            and row.get("policy_allowed") is not False
            and (url := public_url(row.get("url"))) in plan.urls
        )
    )


def public_url(value: Any) -> str:
    try:
        return _public_url(value)
    except ValueError:
        return ""


def search_urls(result: dict, query: str) -> list[str]:
    rows = result.get("results")
    if not isinstance(rows, list) or result.get("status") != "ok":
        return []
    urls = list(
        dict.fromkeys(
            url
            for row in rows[:8]
            if isinstance(row, dict)
            and row.get("policy_allowed") is not False
            and (url := public_url(row.get("url")))
        )
    )
    official = official_plan(query)
    hosts = {urlsplit(url).hostname for url in official.urls} if official else set()
    return sorted(urls, key=lambda url: urlsplit(url).hostname not in hosts)


def validate_plan(proposal: Any, handoff: dict) -> dict:
    if not isinstance(proposal, dict) or set(proposal) != {
        "schema",
        "query",
        "handoff_sha256",
        "gaps",
    }:
        raise ValueError("invalid Standard plan envelope")
    if (
        proposal["schema"] != PLAN_SCHEMA
        or proposal["query"] != handoff["query"]
        or proposal["handoff_sha256"] != handoff["payload_sha256"]
    ):
        raise ValueError("Standard plan identity mismatch")
    gaps = proposal["gaps"]
    if (
        not isinstance(gaps, list)
        or not gaps
        or len(gaps) > len(handoff["unresolved_fields"])
    ):
        raise ValueError("invalid Standard gaps")
    seen: set[str] = set()
    queries: set[str] = set()
    candidates: set[str] = set()
    discovered = discovered_urls(handoff)
    for gap in gaps:
        if not isinstance(gap, dict) or set(gap) != {
            "field",
            "queries",
            "candidate_urls",
        }:
            raise ValueError("invalid Standard gap proposal")
        field = gap["field"]
        if (
            not isinstance(field, str)
            or field not in handoff["unresolved_fields"]
            or field in seen
        ):
            raise ValueError("Standard gap omitted, duplicated or invented")
        seen.add(field)
        if not isinstance(gap["queries"], list) or not isinstance(
            gap["candidate_urls"], list
        ):
            raise ValueError("invalid Standard query/candidate plan")
        if len(gap["queries"]) > 4 or len(gap["candidate_urls"]) > 12:
            raise ValueError("oversized Standard gap proposal")
        for query in gap["queries"]:
            if (
                not isinstance(query, str)
                or not query.strip()
                or query != query.strip()
                or len(query) > 400
            ):
                raise ValueError("invalid Standard planned query")
            queries.add(query)
        for url in gap["candidate_urls"]:
            if not isinstance(url, str) or not public_url(url) or url not in discovered:
                raise ValueError("Standard planner cannot invent undiscovered URLs")
            candidates.add(url)
    if (
        seen != set(handoff["unresolved_fields"])
        or len(queries) > 4
        or len(candidates) > 12
    ):
        raise ValueError("Standard plan coverage or size mismatch")
    return deepcopy(proposal)


def action(kind: str, target: str, fields: list[str], *, origin: str) -> dict:
    identifier = hashlib.sha256(json.dumps([kind, target]).encode()).hexdigest()
    return {
        "id": identifier,
        "kind": kind,
        "target": target,
        "fields": sorted(set(fields)),
        "origin": origin,
    }


def initial_actions(plan: dict, handoff: dict) -> list[dict]:
    actions: dict[str, dict] = {}

    def append(kind: str, target: str, fields: list[str], origin: str) -> None:
        item = action(kind, target, fields, origin=origin)
        if item["id"] in actions:
            item["fields"] = sorted(set(item["fields"] + actions[item["id"]]["fields"]))
            item["origin"] = actions[item["id"]]["origin"]
        actions[item["id"]] = item

    for call in handoff["usable_sources"]:
        append("read", call["arguments"]["url"], handoff["unresolved_fields"], "lookup")
    for gap in plan["gaps"]:
        for url in gap["candidate_urls"]:
            append("read", url, [gap["field"]], "candidate")
    for gap in plan["gaps"]:
        for query in gap["queries"]:
            append("search", query, [gap["field"]], "plan")
    return list(actions.values())


def build_result(ledger: dict, handoff: dict, reason: str) -> dict:
    research = ledger["research"]
    observations = research["observations"]
    acquired, reused = [], []
    gap_states: dict[str, dict] = {
        field: {
            "research_state": "OPEN",
            "support_status": "NOT_EVALUATED",
            "source_urls": [],
        }
        for field in handoff["unresolved_fields"]
    }
    for observation in observations:
        if observation["kind"] != "read" or not observation["readable"]:
            continue
        source = {
            "url": observation["target"],
            "content_sha256": observation["content_sha256"],
        }
        if observation["origin"] == "standard":
            acquired.append(source)
        if observation["reused"]:
            reused.append(source)
        for field in observation["fields"]:
            gap_states[field]["research_state"] = "SOURCE_ACQUIRED"
            gap_states[field]["source_urls"].append(observation["target"])
    return {
        "schema": RESULT_SCHEMA,
        "run_parent_turn_id": ledger["parent_turn_id"],
        "source_run_id": ledger["source_run_id"],
        "handoff_sha256": ledger["handoff_sha256"],
        "plan": deepcopy(research["plan"]),
        "gap_states": gap_states,
        "known_assertion_refs": deepcopy(handoff["known"]),
        "acquired_sources": acquired,
        "reused_sources": reused,
        "read_outcomes": deepcopy(
            [row for row in observations if row["kind"] == "read"]
        ),
        "unresolved_gaps": list(handoff["unresolved_fields"]),
        "conflicts": [],
        "budget_consumed": {
            "new_reads": ledger["new_reads"],
            "new_queries": ledger["new_queries"],
            "planner_calls": research["planner_calls"],
        },
        "stop_reason": reason,
        "publication_authority": False,
    }
