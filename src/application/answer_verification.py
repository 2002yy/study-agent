"""Reusable shadow checks for explicit quotes and computations, including AB2.

Trusted read snapshots and evidence rows are separate from model proposals.
No model calls, prompt edits, repairs, publication rights or semantic verdicts.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
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
        for proposal in inputs.calculations:
            if len(proposal.variables) > 32 or len(dict(proposal.variables)) != len(
                proposal.variables
            ):
                report["calculations"].append(
                    {
                        "status": "UNKNOWN",
                        "reason": "ambiguous_or_excess_variables",
                        "semantic_support": "UNKNOWN",
                    }
                )
            else:
                report["calculations"].append(
                    {
                        **asdict(
                            check_calculation(
                                proposal.expression,
                                proposal.result,
                                variables=dict(proposal.variables),
                                places=proposal.places,
                                rounding=proposal.rounding,
                            )
                        ),
                        "expression": proposal.expression,
                        "claimed_value": proposal.result,
                    }
                )
        # Explicit names keep the public proposal surface independent of the
        # arithmetic function's internal argument names.
        report["boundaries"] = [
            asdict(
                check_boundary(
                    proposal.left,
                    proposal.right,
                    proposal.variable,
                    proposal.result,
                    below=proposal.below,
                    above=proposal.above,
                    below_relation=proposal.below_relation,
                    above_relation=proposal.above_relation,
                    places=proposal.places,
                    rounding=proposal.rounding,
                )
            )
            for proposal in inputs.boundaries
        ]
        checks = report["quotes"] + report["calculations"] + report["boundaries"]
        if checks:
            report["status"] = (
                "FAIL"
                if any(row["status"] == "FAIL" for row in checks)
                else (
                    "UNKNOWN"
                    if any(row["status"] == "UNKNOWN" for row in checks)
                    else "PASS"
                )
            )
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
