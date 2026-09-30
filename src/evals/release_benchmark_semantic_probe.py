"""Bounded, non-qualifying semantic probe for captured benchmark answers.

This cross-model check can expose unsupported answers or weak judge controls.
It never produces release metric labels or judge qualification.
"""

from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import re
from typing import Any, Callable, cast

from src.evals.release_benchmark_answer_pilot import build_answer_review_packet
from src.evals.release_benchmark_registry import ReleaseGold, ReleaseRegistry

SCHEMA = "release-benchmark-semantic-probe-v1"
_SHA = re.compile(r"[0-9a-f]{40}\Z")
_DIMENSIONS = {
    "question_coverage": {"covered", "partial", "unverified"},
    "evidence_grounding": {"supported", "gap", "unverified"},
    "citation_support": {"supported", "gap", "unverified"},
}
_ISSUES = {"coverage_gap", "unsupported_claim", "wrong_citation",
           "overstatement", "other"}
_CONTROLS = ("wrong_citation", "missing_aspect", "unsupported_claim")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _json_bytes(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True,
                       separators=(",", ":")) + "\n").encode("utf-8")


def _parse_assessment(raw: str, source_id: str) -> dict[str, object]:
    if not isinstance(raw, str) or not 1 <= len(raw) <= 12000:
        raise ValueError("semantic probe returned no bounded text")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError("semantic probe did not return JSON") from exc
    if not isinstance(data, dict) or set(data) != {*_DIMENSIONS, "issues"}:
        raise ValueError("semantic probe assessment shape mismatch")
    for name, allowed in _DIMENSIONS.items():
        if data[name] not in allowed:
            raise ValueError("semantic probe dimension is invalid")
    issues = data["issues"]
    if not isinstance(issues, list) or len(issues) > 8:
        raise ValueError("semantic probe issue list is invalid")
    for issue in issues:
        if not isinstance(issue, dict) or set(issue) != {
            "issue_type", "reason", "evidence_refs",
        } or issue["issue_type"] not in _ISSUES:
            raise ValueError("semantic probe issue shape mismatch")
        if (not isinstance(issue["reason"], str)
                or not 1 <= len(issue["reason"].strip()) <= 500
                or issue["evidence_refs"] not in ([], [source_id])):
            raise ValueError("semantic probe issue is not source-bound")
    return data


def _control_answer(case_id: str, answer: str, locator: str,
                    variant: str) -> str:
    if variant == "wrong_citation":
        if locator not in answer:
            raise ValueError("answer lacks registered citation")
        return answer.replace(locator, "https://invalid.example/unregistered", 1)
    if variant == "missing_aspect":
        return answer.splitlines()[0]
    if variant == "unsupported_claim":
        if case_id not in {"REL-F-TEXT-001", "REL-F-PDF-001"}:
            raise ValueError("unsupported semantic probe case")
        falsehood = (
            "The source says lunar gravity is the primary cause of storm surge."
            if case_id == "REL-F-TEXT-001" else
            "The source says the Moon does not rotate on its own axis."
        )
        return answer + f"\n{falsehood} [source]({locator})"
    raise ValueError("unknown semantic probe control")


def _review_messages(*, case: dict[str, Any], source_text: str,
                     answer: str, sample_id: str) -> list[dict[str, str]]:
    source = case["source"]
    payload = {
        "case_id": case["case_id"], "sample_id": sample_id,
        "question": case["question"], "aspects": case["aspects"],
        "aspect_rubric": case["aspect_rubric"],
        "source_id": source["source_id"],
        "source_locator": source["locator"],
        "source_page": source["page"], "source_region": source["region"],
        "source_text": source_text, "answer": answer,
    }
    return [
        {"role": "system", "content": (
            "Evaluate the answer against only the supplied frozen source and rubric. "
            "The sample ID is an opaque run label, not an answer key. Return JSON "
            "with exactly question_coverage (covered|partial|unverified), "
            "evidence_grounding (supported|gap|unverified), citation_support "
            "(supported|gap|unverified), and issues (array). Each issue has "
            "issue_type (coverage_gap|unsupported_claim|wrong_citation|"
            "overstatement|other), reason, and evidence_refs (empty array or "
            "the supplied source ID). Check every claim and citation. Compare "
            "each Markdown citation URL with source_locator exactly; for a PDF, "
            "only a matching #page=source_page suffix is permitted. An unrelated "
            "URL requires citation_support=gap and a wrong_citation issue. A "
            "source citation is not proof that the source supports the sentence. "
            "Any unsupported or contradicted factual sentence requires "
            "evidence_grounding=gap and an unsupported_claim issue. If an issue "
            "reports a coverage gap, question_coverage must be partial. Do not "
            "mark an axis supported when its issue reports a gap."
        )},
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False,
                                               sort_keys=True, separators=(",", ":"))},
    ]


