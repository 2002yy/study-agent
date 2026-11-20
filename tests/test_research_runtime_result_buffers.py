"""Extraction admission preserves source aliases and recovered claim bindings."""

from __future__ import annotations

from typing import Any

import pytest

from src.application.research_runtime_result_buffers import ActiveResearchResultBuffers


def _buffers(*records: dict[str, Any]) -> ActiveResearchResultBuffers:
    return ActiveResearchResultBuffers([], list(records), [], [])


def test_source_upsert_preserves_list_alias_and_first_candidate_match() -> None:
    first = {"candidate_id": "source-a", "read": {"status": "failed"}}
    other = {"candidate_id": "source-b"}
    duplicate = {"candidate_id": "source-a", "read": {"status": "read"}}
    buffers = _buffers(first, other, duplicate)
    published = buffers.selected_sources
    replacement = {"candidate_id": "source-a", "read": {"status": "read"}}

    buffers.upsert_selected_source(replacement)

    assert buffers.selected_sources is published
    assert published[0] is replacement
    assert published[1] is other
    assert published[2] is duplicate

    added = {"candidate_id": "source-c"}
    buffers.upsert_selected_source(added)

    assert buffers.selected_sources is published
    assert published[-1] is added
    assert len(published) == 4


def test_admission_keeps_source_identity_and_initializes_claim_map() -> None:
    source = {"candidate_id": "source-a", "read": {"status": "read"}}
    buffers = _buffers(source)
    selected_sources = buffers.selected_sources

    admitted = buffers.admit_extraction_target("source-a", "claim-1")

    assert admitted is source and buffers.selected_sources is selected_sources
    assert selected_sources[0] is source
    assert source["extractions"] == {}
    source["extractions"]["claim-1"] = {"status": "eligible"}
    assert buffers.admit_extraction_target("source-a", "claim-1") is None
    assert buffers.admit_extraction_target("source-a", "claim-2") is source


@pytest.mark.parametrize(
    "read",
    [None, {}, {"status": "failed"}, {"status": "not_found"}],
)
def test_non_read_source_never_initializes_extractions(read: Any) -> None:
    source: dict[str, Any] = {"candidate_id": "source-a", "read_status": "read"}
    if read is not None:
        source["read"] = read
    buffers = _buffers(source)

    assert buffers.admit_extraction_target("source-a", "claim-1") is None
    assert "extractions" not in source
    assert buffers.admit_extraction_target("absent", "claim-1") is None


@pytest.mark.parametrize(
    ("prior", "expected_admission"),
    [
        ({"status": "eligible"}, False),
        ({"status": "extractor_failed"}, False),
        ({"status": "pending"}, True),
        ("eligible", True),
    ],
)
def test_per_claim_status_controls_retries_without_mutating_other_claims(
    prior: Any, expected_admission: bool
) -> None:
    other = {"status": "eligible"}
    source = {
        "candidate_id": "source-a",
        "read": {"status": "read"},
        "extractions": {"claim-1": prior, "claim-other": other},
    }
    buffers = _buffers(source)

    admitted = buffers.admit_extraction_target("source-a", "claim-1")

    assert (admitted is source) is expected_admission
    assert source["extractions"]["claim-1"] is prior
    assert source["extractions"]["claim-other"] is other


@pytest.mark.parametrize("legacy_status", ["eligible", "extractor_failed"])
def test_legacy_claim_binding_skips_only_when_no_per_claim_entry(
    legacy_status: str,
) -> None:
    source = {
        "candidate_id": "source-a",
        "read": {"status": "read"},
        "extraction": {"status": legacy_status, "claim_id": "claim-1"},
    }
    buffers = _buffers(source)

    assert buffers.admit_extraction_target("source-a", "claim-1") is None
    assert source["extractions"] == {}
    assert buffers.admit_extraction_target("source-a", "claim-2") is source
    source["extractions"]["claim-1"] = {"status": "pending"}
    assert buffers.admit_extraction_target("source-a", "claim-1") is source


def test_first_matching_source_remains_authoritative_after_resume() -> None:
    first = {"candidate_id": "source-a", "read": {"status": "failed"}}
    later = {"candidate_id": "source-a", "read": {"status": "read"}}
    buffers = _buffers(first, later)

    assert buffers.admit_extraction_target("source-a", "claim-1") is None
    assert "extractions" not in first and "extractions" not in later
