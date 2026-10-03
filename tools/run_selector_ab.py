"""§43B paired A/B: legacy window vs production-contract hybrid selector.

Same frozen candidate pool, same K=2, same model, two arms:

    A = deterministic legacy window (the rules that ran in production)
    B = production-contract hybrid: one model call; usable -> model picks;
        otherwise the legacy window on the SAME original pool

Pools are *target-containing*: the Node case uses the agreed annotated
likely-targets; the other cases get their known authoritative target page
injected at the end of the frozen pool (clearly labelled `injected`, testing
whether selection can recover a buried target - not a recall claim).

Reports per pool: legacy/hybrid target hits, the arm that decided (model vs
fallback), the target read for the selected arm, selector calls, and the
wins/ties/losses classification. Diagnostic-only.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from dotenv import load_dotenv  # noqa: E402

from src.web.research.selection_authority import (  # noqa: E402
    MODEL_SELECTION_INPUT_MAX,
    select_candidates_with_model,
)
from tools.run_selector_replay import (  # noqa: E402
    DEFAULT_ANNOTATIONS,
    DEFAULT_PROBE,
    agreed_targets,
    build_pool,
    load_probe_cases,
)

SCHEMA_VERSION = "selector-ab-v1"
WINDOW_CAP = 2

# Known authoritative target pages, injected when the frozen pool for the case
# never recalled them (labelled `injected`; never a recall claim).
INJECTED_TARGETS: dict[str, dict[str, str]] = {
    "rq1c-current-policy-container-registry": {
        "url": "https://docs.docker.com/docker-hub/usage/pulls/",
        "title": "Pull usage and limits | Docker Docs",
        "snippet": "Rate limits for unauthenticated and authenticated pull requests.",
    },
    "rq1c-current-support-postgresql": {
        "url": "https://www.postgresql.org/support/versioning/",
        "title": "PostgreSQL: Versioning Policy",
        "snippet": "Official versioning and support policy for PostgreSQL releases.",
    },
    "rq1c-simple-license-uv": {
        "url": "https://github.com/astral-sh/uv/blob/main/LICENSE-MIT",
        "title": "uv LICENSE-MIT at main - astral-sh/uv",
        "snippet": "MIT License text in the official uv repository.",
    },
}


@dataclass
class PoolResult:
    case_id: str
    pool_source: str
    pool_size: int
    targets: list[str] = field(default_factory=list)
    legacy_picks: list[str] = field(default_factory=list)
    hybrid_picks: list[str] = field(default_factory=list)
    hybrid_source: str = ""
    hybrid_reason: str = ""
    legacy_hit: bool = False
    hybrid_hit: bool = False
    target_read_legacy: str = ""
    target_read_hybrid: str = ""
    selector_calls: int = 0
    outcome: str = ""
    pool_class: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "pool_source": self.pool_source,
            "pool_class": self.pool_class,
            "pool_size": self.pool_size,
            "targets": list(self.targets),
            "legacy_picks": list(self.legacy_picks),
            "hybrid_picks": list(self.hybrid_picks),
            "hybrid_source": self.hybrid_source,
            "hybrid_reason": self.hybrid_reason,
            "legacy_hit": self.legacy_hit,
            "hybrid_hit": self.hybrid_hit,
            "replacement_loss": self.outcome == "loss",
            "target_read_legacy": self.target_read_legacy,
            "target_read_hybrid": self.target_read_hybrid,
            "selector_calls": self.selector_calls,
            "outcome": self.outcome,
        }


def build_items(pool: Sequence[Mapping[str, str]]):
    """CandidatePoolItem rows in pool order (the runtime's own shape)."""

    from src.web.research.candidate_pool import CandidatePoolItem

    items = []
    for rank, entry in enumerate(pool):
        url = str(entry.get("url") or "")
        items.append(
            CandidatePoolItem(
                id=f"candidate_{rank}",
                canonical_url=url,
                url=url,
                title=str(entry.get("title") or url)[:300],
                snippet=str(entry.get("snippet") or ""),
                source="selector_ab",
                published_at="",
                query_ids=("q1",),
                intents=(),
                providers=(),
                first_seen_rank=rank,
            )
        )
    return tuple(items)


def legacy_window(items: Sequence[Any]):
    from src.application.active_research_runtime import _bounded_assessment_candidates
    from src.web.research.scheduler import is_schedulable_candidate  # noqa: F401
    from src.web.research.source_cluster import cluster_candidate_sources

    clusters = cluster_candidate_sources(tuple(items))
    assignments = {entry.candidate_id: entry for entry in clusters.assignments}
    del is_schedulable_candidate
    return _bounded_assessment_candidates(
        tuple(items),
        assignments=assignments,
        max_reads=WINDOW_CAP,
        excluded_candidate_ids=frozenset(),
    ), assignments


def classify(legacy_hit: bool, hybrid_hit: bool) -> str:
    if hybrid_hit and not legacy_hit:
        return "win"
    if legacy_hit and not hybrid_hit:
        return "loss"
    return "tie"


def run_ab(
    *,
    probe_path: Path | None = None,
    annotations_path: Path | None = None,
    pools_file: Path | None = None,
    output_path: Path,
    read_targets: bool,
    selector_caller: Callable[..., tuple[Sequence[Any], Any]] | None = None,
    reader: Callable[[str], Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    load_dotenv(REPO_ROOT / ".env")
    caller = selector_caller or _live_selector()
    read_fn = reader or _live_reader()
    entries: list[dict[str, Any]] = []
    if pools_file is not None:
        raw_entries = json.loads(pools_file.read_text(encoding="utf-8"))
        rows = raw_entries.get("pools") if isinstance(raw_entries, Mapping) else raw_entries
        for row in rows if isinstance(rows, list) else []:
            if not isinstance(row, Mapping):
                continue
            entries.append(
                {
                    "case_id": str(row.get("case_id") or ""),
                    "question": str(row.get("question") or ""),
                    "pool": [
                        dict(item)
                        for item in row.get("pool") or []
                        if isinstance(item, Mapping)
                    ],
                    "targets": [str(item) for item in row.get("targets") or []],
                    "pool_source": str(row.get("pool_source") or "natural"),
                }
            )
    else:
        if probe_path is None or annotations_path is None:
            raise ValueError("run_ab needs either --pools-file or probe + annotations")
        probe = json.loads(probe_path.read_text(encoding="utf-8"))
        annotations = json.loads(annotations_path.read_text(encoding="utf-8"))
        for case in load_probe_cases(probe):
            case_id = str(case.get("case_id") or "")
            pool = build_pool(case)
            injected = INJECTED_TARGETS.get(case_id)
            targets = agreed_targets(annotations, case_id)
            pool_source = "annotated"
            if injected and not targets:
                pool.append(dict(injected))
                targets = [str(injected["url"])]
                pool_source = "injected"
            entries.append(
                {
                    "case_id": case_id,
                    "question": str(case.get("question") or ""),
                    "pool": pool,
                    "targets": targets,
                    "pool_source": pool_source,
                }
            )
    results: list[PoolResult] = []
    for entry in entries:
        targets = entry["targets"]
        if not targets or not entry["pool"]:
            continue
        result = PoolResult(
            case_id=entry["case_id"],
            pool_source=entry["pool_source"],
            pool_size=len(entry["pool"]),
            targets=targets,
        )
        items = build_items(entry["pool"])
        legacy_items, assignments = legacy_window(items)
        result.legacy_picks = [item.canonical_url for item in legacy_items]
        result.legacy_hit = any(url in result.legacy_picks for url in targets)

        picks, diagnostics = caller(
            items,
            claim_text=entry["question"],
            assignments=assignments,
            max_picks=WINDOW_CAP,
        )
        result.selector_calls = 1
        result.hybrid_source = str(getattr(diagnostics, "selection_source", ""))
        result.hybrid_reason = str(getattr(diagnostics, "unusable_reason", ""))
        result.hybrid_picks = [item.canonical_url for item in picks]
        result.hybrid_hit = any(url in result.hybrid_picks for url in targets)
        result.outcome = classify(result.legacy_hit, result.hybrid_hit)
        result.pool_class = "B_preservation" if result.legacy_hit else "A_recovery"

        if read_targets:
            for arm, picked in (("legacy", result.legacy_picks), ("hybrid", result.hybrid_picks)):
                target = next((url for url in targets if url in picked), "")
                if not target:
                    continue
                raw = read_fn(target) or {}
                content = str(raw.get("content") or "")
                status = "ok" if (raw.get("ok") is True and content.strip()) else "failed"
                if arm == "legacy":
                    result.target_read_legacy = status
                else:
                    result.target_read_hybrid = status
        results.append(result)

    wins = sum(1 for row in results if row.outcome == "win")
    losses = sum(1 for row in results if row.outcome == "loss")
    ties = sum(1 for row in results if row.outcome == "tie")
    legacy_hits = sum(1 for row in results if row.legacy_hit)
    hybrid_hits = sum(1 for row in results if row.hybrid_hit)
    total = len(results)
    artifact = {
        "schema_version": SCHEMA_VERSION,
        "diagnostic_only": True,
        "qualification_evidence": False,
        "source_probe": str(probe_path).replace("\\", "/"),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "pools": [row.to_dict() for row in results],
        "summary": {
            "pools": total,
            "pool_classes": {
                "A_recovery": sum(1 for row in results if row.pool_class == "A_recovery"),
                "B_preservation": sum(
                    1 for row in results if row.pool_class == "B_preservation"
                ),
            },
            "conditional_target_selection_rate_legacy": (
                round(legacy_hits / total, 3) if total else None
            ),
            "conditional_target_selection_rate_hybrid": (
                round(hybrid_hits / total, 3) if total else None
            ),
            "legacy_target_hits": legacy_hits,
            "hybrid_target_hits": hybrid_hits,
            "wins": wins,
            "ties": ties,
            "losses": losses,
            "replacement_losses": losses,
            "selector_caused_losses": losses,
            "orchestration_model_calls": total,
            "incremental_target_reads": hybrid_hits - legacy_hits,
            "incremental_target_reads_per_selector_call": (
                round((hybrid_hits - legacy_hits) / total, 3) if total else None
            ),
        },
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(artifact, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return artifact


def _live_selector() -> Callable[..., tuple[Sequence[Any], Any]]:
    from src.application.active_research_runtime import _bounded_assessment_candidates
    from src.web.research.model_gateway import ResearchModelGateway

    gateway = ResearchModelGateway(model_profile="flash", timeout_seconds=30.0)

    def caller(items, *, claim_text, assignments, max_picks):
        unread = tuple(items)[:MODEL_SELECTION_INPUT_MAX]
        picks, diagnostics = select_candidates_with_model(
            model_gateway=gateway,
            claim_text=claim_text,
            candidates=unread,
            max_picks=max_picks,
            timeout_seconds=30.0,
            logical_call_id="selector_ab:1",
            model_name="deepseek-flash",
        )
        if diagnostics.usable and picks:
            picked = set(picks)
            ordered = tuple(item for item in unread if item.canonical_url in picked)
            diagnostics.selection_source = "model"
            diagnostics.final_picks = [item.canonical_url for item in ordered]
            return ordered, diagnostics
        fallback = _bounded_assessment_candidates(
            tuple(items),
            assignments=assignments,
            max_reads=max_picks,
            excluded_candidate_ids=frozenset(),
        )
        diagnostics.selection_source = "legacy_fallback"
        diagnostics.fallback_invoked = True
        diagnostics.fallback_picks = [item.canonical_url for item in fallback]
        diagnostics.final_picks = list(diagnostics.fallback_picks)
        return fallback, diagnostics

    return caller


def _live_reader() -> Callable[[str], Mapping[str, Any]]:
    from src.web.research.active_adapter import ActiveResearchGateway

    gateway = ActiveResearchGateway()

    def read(url: str) -> Mapping[str, Any]:
        return dict(gateway.read(url, max_chars=6000) or {})

    return read


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--probe", type=Path, default=DEFAULT_PROBE)
    parser.add_argument("--annotations", type=Path, default=DEFAULT_ANNOTATIONS)
    parser.add_argument("--pools-file", type=Path, default=None)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--no-read", action="store_true", help="skip target reads")
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    args = _parser().parse_args(list(argv) if argv is not None else None)
    artifact = run_ab(
        probe_path=None if args.pools_file else args.probe.resolve(),
        annotations_path=None if args.pools_file else args.annotations.resolve(),
        pools_file=args.pools_file.resolve() if args.pools_file else None,
        output_path=args.output.resolve(),
        read_targets=not args.no_read,
    )
    print(json.dumps(artifact["summary"], ensure_ascii=False, sort_keys=True))
    for row in artifact["pools"]:
        print(
            f"{row['case_id']} [{row['pool_source']}/{row['pool_class']}] "
            f"legacy={row['legacy_hit']} hybrid={row['hybrid_hit']} "
            f"source={row['hybrid_source']}{('/' + row['hybrid_reason']) if row['hybrid_reason'] else ''} "
            f"read L/H={row['target_read_legacy'] or '-'}/{row['target_read_hybrid'] or '-'}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
