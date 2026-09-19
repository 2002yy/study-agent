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
    """§42 contract diagnostics: model preference, deterministic fallback."""

    enabled: bool = True
    authority: str = "model_preference_with_legacy_fallback"
    model: str = ""
    call_status: str = ""
    elapsed_ms: int = 0
    raw_pick_count: int = 0
    valid_pick_count: int = 0
    usable: bool = False
    unusable_reason: str = ""
    model_picks: list[str] = field(default_factory=list)
    fallback_invoked: bool = False
    fallback_picks: list[str] = field(default_factory=list)
    final_picks: list[str] = field(default_factory=list)
    selection_source: str = ""
    input_size: int = 0
    input_set: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "authority": self.authority,
            "model": self.model,
            "call_status": self.call_status,
            "elapsed_ms": self.elapsed_ms,
            "raw_pick_count": self.raw_pick_count,
            "valid_pick_count": self.valid_pick_count,
            "usable": self.usable,
            "unusable_reason": self.unusable_reason,
            "model_picks": list(self.model_picks),
            "fallback_invoked": self.fallback_invoked,
            "fallback_picks": list(self.fallback_picks),
            "final_picks": list(self.final_picks),
            "selection_source": self.selection_source,
            "input_size": self.input_size,
            "input_set": list(self.input_set),
        }


UNUSABLE_EMPTY = "empty"
UNUSABLE_CALL_UNAVAILABLE = "call_unavailable"
UNUSABLE_INVALID_SCHEMA = "invalid_schema"
UNUSABLE_UNKNOWN_URL = "unknown_url"
UNUSABLE_DUPLICATE_ONLY = "duplicate_only"
UNUSABLE_OVER_K = "over_k"
UNUSABLE_POLICY_VIOLATION = "policy_violation"

_SCHEMA_ERROR_TYPES = frozenset({"ValueError", "TypeError", "JSONDecodeError"})


def _schema_failure(audits: Any) -> bool:
    """True when the exhausted attempts failed on parsing, not transport."""

    error_types = {
        str(getattr(audit, "error_type", "") or "")
        for audit in (audits or ())
    } - {""}
    return bool(error_types) and error_types <= _SCHEMA_ERROR_TYPES


def parse_selection_response(raw: Any) -> list[str]:
    """Strict parser with one representation-only normalization.

    The contract shape is ``{"urls": [str, ...]}``. A top-level JSON array of
    strings is also accepted because it is the same decision in an
    unambiguous shape (no prose parsing, no truncation, no guessing). Anything
    else stays a schema failure.
    """

    if isinstance(raw, list):
        if all(isinstance(item, str) for item in raw):
            return [str(item) for item in raw]
        raise ValueError("selection url array must contain only strings")
    if not isinstance(raw, Mapping):
        raise ValueError("selection response must be an object")
    urls = raw.get("urls")
    if not isinstance(urls, list) or not all(isinstance(item, str) for item in urls):
        raise ValueError("selection response needs a urls list of strings")
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
    forbidden_urls: frozenset[str] = frozenset(),
    model_name: str = "",
    monotonic: Any = None,
) -> tuple[list[str], SelectionAuthorityDiagnostics]:
    """One bounded model call; returns (usable picks, diagnostics).

    §42 usable is mechanical and never self-declared: the call completed, the
    schema parsed, every URL is one of the **input** candidates, none is
    forbidden, no duplicates, and the count is 1..``max_picks``. Anything else
    is unusable and the caller must run the deterministic legacy window on the
    original pool.
    """

    import time

    clock = monotonic or time.monotonic
    diagnostics = SelectionAuthorityDiagnostics(model=model_name)
    ordered = list(candidates)[: max(1, int(input_max))]
    diagnostics.input_size = len(ordered)
    diagnostics.input_set = [
        str(getattr(item, "canonical_url", "")) for item in ordered
    ]
    pool_urls = set(diagnostics.input_set)
    payload = {
        "schema_version": SELECTION_AUTHORITY_SCHEMA_VERSION,
        "claim": claim_text[:2000],
        "max_urls": max(1, int(max_picks)),
        "candidates": candidate_payload(ordered),
    }
    started = clock()
    # §43A: every structured research call disables provider-side thinking for
    # json_object providers; the selector must use the same transport contract
    # or DeepSeek reasoning consumes the 500-token output budget and returns
    # empty/partial JSON (the observed invalid_schema bucket).
    extra_body: Mapping[str, Any] | None = None
    try:
        from src.llm_client import research_structured_output_capabilities

        provider_profile = str(getattr(model_gateway, "provider_profile", "") or "")
        _, thinking_off = research_structured_output_capabilities(provider_profile)
        extra_body = thinking_off
    except Exception:
        extra_body = None
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
            extra_body=extra_body,
        )
    except Exception:  # diagnostics must never fail the run
        diagnostics.call_status = "exception"
        diagnostics.elapsed_ms = int((clock() - started) * 1000)
        diagnostics.unusable_reason = UNUSABLE_CALL_UNAVAILABLE
        diagnostics.model_picks = []
        return [], diagnostics
    diagnostics.elapsed_ms = int((clock() - started) * 1000)

    status = str(getattr(result, "status", ""))
    diagnostics.call_status = status or "unknown"
    value = result.value if status == "completed" else None
    if value is None:
        diagnostics.unusable_reason = (
            UNUSABLE_INVALID_SCHEMA
            if _schema_failure(getattr(result, "audits", ()))
            else UNUSABLE_CALL_UNAVAILABLE
        )
        return [], diagnostics
    raw = list(value)
    diagnostics.raw_pick_count = len(raw)
    if not raw:
        diagnostics.unusable_reason = UNUSABLE_EMPTY
        return [], diagnostics
    if any(str(item) in forbidden_urls for item in raw):
        diagnostics.unusable_reason = UNUSABLE_POLICY_VIOLATION
        return [], diagnostics
    if any(str(item) not in pool_urls for item in raw):
        diagnostics.unusable_reason = UNUSABLE_UNKNOWN_URL
        return [], diagnostics
    unique = list(dict.fromkeys(str(item) for item in raw))
    if len(unique) != len(raw):
        diagnostics.unusable_reason = UNUSABLE_DUPLICATE_ONLY
        return [], diagnostics
    if len(unique) > max(1, int(max_picks)):
        diagnostics.unusable_reason = UNUSABLE_OVER_K
        return [], diagnostics
    diagnostics.usable = True
    diagnostics.valid_pick_count = len(unique)
    diagnostics.model_picks = list(unique)
    return unique, diagnostics


__all__ = [
    "MODEL_SELECTION_INPUT_MAX",
    "SELECTION_AUTHORITY_ENV",
    "SELECTION_AUTHORITY_MODEL",
    "SELECTION_AUTHORITY_RULES",
    "SELECTION_AUTHORITY_SCHEMA_VERSION",
    "SELECTION_SYSTEM_PROMPT",
    "SelectionAuthorityDiagnostics",
    "UNUSABLE_CALL_UNAVAILABLE",
    "UNUSABLE_DUPLICATE_ONLY",
    "UNUSABLE_EMPTY",
    "UNUSABLE_INVALID_SCHEMA",
    "UNUSABLE_OVER_K",
    "UNUSABLE_POLICY_VIOLATION",
    "UNUSABLE_UNKNOWN_URL",
    "candidate_payload",
    "parse_selection_response",
    "select_candidates_with_model",
    "selection_authority_mode",
]
