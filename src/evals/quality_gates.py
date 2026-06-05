from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.mode_manager import RuntimeModes, is_memory_write_allowed
from src.news.domain_policy import evaluate_domain_policy
from src.news.url_normalizer import build_url_metadata, is_public_http_url
from src.tools.local_knowledge import should_retrieve_local_knowledge


@dataclass(frozen=True)
class EvalCheckResult:
    name: str
    passed: bool
    failures: tuple[str, ...] = ()


def load_eval_cases(path: str | Path) -> tuple[dict[str, Any], ...]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    cases = data.get("cases", data)
    if not isinstance(cases, list):
        raise ValueError("Eval fixture must be a list or contain a 'cases' list")
    return tuple(dict(item) for item in cases)


def _as_str_tuple(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,)
    return tuple(str(item) for item in value)


def _result(name: str, failures: list[str]) -> EvalCheckResult:
    return EvalCheckResult(name=name, passed=not failures, failures=tuple(failures))


def evaluate_answer_grounding_case(case: dict[str, Any]) -> EvalCheckResult:
    answer = str(case.get("answer", ""))
    failures: list[str] = []

    for citation in _as_str_tuple(case.get("required_citations")):
        if citation not in answer:
            failures.append(f"missing citation: {citation}")

    for phrase in _as_str_tuple(case.get("required_phrases")):
        if phrase.lower() not in answer.lower():
            failures.append(f"missing required phrase: {phrase}")

    for claim in _as_str_tuple(case.get("forbidden_claims")):
        if claim.lower() in answer.lower():
            failures.append(f"forbidden claim present: {claim}")

    return _result(str(case.get("id", "answer_grounding")), failures)


def evaluate_tool_routing_case(case: dict[str, Any]) -> EvalCheckResult:
    should_retrieve, reason = should_retrieve_local_knowledge(str(case.get("input", "")))
    expected_retrieve = bool(case.get("expected_retrieve"))
    expected_reason = str(case.get("expected_reason", ""))
    failures: list[str] = []

    if should_retrieve != expected_retrieve:
        failures.append(f"expected retrieve={expected_retrieve}, got {should_retrieve}")
    if expected_reason and reason != expected_reason:
        failures.append(f"expected reason={expected_reason}, got {reason}")

    return _result(str(case.get("id", "tool_routing")), failures)


_ALLOWED_STATUS_TRANSITIONS = {
    "pending": {"running", "skipped"},
    "running": {"succeeded", "failed"},
    "succeeded": set(),
    "failed": set(),
    "skipped": set(),
}


def evaluate_workflow_event_case(case: dict[str, Any]) -> EvalCheckResult:
    events = case.get("events", [])
    failures: list[str] = []
    previous_status = str(case.get("initial_status", "pending"))

    if not isinstance(events, list) or not events:
        return EvalCheckResult(
            name=str(case.get("id", "workflow_events")),
            passed=False,
            failures=("workflow case requires non-empty events",),
        )

    for index, event in enumerate(events):
        if not isinstance(event, dict):
            failures.append(f"event {index} is not an object")
            continue

        status = str(event.get("status", ""))
        if status not in _ALLOWED_STATUS_TRANSITIONS:
            failures.append(f"event {index} has unknown status: {status}")
            continue

        allowed_next = _ALLOWED_STATUS_TRANSITIONS.get(previous_status, set())
        if status != previous_status and status not in allowed_next:
            failures.append(f"invalid transition: {previous_status} -> {status}")

        if int(event.get("elapsed_ms", 0)) < 0:
            failures.append(f"event {index} has negative elapsed_ms")
        if not str(event.get("step_id", "")).strip():
            failures.append(f"event {index} missing step_id")
        if not str(event.get("event_type", "")).strip():
            failures.append(f"event {index} missing event_type")
        if status == "failed" and not str(event.get("error", "")).strip():
            failures.append(f"event {index} failed without error")

        previous_status = status

    expected_terminal_status = str(case.get("expected_terminal_status", ""))
    if expected_terminal_status and previous_status != expected_terminal_status:
        failures.append(
            f"expected terminal status={expected_terminal_status}, got {previous_status}"
        )

    return _result(str(case.get("id", "workflow_events")), failures)


def evaluate_memory_safety_case(case: dict[str, Any]) -> EvalCheckResult:
    modes = RuntimeModes(
        memory_mode=str(case.get("memory_mode", "preview")),
        safe_mode=bool(case.get("safe_mode", False)),
    )
    allowed = is_memory_write_allowed(modes)
    expected_allowed = bool(case.get("expected_allowed"))
    failures: list[str] = []

    if allowed != expected_allowed:
        failures.append(f"expected allowed={expected_allowed}, got {allowed}")

    return _result(str(case.get("id", "memory_safety")), failures)


def evaluate_url_safety_case(case: dict[str, Any]) -> EvalCheckResult:
    url = str(case.get("url", ""))
    query = str(case.get("query", ""))
    public = is_public_http_url(url)
    metadata = build_url_metadata(url)
    domain_policy = evaluate_domain_policy(
        {
            "link": url,
            "resolved_link": metadata.resolved_url,
            "canonical_url": metadata.canonical_url,
            "domain": metadata.domain,
        },
        query,
    )
    failures: list[str] = []

    if public != bool(case.get("expected_public")):
        failures.append(f"expected public={case.get('expected_public')}, got {public}")

    expected_status = str(case.get("expected_resolution_status", ""))
    if expected_status and metadata.resolution_status != expected_status:
        failures.append(
            f"expected resolution_status={expected_status}, got {metadata.resolution_status}"
        )

    expected_blocked = case.get("expected_domain_blocked")
    if expected_blocked is not None and domain_policy.blocked != bool(expected_blocked):
        failures.append(
            f"expected domain_blocked={expected_blocked}, got {domain_policy.blocked}"
        )

    return _result(str(case.get("id", "url_safety")), failures)
