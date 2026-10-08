"""Read-only, bounded presentation of durable research; grants no publication."""

from __future__ import annotations

import hashlib
from typing import Any
from urllib.parse import urlsplit

from src.application.research_evidence import research_sources_snapshot
from src.web.research.standard_binding_projection import project_trusted_sources
from src.repositories.deep_publication_repository import validate_recorded_publication
from src.web.research.runtime import load_runtime_cursor


def _object(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _count(value: Any) -> int | None:
    return (
        value
        if isinstance(value, int) and not isinstance(value, bool) and value >= 0
        else None
    )


def _url(value: Any) -> str:
    if (
        not isinstance(value, str)
        or len(value) > 2048
        or any(ord(c) <= 32 for c in value)
        or "\\" in value
    ):
        return ""
    try:
        parsed = urlsplit(value)
        return (
            value
            if parsed.scheme in {"http", "https"}
            and parsed.hostname
            and not parsed.username
            and not parsed.password
            else ""
        )
    except ValueError:
        return ""


def research_run_block(run: Any, turn_web_tools: Any = None) -> dict[str, Any]:
    context = _object(run.research_context)
    metrics = _object(context.get("claim_engine_metrics"))
    brief = _object(context.get("claim_engine_evidence_brief"))
    if brief.get("schema_version") != "research-evidence-brief-v1":
        brief = {}
    runtime = load_runtime_cursor(context)
    standard = _object(context.get("standard"))
    tier = (
        "deep"
        if run.stage == "deep_handoff"
        or _object(context.get("deep")).get("seed")
        or context.get("research_mode") == "deep"
        else (
            "standard"
            if run.stage == "standard_handoff"
            or standard.get("schema") == "standard-dispatch-journal-v1"
            else "lookup"
        )
    )
    sources = []
    snapshot = research_sources_snapshot(run)
    seen: set[str] = set()
    for record in snapshot["selected_sources"][:20]:
        item = _object(record.get("item"))
        assessment = _object(record.get("assessment"))
        url = _url(item.get("url") or assessment.get("url"))
        if not url:
            continue
        source_id = str(
            assessment.get("source_id") or hashlib.sha256(url.encode()).hexdigest()[:20]
        )
        if source_id in seen:
            continue
        seen.add(source_id)
        sources.append(
            {
                "block_id": f"{run.id}:source:{source_id}",
                "source_id": source_id,
                "run_id": run.id,
                "source_truth_version": snapshot["source_truth_version"],
                "title": str(item.get("title") or assessment.get("title") or url)[:200],
                "url": url,
                "read_status": record.get("read_status") or "unknown",
                "publication_status": "observation_only",
            }
        )
    trusted = []
    trusted_read_count = None
    if tier == "standard" and standard.get("schema") == "standard-dispatch-journal-v1":
        # Existing projection re-hashes durable read bodies. No new read/model.
        try:
            trusted = project_trusted_sources(standard)
            trusted_read_count = len({s.url for s in trusted})
        except (KeyError, TypeError, AttributeError, ValueError):
            trusted = []
        for source in trusted[:20]:
            url = _url(source.url)
            source_id = hashlib.sha256(url.encode()).hexdigest()[:20]
            if not url or source_id in seen or len(sources) >= 20:
                continue
            seen.add(source_id)
            sources.append(
                {
                    "block_id": f"{run.id}:source:{source_id}",
                    "source_id": source_id,
                    "run_id": run.id,
                    "source_truth_version": run.version,
                    "title": url[:200],
                    "url": url,
                    "read_status": "read",
                    "content_sha256": source.content_sha256,
                    "publication_status": "observation_only",
                }
            )
    gaps = []
    result = _object(_object(standard.get("research")).get("result"))
    for field, gap in list(_object(result.get("gap_states")).items())[:12]:
        gap = _object(gap)
        state = gap.get("research_state")
        support = gap.get("support_status")
        if state not in {"OPEN", "SOURCE_ACQUIRED"} or support not in {
            "NOT_EVALUATED",
            "SPAN_BOUND",
            "SUPPORT",
            "CONFLICT",
            "INSUFFICIENT",
        }:
            continue
        gaps.append(
            {
                "block_id": f"{run.id}:gap:{hashlib.sha256(str(field).encode()).hexdigest()[:20]}",
                "field": str(field)[:120],
                "research_state": state,
                "support_status": support,
                "publication_status": "observation_only",
            }
        )
    bindings = []
    known_urls = {source["url"] for source in sources}
    seen_bindings: set[tuple[str, str]] = set()
    rows = brief.get("eligible_evidence")
    for row in (rows if isinstance(rows, list) else [])[:24]:
        row = _object(row)
        evidence_id = str(row.get("evidence_id") or "")[:200]
        claim_id = str(row.get("claim_id") or "")[:200]
        relation = row.get("relation")
        url = _url(row.get("url"))
        if (
            not evidence_id
            or not claim_id
            or url not in known_urls
            or relation not in {"supports", "contradicts"}
            or (evidence_id, claim_id) in seen_bindings
        ):
            continue
        seen_bindings.add((evidence_id, claim_id))
        bindings.append(
            {
                "block_id": f"{run.id}:binding:{hashlib.sha256((evidence_id + ':' + claim_id).encode()).hexdigest()[:20]}",
                "evidence_id": evidence_id,
                "claim_id": claim_id,
                "source_url": url,
                "relation": relation,
                "locator": str(row.get("locator") or "")[:300],
                "publication_status": "observation_only",
            }
        )
    conflicts = brief.get("unresolved_conflicts")
    phase = (
        runtime.cursor.phase
        if runtime.available and runtime.cursor is not None
        else metrics.get("phase") or _object(standard.get("research")).get("status")
    )
    gate = brief.get("gate_status")
    web_tools = _object(turn_web_tools)
    owned_tools = web_tools if web_tools.get("run_id") == run.id else {}
    observed_tools = (
        owned_tools
        if _object(owned_tools.get("recovery")).get("mode")
        in {"lookup", "standard", "deep"}
        else {}
    )
    read_count = _count(metrics.get("read_count"))
    if "read_count" not in metrics:
        read_count = (
            _count(_object(context.get("read_summary")).get("successful"))
            if context.get("research_mode") == "deep" or not observed_tools
            else _count(observed_tools.get("read_count"))
        )
    return {
        "block_id": f"{run.id}:research",
        "run_id": run.id,
        "revision": run.version,
        "tier": tier,
        "research_status": run.status,
        "stage": run.stage,
        "publication_status": "observation_only",
        "candidate_count": _count(metrics.get("candidate_count"))
        if "candidate_count" in metrics
        else _count(observed_tools.get("candidate_count")),
        "read_count": trusted_read_count if tier == "standard" else read_count,
        "open_critical_gap_count": _count(metrics.get("open_critical_gap_count")),
        "read_attempt_count": _count(standard.get("new_reads")),
        "sources": sources,
        "updated_at": run.updated_at,
        "gaps": gaps,
        "bindings": bindings,
        "research_phase": str(phase)[:80] if isinstance(phase, str) else None,
        "wave": runtime.cursor.wave_index
        if runtime.available and runtime.cursor is not None
        else None,
        "stop_reason": str(run.stop_reason or "")[:120],
        "evidence_gate_status": gate
        if gate
        in {"pass", "partial", "conditional_pass", "fail", "unavailable", "abstain"}
        else None,
        "conflict_count": len(conflicts) if isinstance(conflicts, list) else None,
        "sources_truncated": len(run.selected_sources) > 20,
    }


def research_run_event(run: Any) -> dict[str, Any]:
    owner = _object(_object(run.research_context).get("owner"))
    return {
        "protocol_version": 1,
        "snapshot_kind": "run",
        "turn_updated_at": None,
        "session_id": run.owner_thread_id,
        "turn_id": owner.get("turn_id"),
        "publication_status": "observation_only",
        "publication_authority": False,
        "blocks": [research_run_block(run)],
        "watch": True,
        "truncated": False,
        "audit_status": None,
        "audit_integrity": "absent",
    }


def research_presentation(turn: Any, runs: list[Any]) -> dict[str, Any]:
    # Ownership is rechecked even when the repository query already filters turn.
    owned = [
        run
        for run in runs
        if run.owner_thread_id == turn.thread_id
        and _object(_object(run.research_context).get("owner")).get("turn_id")
        == turn.id
    ]
    ordered = sorted(owned, key=lambda r: (r.created_at, r.id))
    visible = ordered if len(ordered) <= 20 else [ordered[0], *ordered[-19:]]
    web_tools = _object(_object(turn.rag_snapshot).get("web_tools"))
    blocks = [research_run_block(run, web_tools) for run in visible]
    audit = _object(_object(turn.rag_snapshot).get("deep_publication"))
    audit_valid = (
        validate_recorded_publication(
            audit, parent_turn_id=turn.id, thread_id=turn.thread_id
        )[0]
        if audit
        else False
    )
    audit_status = audit.get("dispatch_status") if audit_valid else None
    rag = _object(turn.rag_snapshot)
    watch = (
        any(run.status in {"pending", "running"} for run in owned)
        or getattr(turn, "status", "")
        in {"pending", "prepared", "generating", "running"}
        or any(
            _object(rag.get(key)).get("dispatch_status") == "pending"
            for key in ("standard_continuation", "deep_terminal", "deep_publication")
        )
    )
    return {
        "protocol_version": 1,
        "snapshot_kind": "turn",
        "turn_updated_at": getattr(turn, "updated_at", None),
        "session_id": turn.thread_id,
        "turn_id": turn.id,
        "publication_status": "observation_only",
        "blocks": blocks,
        "truncated": len(owned) > 20 or len(runs) >= 100,
        "audit_status": audit_status
        if audit_status in {"pending", "audited", "blocked"}
        else None,
        "audit_integrity": "valid" if audit_valid else "invalid" if audit else "absent",
        # Audited Deep candidates are never copied into this presentation.
        "publication_authority": False,
        "watch": watch,
    }
