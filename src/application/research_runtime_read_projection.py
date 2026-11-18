"""Project a completed reader chain into one candidate source record.

This is a pure, post-execution view: it neither admits a read nor updates the
durable cursor, the read quota, checkpoints, metrics, or model spending.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from src.application.active_research_evidence_projection import _source_record
from src.web.research.candidate_pool import CandidatePoolItem
from src.web.research.chain_executor import ChainStepResult
from src.web.research.read_adequacy import ADEQUATE_SHAPE


@dataclass(frozen=True, slots=True)
class ReadSourceProjection:
    """A single source, with the content and outcome used for quota accounting."""

    ok: bool
    content: str
    record: dict[str, Any]


def project_read_chain(
    *,
    candidate: CandidatePoolItem,
    plan_item: Mapping[str, str],
    chain_steps: Sequence[ChainStepResult],
    source_limit: int,
) -> ReadSourceProjection:
    """Keep the legacy winner rule and one-source-per-candidate cardinality.

    Prefer an adequate usable step, then the first usable step. If every step
    fails, preserve the last step's backend and retrieval state for provenance.
    The caller only invokes this after at least one physical backend attempt.
    """

    if not chain_steps:
        raise ValueError("cannot project an empty reader chain")
    usable = next(
        (
            step
            for step in chain_steps
            if step.usable_content and step.adequacy_reason == ADEQUATE_SHAPE
        ),
        None,
    ) or next((step for step in chain_steps if step.usable_content), None)
    ok = usable is not None
    content = str(usable.content or "")[:source_limit] if usable is not None else ""
    final = usable or chain_steps[-1]
    record = _source_record(
        candidate,
        plan_item,
        raw_read={
            "ok": ok,
            "status": "read" if ok else "failed",
            "url": candidate.url,
            "content": content,
            "retrieval_state": str(final.retrieval_state),
        },
        final_backend=str(final.backend),
        retrieval_attempts=[step.to_dict() for step in chain_steps],
    )
    return ReadSourceProjection(ok=ok, content=content, record=record)
