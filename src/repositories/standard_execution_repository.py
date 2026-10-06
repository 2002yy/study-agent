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
from src.web.research.standard_plan import (
    action,
    build_result,
    discovered_urls,
    initial_actions,
    public_url,
    search_urls,
    validate_plan,
)


SCHEMA = "standard-dispatch-journal-v1"
LEASE_SECONDS = 15


class StandardResearchBusy(ValueError):
    """An active caller already owns planning or the next loop step."""


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
        finalizing: bool = False,
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
            cancelled = bool(
                (context.get("operation") or {}).get("cancel_requested_at")
            )
            expired = now >= datetime.fromisoformat(ledger["deadline"]) - timedelta(
                seconds=STANDARD_BUDGET.finalization_reserve
            )
            diagnostic_only = finalizing and (cancelled or expired)
            if (
                row["status"]
                not in (
                    {"pending", "running", "partial", "cancelled"}
                    if diagnostic_only
                    else {"pending", "running", "partial"}
                )
                or cancelled
                and not diagnostic_only
            ):
                raise ValueError("Standard cancelled or terminal")
            if (
                now < datetime.fromisoformat(ledger["admitted_at"])
                or expired
                and not diagnostic_only
            ):
                raise ValueError("Standard deadline exhausted")
            if operation_id is not None:
                if (
                    ledger["operation_id"] != operation_id
                    or (context.get("operation") or {}).get("active_operation_id")
                    != operation_id
                    or now >= datetime.fromisoformat(ledger["lease_until"])
                    and not diagnostic_only
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
                # A live lease is contention, not an integrity failure: the caller must
                # defer and retry, not mark the handoff blocked. StandardResearchBusy is a
                # ValueError subclass, so existing except ValueError behaviour is unchanged.
                raise StandardResearchBusy("Standard operation already leased")
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
            if (ledger.get("research") or {}).get("status") == "completed":
                raise ValueError("Standard research already completed")
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

    @staticmethod
    def _handoff(connection: Any, ledger: dict) -> dict:
        row = connection.execute(
            "SELECT rag_snapshot FROM chat_turns WHERE id = ?",
            (ledger["parent_turn_id"],),
        ).fetchone()
        return load_standard_handoff(
            json.loads(row["rag_snapshot"])["lookup_terminal"]["handoff"]
        )

    def research_snapshot(
        self, run_id: str, thread_id: str, operation_id: str, now: datetime
    ) -> dict:
        with self._transaction(
            run_id, thread_id, now, operation_id=operation_id, write=False
        ) as (connection, _, ledger):
            return {
                "handoff": self._handoff(connection, ledger),
                "ledger": deepcopy(ledger),
            }

    def begin_research_plan(
        self, run_id: str, thread_id: str, operation_id: str, now: datetime
    ) -> dict:
        with self._transaction(run_id, thread_id, now, operation_id=operation_id) as (
            connection,
            _,
            ledger,
        ):
            research = ledger.get("research")
            if research is not None:
                if research.get("schema") != "standard-research-loop-v1":
                    raise ValueError("unknown Standard loop schema")
                if (
                    research["status"] == "planning"
                    and research["planning_operation_id"] == operation_id
                ):
                    raise StandardResearchBusy("Standard planner already claimed")
                if research["plan"] is not None:
                    validate_plan(research["plan"], self._handoff(connection, ledger))
                    if (
                        hashlib.sha256(
                            json.dumps(research["plan"], sort_keys=True).encode()
                        ).hexdigest()
                        != research["plan_sha256"]
                    ):
                        raise ValueError("Standard saved plan digest mismatch")
                return {"invoke": False, "research": deepcopy(research)}
            ledger["research"] = {
                "schema": "standard-research-loop-v1",
                "status": "planning",
                "planner_calls": 1,
                "planning_operation_id": operation_id,
                "plan": None,
                "actions": [],
                "observations": [],
                "next_cursor": 0,
                "inflight": None,
                "result": None,
            }
            ledger["lease_until"] = (now + timedelta(seconds=LEASE_SECONDS)).isoformat()
            return {
                "invoke": True,
                "handoff": self._handoff(connection, ledger),
                "budget": {
                    "new_reads": ledger["new_reads"],
                    "new_queries": ledger["new_queries"],
                    "deadline": ledger["deadline"],
                    "planner_calls": 1,
                },
            }

    def save_research_plan(
        self,
        run_id: str,
        thread_id: str,
        operation_id: str,
        now: datetime,
        proposal: Any,
    ) -> None:
        with self._transaction(run_id, thread_id, now, operation_id=operation_id) as (
            connection,
            _,
            ledger,
        ):
            research = ledger["research"]
            if (
                research["status"] != "planning"
                or research["planning_operation_id"] != operation_id
            ):
                raise ValueError("Standard planner owner/state mismatch")
            handoff = self._handoff(connection, ledger)
            plan = validate_plan(proposal, handoff)
            research.update(
                status="planned",
                plan=plan,
                actions=initial_actions(plan, handoff),
                plan_sha256=hashlib.sha256(
                    json.dumps(plan, sort_keys=True).encode()
                ).hexdigest(),
            )

    def claim_research_step(
        self, run_id: str, thread_id: str, operation_id: str, now: datetime
    ) -> dict | None:
        with self._transaction(run_id, thread_id, now, operation_id=operation_id) as (
            connection,
            _,
            ledger,
        ):
            research = ledger["research"]
            if research["status"] != "planned":
                raise ValueError("Standard research plan not executable")
            if research["next_cursor"] >= len(research["actions"]):
                return None
            prior = research["inflight"]
            if prior and prior["operation_id"] == operation_id:
                raise StandardResearchBusy("Standard research step already claimed")
            step = deepcopy(research["actions"][research["next_cursor"]])
            handoff = self._handoff(connection, ledger)
            fields = step.get("fields")
            if (
                step.get("kind") not in {"read", "search"}
                or not isinstance(step.get("target"), str)
                or not isinstance(fields, list)
                or not fields
                or not all(
                    isinstance(field, str) and field in handoff["unresolved_fields"]
                    for field in fields
                )
                or step.get("id") != work_key(step["kind"], step["target"])
            ):
                raise ValueError("invalid persisted Standard action")
            if step["kind"] == "search":
                if step["target"] not in {
                    query
                    for gap in research["plan"]["gaps"]
                    for query in gap["queries"]
                }:
                    raise ValueError("Standard action escaped saved query plan")
            else:
                allowed = discovered_urls(handoff)
                for saved in ledger["entries"].values():
                    if saved["kind"] == "search" and saved["state"] == "completed":
                        allowed.update(search_urls(saved["result"], handoff["query"]))
                if not public_url(step["target"]) or step["target"] not in allowed:
                    raise ValueError("Standard action has no discovery provenance")
            entry = ledger["entries"].get(work_key(step["kind"], step["target"])) or {}
            step.update(
                operation_id=operation_id,
                cursor=research["next_cursor"],
                was_cached=entry.get("state") == "completed",
            )
            research["inflight"] = step
            ledger["lease_until"] = (now + timedelta(seconds=LEASE_SECONDS)).isoformat()
            return deepcopy(step)

    def observe_research_step(
        self, run_id: str, thread_id: str, operation_id: str, now: datetime, step: dict
    ) -> None:
        with self._transaction(run_id, thread_id, now, operation_id=operation_id) as (
            _,
            _,
            ledger,
        ):
            research = ledger["research"]
            if (
                research["inflight"] != step
                or research["next_cursor"] != step["cursor"]
            ):
                raise ValueError("Standard research cursor mismatch")
            entry = ledger["entries"].get(work_key(step["kind"], step["target"])) or {}
            if entry.get("state") not in {"completed", "failed"}:
                raise ValueError("Standard observation requires a saved outcome")
            result = entry.get("result") or {}
            body = result.get("content") or result.get("readme") or ""
            readable = (
                step["kind"] == "read"
                and entry["state"] == "completed"
                and isinstance(body, str)
                and bool(body.strip())
                and (result.get("ok") is True or result.get("read_backed") is True)
            )
            observation = {
                "action_id": step["id"],
                "kind": step["kind"],
                "target": step["target"],
                "fields": step["fields"],
                "outcome": entry["state"],
                "readable": bool(readable),
                "reused": step["was_cached"],
                "origin": entry.get("origin", "standard"),
                "content_sha256": hashlib.sha256(body.encode()).hexdigest()
                if readable
                else "",
                "support_status": "NOT_EVALUATED",
            }
            research["observations"].append(observation)
            if step["kind"] == "search" and entry["state"] == "completed":
                known = {item["id"] for item in research["actions"]}
                additions: list[dict] = []
                for url in search_urls(result, research["plan"]["query"]):
                    item = action("read", url, step["fields"], origin="discovery")
                    if (
                        item["id"] not in known
                        and len(research["actions"]) + len(additions) < 48
                    ):
                        additions.append(item)
                        known.add(item["id"])
                research["actions"][step["cursor"] + 1 : step["cursor"] + 1] = additions
            research["next_cursor"] += 1
            research["inflight"] = None

    def complete_research(
        self, run_id: str, thread_id: str, operation_id: str, now: datetime, reason: str
    ) -> dict:
        allowed = {
            "plan_exhausted",
            "ready_for_binding",
            "budget_exhausted",
            "deadline",
            "cancelled",
            "result_unknown",
            "planner_invalid",
            "planner_failed",
            "conflict_requires_binding",
        }
        if reason not in allowed:
            raise ValueError("invalid Standard research stop reason")
        with self._transaction(
            run_id, thread_id, now, operation_id=operation_id, finalizing=True
        ) as (connection, context, ledger):
            research = ledger.setdefault(
                "research",
                {
                    "schema": "standard-research-loop-v1",
                    "status": "planning",
                    "planner_calls": 0,
                    "plan": None,
                    "actions": [],
                    "observations": [],
                    "next_cursor": 0,
                    "inflight": None,
                    "result": None,
                },
            )
            handoff = self._handoff(connection, ledger)
            if research["schema"] != "standard-research-loop-v1":
                raise ValueError("unknown Standard loop schema")
            if research["plan"] is not None:
                validate_plan(research["plan"], handoff)
                if (
                    hashlib.sha256(
                        json.dumps(research["plan"], sort_keys=True).encode()
                    ).hexdigest()
                    != research["plan_sha256"]
                ):
                    raise ValueError("Standard saved plan digest mismatch")
            if (context.get("operation") or {}).get("cancel_requested_at"):
                reason = "cancelled"
            elif now >= datetime.fromisoformat(ledger["deadline"]) - timedelta(
                seconds=STANDARD_BUDGET.finalization_reserve
            ):
                reason = "deadline"
            result = build_result(ledger, handoff, reason)
            ledger["research"].update(status="completed", result=result, inflight=None)
            ledger.update(operation_id="", lease_until="")
            context["operation"]["active_operation_id"] = None
            connection.execute(
                "UPDATE web_lookup_runs SET status = ?, stage = 'standard_handoff' WHERE id = ?",
                ("cancelled" if reason == "cancelled" else "partial", run_id),
            )
            return deepcopy(result)


    # --- Standard-4: parent continuation artifact -------------------------------

    CONTINUATION_SCHEMA = "standard-auto-continuation-v1"

    def child_ledger(self, run_id: str, thread_id: str) -> dict:
        """Read a Standard child journal for projection; owner-checked, no write."""

        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT research_context, owner_thread_id FROM web_lookup_runs WHERE id = ?",
                (run_id,),
            ).fetchone()
        if row is None or row["owner_thread_id"] != thread_id:
            raise ValueError("Standard child owner mismatch")
        ledger = (json.loads(row["research_context"]).get("standard")) or {}
        if ledger.get("schema") != SCHEMA:
            raise ValueError("invalid Standard journal")
        return ledger

    def continuation_artifact(self, parent_turn_id: str, thread_id: str) -> dict | None:
        """The saved continuation artifact, if this parent already reached a terminal state."""

        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT rag_snapshot, thread_id FROM chat_turns WHERE id = ?",
                (parent_turn_id,),
            ).fetchone()
        if row is None or row["thread_id"] != thread_id:
            return None
        snapshot = json.loads(row["rag_snapshot"])
        terminal = snapshot.get("lookup_terminal") or {}
        artifact = snapshot.get("standard_continuation")
        if (
            terminal.get("dispatch_status") in {"completed", "blocked"}
            and isinstance(artifact, dict)
        ):
            return deepcopy(artifact)
        return None

    def block_continuation(
        self, parent_turn_id: str, thread_id: str, reason: str
    ) -> dict:
        """Record a deterministic integrity failure; only a bounded reason code is saved."""

        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT rag_snapshot, thread_id FROM chat_turns WHERE id = ?",
                (parent_turn_id,),
            ).fetchone()
            if row is None or row["thread_id"] != thread_id:
                raise ValueError("Standard parent unavailable")
            snapshot = json.loads(row["rag_snapshot"])
            terminal = snapshot.get("lookup_terminal") or {}
            if terminal.get("state") != "ESCALATE_STANDARD":
                raise ValueError("no pending server-owned Standard handoff")
            if terminal.get("dispatch_status") in {"completed", "blocked"}:
                existing = snapshot.get("standard_continuation")
                return deepcopy(existing) if isinstance(existing, dict) else {}
            terminal["dispatch_status"] = "blocked"
            artifact = {
                "schema_version": self.CONTINUATION_SCHEMA,
                "child_run_id": "",
                "reason": str(reason),
                "publication_authority": False,
            }
            snapshot["lookup_terminal"] = terminal
            snapshot["standard_continuation"] = artifact
            connection.execute(
                "UPDATE chat_turns SET rag_snapshot = ? WHERE id = ?",
                (json.dumps(snapshot, ensure_ascii=False), parent_turn_id),
            )
        return deepcopy(artifact)

    def finalize_continuation(
        self,
        run_id: str,
        thread_id: str,
        now: datetime,
        *,
        artifact: dict,
    ) -> dict:
        """Transactionally verify the child and publish the parent artifact.

        Reuses _transaction, which already re-verifies owner, parent completion, the pending
        terminal, the handoff digest, the source run and the child parent_run_id.
        """

        with self._transaction(
            run_id, thread_id, now, finalizing=True
        ) as (connection, _context, ledger):
            child = connection.execute(
                "SELECT research_context, parent_run_id, owner_thread_id FROM web_lookup_runs WHERE id = ?",
                (run_id,),
            ).fetchone()
            if (
                child is None
                or child["owner_thread_id"] != thread_id
                or child["parent_run_id"] != ledger["source_run_id"]
            ):
                raise ValueError("Standard child identity mismatch")
            research = (json.loads(child["research_context"]).get("standard") or {}).get(
                "research"
            ) or {}
            if research.get("status") != "completed" or not isinstance(
                research.get("result"), dict
            ):
                raise ValueError("Standard child not terminal")
            row = connection.execute(
                "SELECT rag_snapshot FROM chat_turns WHERE id = ?",
                (ledger["parent_turn_id"],),
            ).fetchone()
            snapshot = json.loads(row["rag_snapshot"])
            terminal = snapshot.get("lookup_terminal") or {}
            if terminal.get("dispatch_status") in {"completed", "blocked"}:
                existing = snapshot.get("standard_continuation")
                return deepcopy(existing) if isinstance(existing, dict) else {}
            saved = dict(artifact)
            saved["child_run_id"] = run_id
            saved["source_run_id"] = ledger["source_run_id"]
            saved["handoff_sha256"] = ledger["handoff_sha256"]
            saved["publication_authority"] = False
            terminal["dispatch_status"] = "completed"
            snapshot["lookup_terminal"] = terminal
            snapshot["standard_continuation"] = saved
            connection.execute(
                "UPDATE chat_turns SET rag_snapshot = ? WHERE id = ?",
                (json.dumps(snapshot, ensure_ascii=False), ledger["parent_turn_id"]),
            )
            return deepcopy(saved)
