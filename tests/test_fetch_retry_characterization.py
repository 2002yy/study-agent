"""§47 fetch retry characterization: trial logic and summary contracts."""

from __future__ import annotations

from pathlib import Path

from tools.run_fetch_retry_characterization import (
    run_probe,
    run_trial,
    summarize_trials,
)


def _sequence_fetch(outcomes: list[tuple[bool, str]]):
    calls = {"index": 0}

    def fetch(url: str) -> tuple[bool, str, int]:
        del url
        index = min(calls["index"], len(outcomes) - 1)
        calls["index"] += 1
        ok, reason = outcomes[index]
        return ok, reason, 100

    return fetch


def test_first_attempt_success_does_not_retry() -> None:
    fetch = _sequence_fetch([(True, "")])
    trial = run_trial(
        "https://x", fetch=fetch, max_attempts=3, backoff_seconds=(1.0, 2.0), sleep=lambda s: None
    )
    assert trial.success is True
    assert trial.attempts == 1


def test_fail_then_success_counts_as_retry_success() -> None:
    fetch = _sequence_fetch(
        [
            (False, "exception:URLError:<urlopen error [WinError 10054]>"),
            (True, ""),
        ]
    )
    trial = run_trial(
        "https://x", fetch=fetch, max_attempts=3, backoff_seconds=(1.0, 2.0), sleep=lambda s: None
    )
    assert trial.success is True
    assert trial.attempts == 2
    assert trial.signatures[0] == "WinError10054"


def test_all_failures_stop_at_max_attempts() -> None:
    fetch = _sequence_fetch([(False, "exception:URLError:10054")] * 5)
    trial = run_trial(
        "https://x", fetch=fetch, max_attempts=3, backoff_seconds=(1.0, 2.0), sleep=lambda s: None
    )
    assert trial.success is False
    assert trial.attempts == 3


def test_summary_reports_retry_and_final_rates() -> None:
    rows = [
        {"attempts": 1, "success": True, "signatures": ["ok"], "attempt_latencies_ms": [90], "total_latency_ms": 90},
        {
            "attempts": 2,
            "success": True,
            "signatures": ["WinError10054", "ok"],
            "attempt_latencies_ms": [80, 90],
            "total_latency_ms": 170,
        },
        {
            "attempts": 3,
            "success": False,
            "signatures": ["WinError10054", "WinError10054", "WinError10054"],
            "attempt_latencies_ms": [70, 70, 70],
            "total_latency_ms": 210,
        },
        {
            "attempts": 3,
            "success": True,
            "signatures": ["WinError10054", "WinError10054", "ok"],
            "attempt_latencies_ms": [60, 60, 100],
            "total_latency_ms": 220,
        },
    ]
    summary = summarize_trials(rows)
    assert summary["first_attempt_failures"] == 3
    assert summary["first_attempt_failure_rate"] == 0.75
    assert summary["retry_successes"] == 2
    assert summary["retry_success_rate_given_first_failure"] == 0.667
    assert summary["attempts_to_success"] == {"1": 1, "2": 1, "3": 1}
    assert summary["final_success_rate"] == 0.75
    assert summary["failure_signature_counts"] == {"WinError10054": 6}


def test_run_probe_with_injected_fetch(tmp_path: Path) -> None:
    outcomes = [
        (False, "exception:URLError:<10054>"),
        (True, ""),
        (True, ""),
    ]
    fetch = _sequence_fetch(outcomes)
    payload = run_probe(
        output_path=tmp_path / "out.json",
        urls=["https://flaky.example/page"],
        trials=2,
        max_attempts=3,
        fetch=fetch,
        sleep=lambda s: None,
        include_control=False,
    )
    result = payload["results"][0]
    assert result["url"] == "https://flaky.example/page"
    assert len(result["trials"]) == 2
    assert result["summary"]["retry_success_rate_given_first_failure"] == 1.0
    assert result["summary"]["final_success_rate"] == 1.0
