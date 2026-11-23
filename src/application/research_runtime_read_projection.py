"""Project reader-chain or local-seed content into candidate source records.

These pure views never publish sources, admit a read, or update the durable
cursor, read quota, checkpoints, metrics, or model spending.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from src.application.active_research_evidence_projection import _source_record
from src.web.research.candidate_pool import CandidatePoolItem
from src.web.research.chain_executor import ChainStepResult
from src.web.research.deep_runtime import (
    SEED_FINAL_BACKEND,
    materialization_provenance,
    materialized_content,
)
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


def project_exhausted_read_source(
    candidate: CandidatePoolItem, plan_item: Mapping[str, str]
) -> dict[str, Any]:
    """Preserve a failed source with no backend attempt provenance."""

    return _source_record(
        candidate,
        plan_item,
        raw_read={
            "ok": False,
            "status": "failed",
            "url": candidate.url,
            "error": "external_attempts_exhausted",
            "content": "",
        },
    )


def project_deep_seed_source(
    *,
    candidate: CandidatePoolItem,
    plan_item: Mapping[str, Any],
    seed_source: Mapping[str, Any],
    source_limit: int,
) -> dict[str, Any] | None:
    """Project durable seed bytes as a source without publishing them.

    Local materialization is not a physical read: no gateway, reader chain,
    external attempt or retrieval state is created. The runtime owns source
    insertion, character charging and the subsequent checkpoint in that order.
    """

    content = materialized_content(seed_source, source_limit=source_limit)
    if not content:
        return None
    record = _source_record(
        candidate,
        plan_item,
        raw_read={
            "ok": True,
            "status": "read",
            "url": candidate.url,
            "content": content,
        },
        final_backend=SEED_FINAL_BACKEND,
        retrieval_attempts=[],
    )
    record["materialization"] = materialization_provenance(
        seed_source=seed_source,
        materialized_content=content,
        full_body_length=len(str(seed_source.get("content") or "")),
    )
    return record
