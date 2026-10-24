"""Provisional reply contract: task understanding, attribution and lifecycle.

These replies are display-only.  The negative controls here are the point: an
unverified capability must never read as confirmed, a pre-supplement read must
never be claimed as the supplement's finding, and an additive supplement must
never invalidate an earlier judgment.
"""

from src.web.research.steering_replies import (
    ACKNOWLEDGEMENT_TEXT,
    LIFECYCLE_CLOSED,
    LIFECYCLE_OPEN,
    LIFECYCLE_SUPERSEDED,
    NOT_COVERED_TEXT,
    STAGE_ACKNOWLEDGEMENT,
    STAGE_ANALYSIS,
    STAGE_EVIDENCE,
    acknowledgement_reply,
    apply_analysis,
    apply_evidence,
    attribute_analysis,
    close_replies,
    content_fingerprint,
    find_reply,
    mark_additions_stale,
    mark_analysis_not_covered,
    merge_steering_replies,
    next_content_version,
    reply_id_for_steering,
    reply_projection,
    research_reply,
    research_reply_id,
    state_dominates,
    state_key,
    supersede_affected,
)

RUN = "web_lookup_run1"
NOW = "2026-10-18T00:00:00+00:00"


def reply_for(steering_id="s1", *, turn_id="turn1"):
    return acknowledgement_reply(
        run_id=RUN, steering_id=steering_id, turn_id=turn_id, now=NOW
    )


def understanding(**overrides):
    values = {
        "steering_id": "s1",
        "changed_focus": "比较标准扩展到脚本控制与图层级操作",
        "reason_to_check": "自动化能力取决于接口与批量处理，需要重新核对",
        "questions_to_verify": ["脚本接口支持哪些批量操作", "图层样式是否可保留"],
    }
    return values | overrides



def test_a_late_analysis_keeps_the_evidence_provenance():
    """B5: a task understanding arriving after a sourced judgment must not rewrite
    where that judgment's evidence came from.

    Otherwise an earlier judgment could look as if it had been produced from a
    later round, and its citations would claim a provenance they never had.
    """
    current = reply_for()
    evidence = {
        **current,
        "stage": STAGE_EVIDENCE,
        "content_version": 5,
        "based_on_version": 4,
        "text": "初步看可行。",
        "citations": [{"url": "https://example.org/automation", "quote": "脚本接口"}],
        "content_state": {"round": 3, "notes": 9, "revision": "revG2"},
    }
    updated = apply_analysis(
        [evidence],
        reply_id=evidence["reply_id"],
        understanding=understanding(),
        now="2026-10-18T00:00:09+00:00",
        version=6,
        state={"round": 4, "notes": 9, "revision": ""},
        based_on=5,
    )
    reply = find_reply(updated, evidence["reply_id"])
    # The evidence provenance and its citations survive untouched.
    assert reply["content_state"] == {"round": 3, "notes": 9, "revision": "revG2"}
    assert reply["citations"] == evidence["citations"]
    assert reply["stage"] == "evidence_update"
    assert reply["text"] == "初步看可行。"
    # The task understanding records its own provenance separately.
    assert reply["analysis_provenance"] == {"round": 4, "notes": 9, "revision": ""}
    assert reply["analysis_state"] == "ready"

def test_acknowledgement_states_no_analysis_and_carries_no_authority():
    reply = reply_for()
    assert reply["text"] == ACKNOWLEDGEMENT_TEXT
    assert reply["stage"] == STAGE_ACKNOWLEDGEMENT
    assert reply["lifecycle"] == LIFECYCLE_OPEN
    assert reply["analysis_state"] == "pending"
    assert reply["citations"] == []
    assert "（尚未生成模型分析）" in reply["text"]


def test_analysis_text_describes_the_task_only():
    replies = apply_analysis(
        [reply_for()], reply_id=reply_id_for_steering(RUN, "s1"),
        understanding=understanding(), now=NOW, version=2,
    )
    reply = find_reply(replies, reply_id_for_steering(RUN, "s1"))
    assert reply["stage"] == STAGE_ANALYSIS
    assert reply["analysis_state"] == "ready"
    assert reply["content_version"] == 2
    assert "评估重点变化：比较标准扩展到脚本控制与图层级操作" in reply["text"]
    assert "接下来核查：脚本接口支持哪些批量操作" in reply["text"]
    # A task understanding never carries citations or evidence language.
    assert reply["citations"] == []
    assert "已验证" not in reply["text"]


