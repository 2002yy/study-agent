"""Support Formation Audit: why do real runs produce ``relation="lead"``?

PROJECT_STATUS §34.5 defines the current RQ1-C blocker as research-side: real runs
mostly end with lead relations instead of supports, and the next cut depends on
which of two very different causes dominates:

* A. ``lead_because_page_lacks_fact`` - the page really does not contain the
  fact, so the extractor is right and the problem is discovery depth
  (lead -> deeper page);
* B. ``false_lead`` - the page body does contain the fact but the extractor
  still returned lead, which would be an extractor/support-classification
  problem.

This tool does not decide that for you. It assembles the audit table from *real*
evidence:

* verdicts come from stored qualification artifacts (the extractor's own
  relation / strength / locator / anchored spans / caveats per eligible row);
* page bodies are re-fetched with the production reader (bounded), because
  artifacts deliberately never store page bodies;
* deterministic hints are computed (do the recorded anchors/locator/numbers
  actually appear in the fetched page?), but ``human_classification`` is left
  empty for a human to fill in - the tool must not pretend to judge semantics.

Method note: a re-fetched page may differ from the page read during the original
run (freshness drift), so hints are evidence for review, not proof. Every
artifact is diagnostic-only.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections.abc import Iterable, Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from dotenv import load_dotenv  # noqa: E402

from src.web.tool_gateway import GeneralWebGateway  # noqa: E402

SCHEMA_VERSION = "rq1c-support-formation-audit-v1"
DEFAULT_ARTIFACTS = (
    "docs/research_quality/RQ1C_BOUNDED_QUALIFICATION_RUNTIME.4d1ed67.json",
    "docs/research_quality/RQ1C_BOUNDED_QUALIFICATION_RUNTIME.7b6f4aa.json",
    "docs/research_quality/RQ1C_BOUNDED_QUALIFICATION_RUNTIME.fd4295e.json",
)
MAX_EXCERPT_CHARS = 1200
_NUMBER_RE = re.compile(r"\d+(?:[.,]\d+)?")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_audit_rows(artifact_path: Path) -> list[dict[str, Any]]:
    """Extract one audit row per stored eligible-evidence row."""

    data = json.loads(artifact_path.read_text(encoding="utf-8"))
    cases = data.get("cases")
    if not isinstance(cases, list):
        raise ValueError("artifact must contain a cases list")
    rows: list[dict[str, Any]] = []
    for case in cases:
        if not isinstance(case, Mapping):
            continue
        brief_raw = case.get("brief")
        brief: Mapping[str, Any] = brief_raw if isinstance(brief_raw, Mapping) else {}
        eligible_raw = brief.get("eligible_evidence")
        eligible: list[Any] = eligible_raw if isinstance(eligible_raw, list) else []
        for row in eligible:
            if not isinstance(row, Mapping):
                continue
            rows.append(
                {
                    "case_id": case.get("case_id"),
                    "gate_status": (case.get("gate") or {}).get("status"),
                    "claim_id": row.get("claim_id"),
                    "url": row.get("url"),
                    "relation": row.get("relation"),
                    "strength": row.get("strength"),
                    "locator": row.get("locator"),
                    "anchored_spans": [
                        str(item) for item in (row.get("anchored_spans") or [])
                    ],
                    "caveats": [str(item) for item in (row.get("caveats") or [])],
                    "source_role": row.get("source_role"),
                    "title": row.get("title"),
                }
            )
    return rows


def _excerpt(text: str, anchors: Iterable[str]) -> str:
    """Bounded excerpt centred on the first anchor hit (else the head)."""

    for anchor in anchors:
        clean = str(anchor).strip()
        if len(clean) < 8:
            continue
        index = text.find(clean)
        if index >= 0:
            start = max(0, index - MAX_EXCERPT_CHARS // 3)
            return text[start : start + MAX_EXCERPT_CHARS]
    return text[:MAX_EXCERPT_CHARS]


def anchor_hints(row: Mapping[str, Any], content: str) -> dict[str, Any]:
    """Deterministic hints: do the recorded anchors actually appear in the page?"""

    folded = content.casefold()
    anchors = [str(item) for item in (row.get("anchored_spans") or [])]
    hit_anchors = [item for item in anchors if item.strip() and item.casefold() in folded]
    locator = str(row.get("locator") or "").strip()
    locator_hit = bool(locator) and len(locator) >= 8 and locator.casefold() in folded
    numbers = sorted({number for anchor in anchors for number in _NUMBER_RE.findall(anchor)})
    missing_numbers = [number for number in numbers if number not in content]
    return {
        "anchor_count": len(anchors),
        "anchor_hits": len(hit_anchors),
        "locator_hit": locator_hit,
        "anchor_numbers": numbers,
        "anchor_numbers_missing_from_page": missing_numbers,
        # A hint only. The decision needs a human: an ancestor page can contain
        # the fact without containing the exact recorded anchors.
        "hint": (
            "page_contains_recorded_anchors"
            if hit_anchors or locator_hit
            else "recorded_anchors_absent_from_page"
        ),
    }


def audit(
    *,
    artifact_paths: Iterable[Path],
    output_path: Path,
    max_rows: int,
    fetch: bool = True,
) -> dict[str, Any]:
    load_dotenv(REPO_ROOT / ".env")
    gateway = GeneralWebGateway()
    rows: list[dict[str, Any]] = []
    for artifact_path in artifact_paths:
        if not artifact_path.exists():
            continue
        for row in load_audit_rows(artifact_path):
            row["artifact"] = artifact_path.name
            rows.append(row)
    rows = rows[:max_rows]

    cache: dict[str, dict[str, Any]] = {}
    for row in rows:
        url = str(row.get("url") or "")
        row["human_classification"] = ""
        row["hints"] = {}
        if not fetch or not url:
            continue
        if url not in cache:
            entry: dict[str, Any] = {"fetched_at": _utc_now()}
            try:
                result = dict(gateway.read(url, max_chars=6000, timeout=10) or {})
                content = str(result.get("content") or result.get("readme") or "")
                entry.update(
                    {
                        "ok": bool(result.get("ok") is True),
                        "content_chars": len(content),
                        "content_sha256": hashlib.sha256(
                            content.encode("utf-8")
                        ).hexdigest()[:16],
                        "content": content,
                    }
                )
            except Exception as exc:
                entry.update(
                    {
                        "ok": False,
                        "content_chars": 0,
                        "content": "",
                        "error_type": type(exc).__name__,
                    }
                )
            cache[url] = entry
        entry = cache[url]
        row["page_fetch"] = {
            "ok": entry.get("ok"),
            "content_chars": entry.get("content_chars"),
            "content_sha256": entry.get("content_sha256"),
            "error_type": entry.get("error_type", ""),
            "fetched_at": entry.get("fetched_at"),
        }
        content = str(entry.get("content") or "")
        row["hints"] = anchor_hints(row, content)
        row["page_excerpt"] = _excerpt(content, row.get("anchored_spans") or [])
        del row["page_fetch"]["fetched_at"]

    relation_counts: dict[str, int] = {}
    for row in rows:
        key = str(row.get("relation") or "unknown")
        relation_counts[key] = relation_counts.get(key, 0) + 1

    artifact: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "diagnostic_only": True,
        "qualification_evidence": False,
        "generated_at": _utc_now(),
        "source_artifacts": [path.name for path in artifact_paths],
        "method_note": (
            "verdicts are the stored extractor output; page bodies are re-fetched "
            "with the production reader and may have changed since the original "
            "run; human_classification must be filled by a human reviewer with "
            "lead_because_page_lacks_fact or false_lead"
        ),
        "row_count": len(rows),
        "relation_counts": relation_counts,
        "rows": rows,
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(artifact, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return artifact


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--artifact",
        type=Path,
        action="append",
        default=None,
        help="stored qualification artifact (repeatable)",
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--max-rows", type=int, default=40)
    parser.add_argument(
        "--no-fetch",
        action="store_true",
        help="skip page re-fetch (verdicts only, no hints/excerpts)",
    )
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    args = _parser().parse_args(list(argv) if argv is not None else None)
    artifacts = (
        [path for path in args.artifact]
        if args.artifact
        else [Path(item) for item in DEFAULT_ARTIFACTS]
    )
    artifact = audit(
        artifact_paths=artifacts,
        output_path=args.output.resolve(),
        max_rows=max(1, args.max_rows),
        fetch=not args.no_fetch,
    )
    print(
        json.dumps(
            {
                "row_count": artifact["row_count"],
                "relation_counts": artifact["relation_counts"],
                "output": str(args.output.resolve()),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
