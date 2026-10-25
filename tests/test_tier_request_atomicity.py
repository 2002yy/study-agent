"""CL-M3 QD-3e: a refused upgrade request must leave no row behind.

The contract's authorisation rule is a *record* rule (CL_M3_CAPABILITY_CONTRACT
§11.3): an upgrade happens only when a stored authorisation covers it. That
makes the inverse just as important - a request that the domain refuses must
not be stored either. A row that a caller was told had failed is worse than no
row: the caller retries, and the retry meets a request nobody made.

**What was wrong, and why it was more than one field.** ``request_upgrade``
validated the tiers and the counts, committed the INSERT, and only then built
``TierUpgradeRequest`` - whose own checks run in ``__post_init__``. Everything
that lived in the record rather than in the hand-written checks therefore ran
*after* the write:

* ``requested_cost`` of ``inf`` passed ``isinstance`` and ``>= 0``, was stored
  as ``inf``, and only then failed the domain's finiteness rule;
* the method's own default ``reason=""`` failed the record's non-empty rule
  *after* the row was committed - so the documented default could never have
  worked, and every call that relied on it left a stray pending request.

Patching ``requested_cost`` would have left the ordering bug in place for the
next field that the record validates and the method does not. The fix is the
order: build the record first, store only what the record accepted, return the
same object. Each test below is a way to reach the old post-write failure; the
assertion is always the same - the database did not change.

**Negative control.** Against the pre-fix implementation every case in
``test_a_refused_request_writes_nothing`` fails on the row count (the
exception still raises, which is exactly why the defect was invisible).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from src.infrastructure.sqlite.database import RuntimeDatabase
from src.repositories.research_state_repository import ResearchStateRepository
from src.repositories.research_tier_repository import (
    ResearchTierRepository,
    TierAuthorizationDenied,
)

RESEARCH = "research-1"
THREAD = "thread-1"
OPERATION = "operation-1"


@pytest.fixture
def db(tmp_path):
    database = RuntimeDatabase(tmp_path / "runtime.sqlite")
    database.initialize()
    return database


@pytest.fixture
def repository(db):
    return ResearchTierRepository(db)


def _now(offset_seconds: float = 0.0) -> str:
    return (datetime.now(timezone.utc) + timedelta(seconds=offset_seconds)).isoformat()


def _create_research(db, research_id=RESEARCH, *, operation_id=OPERATION, tier="standard"):
    states = ResearchStateRepository(db)
    states.create(
        research_id=research_id,
        thread_id=THREAD,
        operation_id=operation_id,
        original_question="what is X?",
        question="what is X?",
        tier=tier,
    )
    return states


def _arguments(**overrides):
    """A request that would succeed, so each test can spoil exactly one field."""

    arguments = {
        "operation_id": OPERATION,
        "from_tier": "standard",
        "to_tier": "deep",
        "reason": "the standard tier cannot resolve this",
        "requested_calls": 10,
        "requested_cost": 1.25,
        "now": _now(),
    }
    arguments.update(overrides)
    return arguments


def _table_counts(db):
    with db.connect() as connection:
        requests = connection.execute(
            "SELECT COUNT(*) FROM research_tier_upgrade_requests"
        ).fetchone()[0]
        authorizations = connection.execute(
            "SELECT COUNT(*) FROM research_tier_authorizations"
        ).fetchone()[0]
    return requests, authorizations


def _research_row(db, research_id=RESEARCH):
    with db.connect() as connection:
        row = connection.execute(
            "SELECT * FROM research_states WHERE research_id = ?", (research_id,)
        ).fetchone()
    return None if row is None else dict(row)


def _assert_no_side_effects(db):
    """No request, no authorisation, and no change to the research it named."""

    assert _table_counts(db) == (0, 0)


# --- the record's own checks, reached through the repository -------------------------------


@pytest.mark.parametrize(
    "cost",
    [
        pytest.param(float("inf"), id="positive-infinity"),
        pytest.param(float("-inf"), id="negative-infinity"),
        pytest.param(float("nan"), id="not-a-number"),
        pytest.param(-0.01, id="negative"),
        pytest.param(True, id="bool"),
        pytest.param("1.25", id="string"),
        pytest.param(None, id="none"),
    ],
)
def test_a_refused_cost_writes_nothing(repository, db, cost):
    """``inf`` is the one that used to be stored: it is a float, and not negative.

    ``nan`` is the one that used to leak the storage layer's opinion: SQLite
    turns it into NULL, so the caller got an ``IntegrityError`` from the
    database instead of the domain's ``invalid_requested_cost``. Both are the
    same defect - a field validated after persistence - and both now refuse
    before the write.
    """

    _create_research(db)
    before = _research_row(db)

    with pytest.raises(ValueError, match="invalid_requested_cost"):
        repository.request_upgrade(RESEARCH, **_arguments(requested_cost=cost))

    _assert_no_side_effects(db)
    assert _research_row(db) == before


@pytest.mark.parametrize(
    "calls",
    [
        pytest.param(True, id="bool"),
        pytest.param(-1, id="negative"),
        pytest.param(1.5, id="float"),
        pytest.param("10", id="string"),
        pytest.param(None, id="none"),
    ],
)
def test_a_refused_call_count_writes_nothing(repository, db, calls):
    _create_research(db)
    before = _research_row(db)

    with pytest.raises(ValueError, match="invalid_requested_calls"):
        repository.request_upgrade(RESEARCH, **_arguments(requested_calls=calls))

    _assert_no_side_effects(db)
    assert _research_row(db) == before


@pytest.mark.parametrize(
    "reason",
    [
        pytest.param("", id="empty"),
        pytest.param("   ", id="whitespace"),
        pytest.param(None, id="none"),
        pytest.param(123, id="not-a-string"),
        pytest.param("x" * 2001, id="over-long"),
    ],
)
def test_a_refused_reason_writes_nothing(repository, db, reason):
    """The empty string is the method's old default, and it was never storable.

    Every call that omitted ``reason`` used to commit a pending request and
    then raise ``invalid_reason``. The default is gone, and ``reason`` is a
    required keyword: the method cannot be asked for a request the record will
    not hold.
    """

    _create_research(db)
    before = _research_row(db)

    with pytest.raises(ValueError, match="invalid_reason"):
        repository.request_upgrade(RESEARCH, **_arguments(reason=reason))

    _assert_no_side_effects(db)
    assert _research_row(db) == before


def test_the_reason_is_required(repository, db):
    """Omitting it is a programming error, not an empty (and storable) reason."""

    _create_research(db)
    arguments = _arguments()
    del arguments["reason"]

    with pytest.raises(TypeError):
        repository.request_upgrade(RESEARCH, **arguments)

    _assert_no_side_effects(db)


@pytest.mark.parametrize(
    ("field", "value", "expected"),
    [
        pytest.param("research_id", "", "invalid_research_id", id="research-empty"),
        pytest.param("research_id", "has space", "invalid_research_id", id="research-space"),
        pytest.param("research_id", None, "invalid_research_id", id="research-none"),
        pytest.param("operation_id", "", "invalid_operation_id", id="operation-empty"),
        pytest.param("operation_id", "../etc/passwd", "invalid_operation_id", id="operation-path"),
        pytest.param("request_id", "has space", "invalid_request_id", id="request-space"),
        pytest.param("request_id", "r" * 161, "invalid_request_id", id="request-over-long"),
    ],
)
def test_a_refused_identifier_writes_nothing(repository, db, field, value, expected):
    """Identifiers are validated by the record, not by the table's schema.

    The generated id is derived from the research id, so an invalid research id
    is tested with an explicit valid ``request_id``: otherwise the generated id
    would fail first and the test would pass for the wrong reason.
    """

    _create_research(db)
    before = _research_row(db)
    arguments = _arguments(request_id="request-1")
    if field == "research_id":
        research_id = value
    else:
        research_id = RESEARCH
        arguments[field] = value

    with pytest.raises(ValueError, match=expected):
        repository.request_upgrade(research_id, **arguments)

    _assert_no_side_effects(db)
    assert _research_row(db) == before


@pytest.mark.parametrize(
    ("field", "value", "expected"),
    [
        pytest.param("from_tier", "enterprise", "invalid_from_tier", id="unknown-from"),
        pytest.param("from_tier", "", "invalid_from_tier", id="empty-from"),
        pytest.param("to_tier", "enterprise", "invalid_to_tier", id="unknown-to"),
        pytest.param("to_tier", "", "invalid_to_tier", id="empty-to"),
    ],
)
def test_a_refused_tier_writes_nothing(repository, db, field, value, expected):
    _create_research(db)
    before = _research_row(db)

    with pytest.raises(ValueError, match=expected):
        repository.request_upgrade(RESEARCH, **_arguments(**{field: value}))

    _assert_no_side_effects(db)
    assert _research_row(db) == before


@pytest.mark.parametrize(
    "now",
    [
        pytest.param("not-a-timestamp", id="unparseable"),
        pytest.param(12345, id="not-a-string"),
    ],
)
def test_a_refused_timestamp_writes_nothing(repository, db, now):
    """``requested_at`` is the record's field too, so it is checked before the INSERT."""

    _create_research(db)
    before = _research_row(db)

    with pytest.raises(ValueError, match="invalid_requested_at"):
        repository.request_upgrade(RESEARCH, **_arguments(now=now, request_id="request-1"))

    _assert_no_side_effects(db)
    assert _research_row(db) == before


