"""Offline-tested reservation boundary for the proposed M4-C3 batch; no sender.

Uses the existing ledger transaction so calls and money cannot race across
processes. This module does not supply paid authorization or call a provider.
"""

from __future__ import annotations

import sqlite3

from src.infrastructure.sqlite.spend_ledger import Reservation, SpendLedger
from tools.m4c3_prepare import TASKS

EXPERIMENT = "study-agent-live-20261102"
PREFIX = "m4c3-v1:"
MAX_CALLS = 12
PER_CALL_MICROS = 1_000_000
BATCH_MICROS = 12_000_000


def reserve_batch_call(
    ledger: SpendLedger, *, task_id: str, amount_micros: int, now: str
) -> Reservation:
    """Reserve one first attempt with fixed bounds; duplicate tasks stay spent."""
    if task_id not in TASKS:
        raise ValueError("unknown frozen task")
    if type(amount_micros) is not int or not 0 < amount_micros <= PER_CALL_MICROS:
        raise ValueError("per-call reservation must be positive and at most CNY 1")

    def guard(db: sqlite3.Connection, experiment: str) -> str | None:
        cap = db.execute(
            "SELECT cap_micros FROM llm_spend_experiments WHERE experiment_id=?",
            (experiment,),
        ).fetchone()
        if cap is None or cap[0] != 30_000_000:
            return "m4c3_shared_cap_mismatch"
        count, total = db.execute(
            "SELECT COUNT(*),COALESCE(SUM(amount_micros),0) FROM llm_spend_reservations "
            "WHERE experiment_id=? AND substr(request_key,1,?)=?",
            (experiment, len(PREFIX), PREFIX),
        ).fetchone()
        if count >= MAX_CALLS:
            return "m4c3_call_limit"
        if total < 0 or total + amount_micros > BATCH_MICROS:
            return "m4c3_batch_budget"
        return None

    return ledger.reserve(
        EXPERIMENT,
        request_key=f"{PREFIX}{task_id}:first",
        amount_micros=amount_micros,
        purpose="m4c3:first-generation",
        model="deepseek-flash",
        identity=f"m4c3-v1/{task_id}/first",
        now=now,
        admission_guard=guard,
    )
