"""Diagnostic answer generation from byte-bound frozen text/PDF sources.

Remote model inference is recorded explicitly. Its output is not an offline
release observation and cannot supply semantic labels by itself.
"""

from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import re
from typing import Callable

from src.evals.release_benchmark_registry import ReleaseCase, ReleaseGold, ReleaseRegistry
from src.evals.release_benchmark_replay import (
    FrozenPdfGateway,
    FrozenTextGateway,
    block_python_network,
    run_frozen_pdf_pilot,
    run_frozen_text_pilot,
)

SCHEMA = "release-benchmark-answer-diagnostic-v1"
_CODE_SHA = re.compile(r"[0-9a-f]{40}\Z")
_EMBEDDED_LINK = re.compile(r"://|\bwww\.|\[[^\]]+\]\([^)]*\)|[\r\n]", re.I)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":")).encode("utf-8")


def _parse_claims(raw: str, source_id: str) -> list[dict[str, object]]:
    if not isinstance(raw, str) or len(raw) > 10000:
        raise ValueError("answer model response is not bounded text")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError("answer model did not return JSON") from exc
    if not isinstance(data, dict) or set(data) != {"claims"}:
        raise ValueError("answer model response must contain only claims")
    claims = data["claims"]
    if not isinstance(claims, list) or not 1 <= len(claims) <= 6:
        raise ValueError("answer model must return one to six claims")
    parsed: list[dict[str, object]] = []
    for claim in claims:
        if not isinstance(claim, dict) or set(claim) != {"text", "source_ids"}:
            raise ValueError("answer claim has invalid shape")
        claim_text, refs = claim["text"], claim["source_ids"]
        if (not isinstance(claim_text, str) or not claim_text.strip()
                or len(claim_text) > 500 or refs != [source_id]
                or _EMBEDDED_LINK.search(claim_text)):
            raise ValueError("answer claim lacks an authorized citation")
        parsed.append({"text": claim_text.strip(), "source_ids": [source_id]})
    return parsed


def _messages(case: ReleaseCase, content: str) -> list[dict[str, str]]:
    source = case.sources[0]
    return [
        {"role": "system", "content": (
            "Answer only from the supplied frozen source text. Return JSON with exactly "
            "one key, claims: an array of 1 to 6 objects with text and source_ids. "
            "Every source_ids value must be an array containing the supplied source ID. "
            "Keep each claim concise. Do not use outside knowledge. If the source does "
            "not answer an aspect, say so as a cited claim. Do not include citations "
            "inside claim text."
        )},
        {"role": "user", "content": (
            f"Question: {case.question}\nSource ID: {source.source_id}\n"
            f"Source locator: {source.locator}\n"
            f"Page: {source.page or 'web page'}\n"
            f"Source text:\n{content}"
        )},
    ]


def _render_answer(case: ReleaseCase, claims: list[dict[str, object]]) -> str:
    source = case.sources[0]
    label = source.source_id + (f", p.{source.page}" if source.page else "")
    answer = "\n".join(f"{claim['text']} [{label}]({source.locator}"
                       + (f"#page={source.page}" if source.page else "") + ")"
                       for claim in claims)
    if case.limitations:
        answer += "\n" + " ".join(case.limitations)
    return answer


def generate_frozen_answer(
    case: ReleaseCase, root: Path, *, model_call: Callable[[list[dict[str, str]]], str],
    provider: str, model: str, code_sha: str,
) -> dict[str, object]:
    """Run the real reader offline, then a separately disclosed model call."""
    if case.mode != "frozen" or case.modality not in {"text", "pdf"}:
        raise ValueError("answer pilot accepts frozen text/PDF cases only")
    if len(case.sources) != 1:
        raise ValueError("answer pilot requires exactly one registered source")
    if not provider or not model or not _CODE_SHA.fullmatch(code_sha):
        raise ValueError("answer pilot needs model identity and code SHA")
    source = case.sources[0]
    gateway = (FrozenTextGateway(case, root) if case.modality == "text"
               else FrozenPdfGateway(case, root))
    started_at = _now()
    pilot = (run_frozen_text_pilot(case, root) if case.modality == "text"
             else run_frozen_pdf_pilot(case, root))
    rows = pilot["source_reads"]
    if (pilot["run_status"] != "completed" or pilot["stop_reason"] != "sources_read"
            or len(rows) != 1 or rows[0]["state"] != "read"
            or rows[0]["locator"] != source.locator
            or rows[0]["source_sha256"] != source.sha256
            or rows[0]["page"] != source.page
            or rows[0]["region"] != source.region):
        raise ValueError("frozen reader did not complete a registered source read")
    with block_python_network():
        read = gateway.read(source.locator, max_chars=6000)
    if (read["source_sha256"] != source.sha256 or read["url"] != source.locator
            or not read["content"].strip()):
        raise ValueError("frozen source context binding failed")
    messages = _messages(case, read["content"])
    model_started_at = _now()
    raw = model_call(messages)
    model_ended_at = _now()
    if not isinstance(raw, str):
        raise ValueError("answer model returned no text")
    claims = _parse_claims(raw, source.source_id)
    citation = {"source_id": source.source_id, "locator": source.locator,
                "page": source.page, "region": source.region,
                "snapshot_sha256": source.sha256}
    answer = _render_answer(case, claims)
    return {
        "schema_version": SCHEMA,
        "case_id": case.case_id,
        "case_content_sha256": case.content_sha256,
        "code_sha": code_sha,
        "reader_run_id": pilot["run_id"],
        "reader_network_guard": pilot["network_guard"],
        "inference_network": "remote_model_api",
        "provider": provider,
        "model": model,
        "started_at": started_at,
        "model_started_at": model_started_at,
        "model_ended_at": model_ended_at,
        "source": citation,
        "source_context_sha256": sha256(read["content"].encode("utf-8")).hexdigest(),
        "prompt_sha256": sha256(_canonical_bytes(messages)).hexdigest(),
        "messages": messages,
        "raw_model_response": raw,
        "claims": claims,
        "answer": answer,
        "semantic_assessment": "pending_external_adjudication",
        "release_observation": False,
        "release_gate": "NO_GO",
    }


