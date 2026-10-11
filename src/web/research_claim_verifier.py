"""B. Independent claim verification: does the cited text actually support the claim?

Two stages, in this order:

1. DETERMINISTIC - the claim must cite a source this run registered, with a valid span in
   the text version the run actually read. If the full body was evicted, only the adopted
   evidence record may be used; when that is not enough to check the claim the verdict is
   ``unavailable``. The run never re-fetches a URL and assumes it is the same text.
2. SEMANTIC - one batched model call judges support, contradiction, insufficiency or
   unavailability, with a reason and (for insufficient) what is missing.

Only this verifier may raise a goal to the internal ``supported`` state. The older
same-window keyword rule is candidate filtering only.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable, Mapping

from src.web.research_claims import Claim

VERDICTS = ("supported", "contradicted", "insufficient", "unavailable")

_SYSTEM = (
    "You are an evidence verifier. Given a research goal, a candidate claim and the EXACT "
    "passage the claim cites, decide whether the passage genuinely supports it. Be strict: "
    "a passage that merely mentions related terms, describes how to use a tool, or answers a "
    "different question is 'insufficient'. Use 'unavailable' if the passage is missing. "
    'Reply with JSON only: {"verdicts":[{"claim_id":"...","verdict":"supported|contradicted|'
    'insufficient|unavailable","reason":"...","missing":"..."}]}'
)


@dataclass(frozen=True)
class ClaimVerdict:
    goal_id: str
    claim: str
    source_id: str
    verdict: str
    reason: str = ""
    missing: str = ""
    span_start: int = -1
    span_end: int = -1

    @property
    def internal_supported(self) -> bool:
        return self.verdict == "supported"


def _deterministic_stage(claim: Claim, body: Any | None,
                         adopted: Mapping[str, dict[str, Any]] | None) -> tuple[bool, str]:
    """(usable, reason). ``usable`` False means the verdict is forced to unavailable."""
    if body is not None:
        text = getattr(body, "text", "") or ""
        if not (0 <= claim.span_start < claim.span_end <= len(text)):
            return False, "span_out_of_range"
        span_text = text[claim.span_start:claim.span_end]
        if claim.quote and claim.quote not in text:
            return False, "quote_not_locatable"
        if not span_text.strip():
            return False, "empty_span"
        return True, ""
    # full text is gone: a retained evidence record may still cover the claim
    record = (adopted or {}).get(claim.source_id) or {}
    retained = str(record.get("excerpt") or "")
    if retained and (not claim.quote or claim.quote in retained):
        return True, "verified_from_retained_excerpt"
    return False, "full_text_evicted_and_excerpt_insufficient"


def verify_claims(*, claims: list[Claim], goals: Mapping[str, tuple[str, ...]],
                  label_to_id: Mapping[str, str], bodies: Mapping[str, Any],
                  adopted: Mapping[str, dict[str, Any]] | None,
                  completion: Callable[..., str], timeout: float = 20.0) -> list[ClaimVerdict]:
    """Verify a batch of claims. Deterministic failures are never sent to the model."""
    if not claims:
        return []
    prepared: list[dict[str, Any]] = []
    forced: dict[str, tuple[bool, str]] = {}
    for index, claim in enumerate(claims):
        claim_id = f"c{index}"
        body = bodies.get(claim.source_id)
        usable, reason = _deterministic_stage(claim, body, adopted)
        excerpt = ""
        if body is not None:
            excerpt = (getattr(body, "text", "") or "")[claim.span_start:claim.span_end]
        else:
            excerpt = str(((adopted or {}).get(claim.source_id) or {}).get("excerpt") or "")
        forced[claim_id] = (usable, reason)
        prepared.append({"claim_id": claim_id, "goal": label_to_id.get(claim.goal_id, ""),
                         "claim": claim.claim, "excerpt": excerpt[:1200]})
    verdicts: dict[str, dict[str, Any]] = {}
    if any(usable for usable, _reason in forced.values()):
        try:
            raw = completion(
                messages=[{"role": "system", "content": _SYSTEM},
                          {"role": "user", "content": json.dumps(
                              {"items": prepared}, ensure_ascii=False)}],
                timeout=timeout, task_name="research_claim_verifier")
            data = json.loads(raw) if isinstance(raw, str) else raw
            rows = (data or {}).get("verdicts") if isinstance(data, dict) else None
            for row in rows or []:
                if isinstance(row, Mapping) and row.get("claim_id"):
                    verdicts[str(row["claim_id"])] = dict(row)
        except Exception:  # noqa: BLE001 - a failed verifier abstains, never guesses
            verdicts = {}
    out: list[ClaimVerdict] = []
    for index, claim in enumerate(claims):
        claim_id = f"c{index}"
        usable, reason = forced[claim_id]
        row = verdicts.get(claim_id) or {}
        verdict = str(row.get("verdict") or "")
        if not usable:
            out.append(ClaimVerdict(claim.goal_id, claim.claim, claim.source_id,
                                    "unavailable", reason, "", claim.span_start, claim.span_end))
            continue
        if verdict not in VERDICTS or verdict == "unavailable":
            # No usable model verdict: abstain rather than silently accepting the claim.
            out.append(ClaimVerdict(claim.goal_id, claim.claim, claim.source_id,
                                    "insufficient", reason or "verifier_abstained", "",
                                    claim.span_start, claim.span_end))
            continue
        out.append(ClaimVerdict(claim.goal_id, claim.claim, claim.source_id, verdict,
                                str(row.get("reason") or ""), str(row.get("missing") or ""),
                                claim.span_start, claim.span_end))
    return out
