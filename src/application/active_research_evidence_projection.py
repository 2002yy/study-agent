"""Active Claim Engine evidence-state and brief projections.

Pure projections extracted from the active runtime. Runtime persistence, read
scheduling and model calls stay owned by ActiveResearchRuntimeExecutor.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from typing import Any

from src.domain.evidence import ClaimEvidenceLinkV1, build_evidence_snapshot
from src.web.research.contracts import (
    EvidenceCluster,
    ResearchBrief,
    ResearchClaimEvidenceLink,
    ResearchEvidence,
    ResearchState,
    build_research_state,
)
from src.web.research.evidence_gate import EvidenceGateResult
from src.web.research.grounded_excerpts import (
    ANSWER_SHAPE_CONTRACT,
    EXCERPT_MAX_CHARS,
    EXCERPT_TOTAL_CHARS,
    grounded_excerpt,
    grounded_input_enabled,
)


def _evidence_snapshot(
    run_id: str,
    selected_sources: list[dict[str, Any]],
    rejected_sources: list[dict[str, Any]],
):
    return build_evidence_snapshot(
        rag={
            "research_sources": {
                "run_id": run_id,
                "provider_status": "found",
                "source_truth_version": 2,
                "selected_sources": selected_sources,
                "rejected_sources": rejected_sources,
            }
        }
    )


def _evidence_id_for_record(
    run_id: str,
    record: Mapping[str, Any],
    selected_sources: list[dict[str, Any]],
    rejected_sources: list[dict[str, Any]],
) -> str:
    item = record.get("item")
    url = str(item.get("url") or "") if isinstance(item, Mapping) else ""
    for ref in _evidence_snapshot(run_id, selected_sources, rejected_sources).refs:
        if ref.url == url and ref.lifecycle_status == "selected":
            return ref.id
    raise ValueError("server-owned evidence identity unavailable")


def _add_extracted_evidence(state: ResearchState, *, evidence_id: str, link: Any) -> ResearchState:
    evidence = {item.evidence_id: item for item in state.evidence}
    evidence[evidence_id] = ResearchEvidence(
        evidence_id=evidence_id,
        locator=link.locator,
        anchored_spans=link.anchored_spans,
        lifecycle_status="read",
        extraction_status="eligible",
        published_at=link.published_at,
    )
    links = {
        (item.claim_id, item.evidence_id, item.relation): item
        for item in state.evidence_links
    }
    key = (link.claim_id, evidence_id, link.relation)
    links[key] = ResearchClaimEvidenceLink(
        link=ClaimEvidenceLinkV1(
            claim_id=link.claim_id,
            evidence_id=evidence_id,
            support_type=link.relation,
            confidence=link.strength,
        ),
        source_role=link.source_role,
        source_cluster_id=link.source_cluster_id,
        locator=link.locator,
        caveats=link.caveats,
    )
    clusters: dict[str, EvidenceCluster] = {item.id: item for item in state.source_clusters}
    current = clusters.get(link.source_cluster_id)
    clusters[link.source_cluster_id] = EvidenceCluster(
        id=link.source_cluster_id,
        evidence_ids=tuple(dict.fromkeys((*((current.evidence_ids) if current else ()), evidence_id))),
        source_role=link.source_role,
        independence_key=(current.independence_key if current else link.source_cluster_id),
    )
    return build_research_state(
        mode=state.mode,
        questions=state.questions,
        claims=state.claims,
        evidence=evidence.values(),
        evidence_links=links.values(),
        source_clusters=clusters.values(),
        gaps=state.gaps,
        conflict_gaps=state.conflict_gaps,
        budget=state.budget,
        trace=state.trace,
        brief=state.brief,
        reference_date=state.reference_date,
        known_evidence_ids=evidence,
    )


def _state_after_gate(state: ResearchState, gate: EvidenceGateResult) -> ResearchState:
    open_claims = set(gate.open_critical_claims)
    claims = tuple(
        replace(
            claim,
            state=(
                "contested"
                if any(conflict.claim_id == claim.id for conflict in gate.conflicts)
                else "unresolved"
                if claim.id in open_claims
                else "satisfied"
                if claim.priority == "critical"
                else claim.state
            ),
        )
        for claim in state.claims
    )
    claims_by_id = {claim.id: claim for claim in state.claims}
    gaps = tuple(
        replace(
            gap,
            state=(
                "open"
                if gap.claim_id in open_claims
                else "resolved"
                if claims_by_id.get(gap.claim_id) is not None
                and claims_by_id[gap.claim_id].priority == "critical"
                else gap.state
            ),
        )
        for gap in state.gaps
    )
    brief = ResearchBrief(
        claim_ids=tuple(claim.id for claim in claims),
        unresolved_claim_ids=tuple(sorted(open_claims)),
        conflict_gap_ids=tuple(item.id for item in gate.conflicts),
        outline=("eligible_evidence", "claim_links", "conflicts", "open_gaps", "gate"),
    )
    known = tuple(item.evidence_id for item in state.evidence)
    return build_research_state(
        mode=state.mode,
        questions=state.questions,
        claims=claims,
        evidence=state.evidence,
        evidence_links=state.evidence_links,
        source_clusters=state.source_clusters,
        gaps=gaps,
        conflict_gaps=gate.conflicts,
        budget=state.budget,
        trace=state.trace,
        brief=brief,
        reference_date=state.reference_date,
        known_evidence_ids=known,
    )


def _evidence_brief(
    state: ResearchState,
    gate: EvidenceGateResult | None,
    selected_sources: list[dict[str, Any]],
) -> dict[str, Any]:
    records_by_id = {
        str(record.get("candidate_id")): record for record in selected_sources
    }
    grounded_input = grounded_input_enabled()
    excerpt_budget = EXCERPT_TOTAL_CHARS if grounded_input else 0
    evidence_rows: list[dict[str, Any]] = []
    for link in state.evidence_links:
        evidence = next((item for item in state.evidence if item.evidence_id == link.evidence_id), None)
        if evidence is None or evidence.extraction_status != "eligible":
            continue
        record = next(
            (
                item
                for item in records_by_id.values()
                if (
                    isinstance(item.get("extractions"), Mapping)
                    and isinstance(item["extractions"].get(link.claim_id), Mapping)
                    and str(item["extractions"][link.claim_id].get("locator") or "") == link.locator
                )
                or (
                    isinstance(item.get("extraction"), Mapping)
                    and item["extraction"].get("claim_id") == link.claim_id
                    and item["extraction"].get("locator") == link.locator
                )
            ),
            {},
        )
        item = record.get("item") if isinstance(record, Mapping) else {}
        # H7: ResearchEvidence is the source-level identity, so its
        # locator/spans are whatever the last extraction wrote; claim-specific
        # anchors live in record["extractions"][claim_id] and must win when
        # one physical read serves multiple claims.
        claim_anchor: Mapping[str, Any] | None = None
        if isinstance(record, Mapping):
            extractions_map = record.get("extractions")
            if isinstance(extractions_map, Mapping):
                detail = extractions_map.get(link.claim_id)
                if isinstance(detail, Mapping):
                    claim_anchor = detail
        anchors_source = claim_anchor if claim_anchor is not None else {}
        row: dict[str, Any] = {
            "evidence_id": link.evidence_id,
            "claim_id": link.claim_id,
            "relation": link.relation,
            "strength": link.strength,
            "source_role": link.source_role,
            "source_cluster_id": link.source_cluster_id,
            "title": str(item.get("title") or "") if isinstance(item, Mapping) else "",
            "url": str(item.get("url") or "") if isinstance(item, Mapping) else "",
            "locator": str(
                anchors_source.get("locator") or link.locator or ""
            ),
            "anchored_spans": list(
                anchors_source.get("anchored_spans") or evidence.anchored_spans
            ),
            "published_at": evidence.published_at,
            "caveats": list(
                anchors_source.get("caveats") or link.caveats
            ),
        }
        # §40d grounded input (default off): attach a bounded excerpt from the
        # page that was actually read, preferring the anchor's surroundings.
        if grounded_input and excerpt_budget > 0:
            read_payload = record.get("read") if isinstance(record, Mapping) else {}
            content = (
                str(read_payload.get("content") or "")
                if isinstance(read_payload, Mapping)
                else ""
            )
            anchor = str(
                row["locator"]
                or (row["anchored_spans"][0] if row["anchored_spans"] else "")
            )
            excerpt = grounded_excerpt(
                content,
                anchor=anchor,
                max_chars=min(EXCERPT_MAX_CHARS, excerpt_budget),
            )
            if excerpt:
                row["excerpt"] = excerpt
                excerpt_budget -= len(excerpt)
        evidence_rows.append(row)
    return {
        "schema_version": "research-evidence-brief-v1",
        "gate_status": gate.status if gate else "unavailable",
        "gate_reasons": list(gate.reasons) if gate else ["active_runtime_unavailable"],
        # H5: the conclusion constraint is a first-class brief field so
        # downstream consumers never present an unqualified strong conclusion
        # unless the Evidence Gate actually passed.
        "conditional_wording_required": (gate is None or gate.status != "pass"),
        "eligible_evidence": evidence_rows,
        "claim_links": [item.to_dict() for item in state.evidence_links if item.evidence_id in {row["evidence_id"] for row in evidence_rows}],
        "unresolved_conflicts": [item.to_dict() for item in (gate.conflicts if gate else state.conflict_gaps)],
        "open_critical_claim_ids": list(gate.open_critical_claims) if gate else [claim.id for claim in state.claims if claim.priority == "critical"],
        "open_gap_ids": list(gate.gap_ids) if gate else [gap.id for gap in state.gaps if gap.state in {"open", "searching"}],
        "budget": state.budget.to_dict(),
        "answer_instruction": (
            "Use only eligible evidence. State unresolved gaps and conflicts. "
            "When gate_status is not pass, use conditional language and do not present a complete conclusion."
            + (" " + ANSWER_SHAPE_CONTRACT if grounded_input else "")
        ),
    }


def _format_evidence_brief(brief: Mapping[str, Any]) -> str:
    lines = [
        "研究证据简报（仅可使用下列已读取并通过提取校验的证据）",
        f"Evidence Gate: {brief.get('gate_status', 'unavailable')}",
    ]
    for row in brief.get("eligible_evidence", []):
        if not isinstance(row, Mapping):
            continue
        lines.append(
            f"- [{row.get('relation')}] claim={row.get('claim_id')} "
            f"source={row.get('title') or row.get('url')} "
            f"cluster={row.get('source_cluster_id')} strength={row.get('strength')}"
        )
        lines.append(f"  anchor: {row.get('locator')}")
        excerpt = str(row.get("excerpt") or "")
        if excerpt:
            lines.append(f"  excerpt: {excerpt}")
        if row.get("url"):
            lines.append(f"  url: {row.get('url')}")
    open_claims = brief.get("open_critical_claim_ids") or []
    conflicts = brief.get("unresolved_conflicts") or []
    if open_claims:
        lines.append("未闭合关键结论：" + ", ".join(str(item) for item in open_claims))
    if conflicts:
        lines.append("仍有未解决冲突；回答必须并列呈现冲突证据。")
    if brief.get("conditional_wording_required") is True:
        lines.append(
            "结论约束：研究尚未通过完整证据核验；只能使用条件化措辞，不得输出无保留强结论。"
        )
    lines.append(str(brief.get("answer_instruction") or ""))
    return "\n".join(lines)[:20000]


