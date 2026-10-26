"""Whole-job gate for the split workflow (M1).

The aggregate `test` job cannot see step outcomes inside other jobs, so it judges
`needs.<job>.result`. The trap is that `skipped` means two different things:
"the classifier said this job was not needed" (fine) and "an upstream failure
stopped it from running" (a failure). These cases pin both readings.
"""

from __future__ import annotations

import pytest

from tools.check_ci_outcomes import judge_jobs


def results(**overrides: str) -> dict:
    base = {
        "classify": "success",
        "backend": "success",
        "frontend": "success",
        "browser": "success",
    }
    base.update(overrides)
    return {name: {"result": value} for name, value in base.items()}


def test_everything_required_and_green_passes():
    assert judge_jobs(results(), frontend_required=True, browser_required=True) == []


def test_a_legally_skipped_optional_job_passes():
    assert (
        judge_jobs(
            results(frontend="skipped", browser="skipped"),
            frontend_required=False,
            browser_required=False,
        )
        == []
    )


@pytest.mark.parametrize("job", ["frontend", "browser"])
def test_a_required_job_that_was_skipped_fails(job: str):
    outcome = judge_jobs(
        results(**{job: "skipped"}),
        frontend_required=True,
        browser_required=True,
    )
    assert outcome == [f"{job}:skipped"]


@pytest.mark.parametrize("result", ["failure", "cancelled"])
def test_an_optional_job_that_ran_and_failed_still_fails(result: str):
    outcome = judge_jobs(
        results(browser=result),
        frontend_required=False,
        browser_required=False,
    )
    assert outcome == [f"browser:{result}"]


def test_a_failed_backend_fails_even_when_the_browser_passed():
    assert judge_jobs(
        results(backend="failure"), frontend_required=False, browser_required=True
    ) == ["backend:failure"]


def test_a_missing_classify_result_fails_instead_of_shrinking_the_gate():
    needs = results()
    del needs["classify"]
    assert judge_jobs(needs, frontend_required=False, browser_required=False) == [
        "classify:missing"
    ]


def test_an_unreadable_result_is_missing_not_needed():
    needs = results()
    needs["backend"] = {}
    assert judge_jobs(needs, frontend_required=True, browser_required=True) == [
        "backend:missing"
    ]


def test_a_non_mapping_payload_fails_closed():
    assert judge_jobs("not-json", frontend_required=False, browser_required=False) == [
        "classify:missing",
        "backend:missing",
        "frontend:missing",
        "browser:missing",
    ]


def test_classify_must_succeed_even_when_nothing_else_is_required():
    assert judge_jobs(
        results(classify="failure", frontend="skipped", browser="skipped"),
        frontend_required=False,
        browser_required=False,
    ) == ["classify:failure"]
