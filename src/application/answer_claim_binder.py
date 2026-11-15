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
#: Per *batch* verification load. The whole answer may be much longer: it is
#: verified in consecutive batches, and published atomically only when every
#: batch passes. The old rule applied this number to the whole answer, which
#: rejected any normal research answer outright.
_MAX_SEGMENTS = 16
_MAX_SEGMENT_CHARS = 1200
_MAX_BATCHES = 12
_MAX_TOTAL_SEGMENTS = _MAX_SEGMENTS * _MAX_BATCHES
#: Rendered segment block per batch; the evidence context has its own budget.
_MAX_BATCH_CHARS = 12000
#: A paraphrase/entailment quote must really occur in the page. This is the
#: authenticity check that a model cannot satisfy by inventing a quotation.
_MIN_QUOTE_CHARS = 12
_PARAPHRASE_CONFIDENCE = 0.85
_ENTAILMENT_CONFIDENCE = 0.8
_SPECIFIC_TOKEN = re.compile(r"\d+(?:\.\d+)*")
#: Markdown links, bare URLs and footnote labels are citation pointers. Their
#: digits are never a claim about the world.
_CITATION = re.compile(r"\[[^\]]*\]\([^)]*\)|https?://\S+|\[\s*\d+\s*\]|\[web-\d+\]")
#: Verification text is never rendered into the prompt; it exists so the server
#: can check a claim against what the page actually said.
_MAX_GROUNDING_CHARS = 12_000
# Formatting-insensitive identity is suitable for *literal source statements*,
# not for semantic entailment. Paraphrased claims need a verified quotation.
_GROUNDING_KEEP = re.compile(r"[0-9a-z\u4e00-\u9fff]+")

_ALLOWED_SEGMENT_KINDS = frozenset(
    {
        "source_fact",
        "factual",
        "synthesis",
        "premise",
        "recommendation",
        "instructional",
        "question",
        "uncertainty",
    }
)
#: Chinese sentence punctuation is unambiguous. ASCII punctuation only becomes
#: a boundary when followed by whitespace/end-of-answer, so URLs, versions and
#: decimals such as ``https://docs.python.org/3.12/`` and ``v3.12`` stay intact.
#: Commas split only when the following clause clearly switches into
#: advice/instruction wording; splitting every comma over-segments ordinary
#: factual prose without improving claim coverage.
_SENTENCE_BOUNDARY = re.compile(
    r"(?<=[。！？；])|(?<=[.!?;:])(?=\s|$)|"
    r"(?<=[，,])(?=\s*(?:建议|应该|应当|请|不要|需要|需|推荐|最好|可考虑|"
    r"recommend\b|should\b|please\b|consider\b))",
    re.IGNORECASE,
)
_RULE_LINE = re.compile(r"^\s*(?:-{3,}|\*{3,}|_{3,})\s*$")
#: A unit must carry content; bare markdown markers are formatting, not claims.
_CONTENT = re.compile(r"[0-9A-Za-z\u4e00-\u9fff]")

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
    #: The page body this row stands for, when the row was derived from an
    #: inline read rather than a validated claim-engine relation. A row with
    #: verification text is never trusted by its labels: support is granted only
    #: when the claim itself is found in this text.
    grounding_text: str = ""


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
    #: The answer text without the statements that could not be verified. Empty
    #: when nothing survived; callers must then refuse to publish.
    published_text: str = ""
    withheld: tuple[dict[str, Any], ...] = ()


