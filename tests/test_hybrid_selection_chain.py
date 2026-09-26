"""§38b hybrid selection chain: layered acceptance, fallback and invariants."""

from __future__ import annotations

from tools.run_hybrid_selection_chain import run_chain

TARGET = "https://nodejs.cn/api/modules.html"

POOL = [
    {"url": "https://nodejs.org/", "title": "Node.js", "snippet": ""},
    {"url": TARGET, "title": "Modules", "snippet": ""},
]


def _selector(picks_by_call: list[list[str]]):
    calls = {"index": 0}

    def selector(question: str, pool: list[dict], max_picks: int) -> list[str]:
        del question, pool, max_picks
        index = min(calls["index"], len(picks_by_call) - 1)
        calls["index"] += 1
        outcome = list(picks_by_call[index])
        selector.last_call = {
            "status": "completed",
            "reason": "",
            "output_count": len(outcome),
            "empty_output": not outcome,
        }
        return outcome

    return selector


def _reader(pages: dict[str, str]):
    def reader(url: str, max_chars: int) -> dict:
        content = pages.get(url)
        if content is None:
            return {"ok": False, "error": "not_found"}
        return {"ok": True, "content": content[:max_chars]}

    return reader


def _extractor(relations: dict[str, str]):
    def extractor(question: str, entry: dict, content: str) -> dict:
        del question, content
        return {"relation": relations.get(entry["url"], "lead"), "caveat": "caveat"}

    return extractor


def _run(**overrides):
    params = {
        "case_id": "case-x",
        "question": "Which module systems?",
        "pool": POOL,
        "targets": [TARGET],
        "rule_picks": ["https://nodejs.org/"],
        "selector": _selector([[TARGET]]),
        "reader": _reader({TARGET: "CommonJS modules and ECMAScript modules are supported"}),
        "extractor": _extractor({TARGET: "supports"}),
        "max_attempts": 3,
    }
    params.update(overrides)
    return run_chain(**params)


def test_full_chain_reaches_supports_and_keeps_invariants() -> None:
    chain = _run()
    payload = chain.to_dict()
    assert payload["selection_authority"] == "model"
    assert payload["selector_input_candidate_set"] == [entry["url"] for entry in POOL]
    assert payload["selector_output_urls"] == [TARGET]
    assert payload["target_selected"] is True
    assert payload["target_read"] is True
    assert payload["target_fact_relation"] == "supports"
    assert payload["target_fact_present"] is True
    assert payload["supports"] == 1


def test_empty_model_decision_falls_back_to_rule_picks() -> None:
    chain = _run(
        selector=_selector([[]]),
        reader=_reader({"https://nodejs.org/": "homepage text"}),
        extractor=_extractor({}),
    )
    payload = chain.to_dict()
    assert payload["selection_authority"] == "rule_fallback"
    assert payload["picks"] == ["https://nodejs.org/"]
    assert payload["target_selected"] is False
    assert payload["supports"] == 0
    assert payload["selector_attempts"][0]["empty_output"] is True


def test_retry_until_usable_then_model_wins() -> None:
    chain = _run(selector=_selector([[], [], [TARGET]]))
    payload = chain.to_dict()
    assert payload["selection_authority"] == "model"
    assert len(payload["selector_attempts"]) == 3
    assert payload["target_selected"] is True


def test_selector_exception_is_recorded_not_fatal() -> None:
    def exploding(question: str, pool: list[dict], max_picks: int) -> list[str]:
        del question, pool, max_picks
        raise RuntimeError("boom")

    chain = _run(selector=exploding)
    payload = chain.to_dict()
    assert payload["selection_authority"] == "rule_fallback"
    assert payload["selector_attempts"][0]["status"] == "exception"


def test_unreadable_target_records_unreadable_and_no_fact() -> None:
    chain = _run(reader=_reader({}))
    payload = chain.to_dict()
    assert payload["target_selected"] is True
    assert payload["target_read"] is False
    assert payload["target_fact_relation"] == ""
    assert payload["supports"] == 0
    assert payload["extractions"][0]["relation"] == "unreadable"


def test_lead_relation_marks_fact_absent() -> None:
    chain = _run(extractor=_extractor({TARGET: "lead"}))
    payload = chain.to_dict()
    assert payload["target_fact_present"] is False
    assert payload["target_fact_relation"] == "lead"