def test_analysis_is_refused_once_the_reply_is_not_open():
    superseded = [reply_for() | {"lifecycle": LIFECYCLE_SUPERSEDED}]
    updated = apply_analysis(
        superseded, reply_id=reply_id_for_steering(RUN, "s1"),
        understanding=understanding(), now=NOW, version=2,
    )
    assert find_reply(updated, reply_id_for_steering(RUN, "s1"))["content_version"] == 1


def test_additive_supplement_marks_stale_but_never_supersedes():
    first = apply_analysis(
        [reply_for("s1")], reply_id=reply_id_for_steering(RUN, "s1"),
        understanding=understanding(), now=NOW, version=2,
        state={"round": 1, "notes": 1, "revision": "rev-a"},
    )
    second = reply_for("s2")
    updated = mark_additions_stale(
        first + [second], keep_reply_id=reply_id_for_steering(RUN, "s2"),
        added_round=2, now=NOW,
    )
    older = find_reply(updated, reply_id_for_steering(RUN, "s1"))
    assert older["lifecycle"] == LIFECYCLE_OPEN  # an added condition is not a refutation
    assert older["stale"] is True
    assert older["text"].endswith("（尚未覆盖后续新增的条件）")
    assert find_reply(updated, reply_id_for_steering(RUN, "s2"))["stale"] is False


def test_additions_never_replay_history_against_each_other():
    """Processing A then B must not make A and B invalidate each other."""
    a = apply_analysis(
        [reply_for("s1")], reply_id=reply_id_for_steering(RUN, "s1"),
        understanding=understanding(), now=NOW, version=2,
        state={"round": 1, "notes": 1, "revision": "rev-a"},
    )
    b = apply_analysis(
        a + [reply_for("s2")], reply_id=reply_id_for_steering(RUN, "s2"),
        understanding=understanding(steering_id="s2"), now=NOW, version=2,
        state={"round": 2, "notes": 2, "revision": "rev-b"},
    )
    # B is incorporated in round 3: only older content may be marked.
    after_b = mark_additions_stale(
        b, keep_reply_id=reply_id_for_steering(RUN, "s2"), added_round=3, now=NOW
    )
    assert find_reply(after_b, reply_id_for_steering(RUN, "s1"))["stale"] is True
    assert find_reply(after_b, reply_id_for_steering(RUN, "s2"))["stale"] is False
    # Replaying A (round 1) must not touch B, which is newer.
    after_a = mark_additions_stale(
        after_b, keep_reply_id=reply_id_for_steering(RUN, "s1"), added_round=1, now=NOW
    )
    assert find_reply(after_a, reply_id_for_steering(RUN, "s2"))["stale"] is False


def test_every_content_or_lifecycle_change_advances_the_version():
    reply = apply_analysis(
        [reply_for("s1")], reply_id=reply_id_for_steering(RUN, "s1"),
        understanding=understanding(), now=NOW, version=2,
        state={"round": 2, "notes": 2, "revision": "rev-a"},
    )
    stale = mark_additions_stale(
        reply, keep_reply_id="other", added_round=3, now=NOW
    )
    assert find_reply(stale, reply_id_for_steering(RUN, "s1"))["content_version"] == 3
    superseded = supersede_affected(stale, old_terms=["评估重点变化"], now=NOW)
    assert find_reply(superseded, reply_id_for_steering(RUN, "s1"))["content_version"] == 4
    # A superseded reply is already terminal; closing must not rewrite it.
    closed = close_replies(superseded, now=NOW, run_status="completed")
    assert find_reply(closed, reply_id_for_steering(RUN, "s1"))["lifecycle"] == LIFECYCLE_SUPERSEDED
    # Closing an open reply is a lifecycle change and advances the version.
    open_reply = apply_analysis(
        [reply_for("s5")], reply_id=reply_id_for_steering(RUN, "s5"),
        understanding=understanding(steering_id="s5"), now=NOW, version=2,
    )
    closed_open = close_replies(open_reply, now=NOW, run_status="completed")
    closed_reply = find_reply(closed_open, reply_id_for_steering(RUN, "s5"))
    assert closed_reply["content_version"] == 3
    assert closed_reply["lifecycle_closed_by"] == "run_terminal"
    # A not-covered notice is also a change and advances the version.
    pending = reply_for("s3")
    notified = mark_analysis_not_covered(
        [pending], reply_id=reply_id_for_steering(RUN, "s3"), now=NOW
    )
    assert find_reply(notified, reply_id_for_steering(RUN, "s3"))["content_version"] == 2


