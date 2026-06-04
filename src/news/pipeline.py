"""Structured audit helpers for the news ingestion pipeline."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
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


@dataclass(frozen=True)
class PipelineTrace:
    """Round-level audit summary for a set of news items."""

    query: str
    total_items: int
    article_text_items: int
    title_only_items: int
    blocked_items: int
    unsafe_redirect_items: int
    resolution_counts: dict[str, int] = field(default_factory=dict)
    source_counts: dict[str, int] = field(default_factory=dict)
    feed_warnings: tuple[dict[str, Any], ...] = ()
    items: tuple[PipelineItemTrace, ...] = ()

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


def build_pipeline_trace(
    query: str,
    news_items: list[dict],
    feed_warnings: list[dict] | None = None,
) -> PipelineTrace:
    item_traces = tuple(build_item_trace(item) for item in news_items)
    resolution_counts: dict[str, int] = {}
    source_counts: dict[str, int] = {}

    for item in item_traces:
        resolution_counts[item.resolution_status] = (
            resolution_counts.get(item.resolution_status, 0) + 1
        )
        source_counts[item.source] = source_counts.get(item.source, 0) + 1

    article_text_items = sum(
        1 for item in item_traces if item.evidence_level == "article_text"
    )
    blocked_items = sum(
        1 for item in item_traces if item.evidence_level == "domain_blocked"
    )
    unsafe_redirect_items = sum(1 for item in item_traces if item.unsafe_redirect_blocked)

    return PipelineTrace(
        query=query,
        total_items=len(item_traces),
        article_text_items=article_text_items,
        title_only_items=len(item_traces) - article_text_items - blocked_items,
        blocked_items=blocked_items,
        unsafe_redirect_items=unsafe_redirect_items,
        resolution_counts=resolution_counts,
        source_counts=source_counts,
        feed_warnings=tuple(dict(item) for item in (feed_warnings or [])),
        items=item_traces,
    )


def _evidence_label(level: str) -> str:
    return {
        "article_text": "页面文本",
        "domain_blocked": "域名过滤",
        "title_only": "标题/来源",
    }.get(level, level or "未知")


def format_pipeline_trace_markdown(trace: PipelineTrace) -> str:
    """Render a compact audit report for one news round."""
    lines = [
        "# News Pipeline Trace",
        "",
        f"- query: {trace.query}",
        f"- total_items: {trace.total_items}",
        f"- article_text_items: {trace.article_text_items}",
        f"- title_only_items: {trace.title_only_items}",
        f"- blocked_items: {trace.blocked_items}",
        f"- unsafe_redirect_items: {trace.unsafe_redirect_items}",
    ]

    if trace.resolution_counts:
        counts = ", ".join(
            f"{key}={value}" for key, value in sorted(trace.resolution_counts.items())
        )
        lines.append(f"- resolution_counts: {counts}")

    if trace.feed_warnings:
        lines.append("")
        lines.append("## Feed Warnings")
        for warning in trace.feed_warnings:
            lines.append(
                "- "
                f"{warning.get('source', 'unknown')}: "
                f"{warning.get('error_type', 'Error')} "
                f"{warning.get('message', '')}".strip()
            )

    if trace.items:
        lines.append("")
        lines.append("## Items")
        for idx, item in enumerate(trace.items, start=1):
            lines.append(f"{idx}. {item.title or 'Untitled'}")
            lines.append(f"   - source: {item.source}")
            lines.append(f"   - domain: {item.domain or 'unknown'}")
            lines.append(f"   - resolution: {item.resolution_status}")
            lines.append(f"   - evidence: {_evidence_label(item.evidence_level)}")
            if item.redirect_hop_count:
                lines.append(f"   - redirect_hops: {item.redirect_hop_count}")
            if item.unsafe_redirect_blocked:
                lines.append("   - unsafe_redirect: blocked")
            if item.domain_policy_reasons:
                lines.append(
                    "   - domain_policy: " + ", ".join(item.domain_policy_reasons)
                )

    return "\n".join(lines).strip()


def format_feed_health_markdown(rows: list[dict[str, Any]]) -> str:
    """Render feed health rows as a small report."""
    lines = ["# Feed Health", ""]
    if not rows:
        lines.append("No feed health records yet.")
        return "\n".join(lines)

    for row in rows:
        source = row.get("source", "unknown")
        status = row.get("status", "unknown")
        item_count = row.get("item_count", 0)
        lines.append(f"- {source}: {status} ({item_count} items)")
        if row.get("error_type") or row.get("message"):
            lines.append(
                f"  - error: {row.get('error_type', 'Error')} {row.get('message', '')}".strip()
            )
    return "\n".join(lines).strip()
