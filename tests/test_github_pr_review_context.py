from __future__ import annotations

from src.web.github_pr_review_context import GitHubPRReviewContextService

REPO = "https://github.com/openai/example"
BASE_SHA = "a" * 40
HEAD_SHA = "b" * 40


class FakeWorkItems:
    def __init__(self, *, ambiguous: bool = False) -> None:
        self.ambiguous = ambiguous
        self.calls: list[tuple[str, int, dict]] = []

    def pull_request(self, repo_url: str, number: int, **kwargs) -> dict:
        self.calls.append((repo_url, number, kwargs))
        line = 5 if not self.ambiguous else 7
        return {
            "ok": True,
            "status": "resolved",
            "provider_status": "complete",
            "repository": "openai/example",
            "number": number,
            "title": "Improve normalization",
            "url": "https://github.com/openai/example/pull/7",
            "changed_files": 1,
            "file_count": 1,
            "base": {"ref": "main", "commit_sha": BASE_SHA},
            "head": {"ref": "feature", "commit_sha": HEAD_SHA},
            "review_threads": {
                "status": "resolved",
                "threads": [
                    {
                        "id": "thread-1",
                        "is_resolved": False,
                        "is_outdated": False,
                        "path": "src/service.py",
                        "line": line,
                        "start_line": line,
                        "side": "RIGHT",
                        "comments": [
                            {
                                "id": 12,
                                "body": "Please keep strict normalization covered.",
                            }
                        ],
                    }
                ],
                "unresolved_count": 1,
                "truncated": False,
            },
            "inline_comments": [],
            "checks": {
                "ok": True,
                "provider_status": "complete",
                "check_runs": [
                    {
                        "id": 21,
                        "name": "unit tests",
                        "status": "completed",
                        "conclusion": "failure",
                    }
                ],
                "jobs": [
                    {
                        "id": 41,
                        "run_id": 31,
                        "name": "pytest test_service",
                        "status": "completed",
                        "conclusion": "failure",
                        "url": "job-url",
                        "steps": [
                            {
                                "name": "pytest tests/test_service.py",
                                "number": 2,
                                "conclusion": "failure",
                            }
                        ],
                    }
                ],
            },
            "truncated": False,
        }


class FakeImpact:
    def __init__(self, *, ambiguous: bool = False) -> None:
        self.ambiguous = ambiguous
        self.calls: list[tuple[str, str, str, dict]] = []

    def analyze(self, repo_url: str, base: str, head: str, **kwargs) -> dict:
        self.calls.append((repo_url, base, head, kwargs))
        symbols = [
            {
                "name": "normalize",
                "qualified_name": "normalize",
                "kind": "function",
                "language": "python",
                "identity": {"id": "symbol-normalize", "commit_sha": HEAD_SHA},
                "evidence": {
                    "path": "src/service.py",
                    "start_line": 4,
                    "end_line": 8,
                },
            }
        ]
        if self.ambiguous:
            symbols.append(
                {
                    "name": "normalize_alias",
                    "qualified_name": "normalize_alias",
                    "kind": "function",
                    "language": "python",
                    "identity": {"id": "symbol-alias", "commit_sha": HEAD_SHA},
                    "evidence": {
                        "path": "src/service.py",
                        "start_line": 4,
                        "end_line": 8,
                    },
                }
            )
        return {
            "ok": True,
            "status": "resolved",
            "provider_status": "complete",
            "file_changes": [
                {
                    "status": "modified",
                    "old_path": "src/service.py",
                    "new_path": "src/service.py",
                }
            ],
            "changes": [
                {
                    "id": "change-1",
                    "type": "modified",
                    "signature_changed": True,
                    "old": [],
                    "new": symbols,
                }
            ],
            "tests": [
                {
                    "path": "tests/test_service.py",
                    "reasons": ["references normalize"],
                }
            ],
            "affected_files": [
                {"path": "src/service.py", "reasons": ["changed symbol"]},
                {"path": "src/api.py", "reasons": ["caller"]},
            ],
            "missing_test_symbols": [],
            "uncertainties": [],
            "summary": {"symbol_change_count": len(symbols)},
            "truncated": False,
        }


def test_review_context_maps_unresolved_thread_and_failed_ci_to_evidence():
    work_items = FakeWorkItems()
    impact = FakeImpact()

    result = GitHubPRReviewContextService(
        work_items,  # type: ignore[arg-type]
        impact,  # type: ignore[arg-type]
    ).build(REPO, 7, max_files=10, max_symbols=20, depth=3)

    assert result["ok"] is True
    assert result["provider_status"] == "complete"
    assert result["base"]["commit_sha"] == BASE_SHA
    assert result["head"]["commit_sha"] == HEAD_SHA
    assert result["review_items"][0]["mapping"]["status"] == "mapped"
    assert (
        result["review_items"][0]["mapping"]["symbol"]["qualified_name"]
        == "normalize"
    )
    assert result["summary"]["unresolved_review_thread_count"] == 1
    assert result["summary"]["mapped_unresolved_review_thread_count"] == 1
    assert result["ci_associations"][0]["association"]["status"] == "associated"
    assert result["ci_associations"][0]["association"]["tests"] == [
        "tests/test_service.py"
    ]
    assert result["evidence_coverage"]["status"] == "complete"
    assert result["evidence_coverage"]["score"] == 1.0
    assert result["verdict"] == {
        "status": "not_generated",
        "reason": "review_context_is_evidence_not_a_correctness_verdict",
    }
    assert work_items.calls[0][2]["include_checks"] is True
    assert impact.calls[0][1:3] == (BASE_SHA, HEAD_SHA)


def test_review_context_keeps_ambiguous_symbol_mapping_explicit():
    result = GitHubPRReviewContextService(
        FakeWorkItems(ambiguous=True),  # type: ignore[arg-type]
        FakeImpact(ambiguous=True),  # type: ignore[arg-type]
    ).build(REPO, 7)

    mapping = result["review_items"][0]["mapping"]
    assert result["ok"] is True
    assert result["provider_status"] == "partial"
    assert mapping["status"] == "ambiguous"
    assert mapping["candidate_count"] == 2
    assert result["evidence_coverage"]["review_location_symbol_coverage"] == 0.0
    assert {item["kind"] for item in result["uncertainties"]} >= {
        "review_location_ambiguous"
    }
    assert result["verdict"]["status"] == "not_generated"


def test_review_context_returns_pr_failure_without_running_change_impact():
    class FailedWorkItems:
        def pull_request(self, *_args, **_kwargs) -> dict:
            return {"ok": False, "status": "not_found", "error": "missing"}

    class UnexpectedImpact:
        def analyze(self, *_args, **_kwargs) -> dict:
            raise AssertionError("change impact must not run")

    result = GitHubPRReviewContextService(
        FailedWorkItems(),  # type: ignore[arg-type]
        UnexpectedImpact(),  # type: ignore[arg-type]
    ).build(REPO, 404)

    assert result == {"ok": False, "status": "not_found", "error": "missing"}
