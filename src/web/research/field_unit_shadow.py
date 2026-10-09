"""Pre-read field obligations and deterministic verification, observation only.

This private protocol does not populate Claim Engine units or authorize stop.
Requirements come only from the existing strict request planner; candidates
come only from successful reads already admitted as eligible strong support.
"""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import re
from typing import Any

from src.web.research.contracts import ResearchState
from src.web.research.evidence_gate import (
    STRONG_EVIDENCE_THRESHOLD,
    evidence_link_eligibility,
)
from src.web.research.identity import ResearchIdentity, resolve_identity
from src.web.research.lookup_terminal import requested_lookup_fields
from src.web.research.standard_binding import Claim, TrustedSource, bind_field
from src.web.research.standard_binding_projection import evidence_windows
from src.web.research.standard_plan import public_url
from src.web.research_recovery import model_targets

KEY = "field_unit_shadow"
SCHEMA = "research-field-unit-shadow-v1"


def exact_identities(text: str) -> tuple[ResearchIdentity | None, ...]:
    # ASCII boundaries permit Chinese prose without accepting version suffixes.
    anchors = re.finditer(
        r"(?<![A-Za-z0-9_])([A-Za-z][A-Za-z_-]*?)[\s_-]*"
        r"(\d+(?:\.\d+)*(?:(?:a|b|rc)\d+)?)(?![A-Za-z0-9_.+-])",
        text,
        re.I,
    )
    return tuple(resolve_identity(match[1], match[2]) for match in anchors)


def digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()


def declare(query: str) -> dict[str, Any]:
    """Called at new Deep admission, before any child evidence or model call."""
    targets = model_targets(query)
    fields = requested_lookup_fields(query)
    target = resolve_identity(*targets[0]) if len(targets) == 1 else None
    if exact_identities(query) != (target,):
        target = None
    requirements = [
        {
            "unit_id": digest([query, field]),
            "field": field,
            "question_span": [0, len(query)],
            "modality": "text",
        }
        for field in fields
    ]
    frozen = {
        "schema_version": SCHEMA,
        "query": query,
        "target": list(targets[0]) if target else [],
        "requirements": requirements if target else [],
        "publication_authority": False,
    }
    return {
        "declaration": frozen,
        "declaration_sha256": digest(frozen),
        "status": "DECLARED" if target and fields else "NOT_DECLARED",
        "stop_authority": False,
        "publication_authority": False,
    }


def seal_read(raw_read: dict[str, Any], body: str) -> dict[str, Any]:
    """Trusted read boundary: bind the stored slice to the actual input bytes."""
    original = str(raw_read.get("content") or "")
    input_digest = hashlib.sha256(original.encode()).hexdigest()
    reported = raw_read.get("content_sha256")
    return {
        "body_sha256": hashlib.sha256(body.encode()).hexdigest(),
        "input_sha256": input_digest,
        "input_hash_valid": reported is None or reported == input_digest,
    }


def safe_observe(
    shadow: Any, state: ResearchState, records: list[dict[str, Any]]
) -> dict[str, Any]:
    """A malformed observation never changes the existing runtime outcome."""
    try:
        return observe(shadow, state, records)
    except Exception:
        return {
            "status": "INVALID",
            "coverage": [],
            "publication_authority": False,
            "stop_authority": False,
        }