def test_a_request_for_an_unknown_research_writes_nothing(repository, db):
    """The ownership check still runs - and still leaves no request behind.

    It runs *after* validation now: a malformed request names nothing, and a
    refusal about a missing research would be the wrong answer to a question
    that was never well-formed.
    """

    with pytest.raises(TierAuthorizationDenied) as refused:
        repository.request_upgrade("missing-research", **_arguments())

    assert refused.value.reason == "research_not_found"
    _assert_no_side_effects(db)


# --- the positive case the guards must not break ------------------------------------------


def test_a_valid_request_is_stored_and_returned_as_the_record_it_validated(repository, db):
    """A legal request still lands, as ``pending``, and reads back identically.

    The point is not only that it succeeds: the returned object must be the
    one that was written, so a caller can never receive a value the database
    does not hold.
    """

    _create_research(db)
    before = _research_row(db)

    request = repository.request_upgrade(RESEARCH, **_arguments())

    assert request.status == "pending"
    assert request.approved is False
    assert _table_counts(db) == (1, 0)

    with db.connect() as connection:
        row = dict(
            connection.execute(
                "SELECT * FROM research_tier_upgrade_requests WHERE request_id = ?",
                (request.request_id,),
            ).fetchone()
        )

    assert row["research_id"] == request.research_id
    assert row["operation_id"] == request.operation_id
    assert row["from_tier"] == request.from_tier
    assert row["to_tier"] == request.to_tier
    assert row["reason"] == request.reason
    assert row["requested_calls"] == request.requested_calls
    assert row["requested_cost"] == pytest.approx(request.requested_cost)
    assert row["status"] == request.status
    assert row["requested_at"] == request.requested_at

    # A request is not a grant: the research itself has not moved.
    after = _research_row(db)
    assert after["tier"] == before["tier"]
    assert after["tier_upgrade_authorized"] == before["tier_upgrade_authorized"]


def test_the_request_id_stays_unique(repository, db):
    """Validation moving earlier must not move the primary key out of the way."""

    _create_research(db)
    first = repository.request_upgrade(RESEARCH, **_arguments())

    with pytest.raises(Exception):
        repository.request_upgrade(RESEARCH, **_arguments(request_id=first.request_id))

    assert _table_counts(db) == (1, 0)