def bind_answer_claims(
    *,
    request: AnswerClaimBindingRequest,
    model_fn: BinderModelFn,
    producer: str = ANSWER_CLAIM_BINDER_PRODUCER,
    max_attempts: int = 1,
    before_model_call: BinderBeforeCallFn | None = None,
) -> BoundAnswerClaims:
    """Bind the immutable candidate answer to server-owned research evidence.

    Verification runs in consecutive batches so a long answer can still be
    checked completely. The per-batch limit bounds one model request; it no
    longer bounds how much the user is allowed to be told. A failing batch
    rejects the whole answer, so verified head content can never be published
    next to unverified tail content.
    """
    answer = str(request.final_answer or "")
    if not answer.strip():
        raise ValueError("answer claim binding requires a final answer")
    segments, segment_stats = segment_answer_with_stats(answer)
    if not segments:
        return BoundAnswerClaims(
            snapshot=rejected_answer_claim_snapshot(
                answer=answer,
                producer=producer,
                # Too many units is a verification-budget refusal (the caller
                # may shorten or regenerate); an unusable unit is not.
                reason=(
                    "answer_verification_budget_exceeded"
                    if segment_stats.get("overflow_reason") == "segment_count"
                    else "answer_not_segmentable"
                ),
            ),
            attempt_count=0,
            segment_stats=segment_stats,
        )
    batches = _plan_verification_batches(segments)
    if len(segments) > _MAX_TOTAL_SEGMENTS or len(batches) > _MAX_BATCHES:
        # A bounded verification budget is a refusal, not silent partial
        # publication: the caller may shorten or regenerate the answer.
        return BoundAnswerClaims(
            snapshot=rejected_answer_claim_snapshot(
                answer=answer,
                producer=producer,
                reason="answer_verification_budget_exceeded",
            ),
            attempt_count=0,
            segment_stats={
                **segment_stats,
                "batch_count": len(batches),
                "verification_budget_segments": _MAX_TOTAL_SEGMENTS,
                "verification_budget_batches": _MAX_BATCHES,
            },
        )
    rows = tuple(_bounded_rows(request.evidence_rows))
    rows_by_link = {
        (row.claim_id, row.evidence_id): row
        for row in rows
        if row.claim_id and row.evidence_id
    }
    known_evidence_ids = {row.evidence_id for row in rows if row.evidence_id}
    known_research_claim_ids = {row.claim_id for row in rows if row.claim_id}

    attempts = max(0, min(int(max_attempts), 2))
    claims: list[dict[str, Any]] = []
    links: list[dict[str, Any]] = []
    withheld: list[dict[str, Any]] = []
    total_calls = 0
    offset = 0
    for batch_index, batch in enumerate(batches, start=1):
        refs = tuple(_segment_ref(offset + index) for index in range(len(batch)))
        messages = _binding_messages(
            question=request.question,
            answer=answer,
            segments=batch,
            refs=refs,
            rows=rows,
        )
        last_error = ""
        parsed: tuple[
            list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]
        ] | None = None
        repair_used = False
        # The attempt budget covers producer failures; a rejected quotation is a
        # repairable formatting error, so it gets exactly one extra call with the
        # failure fed back. Blind resampling under the same prompt is not repair.
        max_calls = max(1, attempts)
        calls = 0
        while True:
            calls += 1
            # This hook intentionally runs outside the provider-failure catch: an
            # accepted cancellation is control flow, not a failed binder attempt,
            # and must never be swallowed or retried as producer failure.
            if before_model_call is not None:
                before_model_call()
            total_calls += 1
            try:
                raw = model_fn(messages)
            except Exception as exc:  # noqa: BLE001 - provider failures are results
                last_error = f"producer_failed:{type(exc).__name__}"
                if calls >= max_calls:
                    break
                continue
            detail: dict[str, Any] = {}
            parsed, parse_error = _parse_binder_batch(
                raw_output=raw,
                answer=answer,
                question=request.question,
                segments=batch,
                refs=refs,
                rows_by_link=rows_by_link,
                known_evidence_ids=known_evidence_ids,
                known_research_claim_ids=known_research_claim_ids,
                producer=producer,
                failure_detail=detail,
            )
            if parsed is not None:
                break
            last_error = parse_error or "malformed_structured_output"
            if parse_error in {
                "unverified_source_quote",
                "claim_specifics_not_in_source",
            } and not repair_used:
                repair_used = True
                messages = [*messages, _repair_message(detail)]
                max_calls += 1
                continue
            if calls >= max_calls:
                break
        if parsed is None:
            reason = last_error or "producer_unavailable"
            if len(batches) > 1:
                reason = f"batch_{batch_index}_of_{len(batches)}:{reason}"
            return BoundAnswerClaims(
                snapshot=rejected_answer_claim_snapshot(
                    answer=answer, producer=producer, reason=reason
                ),
                attempt_count=total_calls,
                segment_stats={**segment_stats, "batch_count": len(batches)},
            )
        batch_claims, batch_links, batch_withheld = parsed
        claims.extend(batch_claims)
        links.extend(batch_links)
        withheld.extend(batch_withheld)
        offset += len(batch)

    # The same sentence may legitimately repeat inside one answer; it is one
    # claim with one deterministic id, so merge rather than fail the answer.
    unique_claims: dict[str, dict[str, Any]] = {}
    for claim in claims:
        unique_claims.setdefault(str(claim.get("text") or ""), claim)
    unique_links: dict[tuple[str, str, str], dict[str, Any]] = {}
    for link in links:
        unique_links.setdefault(
            (
                str(link.get("claim_id") or ""),
                str(link.get("evidence_id") or ""),
                str(link.get("support_type") or ""),
            ),
            link,
        )
    try:
        snapshot = build_answer_claim_snapshot(
            answer=answer,
            claims=unique_claims.values(),
            claim_links=unique_links.values(),
            known_evidence_ids=known_evidence_ids,
            producer=producer,
            status="validated",
            trust_upstream_claim_ids=False,
        )
    except (TypeError, ValueError):
        return BoundAnswerClaims(
            snapshot=rejected_answer_claim_snapshot(
                answer=answer, producer=producer, reason="malformed_structured_output"
            ),
            attempt_count=total_calls,
            segment_stats={**segment_stats, "batch_count": len(batches)},
        )
    published = answer
    for entry in withheld:
        segment = str(entry.get("segment") or "")
        if segment:
            published = published.replace(segment, "", 1)
    return BoundAnswerClaims(
        snapshot=snapshot,
        attempt_count=total_calls,
        segment_stats={
            **segment_stats,
            "batch_count": len(batches),
            "withheld_count": len(withheld),
        },
        published_text=published.strip(),
        withheld=tuple(withheld),
    )