def test_a_sourced_judgment_is_never_downgraded_or_erased():
    evidence = apply_evidence(
        [reply_for("s1")], reply_id=reply_id_for_steering(RUN, "s1"),
        analysis={"text": "根据已读材料，初步看可行。",
                  "citations": [{"url": "https://example.org/a", "quote": "q" * 20}]},
        now=NOW, version=2, state={"round": 2, "notes": 2, "revision": "rev-a"},
    )
    # The task understanding arrives later: it must not erase the sourced content.
    both = apply_analysis(
        evidence, reply_id=reply_id_for_steering(RUN, "s1"),
        understanding=understanding(), now=NOW, version=3,
        state={"round": 2, "notes": 2, "revision": "rev-a"},
    )
    reply = find_reply(both, reply_id_for_steering(RUN, "s1"))
    assert reply["stage"] == STAGE_EVIDENCE
    assert reply["citations"]
    assert "初步看可行" in reply["text"]
    assert reply["analysis_state"] == "ready"
    assert reply["focus"].startswith("比较标准扩展")
    # And a terminal "not covered" notice cannot replace the sourced text either.
    closed = close_replies(
        mark_analysis_not_covered(
            [reply_for("s9") | {"analysis_state": "pending"}],
            reply_id=reply_id_for_steering(RUN, "s9"), now=NOW,
        ),
        now=NOW,
    )
    assert find_reply(closed, reply_id_for_steering(RUN, "s9"))["text"] == NOT_COVERED_TEXT
    kept = mark_analysis_not_covered(
        evidence, reply_id=reply_id_for_steering(RUN, "s1"), now=NOW
    )
    assert find_reply(kept, reply_id_for_steering(RUN, "s1"))["citations"]


def test_same_state_update_requires_a_current_base_version():
    state = {"round": 4, "notes": 10, "revision": "rev-b"}
    durable = reply_for("s1") | {
        "content_version": 6, "stage": STAGE_ANALYSIS, "content_state": state,
        "text": "newest", "based_on_version": 5,
    }
    # Same research state, higher number, but produced from an older snapshot.
    stale_write = reply_for("s1") | {
        "content_version": 7, "stage": STAGE_ANALYSIS, "content_state": state,
        "text": "from an older snapshot", "based_on_version": 3,
    }
    merged = merge_steering_replies(
        {"steering_replies": [stale_write]}, {"steering_replies": [durable]}
    )
    reply = find_reply(merged["steering_replies"], reply_id_for_steering(RUN, "s1"))
    assert reply["text"] == "newest"
    assert reply["last_conflict"]["reason"] == "stale_base"
    # The same update, produced against the current version, is accepted.
    fresh_write = stale_write | {"based_on_version": 6, "text": "current"}
    merged = merge_steering_replies(
        {"steering_replies": [fresh_write]}, {"steering_replies": [durable]}
    )
    assert find_reply(merged["steering_replies"], reply_id_for_steering(RUN, "s1"))["text"] == "current"