def observe(
    shadow: dict[str, Any], state: ResearchState, records: list[dict[str, Any]]
) -> dict[str, Any]:
    """Recompute from persisted evidence; retries never append duplicate units."""
    frozen = shadow.get("declaration")
    if (
        not isinstance(frozen, dict)
        or frozen.get("schema_version") != SCHEMA
        or frozen.get("publication_authority") is not False
        or shadow.get("declaration_sha256") != digest(frozen)
        or declare(str(frozen.get("query") or ""))["declaration"] != frozen
    ):
        return {
            **deepcopy(shadow),
            "status": "INVALID",
            "coverage": [],
            "publication_authority": False,
            "stop_authority": False,
        }
    if not frozen["requirements"]:
        return {
            **deepcopy(shadow),
            "status": "NOT_DECLARED",
            "coverage": [],
            "publication_authority": False,
            "stop_authority": False,
        }
    critical = [claim for claim in state.claims if claim.priority == "critical"]
    if (
        len(critical) != 1
        or len(state.questions) != 1
        or state.questions[0].question_surface != frozen["query"]
    ):
        return {
            **deepcopy(shadow),
            "status": "WAITING_FOR_OWNED_CLAIM",
            "coverage": [],
            "publication_authority": False,
            "stop_authority": False,
        }
    claim = critical[0]
    if claim.question_id != state.questions[0].id:
        return {
            **deepcopy(shadow),
            "status": "INVALID",
            "coverage": [],
            "publication_authority": False,
            "stop_authority": False,
        }
    evidence = {item.evidence_id: item for item in state.evidence}
    links = {
        link.evidence_id: link
        for link in state.evidence_links
        if link.claim_id == claim.id
        and link.relation == "supports"
        and link.strength >= STRONG_EVIDENCE_THRESHOLD
        and evidence_link_eligibility(
            claim=claim,
            link=link,
            evidence=evidence.get(link.evidence_id),
            reference_date=state.reference_date,
        )
    }
    has_contradiction = any(
        link.claim_id == claim.id
        and link.relation == "contradicts"
        and link.strength >= STRONG_EVIDENCE_THRESHOLD
        and evidence_link_eligibility(
            claim=claim,
            link=link,
            evidence=evidence.get(link.evidence_id),
            reference_date=state.reference_date,
        )
        for link in state.evidence_links
    )
    target = (str(frozen["target"][0]), str(frozen["target"][1]))
    candidates: list[dict[str, Any]] = []
    for record in records:
        link = links.get(str(record.get("field_shadow_evidence_id") or ""))
        read = record.get("read") or {}
        seal = record.get("field_shadow_read") or {}
        body = str(read.get("content") or "")
        if (
            link is None
            or read.get("ok") is not True
            or seal.get("input_hash_valid") is not True
            or seal.get("body_sha256") != hashlib.sha256(body.encode()).hexdigest()
        ):
            continue
        url = str((record.get("item") or {}).get("url") or "")
        if not public_url(url):
            continue
        source = TrustedSource(url, seal["body_sha256"], body, link.source_role)
        source_evidence = evidence[link.evidence_id]
        valid_spans = [
            span for span in source_evidence.anchored_spans if span and span in body
        ]
        for window, start, end in evidence_windows(body):
            observed = exact_identities(window)
            if (
                not observed
                or observed[0] is None
                or observed != (resolve_identity(*target),)
                or not any(window in span for span in valid_spans)
            ):
                continue
            for unit in frozen["requirements"]:
                field = unit["field"]
                proposal = Claim(
                    field, url, source.content_sha256, window, span_start=start
                )
                if field == "version":
                    # A named exact version proves only that identity, not a date,
                    # latest status, performance or the rest of the question.
                    value = observed[0].version
                    status = "SUPPORT"
                else:
                    # The field relation must belong to the named release, not
                    # another noun in the same sentence or a negated assertion.
                    direct_release = re.fullmatch(
                        r"[A-Za-z][A-Za-z_-]*?[\s_-]*\d+(?:\.\d+)*"
                        r"\s+(?:(?:was\s+)?released(?:\s+on)?\s+|release\s+date\s*:\s*)"
                        r"\d{4}-\d{2}-\d{2}[.!]?",
                        window,
                        re.I,
                    )
                    bound: dict[str, Any] = (
                        bind_field(field, [proposal], [source])
                        if field != "release_date" or direct_release
                        else {"status": "SPAN_BOUND"}
                    )
                    status = bound["status"]
                    value = (
                        bound["supports"][0]["normalized_value"]
                        if status == "SUPPORT"
                        else ""
                    )
                candidates.append(
                    {
                        "unit_id": unit["unit_id"],
                        "field": field,
                        "claim_id": claim.id,
                        "question_id": claim.question_id,
                        "requested_identity": list(target),
                        "evidence_id": link.evidence_id,
                        "source_cluster_id": link.source_cluster_id,
                        "source_role": link.source_role,
                        "source_url": url,
                        "content_sha256": source.content_sha256,
                        "source_span": [start, end],
                        "quote": window,
                        "status": status,
                        "value": value,
                    }
                )
    coverage = []
    for unit in frozen["requirements"]:
        supported = [
            row
            for row in candidates
            if row["unit_id"] == unit["unit_id"] and row["status"] == "SUPPORT"
        ]
        values = {row["value"] for row in supported}
        clusters = {row["source_cluster_id"] for row in supported}
        topology_ok = (
            len(clusters) >= claim.evidence_requirement.min_independent_sources
            and claim.state != "unavailable"
            and not has_contradiction
            and not any(gap.claim_id == claim.id for gap in state.conflict_gaps)
            and (
                not claim.evidence_requirement.requires_primary_source
                or any(row["source_role"] == "primary" for row in supported)
            )
        )
        status = (
            "CONFLICT"
            if len(values) > 1
            else "COVERED"
            if values and topology_ok
            else "PARTIAL"
            if values
            else "NOT_EVALUATED"
        )
        coverage.append(
            {
                **unit,
                "status": status,
                "supporting_clusters": len(clusters),
                "required_clusters": claim.evidence_requirement.min_independent_sources,
                "candidates": [
                    row for row in candidates if row["unit_id"] == unit["unit_id"]
                ],
            }
        )
    return {
        "declaration": deepcopy(frozen),
        "declaration_sha256": shadow["declaration_sha256"],
        "status": "OBSERVED",
        "coverage": coverage,
        "publication_authority": False,
        "stop_authority": False,
    }