def _repair_message(detail: Mapping[str, Any]) -> dict[str, str]:
    """Feedback for a rejected quotation: name it, and allow withdrawal.

    A retry that only resamples under the same prompt is not repair. The model is
    told which segment and which evidence failed, must copy a complete sentence
    verbatim, and may drop the support instead of inventing a quotation.
    """

    segment = str(detail.get("segment_ref") or "?")
    evidence_id = str(detail.get("evidence_id") or "?")
    quote = str(detail.get("quote") or "")
    return {
        "role": "user",
        "content": (
            f"上一次输出被拒绝：段落 {segment} 的引文与证据 {evidence_id} 不符"
            "（不在原文中，或缺少该段落里的数字/版本）。请从该证据原文中逐字复制一个"
            "同时包含这些数字的完整句子，不要改写、拼接或意译。如果该证据中找不到"
            "这样的句子，就删除该段落的 support_claims（保留 kind 和其他字段），"
            "不要编造引文，也不要更换证据。只返回与之前相同结构的 JSON。"
            + (f" 被拒绝的引用：{quote}" if quote else "")
        ),
    }


def _parse_binder_batch(
    *,
    raw_output: str,
    answer: str,
    question: str,
    segments: tuple[str, ...],
    refs: tuple[str, ...],
    rows_by_link: Mapping[tuple[str, str], AnswerClaimBindingRow],
    known_evidence_ids: set[str],
    known_research_claim_ids: set[str],
    producer: str,
    failure_detail: dict[str, Any] | None = None,
) -> tuple[tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]] | None, str]:
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
        return None, "producer_refused"
    raw_segments = payload.get("segments")
    if not isinstance(raw_segments, list):
        return None, "malformed_structured_output"
    segment_entries = tuple(_object(entry) for entry in raw_segments)
    if len(segment_entries) != len(segments):
        return None, "segment_coverage_mismatch"
    ref_to_text = dict(zip(refs, segments))
    claims: list[dict[str, Any]] = []
    links: list[dict[str, Any]] = []
    withheld: list[dict[str, Any]] = []
    seen_refs: set[str] = set()
    for entry in segment_entries:
        ref = _clean_identifier(entry.get("segment_ref"))
        if not ref or ref not in ref_to_text or ref in seen_refs:
            return None, "segment_coverage_mismatch"
        seen_refs.add(ref)
        text = ref_to_text[ref]
        kind = str(entry.get("kind") or "").strip()
        if kind == "factual":
            kind = "source_fact"
        status = str(entry.get("status") or "").strip()
        if kind not in _ALLOWED_SEGMENT_KINDS:
            return None, "malformed_structured_output"

        raw_support = entry.get("evidence_support") or []
        if not isinstance(raw_support, list) or not all(
            isinstance(item, str) for item in raw_support
        ):
            return None, "malformed_structured_output"
        support_ids = tuple(_clean_identifier(item) for item in raw_support)
        if any(not item for item in support_ids):
            return None, "malformed_structured_output"
        if len(set(support_ids)) != len(support_ids):
            return None, "duplicate_evidence_support"

        segment_detail: dict[str, Any] = {"segment_ref": ref}
        bindings, error = _claim_support_bindings(
            entry,
            claim_text=text,
            question=question,
            allow_question_numbers=kind in {"synthesis", "recommendation"},
            support_ids=support_ids,
            rows_by_link=rows_by_link,
            known_evidence_ids=known_evidence_ids,
            known_research_claim_ids=known_research_claim_ids,
            failure_detail=segment_detail,
        )
        if error:
            if failure_detail is not None:
                failure_detail.update(segment_detail)
            return None, error

        if kind in {"instructional", "question", "uncertainty"}:
            # A claim id with no evidence authorizes nothing; only support lists
            # are rejected here.
            if bindings:
                return None, "non_factual_segment_support"
            claims.append(
                {
                    "text": text,
                    "kind": kind,
                    "status": "asserted",
                    "source": "provider_structured",
                }
            )
            continue

        if kind == "premise":
            # A restatement of the user's own setup is verified against the
            # question, not against a page. It may not smuggle in a new number
            # and it may not carry source support.
            if bindings:
                return None, "premise_with_support"
            if not _premise_in_question(text, question):
                # A statement the question does not carry is not a premise. It
                # is withheld from the published answer, never relabelled.
                withheld.append({"segment": text, "reason": "premise_not_in_question"})
                continue
            claims.append(
                {
                    "text": text,
                    "kind": "premise",
                    "status": "asserted",
                    "source": "provider_structured",
                }
            )
            continue

        if status not in {"asserted", "qualified"}:
            if kind == "recommendation" and not status:
                # Advice asserts no source fact; a producer that omits the
                # field is still recorded, never relabelled as a fact.
                status = "asserted"
            else:
                return None, "malformed_structured_output"
        if kind == "source_fact" and not bindings:
            # No evidence for a source statement: delete it rather than publish
            # an unsupported assertion (the correction loop's "删去无依据内容").
            withheld.append({"segment": text, "reason": "unbound_factual_segment"})
            continue
        if kind == "synthesis" and not bindings:
            # A synthesis must rest on premises the server can verify; it may
            # never be published as an unconstrained "therefore".
            withheld.append({"segment": text, "reason": "unbound_synthesis_segment"})
            continue
        if kind == "recommendation" and not bindings:
            # Advice with no premise is still allowed, but it may not smuggle
            # in a specific number: that is a factual assertion in disguise.
            if _specific_tokens(text):
                withheld.append(
                    {"segment": text, "reason": "unsupported_specific_claim"}
                )
                continue
            claims.append(
                {
                    "text": text,
                    "kind": "recommendation",
                    "status": status,
                    "source": "provider_structured",
                }
            )
            continue

        claim_id = deterministic_claim_id(
            answer_hash=answer_content_hash(answer), claim_text=text
        )
        claims.append(
            {
                "text": text,
                # ``source_fact`` is the wire name; the snapshot keeps the
                # existing ``factual`` kind so older readers stay valid.
                "kind": "factual" if kind == "source_fact" else kind,
                "status": status,
                "source": "provider_structured",
            }
        )
        for evidence_id, confidence, support_type in bindings:
            links.append(
                {
                    "claim_id": claim_id,
                    "evidence_id": evidence_id,
                    "support_type": support_type,
                    "confidence": confidence,
                }
            )
    return (claims, links, withheld), ""


