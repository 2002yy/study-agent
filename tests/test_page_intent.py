"""§36B slice 1: page-intent inference, bounded query variants, ranking keys."""

from __future__ import annotations

from src.web.research.page_intent import (
    INTENT_KIND_ORDER,
    infer_page_intent,
    lexical_targeting_score,
    query_variants,
    rank_search_results,
    selection_reason,
)


def test_class1_rate_limit_maps_to_limit_policy() -> None:
    intent = infer_page_intent(
        claim_terms=("docker", "hub", "pull", "rate", "limits"),
        missing_fact_terms=("pull-rate", "limits", "unauthenticated"),
    )

    assert intent is not None
    assert intent.kind == "limit_policy"
    assert "limits" in intent.path_terms


def test_class2_supported_versions_map_to_support_lifecycle() -> None:
    intent = infer_page_intent(
        claim_terms=("postgresql", "supported", "versions"),
        missing_fact_terms=("versioning", "eol"),
    )

    assert intent is not None
    assert intent.kind == "support_lifecycle"


def test_class3_free_threaded_maps_to_feature_status() -> None:
    intent = infer_page_intent(
        claim_terms=("python", "free-threaded", "status"),
        missing_fact_terms=("experimental", "stable"),
    )

    assert intent is not None
    assert intent.kind == "feature_status"


def test_class4_original_paper_maps_to_original_source() -> None:
    intent = infer_page_intent(
        claim_terms=("original", "paper", "optimizer", "adam"),
        missing_fact_terms=("learning-rate", "schedule"),
    )

    assert intent is not None
    assert intent.kind == "original_source"


def test_intent_is_none_without_evidence_of_a_page_kind() -> None:
    assert infer_page_intent(claim_terms=(), missing_fact_terms=()) is None
    assert (
        infer_page_intent(claim_terms=("foo", "bar"), missing_fact_terms=("baz",))
        is None
    )


def test_intent_matching_respects_token_boundaries() -> None:
    """``learning-rate`` must not masquerade as a ``rate`` (limit) claim."""

    assert (
        infer_page_intent(
            claim_terms=("optimizer", "learning-rate", "schedule"),
            missing_fact_terms=("adam", "beta"),
        )
        is None
    )
    assert (
        infer_page_intent(
            claim_terms=("consumer", "prices", "inflation"),
            missing_fact_terms=("cpi", "month"),
        )
        is None
    )
    # Real limit/pricing claims still classify.
    limit_intent = infer_page_intent(claim_terms=("rate", "limits"))
    assert limit_intent is not None and limit_intent.kind == "limit_policy"
    pricing_intent = infer_page_intent(claim_terms=("pricing", "plan"))
    assert pricing_intent is not None and pricing_intent.kind == "pricing_plan"


def test_class5_query_variants_never_contain_negation() -> None:
    intent = infer_page_intent(
        claim_terms=("docker", "hub", "pull", "rate", "limits"),
        missing_fact_terms=("pull-rate", "limits"),
    )

    variants = query_variants(
        subject_terms=("docker", "hub", "pull"),
        missing_fact_terms=("pull-rate", "limits", "not", "does"),
        intent=intent,
    )

    assert variants
    for variant in variants:
        for forbidden in ("not", "does", "no ", "without"):
            assert forbidden not in variant


def test_class6_query_variants_are_deduplicated() -> None:
    variants = query_variants(
        subject_terms=("docker", "hub"),
        missing_fact_terms=("limits", "docker"),
        intent=None,
        variant_limit=3,
    )

    assert len(variants) == len(set(variants))


def test_class7_variant_count_has_a_hard_cap() -> None:
    intent = infer_page_intent(claim_terms=("limits",), missing_fact_terms=("quota",))

    assert len(query_variants(
        subject_terms=("a", "b"), missing_fact_terms=("limits",), intent=intent
    )) <= 3
    assert len(query_variants(
        subject_terms=("a", "b"),
        missing_fact_terms=("limits",),
        intent=intent,
        variant_limit=2,
    )) <= 2
    assert query_variants(
        subject_terms=("a",),
        missing_fact_terms=("limits",),
        intent=intent,
        variant_limit=0,
    ) == ()


