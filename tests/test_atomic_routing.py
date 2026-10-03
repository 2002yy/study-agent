"""§39 atomic routing: bounded, factual-only, default-off."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from src.web.research.atomic_routing import (
    ATOMIC_ROUTING_ENV,
    ROUTE_REASON_ALREADY_BOUND,
    ROUTE_REASON_ALREADY_SUPPORTED,
    ROUTE_REASON_BOUNDED_CAP,
    ROUTE_REASON_MISSING_ATOMIC_CHILD,
    ROUTE_REASON_ORIGIN_CLAIM,
    ROUTE_REASON_UNRELATED,
    atomic_routing_enabled,
    route_missing_atomic_claims,
)

READ = "candidate_read"
OTHER = "candidate_other"


@dataclass
class _Claim:
    id: str
    kind: str = "factual"


CLAIMS = (
    _Claim("claim_origin", kind="analytical"),
    _Claim("claim_atomic_a", kind="factual"),
    _Claim("claim_atomic_b", kind="factual"),
    _Claim("claim_atomic_c", kind="factual"),
)


def _targets() -> list[dict]:
    return [{"candidate_id": READ, "claim_id": "claim_origin", "cluster_id": "c1"}]


def test_flag_defaults_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(ATOMIC_ROUTING_ENV, raising=False)
    assert atomic_routing_enabled() is False
    monkeypatch.setenv(ATOMIC_ROUTING_ENV, "on")
    assert atomic_routing_enabled() is True
    monkeypatch.setenv(ATOMIC_ROUTING_ENV, "0")
    assert atomic_routing_enabled() is False


def test_routes_missing_factual_claims_with_reasons() -> None:
    extended, records = route_missing_atomic_claims(
        _targets(),
        claims=CLAIMS,
        supported_claim_ids=frozenset({"claim_atomic_c"}),
        read_candidate_ids=frozenset({READ}),
    )
    routed = [row["claim_id"] for row in extended]
    assert routed[0] == "claim_origin"  # origin row unchanged and first
    assert set(routed[1:]) == {"claim_atomic_a", "claim_atomic_b"}

    record = records[0]
    assert record["read_artifact_id"] == READ
    assert record["origin_claim_id"] == "claim_origin"
    assert record["candidate_claim_ids"] == [claim.id for claim in CLAIMS]
    assert record["routed_claim_ids"] == ["claim_atomic_a", "claim_atomic_b"]
    assert record["routes"] == [
        {"claim_id": "claim_atomic_a", "reason": ROUTE_REASON_MISSING_ATOMIC_CHILD},
        {"claim_id": "claim_atomic_b", "reason": ROUTE_REASON_MISSING_ATOMIC_CHILD},
    ]
    reasons = {item["claim_id"]: item["reason"] for item in record["skips"]}
    assert reasons["claim_origin"] == ROUTE_REASON_ORIGIN_CLAIM
    assert reasons["claim_atomic_c"] == ROUTE_REASON_ALREADY_SUPPORTED


def test_unread_candidates_are_never_routed() -> None:
    extended, records = route_missing_atomic_claims(
        [{"candidate_id": OTHER, "claim_id": "claim_origin", "cluster_id": "c1"}],
        claims=CLAIMS,
        supported_claim_ids=frozenset(),
        read_candidate_ids=frozenset({READ}),
    )
    assert [row["claim_id"] for row in extended] == ["claim_origin"]
    assert records == []


def test_bound_pairs_are_skipped() -> None:
    extended, records = route_missing_atomic_claims(
        [
            {"candidate_id": READ, "claim_id": "claim_origin", "cluster_id": "c1"},
            {"candidate_id": READ, "claim_id": "claim_atomic_a", "cluster_id": "c1"},
        ],
        claims=CLAIMS,
        supported_claim_ids=frozenset(),
        read_candidate_ids=frozenset({READ}),
    )
    assert [row["claim_id"] for row in extended].count("claim_atomic_a") == 1
    record = records[0]
    reasons = {item["claim_id"]: item["reason"] for item in record["skips"]}
    assert reasons["claim_atomic_a"] == ROUTE_REASON_ALREADY_BOUND
    assert record["routed_claim_ids"] == ["claim_atomic_b", "claim_atomic_c"]


def test_caps_are_enforced_per_read_and_per_wave() -> None:
    claims = tuple(_Claim(f"claim_f{index}") for index in range(6))
    extended, records = route_missing_atomic_claims(
        [{"candidate_id": READ, "claim_id": "origin", "cluster_id": "c1"}],
        claims=(_Claim("origin", kind="analytical"), *claims),
        supported_claim_ids=frozenset(),
        read_candidate_ids=frozenset({READ}),
        per_read_max=2,
        per_wave_max=4,
    )
    record = records[0]
    assert record["routed_claim_ids"] == ["claim_f0", "claim_f1"]
    cap_skips = [
        item for item in record["skips"] if item["reason"] == ROUTE_REASON_BOUNDED_CAP
    ]
    assert len(cap_skips) == 4

    two_reads = [
        {"candidate_id": READ, "claim_id": "origin_a", "cluster_id": "c1"},
        {"candidate_id": OTHER, "claim_id": "origin_b", "cluster_id": "c2"},
    ]
    extended, records = route_missing_atomic_claims(
        two_reads,
        claims=(_Claim("origin_a", kind="analytical"), _Claim("origin_b", kind="analytical"), *claims),
        supported_claim_ids=frozenset(),
        read_candidate_ids=frozenset({READ, OTHER}),
        per_read_max=2,
        per_wave_max=3,
    )
    total_routed = sum(len(record["routed_claim_ids"]) for record in records)
    assert total_routed == 3


def test_analytical_claims_are_never_routed_even_when_missing() -> None:
    extended, records = route_missing_atomic_claims(
        [{"candidate_id": READ, "claim_id": "claim_atomic_a", "cluster_id": "c1"}],
        claims=CLAIMS,
        supported_claim_ids=frozenset(),
        read_candidate_ids=frozenset({READ}),
    )
    assert "claim_origin" not in [row["claim_id"] for row in extended]
    reasons = {item["claim_id"]: item["reason"] for item in records[0]["skips"]}
    assert reasons["claim_origin"] == ROUTE_REASON_UNRELATED
