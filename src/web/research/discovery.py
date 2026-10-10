"""Discovery-only contracts. Provider previews never authorize answer evidence."""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any, Literal, Protocol
from urllib.parse import urlsplit, urlunsplit

from src.web.tool_evidence import _public_url

DiscoveryIntent = Literal["general", "official_docs", "release", "current", "research"]


@dataclass(frozen=True)
class DiscoveryRequest:
    query: str
    intent: DiscoveryIntent
    limit: int
    deadline: float
    preferred_domains: tuple[str, ...] = ()
    excluded_domains: tuple[str, ...] = ()
    freshness_days: int | None = None
    live: bool = False

    def __post_init__(self) -> None:
        if not self.query.strip() or len(self.query) > 2000:
            raise ValueError("invalid_query")
        if self.intent not in {"general", "official_docs", "release", "current", "research"}:
            raise ValueError("invalid_intent")
        if not 1 <= self.limit <= 24 or not math.isfinite(self.deadline):
            raise ValueError("invalid_budget")
        if self.freshness_days is not None and self.freshness_days < 0:
            raise ValueError("invalid_freshness")


@dataclass(frozen=True)
class DiscoveryHit:
    url: str
    title: str
    snippet: str
    provider: str
    provider_rank: int
    published_at: str | None = None
    provider_score: float | None = None
    highlights: tuple[str, ...] = ()
    provider_provenance: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not _public_url(self.url) or not self.title.strip() or self.provider_rank < 1:
            raise ValueError("invalid_discovery_hit")

    @property
    def canonical_url(self) -> str:
        # Identity only; redirects and authority still belong to the reader.
        parts = urlsplit(self.url)
        return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path, parts.query, ""))


@dataclass(frozen=True)
class DiscoveryBatch:
    hits: tuple[DiscoveryHit, ...]
    provider: str
    status: Literal["ok", "empty", "unavailable"]
    reason: str = ""
    provider_errors: tuple[str, ...] = ()


class DiscoveryProvider(Protocol):
    def search(self, request: DiscoveryRequest) -> DiscoveryBatch: ...


class LegacySearch(Protocol):
    def search_exact(self, query: str, *, max_results: int, deadline: float) -> dict[str, Any]: ...


class LegacyDiscoveryAdapter:
    """Wrap a run-owned existing provider; retain its circuit/deadline policy.

    This adapter is unregistered. Runtime behavior remains the existing legacy
    path until a later explicit router cutover passes qualification.
    """

    def __init__(self, legacy: LegacySearch) -> None:
        self.legacy = legacy

    def search(self, request: DiscoveryRequest) -> DiscoveryBatch:
        if request.preferred_domains or request.excluded_domains or request.freshness_days is not None or request.live:
            return DiscoveryBatch((), "legacy", "unavailable", "unsupported_request_constraints")
        value = self.legacy.search_exact(request.query, max_results=request.limit, deadline=request.deadline)
        hits = []
        for rank, item in enumerate(value.get("results") or [], 1):
            if not isinstance(item, dict):
                continue
            raw_providers = item.get("providers")
            providers = tuple(str(provider) for provider in raw_providers) if isinstance(raw_providers, (list, tuple)) else (str(item.get("source") or "legacy"),)
            providers = providers or ("legacy",)
            try:
                hits.append(DiscoveryHit(url=str(item.get("url") or item.get("link") or ""),
                                         title=str(item.get("title") or ""), snippet=str(item.get("snippet") or ""),
                                         provider=str(providers[0]), provider_rank=rank,
                                         published_at=str(item.get("published_at") or "") or None,
                                         provider_provenance=providers))
            except ValueError:
                continue
        status: Literal["ok", "empty", "unavailable"] = "ok" if hits else "unavailable" if value.get("status") == "unavailable" else "empty"
        return DiscoveryBatch(tuple(hits[:request.limit]), "legacy", status, str(value.get("reason") or ""),
                              tuple(str(error) for error in value.get("provider_errors") or []))
