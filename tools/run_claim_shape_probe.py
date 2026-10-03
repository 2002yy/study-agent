"""§38c claim-shape / extractor disambiguation: one page, six extractor cells.

Freezes the target page exactly as the runtime read it (same URL, same 6000
chars and sha256), the same frozen extractor and the same model parameters, and
swaps only two dimensions:

    rows    = claim text + claim metadata (what the extractor is asked to prove)
    columns = harness conventions (source role / cluster / title / published_at)

Cells:

    A  offline case question          + offline harness conventions
    B  offline case question          + runtime source conventions
    C  runtime comparison child claim + offline harness conventions
    D  runtime comparison child claim + runtime source conventions
    E  runtime atomic child claim     + offline harness conventions
    F  runtime atomic child claim     + runtime source conventions
A is the known-good offline cell and D is the known runtime cell; the
discriminating cells are B, C and - added here because the runtime bound the
page to the comparison claim, not the atomic one - E and F. The experiment
never adjusts prompts or relations; it only reports what the frozen extractor
returns for each claim shape.

Diagnostic-only; production runtime untouched.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from dotenv import load_dotenv  # noqa: E402

SCHEMA_VERSION = "claim-shape-disambiguation-v1"
TARGET_URL_MARKER = "api/modules.html"


@dataclass
class ClaimSpec:
    key: str
    text: str
    kind: str
    priority: str
    state: str
    requires_successful_read: bool
    min_independent_sources: int
    requires_primary_source: bool
    created_by: str
    created_reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "text": self.text,
            "kind": self.kind,
            "priority": self.priority,
            "state": self.state,
            "requires_successful_read": self.requires_successful_read,
            "min_independent_sources": self.min_independent_sources,
            "requires_primary_source": self.requires_primary_source,
            "created_by": self.created_by,
            "created_reason": self.created_reason,
        }


@dataclass
class HarnessSpec:
    key: str
    source_role: str
    source_cluster_id: str
    title: str
    published_at: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "source_role": self.source_role,
            "source_cluster_id": self.source_cluster_id,
            "title": self.title,
            "published_at": self.published_at,
        }


@dataclass
class CellResult:
    cell: str
    claim_key: str
    harness_key: str
    status: str = ""
    reason: str = ""
    relation: str = ""
    strength: float | None = None
    locator: str = ""
    caveats: list[str] = field(default_factory=list)
    anchored_spans: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "cell": self.cell,
            "claim_key": self.claim_key,
            "harness_key": self.harness_key,
            "status": self.status,
            "reason": self.reason,
            "relation": self.relation,
            "strength": self.strength,
            "locator": self.locator[:200],
            "caveats": [item[:300] for item in self.caveats[:4]],
            "anchored_spans": [item[:200] for item in self.anchored_spans[:3]],
        }


def load_capture(artifact: Mapping[str, Any]) -> dict[str, Any]:
    """Extract frozen content, runtime source metadata and both child claims."""

    case = (artifact.get("cases") or [{}])[0]
    sources = case.get("sources") or []
    target_source = next(
        (
            row
            for row in sources
            if isinstance(row, Mapping) and TARGET_URL_MARKER in str(row.get("url") or "")
        ),
        {},
    )
    source_reads = artifact.get("source_reads") or []
    target_read = next(
        (
            row
            for row in source_reads
            if isinstance(row, Mapping)
            and (
                TARGET_URL_MARKER in str(row.get("url") or "")
                or int(row.get("content_chars") or 0) >= 6000
            )
        ),
        {},
    )
    claims = artifact.get("claims") or []
    by_kind: dict[str, Mapping[str, Any]] = {}
    for claim in claims:
        if isinstance(claim, Mapping):
            by_kind.setdefault(str(claim.get("kind") or ""), claim)
    return {
        "question": str(case.get("question") or ""),
        "content": str(target_read.get("content") or ""),
        "content_sha256": str(target_read.get("content_sha256") or ""),
        "content_chars": int(target_read.get("content_chars") or 0),
        "target_source": {
            "url": str(target_source.get("url") or target_read.get("url") or ""),
            "title": str(target_source.get("title") or target_read.get("title") or "")[:300],
            "source_role": str(target_source.get("source_role") or ""),
            "cluster_id": str(target_source.get("cluster_id") or ""),
            "published_at": str(target_source.get("published_at") or ""),
        },
        "atomic_claim": by_kind.get("factual"),
        "comparison_claim": by_kind.get("analytical"),
    }


def build_claims(capture: Mapping[str, Any]) -> list[ClaimSpec]:
    """Row dimension: offline question, runtime atomic claim, runtime comparison claim."""

    rows = [
        ClaimSpec(
            key="offline_question",
            text=str(capture.get("question") or ""),
            kind="factual",
            priority="critical",
            state="pending",
            requires_successful_read=True,
            min_independent_sources=1,
            requires_primary_source=False,
            created_by="hybrid_selection_chain",
            created_reason="§38b diagnostic chain",
        )
    ]
    for key, claim in (
        ("runtime_comparison_claim", capture.get("comparison_claim")),
        ("runtime_atomic_claim", capture.get("atomic_claim")),
    ):
        if not isinstance(claim, Mapping):
            continue
        requirement = claim.get("evidence_requirement")
        requirement = requirement if isinstance(requirement, Mapping) else {}
        rows.append(
            ClaimSpec(
                key=key,
                text=str(claim.get("text") or ""),
                kind=str(claim.get("kind") or "factual"),
                priority=str(claim.get("priority") or "major"),
                state=str(claim.get("state") or "pending"),
                requires_successful_read=bool(
                    requirement.get("requires_successful_read", True)
                ),
                min_independent_sources=int(
                    requirement.get("min_independent_sources") or 1
                ),
                requires_primary_source=bool(
                    requirement.get("requires_primary_source")
                ),
                created_by=str(claim.get("created_by") or "runtime_claim_planner"),
                created_reason=str(claim.get("created_reason") or ""),
            )
        )
    return rows


def build_harnesses(capture: Mapping[str, Any]) -> list[HarnessSpec]:
    """Column dimension: offline conventions vs the runtime's own source metadata."""

    source = capture.get("target_source") or {}
    return [
        HarnessSpec(
            key="offline_harness",
            source_role="primary",
            source_cluster_id="hybrid_cluster",
            title=str(source.get("title") or "Node.js modules"),
            published_at="",
        ),
        HarnessSpec(
            key="runtime_harness",
            source_role=str(source.get("source_role") or "primary"),
            source_cluster_id=str(source.get("cluster_id") or "runtime_cluster"),
            title=str(source.get("title") or "Node.js modules"),
            published_at=str(source.get("published_at") or ""),
        ),
    ]


