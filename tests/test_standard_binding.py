"""Standard-3 binding: verified identity, proven relation, sourced role, coherent state.

The invariants under test: a source must be a trusted record whose body hashes to its digest;
a date in the span is not a release date unless the span says so; the role comes from the
source, not the claim; a keyword appearing in a body is not support; disagreeing sources are
reported, never averaged; anything undecidable abstains; applying bindings cannot invent gaps
and never grants publication authority.
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
    relation_binder_for,
    research_state_for,
    verify_claim,
)

BODY = "Release date: 2025-10-07. Python 3.14.0 is the first stable release."
SHA = hashlib.sha256(BODY.encode("utf-8")).hexdigest()
URL = "https://www.python.org/downloads/release/python-3140/"
TRUSTED = [TrustedSource(url=URL, content_sha256=SHA, body=BODY, source_role="primary")]

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
    )
    base.update(overrides)
    return Claim(**base)


# --- mechanical span traceability ------------------------------------------------


def test_span_is_located_by_exact_offset():
    assert locate_span(BODY, "2025-10-07") == (14, 24)


def test_span_not_in_body_is_not_found():
    assert locate_span(BODY, "2026-01-01") == (-1, -1)


def test_verified_claim_carries_offsets_and_identity():
    binding = bind_field("release_date", [_claim(span_text="Release date: 2025-10-07")], TRUSTED)
    assert binding["status"] == SUPPORT
    support = binding["supports"][0]
    assert support["span_start"] == 0 and support["span_end"] == 24
    assert support["source_sha256"] == SHA
    assert support["normalized_value"] == "2025-10-07"


# --- identity is bound, not merely non-empty -------------------------------------


def test_forged_digest_is_not_support():
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


# --- the role comes from the source, not the claim -------------------------------


def test_role_comes_from_the_trusted_source():
    binding = bind_field(
        "release_date",
        [_claim(span_text="Release date: 2025-10-07")],
        [TrustedSource(url=URL, content_sha256=SHA, body=BODY, source_role="secondary")],
    )
    assert binding["supports"][0]["source_role"] == "secondary"


def test_claim_cannot_assert_a_role_at_all():
    # Claim has no source_role field; a caller cannot smuggle one in.
    assert not hasattr(_claim(), "source_role")


def test_source_without_a_role_records_an_empty_role():
    binding = bind_field(
        "release_date",
        [_claim(span_text="Release date: 2025-10-07")],
        [TrustedSource(url=URL, content_sha256=SHA, body=BODY)],
    )
    assert binding["supports"][0]["source_role"] == ""


# --- the relation is proven, not inferred from a type ----------------------------


def test_a_date_without_a_release_relation_is_span_bound():
    # Valid date, no release relation: must not become support.
    body = "Documentation updated: 2025-10-07"
    sha = hashlib.sha256(body.encode("utf-8")).hexdigest()
    binding = bind_field(
        "release_date",
        [_claim(source_sha256=sha, span_text="Documentation updated: 2025-10-07")],
        [TrustedSource(url=URL, content_sha256=sha, body=body, source_role="primary")],
    )
    assert binding["status"] == SPAN_BOUND
    assert binding["supports"] == []
    assert binding["span_bound"][0]["normalized_value"] == ""


def test_two_dates_in_one_span_are_ambiguous():
    body = "Released 2025-10-07 and updated 2025-10-14"
    sha = hashlib.sha256(body.encode("utf-8")).hexdigest()
    binding = bind_field(
        "release_date",
        [_claim(source_sha256=sha, span_text=body)],
        [TrustedSource(url=URL, content_sha256=sha, body=body, source_role="primary")],
    )
    assert binding["status"] == SPAN_BOUND
    assert binding["supports"] == []


def test_release_relation_does_prove_support():
    binding = bind_field(
        "release_date", [_claim(span_text="Release date: 2025-10-07")], TRUSTED
    )
    assert binding["status"] == SUPPORT
    assert binding["supports"][0]["normalized_value"] == "2025-10-07"


def test_field_without_a_relation_binder_is_span_bound():
    binding = bind_field("motto", [_claim(field="motto", span_text="Python 3.14.0")], TRUSTED)
    assert binding["status"] == SPAN_BOUND
    assert binding["supports"] == []


def test_relation_binder_for_returns_none_for_unknown_fields():
    assert relation_binder_for("motto") is None
    assert relation_binder_for("release_date") is not None


def test_invalid_calendar_date_does_not_prove_a_relation():
    assert relation_binder_for("release_date")("Released 2025-13-40") is None


def test_version_relation_requires_a_version_cue():
    binder = relation_binder_for("release_version")
    assert binder("Released version 3.14.0 today") == "3.14.0"
    assert binder("3.14.0") is None


# --- the value is derived, not asserted ------------------------------------------


def test_asserted_value_that_the_span_does_not_yield_is_rejected():
    binding = bind_field(
        "release_date",
        [_claim(span_text="Release date: 2025-10-07", normalized_value="2030-01-01")],
        TRUSTED,
    )
    assert binding["status"] == INSUFFICIENT
    assert binding["supports"] == []
    assert binding["rejected"][0]["reason"] == "normalized_value_mismatch"


def test_agreeing_asserted_value_is_accepted():
    binding = bind_field(
        "release_date",
        [_claim(span_text="Release date: 2025-10-07", normalized_value="2025-10-07")],
        TRUSTED,
    )
    assert binding["status"] == SUPPORT


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


def test_caller_span_end_is_ignored_and_rederived():
    binding = bind_field(
        "release_date",
        [_claim(span_text="Release date: 2025-10-07", span_end=3)],
        TRUSTED,
    )
    assert binding["status"] == SUPPORT
    assert binding["supports"][0]["span_end"] == 24


# --- conflict is reported, never averaged ----------------------------------------


def test_disagreeing_sources_produce_a_conflict():
    binding = bind_field(
        "release_date",
        [
            _claim(span_text="Release date: 2025-10-07"),
            _claim(source_url=OTHER.url, source_sha256=OTHER_SHA, span_text=OTHER_BODY),
        ],
        TRUSTED + [OTHER],
    )
    assert binding["status"] == CONFLICT
    assert binding["supports"] == []
    values = [row["normalized_value"] for row in binding["conflicts"]]
    assert values == ["2025-10-07", "2025-10-14"]


def test_agreeing_sources_are_all_supports():
    agree_body = "Released on 2025-10-07."
    agree_sha = hashlib.sha256(agree_body.encode("utf-8")).hexdigest()
    binding = bind_field(
        "release_date",
        [
            _claim(span_text="Release date: 2025-10-07"),
            _claim(source_url=OTHER.url, source_sha256=agree_sha, span_text=agree_body),
        ],
        TRUSTED + [TrustedSource(url=OTHER.url, content_sha256=agree_sha, body=agree_body)],
    )
    assert binding["status"] == SUPPORT
    assert len(binding["supports"]) == 2


# --- abstention -------------------------------------------------------------------


def test_no_claims_at_all_is_not_evaluated():
    assert bind_field("release_date", [], TRUSTED)["status"] == NOT_EVALUATED


def test_other_fields_are_ignored():
    assert bind_field("release_version", [_claim()], TRUSTED)["status"] == NOT_EVALUATED


def test_bind_fields_covers_every_requested_field():
    bindings = bind_fields(["release_date", "release_version"], [_claim()], TRUSTED)
    assert bindings["release_date"]["status"] == SPAN_BOUND
    assert bindings["release_version"]["status"] == NOT_EVALUATED


def test_verify_claim_reports_the_reason():
    ok, reason, start, end = verify_claim(
        TRUSTED, _claim(span_text="Release date: 2025-10-07")
    )
    assert ok is True and reason == "" and (start, end) == (0, 24)
    ok, reason, _, _ = verify_claim(TRUSTED, _claim(span_text="absent"))
    assert ok is False and reason == "span_not_found_in_body"


# --- applying bindings stays coherent and never grants authority ------------------


def _result():
    return {
        "gap_states": {
            "release_date": {
                "research_state": "SOURCE_ACQUIRED",
                "support_status": NOT_EVALUATED,
                "source_urls": [URL],
            }
        },
        "unresolved_gaps": ["release_date"],
        "publication_authority": False,
        "conflicts": [],
    }


def test_supported_field_leaves_unresolved_gaps():
    bindings = bind_fields(
        ["release_date"], [_claim(span_text="Release date: 2025-10-07")], TRUSTED
    )
    updated = apply_bindings(_result(), bindings)
    assert updated["gap_states"]["release_date"]["support_status"] == SUPPORT
    assert updated["gap_states"]["release_date"]["research_state"] == "SUPPORTED"
    assert updated["unresolved_gaps"] == []
    assert updated["publication_authority"] is False


def test_unresolved_statuses_stay_in_unresolved_gaps():
    body = "Documentation updated: 2025-10-07"
    sha = hashlib.sha256(body.encode("utf-8")).hexdigest()
    sources = [TrustedSource(url=URL, content_sha256=sha, body=body, source_role="primary")]
    bindings = bind_fields(["release_date"], [_claim(source_sha256=sha, span_text=body)], sources)
    updated = apply_bindings(_result(), bindings)
    assert updated["gap_states"]["release_date"]["support_status"] == SPAN_BOUND
    assert updated["unresolved_gaps"] == ["release_date"]


def test_conflict_stays_unresolved():
    bindings = bind_fields(
        ["release_date"],
        [
            _claim(span_text="Release date: 2025-10-07"),
            _claim(source_url=OTHER.url, source_sha256=OTHER_SHA, span_text=OTHER_BODY),
        ],
        TRUSTED + [OTHER],
    )
    updated = apply_bindings(_result(), bindings)
    assert updated["gap_states"]["release_date"]["support_status"] == CONFLICT
    assert updated["unresolved_gaps"] == ["release_date"]
    assert updated["conflicts"][0]["field"] == "release_date"


def test_binding_cannot_invent_an_unrequested_field():
    updated = apply_bindings(
        _result(),
        {"ghost_field": {"field": "ghost_field", "status": SUPPORT, "supports": []}},
    )
    assert "ghost_field" not in updated["gap_states"]
    assert updated["unresolved_gaps"] == ["release_date"]


def test_apply_bindings_cannot_grant_authority_even_if_asked():
    result = _result()
    result["publication_authority"] = True
    updated = apply_bindings(result, bind_fields(["release_date"], [_claim()], TRUSTED))
    assert updated["publication_authority"] is False


def test_apply_bindings_does_not_mutate_the_input():
    result = _result()
    apply_bindings(result, bind_fields(["release_date"], [_claim()], TRUSTED))
    assert result["unresolved_gaps"] == ["release_date"]
    assert result["publication_authority"] is False


# --- review round 3: narrowed grammar and recomputed unresolved ------------------


def test_published_with_a_date_is_still_span_bound():
    # "published" is not in the release-date grammar; it must not raise coverage.
    body = "Documentation published: 2025-10-07"
    sha = hashlib.sha256(body.encode("utf-8")).hexdigest()
    binding = bind_field(
        "release_date",
        [_claim(source_sha256=sha, span_text=body)],
        [TrustedSource(url=URL, content_sha256=sha, body=body, source_role="primary")],
    )
    assert binding["status"] == SPAN_BOUND
    assert binding["supports"] == []


def test_explicit_release_grammar_forms_are_accepted():
    binder = relation_binder_for("release_date")
    assert binder("Release date: 2025-10-07") == "2025-10-07"
    assert binder("Released on 2025-10-07") == "2025-10-07"
    assert binder("Released 2025-10-07") == "2025-10-07"


def test_resolved_field_returns_to_unresolved_when_rebound_as_conflict():
    result = {
        "gap_states": {
            "release_date": {
                "research_state": "SUPPORTED",
                "support_status": SUPPORT,
                "source_urls": [URL],
            }
        },
        "unresolved_gaps": [],
        "publication_authority": False,
        "conflicts": [],
    }
    bindings = bind_fields(
        ["release_date"],
        [
            _claim(span_text="Release date: 2025-10-07"),
            _claim(source_url=OTHER.url, source_sha256=OTHER_SHA, span_text=OTHER_BODY),
        ],
        TRUSTED + [OTHER],
    )
    updated = apply_bindings(result, bindings)
    assert updated["gap_states"]["release_date"]["support_status"] == CONFLICT
    assert updated["unresolved_gaps"] == ["release_date"]


def test_resolved_field_returns_to_unresolved_when_rebound_as_span_bound():
    body = "Documentation published: 2025-10-07"
    sha = hashlib.sha256(body.encode("utf-8")).hexdigest()
    result = {
        "gap_states": {
            "release_date": {
                "research_state": "SUPPORTED",
                "support_status": SUPPORT,
                "source_urls": [URL],
            }
        },
        "unresolved_gaps": [],
        "publication_authority": False,
        "conflicts": [],
    }
    bindings = bind_fields(
        ["release_date"],
        [_claim(source_sha256=sha, span_text=body)],
        [TrustedSource(url=URL, content_sha256=sha, body=body, source_role="primary")],
    )
    updated = apply_bindings(result, bindings)
    assert updated["gap_states"]["release_date"]["support_status"] == SPAN_BOUND
    assert updated["unresolved_gaps"] == ["release_date"]


# --- review round 4: research_state is derived from the final status ---------------


def _supported_result(source_urls=None):
    return {
        "gap_states": {
            "release_date": {
                "research_state": "SUPPORTED",
                "support_status": SUPPORT,
                "source_urls": [URL] if source_urls is None else source_urls,
            }
        },
        "unresolved_gaps": [],
        "publication_authority": False,
        "conflicts": [],
    }


def test_research_state_is_derived_for_every_status():
    assert research_state_for(SUPPORT, [URL]) == "SUPPORTED"
    assert research_state_for(CONFLICT, [URL]) == "CONFLICT"
    assert research_state_for(SPAN_BOUND, [URL]) == "SPAN_BOUND"
    assert research_state_for(INSUFFICIENT, [URL]) == "SOURCE_ACQUIRED"
    assert research_state_for(INSUFFICIENT, []) == "OPEN"
    assert research_state_for(NOT_EVALUATED, [URL]) == "SOURCE_ACQUIRED"
    assert research_state_for(NOT_EVALUATED, []) == "OPEN"


def test_supported_field_rebound_as_insufficient_is_not_left_supported():
    # A claim that fails identity binding yields INSUFFICIENT.
    bindings = bind_fields(["release_date"], [_claim(source_sha256="a" * 64)], TRUSTED)
    updated = apply_bindings(_supported_result(), bindings)
    state = updated["gap_states"]["release_date"]
    assert state["support_status"] == INSUFFICIENT
    assert state["research_state"] != "SUPPORTED"
    assert state["research_state"] == "SOURCE_ACQUIRED"
    assert updated["unresolved_gaps"] == ["release_date"]


def test_supported_field_rebound_as_not_evaluated_is_not_left_supported():
    bindings = bind_fields(["release_date"], [], TRUSTED)
    updated = apply_bindings(_supported_result(), bindings)
    state = updated["gap_states"]["release_date"]
    assert state["support_status"] == NOT_EVALUATED
    assert state["research_state"] != "SUPPORTED"
    assert state["research_state"] == "SOURCE_ACQUIRED"
    assert updated["unresolved_gaps"] == ["release_date"]


def test_insufficient_without_any_source_falls_back_to_open():
    bindings = bind_fields(["release_date"], [_claim(source_sha256="a" * 64)], TRUSTED)
    updated = apply_bindings(_supported_result(source_urls=[]), bindings)
    assert updated["gap_states"]["release_date"]["research_state"] == "OPEN"
