"""M4-C5 extraction start gate: material-first, resource-edge fallback (frozen contract)."""

from __future__ import annotations


from src.web.research_tool_agent import (_eligible_windows, _extraction_gate)
from tests.test_evidence_loop import _loop_with

SIDES = ("漏斗", "投掷器")
GENERIC = ("Minecraft 是一款沙盒游戏，由 Mojang Studios 开发，玩家可以在其中建造与探索。"
           "该系列包含多个版本，例如 Java 版与基岩版。Minecraft 也是历史上最畅销的游戏之一。")
HOPPER = "漏斗是一种可以用来捕捉物品实体或转入转出容器中物品的方块，它会从上方吸收物品。"
DROPPER = "投掷器是一种可以将物品向前弹出的方块，它会将物品吐出而不是送入容器。"


class Body:
    def __init__(self, text: str, url: str = ""):
        self.text = text
        self.url = url
        self.quality: dict = {}


def test_a_generic_franchise_window_is_not_material_for_a_comparison():
    """The real failure: a window matching only "minecraft" must not make a goal look ready."""
    windows = _eligible_windows(("minecraft", "漏斗", "投掷器"), {"S1": Body(GENERIC)}, SIDES)
    assert windows == []
    hopper = _eligible_windows(("minecraft", "漏斗", "投掷器"), {"S2": Body(HOPPER)}, SIDES)
    assert hopper and hopper[0]["stated"] == ["漏斗"]


def test_gate_keeps_acquiring_while_a_real_next_step_exists():
    state, reason, goals = _extraction_gate(
        unfinished={"漏斗": ("漏斗",)}, goal_sides={"漏斗": SIDES},
        relevant={"S1": Body(GENERIC)}, confirmed={"https://x/漏斗页"},
        read_pages={}, exclusions={}, rnd=1, max_rounds=8, deadline=100.0, now=10.0,
        reserve=14.0, searches_left=2, reads_left=2, calls_left=10)
    assert (state, reason, goals) == ("acquiring", "material_incomplete", {})


def test_gate_does_best_effort_with_one_sided_material_at_the_resource_edge():
    """A goal with material must still be verified when the other side cannot be reached."""
    state, reason, goals = _extraction_gate(
        unfinished={"漏斗": ("漏斗",), "投掷器": ("投掷器",)},
        goal_sides={"漏斗": SIDES, "投掷器": SIDES},
        relevant={"S2": Body(HOPPER)}, confirmed=set(), read_pages={}, exclusions={},
        rnd=5, max_rounds=6, deadline=100.0, now=95.0, reserve=14.0,
        searches_left=0, reads_left=0, calls_left=10)
    assert state == "best_effort"
    assert list(goals) == ["漏斗"]          # only the goal that holds material
    assert reason == "no_acquisition_left"


def test_gate_abstains_when_nothing_is_checkable_and_nothing_to_acquire():
    state, reason, goals = _extraction_gate(
        unfinished={"漏斗": ("漏斗",)}, goal_sides={"漏斗": SIDES},
        relevant={"S1": Body(GENERIC)}, confirmed=set(), read_pages={}, exclusions={},
        rnd=5, max_rounds=6, deadline=100.0, now=20.0, reserve=14.0,
        searches_left=0, reads_left=0, calls_left=10)
    assert (state, reason, goals) == ("abstain", "no_acquisition_left", {})


def test_a_franchise_only_run_never_spends_the_extraction():
    """Deterministic replay of the Minecraft failure trajectory (generic page, no side)."""
    trace = _loop_with([
        {"tool": "read_page", "url": "https://example.org/a"},
        {"tool": "finish"},
    ], body=GENERIC)
    assert trace["claim_verdicts"] == [] and trace["claim_rejections"] == {}
    assert trace["cost"]["model_calls"] == 2          # no extraction call was spent
    gate = trace["extraction_gate"]
    assert gate["state"] in {"acquiring", "abstain"}
    assert trace["extraction_input"] == {}


def test_once_both_sides_are_in_hand_the_gate_says_ready():
    hopper = _eligible_windows(("漏斗", "投掷器"), {"S1": Body(HOPPER), "S2": Body(DROPPER)},
                               SIDES)
    assert len(hopper) == 2
    state, reason, goals = _extraction_gate(
        unfinished={"漏斗与投掷器": ("漏斗", "投掷器")},
        goal_sides={"漏斗与投掷器": SIDES},
        relevant={"S1": Body(HOPPER), "S2": Body(DROPPER)},
        confirmed=set(), read_pages={}, exclusions={}, rnd=2, max_rounds=8,
        deadline=100.0, now=10.0, reserve=14.0, searches_left=1, reads_left=1, calls_left=10)
    assert (state, reason) == ("ready", "")
    assert goals
