"""Environment latency fingerprint for Live qualification runs (Item 4 v1).

Measures a *structured, comparable snapshot* of the current environment so that
future runs can answer "did the environment get slower?" before attributing any
performance change to code:

- DeepSeek structured smoke (fixed minimal fixtures, not business cases):
  planner / assessor / extractor with elapsed_ms, tokens, finish_reason,
  attempt_count, model_name.
- Provider probe with one fixed query: bing_rss / searxng / duckduckgo with
  status, attempts, elapsed_ms, result_count and the sanitized failure reason.
- Reader fetch of one stable lightweight URL: elapsed_ms / ok / content_chars.

Raw numbers are always kept - never a good/bad boolean. ``fingerprint_id`` is a
short hash over the measured values so two runs can be compared cheaply.

Known limitation (documented, not hidden): the production reader currently uses
a fixed internal timeout and is NOT yet clamped to the research window, so a
read started near the window boundary can still cross it.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
import hashlib
import io
import json
import sys
import time
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from dotenv import load_dotenv  # noqa: E402

DEFAULT_OUTPUT = (
    REPO_ROOT / "docs" / "research_quality" / "ENVIRONMENT_FINGERPRINT.json"
)
SCHEMA_VERSION = "rq1c-environment-fingerprint-v1"
# A stable, non-news-dependent query so provider latency is comparable.
PROBE_QUERY = "python 3.13 release notes"
PROBE_READER_URL = "https://www.python.org/downloads/"


def _run_ms(call) -> tuple[Any, float]:
    started = time.monotonic()
    value = call()
    return value, round((time.monotonic() - started) * 1000.0, 1)


def _audit_value(audit: Any, key: str) -> Any:
    if audit is None:
        return None
    data = asdict(audit) if is_dataclass(audit) else dict(vars(audit))
    return data.get(key)


def _deepseek_smoke() -> dict[str, Any]:
    from src.web.research.active_semantics import (
        RuntimeCandidateAssessor,
        RuntimeEvidenceExtractor,
    )
    from src.web.research.candidate_pool import CandidatePoolItem
    from src.web.research.claim_planner import RuntimeClaimPlanner
    from src.web.research.contracts import (
        EvidenceRequirement,
        ResearchBudget,
        ResearchClaim,
    )
    from src.web.research.gap_planner import GapSearchIntent
    from src.web.research.model_gateway import ResearchModelGateway
    from src.web.research.source_cluster import CandidateClusterAssignment

    gateway = ResearchModelGateway(timeout_seconds=40.0)
    results: dict[str, Any] = {
        "model_name": gateway._resolved_model_name(),
        "provider_profile": gateway.provider_profile,
    }

    planner = RuntimeClaimPlanner(gateway)
    budget = ResearchBudget(
        max_candidates=20,
        max_reads=8,
        soft_timeout_seconds=45.0,
        hard_timeout_seconds=60.0,
    )
    planned, planner_ms = _run_ms(
        lambda: planner.plan(
            run_id="fingerprint",
            question=(
                "According to Docker's official documentation, what pull-rate "
                "limits apply to unauthenticated users on Docker Hub?"
            ),
            reference_date=datetime.now(timezone.utc).date().isoformat(),
            budget=budget,
            mode="active",
        )
    )
    planner_audit = planned.audits[-1] if getattr(planned, "audits", ()) else None
    results["planner"] = {
        "status": getattr(planned, "status", None),
        "elapsed_ms": planner_ms,
        "input_tokens": _audit_value(planner_audit, "input_tokens"),
        "output_tokens": _audit_value(planner_audit, "output_tokens"),
        "finish_reason": _audit_value(planner_audit, "finish_reason"),
        "attempt_count": len(getattr(planned, "audits", ()) or ()),
    }

    claim = ResearchClaim(
        id="claim-fingerprint-1",
        question_id="question-fingerprint-1",
        text="Docker Hub limits unauthenticated users to 100 pulls per 6 hours",
        kind="factual",
        priority="critical",
        state="searching",
        evidence_requirement=EvidenceRequirement(
            source_roles=("primary", "independent_secondary"),
            min_independent_sources=1,
            requires_primary_source=True,
            requires_successful_read=True,
            requires_dated_evidence=False,
        ),
    )
    url = "https://docs.docker.com/docker-hub/usage/pulls/"
    candidate = CandidatePoolItem(
        id="cand-fingerprint-1",
        canonical_url=url,
        url=url,
        title="Docker Hub pull rate limits",
        snippet="Unauthenticated users: 100 pulls per 6 hours.",
        source="Docker Docs",
        published_at="2026-08-01",
        query_ids=("q-fingerprint",),
        intents=(GapSearchIntent.PRIMARY,),
        providers=("bing_rss",),
        first_seen_rank=1,
    )
    assignment = CandidateClusterAssignment(
        candidate_id=candidate.id,
        cluster_id="cluster-fingerprint",
        independence_key="publisher:docker",
        basis="publisher",
        source_role="primary",
    )
    assessor = RuntimeCandidateAssessor(gateway)
    assessed, assessor_ms = _run_ms(
        lambda: assessor.assess(
            run_id="fingerprint",
            claim=claim,
            candidates=(candidate,),
            assignments={candidate.id: assignment},
            reference_date=datetime.now(timezone.utc).date().isoformat(),
        )
    )
    assessor_audit = assessed.audits[-1] if getattr(assessed, "audits", ()) else None
    results["assessor"] = {
        "status": getattr(assessed, "status", None),
        "elapsed_ms": assessor_ms,
        "input_tokens": _audit_value(assessor_audit, "input_tokens"),
        "output_tokens": _audit_value(assessor_audit, "output_tokens"),
        "finish_reason": _audit_value(assessor_audit, "finish_reason"),
        "attempt_count": len(getattr(assessed, "audits", ()) or ()),
    }

    extractor = RuntimeEvidenceExtractor(gateway)
    page = (
        "Docker Hub pull rate limits. Unauthenticated users are limited to 100 "
        "pulls per 6 hours per IPv4 address. Authenticated Personal users get "
        "200 pulls per 6 hours. Documented at docs.docker.com."
    )
    extracted, extractor_ms = _run_ms(
        lambda: extractor.extract(
            run_id="fingerprint",
            claim=claim,
            candidate=candidate,
            source_role="primary",
            source_cluster_id="cluster-fingerprint",
            content=page,
        )
    )
    extractor_audit = (
        extracted.audits[-1] if getattr(extracted, "audits", ()) else None
    )
    results["extractor"] = {
        "status": getattr(extracted, "status", None),
        "elapsed_ms": extractor_ms,
        "input_tokens": _audit_value(extractor_audit, "input_tokens"),
        "output_tokens": _audit_value(extractor_audit, "output_tokens"),
        "finish_reason": _audit_value(extractor_audit, "finish_reason"),
        "attempt_count": len(getattr(extracted, "audits", ()) or ()),
    }
    return results


def _provider_probe() -> dict[str, Any]:
    from src.web.research.provider_search import ResearchProviderSearch

    search = ResearchProviderSearch()
    payload, elapsed_ms = _run_ms(
        lambda: search.search_exact(PROBE_QUERY, max_results=5)
    )
    rows: dict[str, Any] = {}
    elapsed_by_provider: dict[str, float] = {}
    for audit in payload.get("provider_audits", ()):
        if not isinstance(audit, dict):
            continue
        provider = str(audit.get("provider") or "")
        elapsed_by_provider[provider] = round(
            elapsed_by_provider.get(provider, 0.0)
            + float(audit.get("elapsed_seconds") or 0.0) * 1000.0,
            1,
        )
    for outcome in payload.get("provider_outcomes", ()):
        provider = str(outcome.get("provider") or "")
        rows[provider] = {
            "status": outcome.get("status"),
            "reason": outcome.get("reason"),
            "attempts": outcome.get("attempts"),
            "result_count": outcome.get("result_count"),
            "elapsed_ms": elapsed_by_provider.get(provider),
        }
    return {
        "query": PROBE_QUERY,
        "elapsed_ms": elapsed_ms,
        "overall": payload.get("status"),
        "providers": rows,
    }


def _reader_probe() -> dict[str, Any]:
    from src.web.research_gateway import ResearchWebGateway

    reader = ResearchWebGateway()
    result, elapsed_ms = _run_ms(
        lambda: reader.read(PROBE_READER_URL, max_chars=6000)
    )
    content = str((result or {}).get("content") or "")
    return {
        "url": PROBE_READER_URL,
        "elapsed_ms": elapsed_ms,
        "ok": bool((result or {}).get("ok") is True),
        "content_chars": len(content),
        "error": str((result or {}).get("error") or "")[:120],
    }


def _fingerprint_id(payload: dict[str, Any]) -> str:
    material = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:16]


def run_fingerprint(*, output_path: Path | None = DEFAULT_OUTPUT) -> dict[str, Any]:
    load_dotenv(REPO_ROOT / ".env")
    started = datetime.now(timezone.utc)
    measured: dict[str, Any] = {}
    errors: list[str] = []
    for name, probe in (
        ("deepseek", _deepseek_smoke),
        ("providers", _provider_probe),
        ("reader", _reader_probe),
    ):
        try:
            measured[name] = probe()
        except Exception as exc:  # diagnostics: type only, never raw text
            errors.append(f"{name}:{type(exc).__name__}")

    artifact = {
        "schema_version": SCHEMA_VERSION,
        "timestamp": started.isoformat().replace("+00:00", "Z"),
        "deepseek": measured.get("deepseek"),
        "providers": measured.get("providers"),
        "reader": measured.get("reader"),
        "errors": errors,
        "logger_note": (
            "reader uses a fixed internal timeout and is not yet clamped to the "
            "research window (known limitation, see PROJECT_STATUS §25)"
        ),
        "fingerprint_id": _fingerprint_id(measured),
    }
    if output_path is not None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(artifact, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    return artifact


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    artifact = run_fingerprint(
        output_path=args.output.resolve() if args.output else None
    )
    summary = {
        "fingerprint_id": artifact["fingerprint_id"],
        "deepseek": {
            key: (value or {}).get("elapsed_ms")
            for key, value in (
                ("planner", (artifact.get("deepseek") or {}).get("planner")),
                ("assessor", (artifact.get("deepseek") or {}).get("assessor")),
                ("extractor", (artifact.get("deepseek") or {}).get("extractor")),
            )
        },
        "providers": {
            provider: {
                "status": row.get("status"),
                "elapsed_ms": row.get("elapsed_ms"),
            }
            for provider, row in (
                (artifact.get("providers") or {}).get("providers") or {}
            ).items()
        },
        "reader_ms": (artifact.get("reader") or {}).get("elapsed_ms"),
        "errors": artifact["errors"],
    }
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
