"""§63 tier-1.5 domain-targeted retrieval: proposal, sitemap harvest, step."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from src.web.research.domain_targeted import (
    DISCOVERY_METHOD_DOMAIN_TARGETED,
    DOMAIN_TARGETED_ENV,
    MAX_RANK_TERMS,
    build_search_query,
    claim_search_terms,
    domain_targeted_enabled,
    extract_candidate_links,
    parse_domain_proposal,
    parse_sitemap,
    prioritise_sitemap_children,
    rank_domain_urls,
    sitemap_urls,
)

DOCKER_SITEMAP = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://docs.docker.com/security/security-announcements/</loc></url>
  <url><loc>https://docs.docker.com/docker-hub/usage/pulls/</loc></url>
  <url><loc>https://docs.docker.com/reference/api/hub/latest/</loc></url>
  <url><loc>https://docs.docker.com/get-started/tutorials/run-an-app/</loc></url>
  <url><loc>https://other.example/docker-hub/usage/pulls/</loc></url>
</urlset>
"""

DOCKER_INDEX_SITEMAP = """<?xml version="1.0" encoding="UTF-8"?>
<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <sitemap><loc>https://redis.io/sitemap/blog-1.xml</loc></sitemap>
  <sitemap><loc>https://redis.io/sitemap/pages.xml</loc></sitemap>
  <sitemap><loc>https://redis.io/sitemap/routes.xml</loc></sitemap>
</sitemapindex>
"""

HUB_HTML = """
<html><body>
<a href="/docker-hub/usage/pulls/">Pull usage and limits</a>
<a href="https://other.example/pull-limits">External</a>
<a href="#fragment">Frag</a>
<a href="mailto:x@y.z">Mail</a>
<a href="/docker-hub/usage/pulls/">Duplicate</a>
</body></html>
"""

CLAIM_TEXT = "Docker Hub pull-rate limits for unauthenticated users"


def test_flag_defaults_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(DOMAIN_TARGETED_ENV, raising=False)
    assert domain_targeted_enabled() is False
    monkeypatch.setenv(DOMAIN_TARGETED_ENV, "on")
    assert domain_targeted_enabled() is True


def test_domain_parser_is_strict_and_bounded() -> None:
    assert parse_domain_proposal(
        {"domains": ["https://docs.docker.com/docker-hub/", "docs.docker.com", "bad", "example.org"]}
    ) == ["docs.docker.com", "example.org"]
    with pytest.raises(ValueError):
        parse_domain_proposal({"domains": "nope"})
    with pytest.raises(ValueError):
        parse_domain_proposal(["not-an-object"])


def test_claim_terms_and_query() -> None:
    terms = claim_search_terms(CLAIM_TEXT)
    assert "pull-rate" in terms
    assert "for" not in terms
    assert build_search_query(CLAIM_TEXT) == " ".join(terms)


def test_sitemap_urls_are_deterministic() -> None:
    assert sitemap_urls("docs.docker.com") == [
        "https://docs.docker.com/sitemap.xml",
        "https://docs.docker.com/sitemap_index.xml",
    ]
    assert sitemap_urls("bad") == []


def test_parse_sitemap_urlset_and_index() -> None:
    kind, locations = parse_sitemap(DOCKER_SITEMAP)
    assert kind == "urlset"
    assert "https://docs.docker.com/docker-hub/usage/pulls/" in locations
    index_kind, children = parse_sitemap(DOCKER_INDEX_SITEMAP)
    assert index_kind == "index"
    assert len(children) == 3
    assert parse_sitemap("") == ("empty", [])


def test_sitemap_children_prioritise_docs_over_blog() -> None:
    ranked = prioritise_sitemap_children(
        [
            "https://redis.io/sitemap/blog-1.xml",
            "https://redis.io/sitemap/routes.xml",
            "https://redis.io/sitemap/pages.xml",
        ],
        limit=2,
    )
    assert "https://redis.io/sitemap/routes.xml" in ranked
    assert "https://redis.io/sitemap/pages.xml" in ranked
    assert "https://redis.io/sitemap/blog-1.xml" not in ranked


def test_rank_domain_urls_finds_the_deep_target_first() -> None:
    _kind, locations = parse_sitemap(DOCKER_SITEMAP)
    ranked = rank_domain_urls(
        locations, domain="docs.docker.com", terms=claim_search_terms(CLAIM_TEXT)
    )
    assert ranked[0] == "https://docs.docker.com/docker-hub/usage/pulls"
    assert all("other.example" not in url for url in ranked)


