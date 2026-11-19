"""Item-level source evidence metadata for the active news digest."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class PipelineItemTrace:
    """One auditable news item after resolution, policy, and article reading."""

    title: str
    source: str
    original_url: str
    resolved_url: str
    canonical_url: str
    domain: str
    resolution_status: str
    article_status: str
    evidence_level: str
    domain_policy_blocked: bool = False
    domain_policy_reasons: tuple[str, ...] = ()
    redirect_hop_count: int = 0
    unsafe_redirect_blocked: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _evidence_level(item: dict) -> str:
    article_status = str(item.get("article_status", "") or "")
    if item.get("article_excerpt") or article_status.startswith("正文已读"):
        return "article_text"
    policy = item.get("domain_policy") or {}
    if policy.get("blocked"):
        return "domain_blocked"
    if article_status.startswith("域名策略过滤"):
        return "domain_blocked"
    if item.get("search_excerpt"):
        return "search_snippet"
    if item.get("feed_summary"):
        return "feed_summary"
    if "正文不可用" in article_status:
        return "title_only"
    return "title_only"


def build_item_trace(item: dict) -> PipelineItemTrace:
    policy = item.get("domain_policy") or {}
    redirect_hops = item.get("redirect_hops") or []
    unsafe_redirect_blocked = any(
        hop.get("status") == "blocked" or hop.get("is_safe") is False
        for hop in redirect_hops
        if isinstance(hop, dict)
    )

    return PipelineItemTrace(
        title=str(item.get("title", "") or ""),
        source=str(item.get("source", "") or ""),
        original_url=str(item.get("link", "") or ""),
        resolved_url=str(item.get("resolved_link", "") or item.get("link", "") or ""),
        canonical_url=str(item.get("canonical_url", "") or ""),
        domain=str(item.get("domain", "") or ""),
        resolution_status=str(item.get("resolution_status", "") or "unknown"),
        article_status=str(item.get("article_status", "") or "仅标题"),
        evidence_level=_evidence_level(item),
        domain_policy_blocked=bool(policy.get("blocked", False)),
        domain_policy_reasons=tuple(policy.get("reasons") or ()),
        redirect_hop_count=len(redirect_hops),
        unsafe_redirect_blocked=unsafe_redirect_blocked,
    )
