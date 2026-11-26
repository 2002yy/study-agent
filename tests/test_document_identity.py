"""Same document in another UI language is one source, not five."""

from __future__ import annotations

from src.news.url_normalizer import canonicalize_url, document_identity
from src.web.research.candidate_pool import merge_candidate_pool
from src.web.research.gap_planner import GapSearchIntent, PlannedGapQuery
from src.web.source_assessment import assess_sources


def test_language_variants_share_an_identity_but_versions_and_hosts_do_not():
    zh = "https://docs.example.org/zh-cn/4.x/guide/install.html"
    ja = "https://docs.example.org/ja/4.x/guide/install.html"
    older = "https://docs.example.org/en/4.5/guide/install.html"
    stable = "https://docs.example.org/en/stable/guide/install.html"
    latest = "https://docs.example.org/en/latest/guide/install.html"
    mirror = "https://docs-ja.example.net/ja/4.x/guide/install.html"
    other_project = "https://project-b.org/en/4.x/guide/install.html"

    assert document_identity(zh) == document_identity(ja)
    # A channel is not a synonym for another channel or for a concrete version.
    assert document_identity(stable) != document_identity(latest)
    assert document_identity(zh) != document_identity(older)
    # Another host may be a mirror with different content, or a different project.
    assert document_identity(zh) != document_identity(mirror)
    assert document_identity(zh) != document_identity(other_project)


def test_a_language_like_first_segment_without_a_version_is_left_alone():
    url = "https://example.org/it/contact"

    assert document_identity(url) == canonicalize_url(url)


def test_assessment_drops_the_language_duplicate():
    selected, rejected = assess_sources(
        [
            {"title": "使用 Jolt Physics", "url": "https://docs.example.org/zh-cn/4.x/jolt.html"},
            {"title": "Using Jolt Physics", "url": "https://docs.example.org/en/4.x/jolt.html"},
        ],
        canonical_query="Jolt Physics",
    )

    assert len(selected) == 1
    assert rejected
    assert rejected[0]["assessment"]["rejection_reason"] == "duplicate"


def test_candidate_pool_keeps_one_language_variant():
    query = PlannedGapQuery(
        id="gap-1:primary",
        gap_id="gap-1",
        claim_id="claim-1",
        intent=GapSearchIntent.PRIMARY,
        query="jolt guide",
        desired_source_role="primary",
    )
    items = merge_candidate_pool([
        (
            query,
            (
                {"title": "使用 Jolt Physics", "url": "https://docs.example.org/zh-cn/4.x/jolt.html"},
                {"title": "Using Jolt Physics", "url": "https://docs.example.org/en/4.x/jolt.html"},
                {"title": "Using Jolt Physics 4.5", "url": "https://docs.example.org/en/4.5/jolt.html"},
            ),
            ("deepseek",),
        )
    ])

    assert len(items) == 2
    assert items[0].canonical_url.endswith("/zh-cn/4.x/jolt.html")
    assert items[1].canonical_url.endswith("/en/4.5/jolt.html")
