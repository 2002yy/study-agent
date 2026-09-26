"""§44A known-target recall audit: query adequacy vs provider retrieval.

Two modes, both read-only w.r.t. the production pipeline:

``audit``   walks historical artifacts, and for every query the runtime ever
            issued (per case) records, for each known target page:
              query_relevance            (mechanical keyword tier)
              provider_target_returned   (was the exact target URL in results)
              provider_same_domain_returned
              provider_near_page_returned (same domain and a target key term)
            so query adequacy and provider retrieval failure can be separated.

``probe``   positive controls against the live provider: three query classes
            per target (exact title / exact title + entity / natural semantic)
            with hit + rank, which decides between "provider surface" and
            "query compilation" as the recall bottleneck.

Diagnostic-only; no query, provider or pipeline changes.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from dotenv import load_dotenv  # noqa: E402

SCHEMA_VERSION = "known-target-recall-audit-v1"


@dataclass(frozen=True)
class TargetSpec:
    case_id: str
    url: str
    entity_terms: tuple[str, ...]
    page_terms: tuple[str, ...]
    exact_title: str
    semantic_query: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "url": self.url,
            "entity_terms": list(self.entity_terms),
            "page_terms": list(self.page_terms),
            "exact_title": self.exact_title,
            "semantic_query": self.semantic_query,
        }


TARGETS: tuple[TargetSpec, ...] = (
    TargetSpec(
        case_id="rq1c-current-policy-container-registry",
        url="https://docs.docker.com/docker-hub/usage/pulls/",
        entity_terms=("docker",),
        page_terms=("pull", "usage", "limits", "pulls"),
        exact_title="Pull usage and limits",
        semantic_query="Docker Hub pull rate limits",
    ),
    TargetSpec(
        case_id="rq1c-current-support-postgresql",
        url="https://www.postgresql.org/support/versioning/",
        entity_terms=("postgresql", "postgres"),
        page_terms=("versioning", "policy", "supported"),
        exact_title="PostgreSQL Versioning Policy",
        semantic_query="PostgreSQL supported versions policy",
    ),
    TargetSpec(
        case_id="rq1c-simple-license-uv",
        url="https://github.com/astral-sh/uv/blob/main/LICENSE-MIT",
        entity_terms=("uv", "astral"),
        page_terms=("license", "mit"),
        exact_title="uv LICENSE-MIT",
        semantic_query="uv open source license",
    ),
    TargetSpec(
        case_id="rq1c-historical-current-node-modules",
        url="https://nodejs.cn/api/modules.html",
        entity_terms=("node", "node.js", "nodejs"),
        page_terms=("modules", "commonjs", "ecmascript"),
        exact_title="Node.js two module systems",
        semantic_query="Node.js supported module systems",
    ),
)


def _tokens(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", str(text or "").lower()))


def _domain(url: str) -> str:
    match = re.match(r"https?://([^/]+)", str(url or ""))
    return (match.group(1) if match else "").lower()


def classify_query_relevance(query: str, target: TargetSpec) -> str:
    """Mechanical tiers: direct / plausible / weak / unrelated."""

    tokens = _tokens(query)
    entity_hits = sum(1 for term in target.entity_terms if term in tokens)
    page_hits = sum(
        1
        for term in target.page_terms
        if term in tokens or any(term in token for token in tokens)
    )
    if entity_hits >= 1 and page_hits >= 2:
        return "direct_targeting"
    if entity_hits >= 1 and page_hits == 1:
        return "plausible_targeting"
    if entity_hits >= 1 or page_hits >= 1:
        return "weak_targeting"
    return "unrelated"


def audit_case_queries(
    case: Mapping[str, Any], target: TargetSpec
) -> list[dict[str, Any]]:
    """One row per historical query for one target."""

    metrics = case.get("metrics")
    metrics = metrics if isinstance(metrics, Mapping) else {}
    discovery = metrics.get("search_discovery")
    discovery = discovery if isinstance(discovery, Mapping) else {}
    target_domain = _domain(target.url)
    rows: list[dict[str, Any]] = []
    for query in discovery.get("queries") or []:
        if not isinstance(query, Mapping):
            continue
        query_text = str(query.get("query_excerpt") or "")
        results = [row for row in query.get("results") or [] if isinstance(row, Mapping)]
        urls = [str(row.get("url") or "") for row in results]
        target_returned = any(url.rstrip("/") == target.url.rstrip("/") for url in urls)
        same_domain = [url for url in urls if target_domain and target_domain in _domain(url)]
        near_terms = set(target.page_terms)
        near_page = any(
            any(term in _tokens(url) for term in near_terms) for url in same_domain
        )
        rows.append(
            {
                "query": query_text[:200],
                "query_relevance": classify_query_relevance(query_text, target),
                "provider_target_returned": target_returned,
                "provider_same_domain_returned": bool(same_domain),
                "provider_near_page_returned": bool(near_page),
                "result_count": len(urls),
            }
        )
    return rows


def run_audit(
    *, artifacts: Sequence[Path], output_path: Path
) -> dict[str, Any]:
    targets_by_case: dict[str, list[TargetSpec]] = {}
    for target in TARGETS:
        targets_by_case.setdefault(target.case_id, []).append(target)
    rows: list[dict[str, Any]] = []
    seen_queries: set[tuple[str, str, str]] = set()
    for path in artifacts:
        if not path.exists():
            continue
        try:
            artifact = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        for case in artifact.get("cases") or []:
            if not isinstance(case, Mapping):
                continue
            case_id = str(case.get("case_id") or case.get("id") or "")
            for target in targets_by_case.get(case_id, ()):
                for row in audit_case_queries(case, target):
                    key = (case_id, target.url, row["query"])
                    if key in seen_queries:
                        continue
                    seen_queries.add(key)
                    rows.append({"case_id": case_id, "target": target.url, **row})
    summaries: dict[str, dict[str, Any]] = {}
    for target in TARGETS:
        target_rows = [row for row in rows if row["target"] == target.url]
        tiers: dict[str, int] = {}
        for row in target_rows:
            tiers[row["query_relevance"]] = tiers.get(row["query_relevance"], 0) + 1
        summaries[target.case_id] = {
            "target": target.url,
            "queries": len(target_rows),
            "query_relevance": dict(sorted(tiers.items())),
            "provider_target_returned": sum(
                1 for row in target_rows if row["provider_target_returned"]
            ),
            "provider_same_domain_returned": sum(
                1 for row in target_rows if row["provider_same_domain_returned"]
            ),
            "provider_near_page_returned": sum(
                1 for row in target_rows if row["provider_near_page_returned"]
            ),
        }
    payload = {
        "schema_version": SCHEMA_VERSION,
        "mode": "audit",
        "diagnostic_only": True,
        "qualification_evidence": False,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "targets": [target.to_dict() for target in TARGETS],
        "rows": rows,
        "summary": summaries,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return payload


def run_probe(*, output_path: Path, max_results: int = 5) -> dict[str, Any]:
    from src.web.research.active_adapter import ActiveResearchGateway

    load_dotenv(REPO_ROOT / ".env")
    gateway = ActiveResearchGateway()
    results: list[dict[str, Any]] = []
    for target in TARGETS:
        queries = (
            ("exact_title", target.exact_title),
            ("entity_title", f"{target.exact_title} {target.entity_terms[0]}"),
            ("semantic", target.semantic_query),
        )
        target_row: dict[str, Any] = {
            "case_id": target.case_id,
            "target": target.url,
            "probes": {},
        }
        for label, query in queries:
            payload = gateway.search_detailed(query, max_items=max_results)
            urls = [
                str(row.get("url") or "")
                for row in payload.get("results") or []
                if isinstance(row, Mapping)
            ]
            normalized_target = target.url.rstrip("/")
            rank = next(
                (
                    index + 1
                    for index, url in enumerate(urls)
                    if url.rstrip("/") == normalized_target
                ),
                None,
            )
            target_row["probes"][label] = {
                "query": query,
                "hit": rank is not None,
                "rank": rank,
                "result_count": len(urls),
                "top_urls": urls[:3],
                "providers": list(payload.get("providers_attempted") or []),
            }
            print(f"{target.case_id} [{label}] hit={rank is not None} rank={rank} :: {query}")
        results.append(target_row)
    summary = {
        target_row["case_id"]: {
            label: bool(probe["hit"])
            for label, probe in target_row["probes"].items()
        }
        for target_row in results
    }
    payload = {
        "schema_version": SCHEMA_VERSION,
        "mode": "probe",
        "diagnostic_only": True,
        "qualification_evidence": False,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "max_results": max_results,
        "targets": results,
        "summary": summary,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return payload


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=["audit", "probe"], required=True)
    parser.add_argument("--artifacts", type=Path, nargs="*", default=[])
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--max-results", type=int, default=5)
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    args = _parser().parse_args(list(argv) if argv is not None else None)
    if args.mode == "audit":
        payload = run_audit(artifacts=args.artifacts, output_path=args.output.resolve())
        print(json.dumps(payload["summary"], ensure_ascii=False, sort_keys=True))
        return 0
    payload = run_probe(output_path=args.output.resolve(), max_results=args.max_results)
    print(json.dumps(payload["summary"], ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
