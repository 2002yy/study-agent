"""Bounded lead-discovery boundary for the active research runtime.

A **Lead** is a research asset used to *discover* evidence; it is never a weak
evidence link. Lead discovery therefore has its own contract and its own type:
``LeadDiscoveryPayload`` cannot carry claim support, evidence strength, or any
evidence identity, so a lead can never enter the Evidence Graph.

Frozen boundary (v1):
- Evidence eligibility, the Evidence Gate, and the 45s/60s qualification
  budgets are unchanged. Lead reads spend the same shared read/model budget.
- ``rejected`` candidates are never read. Only ``lead_only`` candidates can be
  scheduled as leads, and only by the deterministic scheduler predicate.
- The lead extractor does not decide research strategy: it returns URLs,
  domains, organizations, and primary-source hints only. Query strategy stays
  with the Gap Planner.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any, Mapping
from urllib.parse import urlsplit

from src.llm_client import research_structured_output_capabilities
from src.web.research.candidate_pool import CandidatePoolItem
from src.web.research.model_gateway import (
    AttemptFinishedHook,
    AttemptStartedHook,
    ResearchModelCallAudit,
    ResearchModelGateway,
    with_json_object_contract,
)

LEAD_DISCOVERY_SCHEMA_VERSION = "research-lead-discovery-v1"
LEAD_DISCOVERY_MAX_URLS = 5
LEAD_DISCOVERY_MAX_DOMAINS = 5
LEAD_DISCOVERY_MAX_ORGANIZATIONS = 5
LEAD_DISCOVERY_MAX_HINTS = 5
LEAD_DISCOVERY_MAX_WARNINGS = 4
LEAD_DISCOVERY_MAX_TOKENS = 700
LEAD_DISCOVERY_EXCERPT_CHARS = 6000

LEAD_DISCOVERY_FIELDS = frozenset(
    {
        "schema_version",
        "candidate_id",
        "discovered_urls",
        "domains",
        "organizations",
        "primary_source_hints",
        "warnings",
    }
)

LEAD_DISCOVERY_PAYLOAD_FIELDS = frozenset(
    {
        "source_candidate_id",
        "discovered_urls",
        "domains",
        "organizations",
        "primary_source_hints",
        "warnings",
    }
)

LEAD_DISCOVERY_RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": sorted(LEAD_DISCOVERY_FIELDS),
    "properties": {
        "schema_version": {"const": LEAD_DISCOVERY_SCHEMA_VERSION},
        "candidate_id": {"type": "string"},
        "discovered_urls": {
            "type": "array",
            "maxItems": LEAD_DISCOVERY_MAX_URLS,
            "items": {"type": "string"},
        },
        "domains": {
            "type": "array",
            "maxItems": LEAD_DISCOVERY_MAX_DOMAINS,
            "items": {"type": "string"},
        },
        "organizations": {
            "type": "array",
            "maxItems": LEAD_DISCOVERY_MAX_ORGANIZATIONS,
            "items": {"type": "string"},
        },
        "primary_source_hints": {
            "type": "array",
            "maxItems": LEAD_DISCOVERY_MAX_HINTS,
            "items": {"type": "string"},
        },
        "warnings": {
            "type": "array",
            "maxItems": LEAD_DISCOVERY_MAX_WARNINGS,
            "items": {"type": "string"},
        },
    },
}

LEAD_DISCOVERY_SYSTEM_PROMPT = """You are a provenance scout for a bounded research runtime.
The page below was read as a LEAD: it is related to the research question but is
not eligible to support a claim as evidence. Your only job is to report bounded
discovery assets that could lead to a primary source.

Report only what is actually present in the excerpt:
- discovered_urls: absolute http(s) URLs visible in the excerpt that point to a
  potentially authoritative source (official documentation, standards body,
  vendor page, data publisher). Never invent URLs.
- domains: bare domains of those sources (for example docs.example.com).
- organizations: named organizations that could own an authoritative source.
- primary_source_hints: short search hints (name, document title, or site
  fragment) that could locate an official source. No full sentences.
- warnings: short notes when the page looks like a repost, aggregator, or when
  no usable lead exists.