def test_only_an_authoritative_freeze_may_close_a_reply():
    open_reply = reply_for("s1") | {"content_version": 2, "stage": STAGE_ANALYSIS, "text": "live"}
    claimed = reply_for("s1") | {
        "content_version": 3, "lifecycle": LIFECYCLE_CLOSED, "text": "claimed closed",
    }
    merged = merge_steering_replies(
        {"steering_replies": [claimed]}, {"steering_replies": [open_reply]}
    )
    reply = find_reply(merged["steering_replies"], reply_id_for_steering(RUN, "s1"))
    # A writer claiming "closed" without run-terminal provenance is ignored.
    assert reply["lifecycle"] == LIFECYCLE_OPEN
    assert reply["text"] == "live"

    authoritative = close_replies([open_reply], now=NOW, run_status="cancelled")
    merged = merge_steering_replies(
        {"steering_replies": [open_reply]}, {"steering_replies": authoritative}
    )
    reply = find_reply(merged["steering_replies"], reply_id_for_steering(RUN, "s1"))
    assert reply["lifecycle"] == LIFECYCLE_CLOSED
    assert reply["closed_run_status"] == "cancelled"


def test_attribution_requires_the_supplement_to_have_created_the_task():
    plan = [
        {"task_id": "t0", "sub_question": "共享核查", "status": "done",
         "steering_ids": ["s0", "s1"]},
    ]
    entry = {"id": "s1", "incorporated_in_round": 1}
    analysis = {"citations": [{"question": "共享核查", "round": 2, "quote": "q" * 20}]}
    # Associated but not created by this supplement: research-level, not its finding.
    assert attribute_analysis(analysis, plan=plan, entry=entry) is False
    creator = {"id": "s0", "incorporated_in_round": 1}
    assert attribute_analysis(analysis, plan=plan, entry=creator) is True


def test_fingerprint_distinguishes_task_revisions():
    first = reply_for("s1") | {"content_state": {"round": 2, "notes": 2, "revision": "rev-a"}}
    second = reply_for("s1") | {"content_state": {"round": 2, "notes": 2, "revision": "rev-b"}}
    assert content_fingerprint(first) != content_fingerprint(second)


def test_only_a_correction_of_the_replaced_term_supersedes():
    analysis = apply_analysis(
        [reply_for("s1")], reply_id=reply_id_for_steering(RUN, "s1"),
        understanding=understanding(changed_focus="图层样式保留能力"),
        now=NOW, version=2,
    )
    unrelated = apply_analysis(
        [reply_for("s2")], reply_id=reply_id_for_steering(RUN, "s2"),
        understanding=understanding(steering_id="s2", changed_focus="导出速度"),
        now=NOW, version=2,
    )
    updated = supersede_affected(
        analysis + unrelated, old_terms=["图层样式保留"], now=NOW
    )
    assert find_reply(updated, reply_id_for_steering(RUN, "s1"))["lifecycle"] == LIFECYCLE_SUPERSEDED
    assert find_reply(updated, reply_id_for_steering(RUN, "s2"))["lifecycle"] == LIFECYCLE_OPEN


def test_terminal_run_freezes_replies_and_never_leaves_one_silent():
    replies = [reply_for("s1"), research_reply(run_id=RUN, turn_id="turn1", now=NOW)]
    not_covered = mark_analysis_not_covered(
        replies, reply_id=reply_id_for_steering(RUN, "s1"), now=NOW, version=2
    )
    closed = close_replies(not_covered, now=NOW)
    assert all(reply["lifecycle"] == LIFECYCLE_CLOSED for reply in closed)
    assert find_reply(closed, reply_id_for_steering(RUN, "s1"))["text"] == NOT_COVERED_TEXT


def test_projection_closes_open_replies_only_when_the_run_is_not_active():
    context = {"steering_replies": [reply_for()]}
    live = reply_projection(context, run_id=RUN, turn_id="turn1", active=True)
    assert live[0]["lifecycle"] == LIFECYCLE_OPEN
    terminal = reply_projection(context, run_id=RUN, turn_id="turn1", active=False)
    assert terminal[0]["lifecycle"] == LIFECYCLE_CLOSED
    # An empty reply is never rendered as content.
    empty = reply_projection(
        {"steering_replies": [research_reply(run_id=RUN, turn_id="t", now=NOW)]},
        run_id=RUN, turn_id="t", active=True,
    )
    assert empty == []


