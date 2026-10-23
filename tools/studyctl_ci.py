"""Replay recorded CI facts; never turn an offline receipt into merge authority."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
from typing import Any

from tools.check_ci_outcomes import failed_steps
from tools.studyctl_recording import invalid_constant, unique_object

MAX_CI_BYTES = 2 * 1024 * 1024


def read_evidence(path: Path) -> tuple[dict[str, Any], str]:
    if not path.is_file():
        raise ValueError("evidence unavailable")
    with path.open("rb") as file:
        raw = file.read(MAX_CI_BYTES + 1)
    if len(raw) > MAX_CI_BYTES:
        raise ValueError("evidence budget exceeded")
    data = json.loads(
        raw.decode("utf-8-sig"),
        object_pairs_hook=unique_object,
        parse_constant=invalid_constant,
    )
    if not isinstance(data, dict):
        raise ValueError("evidence must be an object")
    return data, hashlib.sha256(raw).hexdigest()


def valid_sha(value: Any) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{40}", value) is not None


def inspect_ci_snapshot(
    path: Path, repository: str, pr: int, expected_head: str
) -> dict[str, Any]:
    if (
        not isinstance(repository, str)
        or re.fullmatch(r"[A-Za-z0-9_.-]{1,100}/[A-Za-z0-9_.-]{1,100}", repository)
        is None
        or type(pr) is not int
        or pr <= 0
    ):
        raise ValueError("invalid PR selector")
    data, digest = read_evidence(path)
    if not valid_sha(expected_head):
        raise ValueError("expected full commit SHA")
    checks, prs = data.get("checks"), data.get("prs")
    if not isinstance(checks, list) or not isinstance(prs, dict):
        raise ValueError("unsupported snapshot shape")
    selected = [
        row
        for row in checks
        if isinstance(row, dict)
        and row.get("repo") == repository
        and row.get("pr") == pr
    ]
    candidates = [
        item
        for group in prs.values()
        if isinstance(group, dict)
        for item in group.values()
        if isinstance(item, dict)
        and item.get("number") == pr
        and item.get("url") == f"https://github.com/{repository}/pull/{pr}"
    ]
    if len(selected) != 1 or len(candidates) != 1:
        raise ValueError("PR identity unavailable or ambiguous")
    observed, metadata = selected[0], candidates[0]
    if not valid_sha(metadata.get("headRefOid")) or not valid_sha(observed.get("head")):
        raise ValueError("invalid recorded head")
    gaps = [
        "required_check_policy_not_captured",
        "check_contexts_not_captured",
        "live_freshness_not_verified",
        "merge_main_evidence_not_captured",
    ]
    matches = metadata.get("headRefOid") == observed.get("head") == expected_head
    if not matches:
        gaps.append("pr_head_mismatch")
    if metadata.get("state") not in {"OPEN", "CLOSED", "MERGED"}:
        raise ValueError("invalid recorded PR state")
    if metadata["state"] != "OPEN":
        gaps.append("recorded_pr_not_open")
    threads = metadata.get("reviewThreads")
    if (
        not isinstance(threads, dict)
        or not isinstance(threads.get("nodes"), list)
        or not isinstance(threads.get("pageInfo"), dict)
    ):
        raise ValueError("review inventory unavailable")
    complete = threads["pageInfo"].get("hasNextPage") is False
    if not complete:
        gaps.append("review_inventory_incomplete")
    nodes = threads["nodes"]
    if any(
        not isinstance(node, dict) or type(node.get("isResolved")) is not bool
        for node in nodes
    ):
        raise ValueError("invalid review inventory")
    unresolved = sum(not node["isResolved"] for node in nodes)
    if unresolved:
        gaps.append("unresolved_review_threads")
    runs = observed.get("runs")
    if not isinstance(runs, list):
        raise ValueError("run inventory unavailable")
    rows = []
    for run in runs:
        if (
            not isinstance(run, dict)
            or type(run.get("databaseId")) is not int
            or run["databaseId"] <= 0
        ):
            raise ValueError("invalid workflow identity")
        if run.get("headSha") != expected_head:
            gaps.append("workflow_head_mismatch")
        if not valid_sha(run.get("headSha")):
            raise ValueError("invalid recorded workflow head")
        if not isinstance(run.get("event"), str) or run["event"] not in {
            "pull_request",
            "push",
            "workflow_dispatch",
            "schedule",
            "pull_request_target",
            "workflow_run",
            "merge_group",
        }:
            raise ValueError("invalid recorded workflow event")
        if run.get("event") != "pull_request":
            gaps.append("workflow_event_mismatch")
        status, conclusion = run.get("status"), run.get("conclusion")
        if status not in {
            "queued",
            "in_progress",
            "completed",
            "waiting",
            "requested",
            "pending",
        }:
            raise ValueError("unknown workflow status")
        if conclusion not in {
            None,
            "",
            "success",
            "failure",
            "cancelled",
            "timed_out",
            "action_required",
            "skipped",
            "neutral",
            "stale",
            "startup_failure",
        }:
            raise ValueError("unknown workflow conclusion")
        rows.append(
            {
                "run_id": run["databaseId"],
                "head_sha": run.get("headSha"),
                "event": run.get("event"),
                "status": status,
                "conclusion": conclusion,
            }
        )
    if len({row["run_id"] for row in rows}) != len(rows):
        raise ValueError("duplicate workflow identity")
    if not rows:
        gaps.append("workflow_runs_missing")
    pending = any(row["status"] != "completed" for row in rows)
    if pending:
        gaps.append("recorded_workflow_pending")
    failed = any(
        matches
        and row["head_sha"] == expected_head
        and row["event"] == "pull_request"
        and row["status"] == "completed"
        and row["conclusion"]
        in {
            "failure",
            "cancelled",
            "timed_out",
            "action_required",
            "stale",
            "startup_failure",
        }
        for row in rows
    )
    if any(
        row["status"] == "completed" and row["conclusion"] != "success" for row in rows
    ):
        gaps.append("recorded_workflow_not_successful")
    # Attribution belongs to each run. Unrelated evidence remains a gap but
    # cannot erase a known failure from the requested PR head and event.
    code = 4 if failed else 3
    return {
        "status": "FAIL" if code == 4 else "BLOCKED",
        "exit_code": code,
        "errors": [
            {
                "code": "recorded_ci_failed" if code == 4 else "ci_evidence_incomplete",
                "message": "Recorded CI failure."
                if code == 4
                else "Recorded evidence cannot establish current CI or merge readiness.",
            }
        ],
        "github_repository": repository,
        "pr": pr,
        "expected_head_sha": expected_head,
        "observed_head_sha": metadata.get("headRefOid"),
        "head_matches": matches,
        "snapshot_sha256": digest,
        "runs": rows,
        "unresolved_review_threads": unresolved,
        "review_inventory_complete": complete,
        "missing_evidence": sorted(set(gaps)),
        "verification_scope": "historical recorded facts only",
        "merge_authorized": False,
    }


def replay_outcomes(
    path: Path, expected_head: str, run_id: int, event: str
) -> dict[str, Any]:
    data, digest = read_evidence(path)
    if (
        not valid_sha(expected_head)
        or data.get("schema_version") != "studyctl-ci-outcomes-v1"
    ):
        raise ValueError("invalid outcome receipt")
    if (
        data.get("head_sha") != expected_head
        or type(data.get("run_id")) is not int
        or data["run_id"] != run_id
        or run_id <= 0
        or data.get("event") != event
        or event not in {"pull_request", "push"}
    ):
        raise ValueError("outcome receipt identity mismatch")
    frontend, browser, steps = (
        data.get("frontend_required"),
        data.get("browser_required"),
        data.get("steps"),
    )
    if (
        type(frontend) is not bool
        or type(browser) is not bool
        or not isinstance(steps, dict)
    ):
        raise ValueError("routing and raw outcomes are required")
    if any(
        not isinstance(value, dict)
        or value.get("outcome") not in {"success", "failure", "cancelled", "skipped"}
        for value in steps.values()
    ):
        raise ValueError("invalid raw step outcomes")
    failures = failed_steps(steps, browser_required=browser, frontend_required=frontend)
    return {
        "status": "FAIL" if failures else "PASS",
        "exit_code": 4 if failures else 0,
        "errors": [
            {
                "code": "recorded_step_outcomes_failed",
                "message": "Required raw CI outcomes did not pass.",
            }
        ]
        if failures
        else [],
        "receipt_sha256": digest,
        "expected_head_sha": expected_head,
        "run_id": run_id,
        "event": event,
        "failed_steps": failures,
        "frontend_required": frontend,
        "browser_required": browser,
        "verification_scope": "supplied raw outcome receipt only; authenticity not verified",
        "merge_authorized": False,
    }
