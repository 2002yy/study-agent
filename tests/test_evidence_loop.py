"""M4-C5: claim extraction, independent verification, gap-driven follow-ups.

Safety (no false support, no forged source, no guessing) and usefulness (a verifier-approved
claim does settle a goal, gaps do produce a next query) are both asserted.
"""
from __future__ import annotations

import json

from src.web.research_claim_verifier import verify_claims
from src.web.research_claims import extract_claims
from src.web.research_gap_planner import plan_followups
from src.web.research_notebook import ResearchNotebook
from src.web.research_tool_agent import AgentBudget, run_tool_agent
from tests.test_research_tool_agent import FakeGateway

#: A goal with TWO necessary requirements: punctuation splits it, nothing else.
GOAL = "快照机制、清理代价"
MECHANISM = ("多版本并发控制通过保留旧版本行来实现一致性：因为每个事务读取自己的快照，"
             "读操作不会阻塞写操作。代价是旧版本必须清理，否则会造成表膨胀。"
             "系统需要定期回收不再可见的行版本，否则查询会逐渐变慢。") * 3
#: An index/version page as the run really meets it: short labels, numbers, separators.
NAV_SHELL = "\n".join(f"{i}. Section title | v1.{i}" for i in range(30))


def _completion(actions, seen):
    seq = list(actions)

    def run(**kwargs):
        seen.append(kwargs.get("task_name") or "research_tool_agent")
        return json.dumps(seq.pop(0))

    return run


def _bodies(text: str = MECHANISM) -> tuple[ResearchNotebook, dict]:
    notebook = ResearchNotebook()
    notebook.record("https://example.org/a", "https://example.org/a", text, ["g1"])
    return notebook, dict(notebook.bodies)


# --- extraction ---------------------------------------------------------------------

def test_extraction_accepts_a_locatable_claim():
    _notebook, bodies = _bodies()
    quote = "代价是旧版本必须清理"
    claims = extract_claims(
        goals={"g1": ("快照", "代价")}, bodies=bodies,
        completion=_completion([{"claims": [{"goal_id": "g1", "source_id": "https://example.org/a",
                                            "claim": "MVCC 需要清理旧版本", "quote": quote}]}], []))
    assert len(claims) == 1
    claim = claims[0]
    assert claim.quote in MECHANISM
    assert MECHANISM[claim.span_start:claim.span_end] == quote


def test_extraction_rejects_forged_source_and_bad_span():
    _notebook, bodies = _bodies()
    forged = extract_claims(
        goals={"g1": ("快照",)}, bodies=bodies,
        completion=_completion([{"claims": [{"goal_id": "g1", "source_id": "https://evil.example",
                                            "claim": "x", "quote": "快照"}]}], []))
    assert forged == []
    unrelated = extract_claims(
        goals={"g1": ("真空",)}, bodies=bodies,
        completion=_completion([{"claims": [{"goal_id": "g1", "source_id": "https://example.org/a",
                                            "claim": "y", "quote": "完全不存在的一段"}]}], []))
    assert unrelated == []


def test_extraction_drops_urls_the_model_writes_into_a_claim():
    _notebook, bodies = _bodies()
    claims = extract_claims(
        goals={"g1": ("快照",)}, bodies=body_safe(),
        completion=_completion([{"claims": [{"goal_id": "g1", "source_id": "https://example.org/a",
                                            "claim": "见 https://evil.example 的说明", "quote": "快照"}]}], []))
    assert claims and "http" not in claims[0].claim


def body_safe() -> dict:
    _notebook, bodies = _bodies()
    return bodies


# --- verification -------------------------------------------------------------------

def _claims(quote: str = "代价是旧版本必须清理"):
    _notebook, bodies = _bodies()
    return extract_claims(
        goals={"g1": ("快照", "代价")}, bodies=bodies,
        completion=_completion([{"claims": [{"goal_id": "g1", "source_id": "https://example.org/a",
                                            "claim": "MVCC 有清理代价", "quote": quote}]}], [])), bodies


def test_verifier_only_model_support_counts_and_abstention_never_supports():
    claims, bodies = _claims()
    supported = verify_claims(claims=claims, goals={"g1": ("快照", "代价")},
                              label_to_id={"g1": "g1"}, bodies=bodies, adopted={},
                              completion=_completion([{"verdicts": [
                                  {"claim_id": "c0", "verdict": "supported", "reason": "states it"}]}], []))
    assert supported[0].internal_supported
    abstained = verify_claims(claims=claims, goals={"g1": ("快照", "代价")},
                              label_to_id={"g1": "g1"}, bodies=bodies, adopted={},
                              completion=_completion([{"verdicts": []}], []))
    assert abstained[0].verdict == "insufficient"


