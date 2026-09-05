"""Diagnose RQ1-C claim-planner failures on the untouched 12-case manifest.

This is diagnostic evidence, not qualification evidence. It exercises the same
planner prompt, strict response schema, token limit, semantic parser, and pinned
provider configuration as production, but records only bounded metadata and
failure classifications. Raw model text is never written to disk or stdout.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any, Mapping

from openai import OpenAI

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import src.web.research.claim_planner as claim_planner  # noqa: E402
from src.web.research.model_gateway import _strip_json_fence  # noqa: E402
from tools.rq1c_git_identity import exact_checkout_git_sha  # noqa: E402

MANIFEST_SCHEMA_VERSION = "rq1c-bounded-holdout-manifest-v1"
DIAGNOSTIC_SCHEMA_VERSION = "rq1c-planner-live12-diagnostic-v1"
DEFAULT_MANIFEST = (
    REPO_ROOT
    / "tests"
    / "fixtures"
    / "research_quality"
    / "rq1c_bounded_holdout_manifest.json"
)
DEFAULT_OUTPUT = REPO_ROOT / "output" / "rq1c-planner-live12-diagnostic.json"


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _optional_count(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 0 else None


def _usage_value(usage: Any, key: str) -> int | None:
    if usage is None:
        return None
    value = usage.get(key) if isinstance(usage, Mapping) else getattr(usage, key, None)
    return _optional_count(value)


def _load_manifest(path: Path) -> tuple[dict[str, str], ...]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or raw.get("schema_version") != MANIFEST_SCHEMA_VERSION:
        raise ValueError("unsupported RQ1-C manifest schema")
    records = raw.get("cases")
    if not isinstance(records, list) or len(records) != 12:
        raise ValueError("planner diagnostic requires exactly 12 holdout cases")
    result: list[dict[str, str]] = []
    seen: set[str] = set()
    for record in records:
        if not isinstance(record, dict):
            raise ValueError("invalid RQ1-C manifest case")
        case_id = str(record.get("id") or "").strip()
        category = str(record.get("category") or "").strip()
        question = str(record.get("question") or "").strip()
        if not case_id or case_id in seen or not category or not question:
            raise ValueError("invalid or duplicate RQ1-C manifest case")
        seen.add(case_id)
        result.append({"id": case_id, "category": category, "question": question})
    return tuple(result)


def classify_planner_failure(exc: BaseException) -> str:
    """Map exceptions to a stable diagnostic class without persisting messages."""

    error_type = type(exc).__name__
    message = str(exc).casefold()
    if error_type == "JSONDecodeError":
        return "json_decode"
    if "timeout" in error_type.casefold() or "timed out" in message:
        return "timeout"
    if "question anchor must be copied" in message:
        return "anchor_not_verbatim"
    if "question anchor must be non-empty" in message:
        return "anchor_empty"
    if "question anchor exceeds" in message:
        return "anchor_too_long"
    if "duplicate anchors" in message:
        return "duplicate_anchor"
    if "invalid claim kind" in message:
        return "invalid_kind"
    if "invalid evidence policy profile" in message:
        return "invalid_policy_profile"
    if "policy" in message and ("compatible" in message or "unsupported" in message):
        return "kind_policy_incompatible"
    if "fields do not match schema" in message or "must be an object" in message:
        return "semantic_schema"
    if error_type in {"BadRequestError", "UnprocessableEntityError"}:
        return "provider_schema_rejection"
    if error_type in {"APIConnectionError", "ConnectError", "ConnectionError"}:
        return "provider_connection"
    return f"other:{error_type}"[:120]


def _anchor_structure(decoded: Any, *, question: str) -> dict[str, Any]:
    """Describe anchor validity without exposing model-selected anchor text."""

    if not isinstance(decoded, Mapping):
        return {"claims": [], "critical_valid": False}
    critical = decoded.get("critical_claim")
    supporting = decoded.get("supporting_claims")
    raw_claims: list[tuple[str, Any]] = [("critical", critical)]
    if isinstance(supporting, list):
        raw_claims.extend((f"supporting:{index}", item) for index, item in enumerate(supporting))

    seen: set[str] = set()
    rows: list[dict[str, Any]] = []
    for role, raw in raw_claims:
        if not isinstance(raw, Mapping):
            rows.append(
                {
                    "role": role,
                    "object": False,
                    "anchor_length": None,
                    "anchor_sha256": "",
                    "verbatim": False,
                    "duplicate": False,
                }
            )
            continue
        anchor = " ".join(str(raw.get("question_anchor") or "").split())
        dedupe_key = " ".join(anchor.casefold().split())
        duplicate = bool(dedupe_key and dedupe_key in seen)
        if dedupe_key:
            seen.add(dedupe_key)
        rows.append(
            {
                "role": role,
                "object": True,
                "anchor_length": len(anchor),
                "anchor_sha256": _sha256(anchor) if anchor else "",
                "verbatim": bool(anchor and anchor in question),
                "duplicate": duplicate,
            }
        )
    critical_row = rows[0] if rows else {}
    return {
        "claims": rows,
        "critical_valid": bool(
            critical_row.get("object")
            and critical_row.get("verbatim")
            and not critical_row.get("duplicate")
        ),
        "supporting_count": max(0, len(rows) - 1),
        "invalid_verbatim_roles": [
            str(row["role"])
            for row in rows
            if row.get("object") and not row.get("verbatim")
        ],
        "duplicate_roles": [
            str(row["role"]) for row in rows if row.get("duplicate")
        ],
    }


def _planner_client() -> tuple[OpenAI, str]:
    base_url = (os.getenv("RESEARCH_CLAIM_PLANNER_BASE_URL") or "").strip()
    model_name = (os.getenv("RESEARCH_CLAIM_PLANNER_MODEL_NAME") or "").strip()
    api_key = (os.getenv("RESEARCH_CLAIM_PLANNER_API_KEY") or "").strip()
    if not base_url or not model_name or not api_key:
        raise RuntimeError("dedicated claim planner environment is incomplete")
    return OpenAI(api_key=api_key, base_url=base_url, max_retries=0), model_name


def _run_case(
    *,
    client: OpenAI,
    model_name: str,
    case: Mapping[str, str],
    reference_date: str,
    timeout_seconds: float,
) -> dict[str, Any]:
    payload = {
        "question": case["question"],
        "reference_date": reference_date,
        "freshness_requested": False,
        "freshness_days": None,
    }
    started = time.monotonic()
    finish_reason = ""
    input_tokens = output_tokens = total_tokens = None
    response_chars = 0
    response_sha256 = ""
    failure_kind = ""
    error_type = ""
    claim_count = 0
    status = "failed"
    structure: dict[str, Any] = {"claims": [], "critical_valid": False}
    try:
        response = client.chat.completions.create(
            model=model_name,
            messages=[
                {"role": "system", "content": claim_planner._CLAIM_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": claim_planner._claim_user_payload(payload),
                },
            ],
            temperature=0.0,
            max_tokens=claim_planner.CLAIM_PLANNER_MAX_TOKENS,
            response_format=claim_planner._CLAIM_PLAN_RESPONSE_FORMAT,
            timeout=timeout_seconds,
            stream=False,
        )
        raw = str(response.choices[0].message.content or "")
        response_chars = len(raw)
        response_sha256 = _sha256(raw)
        finish_reason = str(response.choices[0].finish_reason or "")[:80]
        usage = getattr(response, "usage", None)
        input_tokens = _usage_value(usage, "prompt_tokens")
        output_tokens = _usage_value(usage, "completion_tokens")
        total_tokens = _usage_value(usage, "total_tokens")
        decoded = json.loads(_strip_json_fence(raw))
        structure = _anchor_structure(decoded, question=case["question"])
        proposals = claim_planner._parse_claim_plan(decoded, question=case["question"])
        claim_count = len(proposals)
        status = "completed"
    except Exception as exc:  # diagnostic taxonomy, never raw text
        error_type = type(exc).__name__[:120]
        failure_kind = classify_planner_failure(exc)
    return {
        "case_id": case["id"],
        "category": case["category"],
        "status": status,
        "failure_kind": failure_kind,
        "error_type": error_type,
        "finish_reason": finish_reason,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": total_tokens,
        "response_chars": response_chars,
        "response_sha256": response_sha256,
        "claim_count": claim_count,
        "anchor_structure": structure,
        "elapsed_seconds": round(max(0.0, time.monotonic() - started), 6),
    }


def run_diagnostic(
    *,
    manifest_path: Path,
    output_path: Path,
    reference_date: str,
    timeout_seconds: float = 20.0,
) -> dict[str, Any]:
    git_sha = exact_checkout_git_sha(REPO_ROOT)
    cases = _load_manifest(manifest_path)
    client, model_name = _planner_client()
    records = [
        _run_case(
            client=client,
            model_name=model_name,
            case=case,
            reference_date=reference_date,
            timeout_seconds=timeout_seconds,
        )
        for case in cases
    ]
    failures = Counter(
        str(record["failure_kind"])
        for record in records
        if record["status"] != "completed"
    )
    artifact = {
        "schema_version": DIAGNOSTIC_SCHEMA_VERSION,
        "git_sha": git_sha,
        "manifest_sha256": _sha256(manifest_path.read_text(encoding="utf-8")),
        "reference_date": reference_date,
        "planner": {
            "model_name": model_name,
            "max_tokens": claim_planner.CLAIM_PLANNER_MAX_TOKENS,
            "timeout_seconds": timeout_seconds,
            "stores_raw_model_text": False,
        },
        "cases": records,
        "summary": {
            "case_count": len(records),
            "completed": sum(record["status"] == "completed" for record in records),
            "failed": sum(record["status"] != "completed" for record in records),
            "failure_kinds": dict(sorted(failures.items())),
        },
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(artifact, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return artifact


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--reference-date", default="2026-09-05")
    parser.add_argument("--timeout-seconds", type=float, default=20.0)
    return parser


def main() -> int:
    args = _parser().parse_args()
    artifact = run_diagnostic(
        manifest_path=args.manifest.resolve(),
        output_path=args.output.resolve(),
        reference_date=str(args.reference_date),
        timeout_seconds=max(1.0, min(float(args.timeout_seconds), 120.0)),
    )
    print(json.dumps(artifact["summary"], ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