def test_ranking_used_the_real_run_claim_text() -> None:
    """Regression for the observed run: generic pages outranked the deep target
    when the subject entity was dropped by the 6-term cap and plural pairs
    double-counted."""

    locations = [
        "https://docs.example.com/ai/gordon/usage-limits",
        "https://docs.example.com/guides/admin-user-management",
        "https://docs.example.com/accounts/individual/deactivate-user-account",
        "https://docs.example.com/docker-hub/usage/pulls",
        "https://docs.example.com/reference/cli/docker/pull",
    ]
    question = (
        "what pull-rate limits apply to unauthenticated users and "
        "authenticated Personal users on Docker Hub?"
    )
    terms = claim_search_terms(question, limit=MAX_RANK_TERMS)
    assert "docker" in terms and "hub" in terms
    ranked = rank_domain_urls(
        locations, domain="docs.example.com", terms=terms
    )
    assert ranked[0] == "https://docs.example.com/docker-hub/usage/pulls"


def test_generic_tokens_are_not_privileged_over_the_subject() -> None:
    """Rare-but-empty claim words must not outrank the on-topic deep page."""

    locations = [
        f"https://docs.example.com/docker/guide-{i}" for i in range(10)
    ] + [
        "https://docs.example.com/trusted-content/official-images",
        "https://docs.example.com/docker-hub/usage/pulls",
    ]
    terms = [
        "According",
        "to",
        "Docker's",
        "current",
        "official",
        "documentation",
        "pull-rate",
        "limits",
        "apply",
    ]
    ranked = rank_domain_urls(
        locations, domain="docs.example.com", terms=terms
    )
    assert ranked[0] == "https://docs.example.com/docker-hub/usage/pulls"


def test_anchor_extraction_filters_and_ranks() -> None:
    links = extract_candidate_links(
        HUB_HTML, domain="docs.docker.com", terms=claim_search_terms(CLAIM_TEXT)
    )
    assert links == ["https://docs.docker.com/docker-hub/usage/pulls"]
    assert len(extract_candidate_links(HUB_HTML, domain="docs.docker.com", terms=["x"])) == 0


# ---------------------------------------------------------------------------
# Runtime step with injected collaborators.
# ---------------------------------------------------------------------------


def _runtime_state_and_claim():
    from src.web.research.contracts import (
        EvidenceGap,
        EvidenceRequirement,
        ResearchBudget,
        ResearchClaim,
        ResearchQuestion,
    )
    from src.web.research.state import build_research_state

    question = ResearchQuestion(id="q1", question_surface="q")
    claim = ResearchClaim(
        id="claim_1",
        question_id="q1",
        text=CLAIM_TEXT,
        kind="factual",
        priority="critical",
        state="pending",
        evidence_requirement=EvidenceRequirement(),
    )
    gap = EvidenceGap(id="gap_1", claim_id="claim_1", gap_type="missing_fact")
    state = build_research_state(
        mode="active",
        questions=(question,),
        claims=(claim,),
        evidence=(),
        evidence_links=(),
        source_clusters=(),
        gaps=(gap,),
        conflict_gaps=(),
        budget=ResearchBudget(
            max_candidates=20,
            max_reads=8,
            soft_timeout_seconds=45,
            hard_timeout_seconds=60,
            max_total_chars=16000,
        ),
        reference_date="2026-09-21",
        known_evidence_ids=(),
    )
    return state, claim


def _runtime_cursor():
    from src.web.research.runtime import (
        ResearchRuntimeCursor,
        RuntimeCandidate,
        RuntimePlannedQuery,
        RuntimeReadOutcome,
    )

    return ResearchRuntimeCursor(
        candidates=(
            RuntimeCandidate(
                id="candidate_search_1",
                url="https://www.docker.com/",
                title="Docker",
                query_ids=("q1",),
                first_seen_rank=0,
            ),
        ),
        read_outcomes=(
            RuntimeReadOutcome(candidate_id="candidate_search_1", status="success"),
        ),
        planned_queries=(
            RuntimePlannedQuery(
                id="q1",
                gap_id="gap_1",
                claim_id="claim_1",
                intent="fact",
                query="docker pull limits",
            ),
        ),
    )


@dataclass
class _Diagnostics:
    relevance: str = "topic_only"


class _Gateway:
    def __init__(self, domains: list[str]) -> None:
        self.domains = domains
        self.calls = 0

    def complete_structured(self, **kwargs):
        from src.web.research.model_gateway import ResearchModelResult

        self.calls += 1
        return ResearchModelResult(status="completed", value=list(self.domains), audits=())