def _claim_support_bindings(
    entry: Mapping[str, Any],
    *,
    claim_text: str,
    question: str,
    allow_question_numbers: bool = False,
    support_ids: tuple[str, ...],
    rows_by_link: Mapping[tuple[str, str], AnswerClaimBindingRow],
    known_evidence_ids: set[str],
    known_research_claim_ids: set[str],
    failure_detail: dict[str, Any] | None = None,
) -> tuple[list[tuple[str, float, str]], str]:
    """Server-verified support for one claim.

    Two independent paths exist, and both end in server checks:

    * literal support - the claim reproduces a complete source sentence;
    * paraphrase/entailment support - the model must return the exact source
      quotation it relied on, that quotation must really occur in the page, and
      every number/version in the claim must occur in the quotation.
    """
    raw_claims = entry.get("support_claims") or []
    if not isinstance(raw_claims, list):
        return [], "malformed_structured_output"
    parsed: list[dict[str, str]] = []
    for raw in raw_claims:
        item = _object(raw)
        evidence_id = _clean_identifier(item.get("evidence_id"))
        relation = str(item.get("relation") or "").strip().lower()
        quote = str(item.get("source_quote") or "")
        if not evidence_id or relation not in {
            "direct_quote",
            "paraphrase",
            "entailment",
            "contradicts",
        }:
            return [], "malformed_structured_output"
        parsed.append(
            {"evidence_id": evidence_id, "relation": relation, "quote": quote}
        )
    all_ids = support_ids + tuple(item["evidence_id"] for item in parsed)
    if len(set(all_ids)) != len(all_ids):
        return [], "duplicate_evidence_support"
    if not all_ids:
        return [], ""
    unknown = [item for item in all_ids if item not in known_evidence_ids]
    if unknown:
        return [], "unknown_evidence_id"
    research_claim_id = _clean_identifier(entry.get("research_claim_id"))
    if research_claim_id:
        if research_claim_id not in known_research_claim_ids:
            return [], "unknown_research_claim_id"
    else:
        inferred = _infer_research_claim_id(
            support_ids=tuple(all_ids),
            rows_by_link=rows_by_link,
            known_research_claim_ids=known_research_claim_ids,
        )
        if inferred is None:
            return [], "missing_research_claim_id"
        research_claim_id = inferred

    verified_quotes: list[str] = []
    bindings: list[tuple[str, float, str]] = []
    for evidence_id in support_ids:
        row = rows_by_link.get((research_claim_id, evidence_id))
        if row is None:
            return [], "claim_evidence_mismatch"
        confidence = _supported_confidence(row, claim_text)
        if confidence is None:
            return [], "ineligible_evidence_support"
        bindings.append((evidence_id, confidence, "direct_support"))
        verified_quotes.append(claim_text)
    for item in parsed:
        row = rows_by_link.get((research_claim_id, item["evidence_id"]))
        if row is None:
            return [], "claim_evidence_mismatch"
        if item["relation"] == "contradicts":
            return [], "claim_contradicted"
        if item["relation"] == "direct_quote":
            confidence = _supported_confidence(row, claim_text)
            if confidence is None:
                return [], "ineligible_evidence_support"
            bindings.append((item["evidence_id"], confidence, "direct_support"))
            verified_quotes.append(claim_text)
            continue
        confidence = _paraphrase_confidence(row, claim_text, item["quote"])
        if confidence is None:
            if failure_detail is not None:
                # The repair loop needs to say *which* quote failed and against
                # which evidence; a bare reason code cannot be acted on.
                failure_detail.update(
                    evidence_id=item["evidence_id"],
                    quote=str(item["quote"])[:200],
                    claim=claim_text[:120],
                )
            return [], "unverified_source_quote"
        bindings.append((item["evidence_id"], confidence, "indirect_support"))
        verified_quotes.append(item["quote"])
    if parsed and not _specific_tokens_within(
        claim_text, verified_quotes, question if allow_question_numbers else ""
    ):
        if failure_detail is not None:
            failure_detail.update(
                evidence_id=parsed[0]["evidence_id"] if parsed else "",
                quote=str(parsed[0]["quote"])[:200] if parsed else "",
                claim=claim_text[:120],
            )
        return [], "claim_specifics_not_in_source"
    return bindings, ""


