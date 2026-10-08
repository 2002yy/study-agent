"""Durable handoff consumer primitives; not an automatic research planner.

Only the caller thread can write the journal. Late provider workers cannot
publish or checkpoint after cancellation, expiry or operation takeover.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from datetime import datetime, timedelta, timezone
import time
from typing import Any, Callable

from src.application.standard_handoff import admit_standard_handoff
from src.domain.runtime_entities import new_id
from src.repositories.runtime_repository import RuntimeRepository
from src.repositories.standard_execution_repository import StandardExecutionRepository
from src.repositories.web_lookup_repository import WebLookupRepository
from src.web.research_recovery import STANDARD_BUDGET


class StandardExecution:
    def __init__(
        self,
        journal: StandardExecutionRepository,
        run_id: str,
        thread_id: str,
        operation_id: str,
        *,
        clock: Callable[[], datetime],
    ):
        self.journal = journal
        self.run_id = run_id
        self.thread_id = thread_id
        self.operation_id = operation_id
        self.clock = clock

    @classmethod
    def start(
        cls,
        repository: RuntimeRepository,
        runs: WebLookupRepository,
        *,
        parent_turn_id: str,
        thread_id: str,
        overall_deadline: datetime,
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> StandardExecution:
        now = clock()
        admission = admit_standard_handoff(
            repository,
            runs,
            parent_turn_id=parent_turn_id,
            thread_id=thread_id,
            overall_deadline=overall_deadline,
            now=now,
        )
        journal = StandardExecutionRepository(repository.database)
        run_id = journal.create(admission)
        operation_id = new_id("standard_op")
        journal.acquire(run_id, thread_id, operation_id, now)
        return cls(journal, run_id, thread_id, operation_id, clock=clock)

    @classmethod
    def resume(
        cls,
        repository: RuntimeRepository,
        *,
        run_id: str,
        thread_id: str,
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> StandardExecution:
        journal = StandardExecutionRepository(repository.database)
        operation_id = new_id("standard_op")
        journal.acquire(run_id, thread_id, operation_id, clock())
        return cls(journal, run_id, thread_id, operation_id, clock=clock)

    def interrupt(self) -> None:
        self.journal.interrupt(
            self.run_id, self.thread_id, self.operation_id, self.clock()
        )

    def read(self, gateway: Any, url: str) -> dict:
        return self._dispatch(gateway, "read", url)

    def search(self, gateway: Any, query: str) -> dict:
        return self._dispatch(gateway, "search", query)

    def _dispatch(self, gateway: Any, kind: str, target: str) -> dict:
        reservation = self.journal.reserve(
            self.run_id, self.thread_id, self.operation_id, kind, target, self.clock()
        )
        if reservation["cached"]:
            return reservation["result"]
        try:
            result = self._bounded_call(
                lambda: (
                    gateway.read(target, max_chars=STANDARD_BUDGET.max_source_chars)
                    if kind == "read"
                    else gateway.search_exact(target, max_results=8)
                ),
                reservation["deadline"],
            )
            if not isinstance(result, dict):
                raise ValueError("invalid Standard provider result")
            self.journal.finish(
                self.run_id,
                self.thread_id,
                self.operation_id,
                reservation["key"],
                self.clock(),
                result=result,
            )
            return result
        except Exception as exc:
            # If the owner is cancelled/expired/stale, leave the charged reservation
            # unknown; never let error recording bypass that ownership gate.
            try:
                self.journal.finish(
                    self.run_id,
                    self.thread_id,
                    self.operation_id,
                    reservation["key"],
                    self.clock(),
                    error=type(exc).__name__,
                )
            except ValueError:
                pass
            raise

    def _bounded_call(self, fn: Callable[[], Any], deadline: str) -> Any:
        """Only for work already reserved in the SQLite journal."""
        end = datetime.fromisoformat(deadline) - timedelta(
            seconds=STANDARD_BUDGET.finalization_reserve
        )
        remaining = (end - self.clock()).total_seconds()
        if remaining <= 0:
            raise ValueError("Standard deadline exhausted before dispatch")
        call_end = time.monotonic() + min(8.0, remaining)

        def invoke() -> dict:
            self.journal.check(
                self.run_id, self.thread_id, self.operation_id, self.clock()
            )
            if time.monotonic() >= call_end:
                raise TimeoutError("Standard provider timeout")
            return fn()

        pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="standard-dispatch")
        future = pool.submit(invoke)
        try:
            while True:
                # Recheck repository cancellation/ownership without dispatching again.
                self.journal.check(
                    self.run_id, self.thread_id, self.operation_id, self.clock()
                )
                remaining = call_end - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError("Standard provider timeout")
                try:
                    result = future.result(timeout=min(0.1, remaining))
                    break
                except FutureTimeout:
                    if future.done():
                        raise
            return result
        finally:
            future.cancel()
            pool.shutdown(wait=False, cancel_futures=True)
