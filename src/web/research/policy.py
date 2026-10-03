"""Deterministic evidence-requirement policy for Claim Engine shadow mode.

The planner must explicitly choose a semantic profile when generic claim kind
is insufficient. This module performs no URL classification and makes no truth
judgment; it only freezes which source roles may satisfy a future hard gate.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from src.web.research.contracts import (
    EvidenceRequirement,
    ResearchClaimKind,
    ResearchClaimPriority,
)

SourceRole = Literal[
    "primary",
    "authoritative_secondary",
    "independent_secondary",
    "community",
    "aggregator",
]
EvidencePolicyProfile = Literal[
    "official_statement",
    "current_fact",
    "quantitative_claim",
    "causal_analysis",
    "community_sentiment",
    "exploratory_hypothesis",
]
ClosureSemantics = Literal["evidence_gated", "hypothesis_only"]

_CLAIM_KINDS = {"research_question", "hypothesis", "factual", "analytical"}
_PRIORITIES = {"critical", "major", "context"}
_PROFILES = {
    "official_statement",
    "current_fact",
    "quantitative_claim",
    "causal_analysis",
    "community_sentiment",
    "exploratory_hypothesis",
}
_ALL_SOURCE_ROLES: tuple[SourceRole, ...] = (
    "primary",
    "authoritative_secondary",
    "independent_secondary",
    "community",
    "aggregator",
)

#: Public authority ordering (best -> worst). Shared with RQ-C conflict ranking so
#: there is exactly one authority order in the engine.
SOURCE_ROLE_AUTHORITY_ORDER: tuple[SourceRole, ...] = _ALL_SOURCE_ROLES


@dataclass(frozen=True)
class EvidencePolicy:
    profile: EvidencePolicyProfile
    requirement: EvidenceRequirement
    eligible_source_roles: tuple[SourceRole, ...]
    lead_only_source_roles: tuple[SourceRole, ...]
    closure_semantics: ClosureSemantics = "evidence_gated"

    def to_dict(self) -> dict[str, object]:
        return {
            "profile": self.profile,
            "requirement": self.requirement.to_dict(),
            "eligible_source_roles": list(self.eligible_source_roles),
            "lead_only_source_roles": list(self.lead_only_source_roles),
            "closure_semantics": self.closure_semantics,
        }


def evidence_policy_for_claim(
    *,
    kind: ResearchClaimKind,
    priority: ResearchClaimPriority,
    profile: EvidencePolicyProfile,
) -> EvidencePolicy:
    """Return one explicit, deterministic requirement policy.

    No default profile is inferred: a factual statement may be an official
    claim, a market number, or a community-sentiment observation, and silently
    treating them alike is the failure this policy is intended to prevent.
    """

    if kind not in _CLAIM_KINDS:
        raise ValueError(f"invalid research claim kind: {kind}")
    if priority not in _PRIORITIES:
        raise ValueError(f"invalid research claim priority: {priority}")
    if profile not in _PROFILES:
        raise ValueError(f"invalid evidence policy profile: {profile}")
    _validate_profile_kind(profile=profile, kind=kind)

    eligible, requires_primary, closure = _profile_rules(profile)
    minimum = _minimum_independent_sources(profile=profile, priority=priority)
    lead_only = tuple(role for role in _ALL_SOURCE_ROLES if role not in eligible)
    requirement = EvidenceRequirement(
        source_roles=eligible,
        min_independent_sources=minimum,
        requires_primary_source=requires_primary,
        requires_successful_read=True,
    )
    return EvidencePolicy(
        profile=profile,
        requirement=requirement,
        eligible_source_roles=eligible,
        lead_only_source_roles=lead_only,
        closure_semantics=closure,
    )


def _profile_rules(
    profile: str,
) -> tuple[tuple[SourceRole, ...], bool, ClosureSemantics]:
    if profile == "official_statement":
        return (("primary",), True, "evidence_gated")
    if profile in {"current_fact", "quantitative_claim"}:
        return (
            ("primary", "authoritative_secondary", "independent_secondary"),
            False,
            "evidence_gated",
        )
    if profile == "causal_analysis":
        return (
            ("primary", "authoritative_secondary", "independent_secondary"),
            False,
            "evidence_gated",
        )
    if profile == "community_sentiment":
        return (
            ("community", "independent_secondary"),
            False,
            "evidence_gated",
        )
    return (
        ("primary", "authoritative_secondary", "independent_secondary", "community"),
        False,
        "hypothesis_only",
    )


def _minimum_independent_sources(*, profile: str, priority: str) -> int:
    if profile == "official_statement":
        return 1
    if priority == "critical":
        return 2
    return 1


def _validate_profile_kind(*, profile: str, kind: str) -> None:
    allowed: dict[str, set[str]] = {
        "official_statement": {"factual"},
        "current_fact": {"factual"},
        "quantitative_claim": {"factual", "analytical"},
        "causal_analysis": {"analytical"},
        "community_sentiment": {"factual", "analytical"},
        "exploratory_hypothesis": {"research_question", "hypothesis"},
    }
    if kind not in allowed[profile]:
        raise ValueError(f"evidence policy profile {profile} is incompatible with {kind}")
