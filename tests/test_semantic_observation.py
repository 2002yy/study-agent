"""M3-QB acceptance: projecting execution observations into the planning episode.

Every test maps to §7.2 ("observation write-back") or Q-9 ("stop conditions") of
``docs/CL_M3_CAPABILITY_CONTRACT.md``. The negative controls are the point: a projection
that merely looks bounded, or a stop decision that cannot name its reason, is not
acceptance.
"""

from __future__ import annotations

import pytest

from src.web.semantic_observation import (
    ATTEMPT_CAP,
    ATTEMPT_FIELDS,
    CONTINUE,
    LEAD_CAP,
    LEAD_FIELDS,
    STOP_BUDGET_EXHAUSTED,
    STOP_CANCELLED,
    STOP_EVIDENCE_SUFFICIENT,
    STOP_NO_NEW_DIRECTION,
    STOP_REASONS,
    absorb,
    new_lead_urls,
    next_phase,
    project_attempts,
    project_leads,
)
from src.web.semantic_recovery import ResearchEpisode


def make_episode(**overrides) -> ResearchEpisode:
    fields = {
        "task_id": "run-1",
        "thread_id": "thread-1",
        "original_question": "漏斗和投掷器的区别",
        "questions": [{"id": "rq-1", "question": "两者机制差异"}],
        "source_run_id": "run-1",
        "attempts": [],
        "source_leads": [],
    }
    fields.update(overrides)
    return ResearchEpisode(**fields)


def is_public(url: str) -> bool:
    """Test-local predicate; the module takes it as an argument on purpose."""

    return isinstance(url, str) and url.startswith("https://example.")


def search(query: str, status: str = "ok") -> dict:
    return {"name": "web_search", "arguments": {"query": query}, "result": {"status": status}}


def read(url: str, *, content: str = "正文", status: str = "ok", **extra) -> dict:
    return {
        "name": "web_read",
        "arguments": {"url": url},
        "result": {"status": status, "content": content, **extra},
    }


# --- projection: bounded, legal, and not an audit log --------------------------------


def test_attempts_come_from_real_searches_in_issue_order():
    calls = [search("漏斗 机制", "ok"), read("https://example.org/a"), search("投掷器 机制", "empty")]
    rows = project_attempts([], calls)
    assert rows == [
        {"query": "漏斗 机制", "outcome": "ok"},
        {"query": "投掷器 机制", "outcome": "empty"},
    ]


def test_the_projection_never_exceeds_the_planning_cap():
    calls = [search(f"q{index}") for index in range(ATTEMPT_CAP + 4)]
    rows = project_attempts([], calls)
    assert len(rows) == ATTEMPT_CAP
    # Newest survive: the planner must see what just happened, not the oldest history.
    assert rows[-1]["query"] == f"q{ATTEMPT_CAP + 3}"
    assert rows[0]["query"] == "q4"


def test_long_values_are_clipped_to_what_the_parse_layer_accepts():
    rows = project_attempts([], [search("q" * 900, "s" * 400)])
    assert len(rows[0]["query"]) == 500
    assert len(rows[0]["outcome"]) == 100


def test_a_private_or_local_read_never_enters_the_planning_context():
    calls = [
        read("https://example.org/ok"),
        read("http://127.0.0.1:8080/secret"),
        read("file:///C:/secrets.txt"),
    ]
    rows = project_leads([], calls, is_public_url=is_public)
    assert [row["url"] for row in rows] == ["https://example.org/ok"]


def test_a_search_verdict_does_not_become_an_episode_field():
    """A read that the executor judged ``answer_eligible`` is still only an observation.

    The projection must carry exactly the schema the parse layer accepts, so evidence
    authority cannot ride along inside the planning episode.
    """

    rows = project_leads(
        [], [read("https://example.org/a", answer_eligible=True)], is_public_url=is_public
    )
    assert set(rows[0]) == set(LEAD_FIELDS)
    assert "answer_eligible" not in rows[0]


def test_identical_rows_are_not_recorded_twice():
    calls = [search("漏斗"), search("漏斗")]
    assert len(project_attempts([], calls)) == 1


def test_empty_calls_are_ignored_instead_of_recorded_as_blank_rows():
    rows = project_attempts([], [search(""), {"name": "web_search"}, "not-a-mapping", {}])
    assert rows == []


def test_previous_rounds_are_kept_so_a_second_round_can_replan_from_them():
    """Deliberate divergence from the legacy single-round block.

    That block replaced ``source_leads`` with the current operation's reads. In a multi-round
    loop that would erase the first round's findings exactly when the planner is asked to
    replan from them.
    """

    first = project_leads([], [read("https://example.org/first")], is_public_url=is_public)
    second = project_leads(
        first, [read("https://example.org/second")], is_public_url=is_public
    )
    assert [row["url"] for row in second] == [
        "https://example.org/first",
        "https://example.org/second",
    ]


