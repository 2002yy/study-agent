"""GitHub collection fails closed on policy, identity and pagination gaps."""

from copy import deepcopy
import json
import subprocess
from unittest.mock import Mock

import pytest

from tools import studyctl_github as gh

HEAD = "a" * 40
BASE = "b" * 40
REPO = "example/project"


@pytest.fixture
def facts():
    return dict(
        repository=REPO,
        expected_head_sha=HEAD,
        pr=7,
        event="pull_request",
        policy=dict(branch="main", base_sha=BASE, protection=None, rules=[]),
        pull_request=dict(
            number=7,
            state="OPEN",
            isDraft=False,
            headRefOid=HEAD,
            baseRefOid=BASE,
            baseRefName="main",
            mergeStateStatus="CLEAN",
            reviewDecision="",
            reviewThreads=[],
            reviews=[],
        ),
        checks=[
            dict(
                id=1,
                name="test",
                head_sha=HEAD,
                status="completed",
                conclusion="success",
                app=dict(id=15368),
                check_suite=dict(id=21),
            )
        ],
        statuses=[],
        runs=[
            dict(
                id=31,
                name="CI",
                event="pull_request",
                head_sha=HEAD,
                status="completed",
                conclusion="success",
                check_suite_id=21,
                pull_requests=[dict(number=7)],
            )
        ],
    )


def test_explicit_project_contract_can_verify_unprotected_branch(facts):
    result = gh.evaluate(facts, ["test"])
    assert result["status"] == "PASS"
    assert result["merge_authorized"] is False
    assert result["project_required_checks"] == ["test"]
    assert gh.evaluate(facts, [])["status"] == "BLOCKED"


@pytest.mark.parametrize(
    "mutation,expected",
    [
        (lambda x: x["checks"][0].update(conclusion="failure"), "FAIL"),
        (lambda x: x["checks"][0].update(conclusion="skipped"), "BLOCKED"),
        (lambda x: x["checks"][0].update(conclusion="neutral"), "BLOCKED"),
        (lambda x: x["checks"][0].update(status="in_progress"), "BLOCKED"),
        (lambda x: x["checks"].clear(), "BLOCKED"),
        (lambda x: x["checks"].append(deepcopy(x["checks"][0])), "BLOCKED"),
        (lambda x: x["runs"][0].update(event="push"), "BLOCKED"),
        (lambda x: x["runs"][0].update(check_suite_id=99), "BLOCKED"),
        (lambda x: x["runs"][0].update(pull_requests=[dict(number=8)]), "BLOCKED"),
        (lambda x: x["runs"][0].update(conclusion="failure"), "BLOCKED"),
        (lambda x: x["pull_request"].update(mergeStateStatus="BEHIND"), "BLOCKED"),
        (lambda x: x["pull_request"].update(isDraft=True), "BLOCKED"),
        (lambda x: x["pull_request"].update(state="CLOSED"), "BLOCKED"),
        (
            lambda x: x["pull_request"].update(reviewDecision="CHANGES_REQUESTED"),
            "BLOCKED",
        ),
        (
            lambda x: x["pull_request"]["reviewThreads"].append(
                dict(id="T1", isResolved=False)
            ),
            "BLOCKED",
        ),
        (
            lambda x: x["policy"]["rules"].append(dict(type="new_unknown_gate")),
            "BLOCKED",
        ),
        (
            lambda x: x["policy"].update(
                protection=dict(
                    required_pull_request_reviews=dict(
                        required_approving_review_count=1
                    )
                )
            ),
            "BLOCKED",
        ),
    ],
)
def test_gate_does_not_borrow_green_from_other_events_or_missing_policy(
    facts, mutation, expected
):
    mutation(facts)
    assert gh.evaluate(facts, ["test"])["status"] == expected


def test_app_bound_policy_and_review_changes_requested(facts):
    facts["policy"]["rules"] = [
        dict(
            type="required_status_checks",
            parameters=dict(
                required_status_checks=[dict(context="test", integration_id=42)]
            ),
        )
    ]
    assert gh.evaluate(facts, ["test"])["status"] == "BLOCKED"
    facts["policy"]["rules"].clear()
    facts["pull_request"]["reviews"] = [
        dict(id="R1", state="CHANGES_REQUESTED", author=dict(login="reviewer"))
    ]
    assert gh.evaluate(facts, ["test"])["status"] == "BLOCKED"
    facts["pull_request"]["reviews"].append(
        dict(id="R2", state="APPROVED", author=dict(login="reviewer"))
    )
    assert gh.evaluate(facts, ["test"])["status"] == "PASS"


