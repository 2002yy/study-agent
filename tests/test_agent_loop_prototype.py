"""§38 agent-loop prototype: bounded controller logic without network access."""

from __future__ import annotations

from tools.run_agent_loop_prototype import LoopBudget, run_loop

QUESTION = "What pull-rate limits apply to Docker Hub?"


def _search(results_by_query: dict[str, list[dict]]):
    calls: list[str] = []

    def search_fn(query: str, max_items: int) -> dict:
        calls.append(query)
        return {"results": results_by_query.get(query, [])[:max_items]}

    search_fn.calls = calls  # type: ignore[attr-defined]
    return search_fn


def _read(pages: dict[str, str]):
    calls: list[str] = []

    def read_fn(url: str, max_chars: int) -> dict:
        calls.append(url)
        content = pages.get(url)
        if content is None:
            return {"ok": False, "error": "not_found"}
        return {"ok": True, "content": content[:max_chars]}

    read_fn.calls = calls  # type: ignore[attr-defined]
    return read_fn


def _plan_next(*queries: str):
    state = {"index": 0}

    def planner_fn(_state):
        if state["index"] >= len(queries):
            return {"sufficient": True}
        query = queries[state["index"]]
        state["index"] += 1
        return {"query": query, "sufficient": False, "reason": "need the fact"}

    return planner_fn


def _select_all(state, candidates, max_urls):
    del state
    return [entry["canonical_url"] for entry in candidates][:max_urls]


def _extract_relation(relation_by_url: dict[str, str]):
    def extract_fn(question, entry, content):
        del question, content
        return {"relation": relation_by_url.get(entry["canonical_url"], "lead")}

    return extract_fn


RESULTS = [
    {"url": "https://docs.docker.com/usage/pulls/", "title": "Pull usage and limits"},
    {"url": "https://example.com/other", "title": "Other page"},
]


def _run(**overrides):
    params = {
        "case_id": "case-x",
        "question": QUESTION,
        "budget": LoopBudget(max_searches=4, max_reads=6, case_timeout_seconds=60.0),
        "search_fn": _search({"q1": RESULTS, "q2": RESULTS}),
        "read_fn": _read({"https://docs.docker.com/usage/pulls/": "pull limits: 100/6h"}),
        "planner_fn": _plan_next("q1"),
        "selector_fn": _select_all,
        "extract_fn": _extract_relation({}),
    }
    params.update(overrides)
    return run_loop(**params)


def test_search_budget_is_never_exceeded_even_with_new_queries() -> None:
    outcome = _run(planner_fn=_plan_next("q1", "q2", "q3", "q4", "q5", "q6"))
    assert outcome.searches == 4
    assert outcome.stop_reason == "search_budget_exhausted"
    assert outcome.budget_violations == []


def test_read_budget_is_never_exceeded_even_with_greedy_selector() -> None:
    budget = LoopBudget(max_searches=4, max_reads=1, case_timeout_seconds=60.0)
    outcome = _run(budget=budget, planner_fn=_plan_next("q1", "q2"))
    assert outcome.reads == 1
    assert outcome.budget_violations == []


def test_planner_stop_and_repeat_are_honored() -> None:
    stopped = _run(planner_fn=_plan_next())
    assert stopped.searches == 0
    assert stopped.stop_reason == "planner_sufficient"

    repeated = _run(planner_fn=_plan_next("q1", "q1"))
    assert repeated.searches == 1
    assert repeated.stop_reason == "planner_repeated_query"


def test_canonical_url_is_read_once_and_selector_is_bounded() -> None:
    search_fn = _search({"q1": RESULTS, "q2": RESULTS})
    read_fn = _read({"https://docs.docker.com/usage/pulls/": "pull limits: 100/6h"})
    outcome = _run(
        planner_fn=_plan_next("q1", "q2"),
        search_fn=search_fn,
        read_fn=read_fn,
    )
    # Greedy selector opens both candidates once; q2 repeats the same results
    # and must not trigger a second read of the same canonical URL.
    assert read_fn.calls == [
        "https://docs.docker.com/usage/pulls/",
        "https://example.com/other",
    ]
    assert len(outcome.read_urls) == len(set(outcome.read_urls)) == 2


def test_supports_stops_the_loop_early() -> None:
    outcome = _run(
        planner_fn=_plan_next("q1", "q2", "q3"),
        extract_fn=_extract_relation({"https://docs.docker.com/usage/pulls/": "supports"}),
    )
    assert outcome.supports == 1
    assert outcome.stop_reason == "supports_found"
    assert outcome.searches == 1
    assert outcome.to_dict()["binding_rows"] == outcome.supports


def test_unreadable_page_is_recorded_without_extraction() -> None:
    outcome = _run(
        read_fn=_read({}),
        extract_fn=_extract_relation({}),
    )
    assert outcome.extractor_calls == 0
    assert outcome.relations == [] or outcome.relations[0]["relation"] != "supports"
    assert outcome.stop_reason in {"search_budget_exhausted", "loop_end", "planner_sufficient"}


def test_timeout_exits_with_case_timeout() -> None:
    clock = {"now": 0.0}

    def monotonic() -> float:
        clock["now"] += 10.0
        return clock["now"]

    outcome = _run(
        budget=LoopBudget(max_searches=4, max_reads=6, case_timeout_seconds=15.0),
        planner_fn=_plan_next("q1", "q2", "q3"),
        monotonic=monotonic,
    )
    assert outcome.stop_reason == "case_timeout"
    assert outcome.budget_violations == []


def test_same_inputs_produce_identical_outcomes() -> None:
    first = _run(planner_fn=_plan_next("q1", "q2"))
    second = _run(planner_fn=_plan_next("q1", "q2"))
    assert first.to_dict() == second.to_dict()
