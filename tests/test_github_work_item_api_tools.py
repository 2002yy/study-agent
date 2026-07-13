from __future__ import annotations

import pytest
from fastapi import HTTPException

from src.api.models.github import (
    GitHubCILogsQueryRequest,
    GitHubChecksQueryRequest,
    GitHubIssueQueryRequest,
    GitHubPullRequestQueryRequest,
)
from src.api.routes.github_routes import (
    inspect_github_checks,
    inspect_github_ci_logs,
    inspect_github_issue,
    inspect_github_pull_request,
)
from src.tools.web_agent import WEB_TOOLS, WebToolAgent
from src.web.persistent_tool_gateway import PersistentGeneralWebGateway


REPO = "https://github.com/openai/example"


class FakeSnapshotService:
    def search_repository(self, *_args, **_kwargs):
        return {"ok": False, "error": "not_used", "results": []}


class FakeWorkItemService:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.calls: list[tuple[str, tuple, dict]] = []

    def pull_request(self, repo_url: str, number: int, **kwargs):
        self.calls.append(("pr", (repo_url, number), kwargs))
        if self.fail:
            return {
                "ok": False,
                "status": "not_found",
                "error": "github_pull_request_unavailable",
            }
        return {"ok": True, "status": "resolved", "number": number, "files": []}

    def issue(self, repo_url: str, number: int, **kwargs):
        self.calls.append(("issue", (repo_url, number), kwargs))
        return {"ok": True, "status": "resolved", "number": number, "comments": []}

    def checks(self, repo_url: str, **kwargs):
        self.calls.append(("checks", (repo_url,), kwargs))
        return {"ok": True, "status": "resolved", "jobs": [{"id": 41}]}

    def ci_logs(self, repo_url: str, job_id: int, **kwargs):
        self.calls.append(("logs", (repo_url, job_id), kwargs))
        return {"ok": True, "status": "resolved", "job_id": job_id, "log": "tail"}


class FakeHistoryService:
    pass


def test_work_item_routes_preserve_budgets_and_options():
    service = FakeWorkItemService()

    pr = inspect_github_pull_request(
        GitHubPullRequestQueryRequest(
            repo_url=REPO,
            number=7,
            max_files=8,
            max_patch_chars=9000,
            max_comments=9,
            max_reviews=10,
            include_checks=False,
        ),
        service,  # type: ignore[arg-type]
    )
    issue = inspect_github_issue(
        GitHubIssueQueryRequest(
            repo_url=REPO,
            number=9,
            max_comments=11,
            max_events=12,
        ),
        service,  # type: ignore[arg-type]
    )
    checks = inspect_github_checks(
        GitHubChecksQueryRequest(
            repo_url=REPO,
            ref="feature",
            max_runs=13,
            max_checks=14,
            max_jobs=15,
            include_jobs=False,
        ),
        service,  # type: ignore[arg-type]
    )
    logs = inspect_github_ci_logs(
        GitHubCILogsQueryRequest(
            repo_url=REPO,
            job_id=41,
            max_chars=16000,
            max_lines=160,
        ),
        service,  # type: ignore[arg-type]
    )

    assert pr.result["number"] == 7
    assert issue.result["number"] == 9
    assert checks.result["jobs"][0]["id"] == 41
    assert logs.result["log"] == "tail"
    assert service.calls == [
        (
            "pr",
            (REPO, 7),
            {
                "max_files": 8,
                "max_patch_chars": 9000,
                "max_comments": 9,
                "max_reviews": 10,
                "include_checks": False,
            },
        ),
        ("issue", (REPO, 9), {"max_comments": 11, "max_events": 12}),
        (
            "checks",
            (REPO,),
            {
                "ref": "feature",
                "max_runs": 13,
                "max_checks": 14,
                "max_jobs": 15,
                "include_jobs": False,
            },
        ),
        ("logs", (REPO, 41), {"max_chars": 16000, "max_lines": 160}),
    ]


def test_work_item_route_maps_not_found_to_404():
    with pytest.raises(HTTPException) as captured:
        inspect_github_pull_request(
            GitHubPullRequestQueryRequest(repo_url=REPO, number=404),
            FakeWorkItemService(fail=True),  # type: ignore[arg-type]
        )

    assert captured.value.status_code == 404
    assert captured.value.detail["status"] == "not_found"


def test_work_item_model_tool_schemas_and_dispatch():
    names = {item["function"]["name"] for item in WEB_TOOLS}
    assert {"github_pr", "github_issue", "github_checks", "github_ci_logs"} <= names

    work_items = FakeWorkItemService()
    gateway = PersistentGeneralWebGateway(
        FakeSnapshotService(),  # type: ignore[arg-type]
        history_service=FakeHistoryService(),  # type: ignore[arg-type]
        work_item_service=work_items,  # type: ignore[arg-type]
    )
    agent = WebToolAgent(gateway=gateway)

    pr = agent._execute(
        "github_pr",
        {
            "repo_url": REPO,
            "number": 7,
            "max_files": 8,
            "max_patch_chars": 9000,
            "max_comments": 9,
            "max_reviews": 10,
            "include_checks": False,
        },
    )
    issue = agent._execute(
        "github_issue",
        {
            "repo_url": REPO,
            "number": 9,
            "max_comments": 11,
            "max_events": 12,
        },
    )
    checks = agent._execute(
        "github_checks",
        {
            "repo_url": REPO,
            "ref": "feature",
            "max_runs": 13,
            "max_checks": 14,
            "max_jobs": 15,
            "include_jobs": False,
        },
    )
    logs = agent._execute(
        "github_ci_logs",
        {
            "repo_url": REPO,
            "job_id": 41,
            "max_chars": 16000,
            "max_lines": 160,
        },
    )

    assert pr["number"] == 7
    assert issue["number"] == 9
    assert checks["jobs"][0]["id"] == 41
    assert logs["job_id"] == 41
    assert work_items.calls[-1] == (
        "logs",
        (REPO, 41),
        {"max_chars": 16000, "max_lines": 160},
    )


def test_model_tools_report_unavailable_gateway_methods():
    agent = WebToolAgent(gateway=object())  # type: ignore[arg-type]

    assert agent._execute("github_pr", {"repo_url": REPO, "number": 7}) == {
        "ok": False,
        "error": "github_pr_unavailable",
    }
    assert agent._execute("github_ci_logs", {"repo_url": REPO, "job_id": 41}) == {
        "ok": False,
        "error": "github_ci_logs_unavailable",
    }
