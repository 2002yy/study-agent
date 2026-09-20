"""§71B retrieval backend contract: boundaries, ledger and budget separation."""

from __future__ import annotations

import pytest

from src.web.research.retrieval_backends import (
    BUDGET_KINDS,
    DISCOVERY_CANDIDATE_FIELDS,
    FORBIDDEN_AUTHORITY_FIELDS,
    RAW_READ_ARTIFACT_FIELDS,
    TERMINAL_RETRIEVAL_STATES,
    DiscoveryCandidate,
    DiscoveryRequest,
    RawReadArtifact,
    ReadRequest,
    RetrievalContractError,
    assert_retrieval_invocations_terminal,
    create_retrieval_invocation,
    finalize_retrieval_invocation,
    retrieval_attempt_row,
    retrieval_invocation_id,
    validate_backend_payload,
)


def _live(store: dict) -> dict:
    return store


def test_candidate_rows_carry_no_local_authority() -> None:
    candidate = DiscoveryCandidate(
        url="https://docs.example.com/pulls",
        title="Pull limits",
        provider="agent_search",
        source_family="official_docs",
        backend="agent_search",
        external_metadata={"confidence": 0.97, "evidence": "looks official"},
    )
    row = candidate.to_candidate_row()
    assert set(row) <= set(DISCOVERY_CANDIDATE_FIELDS)
    assert not FORBIDDEN_AUTHORITY_FIELDS.intersection(row)
    # the external claims survive only as inert metadata on the dataclass
    assert candidate.external_metadata["confidence"] == 0.97


def test_read_artifact_carries_no_local_authority() -> None:
    artifact = RawReadArtifact(
        url="https://docs.example.com/pulls",
        content="pull limits",
        content_type="text/html",
        retrieval_mode="rendered",
        backend="wigolo",
        latency_ms=2600,
        bytes=180000,
        rendered=True,
    )
    assert artifact.usable is True
    assert not FORBIDDEN_AUTHORITY_FIELDS.intersection(artifact.__dict__)
    assert set(artifact.__dict__) - {"external_metadata"} == set(
        RAW_READ_ARTIFACT_FIELDS
    )


def test_payload_validation_rejects_smuggled_authority() -> None:
    validate_backend_payload(
        {"url": "https://x.example/", "title": "t"}, allowed_fields=("url", "title")
    )
    with pytest.raises(RetrievalContractError, match="authority"):
        validate_backend_payload(
            {"url": "https://x.example/", "confidence": 0.9},
            allowed_fields=("url", "title"),
        )
    with pytest.raises(RetrievalContractError, match="undeclared"):
        validate_backend_payload(
            {"url": "https://x.example/", "snippet": "s"},
            allowed_fields=("url", "title"),
        )


def test_invocation_id_format() -> None:
    assert (
        retrieval_invocation_id(
            claim_id="claim_1",
            wave_index=2,
            backend="wigolo",
            operation="fetch",
            sequence=1,
        )
        == "claim_1:2:wigolo:fetch:1"
    )
    with pytest.raises(RetrievalContractError):
        retrieval_invocation_id(
            claim_id="claim_1",
            wave_index=2,
            backend="wigolo",
            operation="teleport",
            sequence=1,
        )


def test_invocation_reaches_terminal_state_and_upserts_by_id() -> None:
    store: dict = {}
    entry = create_retrieval_invocation(
        lambda: _live(store),
        claim_id="claim_1",
        wave_index=2,
        backend="wigolo",
        operation="fetch",
    )
    assert entry["state"] == "running"
    # the runtime replaces the mapping while the backend runs
    replaced: dict = {}
    finalize_retrieval_invocation(
        lambda: replaced,
        entry,
        state="ok",
        result_count=1,
        bytes=1024,
        latency_ms=2600,
        escalation_reason="read_adequacy_failed",
    )
    invocations = replaced["retrieval_invocations"]
    assert len(invocations) == 1
    assert invocations[0]["invocation_id"] == entry["invocation_id"]
    assert invocations[0]["state"] == "ok"
    assert invocations[0]["recovered"] is True
    assert invocations[0]["escalation_reason"] == "read_adequacy_failed"
    assert_retrieval_invocations_terminal(replaced)
    assert store.get("retrieval_invocations", [])[0]["state"] == "ok"


def test_non_terminal_state_is_rejected() -> None:
    store: dict = {}
    entry = create_retrieval_invocation(
        lambda: _live(store),
        claim_id="claim_1",
        wave_index=1,
        backend="ddgs",
        operation="search",
    )
    with pytest.raises(RetrievalContractError, match="terminal"):
        finalize_retrieval_invocation(lambda: _live(store), entry, state="running")
    with pytest.raises(RetrievalContractError, match="non-terminal"):
        assert_retrieval_invocations_terminal(store)
    finalize_retrieval_invocation(lambda: _live(store), entry, state="empty")
    assert_retrieval_invocations_terminal(store)
    assert TERMINAL_RETRIEVAL_STATES  # non-empty by construction


def test_retrieval_attempts_never_spend_model_budget() -> None:
    row = retrieval_attempt_row(
        backend="wigolo",
        operation="fetch",
        claim_id="claim_1",
        wave_index=2,
        latency_ms=2600,
        bytes=180000,
        escalation_reason="thin_body",
    )
    assert row["budget"] == "retrieval_attempt"
    assert "model" not in row["budget"]
    assert set(BUDGET_KINDS) == {"model_attempt", "retrieval_attempt", "wall_clock"}
    # wall clock is charged by the caller; the row only reports latency
    assert row["latency_ms"] == 2600.0


def test_requests_are_declared_and_immutable() -> None:
    discovery = DiscoveryRequest(claim_id="c", wave_index=1, query="q", max_results=5)
    read = ReadRequest(url="https://x.example/", max_chars=1200)
    assert discovery.max_results == 5
    assert read.retrieval_mode == "http"
    with pytest.raises(Exception):
        discovery.query = "other"  # type: ignore[misc]
