"""Reusable shadow checks for explicit quotes and computations, including AB2.

Trusted read snapshots and evidence rows are separate from model proposals.
No model calls, prompt edits, repairs, publication rights or semantic verdicts.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from decimal import Decimal, InvalidOperation
import re
import time
from typing import Any

from src.application.answer_claim_binder import (
    AnswerClaimBindingRow,
    eligible_support_row,
)
from src.application.exact_calculation import check_boundary, check_calculation
from src.application.shadow_isolation import run_shadow_bounded
from src.domain.answer_claims import answer_content_hash
from src.web.research.evidence_binding import ReadDocument, check_read_quote


@dataclass(frozen=True)
class QuoteProposal:
    claim_id: str
    evidence_id: str
    read_id: str
    source_url: str
    content_sha256: str
    payload_sha256: str
    span: tuple[int, int]
    text: str
    kind: str = "direct"


@dataclass(frozen=True)
class CalculationProposal:
    expression: str
    result: str
    variables: tuple[tuple[str, str], ...] = ()
    places: int | None = None
    rounding: str = "half_even"
    label: str = ""
    formula_origin: tuple[str, str] = ("model_recall", "")


@dataclass(frozen=True)
class BoundaryProposal:
    left: str
    right: str
    variable: str
    result: str
    below: str
    above: str
    below_relation: str
    above_relation: str
    places: int | None = None
    rounding: str = "half_even"
    label: str = ""
    formula_origin: tuple[str, str] = ("model_recall", "")


@dataclass(frozen=True)
class FormulaOriginCheck:
    """Program-derived provenance of a formula's premises.

    A claimed origin is only ever *downgraded* to ``unverified``; arithmetic
    ``PASS`` never upgrades it. ``user_given_verified``/``evidence_verified``
    mean the numeric premises were located in the question or an owned read,
    not that the formula is a true external fact.
    """

    status: str
    claimed: str
    ref: str = ""
    reason: str = ""


_NUM_LITERAL = re.compile(r"\d+(?:\.\d+)?")


def _canonical_number(literal: str) -> str:
    try:
        return format(Decimal(literal).normalize(), "f")
    except (InvalidOperation, ValueError):
        return literal


def _numeric_premises(*sources: str) -> tuple[str, ...]:
    found: list[str] = []
    for source in sources:
        for literal in _NUM_LITERAL.findall(str(source or "")):
            if literal not in found:
                found.append(literal)
    return tuple(found)


def _text_numbers(text: str) -> frozenset[str]:
    return frozenset(_canonical_number(item) for item in _NUM_LITERAL.findall(text or ""))


def resolve_formula_origin(
    proposal_origin: tuple[str, str],
    *expressions: str,
    original_question: str = "",
    evidence_ids: frozenset[str] = frozenset(),
    evidence_text: str = "",
) -> FormulaOriginCheck:
    """Independently locate a formula's numeric premises; downgrade only.

    A model may *claim* user_given/evidence_quote, but the status here is derived
    from where the formula's numeric constants actually appear (as standalone
    numeric tokens). The rule can only downgrade to ``unverified``; arithmetic
    PASS never upgrades it and ``model_recall`` is never a verified source.
    """
    claimed, ref = proposal_origin
    if claimed not in {"user_given", "evidence_quote", "model_recall"}:
        return FormulaOriginCheck("unverified", claimed, ref, "unknown_origin_type")
    literals = _numeric_premises(*expressions)
    if not literals:
        return FormulaOriginCheck("unverified", claimed, ref, "no_numeric_premise")
    required = {_canonical_number(literal) for literal in literals}
    if claimed == "user_given":
        ok = required <= _text_numbers(original_question)
        return FormulaOriginCheck(
            "user_given_verified" if ok else "unverified",
            claimed,
            ref,
            "" if ok else "premise_not_in_question",
        )
    if claimed == "evidence_quote":
        if ref not in evidence_ids:
            return FormulaOriginCheck("unverified", claimed, ref, "origin_ref_not_owned_evidence")
        ok = required <= _text_numbers(evidence_text)
        return FormulaOriginCheck(
            "evidence_verified" if ok else "unverified",
            claimed,
            ref,
            "" if ok else "premise_not_in_evidence",
        )
    return FormulaOriginCheck("unverified", claimed, ref, "model_recall_is_not_a_source")



@dataclass(frozen=True)
class AnswerVerificationInputs:
    # Constructed by the server adapter from the immutable candidate, actual
    # reads and existing evidence ledger. Never deserialize this whole object
    # from a model: only the proposal tuples are model-owned.
    answer_hash: str
    documents: tuple[ReadDocument, ...] = ()
    evidence_rows: tuple[AnswerClaimBindingRow, ...] = ()
    quotes: tuple[QuoteProposal, ...] = ()
    calculations: tuple[CalculationProposal, ...] = ()
    boundaries: tuple[BoundaryProposal, ...] = ()
    # Original user-visible question, used only to verify claimed ``user_given``
    # premises. Server-owned; never model-supplied.
    original_question: str = ""
    # Server-owned (evidence_id, text) pairs used only to verify claimed
    # ``evidence_quote`` formula premises. Never model-supplied.
    evidence_texts: tuple[tuple[str, str], ...] = ()
    # Server-owned join to the existing evidence provenance, not model ids.
    # Each tuple is (evidence_id, read_id, content_sha256, payload_sha256).
    evidence_reads: tuple[tuple[str, str, str, str], ...] = ()


def _quote(proposal: QuoteProposal, inputs: AnswerVerificationInputs) -> dict[str, str]:
    result = {
        "status": "UNKNOWN",
        "reason": "read_snapshot_unavailable",
        "semantic_support": "UNKNOWN",
        "claim_id": proposal.claim_id,
        "evidence_id": proposal.evidence_id,
        "read_id": proposal.read_id,
        "content_sha256": proposal.content_sha256,
    }
    if not inputs.evidence_rows:
        return {**result, "reason": "evidence_ownership_unavailable"}
    rows = [
        row
        for row in inputs.evidence_rows
        if (row.claim_id, row.evidence_id) == (proposal.claim_id, proposal.evidence_id)
    ]
    if not rows:
        return {**result, "status": "FAIL", "reason": "claim_evidence_mismatch"}
    if len(rows) != 1:
        return {**result, "reason": "ambiguous_evidence_ownership"}
    if not eligible_support_row(rows[0]):
        return {**result, "status": "FAIL", "reason": "ineligible_evidence_support"}
    if rows[0].url != proposal.source_url:
        return {**result, "status": "FAIL", "reason": "evidence_source_mismatch"}
    provenance = [
        item for item in inputs.evidence_reads if item[0] == proposal.evidence_id
    ]
    if len(provenance) != 1:
        return {**result, "reason": "evidence_read_provenance_unavailable_or_ambiguous"}
    if provenance[0][1:] != (
        proposal.read_id,
        proposal.content_sha256,
        proposal.payload_sha256,
    ):
        return {**result, "status": "FAIL", "reason": "evidence_read_version_mismatch"}
    documents = [
        document
        for document in inputs.documents
        if document.read_id == proposal.read_id
    ]
    if len(documents) != 1:
        return {**result, "reason": "read_snapshot_unavailable_or_ambiguous"}
    if proposal.kind == "paraphrase":
        # Byte comparison is never a semantic paraphrase test.
        return {**result, "reason": "paraphrase_requires_semantic_verification"}
    if proposal.kind != "direct":
        return {**result, "reason": "unsupported_quote_kind"}
    status, reason = check_read_quote(
        documents[0],
        read_id=proposal.read_id,
        source_url=proposal.source_url,
        content_sha256=proposal.content_sha256,
        payload_sha256=proposal.payload_sha256,
        span=proposal.span,
        quote=proposal.text,
    )
    return {**result, "status": status, "reason": reason}


def observe_answer_verification(
    candidate: str, inputs: AnswerVerificationInputs
) -> dict[str, Any]:
    """Shadow only: record failures, do not change the candidate or any gate.

    Missing proposals are UNKNOWN, never implicit zero-error evidence. Results
    verify only the supplied propositions, not all claims in natural prose.
    """
    report: dict[str, Any] = {
        "schema_version": "answer-verification-shadow-v1",
        "candidate_hash": answer_content_hash(candidate),
        "status": "UNKNOWN",
        "reason": "proposals_not_available",
        "semantic_support": "UNKNOWN",
        "publication_authority": False,
        "stop_authority": False,
        "model_calls": 0,
        "quotes": [],
        "calculations": [],
        "boundaries": [],
    }
    try:
        if not inputs.answer_hash or inputs.answer_hash != report["candidate_hash"]:
            return {**report, "status": "FAIL", "reason": "candidate_identity_mismatch"}
        if (
            len(inputs.documents) > 40
            or len(inputs.evidence_rows) > 64
            or len(inputs.evidence_reads) > 64
            or len(inputs.quotes) + len(inputs.calculations) + len(inputs.boundaries)
            > 32
            or any(len(document.text) > 200000 for document in inputs.documents)
        ):
            return {**report, "reason": "input_limit"}
        report["quotes"] = [_quote(proposal, inputs) for proposal in inputs.quotes]
        evidence_ids = frozenset(
            row.evidence_id for row in inputs.evidence_rows if row.evidence_id
        ) | frozenset(evidence_id for evidence_id, _ in inputs.evidence_texts)
        evidence_text = "\n".join(
            [document.text for document in inputs.documents]
            + [text for _, text in inputs.evidence_texts]
        )
        for proposal in inputs.calculations:
            if len(proposal.variables) > 32 or len(dict(proposal.variables)) != len(
                proposal.variables
            ):
                report["calculations"].append(
                    {
                        "status": "UNKNOWN",
                        "reason": "ambiguous_or_excess_variables",
                        "semantic_support": "UNKNOWN",
                        "verified_support": False,
                        "label": proposal.label,
                    }
                )
                continue
            origin = resolve_formula_origin(
                proposal.formula_origin,
                proposal.expression,
                original_question=inputs.original_question,
                evidence_ids=evidence_ids,
                evidence_text=evidence_text,
            )
            check = check_calculation(
                proposal.expression,
                proposal.result,
                variables=dict(proposal.variables),
                places=proposal.places,
                rounding=proposal.rounding,
            )
            report["calculations"].append(
                {
                    **asdict(check),
                    "expression": proposal.expression,
                    "claimed_value": proposal.result,
                    "label": proposal.label,
                    "formula_origin": asdict(origin),
                    "verified_support": (
                        check.status == "PASS" and origin.status != "unverified"
                    ),
                }
            )
        # Explicit names keep the public proposal surface independent of the
        # arithmetic function's internal argument names.
        for boundary in inputs.boundaries:
            origin = resolve_formula_origin(
                boundary.formula_origin,
                boundary.left,
                boundary.right,
                original_question=inputs.original_question,
                evidence_ids=evidence_ids,
                evidence_text=evidence_text,
            )
            check = check_boundary(
                boundary.left,
                boundary.right,
                boundary.variable,
                boundary.result,
                below=boundary.below,
                above=boundary.above,
                below_relation=boundary.below_relation,
                above_relation=boundary.above_relation,
                places=boundary.places,
                rounding=boundary.rounding,
            )
            report["boundaries"].append(
                {
                    **asdict(check),
                    "label": boundary.label,
                    "formula_origin": asdict(origin),
                    "verified_support": (
                        check.status == "PASS" and origin.status != "unverified"
                    ),
                }
            )
        checks = report["quotes"] + report["calculations"] + report["boundaries"]
        if checks:
            # Arithmetic PASS under an unverified formula is not verified
            # support: downgrade to UNKNOWN so it can never read as a fact.
            if any(row["status"] == "FAIL" for row in checks):
                report["status"] = "FAIL"
            elif any(row["status"] == "UNKNOWN" for row in checks) or any(
                not row.get("verified_support", True) for row in checks
            ):
                report["status"] = "UNKNOWN"
            else:
                report["status"] = "PASS"
            report["reason"] = "supplied_proposals_checked"
        report["coverage"] = {
            name: "SUPPLIED" if getattr(inputs, name) else "NOT_OBSERVED"
            for name in ("quotes", "calculations", "boundaries")
        }
        return report
    except Exception:  # malformed shadow input must never change production output
        return {**report, "status": "UNKNOWN", "reason": "invalid_shadow_input"}


def observe_answer_verification_bounded(
    candidate: str, inputs: AnswerVerificationInputs, *, deadline: float | None = None
) -> dict[str, Any]:
    """Reuse the existing bounded shadow executor; late work cannot publish."""
    budget = (
        0.1 if deadline is None else min(0.1, max(0.0, deadline - time.monotonic()))
    )
    outcome = run_shadow_bounded(
        lambda: observe_answer_verification(candidate, inputs), budget_seconds=budget
    )
    if outcome.ok and isinstance(outcome.value, dict):
        return outcome.value
    return {
        "schema_version": "answer-verification-shadow-v1",
        "candidate_hash": answer_content_hash(candidate),
        "status": "UNKNOWN",
        "reason": "shadow_unavailable:" + outcome.reason,
        "semantic_support": "UNKNOWN",
        "publication_authority": False,
        "stop_authority": False,
        "model_calls": 0,
    }
