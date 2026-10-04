"""Replaceable specialist contracts. No login state or credentials live here."""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Literal, Protocol

from src.web.tool_evidence import _public_url

AuthLevel = Literal["anonymous", "optional_auth", "auth_bound"]
PlatformOperation = Literal["search", "detail", "subtitles", "comments", "feed"]


@dataclass(frozen=True)
class PlatformCapability:
    platform: str
    operation: PlatformOperation
    auth_level: AuthLevel
    primary: str
    fallback: str | None = None
    qualification: Literal["unqualified", "qualified", "unavailable"] = "unqualified"


@dataclass(frozen=True)
class PlatformHit:
    platform: str
    content_id: str
    url: str
    title: str
    text_preview: str
    source_type: str
    author_display: str | None = None
    published_at: str | None = None
    # A social post is an observation, never an official factual label.
    epistemic_kind: Literal["community_observation"] = "community_observation"

    def __post_init__(self) -> None:
        if not _public_url(self.url) or not self.content_id or not self.platform:
            raise ValueError("invalid_platform_hit")
        if self.epistemic_kind != "community_observation":
            raise ValueError("platform_hit_cannot_grant_authority")


@dataclass(frozen=True)
class PlatformRequest:
    request_id: str
    platform: str
    operation: PlatformOperation
    query_or_id: str
    limit: int
    deadline: float

    def __post_init__(self) -> None:
        if not self.request_id or not self.platform or not self.query_or_id.strip():
            raise ValueError("missing_request_identity")
        if self.operation not in {"search", "detail", "subtitles", "comments", "feed"}:
            raise ValueError("unsupported_operation")
        if not 1 <= self.limit <= 3 or not math.isfinite(self.deadline):
            raise ValueError("invalid_platform_budget")


@dataclass(frozen=True)
class PlatformBatch:
    request_id: str
    platform: str
    hits: tuple[PlatformHit, ...]
    status: Literal["ok", "empty", "auth_required", "unavailable", "cancelled", "deadline_exhausted"]
    reason: str = ""


class PlatformSearchProvider(Protocol):
    def search(self, request: PlatformRequest) -> PlatformBatch: ...


def validate_platform_batch(request: PlatformRequest, batch: PlatformBatch) -> PlatformBatch:
    if batch.status not in {"ok", "empty", "auth_required", "unavailable", "cancelled", "deadline_exhausted"}:
        raise ValueError("invalid_platform_status")
    if batch.request_id != request.request_id or batch.platform != request.platform:
        raise ValueError("platform_request_binding_mismatch")
    if len(batch.hits) > request.limit or any(hit.platform != request.platform for hit in batch.hits):
        raise ValueError("platform_hit_scope_mismatch")
    if (batch.status == "ok") != bool(batch.hits):
        raise ValueError("platform_status_content_mismatch")
    return batch


def platform_capability_registry() -> tuple[PlatformCapability, ...]:
    # Auth expectations are documentary hints; each operation stays unqualified
    # until local bounded evidence proves it, regardless of an upstream README.
    return (
        PlatformCapability("bilibili", "search", "anonymous", "bili-cli", "MediaCrawler"),
        PlatformCapability("bilibili", "detail", "anonymous", "bili-cli", "MediaCrawler"),
        PlatformCapability("bilibili", "subtitles", "optional_auth", "subtitle-specialist"),
        PlatformCapability("youtube", "search", "anonymous", "yt-dlp"),
        PlatformCapability("youtube", "subtitles", "optional_auth", "yt-dlp"),
        PlatformCapability("rss", "feed", "anonymous", "feedparser"),
        PlatformCapability("v2ex", "detail", "anonymous", "public-api"),
        PlatformCapability("v2ex", "feed", "anonymous", "public-api"),
        PlatformCapability("xhs", "search", "auth_bound", "xiaohongshu-mcp", "MediaCrawler", "unavailable"),
        PlatformCapability("zhihu", "search", "auth_bound", "MediaCrawler", qualification="unavailable"),
        PlatformCapability("reddit", "search", "auth_bound", "platform-specialist", qualification="unavailable"),
        PlatformCapability("twitter", "search", "auth_bound", "platform-specialist", qualification="unavailable"),
    )