def materialize_review_items(
    bundle: dict[str, object], registry: ReleaseRegistry, gold: ReleaseGold,
    root: Path,
) -> dict[str, object]:
    """Frozen review inputs per case: real answer plus the three controls.

    No model call and no scoring. Exposed so a blind reviewer packet can be
    built from exactly the material §161 calibrates against.
    """
    packet = build_answer_review_packet(bundle, registry, gold, root)
    cases = []
    answer_rows = cast(list[dict[str, Any]], bundle["cases"])
    packet_cases = cast(list[dict[str, Any]], packet["cases"])
    for answer_row, packet_case in zip(answer_rows, packet_cases, strict=True):
        source_text = answer_row["messages"][1]["content"].split("Source text:\n", 1)[1]
        locator = packet_case["source"]["locator"]
        cases.append({
            "case_id": packet_case["case_id"],
            "answer_model": answer_row["model"],
            "answer": answer_row["answer"],
            "answer_sha256": sha256(answer_row["answer"].encode("utf-8")).hexdigest(),
            "source_text": source_text,
            "packet_case": packet_case,
            "control_answers": {
                variant: _control_answer(packet_case["case_id"], answer_row["answer"],
                                         locator, variant)
                for variant in _CONTROLS
            },
        })
    return {
        "review_packet": packet,
        "answer_bundle_sha256": packet["answer_bundle_sha256"],
        "cases": cases,
    }


def run_semantic_probe(
    bundle: dict[str, object], registry: ReleaseRegistry, gold: ReleaseGold,
    root: Path, *, code_sha: str, reviewer_provider: str,
    reviewer_model: str, model_call: Callable[[list[dict[str, str]]], str],
) -> dict[str, object]:
    """Review actual answers and three controls per case, without scoring."""
    if (not _SHA.fullmatch(code_sha) or not reviewer_provider or not reviewer_model):
        raise ValueError("semantic probe needs exact code and model identity")
    materialized = materialize_review_items(bundle, registry, gold, root)
    packet = cast(dict[str, Any], materialized["review_packet"])
    cases = []
    started_at = _now()
    for item in cast(list[dict[str, Any]], materialized["cases"]):
        if reviewer_model == item["answer_model"]:
            raise ValueError("semantic probe reviewer must differ from answer model")
        packet_case = item["packet_case"]
        source_text = item["source_text"]
        source_id = packet_case["source"]["source_id"]
        assessments = []
        for sample_id, variant in zip(("A", "B", "C", "D"),
                                      ("actual", *_CONTROLS), strict=True):
            answer = (item["answer"] if variant == "actual"
                      else item["control_answers"][variant])
            messages = _review_messages(case=packet_case, source_text=source_text,
                                        answer=answer, sample_id=sample_id)
            raw = model_call(messages)
            parsed = _parse_assessment(raw, source_id)
            issues = cast(list[dict[str, Any]], parsed["issues"])
            issue_types = {item_["issue_type"] for item_ in issues}
            consistent = not (
                ("wrong_citation" in issue_types
                 and parsed["citation_support"] != "gap")
                or ({"unsupported_claim", "overstatement"} & issue_types
                    and parsed["evidence_grounding"] != "gap")
                or ("coverage_gap" in issue_types
                    and parsed["question_coverage"] != "partial")
            )
            expected = {
                "wrong_citation": ("citation_support", "gap"),
                "missing_aspect": ("question_coverage", "partial"),
                "unsupported_claim": ("evidence_grounding", "gap"),
            }.get(variant)
            assessments.append({
                "variant": variant, "answer": answer, "messages": messages,
                "raw_model_response": raw, "assessment": parsed,
                "dimension_consistent": consistent,
                "control_detected": (consistent and parsed[expected[0]] == expected[1]
                                     if expected else None),
            })
        cases.append({
            "case_id": packet_case["case_id"],
            "answer_sha256": item["answer_sha256"],
            "assessments": assessments,
            "all_controls_detected": all(item_["control_detected"]
                                         for item_ in assessments[1:]),
        })
    return {
        "schema_version": SCHEMA, "review_code_sha": code_sha,
        "answer_code_sha": bundle["code_sha"],
        "answer_bundle_sha256": packet["answer_bundle_sha256"],
        "review_packet_sha256": sha256(_json_bytes(packet)).hexdigest(),
        "reviewer_provider": reviewer_provider,
        "reviewer_model": reviewer_model,
        "assessor_kind": "unqualified_model_diagnostic",
        "inference_network": "remote_model_api",
        "started_at": started_at, "ended_at": _now(),
        "cases": cases,
        "all_controls_detected": all(case["all_controls_detected"] for case in cases),
        "all_dimensions_consistent": all(
            row["dimension_consistent"] for case in cases
            for row in case["assessments"]
        ),
        "formal_semantic_label": False,
        "release_observation": False,
        "release_gate": "NO_GO",
    }
