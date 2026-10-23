"""Offline CI facts and raw outcomes cannot imply live merge authorization."""

import json

import pytest

from tools.check_ci_outcomes import REQUIRED_STEPS
from tools.studyctl_ci import inspect_ci_snapshot, replay_outcomes

HEAD = "a" * 40
REPOSITORY = "owner/project"


@pytest.fixture
def snapshot(tmp_path):
    path = tmp_path / "snapshot.json"
    path.write_text(
        json.dumps(
            {
                "prs": {
                    "repository": {
                        "p7": {
                            "number": 7,
                            "url": "https://github.com/owner/project/pull/7",
                            "state": "OPEN",
                            "headRefOid": HEAD,
                            "reviewThreads": {
                                "pageInfo": {"hasNextPage": False},
                                "nodes": [],
                            },
                        }
                    }
                },
                "checks": [
                    {
                        "repo": REPOSITORY,
                        "pr": 7,
                        "head": HEAD,
                        "runs": [
                            {
                                "databaseId": 42,
                                "headSha": HEAD,
                                "event": "pull_request",
                                "status": "completed",
                                "conclusion": "success",
                            }
                        ],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    return path


def change(path, callback):
    data = json.loads(path.read_bytes())
    callback(data)
    path.write_text(json.dumps(data), encoding="utf-8")


def inspect(path):
    return inspect_ci_snapshot(path, REPOSITORY, 7, HEAD)


def test_green_recording_is_blocked_on_missing_policy_and_freshness(snapshot):
    before = snapshot.read_bytes()
    result = inspect(snapshot)
    assert result["head_matches"] and result["runs"][0]["conclusion"] == "success"
    assert result["status"] == "BLOCKED" and result["exit_code"] == 3
    assert "required_check_policy_not_captured" in result["missing_evidence"]
    assert "live_freshness_not_verified" in result["missing_evidence"]
    assert not result["merge_authorized"] and snapshot.read_bytes() == before


@pytest.mark.parametrize(
    "field",
    [
        "pr_head",
        "run_head",
        "event",
        "pending",
        "review",
        "review_page",
        "missing_runs",
    ],
)
def test_identity_pending_and_review_gaps_remain_explicit(snapshot, field):
    def update(data):
        pr = data["prs"]["repository"]["p7"]
        run = data["checks"][0]["runs"][0]
        if field == "pr_head":
            pr["headRefOid"] = "b" * 40
        elif field == "run_head":
            run["headSha"] = "b" * 40
        elif field == "event":
            run["event"] = "push"
        elif field == "pending":
            run.update(status="in_progress", conclusion="")
        elif field == "review":
            pr["reviewThreads"]["nodes"] = [
                {"isResolved": False, "comments": {"body": "private-review-body"}}
            ]
        elif field == "review_page":
            pr["reviewThreads"]["pageInfo"]["hasNextPage"] = True
        else:
            data["checks"][0]["runs"] = []

    change(snapshot, update)
    result = inspect(snapshot)
    assert result["status"] == "BLOCKED" and len(result["missing_evidence"]) > 4
    assert "private-review-body" not in json.dumps(result)


def test_wrong_head_failure_cannot_be_attributed_to_requested_head(snapshot):
    change(
        snapshot,
        lambda data: data["checks"][0]["runs"][0].update(
            headSha="b" * 40, conclusion="failure"
        ),
    )
    assert inspect(snapshot)["status"] == "BLOCKED"


def test_exact_head_recorded_failure_is_reported_but_not_merge_authority(snapshot):
    change(
        snapshot, lambda data: data["checks"][0]["runs"][0].update(conclusion="failure")
    )
    result = inspect(snapshot)
    assert result["status"] == "FAIL" and result["exit_code"] == 4
    assert not result["merge_authorized"]


@pytest.mark.parametrize(
    ("other_head", "event", "conclusion", "status"),
    [
        (HEAD, "push", "success", "completed"),
        (HEAD, "push", "failure", "completed"),
        ("b" * 40, "pull_request", "success", "completed"),
        ("b" * 40, "pull_request", "failure", "completed"),
        (HEAD, "push", "", "in_progress"),
    ],
)
def test_exact_pr_failure_survives_unrelated_run_evidence(
    snapshot, other_head, event, conclusion, status
):
    def update(data):
        runs = data["checks"][0]["runs"]
        runs[0]["conclusion"] = "failure"
        runs.append(
            dict(
                databaseId=43,
                headSha=other_head,
                event=event,
                status=status,
                conclusion=conclusion,
            )
        )

    change(snapshot, update)
    before = snapshot.read_bytes()
    result = inspect(snapshot)
    assert result["status"] == "FAIL" and result["exit_code"] == 4
    assert len(result["runs"]) == 2 and not result["merge_authorized"]
    assert "live_freshness_not_verified" in result["missing_evidence"]
    assert snapshot.read_bytes() == before


@pytest.mark.parametrize(
    ("other_head", "event"), [(HEAD, "push"), ("b" * 40, "pull_request")]
)
def test_unrelated_failure_does_not_taint_exact_pr_success(snapshot, other_head, event):
    def update(data):
        data["checks"][0]["runs"].append(
            dict(
                databaseId=43,
                headSha=other_head,
                event=event,
                status="completed",
                conclusion="failure",
            )
        )

    change(snapshot, update)
    result = inspect(snapshot)
    assert result["status"] == "BLOCKED" and result["exit_code"] == 3
    assert not result["merge_authorized"]


def test_mismatched_pr_metadata_still_blocks_exact_run_failure(snapshot):
    def update(data):
        data["prs"]["repository"]["p7"]["headRefOid"] = "b" * 40
        data["checks"][0]["runs"][0]["conclusion"] = "failure"

    change(snapshot, update)
    assert inspect(snapshot)["status"] == "BLOCKED"


def test_duplicate_runs_are_not_silently_collapsed(snapshot):
    change(
        snapshot,
        lambda data: data["checks"][0]["runs"].append(data["checks"][0]["runs"][0]),
    )
    with pytest.raises(ValueError):
        inspect(snapshot)


def test_unknown_event_payload_is_rejected_instead_of_echoed(snapshot):
    change(
        snapshot,
        lambda data: data["checks"][0]["runs"][0].update(
            event={"private": "do-not-emit"}
        ),
    )
    with pytest.raises(ValueError):
        inspect(snapshot)


@pytest.mark.parametrize("conclusion", [None, "", "skipped", "neutral"])
def test_missing_or_non_success_conclusion_does_not_invent_execution_failure(
    snapshot, conclusion
):
    change(
        snapshot,
        lambda data: data["checks"][0]["runs"][0].update(conclusion=conclusion),
    )
    result = inspect(snapshot)
    assert result["status"] == "BLOCKED"
    assert "recorded_workflow_not_successful" in result["missing_evidence"]


@pytest.fixture
def receipt(tmp_path):
    path = tmp_path / "outcomes.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": "studyctl-ci-outcomes-v1",
                "head_sha": HEAD,
                "run_id": 42,
                "event": "pull_request",
                "frontend_required": False,
                "browser_required": False,
                "steps": {
                    step: {
                        "outcome": "success",
                        "conclusion": "success",
                        "outputs": {"private": "do-not-emit"},
                    }
                    for step in REQUIRED_STEPS
                },
            }
        ),
        encoding="utf-8",
    )
    return path


def replay(path):
    return replay_outcomes(path, HEAD, 42, "pull_request")


def test_outcome_replay_pass_is_narrow_and_does_not_copy_outputs(receipt):
    result = replay(receipt)
    assert result["status"] == "PASS" and result["exit_code"] == 0
    assert (
        not result["merge_authorized"]
        and "authenticity not verified" in result["verification_scope"]
    )
    assert "do-not-emit" not in json.dumps(result)


def test_continue_on_error_success_conclusion_does_not_hide_failure(receipt):
    change(
        receipt,
        lambda data: data["steps"]["ruff"].update(
            outcome="failure", conclusion="success"
        ),
    )
    result = replay(receipt)
    assert result["exit_code"] == 4 and result["failed_steps"] == ["ruff"]


@pytest.mark.parametrize("kind", ["head", "run", "event", "routing", "bad_step"])
def test_mismatched_or_malformed_outcome_receipts_reject(receipt, kind):
    def update(data):
        if kind == "head":
            data["head_sha"] = "b" * 40
        elif kind == "run":
            data["run_id"] = 43
        elif kind == "event":
            data["event"] = "push"
        elif kind == "routing":
            data["browser_required"] = "false"
        else:
            data["steps"]["ruff"] = None

    change(receipt, update)
    with pytest.raises(ValueError):
        replay(receipt)


def test_existing_impact_substitution_and_optional_browser_failure_are_reused(receipt):
    def update(data):
        data["steps"]["pytest"]["outcome"] = "skipped"
        data["steps"]["pytest_impact"] = {"outcome": "success"}
        data["steps"]["frontend"]["outcome"] = "skipped"

    change(receipt, update)
    assert replay(receipt)["status"] == "PASS"
    change(
        receipt, lambda data: data["steps"].update(browser_e2e={"outcome": "failure"})
    )
    assert replay(receipt)["failed_steps"] == ["browser_e2e"]