def run_matrix(
    *,
    capture: Mapping[str, Any],
    claims: list[ClaimSpec],
    harnesses: list[HarnessSpec],
    extract: Callable[[ClaimSpec, HarnessSpec, str], Mapping[str, Any]],
) -> list[CellResult]:
    """Six cells over the frozen content; the extractor is injectable."""

    content = str(capture.get("content") or "")
    cell_letters = "ABCDEF"
    results: list[CellResult] = []
    index = 0
    for claim in claims:
        for harness in harnesses:
            letter = cell_letters[index] if index < len(cell_letters) else f"C{index}"
            index += 1
            result = CellResult(cell=letter, claim_key=claim.key, harness_key=harness.key)
            try:
                raw = extract(claim, harness, content) or {}
            except Exception as exc:  # diagnostics never fatal
                result.status = "exception"
                result.reason = type(exc).__name__
                results.append(result)
                continue
            result.status = str(raw.get("status") or "")
            result.reason = str(raw.get("reason") or "")
            result.relation = str(raw.get("relation") or "")
            strength = raw.get("strength")
            result.strength = float(strength) if isinstance(strength, (int, float)) else None
            result.locator = str(raw.get("locator") or "")
            result.caveats = [str(item) for item in raw.get("caveats") or []]
            result.anchored_spans = [str(item) for item in raw.get("anchored_spans") or []]
            results.append(result)
    return results