def test_the_oldest_lead_is_dropped_first_when_the_cap_is_reached():
    calls = [read(f"https://example.org/{index}") for index in range(LEAD_CAP + 2)]
    rows = project_leads([], calls, is_public_url=is_public)
    assert len(rows) == LEAD_CAP
    assert rows[-1]["url"] == f"https://example.org/{LEAD_CAP + 1}"
    assert "https://example.org/0" not in [row["url"] for row in rows]


# --- the strongest legality proof: the result can be parsed back ----------------------


def test_the_absorbed_episode_survives_the_real_parse_layer():
    """If the projection were illegal, the episode would become unpersistable.

    This is the check that keeps the module honest: ``ResearchEpisode.parse`` enforces the
    key sets and the field caps, so a projection that quietly drifts fails here rather than
    at some later persistence boundary.
    """

    episode = absorb(
        make_episode(),
        [
            search("q" * 900, "s" * 400),
            read("https://example.org/a", content="c" * 900, status="ok"),
            read("https://example.org/b", content="", status="failed"),
        ],
        is_public_url=is_public,
    )
    restored = ResearchEpisode.parse(episode.to_dict(), thread_id="thread-1")
    assert len(restored.attempts) == 1
    assert len(restored.source_leads) == 2
    assert restored.original_question == "漏斗和投掷器的区别"


# --- Q-9: four stop conditions, each distinguishable ---------------------------------


def test_every_stop_reason_is_distinct_and_reachable():
    assert STOP_REASONS == {
        CONTINUE,
        STOP_EVIDENCE_SUFFICIENT,
        STOP_NO_NEW_DIRECTION,
        STOP_BUDGET_EXHAUSTED,
        STOP_CANCELLED,
    }
    produced = {
        next_phase(cancelled=c, budget_remaining=b, new_leads=n, model_intent=i)
        for c, b, n, i in [
            (False, 2, 1, "CONTINUE_ACTIVE_RESEARCH"),
            (False, 2, 1, "ANSWER"),
            (False, 2, 0, "CONTINUE_ACTIVE_RESEARCH"),
            (False, 0, 1, "CONTINUE_ACTIVE_RESEARCH"),
            (True, 2, 1, "CONTINUE_ACTIVE_RESEARCH"),
        ]
    }
    assert produced == STOP_REASONS


def test_cancellation_outranks_budget_and_the_models_own_preference():
    assert next_phase(cancelled=True, budget_remaining=0, new_leads=0, model_intent="ANSWER") == STOP_CANCELLED


def test_budget_outranks_the_models_wish_to_keep_going():
    assert next_phase(cancelled=False, budget_remaining=0, new_leads=5, model_intent="CONTINUE_ACTIVE_RESEARCH") == STOP_BUDGET_EXHAUSTED


def test_the_model_owns_the_sufficiency_judgement_not_this_function():
    """§7.1 layer three gives the sufficiency call to the model.

    If the adapter could return ``evidence_sufficient`` on its own, it would be inventing an
    evidence judgement; the only way to reach that stop reason is the model saying ANSWER.
    """

    for intent in ("CONTINUE_ACTIVE_RESEARCH", "NEW_RESEARCH", "REFINE_RESEARCH", "ABSTAIN"):
        assert next_phase(cancelled=False, budget_remaining=3, new_leads=1, model_intent=intent) == CONTINUE
    assert next_phase(cancelled=False, budget_remaining=3, new_leads=1, model_intent="ANSWER") == STOP_EVIDENCE_SUFFICIENT


def test_a_round_that_found_nothing_new_is_a_loop_not_progress():
    assert next_phase(cancelled=False, budget_remaining=3, new_leads=0, model_intent="CONTINUE_ACTIVE_RESEARCH") == STOP_NO_NEW_DIRECTION


def test_new_leads_are_measured_against_the_previous_round():
    before = [{"url": "https://example.org/a"}]
    after = [{"url": "https://example.org/a"}, {"url": "https://example.org/b"}]
    assert new_lead_urls(before, after) == {"https://example.org/b"}
    assert new_lead_urls(after, after) == set()


@pytest.mark.parametrize("budget", [-1, 0])
def test_a_non_positive_budget_never_continues(budget: int):
    assert next_phase(cancelled=False, budget_remaining=budget, new_leads=9, model_intent="CONTINUE_ACTIVE_RESEARCH") == STOP_BUDGET_EXHAUSTED


def test_the_attempt_cap_is_the_one_the_parse_layer_enforces():
    from src.web.semantic_observation import LEAD_FIELD_CAPS

    assert ATTEMPT_CAP == 8
    assert LEAD_CAP == 5
    assert set(ATTEMPT_FIELDS) == {"query", "outcome"}
    assert set(LEAD_FIELDS) == {"url", "status", "reason", "summary"}
    assert LEAD_FIELD_CAPS == {"url": 500, "status": 100, "reason": 300, "summary": 300}
