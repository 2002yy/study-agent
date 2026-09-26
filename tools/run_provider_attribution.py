"""§44B provider attribution audit: where does the known target page die?

Splits the production stack into its parts for the §44A positive controls:

    query -> {searxng, bing_rss, duckduckgo_html} raw top20
          -> production round-robin merge (limit 10 / 5)
          -> attribution per target:
             provider_returned / raw_rank / post_merge_rank / survived_topk /
             drop_reason / official deep-page counts before vs after merge

Also probes the SearXNG locale question directly: the production leg is built
with ``language=zh-CN``; the same query is repeated with ``language=en`` to see
whether the official deep page comes back (branch D of the frozen decision
tree).

Diagnostic-only; nothing about production ranking changes.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from dotenv import load_dotenv  # noqa: E402

from tools.run_recall_target_audit import TARGETS  # noqa: E402

SCHEMA_VERSION = "provider-attribution-audit-v1"
PROVIDERS = ("searxng", "bing_rss", "duckduckgo_html")
RAW_LIMIT = 20
MERGE_LIMIT_WIDE = 10
MERGE_LIMIT_PRODUCTION = 5


def _domain(url: str) -> str:
    match = re.match(r"https?://([^/]+)", str(url or ""))
    return (match.group(1) if match else "").lower()


def _path_depth(url: str) -> int:
    match = re.match(r"https?://[^/]+(/.*)?$", str(url or ""))
    path = (match.group(1) if match and match.group(1) else "/").strip("/")
    if not path:
        return 0
    return len([part for part in path.split("/") if part])


def _has_cjk(text: str) -> bool:
    return bool(re.search(r"[\u4e00-\u9fff]", str(text or "")))


def _rank_of(url: str, results: Sequence[Mapping[str, Any]]) -> int | None:
    normalized = url.rstrip("/")
    for index, row in enumerate(results, start=1):
        if str(row.get("url") or "").rstrip("/") == normalized:
            return index
    return None


def drop_reason(
    *, provider_hit: bool, merged_hit: bool, topk_hit: bool
) -> str:
    if not provider_hit:
        return "provider_miss"
    if not merged_hit:
        return "merge_cap_or_dedupe"
    if not topk_hit:
        return "topk_boundary"
    return "survived"


def decide_branch(
    *, any_raw: bool, merged_wide: bool, merged_top5: bool, locale_hit: bool
) -> str:
    """Frozen §44B decision tree (locale branch outranks capability miss)."""

    if merged_top5:
        return "mechanism_ok"
    if merged_wide:
        return "C_ranking_topk_defect"
    if locale_hit:
        return "D_regionalization_defect"
    if any_raw:
        return "B_aggregation_defect"
    return "A_provider_capability_insufficiency"


@dataclass
class AttributionRow:
    case_id: str
    target: str
    query_class: str
    query: str
    provider_ranks: dict[str, int | None] = field(default_factory=dict)
    merged_rank_wide: int | None = None
    merged_rank_top5: int | None = None
    official_deep_before: int = 0
    official_deep_after: int = 0
    searxng_en_hit: bool = False
    searxng_en_rank: int | None = None
    result_languages: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        any_raw = any(rank is not None for rank in self.provider_ranks.values())
        merged_wide = self.merged_rank_wide is not None
        top5 = self.merged_rank_top5 is not None
        return {
            "case_id": self.case_id,
            "target": self.target,
            "query_class": self.query_class,
            "query": self.query,
            "provider_ranks": self.provider_ranks,
            "merged_rank_top10": self.merged_rank_wide,
            "merged_rank_top5": self.merged_rank_top5,
            "drop_reason": drop_reason(
                provider_hit=any_raw, merged_hit=merged_wide, topk_hit=top5
            ),
            "official_deep_pages_before_merge": self.official_deep_before,
            "official_deep_pages_after_merge": self.official_deep_after,
            "searxng_en_hit": self.searxng_en_hit,
            "searxng_en_rank": self.searxng_en_rank,
            "result_language_cjk": self.result_languages.get("cjk", 0),
            "result_language_latin": self.result_languages.get("latin", 0),
            "branch": decide_branch(
                any_raw=any_raw,
                merged_wide=merged_wide,
                merged_top5=top5,
                locale_hit=self.searxng_en_hit,
            ),
        }


def _raw_provider_call(
    provider: str, query: str, limit: int, timeout: float
) -> list[Mapping[str, Any]]:
    from src.web.research.provider_search import _default_provider_call

    results, _error = _default_provider_call(provider, query, limit, timeout)
    return list(results)


def _searxng_language_variant(
    query: str, *, language: str, limit: int, timeout: float
) -> list[Mapping[str, Any]]:
    """Rebuild the searxng leg with an explicit language (diagnostic only)."""

    import urllib.request

    from src.news.search_sources.searxng_source import (
        _parse_searxng_results,
        build_searxng_search_url,
        searxng_base_url,
    )

    url = build_searxng_search_url(
        query,
        searxng_base_url(),
        max_results=limit,
        language=language,
        categories="general",
    )
    if not url:
        return []
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            payload = response.read()
        parsed = _parse_searxng_results(payload, limit)
    except Exception:
        return []
    return [
        {
            "title": str(item.title or ""),
            "url": str(getattr(item, "url", "") or ""),
            "snippet": str(getattr(item, "search_excerpt", "") or ""),
        }
        for item in parsed
    ]


def run_attribution(*, output_path: Path, timeout: float = 12.0) -> dict[str, Any]:
    from src.web.research.provider_search import _round_robin_merge

    load_dotenv(REPO_ROOT / ".env")
    rows: list[AttributionRow] = []
    for target in TARGETS:
        queries = (
            ("exact_title", target.exact_title),
            ("entity_title", f"{target.exact_title} {target.entity_terms[0]}"),
            ("semantic", target.semantic_query),
        )
        for label, query in queries:
            row = AttributionRow(
                case_id=target.case_id,
                target=target.url,
                query_class=label,
                query=query,
            )
            provider_results: dict[str, tuple[Mapping[str, Any], ...]] = {}
            for provider in PROVIDERS:
                results = _raw_provider_call(provider, query, RAW_LIMIT, timeout)
                provider_results[provider] = tuple(results)
                row.provider_ranks[provider] = _rank_of(target.url, results)
                target_domain = _domain(target.url)
                row.official_deep_before += sum(
                    1
                    for item in results
                    if _domain(str(item.get("url") or "")) == target_domain
                    and _path_depth(str(item.get("url") or "")) >= 1
                )
                for item in results:
                    text = f"{item.get('title')} {item.get('snippet')}"
                    if _has_cjk(text):
                        row.result_languages["cjk"] = (
                            row.result_languages.get("cjk", 0) + 1
                        )
                    else:
                        row.result_languages["latin"] = (
                            row.result_languages.get("latin", 0) + 1
                        )
                time.sleep(0.2)
            merged_wide = _round_robin_merge(
                dict(provider_results), PROVIDERS, limit=MERGE_LIMIT_WIDE
            )
            merged_top5 = _round_robin_merge(
                dict(provider_results), PROVIDERS, limit=MERGE_LIMIT_PRODUCTION
            )
            row.merged_rank_wide = _rank_of(target.url, merged_wide)
            row.merged_rank_top5 = _rank_of(target.url, merged_top5)
            target_domain = _domain(target.url)
            row.official_deep_after = sum(
                1
                for item in merged_wide
                if _domain(str(item.get("url") or "")) == target_domain
                and _path_depth(str(item.get("url") or "")) >= 1
            )
            english = _searxng_language_variant(
                query, language="en", limit=RAW_LIMIT, timeout=timeout
            )
            row.searxng_en_rank = _rank_of(target.url, english)
            row.searxng_en_hit = row.searxng_en_rank is not None
            rows.append(row)
            print(
                f"{target.case_id} [{label}] raw={row.provider_ranks} "
                f"wide={row.merged_rank_wide} top5={row.merged_rank_top5} "
                f"en={row.searxng_en_rank} -> {rows[-1].to_dict()['branch']}"
            )

    per_target: dict[str, dict[str, Any]] = {}
    for target in TARGETS:
        target_rows = [row for row in rows if row.target == target.url]
        per_target[target.case_id] = {
            "target": target.url,
            "branches": {
                row.query_class: row.to_dict()["branch"] for row in target_rows
            },
            "any_raw_hit": any(
                rank is not None
                for row in target_rows
                for rank in row.provider_ranks.values()
            ),
            "best_raw_rank": min(
                (
                    rank
                    for row in target_rows
                    for rank in row.provider_ranks.values()
                    if rank is not None
                ),
                default=None,
            ),
            "searxng_en_hit": any(row.searxng_en_hit for row in target_rows),
        }
    payload = {
        "schema_version": SCHEMA_VERSION,
        "diagnostic_only": True,
        "qualification_evidence": False,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "raw_limit": RAW_LIMIT,
        "providers": list(PROVIDERS),
        "searxng_language_note": (
            "production searxng leg is built with language=zh-CN; the en variant "
            "is diagnostic only"
        ),
        "rows": [row.to_dict() for row in rows],
        "per_target": per_target,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return payload


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--timeout", type=float, default=12.0)
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    args = _parser().parse_args(list(argv) if argv is not None else None)
    payload = run_attribution(output_path=args.output.resolve(), timeout=args.timeout)
    print(json.dumps(payload["per_target"], ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
