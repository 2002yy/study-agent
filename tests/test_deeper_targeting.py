"""§36A deeper-page targeting: gap extraction, positive queries, ranking.

These tests freeze the behaviours the batch was defined around, including the
classes that must NOT trigger targeting (already-supports, background) and the
rule that discovery ranking never leaks into evidence semantics.
"""

from __future__ import annotations

from src.web.research.deeper_targeting import (
    AUTHORITY_MIRROR,
    AUTHORITY_OFFICIAL,
    AUTHORITY_TUTORIAL,
    AUTHORITY_UNKNOWN,
    GapHint,
    authority_class,
    discovery_score,
    gap_from_extraction,
    is_root_or_landing,
    missing_fact_terms,
    path_depth,
    rank_targeting_candidates,
    target_path_hit,
    targeted_query_terms,
    targeting_strategy,
)
from src.web.research.page_intent import infer_page_intent, query_variants


def test_class1_official_homepage_prefers_official_deep_docs() -> None:
    """Docker homepage: the official docs beat mirrors and tutorials.

    Root/landing pages rank last by design (§36A priority order), and a bare
    docs-subdomain root is still a root URL - the *deep* official page is what
    discovery must select.
    """

    ranked = rank_targeting_candidates(
        (
            "https://www.docker.com/",
            "https://www.runoob.com/docker/docker-tutorial.html",
            "https://docs.docker.com/docker-hub/usage/pulls/",
            "https://blog.csdn.net/someone/article/details/123",
            "https://docs.docker.com/",
        ),
        source_url="https://www.docker.com/",
        source_authority_class=AUTHORITY_OFFICIAL,
    )

    assert ranked[0] == "https://docs.docker.com/docker-hub/usage/pulls/"
    # Tutorials rank below same-official deep pages, but above bare roots.
    assert ranked.index("https://www.runoob.com/docker/docker-tutorial.html") < (
        ranked.index("https://www.docker.com/")
    )
    assert ranked[-1] == "https://www.docker.com/"


def test_class2_official_homepage_prefers_policy_support_page() -> None:
    """PostgreSQL homepage: versioning/support policy pages come first."""

    ranked = rank_targeting_candidates(
        (
            "https://www.postgresql.org/",
            "https://www.postgresql.org/support/versioning/",
            "https://www.runoob.com/postgresql/postgresql-tutorial.html",
        ),
        source_url="https://www.postgresql.org/",
        source_authority_class=AUTHORITY_OFFICIAL,
    )

    assert ranked[0] == "https://www.postgresql.org/support/versioning/"


def test_class3_official_homepage_prefers_spec_reference() -> None:
    """Python: PEP/reference pages outrank the marketing homepage."""

    ranked = rank_targeting_candidates(
        (
            "https://www.python.org/",
            "https://peps.python.org/pep-0703/",
            "https://docs.python.org/3/howto/free-threading-python.html",
        ),
        source_url="https://www.python.org/",
        source_authority_class=AUTHORITY_OFFICIAL,
    )

    assert ranked[0] in {
        "https://peps.python.org/pep-0703/",
        "https://docs.python.org/3/howto/free-threading-python.html",
    }
    assert ranked[-1] == "https://www.python.org/"


def test_class4_unofficial_tutorial_does_not_lock_into_its_own_domain() -> None:
    """Runoob must not win same-domain affinity; official docs must win."""

    source = "https://www.runoob.com/pytorch/transformer-model.html"
    ranked = rank_targeting_candidates(
        (
            "https://www.runoob.com/pytorch/transformer-model-detail.html",
            "https://arxiv.org/abs/1706.03762",
            "https://www.runoob.com/pytorch/pytorch-tutorial.html",
        ),
        source_url=source,
        source_authority_class=authority_class(source),
    )

    assert authority_class(source) == AUTHORITY_TUTORIAL
    assert ranked[0] == "https://arxiv.org/abs/1706.03762"
    # The tutorial domain is not treated as an authority signal.
    assert discovery_score(
        source + "-deeper",
        source_url=source,
        source_authority_class=AUTHORITY_TUTORIAL,
    ) < discovery_score(
        "https://www.runoob.com/pytorch/transformer-model-detail.html",
        source_url=source,
        source_authority_class=AUTHORITY_OFFICIAL,
    )


def test_class5_supports_never_triggers_targeting() -> None:
    assert (
        gap_from_extraction(
            relation="supports",
            locator="pull rate limits 100/200",
            anchored_spans=("pull rate limits 100/200",),
            caveats=("does not state the reference date",),
            source_url="https://docs.docker.com/docker-hub/usage/pulls/",
        )
        is None
    )


def test_class6_background_never_triggers_targeting() -> None:
    assert (
        gap_from_extraction(
            relation="background",
            locator="CommonJS history",
            anchored_spans=("CommonJS history",),
            caveats=("does not compare current module systems",),
            source_url="https://juejin.cn/post/7108410887052427301",
        )
        is None
    )


def test_class7_duplicate_urls_do_not_waste_a_followup_slot() -> None:
    ranked = rank_targeting_candidates(
        (
            "https://docs.docker.com/docker-hub/usage/pulls/",
            "https://docs.docker.com/docker-hub/usage/pulls/",
            "https://docs.docker.com/",
        ),
        source_url="https://www.docker.com/",
        source_authority_class=AUTHORITY_OFFICIAL,
    )

    assert ranked.count("https://docs.docker.com/docker-hub/usage/pulls/") == 1
    assert len(ranked) == 2


