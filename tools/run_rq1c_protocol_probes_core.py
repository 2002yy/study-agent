"""Run deterministic companion probes for the RQ1-C bounded qualification.

These probes exercise production research components with deterministic injected
provider/reader boundaries. They are deliberately separate from the 12 live
holdouts and never contribute to the 12/12 truthfulness or 10/12 quality scores.
The emitted artifact is bound to the exact live runtime artifact by SHA-256.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import tempfile
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.application.active_research_runtime import ActiveResearchRuntimeExecutor
from src.domain.evidence import ClaimEvidenceLinkV1
from src.domain.runtime_entities import WebLookupRun
from src.infrastructure.sqlite.database import RuntimeDatabase
from src.repositories.web_lookup_repository import WebLookupRepository
from src.web.research.active_adapter import ActiveResearchGateway
from src.web.research.active_semantics import CandidateAssessmentResult
from src.web.research.candidate_pool import CandidatePoolItem
from src.web.research.candidate_ranking import CandidateSemanticAssessment
from src.web.research.contracts import (
    EvidenceCluster,
    EvidenceGap,
    EvidenceRequirement,
    ResearchBudget,
    ResearchClaim,
    ResearchClaimEvidenceLink,
    ResearchEvidence,
    ResearchQuestion,
    ResearchState,
    build_research_state,
)
from src.web.research.evidence_gate import evaluate_evidence_gate
from src.web.research.gap_planner import GapSearchIntent
from src.web.research.provider_search import ResearchProviderSearch
from src.web.research.runtime import (
    CLAIM_ENGINE_RUNTIME_CONTEXT_KEY,
    ResearchRuntimeCursor,
)
from src.web.research.source_cluster import (
    CandidateSourceProfile,
    cluster_candidate_sources,
)
from src.web.research.state import attach_claim_engine_state

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

if __name__ == "__main__":
    from tools.run_rq1c_protocol_probes import main as guarded_main

    raise SystemExit(guarded_main())

from tools.rq1c_git_identity import exact_checkout_git_sha  # noqa: E402

PROTOCOL_SCHEMA_VERSION = "rq1c-bounded-protocol-probes-v1"
RUNTIME_SCHEMA_VERSION = "rq1c-bounded-qualification-runtime-v1"
DEFAULT_RUNTIME = (
    REPO_ROOT / "docs" / "research_quality" / "RQ1C_BOUNDED_QUALIFICATION_RUNTIME.json"
)
DEFAULT_OUTPUT = (
    REPO_ROOT / "docs" / "research_quality" / "RQ1C_BOUNDED_PROTOCOL_PROBES.json"
)
REQUIRED_PROBES = (
    "provider_timeout_retry",
    "user_cancellation",
    "provider_http_429",
    "provider_http_503",
    "unreadable_page",
    "duplicate_republication",
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _git_sha() -> str:
    return exact_checkout_git_sha(REPO_ROOT)


def _probe_state(*, min_independent_sources: int = 1) -> ResearchState:
    question = ResearchQuestion(
        id="rq1c_probe_question",
        question_surface="Verify the current release fact.",
        priority="critical",
        state="unresolved",
    )
    claim = ResearchClaim(
        id="rq1c_probe_claim",
        question_id=question.id,
        text="Verify the current release fact from a primary source",
        kind="factual",
        priority="critical",
        state="searching",
        evidence_requirement=EvidenceRequirement(
            source_roles=("primary", "independent_secondary"),
            min_independent_sources=min_independent_sources,
            requires_primary_source=True,
            requires_successful_read=True,
        ),
        created_by="rq1c_protocol_probe",
        created_reason="deterministic companion probe",
    )
    gap = EvidenceGap(
        id="rq1c_probe_gap",
        claim_id=claim.id,
        gap_type="missing_primary_source",
        desired_source_role="primary",
        priority="critical",
        state="open",
    )
    return build_research_state(
        mode="active",
        questions=(question,),
        claims=(claim,),
        evidence=(),
        evidence_links=(),
        source_clusters=(),
        gaps=(gap,),
        conflict_gaps=(),
        budget=ResearchBudget(
            max_candidates=5,
            max_reads=2,
            soft_timeout_seconds=45,
            hard_timeout_seconds=60,
            max_total_chars=6000,
        ),
        reference_date="2026-09-03",
        known_evidence_ids=(),
    )


def _probe_context(state: ResearchState) -> dict[str, Any]:
    return attach_claim_engine_state(
        {
            "source_truth_version": 2,
            "run_attempt": 0,
            "external_data_policy": {"web_allowed": True, "reason": "allowed"},
        },
        state,
        known_evidence_ids=(),
    )


class _OneResultSearch:
    def __init__(self) -> None:
        self.calls = 0

    def search_exact(self, query: str, *, max_results: int = 5) -> dict[str, Any]:
        del query, max_results
        self.calls += 1
        return {
            "status": "ok",
            "reason": "results_found",
            "results": [
                {
                    "title": "Deterministic primary source",
                    "url": "https://primary.example/rq1c-probe",
                    "snippet": "Deterministic search lead only; the page must still be read.",
                    "source": "probe",
                    "published_at": "2026-09-01",
                    "provider": "searxng",
                }
            ],
            "providers_attempted": ["searxng"],
            "provider_errors": [],
            "provider_audits": [],
            "provider_outcomes": [],
            "searched_at": "2026-09-03T00:00:00+00:00",
        }


class _CancellingSearch(_OneResultSearch):
    def __init__(self, repository: WebLookupRepository, run_id: str) -> None:
        super().__init__()
        self.repository = repository
        self.run_id = run_id

    def search_exact(self, query: str, *, max_results: int = 5) -> dict[str, Any]:
        payload = super().search_exact(query, max_results=max_results)
        self.repository.request_cancel(self.run_id)
        return payload


class _NeverRead:
    def __init__(self) -> None:
        self.calls = 0

    def read(self, url: str, *, max_chars: int = 6000) -> dict[str, Any]:
        del url, max_chars
        self.calls += 1
        raise AssertionError("reader must not run after cancellation")


class _UnreadableReader:
    def __init__(self) -> None:
        self.calls = 0

    def read(self, url: str, *, max_chars: int = 6000) -> dict[str, Any]:
        del url, max_chars
        self.calls += 1
        raise TimeoutError("private reader detail must never enter probe artifact")


class _DeterministicAssessor:
    def assess(
        self,
        *,
        candidates: tuple[CandidatePoolItem, ...],
        assignments: Mapping[str, Any],
        **_: Any,
    ) -> CandidateAssessmentResult:
        assessments = {
            candidate.id: CandidateSemanticAssessment(
                candidate_id=candidate.id,
                relevance="answer_relevant",
                relevance_confidence=1.0,
                source_role="primary",
                source_role_confidence=1.0,
                cluster_id=assignments[candidate.id].cluster_id,
                expected_gain_signals=("new_primary",),
                freshness_score=1.0,
                estimated_read_cost=1.0,
            )
            for candidate in candidates
        }
        return CandidateAssessmentResult(
            status="completed",
            assessments=assessments,
            audits=(),
        )


def _provider_probe(probe_id: str, failure: str) -> dict[str, Any]:
    calls: list[dict[str, Any]] = []

    def provider_call(provider: str, query: str, limit: int, timeout: float) -> tuple[list[Mapping[str, Any]], str]:
        calls.append(
            {
                "provider": provider,
                "limit": limit,
                "timeout_seconds": timeout,
                "query_sha256": hashlib.sha256(query.encode("utf-8")).hexdigest(),
            }
        )
        if failure == "timeout":
            raise TimeoutError("private provider detail")
        return [], f"{failure} private provider detail"

    search = ResearchProviderSearch(
        provider_call=provider_call,  # type: ignore[arg-type]
        provider_enabled=lambda provider: provider == "searxng",
        provider_timeout_seconds=1.0,
    )
    payload = search.search_exact("deterministic rq1c provider probe", max_results=3)
    outcomes = payload.get("provider_outcomes") or []
    audits = payload.get("provider_audits") or []
    expected_reason = "timeout" if failure == "timeout" else failure
    passed = (
        payload.get("status") == "unavailable"
        and len(calls) == 2
        and len(outcomes) == 1
        and outcomes[0].get("status") == "failed"
        and outcomes[0].get("reason") == expected_reason
        and outcomes[0].get("attempts") == 2
        and len(audits) == 2
        and all(audit.get("reason") == expected_reason for audit in audits)
    )
    return {
        "id": probe_id,
        "status": "pass" if passed else "fail",
        "evidence": {
            "production_component": "ResearchProviderSearch.search_exact",
            "attempts": len(calls),
            "final_status": str(payload.get("status") or ""),
            "final_reason": str(outcomes[0].get("reason") if outcomes else ""),
            "query_sha256": str(audits[0].get("query_sha256") if audits else ""),
        },
    }


def _runtime_probe(
    *,
    probe_id: str,
    cancelling: bool,
) -> dict[str, Any]:
    state = _probe_state()
    with tempfile.TemporaryDirectory(prefix=f"{probe_id}_") as directory:
        repository = WebLookupRepository(RuntimeDatabase(Path(directory) / "probe.sqlite"))
        run = repository.create(
            WebLookupRun(
                id=f"rq1c_{probe_id}",
                query="Deterministic RQ1-C protocol probe",
                stage="planned",
                status="pending",
                research_context=_probe_context(state),
                max_items=5,
            )
        )
        reader: _NeverRead | _UnreadableReader
        if cancelling:
            search_backend: Any = _CancellingSearch(repository, run.id)
            reader = _NeverRead()
        else:
            search_backend = _OneResultSearch()
            reader = _UnreadableReader()
        gateway = ActiveResearchGateway(
            search_backend=search_backend,
            read_gateway=reader,
        )
        executor = ActiveResearchRuntimeExecutor(
            repository,
            gateway,
            candidate_assessor=_DeterministicAssessor(),  # type: ignore[arg-type]
        )
        completed = executor.execute(
            run.id,
            initial_state=state,
            raise_on_error=True,
        )
        cursor = ResearchRuntimeCursor.from_dict(
            completed.research_context[CLAIM_ENGINE_RUNTIME_CONTEXT_KEY]
        )
        if cancelling:
            passed = (
                completed.status == "cancelled"
                and completed.stage == "cancelled"
                and completed.stop_reason == "user_cancelled"
                and search_backend.calls == 1
                and reader.calls == 0
                and cursor.inflight_external_call is None
                and cursor.inflight_model_call is None
            )
            evidence = {
                "production_component": "ActiveResearchRuntimeExecutor.execute",
                "run_status": completed.status,
                "stage": completed.stage,
                "stop_reason": completed.stop_reason,
                "search_calls": search_backend.calls,
                "read_calls_after_cancel": reader.calls,
                "inflight_external_cleared": cursor.inflight_external_call is None,
            }
        else:
            failed_reads = [item for item in cursor.read_outcomes if item.status == "failed"]
            failures = [item for item in cursor.failures if item.code == "read_failed"]
            selected_read_statuses = sorted(
                {
                    str(item.get("read_status") or "")
                    for item in completed.selected_sources
                    if isinstance(item, Mapping)
                }
            )
            passed = (
                reader.calls >= 1
                and bool(failed_reads)
                and all(item.error_code == "read_failed" for item in failed_reads)
                and bool(failures)
                and all(item.exception_type == "TimeoutError" for item in failures)
                and all(item.detail == "TimeoutError" for item in failures)
                and not any(item.evidence_id for item in cursor.read_outcomes)
                and "read" not in selected_read_statuses
            )
            evidence = {
                "production_component": "ActiveResearchRuntimeExecutor.execute",
                "run_status": completed.status,
                "reader_calls": reader.calls,
                "failed_read_outcomes": len(failed_reads),
                "read_failure_records": len(failures),
                "eligible_evidence_from_failed_reads": sum(
                    1 for item in cursor.read_outcomes if item.evidence_id
                ),
                "selected_read_statuses": selected_read_statuses,
                "failure_exception_types": sorted(
                    {item.exception_type for item in failures if item.exception_type}
                ),
            }
        return {
            "id": probe_id,
            "status": "pass" if passed else "fail",
            "evidence": evidence,
        }


def _candidate(candidate_id: str, url: str, rank: int) -> CandidatePoolItem:
    return CandidatePoolItem(
        id=candidate_id,
        canonical_url=url,
        url=url,
        title=f"Republication {rank}",
        snippet="Republished summary",
        source="probe",
        published_at="2026-09-01",
        query_ids=("rq1c_probe_query",),
        intents=(GapSearchIntent.DISCOVERY,),
        providers=("searxng",),
        first_seen_rank=rank,
    )


def _duplicate_republication_probe() -> dict[str, Any]:
    candidates = (
        _candidate("candidate_a", "https://mirror-a.example/story", 1),
        _candidate("candidate_b", "https://mirror-b.example/story", 2),
    )
    origin_url = "https://origin.example/original-story"
    clustered = cluster_candidate_sources(
        candidates,
        profiles={
            candidate.id: CandidateSourceProfile(
                candidate_id=candidate.id,
                source_role="primary",
                origin_url=origin_url,
            )
            for candidate in candidates
        },
    )
    same_cluster = (
        len(clustered.clusters) == 1
        and len({item.cluster_id for item in clustered.assignments}) == 1
    )
    cluster_id = clustered.assignments[0].cluster_id
    base = _probe_state(min_independent_sources=2)
    evidence = (
        ResearchEvidence(
            evidence_id="evidence_a",
            locator="anchor-a",
            anchored_spans=("anchor-a",),
            lifecycle_status="read",
            extraction_status="eligible",
            published_at="2026-09-01",
        ),
        ResearchEvidence(
            evidence_id="evidence_b",
            locator="anchor-b",
            anchored_spans=("anchor-b",),
            lifecycle_status="read",
            extraction_status="eligible",
            published_at="2026-09-01",
        ),
    )
    links = tuple(
        ResearchClaimEvidenceLink(
            link=ClaimEvidenceLinkV1(
                claim_id=base.claims[0].id,
                evidence_id=item.evidence_id,
                support_type="supports",
                confidence=0.95,
            ),
            source_role="primary",
            source_cluster_id=cluster_id,
            locator=item.locator,
        )
        for item in evidence
    )
    state = build_research_state(
        mode="active",
        questions=base.questions,
        claims=base.claims,
        evidence=evidence,
        evidence_links=links,
        source_clusters=(
            EvidenceCluster(
                id=cluster_id,
                evidence_ids=("evidence_a", "evidence_b"),
                source_role="primary",
                independence_key=clustered.clusters[0].independence_key,
            ),
        ),
        gaps=base.gaps,
        conflict_gaps=(),
        budget=base.budget,
        reference_date=base.reference_date,
        known_evidence_ids=("evidence_a", "evidence_b"),
    )
    gate = evaluate_evidence_gate(state)
    independence_reason = next(
        (reason for reason in gate.reasons if "eligible_support_clusters=" in reason),
        "",
    )
    passed = (
        same_cluster
        and gate.status == "block"
        and independence_reason.endswith("1/2")
    )
    return {
        "id": "duplicate_republication",
        "status": "pass" if passed else "fail",
        "evidence": {
            "production_components": [
                "cluster_candidate_sources",
                "evaluate_evidence_gate",
            ],
            "candidate_count": len(candidates),
            "independence_cluster_count": len(clustered.clusters),
            "gate_status": gate.status,
            "independence_requirement": independence_reason,
        },
    }


def _safe_probe(probe_id: str, call: Any) -> dict[str, Any]:
    try:
        result = call()
        if result.get("id") != probe_id or result.get("status") not in {"pass", "fail"}:
            raise ValueError("probe returned invalid contract")
        return result
    except Exception as exc:
        return {
            "id": probe_id,
            "status": "fail",
            "evidence": {
                "error_type": type(exc).__name__,
            },
        }


def run_protocol_probes(*, runtime_path: Path, output_path: Path) -> dict[str, Any]:
    git_sha = _git_sha()
    runtime_bytes = runtime_path.read_bytes()
    runtime = json.loads(runtime_bytes)
    if not isinstance(runtime, dict) or runtime.get("schema_version") != RUNTIME_SCHEMA_VERSION:
        raise ValueError("protocol probes require an RQ1-C runtime artifact")
    probes = [
        _safe_probe(
            "provider_timeout_retry",
            lambda: _provider_probe("provider_timeout_retry", "timeout"),
        ),
        _safe_probe(
            "user_cancellation",
            lambda: _runtime_probe(probe_id="user_cancellation", cancelling=True),
        ),
        _safe_probe(
            "provider_http_429",
            lambda: _provider_probe("provider_http_429", "http_status:429"),
        ),
        _safe_probe(
            "provider_http_503",
            lambda: _provider_probe("provider_http_503", "http_status:503"),
        ),
        _safe_probe(
            "unreadable_page",
            lambda: _runtime_probe(probe_id="unreadable_page", cancelling=False),
        ),
        _safe_probe("duplicate_republication", _duplicate_republication_probe),
    ]
    if tuple(item["id"] for item in probes) != REQUIRED_PROBES:
        raise AssertionError("protocol probe order/identity drifted")
    artifact = {
        "schema_version": PROTOCOL_SCHEMA_VERSION,
        "generated_at": _utc_now(),
        "runtime_artifact_sha256": _sha256_bytes(runtime_bytes),
        "git_sha": git_sha,
        "leakage_contract": {
            "stores_generated_query_text": False,
            "stores_page_bodies": False,
            "stores_raw_provider_errors": False,
        },
        "probes": probes,
        "summary": {
            "probe_count": len(probes),
            "passed": sum(item["status"] == "pass" for item in probes),
            "failed": [item["id"] for item in probes if item["status"] != "pass"],
        },
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(artifact, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return artifact


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime", type=Path, default=DEFAULT_RUNTIME)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser


def main() -> int:
    args = _parser().parse_args()
    artifact = run_protocol_probes(
        runtime_path=args.runtime.resolve(),
        output_path=args.output.resolve(),
    )
    print(json.dumps(artifact["summary"], ensure_ascii=False, sort_keys=True))
    return 0 if not artifact["summary"]["failed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())