def _live_extractor(model_timeout_seconds: float = 30.0) -> Callable[..., Mapping[str, Any]]:
    from src.web.research.active_semantics import RuntimeEvidenceExtractor
    from src.web.research.contracts import EvidenceRequirement, ResearchClaim
    from src.web.research.model_gateway import ResearchModelGateway
    from src.web.research.candidate_pool import CandidatePoolItem

    model = ResearchModelGateway(model_profile="flash", timeout_seconds=model_timeout_seconds)
    extractor = RuntimeEvidenceExtractor(model)

    def extract(claim: ClaimSpec, harness: HarnessSpec, content: str) -> Mapping[str, Any]:
        runtime_claim = ResearchClaim(
            id=f"claim_38c_{claim.key}",
            question_id="question_38c",
            text=claim.text[:2000],
            kind=claim.kind,  # type: ignore[arg-type]
            priority=claim.priority,  # type: ignore[arg-type]
            state=claim.state,  # type: ignore[arg-type]
            evidence_requirement=EvidenceRequirement(
                min_independent_sources=claim.min_independent_sources,
                requires_primary_source=claim.requires_primary_source,
                requires_successful_read=claim.requires_successful_read,
            ),
            created_by=claim.created_by,
            created_reason=claim.created_reason,
        )
        item = CandidatePoolItem(
            id="candidate_38c_target",
            canonical_url=harness.source_cluster_id and "https://nodejs.cn/api/modules.html",
            url="https://nodejs.cn/api/modules.html",
            title=harness.title,
            snippet="",
            source="claim_shape_probe",
            published_at=harness.published_at,
            query_ids=(),
            intents=(),
            providers=(),
            first_seen_rank=0,
        )
        result = extractor.extract(
            run_id="claim_shape_probe",
            claim=runtime_claim,
            candidate=item,
            source_role=harness.source_role,
            source_cluster_id=harness.source_cluster_id,
            content=content,
            timeout_seconds=model_timeout_seconds,
        )
        if result.status != "completed" or result.extraction is None:
            return {"status": result.status, "reason": result.reason or "extractor_unavailable"}
        link = result.extraction
        return {
            "status": "completed",
            "relation": link.relation,
            "strength": link.strength,
            "locator": link.locator,
            "caveats": list(link.caveats),
            "anchored_spans": list(link.anchored_spans),
        }

    return extract


def _resolved_model_name() -> str:
    try:
        from src.llm_client import get_model_name

        return get_model_name("flash")
    except Exception:
        return ""


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--capture", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    args = _parser().parse_args(list(argv) if argv is not None else None)
    load_dotenv(REPO_ROOT / ".env")
    artifact = json.loads(args.capture.read_text(encoding="utf-8"))
    capture = load_capture(artifact)
    claims = build_claims(capture)
    harnesses = build_harnesses(capture)
    results = run_matrix(capture=capture, claims=claims, harnesses=harnesses, extract=_live_extractor())
    payload = {
        "schema_version": SCHEMA_VERSION,
        "diagnostic_only": True,
        "qualification_evidence": False,
        "source_capture": str(args.capture).replace("\\", "/"),
        "target_url": capture.get("target_source", {}).get("url", ""),
        "content_chars": capture.get("content_chars"),
        "content_sha256": capture.get("content_sha256"),
        "provider_profile": (__import__("os").getenv("LLM_PROVIDER_PROFILE") or "openai"),
        "model_profile": "flash",
        "model_name": _resolved_model_name(),
        "thinking_mode": "disabled_for_structured_research_calls",
        "claims": [claim.to_dict() for claim in claims],
        "harnesses": [harness.to_dict() for harness in harnesses],
        "cells": [cell.to_dict() for cell in results],
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    for cell in payload["cells"]:
        print(
            f"{cell['cell']}: {cell['claim_key']} x {cell['harness_key']} -> "
            f"{cell['relation'] or cell['status']} ({cell['reason']})"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