def test_attribution_requires_the_supplement_own_questions_and_a_later_read():
    plan = [
        {"task_id": "steer_s1", "sub_question": "compare；新增研究目标：脚本接口",
         "status": "done", "steering_ids": ["s1"]},
        {"task_id": "t0", "sub_question": "基础比较", "status": "done", "steering_ids": []},
    ]
    entry = {"id": "s1", "incorporated_in_round": 2}
    good = {"citations": [
        {"question": "compare；新增研究目标：脚本接口", "round": 2, "quote": "x" * 20}
    ]}
    assert attribute_analysis(good, plan=plan, entry=entry) is True
    # Read before the supplement entered the plan: related, but not this supplement's finding.
    early = {"citations": [
        {"question": "compare；新增研究目标：脚本接口", "round": 1, "quote": "x" * 20}
    ]}
    assert attribute_analysis(early, plan=plan, entry=entry) is False
    # Material read for a question the supplement never created.
    foreign = {"citations": [{"question": "基础比较", "round": 2, "quote": "x" * 20}]}
    assert attribute_analysis(foreign, plan=plan, entry=entry) is False
    # Mixed citations never attribute to the supplement.
    mixed = {"citations": [
        {"question": "compare；新增研究目标：脚本接口", "round": 2, "quote": "x" * 20},
        {"question": "基础比较", "round": 2, "quote": "y" * 20},
    ]}
    assert attribute_analysis(mixed, plan=plan, entry=entry) is False
    assert attribute_analysis({"citations": []}, plan=plan, entry=entry) is False


def test_evidence_update_keeps_citations_bounded_and_clears_stale():
    stale = [reply_for() | {"stale": True, "stage": STAGE_ANALYSIS}]
    updated = apply_evidence(
        stale,
        reply_id=reply_id_for_steering(RUN, "s1"),
        analysis={"text": "根据已读材料，初步看两种方案都能接脚本。",
                  "citations": [{"url": f"https://example.org/{i}", "quote": "q" * 20} for i in range(5)]},
        now=NOW,
        version=3,
    )
    reply = find_reply(updated, reply_id_for_steering(RUN, "s1"))
    assert reply["stage"] == STAGE_EVIDENCE
    assert reply["stale"] is False
    assert len(reply["citations"]) == 3


def test_merge_keeps_the_newer_content_and_never_drops_a_durable_reply():
    newer = reply_for("s1") | {"content_version": 3, "stage": STAGE_ANALYSIS, "text": "newer"}
    older = reply_for("s1") | {"content_version": 2, "stage": STAGE_ANALYSIS, "text": "older"}
    incoming = {"steering_replies": [older]}
    durable = {"steering_replies": [newer]}
    merged = merge_steering_replies(incoming, durable)
    assert find_reply(merged["steering_replies"], reply_id_for_steering(RUN, "s1"))["text"] == "newer"
    # A reply that exists only durably survives an incoming snapshot without it.
    merged = merge_steering_replies({"steering_replies": []}, durable)
    assert find_reply(merged["steering_replies"], reply_id_for_steering(RUN, "s1"))["text"] == "newer"


def test_same_version_same_state_keeps_the_first_successful_write():
    state = {"round": 3, "notes": 4, "revision": "rev-a"}
    durable = reply_for("s1") | {"content_version": 5, "stage": STAGE_ANALYSIS,
                                 "content_state": state, "text": "durable"}
    incoming = reply_for("s1") | {"content_version": 5, "stage": STAGE_ANALYSIS,
                                  "content_state": state, "text": "incoming"}
    assert content_fingerprint(durable) != content_fingerprint(incoming)
    merged = merge_steering_replies(
        {"steering_replies": [incoming]}, {"steering_replies": [durable]}
    )
    reply = find_reply(merged["steering_replies"], reply_id_for_steering(RUN, "s1"))
    # Nothing is decided by updated_at, and the first atomic write is
    # authoritative for that content version.
    assert reply["text"] == "durable"
    assert reply["content_version"] == 5


