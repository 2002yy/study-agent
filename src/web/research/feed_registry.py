"""Small curated, verified feed-source registry (registry-assisted discovery).

Sources are curated and pre-verified; registration is a discovery shortcut, not an
evidence grant — a registered source's articles are still ordinary exploratory
bodies until separately verified.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FeedSource:
    source_id: str
    topic: str
    keywords: tuple[str, ...]
    feed_url: str
    nature: str
    operations: tuple[str, ...]
    qualification: str
    evidence: str


FEED_REGISTRY: tuple[FeedSource, ...] = (
    FeedSource(
        source_id="python-official-blog",
        topic="Python releases and the official Python blog",
        keywords=("python", "cpython", "pep", "python 3"),
        feed_url="https://blog.python.org/feeds/posts/default?alt=rss",
        nature="official_vendor_blog",
        operations=("feed",),
        qualification="qualified",
        evidence="B-Search-2B4 exp1 (2026-10-10): feed->10 entries->read 4379 chars (Python 3.15.0)",
    ),
)


def match_feeds(question: str) -> tuple[FeedSource, ...]:
    """Return registry sources whose keywords match the question (non-forcing)."""
    lowered = (question or "").casefold()
    return tuple(source for source in FEED_REGISTRY if any(k in lowered for k in source.keywords))
