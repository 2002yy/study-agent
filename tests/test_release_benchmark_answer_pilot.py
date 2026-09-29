"""The answer pilot records genuine calls without conferring semantic authority."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import socket

import pytest

from src.evals.release_benchmark_answer_pilot import generate_frozen_answer
from src.evals.release_benchmark_plan import load_release_benchmark_plan
from src.evals.release_benchmark_registry import load_registry

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests/fixtures/release_benchmark"


def _case(modality: str):
    plan = load_release_benchmark_plan(FIXTURES / "plan_v1.json")
    registry = load_registry(FIXTURES / "registry_v1.json", ROOT, plan)
    return next(case for case in registry.cases if case.modality == modality)


@pytest.mark.parametrize("modality", ["text", "pdf"])
def test_answer_pilot_binds_real_read_and_citations_without_labels(modality):
    case = _case(modality)
    source = case.sources[0]
    seen = []

    def model_call(messages):
        # The model call is outside the reader's socket guard. The model sees
        # only the question and source, never the gold answer/rubric.
        socket.socket().connect_ex(("127.0.0.1", 1))
        seen.append(messages)
        return ('{"claims":[{"text":"A source-bound diagnostic claim.",'
                f'"source_ids":["{source.source_id}"]}}]}}')

    result = generate_frozen_answer(
        case, ROOT, model_call=model_call, provider="test-remote", model="fake",
        code_sha="a" * 40,
    )
    assert len(seen) == 1
    assert source.locator in result["answer"]
    assert result["source"]["snapshot_sha256"] == source.sha256
    assert result["source"]["page"] == source.page
    assert result["source"]["region"] == source.region
    assert result["reader_network_guard"] == "python_socket_connect_blocked"
    assert result["inference_network"] == "remote_model_api"
    assert result["semantic_assessment"] == "pending_external_adjudication"
    assert result["release_observation"] is False
    assert result["release_gate"] == "NO_GO"
    assert result["source_context_sha256"]
    if modality == "pdf":
        assert "#page=2" in result["answer"]


@pytest.mark.parametrize("response", [
    'not json',
    '{"claims":[]}',
    '{"claims":[{"text":"claim","source_ids":[] }]}',
    '{"claims":[{"text":"claim","source_ids":["WRONG"]}]}',
    '{"claims":[{"text":"claim","source_ids":["NOAA-SURGE"]}],"score":1}',
])
def test_answer_pilot_rejects_missing_or_forged_citations(response):
    with pytest.raises(ValueError, match="JSON|claim|response"):
        generate_frozen_answer(
            _case("text"), ROOT, model_call=lambda messages: response,
            provider="test-remote", model="fake", code_sha="a" * 40,
        )


def test_answer_pilot_rejects_source_drift_before_model_call():
    case = _case("text")
    drifted = replace(case, sources=(replace(case.sources[0], sha256="0" * 64),))
    calls = []
    with pytest.raises(ValueError, match="digest drift"):
        generate_frozen_answer(
            drifted, ROOT, model_call=lambda messages: calls.append(messages),
            provider="test-remote", model="fake", code_sha="a" * 40,
        )
    assert not calls


def test_answer_pilot_rejects_visual_scope():
    with pytest.raises(ValueError, match="text/PDF"):
        generate_frozen_answer(
            _case("image"), ROOT, model_call=lambda messages: "{}",
            provider="test-remote", model="fake", code_sha="a" * 40,
        )