def _paraphrase_confidence(
    row: AnswerClaimBindingRow, claim_text: str, source_quote: str
) -> float | None:
    """Confidence for a paraphrase whose quotation the server can verify.

    The quotation must be a real substring of the page body; that is what
    separates a translation from an invented citation. Quoting a page that is
    not the cited row fails, and quoting a different part of the same page that
    does not carry the assertion fails the specifics check that follows.
    """

    if not row.grounding_text:
        return None
    body = _grounding_text(row.grounding_text)
    quote = _clean_text(source_quote)
    # A producer may quote a short passage rather than one sentence. Every
    # sentence in it must still occur verbatim: joining real sentences is
    # allowed, inventing one is not.
    parts = [part for part in re.split(r"(?<=[.!?;。！？；])\s*|\n+", quote) if part.strip()]
    verified = 0
    for part in parts:
        normalized = _grounding_text(part)
        if len(normalized) < _MIN_QUOTE_CHARS:
            continue
        if normalized not in body:
            return None
        verified += 1
    if not verified:
        return None
    return _PARAPHRASE_CONFIDENCE


def _specific_tokens(text: str) -> set[str]:
    """Numbers/versions in a claim that a source must actually contain.

    Citation labels and links are pointers, not facts: ``[web-4](url)`` must not
    turn "this is the source I cited" into a numeric claim about the world.
    """

    prose = _CITATION.sub(" ", str(text or ""))
    return set(_SPECIFIC_TOKEN.findall(prose))