def test_class8_variants_are_hints_inside_existing_slots() -> None:
    """The helper itself never allocates budget: it only returns bounded hints.

    §36B is explicit that diversification must happen inside the frozen
    follow-up slots, so the pure contract is "at most N variants", not "one more
    search per variant".
    """

    intent = infer_page_intent(claim_terms=("limits",), missing_fact_terms=("quota",))
    variants = query_variants(
        subject_terms=("docker", "hub"),
        missing_fact_terms=("limits", "quota"),
        intent=intent,
        variant_limit=3,
    )

    assert 1 <= len(variants) <= 3
    assert all(isinstance(item, str) and item for item in variants)


def test_class9_title_match_outranks_snippet_only_match() -> None:
    ranked = rank_search_results(
        [
            {"url": "https://x.test/a", "title": "Unrelated", "snippet": "pull limits"},
            {
                "url": "https://x.test/b",
                "title": "Docker Hub pull limits",
                "snippet": "",
            },
        ],
        missing_fact_terms=("pull", "limits"),
        intent=None,
    )

    assert ranked == ("https://x.test/b", "https://x.test/a")


def test_class10_snippet_intent_match_is_used_when_title_is_silent() -> None:
    ranked = rank_search_results(
        [
            {"url": "https://x.test/a", "title": "Welcome", "snippet": "about us"},
            {
                "url": "https://x.test/b",
                "title": "Welcome",
                "snippet": "rate-limit policy for unauthenticated users",
            },
        ],
        missing_fact_terms=("limits",),
        intent=infer_page_intent(claim_terms=("rate", "limits")),
    )

    assert ranked[0] == "https://x.test/b"


def test_class11_authority_outranks_generic_lexical_near_hit() -> None:
    ranked = rank_search_results(
        [
            {
                "url": "https://www.runoob.com/docker/docker-limits.html",
                "title": "Docker pull limits rate limits",
                "snippet": "pull limits rate limits quota",
            },
            {
                "url": "https://docs.docker.com/docker-hub/usage/pulls/",
                "title": "Pull usage",
                "snippet": "",
            },
        ],
        missing_fact_terms=("pull", "limits", "quota"),
        intent=None,
        authoritative_urls=("https://docs.docker.com/docker-hub/usage/pulls/",),
    )

    assert ranked[0] == "https://docs.docker.com/docker-hub/usage/pulls/"


def test_regression_tutorial_lexical_overlap_cannot_beat_authoritative() -> None:
    """A tutorial that repeats every keyword must not displace the real page."""

    tutorial = {
        "url": "https://www.runoob.com/postgresql/supported-versions.html",
        "title": "PostgreSQL supported versions eol lifecycle",
        "snippet": "supported versions eol lifecycle support policy",
    }
    official = {
        "url": "https://www.postgresql.org/support/versioning/",
        "title": "Versioning policy",
        "snippet": "",
    }

    ranked = rank_search_results(
        [tutorial, official],
        missing_fact_terms=("supported", "versions", "eol"),
        intent=infer_page_intent(claim_terms=("supported", "versions")),
        authoritative_urls=(official["url"],),
    )

    assert ranked[0] == official["url"]


def test_class12_ranking_is_deterministic_for_identical_inputs() -> None:
    rows = [
        {"url": "https://a.test/x", "title": "limits", "snippet": ""},
        {"url": "https://b.test/y", "title": "", "snippet": "limits policy"},
        {"url": "https://c.test/z", "title": "other", "snippet": ""},
    ]

    first = rank_search_results(rows, missing_fact_terms=("limits",), intent=None)
    second = rank_search_results(
        list(reversed(rows)), missing_fact_terms=("limits",), intent=None
    )

    assert first == second


def test_lexical_score_and_selection_reason_are_bounded() -> None:
    score = lexical_targeting_score(
        title="Docker Hub pull limits",
        snippet="rate-limit policy",
        missing_fact_terms=("pull", "limits", "policy"),
        intent=infer_page_intent(claim_terms=("rate", "limits")),
    )

    assert score["candidate_title_match"] == 2
    assert score["candidate_intent_match"] >= 1
    assert selection_reason(
        authoritative=True, title_match=2, intent_match=1
    ) == "authority+missing_fact_title_match+page_intent_match"
    assert selection_reason(
        authoritative=False, title_match=0, intent_match=0
    ) == "fallback_order"


def test_taxonomy_is_bounded_and_ordered() -> None:
    assert len(INTENT_KIND_ORDER) <= 12
    assert INTENT_KIND_ORDER[0] == "limit_policy"
    assert set(INTENT_KIND_ORDER) == {
        "limit_policy",
        "support_lifecycle",
        "feature_status",
        "spec_standard",
        "api_reference",
        "pricing_plan",
        "security_advisory",
        "benchmark_performance",
        "original_source",
    }
