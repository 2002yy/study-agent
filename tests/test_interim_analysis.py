"""Provisional synthesis shares the existing revise call and stays source-bound."""

from copy import deepcopy
import json

import pytest

from src.api.routes.chat_routes import _research_progress
from src.web.research.deep_planner import ModelDeepPlanner
from src.web.research.interim_analysis import analysis_sources, interim_revision, validate_interim_analysis
from src.web.research.research_interaction import interaction_event
from test_early_research_findings import research_run
from test_deep_planner_production import ScriptedGateway, _production_service, _result


ANALYSIS = "提高击破特攻能提高超击破伤害。\n\n这份资料不能用于比较两套配置的具体数值。"


def valid_analysis(notes):
    source = analysis_sources(notes)[0]
    return {"text": ANALYSIS, "citations": [{"source_id": source["source_id"], "quote": source["excerpt"][:40]}]}


def test_analysis_preserves_readable_paragraphs_without_changing_quote_binding():
    notes = research_run().research_context["deep"]["notes"]
    validated = validate_interim_analysis(valid_analysis(notes), analysis_sources(notes))
    assert validated["text"] == ANALYSIS


@pytest.mark.parametrize("invalid", ["text-too-long", "no-citations", "unknown-source", "invented-quote", "short-quote", "bad-shape"])
def test_bad_optional_analysis_is_rejected_without_trusting_model_links(invalid):
    notes = research_run().research_context["deep"]["notes"]
    sources = analysis_sources(notes)
    raw = valid_analysis(notes)
    if invalid == "text-too-long":
        raw["text"] = "x" * 401
    elif invalid == "no-citations":
        raw["citations"] = []
    elif invalid == "unknown-source":
        raw["citations"][0]["source_id"] = "invented"
    elif invalid == "invented-quote":
        raw["citations"][0]["quote"] = "An invented quotation absent from the provided page"
    elif invalid == "short-quote":
        raw["citations"][0]["quote"] = "Actual"
    elif invalid == "bad-shape":
        raw["citations"] = {"url": "https://example.org"}
    assert validate_interim_analysis(raw, sources) is None


def test_projection_revalidates_body_revision_and_redirected_source():
    run = research_run()
    deep = run.research_context["deep"]
    deep["interim_analysis"] = {**validate_interim_analysis(valid_analysis(deep["notes"]), analysis_sources(deep["notes"])),
                                "revision": interim_revision(deep)}
    run.selected_sources[0]["read"]["url"] = "https://example.org/canonical"
    before = deepcopy(vars(run))
    projected = interaction_event(run)["interim_analysis"]
    assert projected["status"] == "provisional"
    assert projected["citations"][0]["url"] == "https://example.org/canonical"
    assert vars(run) == before
    deep["steering"] = [{"id": "new-condition", "content": "change scope"}]
    assert interaction_event(run)["interim_analysis"] is None
    deep["steering"] = []
    run.selected_sources[0]["read"]["answer_eligible"] = False
    assert interaction_event(run)["interim_analysis"] is None


def test_invalid_optional_field_does_not_discard_planner_work():
    planner = ModelDeepPlanner(completion=lambda *_: json.dumps({
        "done": False, "additional": ["new query"], "compute": None,
        "interim_analysis": {"text": "unbound", "citations": []},
    }))
    verdict = planner.revise("", [], [])
    assert verdict == {"done": False, "additional": ["new query"], "compute": None}


def test_source_list_is_bounded_deduplicated_and_uses_only_public_notes():
    notes = [{"url": f"https://example.org/{i}", "facts": "source body " * 40} for i in range(8)]
    notes += [dict(notes[-1]), {"url": "http://127.0.0.1/private", "facts": "private data"}]
    sources = analysis_sources(notes)
    assert len(sources) == 4
    assert len({source["source_id"] for source in sources}) == 4
    assert all(len(source["excerpt"]) <= 280 for source in sources)


def test_production_revise_emits_analysis_before_completion_without_an_extra_call(tmp_path, monkeypatch):
    gateway = ScriptedGateway({"testphase": [_result("https://example.org/facts", "testphase facts")]})
    service, database = _production_service(tmp_path, monkeypatch, gateway)
    calls = []

    def completion(instruction, payload):
        calls.append(payload)
        if "sub_questions" in instruction:
            return json.dumps({"sub_questions": ["testphase facts"]})
        source = payload["sources"][0]
        return json.dumps({"done": True, "additional": [], "compute": None,
                           "interim_analysis": {"text": ANALYSIS, "citations": [
                               {"source_id": source["source_id"], "quote": source["excerpt"][:40]},
                           ]}})

    assert isinstance(service.planner, ModelDeepPlanner)
    service.planner._completion = completion
    checkpoints = []
    checkpoint = service.repository.checkpoint

    def capture(*args, **kwargs):
        saved = checkpoint(*args, **kwargs)
        checkpoints.append(_research_progress(saved))
        return saved

    monkeypatch.setattr(service.repository, "checkpoint", capture)
    run = service.create("testphase compare facts", research_mode="deep")
    completed = service.execute(run.id)
    assert len(calls) == 2  # one plan, one revise; analysis uses the latter
    assert len(gateway.search_calls) == len(gateway.read_calls) == 1
    assert any(event["status"] == "running" and event["interim_analysis"] for event in checkpoints)
    assert ANALYSIS not in completed.source_block
    from src.repositories.web_lookup_repository import WebLookupRepository

    restored = WebLookupRepository(database).get(run.id)
    assert _research_progress(restored)["interim_analysis"]["text"] == ANALYSIS