def test_a_stale_writer_cannot_promote_older_analysis_by_a_higher_version():
    """The user's risk: write order must not outrank research freshness."""
    durable = reply_for("s1") | {
        "content_version": 6, "stage": STAGE_ANALYSIS, "text": "newer analysis",
        "content_state": {"round": 4, "notes": 6, "revision": "rev-b"},
    }
    stale = reply_for("s1") | {
        "content_version": 9, "stage": STAGE_ANALYSIS, "text": "older analysis",
        "content_state": {"round": 2, "notes": 1, "revision": "rev-a"},
    }
    merged = merge_steering_replies(
        {"steering_replies": [stale]}, {"steering_replies": [durable]}
    )
    reply = find_reply(merged["steering_replies"], reply_id_for_steering(RUN, "s1"))
    assert reply["text"] == "newer analysis"
    assert reply["content_version"] == 6


def test_newer_research_state_publishes_under_a_collision_free_version():
    durable = reply_for("s1") | {
        "content_version": 5, "stage": STAGE_ANALYSIS, "text": "older",
        "content_state": {"round": 2, "notes": 1, "revision": "rev-a"},
    }
    incoming = reply_for("s1") | {
        "content_version": 5, "stage": STAGE_ANALYSIS, "text": "newer",
        "content_state": {"round": 3, "notes": 3, "revision": "rev-b"},
    }
    merged = merge_steering_replies(
        {"steering_replies": [incoming]}, {"steering_replies": [durable]}
    )
    reply = find_reply(merged["steering_replies"], reply_id_for_steering(RUN, "s1"))
    assert reply["text"] == "newer"
    assert reply["content_version"] == 6


def test_research_reply_identity_is_stable_per_run():
    assert research_reply_id(RUN) == f"{RUN}:research"
    assert next_content_version(None) == 1
    assert next_content_version({"content_version": 4}) == 5


def test_state_ordering_ignores_the_interim_revision_hash():
    """A hash is an identity, not an ordering: it must never decide freshness."""
    same_round = reply_for("s1") | {"content_state": {"round": 3, "notes": 2, "revision": "zzz"}}
    other_revision = reply_for("s1") | {"content_state": {"round": 3, "notes": 2, "revision": "aaa"}}
    assert state_key(same_round) == state_key(other_revision)
    # Neither direction dominates: the revision cannot be used to order them.
    assert state_dominates(same_round, other_revision) is True
    assert state_dominates(other_revision, same_round) is True


def test_a_refused_write_is_recorded_instead_of_vanishing():
    durable = reply_for("s1") | {
        "content_version": 6, "stage": STAGE_ANALYSIS, "text": "authoritative",
        "content_state": {"round": 4, "notes": 6, "revision": "rev-b"},
    }
    stale = reply_for("s1") | {
        "content_version": 9, "stage": STAGE_ANALYSIS, "text": "stale",
        "content_state": {"round": 2, "notes": 1, "revision": "rev-a"},
    }
    merged = merge_steering_replies(
        {"steering_replies": [stale]}, {"steering_replies": [durable]}
    )
    reply = find_reply(merged["steering_replies"], reply_id_for_steering(RUN, "s1"))
    assert reply["text"] == "authoritative"
    assert reply["conflicts_refused"] == 1
    assert reply["last_conflict"]["reason"] == "older_state"
    assert reply["last_conflict"]["content_version"] == 9


def test_a_same_version_race_that_is_accepted_is_still_auditable():
    state = {"round": 3, "notes": 4, "revision": "rev-a"}
    durable = reply_for("s1") | {
        "content_version": 5, "stage": STAGE_ANALYSIS, "content_state": state, "text": "first",
    }
    incoming = reply_for("s1") | {
        "content_version": 5, "stage": STAGE_EVIDENCE, "content_state": state, "text": "second",
    }
    merged = merge_steering_replies(
        {"steering_replies": [incoming]}, {"steering_replies": [durable]}
    )
    reply = find_reply(merged["steering_replies"], reply_id_for_steering(RUN, "s1"))
    # Same state and same write order: the first atomic write stays authoritative.
    assert reply["text"] == "first"
    assert reply["conflicts_refused"] == 1
    assert reply["last_conflict"]["reason"] == "stale_write"