def test_step_adds_verified_domain_targeted_candidate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.application.active_research_runtime import _domain_targeted_step

    monkeypatch.setenv(DOMAIN_TARGETED_ENV, "on")
    state, claim = _runtime_state_and_claim()
    gateway = _Gateway(["docs.docker.com"])
    target = "https://docs.docker.com/docker-hub/usage/pulls"

    def fetch_text(url: str):
        if url.endswith("/sitemap.xml"):
            return DOCKER_SITEMAP, url, "application/xml", ""
        return "", "", "", "unexpected"

    reads: list[str] = []

    def read_fn(url: str, *, max_chars: int):
        reads.append(url)
        if url == target:
            return {"ok": True, "content": "pull limits", "title": "Pull usage and limits"}
        return {"ok": False, "error": "unsafe_or_empty_url"}

    context: dict = {}
    cursor = _domain_targeted_step(
        cursor=_runtime_cursor(),
        state=state,
        claim=claim,
        assessments={"candidate_search_1": _Diagnostics("topic_only")},
        model_gateway=gateway,
        fetch_text=fetch_text,
        read_fn=read_fn,
        context=context,
        run_id="run_1",
        wave_index=1,
        timeout_seconds=5.0,
        targeted_claim_ids=[],
        seconds_left=lambda: 30.0,
    )
    assert gateway.calls == 1
    added = [
        item
        for item in cursor.candidates
        if item.discovery_method == DISCOVERY_METHOD_DOMAIN_TARGETED
    ]
    assert [item.url for item in added] == [target]
    record = context["claim_engine_metrics"]["domain_targeted"][-1]
    assert record["domains"] == ["docs.docker.com"]
    assert record["inventory_kind"] == "urlset"
    assert record["verified"] == [target]
    assert context["claim_engine_metrics"]["orchestration_model_calls"] == 1


