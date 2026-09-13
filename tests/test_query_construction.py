"""Query Construction Hardening regression fixtures.

These five surfaces are the real bad queries found in the off_target audit
(2026-09-13). The goal is not one blessed output string: it is that the planner
can never again emit a claim's grammar fragment as a standalone search
expression.
"""

from __future__ import annotations

import pytest

from src.web.research.contracts import EvidenceGap, EvidenceRequirement, ResearchClaim
from src.web.research.gap_planner import GapQueryBatch, plan_gap_queries

# (label, question, claim_text) - claim_text is what the runtime really had.
AUDIT_FIXTURES = (
    (
        "docker-pull-rate",
        "According to Docker's current official documentation, what pull-rate limits "
        "apply to unauthenticated users and authenticated Personal users on Docker Hub?",
        "pull-rate limits apply unauthenticated users authenticated Personal users on Docker Hub",
    ),
    (
        "postgresql-oldest-version",
        "What is the oldest supported major version of PostgreSQL that has not reached "
        "end of life as of 2026?",
        "oldest supported major version reach end life 2026",
    ),
    (
        "bank-rate-mpc",
        "What is the current Bank Rate set at the most recent Bank of England Monetary "
        "Policy Committee decision?",
        "Bank Rate was set at recent Bank England Monetary Policy Committee decision",
    ),
    (
        "fragment-date",
        "On what date was that decision announced?",
        "on date was that decision announced",
    ),
    (
        "fragment-month",
        "What period does it cover by month?",
        "month it cover",
    ),
)

# Tokens that must never carry a query on their own.
_FRAGMENT_TOKENS = {
    "it", "its", "that", "this", "these", "those", "they", "them",
    "was", "were", "is", "are", "be", "been", "do", "does", "did",
    "the", "a", "an", "and", "or", "but", "of", "on", "in", "at", "to",
    "what", "which", "when", "where", "who", "how", "why",
}


def _batch(question: str, claim_text: str) -> GapQueryBatch:
    claim = ResearchClaim(
        id="claim-1",
        question_id="q-1",
        text=claim_text,
        kind="factual",
        priority="critical",
        state="searching",
        evidence_requirement=EvidenceRequirement(
            source_roles=("primary", "independent_secondary"),
            min_independent_sources=1,
            requires_primary_source=True,
            requires_successful_read=True,
            requires_dated_evidence=False,
        ),
    )
    gap = EvidenceGap(
        id="gap-1",
        claim_id="claim-1",
        gap_type="primary_required",
        desired_source_role="primary",
        state="open",
    )
    return plan_gap_queries(
        gap, claim, reference_date="2026-09-13", question=question
    )


@pytest.mark.parametrize(("label", "question", "claim_text"), AUDIT_FIXTURES)
def test_audit_fixture_never_emits_a_grammar_fragment(
    label: str, question: str, claim_text: str
) -> None:
    batch = _batch(question, claim_text)

    for item in batch.queries:
        query = item.query
        lowered = query.casefold()
        tokens = [token.casefold() for token in query.split()]
        # 1) never only function words / pronouns / auxiliaries
        assert any(token not in _FRAGMENT_TOKENS for token in tokens), (
            label,
            query,
        )
        # 2) never led by a dangling fragment
        assert not lowered.startswith(
            ("it ", "that ", "this ", "was ", "on date", "month ")
        ), (label, query)
        # 3) no stacked primary-source suffixes
        assert "official documentation primary source" not in lowered, (label, query)
        assert "original source announcement" not in lowered, (label, query)
        assert lowered.count("official") <= 1, (label, query)
        assert lowered.count("primary") <= 1, (label, query)


def test_entity_anchors_survive_query_construction() -> None:
    docker = _batch(*AUDIT_FIXTURES[0][1:])
    postgres = _batch(*AUDIT_FIXTURES[1][1:])
    bank = _batch(*AUDIT_FIXTURES[2][1:])

    assert "Docker Hub" in docker.queries[1].query
    assert "PostgreSQL" in postgres.queries[1].query
    assert "Bank" in bank.queries[1].query
    assert docker.queries[1].anchored is True
    assert postgres.queries[1].anchored is True


def test_unanchored_surfaces_are_flagged_not_hidden() -> None:
    date_batch = _batch(*AUDIT_FIXTURES[3][1:])
    month_batch = _batch(*AUDIT_FIXTURES[4][1:])

    assert date_batch.queries[0].anchored is False
    assert month_batch.queries[0].anchored is False
    # The leading temporal fragment is dropped; the query is still a
    # deterministic standalone expression.
    assert not date_batch.queries[0].query.casefold().startswith("date")
    assert not month_batch.queries[0].query.casefold().startswith("month")
    assert date_batch.queries[0].query
    assert month_batch.queries[0].query
