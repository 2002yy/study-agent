"""Standard-4 projection: durable sources, and claims that keep target and relation together.

The negative controls here are the ones the contract calls out: a body that does not re-hash to
its recorded digest never becomes a trusted source; a missing relation cue does not support; and
a target identity that appears on the page but not in the relation window does not support.
"""

from __future__ import annotations

import hashlib

from src.repositories.standard_execution_repository import work_key
from src.web.research.standard_binding import bind_fields
from src.web.research.standard_binding_projection import (
    evidence_windows,
    journal_work_key,
    project_mechanical_claims,
    project_trusted_sources,
)

BODY = "Python 3.14.0 was released on 2025-10-07. See the notes for 3.13."
SHA = hashlib.sha256(BODY.encode()).hexdigest()
URL = "https://www.python.org/downloads/release/python-3140/"


def _ledger(body=BODY, *, state="completed", digest=SHA, readable=True, kind="read"):
    return {
        "research": {
            "observations": [
                {
                    "kind": kind,
                    "target": URL,
                    "readable": readable,
                    "content_sha256": digest if readable else "",
                }
            ]
        },
        "entries": {journal_work_key("read", URL): {"state": state, "result": {"content": body}}},
    }


# --- key derivation must match the repository --------------------------------------


def test_journal_key_matches_the_repository():
    assert journal_work_key("read", URL) == work_key("read", URL)


# --- trusted sources come from the durable journal, re-hashed ---------------------


def test_readable_source_with_a_matching_digest_is_trusted():
    sources = project_trusted_sources(_ledger())
    assert len(sources) == 1
    assert sources[0].url == URL and sources[0].body == BODY
    assert sources[0].source_role == ""


def test_body_that_does_not_rehash_is_not_trusted():
    sources = project_trusted_sources(_ledger(body="tampered body", digest=SHA))
    assert sources == []


def test_incomplete_entry_is_not_trusted():
    assert project_trusted_sources(_ledger(state="failed")) == []


def test_unreadable_observation_is_not_trusted():
    assert project_trusted_sources(_ledger(readable=False)) == []


def test_non_read_observation_is_not_trusted():
    assert project_trusted_sources(_ledger(kind="search")) == []


def test_empty_body_is_not_trusted():
    empty = ""
    assert project_trusted_sources(_ledger(body=empty, digest=hashlib.sha256(empty.encode()).hexdigest())) == []


# --- windows -----------------------------------------------------------------------


def test_windows_keep_original_offsets():
    for text, start, end in evidence_windows(BODY):
        assert BODY[start:end] == text


def test_windows_split_on_sentence_boundaries():
    texts = [text for text, _, _ in evidence_windows(BODY)]
    assert any(text.startswith("Python 3.14.0 was released") for text in texts)


# --- claims need the target and the relation in the same window -------------------


def test_target_and_relation_in_one_window_produces_a_claim():
    claims = project_mechanical_claims(["release_date"], project_trusted_sources(_ledger()), target=("Python", "3.14.0"))
    assert len(claims) == 1
    assert claims[0].span_text == "Python 3.14.0 was released on 2025-10-07."
    assert claims[0].span_start == 0
    assert claims[0].normalized_value == ""


def test_missing_relation_cue_produces_no_claim():
    body = "Python 3.14.0 updated on 2025-10-07."
    digest = hashlib.sha256(body.encode()).hexdigest()
    ledger = _ledger(body=body, digest=digest)
    assert project_mechanical_claims(["release_date"], project_trusted_sources(ledger), target=("Python", "3.14.0")) == []


def test_target_absent_from_the_relation_window_produces_no_claim():
    # The page names 3.13 next to a release date, but the target is 3.14.
    body = "Python 3.13.0 was released on 2025-10-07."
    digest = hashlib.sha256(body.encode()).hexdigest()
    ledger = _ledger(body=body, digest=digest)
    assert project_mechanical_claims(["release_date"], project_trusted_sources(ledger), target=("Python", "3.14.0")) == []


def test_no_target_produces_no_claim():
    assert project_mechanical_claims(["release_date"], project_trusted_sources(_ledger()), target=None) == []


def test_field_without_a_relation_binder_is_skipped():
    assert project_mechanical_claims(["motto"], project_trusted_sources(_ledger()), target=("Python", "3.14.0")) == []


def test_identity_uses_the_canonical_pattern():
    from src.web.research_recovery import target_identity_pattern

    pattern = target_identity_pattern(("Python", "3.14"))
    assert pattern.search("the Python 3.14 release")
    assert pattern.search("Python 3.14.0 was released")
    assert not pattern.search("Python 3.14.1 was released")
    assert not pattern.search("Python 3.13 was released")


# --- end to end through Standard-3 -------------------------------------------------


def test_projected_claim_binds_through_standard_3():
    trusted = project_trusted_sources(_ledger())
    claims = project_mechanical_claims(["release_date"], trusted, target=("Python", "3.14.0"))
    bindings = bind_fields(["release_date"], claims, trusted)
    assert bindings["release_date"]["status"] == "SUPPORT"
    assert bindings["release_date"]["supports"][0]["normalized_value"] == "2025-10-07"


def test_projection_cannot_force_support_without_a_relation():
    body = "Python 3.14.0 documentation updated on 2025-10-07."
    digest = hashlib.sha256(body.encode()).hexdigest()
    trusted = project_trusted_sources(_ledger(body=body, digest=digest))
    claims = project_mechanical_claims(["release_date"], trusted, target=("Python", "3.14.0"))
    bindings = bind_fields(["release_date"], claims, trusted)
    assert bindings["release_date"]["status"] == "NOT_EVALUATED"
    assert bindings["release_date"]["supports"] == []


# --- adjacent versions must never be confused (blocker: weak identity grammar) -----


def _ledger_for(body):
    digest = hashlib.sha256(body.encode()).hexdigest()
    return _ledger(body=body, digest=digest)


def test_canonical_zero_patch_alias_is_accepted():
    claims = project_mechanical_claims(
        ["release_date"], project_trusted_sources(_ledger_for("Python 3.14.0 was released on 2025-10-07.")), target=("Python", "3.14")
    )
    assert len(claims) == 1


def test_adjacent_patch_is_not_the_same_identity():
    claims = project_mechanical_claims(
        ["release_date"], project_trusted_sources(_ledger_for("Python 3.14.1 was released on 2025-10-07.")), target=("Python", "3.14")
    )
    assert claims == []


def test_adjacent_minor_is_not_the_same_identity():
    claims = project_mechanical_claims(
        ["release_date"], project_trusted_sources(_ledger_for("Python 3.13 was released on 2025-10-07.")), target=("Python", "3.14")
    )
    assert claims == []
