"""Bounded GitHub reads. Reports observed gates, never grants merge authority."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import os
import re
import subprocess
import tempfile
import time
from typing import Any
from urllib.parse import quote

from tools.studyctl_ci import MAX_CI_BYTES, valid_sha
from tools.studyctl_recording import invalid_constant, unique_object

MAX_PAGES = 10
MAX_SECONDS = 90
PR_QUERY = """query($owner:String!,$repo:String!,$number:Int!,$cursor:String,$reviewCursor:String){
 repository(owner:$owner,name:$repo){nameWithOwner pullRequest(number:$number){
 number state isDraft headRefOid baseRefOid baseRefName mergeStateStatus reviewDecision
 reviewThreads(first:100,after:$cursor){nodes{id isResolved}
 pageInfo{hasNextPage endCursor}}
 reviews(first:100,after:$reviewCursor){nodes{id state author{login} commit{oid}}
 pageInfo{hasNextPage endCursor}}}}}"""


class Unavailable(ValueError):
    """Only a fixed local reason may cross the CLI boundary."""


def valid_repository(value: str) -> bool:
    return re.fullmatch(
        r"[A-Za-z0-9][A-Za-z0-9-]{0,38}/[A-Za-z0-9_.-]{1,100}", value
    ) is not None and value.split("/")[1] not in {".", ".."}


class GitHub:
    def __init__(self) -> None:
        self.deadline = time.monotonic() + MAX_SECONDS
        self.calls = 0

    def api(
        self,
        endpoint: str,
        *,
        fields: dict[str, Any] | None = None,
        projection: str = ".",
        missing_ok: bool = False,
    ) -> Any:
        remaining = self.deadline - time.monotonic()
        if remaining <= 0 or self.calls >= 80:
            raise Unavailable("collection_budget_exceeded")
        self.calls += 1
        argv = [
            "gh",
            "api",
            "--hostname",
            "github.com",
            "--method",
            "POST" if fields is not None else "GET",
            endpoint,
            "--jq",
            projection,
        ]
        if fields is not None:
            # Only the fixed read-only query above is admitted.
            if endpoint != "graphql" or fields.get("query") != PR_QUERY:
                raise Unavailable("unregistered_query")
            for key, value in fields.items():
                argv.extend(["-F" if type(value) is int else "-f", f"{key}={value}"])
        allowed = {
            "SYSTEMROOT",
            "WINDIR",
            "PATH",
            "PATHEXT",
            "COMSPEC",
            "TEMP",
            "TMP",
            "USERPROFILE",
            "APPDATA",
            "LOCALAPPDATA",
            "HOMEDRIVE",
            "HOMEPATH",
            "GH_TOKEN",
            "GITHUB_TOKEN",
            "GH_CONFIG_DIR",
        }
        env = {
            key: value for key, value in os.environ.items() if key.upper() in allowed
        }
        env.update(GH_PROMPT_DISABLED="1", GH_PAGER="cat")
        with tempfile.TemporaryFile() as output:
            try:
                result = subprocess.run(
                    argv,
                    stdin=subprocess.DEVNULL,
                    stdout=output,
                    stderr=subprocess.DEVNULL,
                    env=env,
                    timeout=min(15, remaining),
                    check=False,
                )
            except (OSError, subprocess.TimeoutExpired):
                raise Unavailable("github_transport_unavailable") from None
            output.seek(0)
            raw = output.read(MAX_CI_BYTES + 1)
        if len(raw) > MAX_CI_BYTES:
            raise Unavailable("github_response_budget_exceeded")
        try:
            data = json.loads(
                raw, object_pairs_hook=unique_object, parse_constant=invalid_constant
            )
        except (ValueError, UnicodeError, RecursionError):
            raise Unavailable("github_response_invalid") from None
        if result.returncode:
            if missing_ok and isinstance(data, dict) and data.get("status") == "404":
                return None
            raise Unavailable("github_permission_or_api_failure")
        if isinstance(data, dict) and data.get("errors"):
            raise Unavailable("github_graphql_incomplete")
        return data

    def pages(
        self,
        endpoint: str,
        key: str | None,
        projection: str,
        *,
        identity_key: str | None = "id",
    ) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        total: int | None = None
        for page in range(1, MAX_PAGES + 1):
            separator = "&" if "?" in endpoint else "?"
            data = self.api(
                f"{endpoint}{separator}per_page=100&page={page}", projection=projection
            )
            batch = data.get(key) if key and isinstance(data, dict) else data
            if not isinstance(batch, list) or any(
                not isinstance(x, dict) for x in batch
            ):
                raise Unavailable("github_page_invalid")
            if key:
                count = data.get("total_count")
                if (
                    type(count) is not int
                    or count < 0
                    or (total is not None and count != total)
                ):
                    raise Unavailable("github_page_count_changed")
                total = count
            items.extend(batch)
            if len(batch) < 100:
                if total is not None and len(items) != total:
                    raise Unavailable("github_pages_incomplete")
                ids = (
                    [x.get(identity_key) for x in items]
                    if identity_key
                    else [json.dumps(x, sort_keys=True) for x in items]
                )
                if (identity_key and any(type(x) is not int for x in ids)) or len(
                    ids
                ) != len(set(ids)):
                    raise Unavailable("github_page_identity_invalid")
                return items
        raise Unavailable("github_page_budget_exceeded")


def pr_state(api: GitHub, repository: str, number: int) -> dict[str, Any]:
    owner, repo = repository.split("/")
    fields: dict[str, Any] = dict(query=PR_QUERY, owner=owner, repo=repo, number=number)
    threads: list[dict[str, Any]] = []
    reviews: list[dict[str, Any]] = []
    first = None
    cursors: dict[str, set[str]] = {"cursor": set(), "reviewCursor": set()}
    done: set[str] = set()
    for _ in range(MAX_PAGES):
        data = api.api("graphql", fields=fields)
        record = data["data"]["repository"]
        if record["nameWithOwner"].lower() != repository.lower():
            raise Unavailable("repository_identity_mismatch")
        current = dict(record["pullRequest"])
        connection = current.pop("reviewThreads")
        review_connection = current.pop("reviews")
        if first is not None and first != current:
            raise Unavailable("pr_changed_during_pagination")
        first = current
        for key, stream, destination in (
            ("cursor", connection, threads),
            ("reviewCursor", review_connection, reviews),
        ):
            if key in done:
                continue
            nodes = stream["nodes"]
            if not isinstance(nodes, list) or any(
                not isinstance(x, dict) or not isinstance(x.get("id"), str)
                for x in nodes
            ):
                raise Unavailable("review_page_invalid")
            if key == "cursor" and any(
                type(x.get("isResolved")) is not bool for x in nodes
            ):
                raise Unavailable("review_page_invalid")
            destination.extend(nodes)
            info = stream["pageInfo"]
            if info["hasNextPage"] is False:
                if len({x["id"] for x in destination}) != len(destination):
                    raise Unavailable("review_page_identity_invalid")
                done.add(key)
                continue
            cursor = info.get("endCursor")
            if (
                info["hasNextPage"] is not True
                or not isinstance(cursor, str)
                or not cursor
                or cursor in cursors[key]
            ):
                raise Unavailable("review_cursor_invalid")
            cursors[key].add(cursor)
            fields[key] = cursor
        if len(done) == 2:
            return {**current, "reviewThreads": threads, "reviews": reviews}
    raise Unavailable("review_page_budget_exceeded")


def policy(api: GitHub, repository: str, branch: str) -> dict[str, Any]:
    prefix = f"repos/{repository}"
    metadata = api.api(
        prefix, projection="{full_name,permissions:{admin:.permissions.admin}}"
    )
    if metadata["full_name"].lower() != repository.lower():
        raise Unavailable("repository_identity_mismatch")
    encoded = quote(branch, safe="")
    ref = api.api(
        f"{prefix}/branches/{encoded}",
        projection="{name,protected,commit:{sha:.commit.sha}}",
    )
    protection = api.api(f"{prefix}/branches/{encoded}/protection", missing_ok=True)
    # Effective rules have no per-rule id; preserve all fields for page identity.
    rules = api.pages(
        f"{prefix}/rules/branches/{encoded}", None, ".", identity_key=None
    )
    if ref.get("name") != branch or not valid_sha(ref["commit"]["sha"]):
        raise Unavailable("base_branch_identity_invalid")
    # An inaccessible protection endpoint must never be interpreted as no policy.
    if protection is None and (
        ref.get("protected") is not False
        or metadata["permissions"].get("admin") is not True
    ):
        raise Unavailable("protection_absence_not_verified")
    if not isinstance(rules, list) or any(not isinstance(x, dict) for x in rules):
        raise Unavailable("effective_rules_invalid")
    return dict(
        branch=branch, base_sha=ref["commit"]["sha"], protection=protection, rules=rules
    )


def check_inventory(api: GitHub, repository: str, head: str) -> dict[str, Any]:
    prefix = f"repos/{repository}"
    checks = api.pages(
        f"{prefix}/commits/{head}/check-runs?filter=latest",
        "check_runs",
        "{total_count,check_runs:[.check_runs[]|{id,name,status,conclusion,head_sha,app:{id:.app.id},check_suite:{id:.check_suite.id}}]}",
    )
    statuses = api.pages(
        f"{prefix}/commits/{head}/statuses", None, "[.[]|{id,context,state,sha}]"
    )
    runs = api.pages(
        f"{prefix}/actions/runs?head_sha={head}",
        "workflow_runs",
        "{total_count,workflow_runs:[.workflow_runs[]|{id,name,event,head_sha,status,conclusion,check_suite_id,pull_requests:[.pull_requests[]|{number}]}]}",
    )
    if any(x.get("head_sha") != head for x in checks + runs) or any(
        x.get("sha") != head for x in statuses
    ):
        raise Unavailable("check_head_mismatch")
    return dict(checks=checks, statuses=statuses, runs=runs)


def evaluate(observed: dict[str, Any], project_checks: list[str]) -> dict[str, Any]:
    """Evaluate collected facts only. Local callers still own acceptance and merge."""
    gaps: list[str] = []
    failures: list[str] = []
    policy_data = observed["policy"]
    required: list[tuple[str, int | None]] = [(x, None) for x in project_checks]
    protection = policy_data["protection"] or {}
    settings = protection.get("required_status_checks") or {}
    if settings.get("checks"):
        required.extend((x["context"], x.get("app_id")) for x in settings["checks"])
    else:
        required.extend((x, None) for x in settings.get("contexts", []))
    for rule in policy_data["rules"]:
        kind = rule.get("type")
        if kind == "required_status_checks":
            required.extend(
                (x["context"], x.get("integration_id"))
                for x in rule["parameters"]["required_status_checks"]
            )
        elif kind not in {
            "pull_request",
            "creation",
            "update",
            "deletion",
            "non_fast_forward",
            "required_linear_history",
            "required_signatures",
            "required_conversation_resolution",
        }:
            gaps.append("unsupported_additional_gate")
    if not required:
        gaps.append("no_required_check_contract")
    latest_status: dict[str, dict[str, Any]] = {}
    for item in observed["statuses"]:
        if (
            item["context"] not in latest_status
            or item["id"] > latest_status[item["context"]]["id"]
        ):
            latest_status[item["context"]] = item
    selected = []
    for name, app in sorted(set(required), key=lambda x: (x[0], x[1] or -1)):
        if (
            not isinstance(name, str)
            or not name
            or (app is not None and type(app) is not int)
        ):
            raise Unavailable("required_check_policy_invalid")
        matches = [
            x
            for x in observed["checks"]
            if x["name"] == name and (app in (None, -1) or x["app"]["id"] == app)
        ]
        if app in (None, -1) and name in latest_status:
            matches.append(latest_status[name])
        if len(matches) != 1:
            gaps.append("required_check_missing_or_ambiguous")
            continue
        check = matches[0]
        selected.append(dict(name=name, app_id=app, id=check["id"]))
        if "state" in check:
            state = check["state"]
        else:
            state = check["conclusion"] if check["status"] == "completed" else "pending"
            if check["app"]["id"] == 15368:
                runs = [
                    x
                    for x in observed["runs"]
                    if x["check_suite_id"] == check["check_suite"]["id"]
                ]
                if (
                    len(runs) != 1
                    or runs[0]["event"] != observed["event"]
                    or (
                        observed["event"] == "pull_request"
                        and observed["pr"]
                        not in [x["number"] for x in runs[0]["pull_requests"]]
                    )
                ):
                    gaps.append("required_workflow_event_mismatch")
                    # A failure belonging to another event/PR is not evidence
                    # that this requested PR or main gate executed and failed.
                    continue
                elif (
                    runs[0]["status"] != "completed"
                    or runs[0]["conclusion"] != "success"
                ):
                    gaps.append("required_workflow_not_successful")
        if state in {
            "failure",
            "error",
            "cancelled",
            "timed_out",
            "action_required",
            "startup_failure",
        }:
            failures.append("required_check_failed")
        elif state != "success":
            gaps.append("required_check_not_successful")
    if observed["event"] == "pull_request":
        pr = observed["pull_request"]
        if (
            pr["state"] != "OPEN"
            or pr["isDraft"] is not False
            or pr["mergeStateStatus"] != "CLEAN"
        ):
            gaps.append("pr_not_mergeable")
        if pr["reviewDecision"] not in (None, "", "APPROVED"):
            gaps.append("review_not_approved")
        if any(not x["isResolved"] for x in pr["reviewThreads"]):
            gaps.append("unresolved_review_threads")
        latest_reviews: dict[str, str] = {}
        for review in pr["reviews"]:
            state = review["state"]
            if state not in {
                "PENDING",
                "COMMENTED",
                "APPROVED",
                "CHANGES_REQUESTED",
                "DISMISSED",
            }:
                raise Unavailable("review_state_invalid")
            if state in {"APPROVED", "CHANGES_REQUESTED", "DISMISSED"}:
                author = review.get("author")
                if not isinstance(author, dict) or not isinstance(
                    author.get("login"), str
                ):
                    raise Unavailable("review_author_unavailable")
                latest_reviews[author["login"]] = state
        if "CHANGES_REQUESTED" in latest_reviews.values():
            gaps.append("review_changes_requested")
        needs_review = bool(protection.get("required_pull_request_reviews")) or any(
            x.get("type") == "pull_request" for x in policy_data["rules"]
        )
        if needs_review and pr["reviewDecision"] != "APPROVED":
            gaps.append("required_review_not_approved")
    status, code = (
        ("FAIL", 4) if failures else (("BLOCKED", 3) if gaps else ("PASS", 0))
    )
    return dict(
        status=status,
        exit_code=code,
        merge_authorized=False,
        verification_scope="live GitHub required checks and recorded review gates only",
        required_checks=selected,
        project_required_checks=project_checks,
        errors=[
            dict(code=x, message=x.replace("_", " "))
            for x in sorted(set(failures + gaps))
        ],
    )


def collect(
    repository: str,
    head: str,
    *,
    pr: int | None = None,
    project_checks: list[str],
    api: GitHub | None = None,
) -> dict[str, Any]:
    if (
        not valid_repository(repository)
        or not valid_sha(head)
        or (pr is not None and (type(pr) is not int or pr <= 0))
    ):
        raise Unavailable("invalid_github_selector")
    if len(project_checks) > 20 or any(
        not isinstance(x, str) or not x or len(x) > 150 or any(ord(c) < 32 for c in x)
        for x in project_checks
    ):
        raise Unavailable("invalid_project_check_contract")
    client = api or GitHub()
    started = datetime.now(timezone.utc).isoformat()
    first = pr_state(client, repository, pr) if pr else None
    if first is not None and (first["number"] != pr or first["headRefOid"] != head):
        raise Unavailable("pr_head_mismatch")
    branch = first["baseRefName"] if first else "main"
    before = policy(client, repository, branch)
    if (first and first["baseRefOid"] != before["base_sha"]) or (
        not first and before["base_sha"] != head
    ):
        raise Unavailable("base_or_main_head_mismatch")
    inventory = check_inventory(client, repository, head)
    last = pr_state(client, repository, pr) if pr else None
    after = policy(client, repository, branch)
    if first != last or before != after:
        raise Unavailable("github_state_changed_during_collection")
    observed = dict(
        repository=repository,
        expected_head_sha=head,
        pr=pr,
        event="pull_request" if pr else "push",
        policy=before,
        pull_request=first,
        **inventory,
    )
    return dict(
        schema="studyctl-github-live-v1",
        started_at=started,
        completed_at=datetime.now(timezone.utc).isoformat(),
        api_calls=client.calls,
        **observed,
        **evaluate(observed, project_checks),
    )
