"""Minimal candidate records shared by read scheduling and projection tests."""

from src.web.research.candidate_pool import CandidatePoolItem


def read_candidate(
    candidate_id: str = "target",
    *,
    url: str = "https://example.org/article",
    title: str = "article",
    source: str = "",
) -> CandidatePoolItem:
    return CandidatePoolItem(
        id=candidate_id,
        url=url,
        canonical_url=url,
        title=title,
        snippet="",
        source=source,
        published_at="",
        query_ids=(),
        intents=(),
        providers=(),
        first_seen_rank=0,
    )
