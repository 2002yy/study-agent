"""Production answer-claim binder (RQ1-C answer/citation binding batch).

The binder runs AFTER the final answer is generated and BEFORE the ChatTurn
completes. It turns the already-produced answer into structured factual claims
bound to existing server-owned evidence ids. It is deliberately NOT an answer
generator:

- it never rewrites the final answer text;
- it never invents evidence or research-claim ids;
- it never reads rubric or qualification expected answers;
- it validates support against server-owned research-claim/evidence lineage,
  relation and strength rather than trusting the producer to promote any known
  id into positive support.

Fail-closed contract: malformed structured output, provider failures and
unverifiable bindings yield a ``rejected`` snapshot with a canonical reason.
Evidence context is bounded: each row renders only metadata and short anchored
excerpts, never a page body.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Mapping, Sequence

from src.domain.answer_claims import (
    AnswerClaimSnapshotV1,
    answer_content_hash,
    build_answer_claim_snapshot,
    deterministic_claim_id,
    rejected_answer_claim_snapshot,
)
from src.web.research.evidence_gate import STRONG_EVIDENCE_THRESHOLD

BINDER_SCHEMA_VERSION = "answer-claim-binder-v3"
ANSWER_CLAIM_BINDER_PRODUCER = "answer_claim_binder_v3"

_MAX_EVIDENCE_ROWS = 24
_MAX_CONTEXT_CHARS = 16000
_MAX_ROW_CHARS = 1600
_MAX_ANCHOR_CHARS = 300
_MAX_CAVEAT_CHARS = 200
_MAX_ANCHORED_SPANS_PER_ROW = 6
_MAX_CAVEATS_PER_ROW = 6
_MAX_SEGMENTS = 16
_MAX_SEGMENT_CHARS = 1200

_ALLOWED_SEGMENT_KINDS = frozenset(
    {"factual", "instructional", "question", "recommendation", "uncertainty"}
)
# Chinese sentence punctuation is unambiguous. ASCII punctuation only becomes
# a boundary when followed by whitespace/end-of-answer, so URLs, versions and
# decimals such as ``https://docs.python.org/3.12/`` and ``v3.12`` stay intact.
# Commas split only when the following clause clearly switches into
# advice/instruction wording; splitting every comma over-segments ordinary
# factual prose and can exhaust the bounded segment budget without improving
# claim coverage.
_SEGMENT_BOUNDARY = re.compile(
    r"(?<=[。！？；])|(?<=[.!?;:：])(?=\s|$)|[\r\n]+|"
    r"(?<=[，,])(?=\s*(?:建议|应该|应当|请|不要|需要|需|推荐|最好|可考虑|"
    r"recommend\b|should\b|please\b|consider\b))",
    re.IGNORECASE,
)

BinderModelFn = Callable[[Sequence[Mapping[str, Any]]], str]
BinderBeforeCallFn = Callable[[], None]


@dataclass(frozen=True)
class AnswerClaimBindingRow:
    """One server-owned research claim/evidence relation offered to the binder."""

    evidence_id: str
    claim_id: str = ""
    title: str = ""
    url: str = ""
    source_role: str = ""
    source_cluster_id: str = ""
    relation: str = ""
    strength: str = ""
    locator: str = ""
    anchored_spans: tuple[str, ...] = ()
    caveats: tuple[str, ...] = ()


@dataclass(frozen=True)
class AnswerClaimBindingRequest:
    question: str
    final_answer: str
    evidence_rows: tuple[AnswerClaimBindingRow, ...] = ()


@dataclass(frozen=True)
class BoundAnswerClaims:
    snapshot: AnswerClaimSnapshotV1
    raw_output: str = ""
    attempt_count: int = 0
    segment_stats: dict[str, Any] = field(default_factory=dict)


def bind_answer_claims(
    *,
    request: AnswerClaimBindingRequest,
    model_fn: BinderModelFn,
    producer: str = ANSWER_CLAIM_BINDER_PRODUCER,
    max_attempts: int = 1,
    before_model_call: BinderBeforeCallFn | None = None,
) -> BoundAnswerClaims:
    """Bind the immutable candidate answer to server-owned research evidence."""
    answer = str(request.final_answer or "")
    if not answer.strip():
        raise ValueError("answer claim binding requires a final answer")
    segments, segment_stats = segment_answer_with_stats(answer)
    if not segments:
        return BoundAnswerClaims(
            snapshot=rejected_answer_claim_snapshot(
                answer=answer,
                producer=producer,
                reason="answer_not_segmentable",
            ),
            attempt_count=0,
            segment_stats=segment_stats,
        )
    rows = tuple(_bounded_rows(request.evidence_rows))
    rows_by_link = {
        (row.claim_id, row.evidence_id): row
        for row in rows
        if row.claim_id and row.evidence_id
    }
    known_evidence_ids = {row.evidence_id for row in rows if row.evidence_id}
    known_research_claim_ids = {row.claim_id for row in rows if row.claim_id}
    messages = _binding_messages(
        question=request.question, answer=answer, segments=segments, rows=rows
    )

    attempts = max(0, min(int(max_attempts), 2))
    last_error = ""
    for attempt in range(1, attempts + 1):
        # This hook intentionally runs outside the provider-failure catch: an
        # accepted cancellation is control flow, not a failed binder attempt,
        # and must never be swallowed or retried as producer failure.
        if before_model_call is not None:
            before_model_call()
        try:
            raw = model_fn(messages)
        except Exception as exc:  # noqa: BLE001 - provider failures are results
            last_error = f"producer_failed:{type(exc).__name__}"
            continue
        parsed, parse_error = _parse_binder_output(
            raw_output=raw,
            answer=answer,
            segments=segments,
            rows_by_link=rows_by_link,
            known_evidence_ids=known_evidence_ids,
            known_research_claim_ids=known_research_claim_ids,
            producer=producer,
        )
        if parsed is not None:
            return BoundAnswerClaims(
                snapshot=parsed,
                raw_output=raw,
                attempt_count=attempt,
                segment_stats=segment_stats,
            )
        last_error = parse_error or "malformed_structured_output"
    return BoundAnswerClaims(
        snapshot=rejected_answer_claim_snapshot(
            answer=answer,
            producer=producer,
            reason=last_error or "producer_unavailable",
        ),
        attempt_count=attempts,
        segment_stats=segment_stats,
    )


def _parse_binder_output(
    *,
    raw_output: str,
    answer: str,
    segments: tuple[str, ...],
    rows_by_link: Mapping[tuple[str, str], AnswerClaimBindingRow],
    known_evidence_ids: set[str],
    known_research_claim_ids: set[str],
    producer: str,
) -> tuple[AnswerClaimSnapshotV1 | None, str]:
    if not raw_output or not raw_output.strip():
        return None, "empty_producer_output"
    try:
        payload = json.loads(_strip_json_fence(raw_output))
    except (TypeError, ValueError):
        return None, "malformed_structured_output"
    if not isinstance(payload, Mapping):
        return None, "malformed_structured_output"
    refused = payload.get("refused")
    if not isinstance(refused, bool):
        return None, "malformed_structured_output"
    if refused:
        return (
            rejected_answer_claim_snapshot(
                answer=answer,
                producer=producer,
                reason="producer_refused",
            ),
            "",
        )
    raw_segments = payload.get("segments")
    if not isinstance(raw_segments, list):
        return None, "malformed_structured_output"
    segment_entries = tuple(_object(entry) for entry in raw_segments)
    if len(segment_entries) != len(segments):
        return None, "segment_coverage_mismatch"
    ref_to_text = {
        _segment_ref(index): text for index, text in enumerate(segments)
    }
    claims: list[dict[str, Any]] = []
    links: list[dict[str, Any]] = []
    seen_refs: set[str] = set()
    for entry in segment_entries:
        ref = _clean_identifier(entry.get("segment_ref"))
        if not ref or ref not in ref_to_text or ref in seen_refs:
            return None, "segment_coverage_mismatch"
        seen_refs.add(ref)
        kind = str(entry.get("kind") or "").strip()
        status = str(entry.get("status") or "").strip()
        research_claim_id = _clean_identifier(entry.get("research_claim_id"))
        raw_support = entry.get("evidence_support")
        if kind not in _ALLOWED_SEGMENT_KINDS:
            return None, "malformed_structured_output"
        if not isinstance(raw_support, list) or not all(
            isinstance(item, str) for item in raw_support
        ):
            return None, "malformed_structured_output"
        support_ids = tuple(_clean_identifier(item) for item in raw_support)
        if any(not item for item in support_ids):
            return None, "malformed_structured_output"
        if len(set(support_ids)) != len(support_ids):
            return None, "duplicate_evidence_support"

        if kind != "factual":
            if status or research_claim_id or support_ids:
                return None, "non_factual_segment_support"
            continue
        if status not in {"asserted", "qualified"}:
            return None, "malformed_structured_output"
        if not support_ids:
            return None, "unbound_factual_segment"
        unknown = [item for item in support_ids if item not in known_evidence_ids]
        if unknown:
            return None, "unknown_evidence_id"
        if research_claim_id:
            if research_claim_id not in known_research_claim_ids:
                return None, "unknown_research_claim_id"
        else:
            inferred = _infer_research_claim_id(
                support_ids=support_ids,
                rows_by_link=rows_by_link,
                known_research_claim_ids=known_research_claim_ids,
            )
            if inferred is None:
                return None, "missing_research_claim_id"
            research_claim_id = inferred

        support_rows: list[tuple[str, float]] = []
        for evidence_id in support_ids:
            row = rows_by_link.get((research_claim_id, evidence_id))
            if row is None:
                return None, "claim_evidence_mismatch"
            confidence = _positive_support_confidence(row)
            if confidence is None:
                return None, "ineligible_evidence_support"
            support_rows.append((evidence_id, confidence))

        claim_id = deterministic_claim_id(
            answer_hash=answer_content_hash(answer), claim_text=ref_to_text[ref]
        )
        claims.append(
            {
                "text": ref_to_text[ref],
                "kind": "factual",
                "status": status,
                "source": "provider_structured",
            }
        )
        for evidence_id, confidence in support_rows:
            links.append(
                {
                    "claim_id": claim_id,
                    "evidence_id": evidence_id,
                    "support_type": "direct_support",
                    "confidence": confidence,
                }
            )
    try:
        return (
            build_answer_claim_snapshot(
                answer=answer,
                claims=claims,
                claim_links=links,
                known_evidence_ids=known_evidence_ids,
                producer=producer,
                status="validated",
                trust_upstream_claim_ids=False,
            ),
            "",
        )
    except (TypeError, ValueError):
        return None, "malformed_structured_output"


def _infer_research_claim_id(
    *,
    support_ids: tuple[str, ...],
    rows_by_link: Mapping[tuple[str, str], AnswerClaimBindingRow],
    known_research_claim_ids: set[str],
) -> str | None:
    """Infer a claim id only when all support ids imply one unique claim.

    This is server-side lineage resolution, not model authority: no new id is
    invented. If the same evidence set can belong to multiple research claims,
    omission stays ambiguous and the binding fails closed.
    """
    candidates = {
        claim_id
        for claim_id in known_research_claim_ids
        if all((claim_id, evidence_id) in rows_by_link for evidence_id in support_ids)
    }
    if len(candidates) != 1:
        return None
    return next(iter(candidates))


def _positive_support_confidence(row: AnswerClaimBindingRow) -> float | None:
    if _clean_text(row.relation) != "supports":
        return None
    strength = _parse_strength(row.strength)
    if strength is None or strength < STRONG_EVIDENCE_THRESHOLD:
        return None
    return strength


def _parse_strength(value: Any) -> float | None:
    if isinstance(value, str) and value.strip().lower() == "strong":
        return 1.0
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if parsed < 0 or parsed > 1:
        return None
    return parsed


def _segment_ref(index: int) -> str:
    return f"s{index + 1}"


def segment_answer_with_stats(answer: str) -> tuple[tuple[str, ...], dict[str, Any]]:
    """Segment with §40d diagnostics: raw count, limit and overflow flag.

    ``_segment_answer`` collapses both "no content" and "over the segment
    budget" into ``()``; the stats keep those cases distinguishable in the
    audit, so an overflow never looks like an empty answer.
    """

    raw_parts = _SEGMENT_BOUNDARY.split(answer or "")
    nonempty = [part.strip(" \t\n\r") for part in raw_parts]
    nonempty = [part for part in nonempty if part]
    overflow_chars = any(len(part) > _MAX_SEGMENT_CHARS for part in nonempty)
    overflow_count = len(nonempty) > _MAX_SEGMENTS
    segments = _segment_answer(answer)
    stats = {
        "raw_nonempty_segment_count": len(nonempty),
        "segment_limit": _MAX_SEGMENTS,
        "max_segment_chars": _MAX_SEGMENT_CHARS,
        "segment_overflow": bool(overflow_count or overflow_chars),
        "overflow_reason": (
            "segment_count"
            if overflow_count
            else ("segment_chars" if overflow_chars else "")
        ),
        "accepted": bool(segments),
    }
    return segments, stats


def _segment_answer(answer: str) -> tuple[str, ...]:
    raw_parts = _SEGMENT_BOUNDARY.split(answer)
    segments: list[str] = []
    for part in raw_parts:
        candidate = part.strip(" \t\n\r")
        if not candidate:
            continue
        if len(candidate) > _MAX_SEGMENT_CHARS:
            return ()
        if len(segments) >= _MAX_SEGMENTS:
            return ()
        segments.append(candidate)
    return tuple(segments)


def factual_claims_fully_bound(snapshot: AnswerClaimSnapshotV1) -> bool:
    """True when every factual claim has server-eligible strong support."""
    bound_claim_ids = {
        link.claim_id
        for link in snapshot.claim_links
        if link.claim_id
        and link.support_type in _POSITIVE_SUPPORT_TYPES
        and link.confidence >= STRONG_EVIDENCE_THRESHOLD
    }
    return all(
        claim.kind != "factual" or claim.id in bound_claim_ids
        for claim in snapshot.claims
    )


_POSITIVE_SUPPORT_TYPES = frozenset({"direct_support", "indirect_support"})


def _binding_messages(
    *,
    question: str,
    answer: str,
    segments: tuple[str, ...],
    rows: tuple[AnswerClaimBindingRow, ...],
) -> list[dict[str, str]]:
    context = _render_context(rows)
    numbered = "\n".join(
        f"[{_segment_ref(index)}] {segment}" for index, segment in enumerate(segments)
    )
    system = (
        "You classify every segment of an already-written final answer against "
        "server-owned research claim/evidence relations.\n"
        "Rules:\n"
        "1. Never modify or add to the answer; classify every server segment.\n"
        "2. Return EXACTLY one entry per segment_ref; missing, duplicate or "
        "unknown refs are rejected.\n"
        "3. kind is factual/instructional/question/recommendation/uncertainty.\n"
        "4. Every factual segment needs status asserted|qualified and at least "
        "one evidence_id from one research claim. research_claim_id SHOULD be "
        "copied from the evidence rows; if omitted, the server accepts it only "
        "when all chosen evidence ids uniquely imply the same claim. Use only "
        "evidence rows that positively and strongly support the segment.\n"
        "5. Non-factual segments must omit status/research_claim_id and have an "
        "empty evidence_support list.\n"
        "6. If the whole answer cannot be safely bound, set refused=true.\n"
        'Respond with JSON only: {"refused": bool, "segments": '
        '[{"segment_ref":"s1","kind":"factual",'
        '"research_claim_id":"claim_id","status":"asserted|qualified",'
        '"evidence_support":["evidence_id"]}]}.'
    )
    user = (
        "Question:\n{question}\n\n"
        "Final answer segments (read-only):\n{numbered}\n\n"
        "Available server-owned research claim/evidence rows:\n{context}"
    ).format(
        question=_clean_text(question)[:_MAX_CONTEXT_CHARS],
        numbered=numbered[:_MAX_CONTEXT_CHARS],
        context=context or "(none)",
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


def _render_context(rows: tuple[AnswerClaimBindingRow, ...]) -> str:
    rendered: list[str] = []
    budget = _MAX_CONTEXT_CHARS
    for row in rows:
        line = _render_row(row)
        if budget - len(line) < 0:
            break
        budget -= len(line)
        rendered.append(line)
    return "\n".join(rendered)


def _render_row(row: AnswerClaimBindingRow) -> str:
    spans = " | ".join(
        _clip(span, _MAX_ANCHOR_CHARS)
        for span in row.anchored_spans[:_MAX_ANCHORED_SPANS_PER_ROW]
    )
    caveats = " | ".join(
        _clip(caveat, _MAX_CAVEAT_CHARS)
        for caveat in row.caveats[:_MAX_CAVEATS_PER_ROW]
    )
    parts = [
        f"[{row.evidence_id}]",
        f"claim={_clip(row.claim_id, 160)}",
        _clip(row.title, 200),
        _clip(row.url, 500),
        _clip(row.source_role, 100),
        _clip(row.source_cluster_id, 100),
        _clip(row.relation, 100),
        _clip(row.strength, 100),
        _clip(row.locator, 300),
    ]
    if spans:
        parts.append(f"anchors: {spans}")
    if caveats:
        parts.append(f"caveats: {caveats}")
    return " | ".join(part for part in parts if part)[:_MAX_ROW_CHARS]


def _bounded_rows(
    rows: Iterable[AnswerClaimBindingRow],
) -> Iterable[AnswerClaimBindingRow]:
    seen: set[tuple[str, str]] = set()
    count = 0
    for row in rows:
        evidence_id = _clean_identifier(row.evidence_id)
        claim_id = _clean_identifier(row.claim_id)
        if not evidence_id or not claim_id:
            continue
        key = (claim_id, evidence_id)
        if key in seen:
            continue
        seen.add(key)
        count += 1
        if count > _MAX_EVIDENCE_ROWS:
            return
        yield AnswerClaimBindingRow(
            evidence_id=evidence_id,
            claim_id=claim_id,
            title=_clean_text(row.title),
            url=_clean_text(row.url),
            source_role=_clean_text(row.source_role),
            source_cluster_id=_clean_text(row.source_cluster_id),
            relation=_clean_text(row.relation),
            strength=_clean_text(row.strength),
            locator=_clean_text(row.locator),
            anchored_spans=tuple(
                _clip(span, _MAX_ANCHOR_CHARS) for span in row.anchored_spans
            )[:_MAX_ANCHORED_SPANS_PER_ROW],
            caveats=tuple(
                _clip(caveat, _MAX_CAVEAT_CHARS) for caveat in row.caveats
            )[:_MAX_CAVEATS_PER_ROW],
        )


def _clip(value: str, limit: int) -> str:
    return _clean_text(value)[:limit]


def _clean_identifier(value: Any) -> str:
    identifier = str(value or "").strip()
    if not identifier:
        return ""
    if len(identifier) > 160 or any(character.isspace() for character in identifier):
        return ""
    return identifier


def _clean_text(value: Any) -> str:
    return " ".join(str(value or "").split())


def _strip_json_fence(value: str) -> str:
    text = str(value).strip()
    if text.startswith("```"):
        first_newline = text.find("\n")
        if first_newline != -1:
            text = text[first_newline + 1 :]
        if text.endswith("```"):
            text = text[:-3]
    return text.strip()


def _object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    return dict(value) if isinstance(value, Mapping) else {}


__all__ = [
    "ANSWER_CLAIM_BINDER_PRODUCER",
    "AnswerClaimBindingRequest",
    "AnswerClaimBindingRow",
    "BINDER_SCHEMA_VERSION",
    "BoundAnswerClaims",
    "bind_answer_claims",
]
