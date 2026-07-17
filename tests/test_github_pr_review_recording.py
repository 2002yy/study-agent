from src.web.github_pr_review_recording import compact_recording
from tools.record_github_replay import _repository_url


def test_repository_url_accepts_owner_name_or_full_url():
    assert _repository_url("pallets/flask") == "https://github.com/pallets/flask"
    assert (
        _repository_url("https://github.com/pallets/flask")
        == "https://github.com/pallets/flask"
    )


def test_compact_recording_keeps_replay_evidence_without_provider_bodies():
    payload = compact_recording(
        {
            "ok": True,
            "provider_status": "complete",
            "repository": "example/repo",
            "number": 7,
            "url": "https://github.com/example/repo/pull/7",
            "base": {"commit_sha": "a" * 40},
            "head": {"commit_sha": "b" * 40},
            "review_items": [
                {
                    "kind": "review_thread",
                    "id": "thread-1",
                    "path": "src/app.py",
                    "line": 12,
                    "body": "provider comment body must not be recorded",
                    "mapping": {"status": "mapped", "symbol": {"identity": {"id": "s1"}}},
                    "hunk_mapping": {"status": "mapped"},
                }
            ],
            "ci_associations": [
                {
                    "check": {
                        "id": 10,
                        "name": "tests",
                        "conclusion": "failure",
                        "url": "https://example.test/check/10",
                        "logs": "must not be recorded",
                    },
                    "association": {"status": "associated", "tests": ["tests/test_app.py"]},
                }
            ],
            "source_evidence": {"large": "must not be recorded"},
            "provider_request_budget": {"used_requests": 9},
            "cache_hit": False,
        },
        elapsed_ms=12.3456,
        recorded_at="2026-07-17T00:00:00+00:00",
    )

    assert payload["source"]["base_sha"] == "a" * 40
    assert payload["replay_metadata"] == {
        "recorded_at": "2026-07-17T00:00:00+00:00",
        "provider_requests": 9,
        "elapsed_ms": 12.346,
        "cache_hit": False,
    }
    assert payload["review_items"][0]["mapping"]["symbol"]["identity"]["id"] == "s1"
    assert payload["ci_associations"][0]["association"]["tests"] == ["tests/test_app.py"]
    assert "body" not in payload["review_items"][0]
    assert "logs" not in payload["ci_associations"][0]["check"]
    assert "source_evidence" not in payload


def test_compact_recording_keeps_bounded_change_symbol_candidates_for_labeling():
    payload = compact_recording(
        {
            "ok": True,
            "repository": "example/repo",
            "number": 7,
            "base": {"commit_sha": "a" * 40},
            "head": {"commit_sha": "b" * 40},
            "source_evidence": {
                "change_impact": {
                    "changes": [
                        {
                            "type": "modified",
                            "old": [],
                            "new": [
                                {
                                    "qualified_name": "Service.run",
                                    "kind": "method",
                                    "language": "python",
                                    "identity": {"id": "symbol-run"},
                                    "evidence": {
                                        "path": "src/service.py",
                                        "start_line": 10,
                                        "end_line": 20,
                                    },
                                }
                            ],
                        }
                    ]
                },
                "large": "not retained",
            },
        },
        elapsed_ms=1,
        recorded_at="2026-07-17T00:00:00+00:00",
    )

    assert payload["label_candidates"] == [
        {
            "side": "new",
            "change_type": "modified",
            "id": "symbol-run",
            "qualified_name": "Service.run",
            "kind": "method",
            "language": "python",
            "path": "src/service.py",
            "start_line": 10,
            "end_line": 20,
        }
    ]


def test_compact_recording_rejects_non_immutable_refs():
    try:
        compact_recording(
            {
                "ok": True,
                "base": {"commit_sha": "main"},
                "head": {"commit_sha": "b" * 40},
            },
            elapsed_ms=0,
            recorded_at="2026-07-17T00:00:00+00:00",
        )
    except ValueError as exc:
        assert "immutable" in str(exc)
    else:
        raise AssertionError("expected immutable SHA validation failure")
