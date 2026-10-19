"""Real SQLite tests for restart idempotency, concurrency and fail-closed calls."""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
import json
import sqlite3
import subprocess
import sys

import pytest

from src.application.conversation_decision import DecisionContext
from src.application.conversation_decision_admission import SqliteDecisionAdmission
from src.application.conversation_decision_runner import decide_conversation_action


def ledger(path, **changes):
    return SqliteDecisionAdmission(
        path,
        **{
            "max_calls": 2,
            "max_prompt_chars": 100000,
            "max_output_tokens": 1600,
            **changes,
        },
    )


def test_reservations_and_usage_survive_new_instances(tmp_path):
    path = tmp_path / "admission.sqlite"
    first = ledger(path)
    assert first.reserve("request-1", 100, 800) == "reserved"
    second = ledger(path)
    assert second.reserve("request-1", 100, 800) == "already_attempted"
    assert second.reserve("request-2", 100, 800) == "reserved"
    assert ledger(path).reserve("request-3", 1, 1) == "budget_exhausted"
    used = second.usage()
    assert (used.calls, used.prompt_chars, used.output_tokens) == (2, 200, 1600)


def test_subprocess_restart_cannot_repeat_a_previous_request(tmp_path):
    path = tmp_path / "admission.sqlite"
    ledger(path).reserve("request-1", 100, 800)
    code = (
        "from pathlib import Path; import sys; "
        "from src.application.conversation_decision_admission import SqliteDecisionAdmission; "
        "s=SqliteDecisionAdmission(Path(sys.argv[1]),max_calls=2,max_prompt_chars=100000,max_output_tokens=1600); "
        "print(s.reserve('request-1',100,800))"
    )
    result = subprocess.run(
        [sys.executable, "-c", code, str(path)],
        capture_output=True,
        text=True,
        check=True,
    )
    assert result.stdout.strip() == "already_attempted"


@pytest.mark.parametrize("axis", ["max_calls", "max_prompt_chars", "max_output_tokens"])
def test_reopening_does_not_silently_increase_a_frozen_budget(tmp_path, axis):
    path = tmp_path / "admission.sqlite"
    original = ledger(path)
    with pytest.raises(ValueError, match="persisted contract"):
        ledger(path, **{axis: 100001})
    assert original.usage().calls == 0


@pytest.mark.parametrize(
    "limits,prompt,tokens",
    [
        ({"max_calls": 0}, 1, 1),
        ({"max_prompt_chars": 10}, 11, 1),
        ({"max_output_tokens": 10}, 1, 11),
    ],
)
def test_each_budget_axis_rejects_without_persisting_a_request(
    tmp_path, limits, prompt, tokens
):
    store = ledger(tmp_path / "admission.sqlite", **limits)
    assert store.reserve("request-1", prompt, tokens) == "budget_exhausted"
    assert store.usage().calls == 0


def test_independent_connections_cannot_overspend_concurrently(tmp_path):
    path = tmp_path / "admission.sqlite"
    stores = [ledger(path) for _ in range(8)]

    def reserve(index):
        try:
            return stores[index].reserve(f"request-{index}", 100, 800)
        except sqlite3.OperationalError:
            return "contention_rejected"

    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(reserve, range(8)))
    assert 1 <= results.count("reserved") <= 2
    used = ledger(path).usage()
    assert used.calls == results.count("reserved")
    assert used.output_tokens == used.calls * 800


def test_foreign_database_is_refused_without_changes(tmp_path):
    path = tmp_path / "runtime.sqlite"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE application_state (id INTEGER)")
        db.execute("INSERT INTO application_state VALUES (1)")
    before = sha256(path.read_bytes()).hexdigest()
    with pytest.raises(ValueError, match="ownership marker"):
        ledger(path)
    assert sha256(path.read_bytes()).hexdigest() == before
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT * FROM application_state").fetchall() == [(1,)]


@pytest.mark.parametrize("valid_sqlite", [False, True])
def test_preexisting_empty_file_is_never_claimed_or_modified(tmp_path, valid_sqlite):
    path = tmp_path / "application-not-yet-migrated.sqlite"
    if valid_sqlite:
        with sqlite3.connect(path) as db:
            db.execute("VACUUM")
    else:
        path.write_bytes(b"")
    before = path.read_bytes()
    with pytest.raises(ValueError, match="ownership marker"):
        ledger(path)
    assert path.read_bytes() == before


def test_provider_failures_are_not_refunded_after_restart(tmp_path):
    path = tmp_path / "admission.sqlite"
    calls = []
    context = DecisionContext("request-1", "解释递归")

    async def failing_transport(request):
        calls.append(request)
        raise RuntimeError("private provider error")

    def decide(store):
        return asyncio.run(
            decide_conversation_action(
                context,
                budget=store,
                transport=failing_transport,
                current_context=lambda: context,
            )
        )

    assert decide(ledger(path)).status == "provider_error"
    assert decide(ledger(path)).status == "already_attempted"
    assert len(calls) == 1


def test_locked_ledger_cannot_start_transport_or_leak_database_errors(tmp_path):
    path = tmp_path / "admission.sqlite"
    store = ledger(path)
    context = DecisionContext("request-1", "解释递归")

    async def transport(request):
        pytest.fail("model must not run without durable admission")

    with sqlite3.connect(path, isolation_level=None) as blocker:
        blocker.execute("BEGIN IMMEDIATE")
        try:
            result = asyncio.run(
                decide_conversation_action(
                    context,
                    budget=store,
                    transport=transport,
                    current_context=lambda: context,
                )
            )
            assert result.status == "admission_unavailable"
            assert not result.attempted and result.proposal is None
            assert "sqlite" not in repr(result)
        finally:
            blocker.rollback()
    assert store.usage().calls == 0


def test_runner_accepts_successful_durable_admission_without_executing_tools(tmp_path):
    context = DecisionContext("request-1", "解释递归")
    store = ledger(tmp_path / "admission.sqlite")

    async def transport(request):
        return json.dumps(
            {
                "schema": "conversation-decision-v1",
                "request_id": context.request_id,
                "action": "answer",
                "relation": "new_topic",
                "reason": "已有知识足够",
                "focus": "解释递归",
                "tool": None,
                "target_run_id": None,
                "target_revision": None,
                "active_run_disposition": "none",
            }
        )

    result = asyncio.run(
        decide_conversation_action(
            context,
            budget=store,
            transport=transport,
            current_context=lambda: context,
        )
    )
    assert result.status == "completed" and result.proposal.action == "answer"
    assert store.usage().calls == 1


@pytest.mark.parametrize("bad_status", ["unexpected", {}, None])
def test_malformed_admission_result_cannot_reach_transport(bad_status):
    class BrokenAdmission:
        def reserve(self, *args):
            return bad_status

    context = DecisionContext("request-1", "解释递归")

    async def transport(request):
        pytest.fail("model cannot start without an explicit reserved status")

    result = asyncio.run(
        decide_conversation_action(
            context,
            budget=BrokenAdmission(),
            transport=transport,
            current_context=lambda: context,
        )
    )
    assert result.status == "admission_unavailable" and not result.attempted


@pytest.mark.parametrize("value", [-1, True, 2**63])
def test_invalid_caps_cannot_create_the_database(tmp_path, value):
    path = tmp_path / "admission.sqlite"
    with pytest.raises(ValueError):
        ledger(path, max_calls=value)
    assert not path.exists()
