"""Persist Codex-style audit artifacts for news ingestion runs."""

from __future__ import annotations

import json
import re
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from src.news.feed_registry import feed_health_rows
from src.news.pipeline import (
    build_pipeline_trace,
    format_feed_health_markdown,
    format_pipeline_trace_markdown,
)
from src.safe_writer import safe_write_text

ROOT = Path(__file__).resolve().parent.parent.parent
NEWS_AUDIT_DIR = ROOT / "logs" / "news_audit"


@dataclass(frozen=True)
class NewsAuditArtifact:
    """File paths and run id for a persisted news audit artifact."""

    run_id: str
    markdown_path: str
    json_path: str


def _slugify(value: str, max_chars: int = 40) -> str:
    slug = re.sub(r"[^a-zA-Z0-9一-鿿_-]+", "-", (value or "").strip())
    slug = re.sub(r"-+", "-", slug).strip("-")
    return (slug or "news")[:max_chars]


def _build_run_id(query_text: str, now: float | None = None) -> str:
    timestamp = time.strftime("%Y%m%d-%H%M%S", time.localtime(time.time() if now is None else now))
    return f"{timestamp}-{_slugify(query_text)}"


def save_news_audit(
    *,
    query_text: str,
    news_items: list[dict],
    source_block: str,
    digest: str,
    article_coverage: dict[str, Any],
    warnings: list[str],
    feed_warnings: list[dict] | None = None,
    elapsed_ms: int = 0,
    audit_dir: Path = NEWS_AUDIT_DIR,
    now: float | None = None,
) -> NewsAuditArtifact:
    """Save JSON and Markdown audit artifacts for one news round."""
    run_id = _build_run_id(query_text, now=now)
    trace = build_pipeline_trace(query_text, news_items, feed_warnings=feed_warnings)
    health_rows = feed_health_rows()

    payload = {
        "run_id": run_id,
        "query_text": query_text,
        "elapsed_ms": elapsed_ms,
        "article_coverage": article_coverage,
        "warnings": warnings,
        "source_block": source_block,
        "digest": digest,
        "pipeline_trace": trace.to_dict(),
        "feed_health": health_rows,
    }

    md_lines = [
        f"# News Audit {run_id}",
        "",
        f"- query: {query_text}",
        f"- elapsed_ms: {elapsed_ms}",
        f"- warning_count: {len(warnings)}",
        "",
        "## Coverage",
    ]
    for key, value in sorted(article_coverage.items()):
        md_lines.append(f"- {key}: {value}")

    if warnings:
        md_lines.append("")
        md_lines.append("## Warnings")
        for warning in warnings:
            md_lines.append(f"- {warning}")

    md_lines.extend(
        [
            "",
            "## Source Block",
            "",
            "```text",
            source_block,
            "```",
            "",
            "## Pipeline Trace",
            "",
            format_pipeline_trace_markdown(trace),
            "",
            "## Feed Health",
            "",
            format_feed_health_markdown(health_rows),
        ]
    )

    markdown_path = audit_dir / f"{run_id}.md"
    json_path = audit_dir / f"{run_id}.json"
    safe_write_text(markdown_path, "\n".join(md_lines).strip() + "\n")
    safe_write_text(json_path, json.dumps(payload, ensure_ascii=False, indent=2))

    return NewsAuditArtifact(
        run_id=run_id,
        markdown_path=str(markdown_path),
        json_path=str(json_path),
    )


def artifact_to_dict(artifact: NewsAuditArtifact) -> dict[str, str]:
    return asdict(artifact)
