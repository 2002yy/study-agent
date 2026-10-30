"""Versioned, server-owned evidence projections for chat turns.

This module does not own retrieval or research execution. It projects the
existing authoritative RAG, WebTool/ResearchRun and disclosure decisions into
one stable snapshot that can be persisted with a ChatTurn and restored without
frontend inference.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from hashlib import sha256
from pathlib import PurePath
from typing import Any, Iterable, Literal
from urllib.parse import urlparse

EVIDENCE_SNAPSHOT_SCHEMA_VERSION = "evidence-snapshot-v1"
EvidenceLifecycleStatus = Literal["candidate", "read", "selected", "rejected"]
#: How a source relates to the answer that was actually published.
#: ``cited`` requires a passed publication gate; see ``runtime_entities``.
CitationStatus = Literal["cited", "unverified", "none"]
#: Same bar as the binder's strong-support threshold. A link below it never
#: becomes a visible citation, even if it exists in the snapshot.
MIN_VERIFIED_CITATION_CONFIDENCE = 0.7
_POSITIVE_SUPPORT_TYPES = frozenset({"direct_support", "indirect_support"})

_STATUS_PRIORITY: dict[EvidenceLifecycleStatus, int] = {
    "selected": 0,
    "read": 1,
    "rejected": 2,
    "candidate": 3,
}


@dataclass(frozen=True)
class EvidenceRefV1:
    id: str
    type: str
    title: str = ""
    source: str = ""
    url: str = ""
    domain: str = ""
    published_at: str = ""
    score: float = 0.0
    lifecycle_status: EvidenceLifecycleStatus = "candidate"
    provider_status: str = ""
    selection_reason: str = ""
    rejection_reason: str = ""
    #: ``cited`` only when the published answer passed publication and links
    #: this source; ``unverified`` when it was read/selected but is not a
    #: citation; ``none`` for candidates and legacy rows.
    citation_status: CitationStatus = "none"

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "type": self.type,
            "title": self.title,
            "source": self.source,
            "url": self.url,
            "domain": self.domain,
            "published_at": self.published_at,
            "score": self.score,
            "lifecycle_status": self.lifecycle_status,
            "provider_status": self.provider_status,
            "selection_reason": self.selection_reason,
            "rejection_reason": self.rejection_reason,
            "citation_status": self.citation_status,
        }


@dataclass(frozen=True)
class ClaimEvidenceLinkV1:
    claim_id: str
    evidence_id: str
    support_type: str
    confidence: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "claim_id": self.claim_id,
            "evidence_id": self.evidence_id,
            "support_type": self.support_type,
            "confidence": self.confidence,
        }


@dataclass(frozen=True)
class EvidenceSnapshotV1:
    refs: tuple[EvidenceRefV1, ...] = ()
    pedagogy_evidence_ids: tuple[str, ...] = ()
    claim_links: tuple[ClaimEvidenceLinkV1, ...] = ()
    disclosure_policy: str = "none"
    schema_version: str = EVIDENCE_SNAPSHOT_SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "disclosure_policy": self.disclosure_policy,
            "refs": [ref.to_dict() for ref in self.refs],
            "pedagogy_evidence_ids": list(self.pedagogy_evidence_ids),
            "claim_links": [link.to_dict() for link in self.claim_links],
        }


class _EvidenceAccumulator:
    def __init__(self) -> None:
        self._refs: dict[str, EvidenceRefV1] = {}
        self._order: list[str] = []

    def add(self, ref: EvidenceRefV1) -> None:
        if not ref.id or not (ref.title or ref.source or ref.url):
            return
        current = self._refs.get(ref.id)
        if current is None:
            self._refs[ref.id] = ref
            self._order.append(ref.id)
            return
        if _should_replace(current, ref):
            self._refs[ref.id] = _merge_ref(current, ref)

    def values(self) -> tuple[EvidenceRefV1, ...]:
        return tuple(self._refs[ref_id] for ref_id in self._order)


def build_evidence_snapshot(
    *,
    rag: dict[str, Any],
    disclosed_units: Iterable[dict[str, Any]] = (),
    disclosure_policy: str = "none",
    pedagogy_evidence_ids: Iterable[str] = (),
    claim_links: Iterable[ClaimEvidenceLinkV1] = (),
    cited_evidence_ids: Iterable[str] = (),
) -> EvidenceSnapshotV1:
    """Project current authoritative evidence into a durable v1 snapshot.

    Lifecycle status is deliberately conservative:
    - local chunks become selected only when disclosure selected that chunk ID;
    - WebTool search results are candidates; reads become selected only when used;
    - ResearchRun selections require durable read/structured-evidence truth;
    - legacy ResearchRun selections without read truth remain unknown candidates;
    - ordinal legacy web IDs such as ``web-1`` never become selected URLs;
    - pedagogy evidence references remain distinct from answer claim links;
    - claim links are accepted only from an upstream owner with a real claim ID.
    """

    disclosed = tuple(unit for unit in disclosed_units if isinstance(unit, dict))
    selected_ids = {
        _text(unit.get("source_id"))
        for unit in disclosed
        if _text(unit.get("source_id"))
    }
    refs = _EvidenceAccumulator()
    _add_local_refs(refs, rag=rag, selected_ids=selected_ids, policy=disclosure_policy)
    _add_web_tool_refs(refs, rag=rag)
    _add_research_run_refs(refs, rag=rag)
    _add_claim_binding_refs(refs, rag=rag)

    projected = refs.values()
    known_ids = {ref.id for ref in projected}
    pedagogy_refs = tuple(
        evidence_id
        for evidence_id in _dedupe_text(pedagogy_evidence_ids)
        if evidence_id in known_ids
    )
    validated_links = tuple(
        link
        for link in claim_links
        if _text(link.claim_id) and link.evidence_id in known_ids
    )
    cited_ids = {evidence_id for evidence_id in cited_evidence_ids if evidence_id in known_ids}
    annotated = tuple(
        replace(
            ref,
            citation_status=(
                "cited"
                if ref.id in cited_ids
                else "unverified"
                if ref.lifecycle_status in {"read", "selected"}
                else "none"
            ),
        )
        for ref in projected
    )
    return EvidenceSnapshotV1(
        refs=annotated,
        pedagogy_evidence_ids=pedagogy_refs,
        claim_links=validated_links,
        disclosure_policy=disclosure_policy or "none",
    )


def _add_local_refs(
    accumulator: _EvidenceAccumulator,
    *,
    rag: dict[str, Any],
    selected_ids: set[str],
    policy: str,
) -> None:
    provider_status = _text(rag.get("status"))
    for index, raw_result in enumerate(rag.get("results") or (), start=1):
        if not isinstance(raw_result, dict):
            continue
        chunk = _object(raw_result.get("chunk"))
        if not chunk:
            continue
        source = _text(chunk.get("source_path"))
        title = _text(chunk.get("title")) or _basename(source)
        start_line = _text(chunk.get("start_line"))
        end_line = _text(chunk.get("end_line"))
        evidence_id = _text(chunk.get("chunk_id")) or _stable_id(
            "local",
            source,
            start_line,
            end_line,
            title,
            str(index),
        )
        score = _finite_float(raw_result.get("score"))
        if score <= 0 or not (source or title):
            continue
        selected = evidence_id in selected_ids
        accumulator.add(
            EvidenceRefV1(
                id=evidence_id,
                type="local",
                title=title,
                source=source,
                score=score,
                lifecycle_status="selected" if selected else "candidate",
                provider_status=provider_status,
                selection_reason=(
                    f"disclosure_policy:{policy or 'none'}" if selected else ""
                ),
            )
        )


def _add_web_tool_refs(
    accumulator: _EvidenceAccumulator,
    *,
    rag: dict[str, Any],
) -> None:
    web_tools = _object(rag.get("web_tools"))
    if not web_tools:
        return
    tool_error = _text(web_tools.get("error"))
    evidence_status = _text(web_tools.get("evidence_status"))
    candidate_provider_status = (
        "candidate_only"
        if evidence_status == "candidate_only"
        else "provider_failed"
        if tool_error
        else "found"
    )
    used_urls = {
        _text(item.get("url")).rstrip("/").casefold()
        for item in web_tools.get("used_sources") or ()
        if isinstance(item, dict) and _text(item.get("url"))
    }
    for call in web_tools.get("calls") or ():
        if not isinstance(call, dict):
            continue
        name = _text(call.get("name"))
        arguments = _object(call.get("arguments"))
        result = _object(call.get("result"))
        if name == "web_search":
            query = _text(arguments.get("query"))
            for item in result.get("results") or ():
                if not isinstance(item, dict):
                    continue
                url = _source_url(item)
                title = _text(item.get("title")) or url
                if not (title or url):
                    continue
                accumulator.add(
                    EvidenceRefV1(
                        id=_web_id(url=url, title=title),
                        type="web_search",
                        title=title,
                        source=query,
                        url=url,
                        domain=_domain(url),
                        published_at=_published_at(item),
                        lifecycle_status="candidate",
                        provider_status=candidate_provider_status,
                    )
                )
        elif name == "web_read":
            url = _text(arguments.get("url") or result.get("url"))
            if not url:
                continue
            ok = result.get("ok") is True or _text(result.get("ok")).lower() == "true"
            selected = ok and url.rstrip("/").casefold() in used_urls
            accumulator.add(
                EvidenceRefV1(
                    id=_web_id(url=url, title=url),
                    type="web_read",
                    title=_text(result.get("title")) or url,
                    source=url,
                    url=url,
                    domain=_domain(url),
                    lifecycle_status=(
                        "selected" if selected else "read" if ok else "candidate"
                    ),
                    provider_status="read" if ok else "read_failed",
                    selection_reason=(
                        "web_read_sent_to_answer" if selected else ""
                    ),
                )
            )


def _add_claim_binding_refs(
    accumulator: _EvidenceAccumulator,
    *,
    rag: dict[str, Any],
) -> None:
    """Add server-owned evidence ids validated by the answer-claim binder.

    The binder accepted claim links only against rows projected from the
    ResearchRun Evidence Brief (``rag["research_evidence_refs"]``); persisting
    those bounded rows lets later reads re-validate the claim links instead of
    demoting a validated snapshot to rejected because the id space of the
    research-run extraction differs from web source ids.
    """
    for raw in rag.get("research_evidence_refs") or ():
        if not isinstance(raw, dict):
            continue
        evidence_id = _text(raw.get("evidence_id"))
        title = _text(raw.get("title"))
        url = _text(raw.get("url"))
        source_cluster_id = _text(raw.get("source_cluster_id"))
        if not evidence_id or not (title or url or source_cluster_id):
            continue
        accumulator.add(
            EvidenceRefV1(
                id=evidence_id,
                type="research",
                title=title,
                source=source_cluster_id,
                url=url,
                domain=_domain(url),
                published_at=_published_at(raw),
                lifecycle_status="selected",
                provider_status="structured_evidence",
                selection_reason="answer_claim_binding:validated",
            )
        )


def _add_research_run_refs(
    accumulator: _EvidenceAccumulator,
    *,
    rag: dict[str, Any],
) -> None:
    research = _object(rag.get("research_sources"))
    if not research:
        return
    provider_status = _text(research.get("provider_status"))
    run_id = _text(research.get("run_id"))
    truth_version = _nonnegative_int(research.get("source_truth_version"))
    statuses: tuple[tuple[EvidenceLifecycleStatus, str], ...] = (
        ("selected", "selected_sources"),
        ("rejected", "rejected_sources"),
    )
    for status, key in statuses:
        for record in research.get(key) or ():
            if not isinstance(record, dict):
                continue
            item = _object(record.get("item"))
            assessment = _object(record.get("assessment"))
            url = _text(
                assessment.get("url")
                or item.get("url")
                or item.get("link")
                or item.get("href")
            )
            title = _text(assessment.get("title") or item.get("title")) or url
            source_id = _text(assessment.get("source_id"))
            evidence_state = _text(record.get("evidence_state"))
            read_status = _text(record.get("read_status"))
            assessment_reason = _text(assessment.get("selection_reason"))
            verified = read_status in {"read", "structured"} or assessment_reason in {
                "read_backed_tool_evidence",
                "structured_tool_evidence",
            }
            lifecycle_status: EvidenceLifecycleStatus = status
            ref_provider_status = provider_status
            if status == "selected" and not verified:
                lifecycle_status = "candidate"
                if truth_version < 2 and not read_status:
                    ref_provider_status = "legacy_unknown"
                elif read_status == "failed":
                    ref_provider_status = "read_failed"
                elif read_status == "skipped":
                    ref_provider_status = "read_skipped"
                else:
                    ref_provider_status = "candidate_only"
            evidence_id = _web_id(url=url, title=title) if (url or title) else source_id
            if not evidence_id:
                continue
            accumulator.add(
                EvidenceRefV1(
                    id=evidence_id,
                    type="research",
                    title=title,
                    source=source_id or run_id,
                    url=url,
                    domain=_text(assessment.get("domain")) or _domain(url),
                    published_at=_published_at(item),
                    score=_finite_float(assessment.get("relevance")),
                    lifecycle_status=lifecycle_status,
                    provider_status=ref_provider_status,
                    selection_reason=(
                        f"research_{evidence_state}:{run_id}"
                        if lifecycle_status == "selected" and evidence_state and run_id
                        else f"research_run:{run_id}"
                        if lifecycle_status == "selected" and run_id
                        else "research_selected"
                        if lifecycle_status == "selected"
                        else ""
                    ),
                    rejection_reason=(
                        (
                            _text(assessment.get("rejection_reason"))
                            or evidence_state
                            or "research_rejected"
                        )
                        if status == "rejected"
                        else ""
                    ),
                )
            )


def _should_replace(current: EvidenceRefV1, incoming: EvidenceRefV1) -> bool:
    current_priority = _STATUS_PRIORITY[current.lifecycle_status]
    incoming_priority = _STATUS_PRIORITY[incoming.lifecycle_status]
    if incoming_priority < current_priority:
        return True
    if incoming_priority > current_priority:
        return False
    if incoming.type == "web_read" and current.type == "web_search":
        return True
    return incoming.score > current.score


def _merge_ref(current: EvidenceRefV1, incoming: EvidenceRefV1) -> EvidenceRefV1:
    return EvidenceRefV1(
        id=current.id,
        type=incoming.type or current.type,
        title=incoming.title or current.title,
        source=incoming.source or current.source,
        url=incoming.url or current.url,
        domain=incoming.domain or current.domain,
        published_at=incoming.published_at or current.published_at,
        score=max(current.score, incoming.score),
        lifecycle_status=incoming.lifecycle_status,
        provider_status=incoming.provider_status or current.provider_status,
        selection_reason=incoming.selection_reason or current.selection_reason,
        rejection_reason=incoming.rejection_reason or current.rejection_reason,
    )


def _web_id(*, url: str, title: str) -> str:
    if url:
        return _stable_id("web", _canonical_url(url))
    return _stable_id("web-title", title.casefold())


def _stable_id(prefix: str, *parts: str) -> str:
    material = "\u0000".join(_text(part) for part in parts)
    return f"{prefix}_{sha256(material.encode('utf-8')).hexdigest()[:24]}"


def _canonical_url(url: str) -> str:
    parsed = urlparse(url.strip())
    if not parsed.scheme or not parsed.netloc:
        return url.strip()
    path = parsed.path.rstrip("/") or "/"
    return f"{parsed.scheme.lower()}://{parsed.netloc.lower()}{path}"


def _domain(url: str) -> str:
    host = (urlparse(url).hostname or "").lower()
    return host[4:] if host.startswith("www.") else host


def _source_url(item: dict[str, Any]) -> str:
    return _text(item.get("url") or item.get("link") or item.get("href"))


def _published_at(item: dict[str, Any]) -> str:
    return _text(
        item.get("published_at")
        or item.get("published")
        or item.get("date")
        or item.get("pubDate")
    )


def _basename(source: str) -> str:
    return PurePath(source).name if source else ""


def _finite_float(value: Any) -> float:
    try:
        parsed = float(value or 0)
    except (TypeError, ValueError):
        return 0.0
    if parsed != parsed or parsed in {float("inf"), float("-inf")}:
        return 0.0
    return parsed


def _nonnegative_int(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _object(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _text(value: Any) -> str:
    return " ".join(str(value or "").split())


def _dedupe_text(values: Iterable[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(_text(value) for value in values if _text(value)))