def test_evicted_body_without_enough_excerpt_is_unavailable():
    claims, _bodies_map = _claims()
    verdicts = verify_claims(claims=claims, goals={"g1": ("快照", "代价")},
                             label_to_id={"g1": "g1"}, bodies={}, adopted={},
                             completion=_completion([], []))
    assert verdicts[0].verdict == "unavailable"


# --- the old keyword rule can no longer settle a goal --------------------------------

def test_keyword_rule_never_marks_a_goal_supported():
    gateway = FakeGateway()
    gateway.read = lambda url, max_chars=6000, timeout=8: {
        "ok": True, "url": url, "content": MECHANISM}
    trace = run_tool_agent(
        gateway=gateway, completion=_completion(
            [{"tool": "read_page", "url": "https://example.org/a"}, {"tool": "finish"}], []),
        question="PostgreSQL 的快照和代价",
        budget=AgentBudget(max_rounds=3, max_searches=2, max_reads=2, hard_seconds=30.0),
        sub_goals=(("g1", ("快照", "代价")),),
        initial_urls=("https://example.org/a",), evidence_loop=False,
    )
    states = {k: (v or {}).get("status")
              for k, v in (trace["coverage_audit"]["sub_goals"] or {}).items()}
    assert states and all(value != "supported" for value in states.values()), states


# --- gap planner --------------------------------------------------------------------

def test_gap_planner_is_bounded_and_skips_issued_queries():
    claims, _bodies_map = _claims()
    verdicts = verify_claims(claims=claims, goals={"g1": ("快照", "代价")},
                             label_to_id={"g1": "g1"}, bodies={}, adopted={},
                             completion=_completion([], []))
    planned = plan_followups(verdicts=verdicts, goals={"g1": ("快照", "代价", "清理")},
                             issued=[])
    assert planned and len(planned) <= 2
    assert "代价" in planned[0]["query"] or "清理" in planned[0]["query"]
    again = plan_followups(verdicts=verdicts, goals={"g1": ("快照", "代价", "清理")},
                           issued=[planned[0]["query"]])
    assert all(item["query"] != planned[0]["query"] for item in again)


# --- loop integration and budget ----------------------------------------------------

def _loop_with(actions: list[dict], body: str = MECHANISM) -> dict:
    gateway = FakeGateway()
    gateway.read = lambda url, max_chars=6000, timeout=8: {
        "ok": True, "url": url, "content": body}
    seen: list[str] = []
    return run_tool_agent(
        gateway=gateway, completion=_completion(actions, seen),
        question="PostgreSQL 的快照和代价", evidence_loop=True,
        budget=AgentBudget(max_rounds=4, max_searches=3, max_reads=2, hard_seconds=40.0),
        sub_goals=((GOAL, ("快照", "代价")),),
        initial_urls=("https://example.org/a",),
    )


def _loop_run(quote: str, covers: list[int] | None = None) -> dict:
    return _loop_with([
        {"tool": "read_page", "url": "https://example.org/a"},
        {"claims": [{"goal_id": GOAL, "source_id": "S1",
                     "claim": "MVCC 需要清理旧版本", "quote": quote}]},
        {"verdicts": [{"claim_id": "c0", "verdict": "supported", "reason": "states it",
                       "covers": covers if covers is not None else [0]}]},
        {"tool": "finish"},
    ])


def test_partial_support_does_not_settle_a_goal():
    """One claim answers ONE requirement; a goal needing two stays unsettled."""
    trace = _loop_run("代价是旧版本必须清理", covers=[0])
    assert trace["claim_verdicts"] and trace["claim_verdicts"][0]["verdict"] == "supported"
    assert trace["coverage_audit"]["sub_goals"][GOAL]["status"] == "explored"
    assert trace["goal_status"][GOAL] == "goal_partial"
    assert any(row.get("partial") for row in trace["goal_evidence"].get(GOAL, []))


def test_complete_coverage_settles_the_goal_and_counts_calls():
    """Both requirements covered: the goal is settled, and the loop costs two calls."""
    trace = _loop_run("每个事务读取自己的快照，读操作不会阻塞写操作。代价是旧版本必须清理",
                      covers=[0, 1])
    assert trace["coverage_audit"]["sub_goals"][GOAL]["status"] == "supported"
    assert trace["goal_status"][GOAL] == "goal_supported"
    assert trace["cost"]["model_calls"] == 4          # read decision + extract + verify + finish
    assert trace["evidence_outcome"] == "verified"


def test_a_supported_claim_without_covered_items_is_not_completion():
    """A verifier that says 'supported' but names no requirement cannot settle a goal."""
    trace = _loop_run("代价是旧版本必须清理", covers=[])
    assert trace["coverage_audit"]["sub_goals"][GOAL]["status"] == "explored"
    assert trace["goal_status"][GOAL] == "goal_insufficient"