def _premise_in_question(claim_text: str, question: str) -> bool:
    """True when a premise restates the user's setup and adds no new numbers.

    The wording need not be identical, so this compares CJK bigrams instead of
    whole phrases: at least half of them must occur in the question.
    """

    asked = _clean_text(question)
    if not asked:
        return False
    if any(token not in asked for token in _specific_tokens(claim_text)):
        return False
    characters = re.findall(r"[\u4e00-\u9fff]", claim_text)
    bigrams = {"".join(pair) for pair in zip(characters, characters[1:])}
    if bigrams:
        overlap = sum(1 for bigram in bigrams if bigram in asked)
        return overlap / len(bigrams) >= 0.5
    words = re.findall(r"[A-Za-z][A-Za-z0-9_.-]{2,}", claim_text)
    return any(word.casefold() in asked.casefold() for word in words)


def _specific_tokens_within(
    claim_text: str, quotes: Iterable[str], question: str = ""
) -> bool:
    """Every number in a claim must be traceable, but to a permitted origin.

    A source fact may only use numbers the source states. A synthesis or a
    recommendation may also reuse a figure the user supplied in the question
    ("4 个 worker"); it still may not invent one.
    """

    required = _specific_tokens(claim_text)
    if not required:
        return True
    corpus = _grounding_text(" ".join(quotes) + " " + str(question or ""))
    return all(_grounding_text(token) in corpus for token in required)


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


def _supported_confidence(
    row: AnswerClaimBindingRow, claim_text: str
) -> float | None:
    """Confidence for a claim/evidence link, decided by the server.

    A row that carries the page body cannot be trusted by its labels: reading a
    page is not support for a claim. Support is granted only when the claim's own
    content is found in that body (see :func:`claim_grounded_in_text`). Rows
    without verification text keep the claim-engine rule, which is validated
    upstream by the Evidence Gate.
    """

    if row.grounding_text:
        if not claim_grounded_in_text(claim_text, row.grounding_text):
            return None
        # A literal source sentence is evidence of what that page states,
        # not a semantic entailment proof or maximal confidence.
        return STRONG_EVIDENCE_THRESHOLD
    return _positive_support_confidence(row)


def claim_grounded_in_text(claim_text: str, page_text: str) -> bool:
    """Allow only a literal full-sentence source assertion for inline reads.

    A shared substring, matched version, or matching negation is *not* evidence
    of entailment: A acquired B and B acquired A share most words.
    Inline reads have no claim-engine Evidence Gate, so the server only accepts
    formatting-insensitive identity with a complete source sentence. Other
    factual paraphrases must fail closed until claim-level evidence is qualified.

    This proves what the retrieved page *states*, not whether the page is true.
    The existing binder still decides which source id belongs to each segment.
    """
    claim = _grounding_text(claim_text)
    if not claim or not _grounding_text(page_text):
        return False
    return any(
        _grounding_text(sentence) == claim
        for sentence in _SENTENCE_SPLIT.split(str(page_text or ""))
    )


