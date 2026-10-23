"""AR-1C-2-E1/E4: one event per read attempt, one summary per round.

The movement layer answers "what material did I get"; the authoritative read
records stay the only source of truth. These controls pin that separation.
"""

from src.web.research.motion_events import (
    EVIDENCE_CONFLICT,
    EVIDENCE_READ,
    MAX_RECORDED_EVENTS,
    READ_FAILED,
    MotionEvent,
    record_event,
)
from src.web.research.read_evidence import (
    build_read_event,
    read_id_for,
    round_read_summary,
)

NOW = "2026-10-20T00:00:00+00:00"
PAGE = "版本 A 在旧设备上仍然受支持，因此兼容性测试仍然需要覆盖它。"


def _record(url, *, status="read", content=PAGE, error=None):
    read = {"ok": status == "read", "status": status}
    if status == "read":
        read["content"] = content
    else:
        read["error"] = error or "http_403"
    return {
        "read": read,
        "item": {"title": url, "url": url},
        "assessment": {"url": url},
    }


def _event(record, records, *, round_index=2):
    return build_read_event(
        run_id="run1",
        records=records,
        record=record,
        round_index=round_index,
        notes=3,
        revision="rev-2",
        at=NOW,
    )


def test_five_pages_in_one_round_produce_five_events():
    records = [_record(f"https://example.com/{index}") for index in range(5)]
    events = [_event(record, records) for record in records]

    assert [event.kind for event in events] == [EVIDENCE_READ] * 5
    assert len({event.identity() for event in events}) == 5


def test_a_failed_read_is_not_reported_as_evidence():
    record = _record("https://example.com/blocked", status="failed", error="http_403")
    event = _event(record, [record])

    assert event.kind == READ_FAILED
    assert event.detail["reason"] == "http_403"


def test_a_read_without_usable_content_is_a_failure_not_evidence():
    record = _record("https://example.com/empty", content="   ")
    event = _event(record, [record])

    assert event.kind == READ_FAILED
    assert event.detail["reason"] == "no_usable_content"


def test_a_page_that_was_never_attempted_produces_no_event():
    record = {
        "read": {"ok": False, "status": "skipped", "reason": "read_budget_exhausted"},
        "item": {"url": "https://example.com/skipped"},
    }
    assert _event(record, [record]) is None


def test_a_replayed_read_keeps_its_identity():
    record = _record("https://example.com/a")
    first = _event(record, [record])
    # Same persisted state, rebuilt after a restart: same identity, not a twin.
    rebuilt = dict(record)
    second = _event(rebuilt, [rebuilt])

    assert first.identity() == second.identity()
    assert first.identity() == read_id_for(
        run_id="run1", url="https://example.com/a", round_index=2, attempt=1
    )


def test_two_reads_of_the_same_url_are_two_attempts_not_a_duplicate():
    first = _record("https://example.com/a")
    second = _record("https://example.com/a")
    records = [first, second]

    events = [_event(first, [first]), _event(second, records)]

    assert events[0].identity() != events[1].identity()
    assert events[0].detail["read_id"] != events[1].detail["read_id"]


def test_the_diagnostic_window_overflows_without_touching_the_records():
    context = {}
    records = [_record(f"https://example.com/{index}") for index in range(25)]
    for index, record in enumerate(records):
        record["read"]["round"] = 1
        event = _event(record, records, round_index=1)
        assert event is not None
        record_event(context, event)

    assert len(context["revision_events"]) == MAX_RECORDED_EVENTS
    assert len(records) == 25
    summary = round_read_summary(records, context["revision_events"])
    assert summary == [{"round": 1, "read": 25, "failed": 0, "recent_recheck": 0}]


def test_the_round_summary_is_derived_from_records_not_from_the_event_window():
    records = [_record(f"https://example.com/{index}") for index in range(30)]
    for record in records:
        record["read"]["round"] = 2
    records.append(_record("https://example.com/blocked", status="failed"))
    records[-1]["read"]["round"] = 2
    events = [MotionEvent(kind=EVIDENCE_READ, at=NOW, round=2, detail={}).to_dict()]

    summary = round_read_summary(records, events)

    assert summary == [{"round": 2, "read": 30, "failed": 1, "recent_recheck": 0}]


