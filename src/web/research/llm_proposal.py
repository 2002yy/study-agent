"""§45 Tier-2 LLM URL proposal: a second discovery channel, never evidence.

Contract (frozen by the user):

    proposal -> URL validation -> reader verification -> candidate
             -> assessment -> extraction -> support -> eligibility -> Gate

The model proposes at most three HTTPS URLs; only URLs that the existing
reader verifies (ok + non-empty content) become candidates, and candidates
carry ``discovery_method="llm_proposed"`` so discovery provenance stays
separable from ``search``. Nothing here can create evidence: the extractor and
the Evidence Gate keep final authority.

Trigger is the Tier-1 miss condition: the claim has candidates but none was
assessed ``answer_relevant``. Default off
(``RESEARCH_LLM_PROPOSAL=on`` enables the diagnostic).
"""

from __future__ import annotations

import json
import os
from typing import Any, Mapping, Sequence

from src.news.url_normalizer import canonicalize_url

LLM_PROPOSAL_ENV = "RESEARCH_LLM_PROPOSAL"
MAX_PROPOSALS = 3
DISCOVERY_METHOD_LLM_PROPOSED = "llm_proposed"
DISCOVERY_METHOD_SEARCH = "search"

LLM_PROPOSAL_SYSTEM_PROMPT = (
    "You are a web-research planner with knowledge of official documentation "
    f"sites. Given a claim, propose up to {MAX_PROPOSALS} candidate official "
    "documentation URLs that would directly state the needed fact. Only "
    "official sources (vendor docs, official repositories, standards bodies). "
    "Copy full https URLs, most likely first. "
    'Reply with strict JSON: {"urls": ["https://...", ...]}'
)


def llm_proposal_enabled() -> bool:
    raw = (os.getenv(LLM_PROPOSAL_ENV) or "").strip().lower()
    return raw in {"1", "true", "on", "yes"}


def parse_proposal_response(raw: Any) -> list[str]:
    """Strict parser: object with a urls list of https strings, bounded."""

    if not isinstance(raw, Mapping):
        raise ValueError("proposal response must be an object")
    urls = raw.get("urls")
    if not isinstance(urls, list) or not all(isinstance(item, str) for item in urls):
        raise ValueError("proposal response needs a urls list of strings")
    cleaned: list[str] = []
    for item in urls:
        url = str(item).strip()
        if not url.lower().startswith("https://"):
            continue
        canonical = canonicalize_url(url)
        if canonical and canonical not in cleaned:
            cleaned.append(canonical)
        if len(cleaned) >= MAX_PROPOSALS:
            break
    return cleaned


def tier1_miss_reason(
    *,
    assessments: Mapping[str, Any],
    candidate_ids: Sequence[str],
) -> str:
    """Return a miss reason when Tier-1 produced no promising candidate."""

    if not candidate_ids:
        return "no_candidates"
    relevant = [
        candidate_id
        for candidate_id in candidate_ids
        if str(getattr(assessments.get(candidate_id), "relevance", "") or "")
        == "answer_relevant"
    ]
    if relevant:
        return ""
    return "no_answer_relevant_candidate"


def build_proposal_payload(claim_text: str) -> dict[str, str]:
    return {"claim": str(claim_text or "")[:2000]}


def proposal_messages(claim_text: str) -> list[dict[str, str]]:
    return [
        {"role": "system", "content": LLM_PROPOSAL_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": json.dumps(
                build_proposal_payload(claim_text), ensure_ascii=False
            ),
        },
    ]


__all__ = [
    "DISCOVERY_METHOD_LLM_PROPOSED",
    "DISCOVERY_METHOD_SEARCH",
    "LLM_PROPOSAL_ENV",
    "LLM_PROPOSAL_SYSTEM_PROMPT",
    "MAX_PROPOSALS",
    "build_proposal_payload",
    "llm_proposal_enabled",
    "parse_proposal_response",
    "proposal_messages",
    "tier1_miss_reason",
]