# Keep decimals/versions and URLs intact; an ASCII full stop is only a
# sentence boundary if followed by whitespace or the end of the text.
_SENTENCE_SPLIT = re.compile(r"(?<=[。！？\n;；])|(?<=[.!?])(?=\s|$)")


def _grounding_text(value: Any) -> str:
    """Normalize formatting only; never discard or paraphrase predicates."""
    return "".join(_GROUNDING_KEEP.findall(str(value or "").casefold()))


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
    """Segment with diagnostics that keep "empty" apart from "too big".

    ``_segment_answer`` collapses "no content", "a unit is too long" and "the
    answer needs more verification batches than the budget allows" into ``()``;
    the stats keep those cases distinguishable in the audit.
    """

    units = _segment_answer_units(answer or "")
    overflow_chars = any(len(part) > _MAX_SEGMENT_CHARS for part in units)
    overflow_count = len(units) > _MAX_TOTAL_SEGMENTS
    segments = () if overflow_chars or overflow_count else tuple(units)
    stats = {
        "raw_nonempty_segment_count": len(units),
        "segment_limit": _MAX_SEGMENTS,
        "max_segment_chars": _MAX_SEGMENT_CHARS,
        "segment_overflow": bool(overflow_count or overflow_chars),
        "overflow_reason": (
            "segment_count"
            if overflow_count
            else ("segment_chars" if overflow_chars else "")
        ),
        "accepted": bool(segments),
        "batch_count": (
            len(_plan_verification_batches(segments)) if segments else 0
        ),
    }
    return segments, stats


def _segment_answer_units(answer: str) -> list[str]:
    """Split an answer into verifiable units without splitting every line.

    A unit is a sentence or a list item. Markdown headings stay attached to the
    block they introduce, and rules are dropped. The previous implementation
    treated every newline as a boundary, which turned an ordinary 4.9k answer
    into 133 fragments and made the whole answer unpublishable.
    """

    text = str(answer or "").replace("\r\n", "\n").replace("\r", "\n")
    units: list[str] = []
    pending_heading = ""
    for block in re.split(r"\n\s*\n", text):
        for raw_line in block.split("\n"):
            line = raw_line.strip()
            if not line or _RULE_LINE.match(line):
                continue
            if line.startswith("#"):
                pending_heading = f"{pending_heading} {line}".strip()
                continue
            body = f"{pending_heading} {line}".strip() if pending_heading else line
            pending_heading = ""
            for part in _SENTENCE_BOUNDARY.split(body):
                part = part.strip()
                if part and _CONTENT.search(part):
                    units.append(part)
    if pending_heading and _CONTENT.search(pending_heading):
        units.append(pending_heading)
    return units


def _plan_verification_batches(
    segments: tuple[str, ...],
) -> list[tuple[str, ...]]:
    """Consecutive batches, each bounded by one model request.

    Batching is what lets the per-request limit stay small without capping the
    length of the answer a reader can be told.
    """

    batches: list[tuple[str, ...]] = []
    current: list[str] = []
    chars = 0
    for segment in segments:
        cost = len(segment) + 8
        if current and (
            len(current) >= _MAX_SEGMENTS or chars + cost > _MAX_BATCH_CHARS
        ):
            batches.append(tuple(current))
            current = []
            chars = 0
        current.append(segment)
        chars += cost
    if current:
        batches.append(tuple(current))
    return batches


def _segment_answer(answer: str) -> tuple[str, ...]:
    segments: list[str] = []
    for candidate in _segment_answer_units(answer):
        if len(candidate) > _MAX_SEGMENT_CHARS:
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


