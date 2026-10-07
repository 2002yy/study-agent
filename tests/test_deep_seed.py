"""Deep-1 seed projection: only bytes the durable Standard journal actually holds.

The point of the seed is that Deep never re-fetches a URL Standard already read. That only
works if the seed is derived from the journal and re-hashed, so a body that does not describe
its recorded digest is refused rather than carried forward.
"""

from __future__ import annotations

import hashlib

from src.web.research.deep_seed import DEEP_SEED_SCHEMA, project_standard_seed, seed_refs_match
from src.web.research.standard_binding_projection import journal_work_key

BODY = "Python 3.14.0 was released on 2025-10-07."
SHA = hashlib.sha256(BODY.encode()).hexdigest()
URL = "https://www.python.org/downloads/release/python-3140/"
CHILD = "standard-abc"


def _ledger(body=BODY, *, digest=SHA, state="completed", readable=True, kind="read", origin="standard"):
    return {
        "research": {
            "observations": [
                {
                    "kind": kind,
                    "target": URL,
                    "fields": ["release_date"],
                    "readable": readable,
                    "origin": origin,
                    "content_sha256": digest if readable else "",
                }
            ]
        },
        "entries": {journal_work_key("read", URL): {"state": state, "result": {"content": body}}},
    }


# --- D14: seed body comes only from the durable journal ---------------------------


def test_a_readable_matching_source_becomes_a_seed():
    seed = project_standard_seed(_ledger(), standard_child_run_id=CHILD)
    assert seed["schema_version"] == DEEP_SEED_SCHEMA
    assert seed["standard_child_run_id"] == CHILD
    assert len(seed["sources"]) == 1
    assert seed["sources"][0]["content"] == BODY
    assert seed["sources"][0]["content_sha256"] == SHA
    assert seed["sources"][0]["fields"] == ["release_date"]
    assert seed["sources"][0]["origin"] == "standard"


def test_seed_refs_carry_no_content():
    seed = project_standard_seed(_ledger(), standard_child_run_id=CHILD)
    assert set(seed["refs"][0]) == {"url", "content_sha256", "fields", "origin"}


# --- D9: a body that does not rehash is not a seed --------------------------------


def test_a_body_that_does_not_rehash_is_not_a_seed():
    seed = project_standard_seed(
        _ledger(body="tampered body", digest=SHA), standard_child_run_id=CHILD
    )
    assert seed["sources"] == []
    assert seed["refs"] == []


def test_an_incomplete_entry_is_not_a_seed():
    assert project_standard_seed(_ledger(state="failed"), standard_child_run_id=CHILD)["sources"] == []


def test_an_unreadable_observation_is_not_a_seed():
    assert project_standard_seed(_ledger(readable=False), standard_child_run_id=CHILD)["sources"] == []


def test_a_non_read_observation_is_not_a_seed():
    assert project_standard_seed(_ledger(kind="search"), standard_child_run_id=CHILD)["sources"] == []


def test_an_empty_body_is_not_a_seed():
    empty = ""
    seed = project_standard_seed(
        _ledger(body=empty, digest=hashlib.sha256(empty.encode()).hexdigest()),
        standard_child_run_id=CHILD,
    )
    assert seed["sources"] == []


# --- mismatch is a hard stop, not a silent drop -----------------------------------


def test_matching_refs_are_accepted():
    seed = project_standard_seed(_ledger(), standard_child_run_id=CHILD)
    assert seed_refs_match(seed["refs"], seed["refs"]) is True


def test_a_claimed_ref_absent_from_the_journal_does_not_match():
    seed = project_standard_seed(_ledger(), standard_child_run_id=CHILD)
    claimed = [*seed["refs"], {"url": "https://evil", "content_sha256": "d" * 64}]
    assert seed_refs_match(claimed, seed["refs"]) is False


def test_a_ref_with_a_different_digest_does_not_match():
    seed = project_standard_seed(_ledger(), standard_child_run_id=CHILD)
    claimed = [{"url": URL, "content_sha256": "d" * 64}]
    assert seed_refs_match(claimed, seed["refs"]) is False
