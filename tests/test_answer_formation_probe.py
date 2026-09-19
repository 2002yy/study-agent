"""§40 answer formation probe: classification, replay, summary contracts."""

from __future__ import annotations

from tools.run_answer_formation_probe import (
    capture_chat_records,
    classify_reply_outcome,
    replay,
    summarize_attempts,
)

CALL = {
    "messages": [
        {"role": "system", "content": "You are a careful research assistant."},
        {"role": "user", "content": "Question + evidence brief"},
    ],
    "kwargs": {
        "task_name": "answer_generation",
        "model_profile": "flash",
        "provider_profile": "deepseek",
        "timeout": 30.0,
        "request_max_retries": 0,
    },
}


def test_classification_distinguishes_a_b_c() -> None:
    assert (
        classify_reply_outcome({"completed": True, "reply_chars": 0, "candidate_chars": 0})
        == "A_model_empty"
    )
    assert (
        classify_reply_outcome({"completed": True, "reply_chars": 120, "candidate_chars": 0})
        == "B_parse_loss"
    )
    assert (
        classify_reply_outcome({"completed": False, "exception_type": "APITimeoutError"})
        == "C_call_unavailable"
    )
    assert (
        classify_reply_outcome({"completed": True, "reply_chars": 80, "candidate_chars": 80})
        == "ok"
    )


def test_replay_records_the_diagnostics_contract() -> None:
    def chat_fn(messages, **kwargs):
        del messages, kwargs
        return "The answer with [1] citation."

    attempts = replay(CALL, chat_fn=chat_fn, runs=1, policy="captured")
    record = attempts[0]
    assert record["completed"] is True
    assert record["elapsed_ms"] >= 0
    assert record["thinking_mode"] == "on"
    assert record["raw_response_chars"] == len("The answer with [1] citation.")
    assert record["candidate_sha256"]
    assert record["publish_decision"] == "publish_candidate"
    assert record["classification"] == "ok"


def test_replay_marks_empty_reply_as_fail_closed() -> None:
    def chat_fn(messages, **kwargs):
        del messages, kwargs
        return ""

    attempts = replay(CALL, chat_fn=chat_fn, runs=2, policy="captured")
    assert [row["classification"] for row in attempts] == ["A_model_empty", "A_model_empty"]
    assert all(row["publish_decision"] == "fail_closed_empty_candidate" for row in attempts)


def test_replay_thinking_off_sets_extra_body_for_the_ab() -> None:
    seen: list[dict] = []

    def chat_fn(messages, **kwargs):
        del messages
        seen.append(dict(kwargs.get("extra_body") or {}))
        return "ok text"

    replay(CALL, chat_fn=chat_fn, runs=1, policy="thinking_off")
    assert seen == [{"thinking": {"type": "disabled"}}]


def test_replay_exception_is_recorded_not_raised() -> None:
    def chat_fn(messages, **kwargs):
        del messages, kwargs
        raise TimeoutError("deadline")

    attempts = replay(CALL, chat_fn=chat_fn, runs=1, policy="captured")
    assert attempts[0]["exception_type"] == "TimeoutError"
    assert attempts[0]["classification"] == "C_call_unavailable"
    assert attempts[0]["candidate_sha256"] == (
        "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
    )


def test_summary_reports_rates_and_latency() -> None:
    attempts = [
        {"classification": "ok", "candidate_chars": 120, "elapsed_ms": 100},
        {"classification": "A_model_empty", "candidate_chars": 0, "elapsed_ms": 5000},
        {"classification": "C_call_unavailable", "candidate_chars": 0, "elapsed_ms": 30000},
    ]
    summary = summarize_attempts(attempts)
    assert summary["attempts"] == 3
    assert summary["non_empty_candidate_rate"] == 0.333
    assert summary["fail_closed_rate"] == 0.667
    assert summary["latency_ms_max"] == 30000


def test_capture_records_are_bounded_and_readable() -> None:
    artifact = {"answer_calls": [{"messages": [{"role": "user", "content": "x"}]}, "junk"]}
    rows = capture_chat_records(artifact)
    assert len(rows) == 1
    assert rows[0]["messages"][0]["content"] == "x"
