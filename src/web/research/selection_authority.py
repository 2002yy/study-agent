"""§38b diagnostic selection authority: model selector over the pooled candidates.

Inactive by default. The production path keeps the deterministic
``_bounded_assessment_candidates`` window unless the operator explicitly sets
``RESEARCH_SELECTION_AUTHORITY=model`` for a diagnostic run.

When enabled, the model decides **which** candidates enter the bounded
assessment window (at most the same window cap the rules used); every bound
stays in code:

- the candidate set is the runtime's own pooled, deduped candidate tuple;
- the model may only choose URLs that exist in that set (canonical match);
- unusable decisions (empty/unavailable/invalid) make the caller fall back to
  the deterministic window, so the model can raise the ceiling but can never
  remove the floor;
- diagnostics record the exact selector input/output sets so a runtime
  divergence from the offline replay is visible instead of guessed.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from src.news.url_normalizer import canonicalize_url

SELECTION_AUTHORITY_ENV = "RESEARCH_SELECTION_AUTHORITY"
SELECTION_AUTHORITY_RULES = "rules"
SELECTION_AUTHORITY_MODEL = "model"
SELECTION_AUTHORITY_SCHEMA_VERSION = "research-selection-authority-v1"
MODEL_SELECTION_INPUT_MAX = 24

SELECTION_SYSTEM_PROMPT = (
    "You are a bounded search-result selector. Given the claim and the "
    "candidate search results, choose which pages to open. Reply with strict "
    'JSON: {"urls": [str], "reason": str}. Copy the candidate URLs exactly as '
    "given - no rewrites, no invented URLs. Choose between 1 and the given "
    "maximum number of pages whenever any candidate plausibly concerns the "
    "claim; only return an empty list when no candidate is even plausibly "
    "related. Prefer the page that would directly state the missing fact "
    "(official or primary sources first)."
)


def selection_authority_mode() -> str:
    """Resolve the diagnostic flag; anything unknown stays on the rules."""

    raw = (os.getenv(SELECTION_AUTHORITY_ENV) or "").strip().lower()
    return SELECTION_AUTHORITY_MODEL if raw == SELECTION_AUTHORITY_MODEL else SELECTION_AUTHORITY_RULES


@dataclass
class SelectionAuthorityDiagnostics:
    mode: str = SELECTION_AUTHORITY_MODEL
    status: str = ""
    reason: str = ""
    input_size: int = 0
    input_set: list[str] = field(default_factory=list)
    output_urls: list[str] = field(default_factory=list)
    output_count: int = 0
    fallback: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "status": self.status,
            "reason": self.reason,
            "input_size": self.input_size,
            "input_set": list(self.input_set),
            "output_urls": list(self.output_urls),
            "output_count": self.output_count,
            "fallback": self.fallback,
        }


def parse_selection_response(raw: Any) -> list[str]:
    """Strict parser: an object with a urls list of strings."""

    if not isinstance(raw, Mapping):
        raise ValueError("selection response must be an object")
    urls = raw.get("urls")
    if not isinstance(urls, list):
        raise ValueError("selection response needs a urls list")
    return [str(item) for item in urls]


def candidate_payload(candidates: Sequence[Any]) -> list[dict[str, str]]:
    """Bounded (url, title, snippet) rows for exactly these candidates."""

    rows: list[dict[str, str]] = []
    for item in candidates:
        rows.append(
            {
                "url": str(getattr(item, "canonical_url", "") or ""),
                "title": " ".join(str(getattr(item, "title", "") or "").split())[:300],
                "snippet": " ".join(str(getattr(item, "snippet", "") or "").split())[:400],
            }
        )
    return rows


def select_candidates_with_model(
    *,
    model_gateway: Any,
    claim_text: str,
    candidates: Sequence[Any],
    max_picks: int,
    timeout_seconds: float | None,
    logical_call_id: str,
    input_max: int = MODEL_SELECTION_INPUT_MAX,
) -> tuple[list[str], SelectionAuthorityDiagnostics]:
    """One bounded model call; returns (picked canonical urls, diagnostics).

    Usable means: the gateway completed AND at least one returned URL matched a
    candidate. Everything else is the caller's cue to fall back.
    """

    diagnostics = SelectionAuthorityDiagnostics()
    ordered = list(candidates)[: max(1, int(input_max))]
    diagnostics.input_size = len(ordered)
    diagnostics.input_set = [str(getattr(item, "canonical_url", "")) for item in ordered]
    payload = {
        "schema_version": SELECTION_AUTHORITY_SCHEMA_VERSION,
        "claim": claim_text[:2000],
        "max_urls": max(1, int(max_picks)),
        "candidates": candidate_payload(ordered),
    }
    try:
        result = model_gateway.complete_structured(
            logical_call_id=logical_call_id,
            purpose="research_selection_authority",
            messages=[
                {"role": "system", "content": SELECTION_SYSTEM_PROMPT},
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
            ],
            audit_payload=payload,
            response_schema_version=SELECTION_AUTHORITY_SCHEMA_VERSION,
            parse=parse_selection_response,
            data_categories=("public_research_claim", "public_candidate_metadata"),
            max_tokens=500,
            timeout_seconds=timeout_seconds,
        )
    except Exception as exc:  # diagnostics must never fail the run
        diagnostics.status = "exception"
        diagnostics.reason = type(exc).__name__
        return [], diagnostics

    status = str(getattr(result, "status", ""))
    diagnostics.status = status or "unknown"
    diagnostics.reason = str(getattr(result, "reason", "") or "")[:300]
    value = result.value if status == "completed" else None
    if value is None:
        return [], diagnostics

    by_url = {
        str(getattr(item, "canonical_url", "")): str(getattr(item, "canonical_url", ""))
        for item in ordered
    }
    picks: list[str] = []
    for item in list(value):
        canonical = canonicalize_url(str(item))
        if canonical and canonical in by_url and canonical not in picks:
            picks.append(canonical)
        if len(picks) >= max(1, int(max_picks)):
            break
    diagnostics.output_urls = list(picks)
    diagnostics.output_count = len(picks)
    return picks, diagnostics


__all__ = [
    "MODEL_SELECTION_INPUT_MAX",
    "SELECTION_AUTHORITY_ENV",
    "SELECTION_AUTHORITY_MODEL",
    "SELECTION_AUTHORITY_RULES",
    "SELECTION_AUTHORITY_SCHEMA_VERSION",
    "SELECTION_SYSTEM_PROMPT",
    "SelectionAuthorityDiagnostics",
    "candidate_payload",
    "parse_selection_response",
    "select_candidates_with_model",
    "selection_authority_mode",
]