def test_latest_status_replaces_earlier_failure(facts):
    facts["checks"].clear()
    facts["statuses"] = [
        dict(id=2, context="test", state="success", sha=HEAD),
        dict(id=1, context="test", state="failure", sha=HEAD),
    ]
    assert gh.evaluate(facts, ["test"])["status"] == "PASS"


def test_main_requires_push_and_omits_pr_review(facts):
    facts.update(pr=None, event="push", pull_request=None)
    facts["runs"][0].update(event="push", pull_requests=[])
    assert gh.evaluate(facts, ["test"])["status"] == "PASS"
    facts["runs"][0]["event"] = "pull_request"
    assert gh.evaluate(facts, ["test"])["status"] == "BLOCKED"


def collection_mocks(monkeypatch, facts):
    pr = Mock(return_value=facts["pull_request"])
    policy = Mock(return_value=facts["policy"])
    inventory = Mock(
        return_value={key: facts[key] for key in ("checks", "statuses", "runs")}
    )
    monkeypatch.setattr(gh, "pr_state", pr)
    monkeypatch.setattr(gh, "policy", policy)
    monkeypatch.setattr(gh, "check_inventory", inventory)
    return pr, policy, inventory


def test_collect_bookends_identity_and_policy(monkeypatch, facts):
    pr, policy, _ = collection_mocks(monkeypatch, facts)
    result = gh.collect(REPO, HEAD, pr=7, project_checks=["test"])
    assert result["status"] == "PASS"
    assert pr.call_count == policy.call_count == 2
    assert result["started_at"] <= result["completed_at"]


@pytest.mark.parametrize("change", ["head", "base", "policy", "review"])
def test_collect_rejects_changes_during_window(monkeypatch, facts, change):
    pr, policy, _ = collection_mocks(monkeypatch, facts)
    if change in {"head", "base", "review"}:
        later = deepcopy(facts["pull_request"])
        later[
            {"head": "headRefOid", "base": "baseRefOid", "review": "reviewDecision"}[
                change
            ]
        ] = "changed"
        pr.side_effect = [facts["pull_request"], later]
    else:
        later = deepcopy(facts["policy"])
        later["rules"] = [dict(type="pull_request")]
        policy.side_effect = [facts["policy"], later]
    with pytest.raises(gh.Unavailable, match="changed_during"):
        gh.collect(REPO, HEAD, pr=7, project_checks=["test"])


def test_initial_wrong_head_and_main_head_block_before_inventory(monkeypatch, facts):
    _, _, inventory = collection_mocks(monkeypatch, facts)
    with pytest.raises(gh.Unavailable, match="pr_head_mismatch"):
        gh.collect(REPO, BASE, pr=7, project_checks=["test"])
    with pytest.raises(gh.Unavailable, match="main_head_mismatch"):
        gh.collect(REPO, HEAD, project_checks=["test"])
    inventory.assert_not_called()


def test_protection_404_only_absent_with_admin_and_unprotected_ref():
    def client(admin, protected):
        api = Mock()
        api.pages.return_value = []
        api.api.side_effect = [
            dict(full_name=REPO, permissions=dict(admin=admin)),
            dict(name="main", protected=protected, commit=dict(sha=BASE)),
            None,
            [],
        ]
        return api

    assert gh.policy(client(True, False), REPO, "main")["protection"] is None
    for admin, protected in [(False, False), (None, False), (True, True)]:
        with pytest.raises(gh.Unavailable, match="absence_not_verified"):
            gh.policy(client(admin, protected), REPO, "main")


def connection(nodes, more=False, cursor=None):
    return dict(nodes=nodes, pageInfo=dict(hasNextPage=more, endCursor=cursor))


def test_reviews_and_threads_paginate_independently(facts):
    base = {
        k: v
        for k, v in facts["pull_request"].items()
        if k not in {"reviewThreads", "reviews"}
    }

    def page(threads, reviews):
        return dict(
            data=dict(
                repository=dict(
                    nameWithOwner=REPO,
                    pullRequest=dict(**base, reviewThreads=threads, reviews=reviews),
                )
            )
        )

    api = Mock()
    api.api.side_effect = [
        page(
            connection([dict(id="T1", isResolved=True)], True, "c1"),
            connection([], True, "r1"),
        ),
        page(
            connection([dict(id="T2", isResolved=True)]),
            connection([dict(id="R1", state="COMMENTED")], True, "r2"),
        ),
        page(
            connection([dict(id="T2", isResolved=True)]),
            connection([dict(id="R2", state="APPROVED")]),
        ),
    ]
    result = gh.pr_state(api, REPO, 7)
    assert [x["id"] for x in result["reviewThreads"]] == ["T1", "T2"]
    assert [x["id"] for x in result["reviews"]] == ["R1", "R2"]


