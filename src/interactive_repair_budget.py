"""Request-local repair limits enforced by the existing paid-send ledger."""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
import hashlib
import json
import math
import re
import sqlite3
from typing import Iterator

from src.infrastructure.sqlite.spend_ledger import AdmissionGuard, cny_to_micros


@dataclass(frozen=True)
class InteractiveRepairBudget:
    thread_id: str
    component_id: str
    source_revision: int
    source_sha256: str
    capabilities: tuple[str, ...] = ()
    per_call_cny: float = 1.0
    max_calls: int = 2
    total_cny: float = 2.0

    def __post_init__(self) -> None:
        if not isinstance(self.thread_id, str) or not self.thread_id.strip():
            raise ValueError("repair requires a thread identity")
        if not re.fullmatch(r"[a-zA-Z0-9_-]{1,64}", self.component_id):
            raise ValueError("repair requires a valid component identity")
        if (
            type(self.source_revision) is not int
            or not 1 <= self.source_revision <= 999
        ):
            raise ValueError("repair requires a valid source revision")
        if not re.fullmatch(r"[0-9a-f]{64}", self.source_sha256):
            raise ValueError("repair requires an exact source hash")
        if self.capabilities not in ((), ("three",)):
            raise ValueError("unsupported repair source capabilities")
        if type(self.max_calls) is not int or self.max_calls < 1:
            raise ValueError("repair max_calls must be positive")
        for value in (self.per_call_cny, self.total_cny):
            if isinstance(value, bool) or not math.isfinite(value) or value <= 0:
                raise ValueError("repair money limits must be finite and positive")

    @property
    def purpose(self) -> str:
        # Revisions and capabilities are evidence metadata, never fresh budgets.
        identity = json.dumps([self.thread_id, self.component_id], ensure_ascii=True)
        return "interactive-repair:" + hashlib.sha256(identity.encode()).hexdigest()

    def reservation_identity(self, original: str, purpose: str, attempts: int) -> str:
        return json.dumps(
            {
                "original_identity": original,
                "original_purpose": purpose,
                "source_revision": self.source_revision,
                "source_sha256": self.source_sha256,
                "capabilities": self.capabilities,
                "attempts": attempts,
            },
            sort_keys=True,
        )

    def admission_guard(
        self, amount_micros: int, attempts: int, previous: AdmissionGuard | None = None
    ) -> AdmissionGuard:
        def guard(connection: sqlite3.Connection, experiment_id: str) -> str | None:
            if previous is not None:
                reason = previous(connection, experiment_id)
                if reason:
                    return reason
            if amount_micros > cny_to_micros(self.per_call_cny):
                return "interactive_repair_call_cost_exceeded"
            rows = connection.execute(
                "SELECT identity, amount_micros FROM llm_spend_reservations WHERE purpose = ?",
                (self.purpose,),
            ).fetchall()
            calls = 0
            for row in rows:
                try:
                    units = json.loads(row["identity"])["attempts"]
                except (KeyError, ValueError, TypeError):
                    return "interactive_repair_history_invalid"
                if type(units) is not int or units < 1:
                    return "interactive_repair_history_invalid"
                calls += units
            if calls + attempts > self.max_calls:
                return "interactive_repair_call_limit_exceeded"
            if sum(
                row["amount_micros"] for row in rows
            ) + amount_micros > cny_to_micros(self.total_cny):
                return "interactive_repair_total_cost_exceeded"
            return None

        return guard


_repair_budget: ContextVar[InteractiveRepairBudget | None] = ContextVar(
    "interactive_repair_budget", default=None
)


def current_repair_budget() -> InteractiveRepairBudget | None:
    return _repair_budget.get()


@contextmanager
def repair_budget_scope(
    budget: InteractiveRepairBudget,
) -> Iterator[InteractiveRepairBudget]:
    """Bind to the full send/stream lifetime; construction never authorizes cost."""
    if not isinstance(budget, InteractiveRepairBudget):
        raise ValueError("repair budget must be a validated policy")
    if _repair_budget.get() is not None:
        raise ValueError("nested repair budgets cannot replace an active policy")
    token = _repair_budget.set(budget)
    try:
        yield budget
    finally:
        _repair_budget.reset(token)
