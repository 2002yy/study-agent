"""Standard-3 binding: verifiable support, honest conflict, and abstention.

The invariants under test: a keyword appearing in a body is not support; two sources that
disagree are reported, never averaged; anything undecidable abstains; and no binding ever
grants publication authority.
"""

from __future__ import annotations

from src.web.research.standard_binding import (
    CONFLICT,
    INSUFFICIENT,
    NOT_EVALUATED,
    SUPPORT,
    Claim,
    apply_bindings,
    bind_field,
    bind_fields,
    locate_span,
    verify_claim,
)

BODY = "Release date: 2025-10-07. Python 3.14.0 is the first stable release."
SHA = "a" * 64


def _claim(**overrides):
    base = dict(
        field="release_date",
        source_url="https://www.python.org/downloads/release/python-3140/",
        source_sha256=SHA,
        span_text="2025-10-07",
        normalized_value="2025-10-07",
        source_role="primary",
    )
    base.update(overrides)
    return Claim(**base)


# --- mechanical span traceability ------------------------------------------------


def test_span_is_located_by_exact_offset():
    assert locate_span(BODY, "2025-10-07") == (14, 24)


def test_span_not_in_body_is_not_found():
    assert locate_span(BODY, "2026-01-01") == (-1, -1)


def test_verified_claim_carries_offsets_and_identity():
    binding = bind_field("release_date", [_claim()], {SHA: BODY})
    assert binding["status"] == SUPPORT
    support = binding["supports"][0]
    assert support["span_start"] == 14 and support["span_end"] == 24
    assert support["source_sha256"] == SHA
    assert support["source_role"] == "primary"


# --- a keyword is not support ----------------------------------------------------


def test_keyword_presence_without_a_span_is_not_support():
    # The word "release" appears, but the claim points at text that does not.
    binding = bind_field(
        "release_date", [_claim(span_text="released on 2025-10-07")], {SHA: BODY}
    )
    assert binding["status"] == INSUFFICIENT
    assert binding["supports"] == []
    assert binding["rejected"][0]["reason"] == "span_not_found_in_body"


def test_claim_without_source_identity_is_rejected():
    binding = bind_field("release_date", [_claim(source_sha256="")], {SHA: BODY})
    assert binding["status"] == INSUFFICIENT
    assert binding["rejected"][0]["reason"] == "unbound_source_identity"


def test_claim_without_a_normalized_value_is_rejected():
    binding = bind_field("release_date", [_claim(normalized_value="  ")], {SHA: BODY})
    assert binding["rejected"][0]["reason"] == "empty_normalized_value"


def test_unknown_body_is_rejected_not_guessed():
    binding = bind_field("release_date", [_claim()], {})
    assert binding["status"] == INSUFFICIENT
    assert binding["rejected"][0]["reason"] == "body_not_available"


def test_offset_mismatch_is_rejected():
    binding = bind_field("release_date", [_claim(span_start=999)], {SHA: BODY})
    assert binding["rejected"][0]["reason"] == "span_offset_mismatch"


# --- conflict is reported, never averaged ----------------------------------------


def test_disagreeing_sources_produce_a_conflict():
    other_sha = "b" * 64
    other_body = "Release date: 2025-10-14."
    binding = bind_field(
        "release_date",
        [
            _claim(),
            _claim(source_sha256=other_sha, span_text="2025-10-14", normalized_value="2025-10-14"),
        ],
        {SHA: BODY, other_sha: other_body},
    )
    assert binding["status"] == CONFLICT
    assert binding["supports"] == []
    values = [row["normalized_value"] for row in binding["conflicts"]]
    assert values == ["2025-10-07", "2025-10-14"]


def test_agreeing_sources_are_all_supports():
    other_sha = "b" * 64
    other_body = "The release date is 2025-10-07."
    binding = bind_field(
        "release_date",
        [_claim(), _claim(source_url="https://example.org/x", source_sha256=other_sha)],
        {SHA: BODY, other_sha: other_body},
    )
    assert binding["status"] == SUPPORT
    assert len(binding["supports"]) == 2


# --- abstention -------------------------------------------------------------------


def test_no_claims_at_all_is_not_evaluated():
    binding = bind_field("release_date", [], {SHA: BODY})
    assert binding["status"] == NOT_EVALUATED


def test_other_fields_are_ignored():
    binding = bind_field("release_version", [_claim()], {SHA: BODY})
    assert binding["status"] == NOT_EVALUATED


def test_bind_fields_covers_every_requested_field():
    bindings = bind_fields(["release_date", "release_version"], [_claim()], {SHA: BODY})
    assert bindings["release_date"]["status"] == SUPPORT
    assert bindings["release_version"]["status"] == NOT_EVALUATED


# --- publication authority is never granted ---------------------------------------


def test_apply_bindings_records_state_without_authority():
    result = {
        "gap_states": {
            "release_date": {
                "research_state": "SOURCE_ACQUIRED",
                "support_status": NOT_EVALUATED,
                "source_urls": ["https://www.python.org/x"],
            }
        },
        "publication_authority": False,
        "conflicts": [],
    }
    bindings = bind_fields(["release_date"], [_claim()], {SHA: BODY})
    updated = apply_bindings(result, bindings)
    assert updated["gap_states"]["release_date"]["support_status"] == SUPPORT
    assert updated["gap_states"]["release_date"]["research_state"] == "SUPPORTED"
    assert updated["publication_authority"] is False


def test_apply_bindings_cannot_grant_authority_even_if_asked():
    result = {"gap_states": {}, "publication_authority": True, "conflicts": []}
    updated = apply_bindings(result, bind_fields(["f"], [_claim(field="f")], {SHA: BODY}))
    assert updated["publication_authority"] is False


def test_apply_bindings_records_conflicts():
    other_sha = "b" * 64
    result = {"gap_states": {}, "publication_authority": False, "conflicts": []}
    bindings = bind_fields(
        ["release_date"],
        [
            _claim(),
            _claim(source_sha256=other_sha, span_text="2025-10-14", normalized_value="2025-10-14"),
        ],
        {SHA: BODY, other_sha: "Release date: 2025-10-14."},
    )
    updated = apply_bindings(result, bindings)
    assert updated["gap_states"]["release_date"]["support_status"] == CONFLICT
    assert updated["conflicts"][0]["field"] == "release_date"


def test_apply_bindings_does_not_mutate_the_input():
    result = {"gap_states": {}, "publication_authority": False, "conflicts": []}
    apply_bindings(result, bind_fields(["f"], [_claim(field="f")], {SHA: BODY}))
    assert result["gap_states"] == {}
    assert result["publication_authority"] is False


def test_verify_claim_reports_the_reason():
    ok, reason = verify_claim(BODY, _claim())
    assert ok is True and reason == ""
    ok, reason = verify_claim(BODY, _claim(span_text="absent"))
    assert ok is False and reason == "span_not_found_in_body"