def test_navigation_shell_never_spends_the_evidence_loop():
    """An index page in hand is not material: the loop must wait, not burn its one chance."""
    trace = _loop_with([
        {"tool": "read_page", "url": "https://example.org/a"},
        {"tool": "finish"},
    ], body=NAV_SHELL)
    assert trace["body_kinds"] == {"S1": "navigation"}
    assert trace["substantive_bodies"] == []
    assert trace["navigation_only_reads"] == ["S1"]
    assert trace["evidence_loop_skipped"] == "no_substantive_body"
    assert trace["evidence_outcome"] == "no_substantive_body"
    assert trace["claim_verdicts"] == [] and trace["claim_rejections"] == {}
    assert trace["cost"]["model_calls"] == 2          # read decision + finish, no extraction


def test_windows_refuse_a_list_only_passage():
    """A passage that is nothing but itemised names is not offered as a window."""
    body = (" - 快照 - 代价 - 清理 - 版本 - 回收 - 膨胀 - 事务 - 并发 - 阻塞 - 读锁 - 写锁")
    from src.web.research_claims import candidate_windows

    assert candidate_windows(("快照",), {"S1": type("B", (), {"text": body})()}) == []


def test_number_corroboration_keeps_three_conservative_states():
    """A quantity is the cheapest thing for a source to get wrong, so this stays stingy.

    An unrelated number NEVER clears the warning: only the same attribute with the same amount
    counts as corroboration, and the same attribute with a different amount is a conflict.
    """
    from src.web.research_tool_agent import _number_corroboration

    quote = "漏斗可以用1个铁锭和1个箱子合成"
    assert _number_corroboration(quote, ("漏斗",), {
        "S1": "漏斗可以用5个铁锭和1个箱子合成，这是标准配方。"}) == "number_conflict"
    assert _number_corroboration(quote, ("漏斗",), {
        "S1": "漏斗需要1个铁锭和1个箱子。"}) == ""
    assert _number_corroboration(quote, ("漏斗",), {
        "S1": "漏斗在 Java 1.5 快照中加入，合成需要铁锭。"}) == "number_uncorroborated"
    assert _number_corroboration(quote, ("漏斗",), {
        "S1": "| 材料 | 合成配方 | |---|---| | 铁锭 + 箱子 | 挖掘漏斗需要镐。"}
    ) == "number_uncorroborated"
    assert _number_corroboration("漏斗是一种方块", ("漏斗",), {"S1": "漏斗是一种方块。"}) == ""


def test_needs_review_is_reported_in_the_trace():
    """The run exposes the review marks; a digit-free finding raises none."""
    trace = _loop_run("代价是旧版本必须清理", covers=[0])
    assert trace["needs_review"] == []


def test_an_off_topic_body_never_spends_the_evidence_loop():
    """A substantive page about something else is not material: keep acquiring, don't spend.

    This is the Minecraft failure mode: the run read a real "item" article, spent its single
    extraction on it, and never examined the mechanism article it read much later.
    """
    trace = _loop_with([
        {"tool": "read_page", "url": "https://example.org/a"},
        {"tool": "finish"},
    ], body="Minecraft 的物品是出现在物品栏中的物体，它们有各种不同的行为与作用。"
           "所有物品都有堆叠限制，大多数物品的最大堆叠数量为 64，但有些物品为 16。"
           "物品实体可以使用它们所代表的物品，盔甲架可以展示盔甲并被玩家看见。")
    assert trace["body_kinds"] == {"S1": "substantive"}
    assert trace["evidence_loop_skipped"] == "no_relevant_body"
    assert trace["evidence_outcome"] == "no_relevant_body"
    assert trace["claim_rejections"] == {} and trace["claim_verdicts"] == []
    assert trace["cost"]["model_calls"] == 2          # read decision + finish, no extraction


def test_empty_extraction_is_reported_as_such():
    trace = _loop_with([
        {"tool": "read_page", "url": "https://example.org/a"},
        {"claims": []},
        {"tool": "finish"},
    ])
    assert trace["claim_verdicts"] == []
    assert trace["claim_rejections"] == {"no_claims_returned": 1}
    assert trace["evidence_outcome"] == "extraction_no_claim"


def test_unsupported_verdict_is_reported_as_insufficient():
    trace = _loop_with([
        {"tool": "read_page", "url": "https://example.org/a"},
        {"claims": [{"goal_id": GOAL, "source_id": "S1", "claim": "MVCC 需要清理旧版本",
                     "quote": "代价是旧版本必须清理"}]},
        {"verdicts": [{"claim_id": "c0", "verdict": "insufficient", "reason": "not stated"}]},
        {"tool": "finish"},
    ])
    assert trace["claim_verdicts"][0]["verdict"] == "insufficient"
    assert trace["coverage_audit"]["sub_goals"][GOAL]["status"] != "supported"
    assert trace["evidence_outcome"] == "verification_insufficient"