def test_recent_recheck_is_only_counted_when_an_evaluation_raised_a_conflict():
    records = [_record("https://example.com/a")]
    records[0]["read"]["round"] = 2
    quiet = round_read_summary(records, [])
    conflict = MotionEvent(
        kind=EVIDENCE_CONFLICT,
        at=NOW,
        round=2,
        detail={"urls": ["https://example.com/a"]},
    ).to_dict()

    assert quiet[0]["recent_recheck"] == 0
    assert round_read_summary(records, [conflict])[0]["recent_recheck"] == 1


def test_reading_material_does_not_by_itself_make_an_answer_supported():
    # The event says "a page was read". It carries no claim about the answer, so a
    # consumer has nothing to promote: no replacement, no retraction.
    record = _record("https://example.com/a")
    event = _event(record, [record])

    assert event.kind == EVIDENCE_READ
    assert "replacement" not in event.detail
    assert "target_reply_id" not in event.detail


# -- P0: a binding is evidence only against a real read ----------------------
def _replacement(binding, replacement="版本 A 在旧设备上仍然受支持。"):
    from src.web.research.answer_revision import REPLACE, RevisionProposal

    return RevisionProposal(
        target_reply_id="run1:research",
        target_content_version=1,
        action=REPLACE,
        reason="新证据覆盖旧判断",
        research_revision="rev-2",
        research_round=2,
        research_notes=3,
        replacement=replacement,
        source_bindings=(binding,),
    )


def _reply():
    return {
        "reply_id": "run1:research",
        "scope": "research",
        "turn_id": "turn1",
        "lifecycle": "open",
        "content_version": 1,
        "stale": True,
        "text": "旧判断。",
        "citations": [],
        "content_state": {"round": 1, "notes": 2, "revision": "rev-1"},
    }


def test_a_binding_without_read_records_is_refused_outright():
    import hashlib

    from src.web.research.answer_revision import evaluate

    quote = PAGE[:20]
    binding = {
        "url": "https://example.com/a",
        "quote": quote,
        "quote_sha256": hashlib.sha256(quote.encode()).hexdigest(),
    }

    decision = evaluate(_replacement(binding), _reply())

    assert decision.accepted is False
    assert decision.refusal == "source_reads_unavailable"


def test_the_quote_hash_and_the_read_excerpt_hash_are_not_interchangeable():
    import hashlib

    from src.web.research.answer_revision import evaluate
    from src.web.research.read_evidence import ReadEvidence

    quote = PAGE[:20]
    reads = (ReadEvidence.build(url="https://example.com/a", excerpt=PAGE),)
    binding = {
        "url": "https://example.com/a",
        "quote": quote,
        "quote_sha256": hashlib.sha256(quote.encode()).hexdigest(),
        # the hash of the quote is not the hash of the page that was read
        "read_excerpt_sha256": hashlib.sha256(quote.encode()).hexdigest(),
    }

    decision = evaluate(_replacement(binding), _reply(), read_evidence=reads)

    assert decision.accepted is False
    assert decision.refusal == "read_excerpt_not_found"


def test_a_binding_must_name_a_read_that_happened():
    import hashlib

    from src.web.research.answer_revision import evaluate
    from src.web.research.read_evidence import ReadEvidence

    quote = PAGE[:20]
    reads = (ReadEvidence.build(url="https://example.com/a", excerpt=PAGE, read_id="real"),)
    binding = {
        "url": "https://example.com/a",
        "quote": quote,
        "quote_sha256": hashlib.sha256(quote.encode()).hexdigest(),
        "read_id": "invented",
    }

    decision = evaluate(_replacement(binding), _reply(), read_evidence=reads)

    assert decision.accepted is False
    assert decision.refusal == "read_id_not_found"


def test_a_binding_against_the_read_it_names_is_accepted():
    import hashlib

    from src.web.research.answer_revision import evaluate
    from src.web.research.read_evidence import ReadEvidence

    quote = PAGE[:20]
    read = ReadEvidence.build(url="https://example.com/a", excerpt=PAGE, read_id="r1")
    binding = {
        "url": "https://example.com/a/",  # normalisation must not create a miss
        "quote": quote,
        "quote_sha256": hashlib.sha256(quote.encode()).hexdigest(),
        "read_id": "r1",
        "read_excerpt_sha256": read.content_sha256,
    }

    decision = evaluate(_replacement(binding), _reply(), read_evidence=(read,))

    assert decision.accepted is True, decision.refusal