def build_answer_review_packet(bundle: dict[str, object], registry: ReleaseRegistry,
                               gold: ReleaseGold, root: Path) -> dict[str, object]:
    """Recheck a saved diagnostic against snapshots before disclosing gold."""
    if (not isinstance(bundle, dict) or set(bundle) != {
        "schema_version", "code_sha", "plan_digest", "registry_digest",
        "gold_digest", "inference_network", "release_gate", "cases",
    } or bundle["schema_version"] != "release-benchmark-answer-pilot-bundle-v1"
            or bundle["plan_digest"] != registry.plan_digest
            or bundle["registry_digest"] != registry.digest
            or bundle["gold_digest"] != gold.digest
            or bundle["inference_network"] != "remote_model_api"
            or bundle["release_gate"] != "NO_GO"
            or not isinstance(bundle["code_sha"], str)
            or not _CODE_SHA.fullmatch(bundle["code_sha"])):
        raise ValueError("answer bundle manifest binding is invalid")
    reviewed = {review.case_id: review for review in gold.reviews
                if review.structurally_reviewed}
    selected = [case for case in registry.cases if case.case_id in reviewed
                and case.mode == "frozen" and case.modality in {"text", "pdf"}]
    rows = bundle["cases"]
    if (not isinstance(rows, list) or len(rows) != len(selected)
            or [row.get("case_id") for row in rows if isinstance(row, dict)]
            != [case.case_id for case in selected]):
        raise ValueError("answer bundle case scope mismatch")
    packet_cases = []
    for case, row in zip(selected, rows, strict=True):
        source = case.sources[0]
        expected_keys = {
            "schema_version", "case_id", "case_content_sha256", "code_sha",
            "reader_run_id", "reader_network_guard", "inference_network",
            "provider", "model", "started_at", "model_started_at",
            "model_ended_at", "source", "source_context_sha256",
            "prompt_sha256", "messages", "raw_model_response", "claims",
            "answer", "semantic_assessment", "release_observation", "release_gate",
        }
        if (set(row) != expected_keys or row["schema_version"] != SCHEMA
                or row["case_content_sha256"] != case.content_sha256
                or row["code_sha"] != bundle["code_sha"]
                or row["reader_network_guard"] != "python_socket_connect_blocked"
                or row["inference_network"] != "remote_model_api"
                or row["semantic_assessment"] != "pending_external_adjudication"
                or row["release_observation"] is not False
                or row["release_gate"] != "NO_GO"
                or not isinstance(row["reader_run_id"], str)
                or not row["reader_run_id"].startswith("web_lookup_")
                or not isinstance(row["provider"], str) or not row["provider"]
                or not isinstance(row["model"], str) or not row["model"]):
            raise ValueError("answer diagnostic fields are invalid")
        expected_source = {
            "source_id": source.source_id, "locator": source.locator,
            "page": source.page, "region": source.region,
            "snapshot_sha256": source.sha256,
        }
        if row["source"] != expected_source:
            raise ValueError("answer citation source binding is invalid")
        gateway = (FrozenTextGateway(case, root) if case.modality == "text"
                   else FrozenPdfGateway(case, root))
        with block_python_network():
            content = gateway.read(source.locator, max_chars=6000)["content"]
        messages = _messages(case, content)
        if (row["source_context_sha256"] != sha256(content.encode("utf-8")).hexdigest()
                or row["messages"] != messages
                or row["prompt_sha256"] != sha256(_canonical_bytes(messages)).hexdigest()):
            raise ValueError("answer prompt or source context drift")
        claims = _parse_claims(row["raw_model_response"], source.source_id)
        if row["claims"] != claims or row["answer"] != _render_answer(case, claims):
            raise ValueError("answer claims or citations were altered")
        review = reviewed[case.case_id]
        packet_cases.append({
            "case_id": case.case_id, "question": case.question,
            "answer": row["answer"], "claims": claims,
            "source": expected_source, "aspects": list(case.aspects),
            "required_units": list(case.required_units),
            "limitations": list(case.limitations),
            "aspect_rubric": dict(review.aspect_rubric),
            "unit_sources": {key: list(value) for key, value in review.unit_sources},
            "semantic_metrics_pending": ["question_coverage", "evidence_grounding",
                                         "citation_support", "answer_utility"],
        })
    return {
        "schema_version": "release-benchmark-answer-review-packet-v1",
        "answer_bundle_sha256": sha256(_canonical_bytes(bundle) + b"\n").hexdigest(),
        "code_sha": bundle["code_sha"],
        "registry_digest": registry.digest,
        "gold_digest": gold.digest,
        "cases": packet_cases,
        "semantic_assessment": "pending_external_adjudication",
        "release_gate": "NO_GO",
    }
