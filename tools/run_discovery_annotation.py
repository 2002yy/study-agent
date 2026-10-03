"""§37A.2 model-assisted blind annotation for search-discovery candidates.

The observation system (§37A/§37A.1) produced 75 unique candidates across 12
cases. They must be classified before any provider-recall experiment, and the
classification must not be produced by the same code that produced the
extractor verdicts - nor may it masquerade as human review.

Therefore:

* tasks carry ONLY ``claim / page_intent / url / title / snippet``. No relation,
  no caveat, no read state, no answer text, and no known-correct URLs: the
  annotator must not be anchored by downstream outcomes;
* annotations are emitted as ``reviewer_type = opencode`` with an explicit
  ``reviewer_model`` and a ``pass`` label. The ``human_*`` fields stay empty;
* two passes (A, B) are produced independently, with the candidate order
  shuffled per pass, and the merge step reports exact agreement plus the
  disagreements that a human should adjudicate;
* presence (``target_fact_present_after_read``) is only asked for candidates
  that were actually read, and only with bounded fetched text; a page that was
  never read stays ``unobserved``.

Nothing here changes search, ranking, budgets, eligibility or the Gate.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import sys
from collections.abc import Iterable, Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from dotenv import load_dotenv  # noqa: E402

from src.web.research.discovery_observability import (  # noqa: E402
    STATE_TRUE,
    canonical_for_audit,
)
from src.web.tool_gateway import GeneralWebGateway  # noqa: E402

SCHEMA_VERSION = "rq1c-discovery-annotation-v1"
CLASSIFICATION_LABELS = ("likely_target", "near_hit", "irrelevant", "unknown")
PRESENCE_LABELS = ("true", "false", "unobserved")
_MAX_EXCERPT = 3000
PASS_SEEDS = {"A": 11, "B": 29}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def build_classification_tasks(
    audit_artifact: Path,
    *,
    pass_label: str,
) -> dict[str, Any]:
    """Blind pass-1 tasks: claim + page intent + url/title/snippet only."""

    data = _load(audit_artifact)
    cases_raw = data.get("search_discovery") or []
    seed = PASS_SEEDS.get(pass_label, 0)
    tasks: list[dict[str, Any]] = []
    for case in cases_raw:
        if not isinstance(case, Mapping):
            continue
        candidates = [item for item in (case.get("unique_candidates") or []) if isinstance(item, Mapping)]
        order = list(range(len(candidates)))
        random.Random(seed + len(case.get("case_id") or "")).shuffle(order)
        ordered = [candidates[index] for index in order]
        intent_kind = ""
        for query in case.get("queries") or []:
            if isinstance(query, Mapping):
                intent = query.get("page_intent")
                if isinstance(intent, Mapping) and intent.get("kind"):
                    intent_kind = str(intent["kind"])
                    break
        tasks.append(
            {
                "case_id": case.get("case_id"),
                "claim": case.get("claim") or "",
                "page_intent": intent_kind,
                "candidates": [
                    {
                        "canonical_url": candidate.get("canonical_url"),
                        # Blind payload: only what a search result shows.
                        "url": candidate.get("url"),
                        "title": candidate.get("title"),
                        "snippet": candidate.get("snippet"),
                    }
                    for candidate in ordered
                ],
            }
        )
    return {
        "schema_version": SCHEMA_VERSION,
        "mode": "classification",
        "pass": pass_label,
        "blind": True,
        "forbidden_inputs": [
            "extractor relation",
            "caveats",
            "read state",
            "answer text",
            "known-correct URLs",
            "authority class",
        ],
        "generated_at": _utc_now(),
        "case_count": len(tasks),
        "candidate_count": sum(len(item["candidates"]) for item in tasks),
        "tasks": tasks,
    }


def build_presence_tasks(
    audit_artifact: Path,
    *,
    pass_label: str,
    fetch: bool = True,
) -> dict[str, Any]:
    """Pass-2 tasks: only candidates that were actually read, with bounded text."""

    data = _load(audit_artifact)
    gateway = GeneralWebGateway()
    cases: list[dict[str, Any]] = []
    cache: dict[str, dict[str, Any]] = {}
    for case in data.get("search_discovery") or []:
        if not isinstance(case, Mapping):
            continue
        read_candidates = [
            item
            for item in (case.get("unique_candidates") or [])
            if isinstance(item, Mapping)
            and str(item.get("selected_for_read")) == STATE_TRUE
        ]
        if not read_candidates:
            continue
        rows: list[dict[str, Any]] = []
        for candidate in read_candidates:
            url = str(candidate.get("url") or "")
            entry: dict[str, Any] = {}
            if fetch and url:
                if url not in cache:
                    try:
                        result = dict(gateway.read(url, max_chars=_MAX_EXCERPT, timeout=15) or {})
                        content = str(result.get("content") or result.get("readme") or "")
                        cache[url] = {
                            "ok": bool(result.get("ok") is True),
                            "content_chars": len(content),
                            "content_sha256": hashlib.sha256(
                                content.encode("utf-8")
                            ).hexdigest()[:16],
                            "excerpt": content[:_MAX_EXCERPT],
                        }
                    except Exception as exc:
                        cache[url] = {
                            "ok": False,
                            "content_chars": 0,
                            "content_sha256": "",
                            "excerpt": "",
                            "error_type": type(exc).__name__,
                        }
                entry = cache[url]
            rows.append(
                {
                    "canonical_url": candidate.get("canonical_url"),
                    "url": url,
                    "title": candidate.get("title"),
                    "read_status": candidate.get("read_status"),
                    "excerpt_chars": entry.get("content_chars", 0),
                    "excerpt_sha256": entry.get("content_sha256", ""),
                    # Freshness caveat: re-fetched, not the original read bytes.
                    "excerpt": entry.get("excerpt", ""),
                }
            )
        cases.append(
            {
                "case_id": case.get("case_id"),
                "claim": case.get("claim") or "",
                "read_candidates": rows,
            }
        )
    return {
        "schema_version": SCHEMA_VERSION,
        "mode": "presence",
        "pass": pass_label,
        "blind": True,
        "note": (
            "excerpts are re-fetched with the production reader and are not the "
            "original read bytes; judge presence only from the excerpt"
        ),
        "generated_at": _utc_now(),
        "case_count": len(cases),
        "candidate_count": sum(len(item["read_candidates"]) for item in cases),
        "cases": cases,
    }


def validate_annotations(
    payload: Mapping[str, Any],
    *,
    expected_pass: str | None = None,
) -> list[dict[str, Any]]:
    """Return validated annotation rows, failing closed on contract violations."""

    if str(payload.get("reviewer_type") or "") != "opencode":
        raise ValueError("annotations must declare reviewer_type=opencode")
    if not str(payload.get("reviewer_model") or "").strip():
        raise ValueError("annotations must declare reviewer_model")
    if expected_pass is not None and str(payload.get("pass") or "") != expected_pass:
        raise ValueError(f"annotations must be for pass {expected_pass}")
    rows: list[dict[str, Any]] = []
    for row in payload.get("annotations") or []:
        if not isinstance(row, Mapping):
            continue
        label = str(row.get("candidate_classification") or "").strip()
        if label not in CLASSIFICATION_LABELS:
            raise ValueError(f"invalid candidate_classification: {label!r}")
        presence = str(row.get("target_fact_present_after_read") or "unobserved").strip()
        if presence not in PRESENCE_LABELS:
            raise ValueError(f"invalid target_fact_present_after_read: {presence!r}")
        rows.append(
            {
                "case_id": str(row.get("case_id") or ""),
                "canonical_url": canonical_for_audit(str(row.get("canonical_url") or "")),
                "candidate_classification": label,
                "target_fact_present_after_read": presence,
                "confidence": str(row.get("confidence") or ""),
                "reason": str(row.get("reason") or "")[:400],
                "reviewer_type": "opencode",
                "reviewer_model": str(payload.get("reviewer_model") or ""),
                "pass": str(payload.get("pass") or ""),
            }
        )
    return rows


def merge_passes(
    pass_a: Mapping[str, Any],
    pass_b: Mapping[str, Any],
) -> dict[str, Any]:
    """Exact agreement between two independent passes + disagreement list."""

    rows_a = {(row["case_id"], row["canonical_url"]): row for row in validate_annotations(pass_a, expected_pass="A")}
    rows_b = {(row["case_id"], row["canonical_url"]): row for row in validate_annotations(pass_b, expected_pass="B")}
    keys = sorted(set(rows_a) | set(rows_b))
    classification_agreement = 0
    presence_agreement = 0
    disagreements: list[dict[str, Any]] = []
    for key in keys:
        left, right = rows_a.get(key), rows_b.get(key)
        if left is None or right is None:
            disagreements.append(
                {"case_id": key[0], "canonical_url": key[1], "reason": "missing_in_one_pass"}
            )
            continue
        same_classification = (
            left["candidate_classification"] == right["candidate_classification"]
        )
        same_presence = (
            left["target_fact_present_after_read"]
            == right["target_fact_present_after_read"]
        )
        classification_agreement += int(same_classification)
        presence_agreement += int(same_presence)
        if not same_classification or not same_presence:
            disagreements.append(
                {
                    "case_id": key[0],
                    "canonical_url": key[1],
                    "pass_a": left["candidate_classification"],
                    "pass_b": right["candidate_classification"],
                    "presence_a": left["target_fact_present_after_read"],
                    "presence_b": right["target_fact_present_after_read"],
                    "reason": "classification_or_presence_disagreement",
                }
            )
    total = len(keys)
    return {
        "schema_version": SCHEMA_VERSION,
        "mode": "merge",
        "candidate_count": total,
        "classification_exact_agreement": round(classification_agreement / total, 4) if total else None,
        "presence_exact_agreement": round(presence_agreement / total, 4) if total else None,
        "likely_target_disagreements": [
            item
            for item in disagreements
            if "likely_target"
            in {str(item.get("pass_a")), str(item.get("pass_b"))}
        ],
        "disagreements": disagreements,
        "merged": [
            {
                "case_id": key[0],
                "canonical_url": key[1],
                "pass_a": rows_a[key]["candidate_classification"] if key in rows_a else None,
                "pass_b": rows_b[key]["candidate_classification"] if key in rows_b else None,
                "presence_a": rows_a[key]["target_fact_present_after_read"] if key in rows_a else None,
                "presence_b": rows_b[key]["target_fact_present_after_read"] if key in rows_b else None,
            }
            for key in keys
        ],
        "generated_at": _utc_now(),
        "reviewer_note": (
            "model-assisted annotation: rates derived from this merge are model_* "
            "rates, never human_* rates"
        ),
    }


def _agreed_label(row: Mapping[str, Any]) -> str | None:
    left = str(row.get("pass_a") or "")
    right = str(row.get("pass_b") or "")
    return left if left and left == right else None


def summarize_model_rates(
    merged: Mapping[str, Any],
    audit_artifact: Path | None,
) -> dict[str, Any]:
    """The four-number funnel from agreed model annotations (+ extractor stage)."""

    rows = [item for item in (merged.get("merged") or []) if isinstance(item, Mapping)]
    by_case: dict[str, list[Mapping[str, Any]]] = {}
    for row in rows:
        by_case.setdefault(str(row.get("case_id")), []).append(row)

    states: dict[tuple[str, str], dict[str, Any]] = {}
    relations: dict[tuple[str, str], str] = {}
    if audit_artifact is not None and audit_artifact.exists():
        data = _load(audit_artifact)
        for case in data.get("search_discovery") or []:
            if not isinstance(case, Mapping):
                continue
            case_id = str(case.get("case_id"))
            for candidate in case.get("unique_candidates") or []:
                if not isinstance(candidate, Mapping):
                    continue
                key = (case_id, canonical_for_audit(str(candidate.get("canonical_url") or "")))
                states[key] = {
                    "read": str(candidate.get("selected_for_read")) == STATE_TRUE,
                    "harvest": str(candidate.get("selected_for_harvest")),
                    "relation": str(candidate.get("final_relation") or ""),
                }
                relations[key] = str(candidate.get("final_relation") or "")

    cases_with_candidate = 0
    cases_with_read = 0
    cases_with_fact = 0
    cases_with_supports = 0
    for case_id, case_rows in by_case.items():
        likely = [
            row
            for row in case_rows
            if _agreed_label(row) == "likely_target"
        ]
        if not likely:
            continue
        cases_with_candidate += 1
        # Read state comes from the observation system, never from the presence
        # label: an unread candidate keeps presence "unobserved".
        read_likely = [
            row
            for row in likely
            if states.get(
                (case_id, str(row.get("canonical_url"))), {}
            ).get("read")
        ]
        if read_likely:
            cases_with_read += 1
            present = any(
                str(row.get("presence_a")) == "true"
                and str(row.get("presence_b")) == "true"
                for row in read_likely
            )
            if present:
                cases_with_fact += 1
            if any(
                relations.get((case_id, str(row.get("canonical_url")))) == "supports"
                for row in read_likely
            ):
                cases_with_supports += 1

    def _rate(numerator: int, denominator: int) -> float | None:
        return round(numerator / denominator, 4) if denominator else None

    return {
        "reviewer_type": "opencode",
        "cases_total": len(by_case),
        "cases_with_likely_target": cases_with_candidate,
        "model_target_fact_candidate_rate": _rate(cases_with_candidate, len(by_case)),
        "model_likely_target_read_rate": _rate(cases_with_read, cases_with_candidate),
        "model_target_fact_present_rate": _rate(cases_with_fact, cases_with_read),
        "model_extractor_capture_rate": _rate(cases_with_supports, cases_with_fact),
        "target_fact_harvest_rate": "unobserved",
        "note": (
            "model-assisted rates from agreed pass A/B labels; they are not "
            "human_* rates and harvest stays unobserved"
        ),
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("classification", "presence", "merge", "rates"), required=True)
    parser.add_argument("--audit", type=Path, required=True)
    parser.add_argument("--pass-label", default="A")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--pass-a", type=Path)
    parser.add_argument("--pass-b", type=Path)
    parser.add_argument("--no-fetch", action="store_true")
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    args = _parser().parse_args(list(argv) if argv is not None else None)
    load_dotenv(REPO_ROOT / ".env")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    if args.mode == "classification":
        payload = build_classification_tasks(args.audit, pass_label=args.pass_label)
    elif args.mode == "presence":
        payload = build_presence_tasks(
            args.audit, pass_label=args.pass_label, fetch=not args.no_fetch
        )
    elif args.mode == "merge":
        if args.pass_a is None or args.pass_b is None:
            raise SystemExit("--pass-a and --pass-b are required for merge")
        payload = merge_passes(_load(args.pass_a), _load(args.pass_b))
    else:
        if args.pass_a is None or args.pass_b is None:
            raise SystemExit("--pass-a and --pass-b are required for rates")
        merged = merge_passes(_load(args.pass_a), _load(args.pass_b))
        payload = summarize_model_rates(merged, args.audit)
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    summary = {
        key: payload.get(key)
        for key in (
            "mode",
            "pass",
            "case_count",
            "candidate_count",
            "classification_exact_agreement",
            "presence_exact_agreement",
            "model_target_fact_candidate_rate",
            "model_likely_target_read_rate",
            "model_target_fact_present_rate",
            "model_extractor_capture_rate",
        )
        if key in payload
    }
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
