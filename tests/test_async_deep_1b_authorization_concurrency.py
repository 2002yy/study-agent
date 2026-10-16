"""Async Deep-1B evidence: authorization carry-forward is concurrency-safe.

Real SQLite with real threads; no model, search or network call.
"""

from __future__ import annotations

import threading

from src.infrastructure.sqlite.database import RuntimeDatabase
from src.repositories.llm_spend_ledger_repository import SpendLedgerRepository
from src.repositories.research_authorization_repository import (
    ResearchAuthorizationRepository,
    cny_to_micros,
)

CNY = cny_to_micros


def _grant(auth, run_id, *, spend_cny=10):
    return auth.create_grant(
        owner_thread_id="thread-1", deadline_at="2099-01-01T00:00:00+00:00",
        max_model_calls=24, max_vision_calls=2, max_searches=20, max_reads=30,
        max_spend_micros=CNY(spend_cny), run_id=run_id,
    )


def test_concurrent_reauthorization_keeps_versions_monotonic_and_usage_intact(tmp_path):
    database = RuntimeDatabase(tmp_path / "runtime.db")
    auth = ResearchAuthorizationRepository(database)
    ledger = SpendLedgerRepository(database)
    ledger.ensure_account(CNY(50))
    run_id = "run-concurrent"

    first = _grant(auth, run_id)
    ledger.reserve(
        call_id="c-1", authorization_id=first.id, scope_id=run_id, purpose="planner",
        model="deepseek-chat", estimated_micros=CNY(3),
    )

    created: list[object] = []
    failures: list[Exception] = []
    lock = threading.Lock()
    start = threading.Barrier(4)

    def attempt() -> None:
        start.wait()
        try:
            grant = _grant(auth, run_id, spend_cny=10)
        except Exception as exc:  # a losing writer may fail; it must not corrupt state
            with lock:
                failures.append(exc)
            return
        with lock:
            created.append(grant)

    threads = [threading.Thread(target=attempt) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    versions = sorted(int(grant.authorization_version) for grant in created)
    assert len(versions) == len(set(versions)), "concurrent grants must not share a version"
    assert versions == list(range(2, 2 + len(versions))), (
        "versions must continue monotonically from the first grant"
    )

    with database.connect() as connection:
        active = connection.execute(
            "SELECT id, reserved_micros FROM research_authorizations "
            "WHERE run_id = ? AND status = 'active'",
            (run_id,),
        ).fetchall()
    assert len(active) == 1, "exactly one grant may be authoritative"

    usage = auth.run_usage(run_id)
    assert usage["reserved_micros"] == CNY(3), (
        "concurrent re-authorization must not lose or duplicate accumulated spend"
    )
    assert int(active[0]["reserved_micros"]) == CNY(3)
