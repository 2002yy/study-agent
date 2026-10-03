"""§38 Agent-loop prototype: model-driven PLAN/SEARCH/READ/JUDGE controller.

Diagnostic-only hypothesis test, deliberately NOT wired into the production
research pipeline. The only question it answers: if query planning and result
selection are decided by a small model instead of the rule chain, do we find
the fact-bearing page with fewer searches and fewer reads?

Kept deterministic by construction:

- bounds live in code: ``max_searches`` (default 4) and ``max_reads`` (default
  6) per case, plus a per-case wall-clock cap;
- provider search and page reading reuse the production stacks
  (``ActiveResearchGateway.search_detailed`` / ``.read``);
- evidence extraction and the supports predicate reuse the frozen
  ``RuntimeEvidenceExtractor`` (same prompt, same relation vocabulary);
- duplicates are rejected in code (canonical URLs never read twice, queries
  never repeated untouched: the planner sees previous queries and results).

The loop itself is pure and injectable so tests can run it without network or
model access. The artifact is explicitly ``qualification_evidence: false`` and
must never be mixed with RQ1-C gate numbers.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from dotenv import load_dotenv  # noqa: E402

from src.news.url_normalizer import canonicalize_url  # noqa: E402

PROTOTYPE_SCHEMA_VERSION = "agent-loop-prototype-v1"
DEFAULT_MAX_SEARCHES = 4
DEFAULT_MAX_READS = 6
DEFAULT_RESULTS_PER_QUERY = 5
DEFAULT_READ_CHARS = 6000

PlannerFn = Callable[[Mapping[str, Any]], Mapping[str, Any]]
SelectorFn = Callable[[Mapping[str, Any], tuple[dict, ...], int], Iterable[str]]
ReaderFn = Callable[[str, int], Mapping[str, Any]]
SearcherFn = Callable[[str, int], Mapping[str, Any]]
ExtractFn = Callable[[str, Mapping[str, Any], str], Mapping[str, Any]]


@dataclass
class LoopBudget:
    max_searches: int = DEFAULT_MAX_SEARCHES
    max_reads: int = DEFAULT_MAX_READS
    results_per_query: int = DEFAULT_RESULTS_PER_QUERY
    read_chars: int = DEFAULT_READ_CHARS
    case_timeout_seconds: float = 60.0


@dataclass
class LoopOutcome:
    case_id: str
    question: str
    status: str = "completed"
    stop_reason: str = ""
    elapsed_seconds: float = 0.0
    searches: int = 0
    reads: int = 0
    extractor_calls: int = 0
    planner_calls: int = 0
    selector_calls: int = 0
    queries: list[str] = field(default_factory=list)
    search_steps: list[dict] = field(default_factory=list)
    selector_steps: list[dict] = field(default_factory=list)
    planner_failures: int = 0
    selector_failures: int = 0
    results_seen: list[dict] = field(default_factory=list)
    read_urls: list[str] = field(default_factory=list)
    relations: list[dict] = field(default_factory=list)
    relation_counts: dict[str, int] = field(default_factory=dict)
    supports: int = 0
    budget_violations: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "question": self.question,
            "status": self.status,
            "stop_reason": self.stop_reason,
            "elapsed_seconds": round(self.elapsed_seconds, 3),
            "searches": self.searches,
            "reads": self.reads,
            "extractor_calls": self.extractor_calls,
            "planner_calls": self.planner_calls,
            "planner_failures": self.planner_failures,
            "selector_calls": self.selector_calls,
            "selector_failures": self.selector_failures,
            "queries": list(self.queries),
            "search_steps": list(self.search_steps),
            "selector_steps": list(self.selector_steps),
            "results_seen": list(self.results_seen),
            "read_urls": list(self.read_urls),
            "relations": list(self.relations),
            "relation_counts": dict(sorted(self.relation_counts.items())),
            "supports": self.supports,
            "binding_rows": self.supports,
            "budget_violations": list(self.budget_violations),
        }


def run_loop(
    *,
    case_id: str,
    question: str,
    budget: LoopBudget,
    search_fn: SearcherFn,
    read_fn: ReaderFn,
    planner_fn: PlannerFn,
    selector_fn: SelectorFn,
    extract_fn: ExtractFn,
    monotonic: Callable[[], float] = time.monotonic,
) -> LoopOutcome:
    """The bounded controller: PLAN -> SEARCH -> SELECT -> READ -> JUDGE."""

    outcome = LoopOutcome(case_id=case_id, question=question)
    started = monotonic()
    seen_urls: set[str] = set()
    evidence_rows: list[dict] = []

    def elapsed() -> float:
        return max(0.0, monotonic() - started)

    while True:
        if elapsed() >= budget.case_timeout_seconds:
            outcome.stop_reason = "case_timeout"
            break
        if outcome.searches >= budget.max_searches:
            outcome.stop_reason = "search_budget_exhausted"
            break

        planner_state = {
            "case_id": case_id,
            "step": outcome.searches + 1,
            "question": question,
            "evidence": evidence_rows[-8:],
            "previous_queries": list(outcome.queries),
            "results": outcome.results_seen[-24:],
            "remaining_searches": budget.max_searches - outcome.searches,
            "remaining_reads": budget.max_reads - outcome.reads,
        }
        plan_raw = planner_fn(planner_state) or {}
        outcome.planner_calls += 1
        if bool(plan_raw.get("sufficient")):
            outcome.stop_reason = "planner_sufficient"
            break
        query = " ".join(str(plan_raw.get("query") or "").split())
        if not query:
            outcome.planner_failures += 1
            outcome.stop_reason = "planner_no_query"
            break
        if query in outcome.queries:
            outcome.stop_reason = "planner_repeated_query"
            break
        if elapsed() >= budget.case_timeout_seconds:
            outcome.stop_reason = "case_timeout"
            break

        outcome.searches += 1
        outcome.queries.append(query)
        payload = search_fn(query, budget.results_per_query) or {}
        outcomes: list[dict] = []
        for raw in payload.get("results") or []:
            if not isinstance(raw, Mapping):
                continue
            canonical = canonicalize_url(str(raw.get("url") or raw.get("link") or ""))
            title = " ".join(str(raw.get("title") or raw.get("name") or "").split())
            if not canonical or not title:
                continue
            entry = {
                "canonical_url": canonical,
                "title": title[:300],
                "snippet": " ".join(str(raw.get("snippet") or "").split())[:400],
            }
            if canonical not in seen_urls:
                seen_urls.add(canonical)
                outcome.results_seen.append(entry)
            outcomes.append(entry)
        outcome.search_steps.append(
            {
                "query": query,
                "status": str(payload.get("status") or ""),
                "result_count": len(outcomes),
                "providers_attempted": list(payload.get("providers_attempted") or []),
                "provider_errors": list(payload.get("provider_errors") or []),
            }
        )

        remaining_reads = budget.max_reads - outcome.reads
        if remaining_reads <= 0:
            outcome.stop_reason = "read_budget_exhausted"
            break
        candidates = tuple(
            entry
            for entry in outcomes
            if entry["canonical_url"] not in set(outcome.read_urls)
        )
        if not candidates:
            continue
        selector_state = {
            "case_id": case_id,
            "step": outcome.searches,
            "question": question,
            "evidence": evidence_rows[-8:],
            "queries": list(outcome.queries),
        }
        chosen_raw = selector_fn(selector_state, candidates, remaining_reads) or ()
        outcome.selector_calls += 1
        candidate_urls = {entry["canonical_url"]: entry["canonical_url"] for entry in candidates}
        chosen: list[str] = []
        rejected: list[str] = []
        for item in chosen_raw:
            canonical = canonicalize_url(str(item))
            if (
                canonical
                and canonical in candidate_urls
                and canonical not in outcome.read_urls
                and len(chosen) < remaining_reads
            ):
                chosen.append(canonical)
            else:
                rejected.append(str(item)[:200])
        outcome.selector_steps.append(
            {
                "query": query,
                "candidate_count": len(candidates),
                "chosen": list(chosen),
                "rejected": rejected[:6],
                "raw": [str(item)[:200] for item in list(chosen_raw)[:8]],
            }
        )
        if not chosen:
            if not list(chosen_raw):
                outcome.selector_failures += 1
            continue

        for canonical in chosen:
            if outcome.reads >= budget.max_reads:
                outcome.stop_reason = "read_budget_exhausted"
                break
            if elapsed() >= budget.case_timeout_seconds:
                outcome.stop_reason = "case_timeout"
                break
            meta = next(
                entry for entry in outcome.results_seen if entry["canonical_url"] == canonical
            )
            outcome.reads += 1
            outcome.read_urls.append(canonical)
            raw_read = read_fn(canonical, budget.read_chars) or {}
            content = str(raw_read.get("content") or "")[: budget.read_chars]
            if not content.strip():
                evidence_rows.append(
                    {
                        "canonical_url": canonical,
                        "relation": "unreadable",
                        "caveat": str(raw_read.get("error") or "empty_read")[:200],
                    }
                )
                continue
            outcome.extractor_calls += 1
            extraction = extract_fn(question, meta, content) or {}
            relation = " ".join(str(extraction.get("relation") or "unavailable").split())
            row = {
                "canonical_url": canonical,
                "title": meta["title"],
                "relation": relation,
                "caveat": " ".join(str(extraction.get("caveat") or "").split())[:300],
            }
            evidence_rows.append(row)
            outcome.relations.append(row)
            outcome.relation_counts[relation] = outcome.relation_counts.get(relation, 0) + 1
            if relation == "supports":
                outcome.supports += 1
        if outcome.stop_reason:
            break
        if outcome.supports > 0:
            outcome.stop_reason = "supports_found"
            break
        if outcome.searches >= budget.max_searches:
            outcome.stop_reason = "search_budget_exhausted"
            break

    if outcome.searches > budget.max_searches:
        outcome.budget_violations.append("max_searches")
    if outcome.reads > budget.max_reads:
        outcome.budget_violations.append("max_reads")
    outcome.elapsed_seconds = elapsed()
    if not outcome.stop_reason:
        outcome.stop_reason = "loop_end"
    return outcome


# ---------------------------------------------------------------------------
# Production-backed adapters (constructed explicitly, never on import).
# ---------------------------------------------------------------------------

PLANNER_SYSTEM_PROMPT = (
    "You are a bounded web-research planner. Given the claim, the evidence so "
    "far (relation + caveat) and the queries/results already tried, decide the "
    "single next search query that would most directly carry the missing fact. "
    "The search backend is Bing RSS: it does not support site:, boolean "
    "operators or long keyword stacks. Use short queries (roughly 3-8 words), "
    "prefer one distinctive quoted phrase plus at most two concept words, and "
    "when earlier results were off-target change the phrase or the document "
    "type (official docs / support policy / changelog) instead of adding more "
    'keywords. Reply with strict JSON: {"query": str, "desired_source_type": '
    'str, "sufficient": bool, "reason": str}. Set sufficient=true only when '
    "the existing evidence already answers the claim."
)

SELECTOR_SYSTEM_PROMPT = (
    "You are a bounded search-result selector. Given the claim, the evidence "
    "so far and the candidate search results, choose which pages to open. "
    'Reply with strict JSON: {"urls": [str], "reason": str}. Copy the '
    "candidate URLs exactly as given - no rewrites, no invented URLs. Choose "
    "between 1 and the given maximum number of pages whenever any candidate "
    "plausibly concerns the claim; only return an empty list when no candidate "
    "is even plausibly related. Prefer the page that would directly state the "
    "missing fact (official or primary sources first)."
)


def _parse_planner(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, Mapping):
        raise ValueError("planner response must be an object")
    return {
        "query": str(raw.get("query") or ""),
        "desired_source_type": str(raw.get("desired_source_type") or "")[:200],
        "sufficient": bool(raw.get("sufficient")),
        "reason": str(raw.get("reason") or "")[:400],
    }


def _parse_selector(raw: Any) -> list[str]:
    if not isinstance(raw, Mapping):
        raise ValueError("selector response must be an object")
    urls = raw.get("urls")
    if not isinstance(urls, list):
        raise ValueError("selector response needs a urls list")
    return [str(item) for item in urls]


def build_adapters(
    *,
    model_timeout_seconds: float = 30.0,
) -> tuple[
    SearcherFn,
    ReaderFn,
    PlannerFn,
    SelectorFn,
    ExtractFn,
    Callable[[], None],
    Callable[[], list[dict]],
]:
    """Wire the prototype to the same provider/reader/extractor production uses."""

    from src.web.research.active_adapter import ActiveResearchGateway
    from src.web.research.active_semantics import RuntimeEvidenceExtractor
    from src.web.research.contracts import (
        EvidenceRequirement,
        ResearchClaim,
    )
    from src.web.research.model_gateway import ResearchModelGateway

    gateway = ActiveResearchGateway()
    model = ResearchModelGateway(model_profile="flash", timeout_seconds=model_timeout_seconds)
    extractor = RuntimeEvidenceExtractor(model)
    state: dict[str, Any] = {"claim": None}
    diagnostics: list[dict] = []

    def _record_model_call(purpose: str, logical_call_id: str, result: Any) -> None:
        diagnostics.append(
            {
                "purpose": purpose,
                "logical_call_id": logical_call_id,
                "status": str(getattr(result, "status", "")),
                "reason": str(getattr(result, "reason", "") or "")[:300],
                "attempts": len(getattr(result, "audits", ()) or ()),
            }
        )

    def claim_for(question: str) -> Any:
        claim = state.get("claim")
        if claim is None or claim.text != question:
            claim = ResearchClaim(
                id="claim_agent_loop",
                question_id="question_agent_loop",
                text=question[:2000],
                kind="factual",
                priority="critical",
                state="pending",
                evidence_requirement=EvidenceRequirement(requires_successful_read=True),
                created_by="agent_loop_prototype",
                created_reason="§38 diagnostic controller",
            )
            state["claim"] = claim
        return claim

    def search_fn(query: str, max_items: int) -> Mapping[str, Any]:
        return gateway.search_detailed(query, max_items=max_items)

    def read_fn(url: str, max_chars: int) -> Mapping[str, Any]:
        return dict(gateway.read(url, max_chars=max_chars) or {})

    def planner_fn(loop_state: Mapping[str, Any]) -> Mapping[str, Any]:
        question = str(loop_state.get("question") or "")
        payload = {
            "question": question,
            "evidence": list(loop_state.get("evidence") or []),
            "previous_queries": list(loop_state.get("previous_queries") or []),
            "observed_results": list(loop_state.get("results") or []),
            "remaining_searches": loop_state.get("remaining_searches"),
            "remaining_reads": loop_state.get("remaining_reads"),
        }
        logical_call_id = (
            f"agent_loop_planner:{loop_state.get('case_id')}:{loop_state.get('step')}"
        )
        result = model.complete_structured(
            logical_call_id=logical_call_id,
            purpose="agent_loop_planner",
            messages=[
                {"role": "system", "content": PLANNER_SYSTEM_PROMPT},
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
            ],
            audit_payload=payload,
            response_schema_version="agent-loop-planner-v1",
            parse=_parse_planner,
            data_categories=("public_research_claim", "public_candidate_metadata"),
            max_tokens=400,
        )
        if getattr(result, "status", "") != "completed" or result.value is None:
            _record_model_call("planner", logical_call_id, result)
            return {"query": "", "sufficient": False}
        _record_model_call("planner", logical_call_id, result)
        return result.value

    def selector_fn(
        loop_state: Mapping[str, Any],
        candidates: tuple[dict, ...],
        max_urls: int,
    ) -> list[str]:
        payload = {
            "question": str(loop_state.get("question") or ""),
            "evidence": list(loop_state.get("evidence") or []),
            "queries_tried": list(loop_state.get("queries") or []),
            "max_urls": max_urls,
            "candidates": [
                {
                    "url": entry["canonical_url"],
                    "title": entry["title"],
                    "snippet": entry["snippet"],
                }
                for entry in candidates
            ],
        }
        logical_call_id = (
            f"agent_loop_selector:{loop_state.get('case_id')}:{loop_state.get('step')}"
        )
        result = model.complete_structured(
            logical_call_id=logical_call_id,
            purpose="agent_loop_selector",
            messages=[
                {"role": "system", "content": SELECTOR_SYSTEM_PROMPT},
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
            ],
            audit_payload=payload,
            response_schema_version="agent-loop-selector-v1",
            parse=_parse_selector,
            data_categories=("public_research_claim", "public_candidate_metadata"),
            max_tokens=400,
        )
        _record_model_call("selector", logical_call_id, result)
        if getattr(result, "status", "") != "completed" or result.value is None:
            return []
        return list(result.value)[:max_urls]

    def extract_fn(
        question: str, entry: Mapping[str, Any], content: str
    ) -> Mapping[str, Any]:
        from src.web.research.candidate_pool import CandidatePoolItem

        canonical_url = str(entry.get("canonical_url") or "")
        claim = claim_for(question)
        item = CandidatePoolItem(
            id=canonical_url,
            canonical_url=canonical_url,
            url=canonical_url,
            title=str(entry.get("title") or canonical_url)[:300],
            snippet="",
            source="agent_loop_prototype",
            published_at="",
            query_ids=(),
            intents=(),
            providers=(),
            first_seen_rank=0,
        )
        result = extractor.extract(
            run_id="agent_loop_prototype",
            claim=claim,
            candidate=item,
            source_role="primary",
            source_cluster_id="agent_loop_cluster",
            content=content,
            timeout_seconds=model_timeout_seconds,
        )
        if result.status != "completed" or result.extraction is None:
            return {"relation": "unavailable", "caveat": result.reason or "extractor_unavailable"}
        link = result.extraction
        return {"relation": link.relation, "caveat": "; ".join(link.caveats or ())}

    def close() -> None:
        return None

    def drain_diagnostics() -> list[dict]:
        items = list(diagnostics)
        diagnostics.clear()
        return items

    return (
        search_fn,
        read_fn,
        planner_fn,
        selector_fn,
        extract_fn,
        close,
        drain_diagnostics,
    )


def _load_cases(manifest_path: Path, case_ids: Iterable[str]) -> list[dict[str, str]]:
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    rows = payload.get("cases")
    if not isinstance(rows, list):
        raise ValueError("holdout manifest must contain a cases list")
    by_id = {
        str(row.get("id")): row
        for row in rows
        if isinstance(row, Mapping) and row.get("id")
    }
    selected: list[dict[str, str]] = []
    for case_id in case_ids:
        row = by_id.get(case_id)
        if row is None:
            raise ValueError(f"case is not in the manifest: {case_id}")
        selected.append({
            "id": case_id,
            "category": str(row.get("category") or ""),
            "question": str(row.get("question") or ""),
        })
    if not selected:
        raise ValueError("no case selected")
    return selected


DEFAULT_MANIFEST = (
    REPO_ROOT
    / "tests"
    / "fixtures"
    / "research_quality"
    / "rq1c_bounded_holdout_manifest.json"
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument(
        "--cases",
        default="rq1c-historical-current-node-modules",
        help="comma separated case ids",
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--max-searches", type=int, default=DEFAULT_MAX_SEARCHES)
    parser.add_argument("--max-reads", type=int, default=DEFAULT_MAX_READS)
    parser.add_argument("--case-timeout", type=float, default=60.0)
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    args = _parser().parse_args(list(argv) if argv is not None else None)
    load_dotenv(REPO_ROOT / ".env")
    case_ids = [item.strip() for item in args.cases.split(",") if item.strip()]
    cases = _load_cases(args.manifest, case_ids)
    budget = LoopBudget(
        max_searches=max(1, args.max_searches),
        max_reads=max(0, args.max_reads),
        case_timeout_seconds=max(5.0, args.case_timeout),
    )
    (
        search_fn,
        read_fn,
        planner_fn,
        selector_fn,
        extract_fn,
        close,
        drain_diagnostics,
    ) = build_adapters()
    artifact: dict[str, Any] = {
        "schema_version": PROTOTYPE_SCHEMA_VERSION,
        "diagnostic_only": True,
        "qualification_evidence": False,
        "git_sha": _git_sha(),
        "started_at": datetime.now(timezone.utc).isoformat(),
        "limits": {
            "max_searches": budget.max_searches,
            "max_reads": budget.max_reads,
            "results_per_query": budget.results_per_query,
            "read_chars": budget.read_chars,
            "case_timeout_seconds": budget.case_timeout_seconds,
        },
        "provider_profile": os.getenv("LLM_PROVIDER_PROFILE") or "openai",
        "model_profile": "flash",
        "model_name": _resolved_model_name(),
        "thinking_mode": "disabled_for_structured_research_calls",
        "assumptions": {
            "source_role": "primary_for_every_selector_chosen_page",
            "source_cluster_id": "single_constant_cluster",
            "claim": "one factual claim per case (the case question)",
            "note": "prototype simplification; do not compare relation semantics "
            "against the production assessment-assigned roles",
        },
        "cases": [],
        "summary": {},
    }
    try:
        for case in cases:
            print(f"[agent-loop] {case['id']} ...", flush=True)
            outcome = run_loop(
                case_id=case["id"],
                question=case["question"],
                budget=budget,
                search_fn=search_fn,
                read_fn=read_fn,
                planner_fn=planner_fn,
                selector_fn=selector_fn,
                extract_fn=extract_fn,
            )
            record = outcome.to_dict()
            record["category"] = case["category"]
            record["model_calls"] = drain_diagnostics()
            artifact["cases"].append(record)
            print(
                f"[agent-loop] {case['id']}: searches={record['searches']} "
                f"reads={record['reads']} supports={record['supports']} "
                f"stop={record['stop_reason']} elapsed={record['elapsed_seconds']}s",
                flush=True,
            )
    finally:
        close()
    artifact["completed_at"] = datetime.now(timezone.utc).isoformat()
    total_supports = sum(case["supports"] for case in artifact["cases"])
    artifact["summary"] = {
        "case_count": len(artifact["cases"]),
        "supports_cases": sum(1 for case in artifact["cases"] if case["supports"] > 0),
        "supports_total": total_supports,
        "searches_total": sum(case["searches"] for case in artifact["cases"]),
        "reads_total": sum(case["reads"] for case in artifact["cases"]),
        "budget_violation_cases": sum(
            1 for case in artifact["cases"] if case["budget_violations"]
        ),
        "total_elapsed_seconds": round(
            sum(case["elapsed_seconds"] for case in artifact["cases"]), 3
        ),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(artifact, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    print(json.dumps(artifact["summary"], ensure_ascii=False, sort_keys=True))
    return 0


def _git_sha() -> str:
    import subprocess

    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    except Exception:
        return ""


def _resolved_model_name() -> str:
    """The exact model id the flash profile resolves to (methodology lock)."""

    try:
        from src.llm_client import get_model_name

        return get_model_name("flash")
    except Exception:
        return ""


if __name__ == "__main__":
    raise SystemExit(main())