def test_class8_caveat_negation_is_never_searched_for() -> None:
    """The query targets the missing fact positively, not the caveat sentence."""

    caveat = (
        "The excerpt mentions Docker Hub pull volume but does not state any "
        "pull-rate limits for unauthenticated or authenticated users."
    )

    terms = missing_fact_terms(caveat)

    assert "pull-rate" in terms or "pull" in terms
    assert "unauthenticated" in terms
    for forbidden in (
        "not",
        "does",
        "no",
        "state",
        "mentions",
        "only",
        "without",
    ):
        assert forbidden not in terms


def test_gap_hint_builds_a_positive_bounded_query() -> None:
    gap = gap_from_extraction(
        relation="lead",
        locator="Docker Hub pull volume",
        anchored_spans=("Docker Hub pull volume",),
        caveats=(
            "The excerpt mentions Docker Hub pull volume but does not state any "
            "pull-rate limits for unauthenticated or authenticated users.",
        ),
        source_url="https://www.docker.com/",
        source_role="primary",
    )

    assert isinstance(gap, GapHint)
    # Authority is not guessed from the host: the server-owned primary role of
    # the source page is what makes it an authoritative source.
    assert gap.source_authority_class == AUTHORITY_OFFICIAL
    assert gap.targeting_strategy == "root_or_landing_page"
    terms = targeted_query_terms(gap, ("docker", "hub", "pull", "rate", "limits"))
    assert terms[0] == "docker"
    assert "unauthenticated" in terms
    assert all(term not in {"not", "does", "no", "state"} for term in terms)
    assert len(terms) <= 6
    # Diagnostics payload stays bounded and JSON-friendly.
    payload = gap.to_dict()
    assert payload["source_url"] == "https://www.docker.com/"
    assert payload["targeting_strategy"] == "root_or_landing_page"
    assert isinstance(payload["missing_fact_terms"], list)


def test_caveat_without_absence_clause_yields_no_junk_query_terms() -> None:
    """A source-quality caveat must not become query text."""

    gap = gap_from_extraction(
        relation="lead",
        locator="third-party tutorial page",
        anchored_spans=("third-party tutorial page",),
        caveats=(
            "Excerpt is a third-party tutorial page (runoob.com), not Docker's "
            "official documentation.",
        ),
        source_url="https://www.runoob.com/docker/docker-tutorial.html",
        source_role="independent_secondary",
    )

    assert isinstance(gap, GapHint)
    assert gap.missing_fact_terms == ()
    # With no missing-fact terms the query must fall back to claim terms and
    # page intent, and never reuse the caveat sentence.
    variants = query_variants(
        subject_terms=("docker", "hub", "pull"),
        missing_fact_terms=gap.missing_fact_terms,
        intent=infer_page_intent(claim_terms=("docker", "hub", "pull", "rate", "limits")),
    )
    assert variants
    for variant in variants:
        assert "runoob" not in variant
        assert "third-party" not in variant


def test_gap_hint_requires_usable_anchor_and_caveat() -> None:
    base = {
        "relation": "lead",
        "source_url": "https://example.test/doc",
        "source_role": "primary",
    }

    assert (
        gap_from_extraction(
            locator="",
            anchored_spans=(),
            caveats=("does not state the limit",),
            **base,
        )
        is None
    )
    assert (
        gap_from_extraction(
            locator="short",
            anchored_spans=(),
            caveats=("does not state the limit",),
            **base,
        )
        is None
    )
    assert (
        gap_from_extraction(
            locator="a long enough locator value",
            anchored_spans=(),
            caveats=(),
            **base,
        )
        is None
    )


def test_ranking_is_deterministic_for_identical_inputs() -> None:
    urls = (
        "https://docs.docker.com/docker-hub/usage/pulls/",
        "https://www.docker.com/",
        "https://blog.csdn.net/x/article/details/1",
        "https://docs.docker.com/docker-hub/",
    )

    first = rank_targeting_candidates(
        urls, source_url="https://www.docker.com/", source_authority_class=AUTHORITY_OFFICIAL
    )
    second = rank_targeting_candidates(
        tuple(reversed(urls)),
        source_url="https://www.docker.com/",
        source_authority_class=AUTHORITY_OFFICIAL,
    )

    assert first == second


def test_helper_predicates() -> None:
    # Unknown hosts are simply not penalised; authority is never guessed.
    assert authority_class("https://docs.docker.com/x") == AUTHORITY_UNKNOWN
    assert authority_class("https://docker.github.net.cn/x") == AUTHORITY_MIRROR
    assert authority_class("https://www.zhihu.com/x") == AUTHORITY_TUTORIAL
    assert path_depth("https://example.test/") == 0
    assert path_depth("https://example.test/a/b/c") >= 2
    assert is_root_or_landing("https://example.test/") is True
    assert is_root_or_landing("https://example.test/a/b/c") is False
    assert target_path_hit("https://x.test/docs/guide") is True
    assert target_path_hit("https://x.test/blog/hello") is False
    strategy = targeting_strategy(
        "https://docs.docker.com/docker-hub/usage/pulls/",
        source_url="https://www.docker.com/",
        source_authority_class=AUTHORITY_OFFICIAL,
    )
    assert strategy == "same_official_domain_deep_page"
