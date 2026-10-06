"""Standard-3 binding: verified identity, derived value, honest conflict, abstention.

The invariants under test: a source must be a trusted record whose body hashes to its digest;
the normalized value is derived from the verified span, not asserted by the caller; a keyword
appearing in a body is not support; disagreeing sources are reported, never averaged; anything
undecidable abstains; and no binding ever grants publication authority.
"""

from __future__ import annotations

import hashlib

from src.web.research.standard_binding import (
    CONFLICT,
    INSUFFICIENT,
    NOT_EVALUATED,
    SPAN_BOUND,
    SUPPORT,
    Claim,
    TrustedSource,
    apply_bindings,
    bind_field,
    bind_fields,
    find_trusted_source,
    locate_span,
    normalizer_for,
    verify_claim,
)

BODY = "Release date: 2025-10-07. Python 3.14.0 is the first stable release."
SHA = hashlib.sha256(BODY.encode("utf-8")).hexdigest()
URL = "https://www.python.org/downloads/release/python-3140/"
TRUSTED = [TrustedSource(url=URL, content_sha256=SHA, body=BODY)]

OTHER_BODY = "Release date: 2025-10-14."
OTHER_SHA = hashlib.sha256(OTHER_BODY.encode("utf-8")).hexdigest()
OTHER = TrustedSource(url="https://example.org/x", content_sha256=OTHER_SHA, body=OTHER_BODY)


