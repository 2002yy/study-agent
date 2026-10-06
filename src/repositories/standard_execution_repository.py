"""Transactional Standard dispatch journal on existing research-run storage.

No network work happens inside a transaction. A reserved dispatch with no saved
result is never retried automatically: exactly-once remote execution cannot be
guaranteed across a process crash, so that gap stays explicit.
"""

from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timedelta
import hashlib
import json
from typing import Any, Iterator

from src.domain.runtime_entities import WebLookupRun
from src.infrastructure.sqlite.database import RuntimeDatabase
from src.repositories.web_lookup_repository import WebLookupRepository
from src.web.research_recovery import STANDARD_BUDGET
from src.web.research.lookup_terminal import load_standard_handoff


SCHEMA = "standard-dispatch-journal-v1"
LEASE_SECONDS = 15


def work_key(kind: str, target: str) -> str:
    return hashlib.sha256(json.dumps([kind, target]).encode()).hexdigest()


class StandardExecutionRepository:
    def __init__(self, database: RuntimeDatabase):
        self.database = database

    def create(self, admission: Any) -> str:
        """Idempotent child creation; acquisition rechecks the saved authorities."""
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT rag_snapshot FROM chat_turns WHERE id = ?",
                (admission.parent_turn_id,),
            ).fetchone()
        if row is None:
            raise ValueError("Standard parent unavailable")
        handoff = load_standard_handoff(
            json.loads(row["rag_snapshot"])["lookup_terminal"]["handoff"]
        )
        if handoff["payload_sha256"] != admission.handoff["payload_sha256"]:
            raise ValueError("Standard handoff changed")
        entries = {}
        for call in handoff["attempted"]:
            if call in handoff["usable_sources"]:
                kind, target = "read", call["arguments"]["url"]
            elif call["name"] == "web_search" and call["result"].get("status") == "ok":
                kind, target = "search", call["arguments"]["query"]
            else:
                continue
            result = call["result"]
            if target:
                entries[work_key(kind, target)] = {
                    "kind": kind,
                    "target": target,
                    "state": "completed",
                    "result": deepcopy(result),
                    "origin": "lookup",
                }
        end = min(
            admission.deadline,
            admission.admitted_at + timedelta(seconds=STANDARD_BUDGET.hard_seconds),
        )
        ledger = {
            "schema": SCHEMA,
            "parent_turn_id": admission.parent_turn_id,
            "thread_id": admission.thread_id,
            "source_run_id": admission.source_run_id,
            "source_run_version": admission.source_run_version,
            "handoff_sha256": admission.handoff["payload_sha256"],
            "admitted_at": admission.admitted_at.isoformat(),
            "deadline": end.isoformat(),
            "new_reads": 0,
            "new_queries": 0,
            "reused_reads": 0,
            "cursor": 0,
            "entries": entries,
            "operation_id": "",
            "lease_until": "",
            "tokens": [],
            "publication_authority": False,
        }
        request_id = "standard-handoff:" + admission.parent_turn_id
        run = WebLookupRepository(self.database).create_child(
            WebLookupRun(
                id="standard-" + hashlib.sha256(request_id.encode()).hexdigest()[:24],
                query=admission.handoff["query"],
                stage="standard_handoff",
                status="pending",
                owner_thread_id=admission.thread_id,
                parent_run_id=admission.source_run_id,
                create_request_id=request_id,
                research_context={
                    "owner": {
                        "thread_id": admission.thread_id,
                        "turn_id": admission.parent_turn_id,
                    },
                    "standard": ledger,
                },
            )
        )
        saved = run.research_context.get("standard") or {}
        if (
            saved.get("handoff_sha256") != ledger["handoff_sha256"]
            or saved.get("source_run_version") != ledger["source_run_version"]
        ):
            raise ValueError("Standard child snapshot mismatch")
        return run.id

    @contextmanager
    def _transaction(
        self,
        run_id: str,
        thread_id: str,
        now: datetime,
        *,
        operation_id: str | None = None,
        write: bool = True,
    ) -> Iterator[tuple[Any, dict, dict]]:
        if now.tzinfo is None:
            raise ValueError("invalid Standard clock")
        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM web_lookup_runs WHERE id = ?", (run_id,)
            ).fetchone()
            if row is None or row["owner_thread_id"] != thread_id:
                raise ValueError("Standard run owner mismatch")
            context = json.loads(row["research_context"])
            ledger = context.get("standard") or {}
            if (
                ledger.get("schema") != SCHEMA
                or ledger.get("publication_authority") is not False
            ):
                raise ValueError("invalid Standard journal")
            parent = connection.execute(
                "SELECT * FROM chat_turns WHERE id = ?", (ledger["parent_turn_id"],)
            ).fetchone()
            source = connection.execute(
                "SELECT * FROM web_lookup_runs WHERE id = ?", (ledger["source_run_id"],)
            ).fetchone()
            thread = connection.execute(
                "SELECT status FROM chat_threads WHERE id = ?", (thread_id,)
            ).fetchone()
            if (
                parent is None
                or parent["thread_id"] != thread_id
                or parent["status"] != "completed"
                or parent["cancel_requested_at"]
                or thread is None
                or thread["status"] != "active"
            ):
                raise ValueError("Standard parent unavailable")
            terminal = json.loads(parent["rag_snapshot"]).get("lookup_terminal") or {}
            load_standard_handoff(terminal.get("handoff") or {})
            owner = terminal.get("owner") or {}
            if (
                terminal.get("state") != "ESCALATE_STANDARD"
                or terminal.get("dispatch_status") != "pending"
                or owner
                != {
                    "thread_id": thread_id,
                    "turn_id": parent["id"],
                    "run_id": ledger["source_run_id"],
                }
                or (terminal.get("handoff") or {}).get("payload_sha256")
                != ledger["handoff_sha256"]
            ):
                raise ValueError("Standard handoff changed")
            if (
                source is None
                or source["status"] != "completed"
                or source["owner_thread_id"] != thread_id
                or source["version"] != ledger["source_run_version"]
                or source["query"] != parent["user_message"]
                or row["parent_run_id"] != source["id"]
                or ledger["thread_id"] != thread_id
            ):
                raise ValueError("Standard source changed")
            source_context = json.loads(source["research_context"])
            if source_context.get("owner") != {
                "thread_id": thread_id,
                "turn_id": parent["id"],
            } or (source_context.get("operation") or {}).get("cancel_requested_at"):
                raise ValueError("Standard source cancelled or owner mismatch")
            if row["status"] not in {"pending", "running", "partial"} or (
                context.get("operation") or {}
            ).get("cancel_requested_at"):
                raise ValueError("Standard cancelled or terminal")
            if now < datetime.fromisoformat(
                ledger["admitted_at"]
            ) or now >= datetime.fromisoformat(ledger["deadline"]) - timedelta(
                seconds=STANDARD_BUDGET.finalization_reserve
            ):
                raise ValueError("Standard deadline exhausted")
            if operation_id is not None:
                if (
                    ledger["operation_id"] != operation_id
                    or (context.get("operation") or {}).get("active_operation_id")
                    != operation_id
                    or now >= datetime.fromisoformat(ledger["lease_until"])
                ):
                    raise ValueError("Standard stale operation")
            yield connection, context, ledger
            if write:
                connection.execute(
                    "UPDATE web_lookup_runs SET research_context = ?, updated_at = ?, version = version + 1 WHERE id = ?",
                    (json.dumps(context, ensure_ascii=False), now.isoformat(), run_id),
                )

    def check(
        self, run_id: str, thread_id: str, operation_id: str, now: datetime
    ) -> None:
        with self._transaction(
            run_id, thread_id, now, operation_id=operation_id, write=False
        ):
            pass

    def acquire(
        self, run_id: str, thread_id: str, operation_id: str, now: datetime
    ) -> dict:
        if not operation_id.strip():
            raise ValueError("Standard operation is required")
        with self._transaction(run_id, thread_id, now) as (connection, context, ledger):
            previous = ledger["operation_id"]
            active = (context.get("operation") or {}).get("active_operation_id") or ""
            if active != previous:
                raise ValueError("Standard execution owner mismatch")
            if previous and now < datetime.fromisoformat(ledger["lease_until"]):
                raise ValueError("Standard operation already leased")
            if operation_id in ledger["tokens"]:
                raise ValueError("Standard resumed operation requires a fresh token")
            if len(ledger["tokens"]) >= 100:
                raise ValueError("Standard resume budget exhausted")
            ledger["tokens"].append(operation_id)
            for entry in ledger["entries"].values():
                if entry["state"] == "reserved":
                    entry["state"] = "unknown"
            ledger.update(
                operation_id=operation_id,
                lease_until=(now + timedelta(seconds=LEASE_SECONDS)).isoformat(),
            )
            context["operation"] = {
                "active_operation_id": operation_id,
                "active_operation_started_at": now.isoformat(),
                "stage_started_at": now.isoformat(),
                "cancel_requested_at": None,
            }
            connection.execute(
                "UPDATE web_lookup_runs SET status = 'running', stage = 'standard_handoff' WHERE id = ?",
                (run_id,),
            )
            return deepcopy(ledger)

    def reserve(
        self,
        run_id: str,
        thread_id: str,
        operation_id: str,
        kind: str,
        target: str,
        now: datetime,
    ) -> dict:
        if kind not in {"read", "search"} or not target.strip():
            raise ValueError("invalid Standard dispatch")
        with self._transaction(run_id, thread_id, now, operation_id=operation_id) as (
            _,
            _,
            ledger,
        ):
            key = work_key(kind, target)
            prior = ledger["entries"].get(key)
            if prior:
                if prior["state"] != "completed":
                    raise ValueError(
                        "Standard dispatch result unavailable; automatic retry forbidden"
                    )
                if kind == "read":
                    ledger["reused_reads"] += 1
                return {"cached": True, "result": deepcopy(prior["result"])}
            counter, limit = (
                ("new_reads", STANDARD_BUDGET.max_reads)
                if kind == "read"
                else ("new_queries", STANDARD_BUDGET.max_queries)
            )
            if ledger[counter] >= limit:
                raise ValueError("Standard dispatch budget exhausted")
            ledger[counter] += 1
            ledger["cursor"] += 1
            ledger["lease_until"] = (now + timedelta(seconds=LEASE_SECONDS)).isoformat()
            ledger["entries"][key] = {
                "kind": kind,
                "target": target,
                "state": "reserved",
                "operation_id": operation_id,
                "cursor": ledger["cursor"],
                "origin": "standard",
            }
            return {"cached": False, "key": key, "deadline": ledger["deadline"]}

    def finish(
        self,
        run_id: str,
        thread_id: str,
        operation_id: str,
        key: str,
        now: datetime,
        *,
        result: dict | None = None,
        error: str = "",
    ) -> None:
        with self._transaction(run_id, thread_id, now, operation_id=operation_id) as (
            _,
            _,
            ledger,
        ):
            entry = ledger["entries"].get(key) or {}
            if (
                entry.get("state") != "reserved"
                or entry.get("operation_id") != operation_id
            ):
                raise ValueError("Standard dispatch owner/state mismatch")
            if not error:
                if not isinstance(result, dict):
                    raise ValueError("invalid Standard result")

                def body_size(value: dict) -> int:
                    return len(str(value.get("content") or value.get("readme") or ""))

                size = body_size(result) if entry["kind"] == "read" else 0
                total = sum(
                    body_size(item.get("result") or {})
                    for item in ledger["entries"].values()
                    if item["kind"] == "read" and item["state"] == "completed"
                )
                if (
                    size > STANDARD_BUDGET.max_source_chars
                    or total + size > STANDARD_BUDGET.max_total_chars
                ):
                    raise ValueError("Standard source text budget exhausted")
            entry.update(
                state="failed" if error else "completed",
                error=error,
                result=deepcopy(result) if result is not None else {},
            )

    def interrupt(
        self, run_id: str, thread_id: str, operation_id: str, now: datetime
    ) -> None:
        with self._transaction(run_id, thread_id, now, operation_id=operation_id) as (
            connection,
            context,
            ledger,
        ):
            for entry in ledger["entries"].values():
                if entry["state"] == "reserved":
                    entry["state"] = "unknown"
            ledger.update(operation_id="", lease_until="")
            context["operation"]["active_operation_id"] = None
            connection.execute(
                "UPDATE web_lookup_runs SET status = 'partial', stage = 'standard_handoff' WHERE id = ?",
                (run_id,),
            )
