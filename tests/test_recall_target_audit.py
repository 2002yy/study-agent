"""§44A recall audit: query classification and per-target aggregation."""

from __future__ import annotations

from tools.run_recall_target_audit import (
    TARGETS,
    audit_case_queries,
    classify_query_relevance,
)

DOCKER = next(t for t in TARGETS if t.case_id.endswith("container-registry"))


def test_relevance_tiers_are_mechanical_and_ordered() -> None:
    assert classify_query_relevance(
        "Docker Hub pull usage and limits official docs", DOCKER
    ) == "direct_targeting"
    assert classify_query_relevance("Docker Hub usage", DOCKER) == "plausible_targeting"
    assert classify_query_relevance("docker tutorial", DOCKER) == "weak_targeting"
    assert classify_query_relevance("python packaging guide", DOCKER) == "unrelated"


def test_audit_rows_capture_provider_retrieval_fields() -> None:
    case = {
        "case_id": "rq1c-current-policy-container-registry",
        "metrics": {
            "search_discovery": {
                "queries": [
                    {
                        "query_excerpt": "Docker Hub pull usage limits",
                        "results": [
                            {"url": "https://www.docker.com/"},
                            {"url": "https://docs.docker.com/docker-hub/usage/pulls/"},
                        ],
                    },
                    {
                        "query_excerpt": "docker tutorial",
                        "results": [{"url": "https://www.runoob.com/docker/docker-tutorial.html"}],
                    },
                ]
            }
        },
    }
    rows = audit_case_queries(case, DOCKER)
    assert rows[0]["query_relevance"] == "direct_targeting"
    assert rows[0]["provider_target_returned"] is True
    assert rows[0]["provider_same_domain_returned"] is True
    assert rows[0]["provider_near_page_returned"] is True
    assert rows[1]["provider_target_returned"] is False
    assert rows[1]["provider_same_domain_returned"] is False


def test_audit_skips_other_cases_and_dedupes(tmp_path) -> None:
    import json

    from tools.run_recall_target_audit import run_audit

    case = {
        "cases": [
            {
                "case_id": "rq1c-current-policy-container-registry",
                "metrics": {
                    "search_discovery": {
                        "queries": [
                            {
                                "query_excerpt": "Docker Hub limits",
                                "results": [
                                    {"url": "https://docs.docker.com/docker-hub/usage/pulls/"}
                                ],
                            }
                        ]
                    }
                },
            },
            {"case_id": "rq1c-unverifiable-python-security", "metrics": {}},
        ]
    }
    artifact = tmp_path / "a.json"
    artifact.write_text(json.dumps(case), encoding="utf-8")
    payload = run_audit(artifacts=[artifact], output_path=tmp_path / "out.json")
    assert len(payload["rows"]) == 1
    summary = payload["summary"]["rq1c-current-policy-container-registry"]
    assert summary["provider_target_returned"] == 1
