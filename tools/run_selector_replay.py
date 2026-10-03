"""§38b selector replay: rule window vs model selector on frozen discovery data.

Completely offline A/B on the §37A artifact (95 queries / 475 provider results,
already frozen and annotated). For every case it rebuilds the exact candidate
pool the runtime observed, takes the rule selection that actually happened
(`selected_for_read`), asks the flash selector for its own top-K from the same
pool, and compares both against the agreed likely targets.

This isolates the one architectural question §37B raised: if the *selection*
decision is given to a small model - everything else frozen - does the target
that the rule window drops get picked up?

Diagnostic-only; no production path is touched and no search/read is executed.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from dotenv import load_dotenv  # noqa: E402

from src.news.url_normalizer import canonicalize_url  # noqa: E402
from tools.run_agent_loop_prototype import (  # noqa: E402
    SELECTOR_SYSTEM_PROMPT,
    _parse_selector,
)

SCHEMA_VERSION = "selector-replay-v1"
DEFAULT_PROBE = REPO_ROOT / "docs" / "research_quality" / "SEARCH_DISCOVERY_PROBE.json"
DEFAULT_ANNOTATIONS = REPO_ROOT / "docs" / "research_quality" / "ANNOTATIONS_MERGED.json"
MAX_POOL = 40


@dataclass
class ReplayCase:
    case_id: str
    question: str
    pool: list[dict] = field(default_factory=list)
    rule_picks: list[str] = field(default_factory=list)
    rule_reasons: dict[str, str] = field(default_factory=dict)
    targets: list[str] = field(default_factory=list)
    model_picks: list[str] = field(default_factory=list)
    model_picks_runs: list[list[str]] = field(default_factory=list)
    model_calls_runs: list[dict] = field(default_factory=list)
    model_error: str = ""

    def model_hits(self) -> int:
        return sum(
            1
            for picks in self.model_picks_runs
            if any(target in picks for target in self.targets)
        )

    def model_empties(self) -> int:
        return sum(1 for picks in self.model_picks_runs if not picks)

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "question": self.question,
            "pool_size": len(self.pool),
            "rule_picks": list(self.rule_picks),
            "rule_reasons": dict(self.rule_reasons),
            "targets": list(self.targets),
            "rule_target_hits": [t for t in self.targets if t in self.rule_picks],
            "model_picks": list(self.model_picks),
            "model_picks_runs": [list(picks) for picks in self.model_picks_runs],
            "model_calls_runs": [dict(call) for call in self.model_calls_runs],
            "model_hit_runs": self.model_hits(),
            "model_empty_runs": self.model_empties(),
            "model_runs": len(self.model_picks_runs),
            "model_target_hits": [t for t in self.targets if t in self.model_picks],
            "model_target_rank": (
                self.model_picks.index(self.targets[0]) + 1
                if self.targets and self.targets[0] in self.model_picks
                else None
            ),
            "model_error": self.model_error,
            "pool_head": [
                {"url": entry["url"], "title": entry["title"][:120]}
                for entry in self.pool[:12]
            ],
        }


def load_probe_cases(probe: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    cases = probe.get("cases")
    return [case for case in cases if isinstance(case, Mapping)] if isinstance(cases, list) else []


def build_pool(case: Mapping[str, Any]) -> list[dict]:
    """Deduplicated candidate pool in first-observation order (bounded)."""

    metrics = case.get("metrics")
    metrics = metrics if isinstance(metrics, Mapping) else {}
    discovery = metrics.get("search_discovery")
    discovery = discovery if isinstance(discovery, Mapping) else {}
    pool: list[dict] = []
    seen: set[str] = set()
    for query in discovery.get("queries") or []:
        if not isinstance(query, Mapping):
            continue
        for raw in query.get("results") or []:
            if not isinstance(raw, Mapping):
                continue
            canonical = canonicalize_url(str(raw.get("url") or ""))
            if not canonical or canonical in seen:
                continue
            seen.add(canonical)
            pool.append(
                {
                    "url": canonical,
                    "title": " ".join(str(raw.get("title") or "").split())[:300],
                    "snippet": " ".join(str(raw.get("snippet") or "").split())[:400],
                }
            )
            if len(pool) >= MAX_POOL:
                return pool
    return pool


def rule_selection(case: Mapping[str, Any]) -> tuple[list[str], dict[str, str]]:
    """The reads the frozen run actually performed.

    The §37A probe's per-result ``selected_for_read`` flags are placeholders
    (all false); the run's real read set is the ``sources`` list with
    ``read_status == "read"``. Per-result flags are only used as a fallback
    when no sources were recorded, so the baseline column stays honest.
    """

    picks: list[str] = []
    reasons: dict[str, str] = {}
    sources = case.get("sources")
    if isinstance(sources, list) and sources:
        for source in sources:
            if not isinstance(source, Mapping):
                continue
            if str(source.get("read_status")) != "read":
                continue
            canonical = canonicalize_url(str(source.get("url") or ""))
            if canonical and canonical not in reasons:
                picks.append(canonical)
                reasons[canonical] = f"source_role:{source.get('source_role') or 'unknown'}"
        return picks, reasons

    metrics = case.get("metrics")
    metrics = metrics if isinstance(metrics, Mapping) else {}
    discovery = metrics.get("search_discovery")
    discovery = discovery if isinstance(discovery, Mapping) else {}
    for query in discovery.get("queries") or []:
        if not isinstance(query, Mapping):
            continue
        for raw in query.get("results") or []:
            if not isinstance(raw, Mapping):
                continue
            canonical = canonicalize_url(str(raw.get("url") or ""))
            if not canonical or canonical in reasons:
                continue
            if bool(raw.get("selected_for_read")) or str(raw.get("read_status")) == "read":
                picks.append(canonical)
                reasons[canonical] = str(raw.get("selection_reason") or "")
    return picks, reasons


def agreed_targets(annotations: Mapping[str, Any], case_id: str) -> list[str]:
    rows = annotations.get("merged")
    if not isinstance(rows, list):
        rows = annotations.get("annotations")
    targets: list[str] = []
    for item in rows if isinstance(rows, list) else []:
        if not isinstance(item, Mapping) or str(item.get("case_id")) != case_id:
            continue
        label = str(item.get("candidate_classification") or "")
        if not label:
            pass_a = str(item.get("pass_a") or "")
            pass_b = str(item.get("pass_b") or "")
            label = pass_a if pass_a and pass_a == pass_b else ""
        if label != "likely_target":
            continue
        url = canonicalize_url(str(item.get("canonical_url") or ""))
        if url and url not in targets:
            targets.append(url)
    return targets


def replay(
    probe: Mapping[str, Any],
    annotations: Mapping[str, Any],
    *,
    selector: Any,
    max_picks: int = 2,
    repeat: int = 1,
) -> list[ReplayCase]:
    """Run the model selector over every frozen case (selector is injectable)."""

    results: list[ReplayCase] = []
    for case in load_probe_cases(probe):
        case_id = str(case.get("case_id") or "")
        question = str(case.get("question") or "")
        replay_case = ReplayCase(case_id=case_id, question=question)
        replay_case.pool = build_pool(case)
        replay_case.rule_picks, replay_case.rule_reasons = rule_selection(case)
        replay_case.targets = agreed_targets(annotations, case_id)
        if replay_case.pool:
            for _ in range(max(1, repeat)):
                try:
                    picks = list(selector(question, replay_case.pool, max_picks))[:max_picks]
                    replay_case.model_picks_runs.append(picks)
                    call_record = getattr(selector, "last_call", None)
                    if isinstance(call_record, dict):
                        replay_case.model_calls_runs.append(dict(call_record))
                    if not replay_case.model_picks:
                        replay_case.model_picks = list(picks)
                except Exception as exc:  # model failures stay visible, never fatal
                    replay_case.model_error = f"{type(exc).__name__}: {exc}"[:300]
                    replay_case.model_picks_runs.append([])
        results.append(replay_case)
    return results


def _load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _resolved_model_name() -> str:
    """The exact model id the flash profile resolves to (methodology lock)."""

    try:
        from src.llm_client import get_model_name

        return get_model_name("flash")
    except Exception:
        return ""

def _model_selector(max_calls: int = 60) -> Any:
    from src.web.research.model_gateway import ResearchModelGateway

    model = ResearchModelGateway(model_profile="flash", timeout_seconds=30.0)
    calls = {"count": 0, "statuses": {}}

    def selector(question: str, pool: list[dict], max_picks: int) -> list[str]:
        if calls["count"] >= max_calls:
            return []
        calls["count"] += 1
        payload = {
            "question": question,
            "max_urls": max_picks,
            "candidates": pool,
        }
        result = model.complete_structured(
            logical_call_id=f"selector_replay:{calls['count']}",
            purpose="selector_replay",
            messages=[
                {"role": "system", "content": SELECTOR_SYSTEM_PROMPT},
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
            ],
            audit_payload=payload,
            response_schema_version="selector-replay-v1",
            parse=_parse_selector,
            data_categories=("public_research_claim", "public_candidate_metadata"),
            max_tokens=500,
        )
        status = str(getattr(result, "status", ""))
        reason = str(getattr(result, "reason", "") or "")
        key = f"{status}:{reason}" if reason else status
        calls["statuses"][key] = calls["statuses"].get(key, 0) + 1
        raw_urls = (
            list(result.value)
            if getattr(result, "status", "") == "completed" and result.value is not None
            else []
        )
        selector.last_call = {  # type: ignore[attr-defined]
            "status": status,
            "reason": reason,
            "output_count": len(raw_urls),
            "empty_output": len(raw_urls) == 0,
        }
        if status != "completed" or result.value is None:
            return []
        pool_urls = {entry["url"] for entry in pool}
        picks: list[str] = []
        for item in list(result.value):
            canonical = canonicalize_url(str(item))
            if canonical and canonical in pool_urls and canonical not in picks:
                picks.append(canonical)
            if len(picks) >= max_picks:
                break
        return picks

    selector.status_counts = lambda: dict(calls["statuses"])  # type: ignore[attr-defined]
    return selector


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--probe", type=Path, default=DEFAULT_PROBE)
    parser.add_argument("--annotations", type=Path, default=DEFAULT_ANNOTATIONS)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--max-picks", type=int, default=2)
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument(
        "--cases",
        default="",
        help="optional comma separated case-id filter",
    )
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    args = _parser().parse_args(list(argv) if argv is not None else None)
    load_dotenv(REPO_ROOT / ".env")
    probe = _load(args.probe)
    annotations = _load(args.annotations)
    wanted = {item.strip() for item in args.cases.split(",") if item.strip()}
    if wanted and isinstance(probe, dict):
        probe = {
            **probe,
            "cases": [
                case
                for case in probe.get("cases") or []
                if str(case.get("case_id")) in wanted
            ],
        }
    selector = _model_selector(max_calls=40 * max(1, args.repeat))
    cases = replay(
        probe,
        annotations,
        selector=selector,
        max_picks=args.max_picks,
        repeat=max(1, args.repeat),
    )
    artifact = {
        "schema_version": SCHEMA_VERSION,
        "diagnostic_only": True,
        "qualification_evidence": False,
        "source_probe": str(args.probe).replace("\\", "/"),
        "annotations": str(args.annotations).replace("\\", "/"),
        "max_picks": args.max_picks,
        "repeat": max(1, args.repeat),
        "provider_profile": (os.getenv("LLM_PROVIDER_PROFILE") or "openai"),
        "model_profile": "flash",
        "model_name": _resolved_model_name(),
        "thinking_mode": "disabled_for_structured_research_calls",
        "model_status_counts": (
            selector.status_counts() if hasattr(selector, "status_counts") else {}
        ),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "cases": [case.to_dict() for case in cases],
        "summary": {
            "cases": len(cases),
            "cases_with_targets": sum(1 for case in cases if case.targets),
            "rule_target_hits": sum(
                1 for case in cases if any(t in case.rule_picks for t in case.targets)
            ),
            "model_target_hit_runs": sum(case.model_hits() for case in cases),
            "model_runs_total": sum(len(case.model_picks_runs) for case in cases),
            "model_empty_runs": sum(case.model_empties() for case in cases),
            "model_errors": sum(1 for case in cases if case.model_error),
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(artifact, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    print(json.dumps(artifact["summary"], ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