def test_step_follows_a_sitemap_index_child(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.application.active_research_runtime import _domain_targeted_step

    monkeypatch.setenv(DOMAIN_TARGETED_ENV, "on")
    state, claim = _runtime_state_and_claim()
    gateway = _Gateway(["docs.docker.com"])
    target = "https://docs.docker.com/docker-hub/usage/pulls"

    def fetch_text(url: str):
        if url.endswith("/sitemap.xml"):
            return DOCKER_INDEX_SITEMAP, url, "application/xml", ""
        if url.endswith("pages.xml"):
            return DOCKER_SITEMAP, url, "application/xml", ""
        return "", "", "", "not_expected"

    context: dict = {}
    cursor = _domain_targeted_step(
        cursor=_runtime_cursor(),
        state=state,
        claim=claim,
        assessments={},
        model_gateway=gateway,
        fetch_text=fetch_text,
        read_fn=lambda url, *, max_chars: {"ok": True, "content": "x"},
        context=context,
        run_id="run_1",
        wave_index=1,
        timeout_seconds=5.0,
        targeted_claim_ids=[],
        seconds_left=lambda: 30.0,
    )
    record = context["claim_engine_metrics"]["domain_targeted"][-1]
    assert record["inventory_kind"] == "index"
    assert record["verified"][0] == target
    assert len(record["verified"]) <= 3
    assert any(item.url == target for item in cursor.candidates)


def test_step_is_silent_when_support_exists(monkeypatch: pytest.MonkeyPatch) -> None:
    from src.application.active_research_runtime import _domain_targeted_step

    monkeypatch.setenv(DOMAIN_TARGETED_ENV, "on")
    state = _state_with_support("claim_1")
    claim = state.claims[0]
    gateway = _Gateway(["docs.docker.com"])
    cursor = _domain_targeted_step(
        cursor=_runtime_cursor(),
        state=state,
        claim=claim,
        assessments={},
        model_gateway=gateway,
        fetch_text=lambda url: (DOCKER_SITEMAP, url, "application/xml", ""),
        read_fn=lambda url, *, max_chars: {"ok": True, "content": "x"},
        context={},
        run_id="run_1",
        wave_index=2,
        timeout_seconds=5.0,
        targeted_claim_ids=[],
        seconds_left=lambda: 30.0,
    )
    assert gateway.calls == 0
    assert len(cursor.candidates) == 1


def test_step_never_runs_twice_for_the_same_claim(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.application.active_research_runtime import _domain_targeted_step

    monkeypatch.setenv(DOMAIN_TARGETED_ENV, "on")
    state, claim = _runtime_state_and_claim()
    gateway = _Gateway(["docs.docker.com"])
    _domain_targeted_step(
        cursor=_runtime_cursor(),
        state=state,
        claim=claim,
        assessments={},
        model_gateway=gateway,
        fetch_text=lambda url: (DOCKER_SITEMAP, url, "application/xml", ""),
        read_fn=lambda url, *, max_chars: {"ok": True, "content": "x"},
        context={},
        run_id="run_1",
        wave_index=1,
        timeout_seconds=5.0,
        targeted_claim_ids=["claim_1"],
        seconds_left=lambda: 30.0,
    )
    assert gateway.calls == 0


def test_it_reads_no_content_from_the_inventory_fetches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.application.active_research_runtime import _domain_targeted_step

    monkeypatch.setenv(DOMAIN_TARGETED_ENV, "on")
    state, claim = _runtime_state_and_claim()
    gateway = _Gateway(["docs.docker.com"])
    reads: list[str] = []

    def read_fn(url: str, *, max_chars: int):
        reads.append(url)
        return {"ok": False, "error": "unsafe_or_empty_url"}

    context: dict = {}
    _domain_targeted_step(
        cursor=_runtime_cursor(),
        state=state,
        claim=claim,
        assessments={},
        model_gateway=gateway,
        fetch_text=lambda url: (DOCKER_SITEMAP, url, "application/xml", ""),
        read_fn=read_fn,
        context=context,
        run_id="run_1",
        wave_index=1,
        timeout_seconds=5.0,
        targeted_claim_ids=[],
        seconds_left=lambda: 30.0,
    )
    record = context["claim_engine_metrics"]["domain_targeted"][-1]
    assert record["inventory_kind"] == "urlset"
    assert record["inventory_locations"] == 5
    assert record["added_candidate_ids"] == []
    assert any(row["reason"] == "read_failed" for row in record["dropped"])
    assert len(reads) >= 1


def test_window_guard_skips_inventory_fetches(monkeypatch: pytest.MonkeyPatch) -> None:
    from src.application.active_research_runtime import _domain_targeted_step

    monkeypatch.setenv(DOMAIN_TARGETED_ENV, "on")
    state, claim = _runtime_state_and_claim()
    gateway = _Gateway(["docs.docker.com", "hub.docker.com"])
    attempts: list[str] = []

    def fetch_text(url: str):
        attempts.append(url)
        return DOCKER_SITEMAP, url, "application/xml", ""

    context: dict = {}
    _domain_targeted_step(
        cursor=_runtime_cursor(),
        state=state,
        claim=claim,
        assessments={},
        model_gateway=gateway,
        fetch_text=fetch_text,
        read_fn=lambda url, *, max_chars: {"ok": True, "content": "x"},
        context=context,
        run_id="run_1",
        wave_index=1,
        timeout_seconds=5.0,
        targeted_claim_ids=[],
        seconds_left=lambda: 5.0,
    )
    record = context["claim_engine_metrics"]["domain_targeted"][-1]
    assert attempts == []
    assert record["search_urls"] == []
    assert {row["reason"] for row in record["dropped"]} == {"skipped_by_window"}


def _state_with_support(claim_id: str):
    from src.domain.evidence import ClaimEvidenceLinkV1
    from src.web.research.contracts import (
        EvidenceCluster,
        EvidenceGap,
        EvidenceRequirement,
        ResearchBudget,
        ResearchClaim,
        ResearchClaimEvidenceLink,
        ResearchEvidence,
        ResearchQuestion,
    )
    from src.web.research.state import build_research_state

    question = ResearchQuestion(id="q1", question_surface="q")
    claim = ResearchClaim(
        id=claim_id,
        question_id="q1",
        text=CLAIM_TEXT,
        kind="factual",
        priority="critical",
        state="pending",
        evidence_requirement=EvidenceRequirement(),
    )
    gap = EvidenceGap(id="gap_1", claim_id=claim_id, gap_type="missing_fact")
    return build_research_state(
        mode="active",
        questions=(question,),
        claims=(claim,),
        evidence=(
            ResearchEvidence(
                evidence_id="ev_x",
                locator="pull limits",
                anchored_spans=("pull limits",),
                lifecycle_status="read",
                extraction_status="eligible",
            ),
        ),
        evidence_links=(
            ResearchClaimEvidenceLink(
                link=ClaimEvidenceLinkV1(
                    claim_id=claim_id,
                    evidence_id="ev_x",
                    support_type="supports",
                    confidence=0.9,
                ),
                source_role="primary",
                source_cluster_id="c1",
            ),
        ),
        source_clusters=(EvidenceCluster(id="c1", evidence_ids=("ev_x",)),),
        gaps=(gap,),
        conflict_gaps=(),
        budget=ResearchBudget(
            max_candidates=20,
            max_reads=8,
            soft_timeout_seconds=45,
            hard_timeout_seconds=60,
            max_total_chars=16000,
        ),
        reference_date="2026-09-21",
        known_evidence_ids=("ev_x",),
    )