def substantive_claims_fully_bound(snapshot: AnswerClaimSnapshotV1) -> bool:
    """True when every claim that asserts something about the world is bound.

    A synthesis is a conclusion drawn from verified premises; it is published
    as an inference, but it still needs those premises. Recommendations are
    advice rather than source statements and are audited under their own kind.
    """
    bound_claim_ids = {
        link.claim_id
        for link in snapshot.claim_links
        if link.claim_id
        and link.support_type in _POSITIVE_SUPPORT_TYPES
        and link.confidence >= STRONG_EVIDENCE_THRESHOLD
    }
    return all(
        claim.kind not in {"factual", "source_fact", "synthesis"}
        or claim.id in bound_claim_ids
        for claim in snapshot.claims
    )


_POSITIVE_SUPPORT_TYPES = frozenset({"direct_support", "indirect_support"})


def _numbered_segments(segments: tuple[str, ...], refs: tuple[str, ...]) -> str:
    """The prompt's segment block, built once so its size can be enforced."""

    return "\n".join(
        f"[{ref}] {segment}" for ref, segment in zip(refs, segments, strict=False)
    )


def _binding_messages(
    *,
    question: str,
    answer: str,
    segments: tuple[str, ...],
    refs: tuple[str, ...],
    rows: tuple[AnswerClaimBindingRow, ...],
) -> list[dict[str, str]]:
    context = _render_context(rows)
    numbered = _numbered_segments(segments, refs)
    system = (
        "You verify every segment of an already-written final answer against "
        "server-owned page evidence. The answer may be in Chinese while the "
        "pages are in English; a faithful translation is acceptable support, "
        "but only with the exact source sentence that carries it.\n"
        "Rules:\n"
        "1. Never modify or add to the answer; classify every server segment.\n"
        "2. Return EXACTLY one entry per segment_ref; missing, duplicate or "
        "unknown refs are rejected.\n"
        "3. kind is source_fact | synthesis | premise | recommendation | "
        "instructional | question | uncertainty. source_fact states what a "
        "source says; synthesis combines verified premises into a conclusion; "
        "premise restates the user's own setup from the question and may add no "
        "new number; recommendation gives advice. Never label advice, a "
        "conclusion or a restated assumption as source_fact.\n"
        "4a. Literal support: put the evidence_id in evidence_support ONLY when "
        "the segment reproduces a COMPLETE sentence from that page (formatting "
        "ignored).\n"
        "4b. Paraphrase/translation support: add to support_claims an object "
        "with evidence_id, relation paraphrase|entailment, and source_quote "
        "copied VERBATIM from that page (one or more complete sentences; every "
        "sentence must appear on the page unchanged). The server checks that "
        "each quoted sentence really occurs in the page, and that every "
        "number/version in the segment also occurs in the quotation. Invented "
        "or altered quotations are rejected.\n"
        "4c. source_fact needs at least one verified support. synthesis needs at "
        "least one verified premise and is published as an inference, not as a "
        "source statement. recommendation may stand without support only when "
        "it contains no specific number/version.\n"
        "4d. A source that does not support the segment, contradicts it, or "
        "supports only a weaker claim must not be cited; the segment is "
        "rejected instead. If the pages cannot settle the question, say so "
        "through kind=uncertainty rather than asserting it.\n"
        "5. instructional/question/uncertainty segments omit status, "
        "research_claim_id and both support lists.\n"
        "6. If the whole answer cannot be safely bound, set refused=true.\n"
        'Respond with JSON only: {"refused": bool, "segments": '
        '[{"segment_ref":"s1","kind":"source_fact",'
        '"research_claim_id":"claim_id","status":"asserted|qualified",'
        '"evidence_support":["evidence_id"],'
        '"support_claims":[{"evidence_id":"evidence_id",'
        '"relation":"paraphrase|entailment","source_quote":"exact page sentence"}]}]}.'
    )
    user = (
        "Question:\n{question}\n\n"
        "Final answer segments (read-only):\n{numbered}\n\n"
        "Available server-owned research claim/evidence rows:\n{context}"
    ).format(
        question=_clean_text(question)[:_MAX_CONTEXT_CHARS],
        numbered=numbered[:_MAX_BATCH_CHARS],
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
    if row.grounding_text:
        # Quotable page text, so a paraphrase can name the sentence it relies
        # on. Verification still checks the quotation against the full body.
        parts.append(f"excerpt: {_clip(row.grounding_text, 400)}")
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
            grounding_text=_clean_text(row.grounding_text)[:_MAX_GROUNDING_CHARS],
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