def _claim(**overrides):
    base = dict(
        field="release_date",
        source_url=URL,
        source_sha256=SHA,
        span_text="2025-10-07",
        normalized_value="",
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
    binding = bind_field("release_date", [_claim()], TRUSTED)
    assert binding["status"] == SUPPORT
    support = binding["supports"][0]
    assert support["span_start"] == 14 and support["span_end"] == 24
    assert support["source_sha256"] == SHA
    assert support["source_role"] == "primary"
    assert support["normalized_value"] == "2025-10-07"


# --- identity is bound, not merely non-empty -------------------------------------


def test_forged_digest_is_not_support():
    # The digest is well-formed but does not correspond to any trusted record.
    binding = bind_field("release_date", [_claim(source_sha256="a" * 64)], TRUSTED)
    assert binding["status"] == INSUFFICIENT
    assert binding["supports"] == []
    assert binding["rejected"][0]["reason"] == "source_not_trusted"


def test_forged_url_is_not_support():
    binding = bind_field(
        "release_date", [_claim(source_url="https://evil.example/x")], TRUSTED
    )
    assert binding["status"] == INSUFFICIENT
    assert binding["rejected"][0]["reason"] == "source_not_trusted"


def test_trusted_record_whose_body_does_not_hash_is_rejected():
    tampered = [TrustedSource(url=URL, content_sha256=SHA, body="tampered body")]
    binding = bind_field("release_date", [_claim()], tampered)
    assert binding["status"] == INSUFFICIENT
    assert binding["rejected"][0]["reason"] == "body_digest_mismatch"


def test_claim_without_source_identity_is_rejected():
    binding = bind_field("release_date", [_claim(source_sha256="")], TRUSTED)
    assert binding["rejected"][0]["reason"] == "unbound_source_identity"


def test_find_trusted_source_returns_the_record():
    source, reason = find_trusted_source(TRUSTED, _claim())
    assert source is not None and reason == ""
    assert source.body == BODY


# --- the value is derived, not asserted ------------------------------------------


def test_asserted_value_that_the_span_does_not_yield_is_rejected():
    # The span really exists, but the caller claims a different value.
    binding = bind_field(
        "release_date", [_claim(normalized_value="2030-01-01")], TRUSTED
    )
    assert binding["status"] == INSUFFICIENT
    assert binding["supports"] == []
    assert binding["rejected"][0]["reason"] == "normalized_value_mismatch"


def test_derived_value_is_used_and_recorded():
    binding = bind_field("release_date", [_claim()], TRUSTED)
    assert binding["supports"][0]["normalized_value"] == "2025-10-07"


def test_agreeing_asserted_value_is_accepted():
    binding = bind_field(
        "release_date", [_claim(normalized_value="2025-10-07")], TRUSTED
    )
    assert binding["status"] == SUPPORT


def test_invalid_calendar_date_does_not_normalize():
    assert normalizer_for("release_date")("2025-13-40") is None
    assert normalizer_for("release_date")("2025-10-07") == "2025-10-07"


def test_version_normalizer_extracts_semver():
    assert normalizer_for("release_version")("3.14.0 is out") == "3.14.0"


def test_field_without_a_normalizer_is_span_bound_not_support():
    binding = bind_field("motto", [_claim(field="motto", span_text="Python 3.14.0")], TRUSTED)
    assert binding["status"] == SPAN_BOUND
    assert binding["supports"] == []
    assert binding["span_bound"][0]["span_start"] == 26


# --- a keyword is not support ----------------------------------------------------


def test_keyword_presence_without_a_span_is_not_support():
    binding = bind_field(
        "release_date", [_claim(span_text="released on 2025-10-07")], TRUSTED
    )
    assert binding["status"] == INSUFFICIENT
    assert binding["rejected"][0]["reason"] == "span_not_found_in_body"


def test_offset_mismatch_is_rejected():
    binding = bind_field("release_date", [_claim(span_start=999)], TRUSTED)
    assert binding["rejected"][0]["reason"] == "span_offset_mismatch"


# --- conflict is reported, never averaged ----------------------------------------


def test_disagreeing_sources_produce_a_conflict():
    binding = bind_field(
        "release_date",
        [_claim(), _claim(source_url=OTHER.url, source_sha256=OTHER_SHA, span_text="2025-10-14")],
        TRUSTED + [OTHER],
    )
    assert binding["status"] == CONFLICT
    assert binding["supports"] == []
    values = [row["normalized_value"] for row in binding["conflicts"]]
    assert values == ["2025-10-07", "2025-10-14"]


def test_agreeing_sources_are_all_supports():
    agree_body = "On 2025-10-07 it shipped."
    agree_sha = hashlib.sha256(agree_body.encode("utf-8")).hexdigest()
    binding = bind_field(
        "release_date",
        [
            _claim(),
            _claim(source_url=OTHER.url, source_sha256=agree_sha, span_text="2025-10-07"),
        ],
        TRUSTED + [TrustedSource(url=OTHER.url, content_sha256=agree_sha, body=agree_body)],
    )
    assert binding["status"] == SUPPORT
    assert len(binding["supports"]) == 2


# --- abstention -------------------------------------------------------------------


def test_no_claims_at_all_is_not_evaluated():
    binding = bind_field("release_date", [], TRUSTED)
    assert binding["status"] == NOT_EVALUATED


def test_other_fields_are_ignored():
    binding = bind_field("release_version", [_claim()], TRUSTED)
    assert binding["status"] == NOT_EVALUATED


def test_bind_fields_covers_every_requested_field():
    bindings = bind_fields(["release_date", "release_version"], [_claim()], TRUSTED)
    assert bindings["release_date"]["status"] == SUPPORT
    assert bindings["release_version"]["status"] == NOT_EVALUATED


def test_verify_claim_reports_the_reason():
    ok, reason, start, end = verify_claim(TRUSTED, _claim())
    assert ok is True and reason == "" and (start, end) == (14, 24)
    ok, reason, _, _ = verify_claim(TRUSTED, _claim(span_text="absent"))
    assert ok is False and reason == "span_not_found_in_body"


# --- publication authority is never granted ---------------------------------------


def test_apply_bindings_records_state_without_authority():
    result = {
        "gap_states": {
            "release_date": {
                "research_state": "SOURCE_ACQUIRED",
                "support_status": NOT_EVALUATED,
                "source_urls": [URL],
            }
        },
        "publication_authority": False,
        "conflicts": [],
    }
    bindings = bind_fields(["release_date"], [_claim()], TRUSTED)
    updated = apply_bindings(result, bindings)
    assert updated["gap_states"]["release_date"]["support_status"] == SUPPORT
    assert updated["gap_states"]["release_date"]["research_state"] == "SUPPORTED"
    assert updated["publication_authority"] is False


def test_apply_bindings_cannot_grant_authority_even_if_asked():
    result = {"gap_states": {}, "publication_authority": True, "conflicts": []}
    updated = apply_bindings(result, bind_fields(["f"], [_claim(field="f")], TRUSTED))
    assert updated["publication_authority"] is False


def test_apply_bindings_records_span_bound_without_support():
    result = {"gap_states": {}, "publication_authority": False, "conflicts": []}
    updated = apply_bindings(
        result,
        bind_fields(["motto"], [_claim(field="motto", span_text="Python 3.14.0")], TRUSTED),
    )
    assert updated["gap_states"]["motto"]["support_status"] == SPAN_BOUND
    assert updated["gap_states"]["motto"]["research_state"] == "SPAN_BOUND"


def test_apply_bindings_records_conflicts():
    result = {"gap_states": {}, "publication_authority": False, "conflicts": []}
    bindings = bind_fields(
        ["release_date"],
        [_claim(), _claim(source_url=OTHER.url, source_sha256=OTHER_SHA, span_text="2025-10-14")],
        TRUSTED + [OTHER],
    )
    updated = apply_bindings(result, bindings)
    assert updated["gap_states"]["release_date"]["support_status"] == CONFLICT
    assert updated["conflicts"][0]["field"] == "release_date"


def test_apply_bindings_does_not_mutate_the_input():
    result = {"gap_states": {}, "publication_authority": False, "conflicts": []}
    apply_bindings(result, bind_fields(["f"], [_claim(field="f")], TRUSTED))
    assert result["gap_states"] == {}
    assert result["publication_authority"] is False
