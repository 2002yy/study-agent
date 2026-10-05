"""§175 ③: release/download pages are preferred, but only as a ranking tie-break."""

from __future__ import annotations

from src.web.research.domain_targeted import rank_domain_urls


def test_release_path_wins_among_equal_term_matches():
    urls = [
        "https://www.python.org/about/python-3140/",
        "https://www.python.org/downloads/release/python-3140/",
    ]
    ranked = rank_domain_urls(
        urls, domain="python.org", terms=["python", "3140"], limit=5
    )
    assert ranked[0].endswith("/downloads/release/python-3140")


def test_changelog_is_also_preferred():
    urls = [
        "https://x.dev/notes/v2/",
        "https://x.dev/changelog/v2/",
    ]
    ranked = rank_domain_urls(urls, domain="x.dev", terms=["v2"], limit=5)
    assert ranked[0].endswith("/changelog/v2")


def test_term_matches_still_outrank_release_affinity():
    urls = [
        "https://x.dev/release/other/",
        "https://x.dev/guide/alpha/beta/",
    ]
    ranked = rank_domain_urls(
        urls, domain="x.dev", terms=["alpha", "beta"], limit=5
    )
    # The release path has affinity but only one weak stem; the deep page matches
    # both claim terms and must still win.
    assert ranked[0].endswith("/guide/alpha/beta")


def test_release_affinity_is_deterministic():
    urls = [
        "https://x.dev/releases/tag/v2/",
        "https://x.dev/downloads/v2/",
    ]
    first = rank_domain_urls(urls, domain="x.dev", terms=["v2"], limit=5)
    second = rank_domain_urls(list(reversed(urls)), domain="x.dev", terms=["v2"], limit=5)
    assert first == second


def test_no_term_match_still_yields_nothing():
    ranked = rank_domain_urls(
        ["https://x.dev/downloads/release/"],
        domain="x.dev",
        terms=["unrelated"],
        limit=5,
    )
    assert ranked == []