def test_rest_pages_check_counts_duplicates_and_budget():
    client = gh.GitHub()
    client.api = Mock(
        side_effect=[
            dict(total_count=101, checks=[dict(id=x) for x in range(100)]),
            dict(total_count=101, checks=[dict(id=100)]),
        ]
    )
    assert len(client.pages("endpoint", "checks", ".")) == 101
    client.api = Mock(return_value=dict(total_count=2, checks=[dict(id=1)]))
    with pytest.raises(gh.Unavailable, match="incomplete"):
        client.pages("endpoint", "checks", ".")
    client.api = Mock(return_value=[dict(id=1), dict(id=1)])
    with pytest.raises(gh.Unavailable, match="identity_invalid"):
        client.pages("endpoint", None, ".")


@pytest.mark.parametrize("error", ["permission", "timeout", "malformed", "oversized"])
def test_transport_sanitizes_failures(monkeypatch, error):
    def run(argv, **kwargs):
        if error == "timeout":
            raise subprocess.TimeoutExpired(argv, 1, output="private-token")
        raw = {
            "permission": b'{"message":"private-token","status":"403"}',
            "malformed": b"private-token",
            "oversized": b"x" * (gh.MAX_CI_BYTES + 1),
        }[error]
        kwargs["stdout"].write(raw)
        return subprocess.CompletedProcess(argv, 1 if error == "permission" else 0)

    monkeypatch.setattr(gh.subprocess, "run", run)
    with pytest.raises(gh.Unavailable) as caught:
        gh.GitHub().api("repos/example/project")
    assert "private-token" not in str(caught.value)


def test_transport_is_fixed_host_read_only_no_debug_environment(monkeypatch):
    monkeypatch.setenv("GH_HOST", "evil.example")
    monkeypatch.setenv("GH_DEBUG", "api")

    def run(argv, **kwargs):
        assert argv[:7] == [
            "gh",
            "api",
            "--hostname",
            "github.com",
            "--method",
            "GET",
            "repos/example/project",
        ]
        assert "GH_HOST" not in kwargs["env"] and "GH_DEBUG" not in kwargs["env"]
        assert kwargs["stderr"] == subprocess.DEVNULL
        kwargs["stdout"].write(json.dumps(dict(ok=True)).encode())
        return subprocess.CompletedProcess(argv, 0)

    monkeypatch.setattr(gh.subprocess, "run", run)
    assert gh.GitHub().api("repos/example/project") == dict(ok=True)
    with pytest.raises(gh.Unavailable, match="unregistered_query"):
        gh.GitHub().api("graphql", fields=dict(query="mutation {danger}"))


def test_budget_and_invalid_selectors_do_not_start_transport(monkeypatch):
    run = Mock()
    monkeypatch.setattr(gh.subprocess, "run", run)
    client = gh.GitHub()
    client.deadline = 0
    with pytest.raises(gh.Unavailable, match="budget"):
        client.api("repos/example/project")
    with pytest.raises(gh.Unavailable, match="invalid_github_selector"):
        gh.collect("../bad", HEAD, pr=7, project_checks=["test"])
    run.assert_not_called()


@pytest.mark.parametrize(
    "last_rule",
    [
        dict(
            type="required_status_checks",
            ruleset_id=101,
            parameters=dict(
                required_status_checks=[
                    dict(context="additional-gate", integration_id=None)
                ]
            ),
        ),
        dict(type="unknown-additional-gate", ruleset_id=101),
    ],
)
def test_effective_rules_second_page_cannot_be_omitted(facts, last_rule):
    first_page = [dict(type="creation", ruleset_id=index) for index in range(100)]
    client = gh.GitHub()
    client.api = Mock(
        side_effect=[
            dict(full_name=REPO, permissions=dict(admin=True)),
            dict(name="main", protected=True, commit=dict(sha=BASE)),
            {},
            first_page,
            [last_rule],
        ]
    )
    rules = gh.policy(client, REPO, "main")
    assert len(rules["rules"]) == 101
    assert client.api.call_args_list[-1].args[0].endswith("per_page=100&page=2")
    facts["policy"] = {**rules, "rules": first_page}
    assert gh.evaluate(facts, ["test"])["status"] == "PASS"  # old first-page behavior
    facts["policy"] = rules
    assert gh.evaluate(facts, ["test"])["status"] == "BLOCKED"


def test_effective_rules_page_budget_blocks_incomplete_contract():
    client = gh.GitHub()
    client.api = Mock(
        side_effect=[
            [
                dict(type="creation", ruleset_id=page * 100 + index)
                for index in range(100)
            ]
            for page in range(gh.MAX_PAGES)
        ]
    )
    with pytest.raises(gh.Unavailable, match="page_budget"):
        client.pages("rules/branches/main", None, ".", identity_key=None)
    assert client.api.call_count == gh.MAX_PAGES