Do NOT output claim support, evidence strength, evidence identifiers, or any
judgement about whether the claim is true. You are not producing evidence.
Output one JSON object with exactly these keys and nothing else."""


@dataclass(frozen=True)
class LeadDiscoveryPayload:
    """Bounded discovery assets produced by one lead read.

    This type intentionally has no claim-support, strength, or evidence identity
    field: a lead can never become eligible evidence.
    """

    source_candidate_id: str
    discovered_urls: tuple[str, ...]
    domains: tuple[str, ...]
    organizations: tuple[str, ...]
    primary_source_hints: tuple[str, ...]
    warnings: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_candidate_id": self.source_candidate_id,
            "discovered_urls": list(self.discovered_urls),
            "domains": list(self.domains),
            "organizations": list(self.organizations),
            "primary_source_hints": list(self.primary_source_hints),
            "warnings": list(self.warnings),
        }

    @classmethod
    def from_dict(cls, raw: Any) -> "LeadDiscoveryPayload":
        """Strict durable-cursor round trip (same bounds as the model parser)."""

        data = _mapping(raw, "lead discovery payload")
        if set(data) != LEAD_DISCOVERY_PAYLOAD_FIELDS:
            raise ValueError("lead discovery payload has unknown or missing fields")
        return cls(
            source_candidate_id=_required_text(
                data.get("source_candidate_id"), 300, "source_candidate_id"
            ),
            discovered_urls=_url_tuple(
                data.get("discovered_urls"), LEAD_DISCOVERY_MAX_URLS, "discovered_urls"
            ),
            domains=_text_tuple(
                data.get("domains"), LEAD_DISCOVERY_MAX_DOMAINS, 253, "domains"
            ),
            organizations=_text_tuple(
                data.get("organizations"),
                LEAD_DISCOVERY_MAX_ORGANIZATIONS,
                200,
                "organizations",
            ),
            primary_source_hints=_text_tuple(
                data.get("primary_source_hints"),
                LEAD_DISCOVERY_MAX_HINTS,
                300,
                "primary_source_hints",
            ),
            warnings=_text_tuple(
                data.get("warnings"), LEAD_DISCOVERY_MAX_WARNINGS, 300, "warnings"
            ),
        )


@dataclass(frozen=True)
class LeadDiscoveryResult:
    status: str
    discovery: LeadDiscoveryPayload | None
    audits: tuple[ResearchModelCallAudit, ...]
    reason: str = ""


class RuntimeLeadDiscoverer:
    """One bounded lead-discovery call per invocation (no hidden retries)."""

    def __init__(self, model_gateway: ResearchModelGateway) -> None:
        self.model_gateway = model_gateway

    def discover(
        self,
        *,
        run_id: str,
        candidate: CandidatePoolItem,
        content: str,
        timeout_seconds: float | None = None,
        on_attempt_started: AttemptStartedHook | None = None,
        on_attempt_finished: AttemptFinishedHook | None = None,
        call_id_suffix: str = "",
        attempt_start: int = 1,
    ) -> LeadDiscoveryResult:
        excerpt = str(content or "")[:LEAD_DISCOVERY_EXCERPT_CHARS]
        if not excerpt.strip():
            return LeadDiscoveryResult(
                status="unavailable",
                discovery=None,
                audits=(),
                reason="empty_read_content",
            )
        request = {
            "schema_version": LEAD_DISCOVERY_SCHEMA_VERSION,
            "candidate_id": candidate.id,
            "page": {
                "title": candidate.title[:500],
                "url": candidate.canonical_url[:2000],
                "excerpt": excerpt,
            },
        }
        mode, thinking_off = research_structured_output_capabilities(
            self.model_gateway.provider_profile
        )
        messages: list[dict[str, str]] = [
            {"role": "system", "content": LEAD_DISCOVERY_SYSTEM_PROMPT},
            {"role": "user", "content": json.dumps(request, ensure_ascii=False)},
        ]
        if mode == "json_object":
            messages = with_json_object_contract(messages, LEAD_DISCOVERY_RESPONSE_SCHEMA)
        result = self.model_gateway.complete_structured(
            logical_call_id=(
                f"research_lead_discovery:{run_id}:{candidate.id}:1{call_id_suffix}"
            ),
            purpose="research_lead_discovery",
            messages=messages,
            audit_payload=request,
            response_schema_version=LEAD_DISCOVERY_SCHEMA_VERSION,
            parse=lambda raw: parse_lead_discovery_response(
                raw, candidate_id=candidate.id
            ),
            data_categories=(
                "public_research_candidate_metadata",
                "bounded_public_page_excerpt",
            ),
            data_counts={
                "candidate_metadata": 1,
                "page_excerpt_chars": len(excerpt),
            },
            max_tokens=LEAD_DISCOVERY_MAX_TOKENS,
            temperature=0.0,
            timeout_seconds=timeout_seconds,
            on_attempt_started=on_attempt_started,
            on_attempt_finished=on_attempt_finished,
            attempt_start=attempt_start,
            extra_body=thinking_off,
        )
        return LeadDiscoveryResult(
            status=result.status,
            discovery=result.value,
            audits=result.audits,
            reason=result.reason,
        )


def parse_lead_discovery_response(
    raw: Any,
    *,
    candidate_id: str,
) -> LeadDiscoveryPayload:
    """Strict parser: final authority over lead-discovery output."""

    data = _mapping(raw, "lead discovery")
    if set(data) != LEAD_DISCOVERY_FIELDS:
        raise ValueError("lead discovery has unknown or missing fields")
    if data.get("schema_version") != LEAD_DISCOVERY_SCHEMA_VERSION:
        raise ValueError("lead discovery schema version mismatch")
    if _required_text(data.get("candidate_id"), 300, "candidate_id") != candidate_id:
        raise ValueError("lead discovery changed server-owned candidate_id")
    return LeadDiscoveryPayload(
        source_candidate_id=candidate_id,
        discovered_urls=_url_tuple(
            data.get("discovered_urls"), LEAD_DISCOVERY_MAX_URLS, "discovered_urls"
        ),
        domains=_text_tuple(
            data.get("domains"), LEAD_DISCOVERY_MAX_DOMAINS, 253, "domains"
        ),
        organizations=_text_tuple(
            data.get("organizations"),
            LEAD_DISCOVERY_MAX_ORGANIZATIONS,
            200,
            "organizations",
        ),
        primary_source_hints=_text_tuple(
            data.get("primary_source_hints"),
            LEAD_DISCOVERY_MAX_HINTS,
            300,
            "primary_source_hints",
        ),
        warnings=_text_tuple(
            data.get("warnings"), LEAD_DISCOVERY_MAX_WARNINGS, 300, "warnings"
        ),
    )


def _mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} must be an object")
    return value


def _required_text(value: Any, limit: int, label: str) -> str:
    text = " ".join(str(value or "").split())
    if not text:
        raise ValueError(f"{label} is required")
    if len(text) > limit:
        raise ValueError(f"{label} exceeds {limit} characters")
    return text


def _text_tuple(value: Any, limit: int, item_limit: int, label: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list):
        raise ValueError(f"{label} must be a list")
    if len(value) > limit:
        raise ValueError(f"{label} exceeds {limit} items")
    items: list[str] = []
    seen: set[str] = set()
    for item in value:
        text = _required_text(item, item_limit, label)
        key = text.casefold()
        if key in seen:
            continue
        seen.add(key)
        items.append(text)
    return tuple(items)


def _url_tuple(value: Any, limit: int, label: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list):
        raise ValueError(f"{label} must be a list")
    if len(value) > limit:
        raise ValueError(f"{label} exceeds {limit} items")
    urls: list[str] = []
    seen: set[str] = set()
    for item in value:
        text = _required_text(item, 2000, label)
        parsed = urlsplit(text)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError(f"{label} must contain absolute http(s) URLs")
        key = text.casefold()
        if key in seen:
            continue
        seen.add(key)
        urls.append(text)
    return tuple(urls)


__all__ = [
    "LEAD_DISCOVERY_FIELDS",
    "LEAD_DISCOVERY_MAX_TOKENS",
    "LEAD_DISCOVERY_PAYLOAD_FIELDS",
    "LEAD_DISCOVERY_RESPONSE_SCHEMA",
    "LEAD_DISCOVERY_SCHEMA_VERSION",
    "LeadDiscoveryPayload",
    "LeadDiscoveryResult",
    "RuntimeLeadDiscoverer",
    "parse_lead_discovery_response",
]
