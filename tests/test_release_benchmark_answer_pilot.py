"""The answer pilot records genuine calls without conferring semantic authority."""

from __future__ import annotations

from dataclasses import replace
from copy import deepcopy
from pathlib import Path
import socket

import pytest

from src.evals.release_benchmark_answer_pilot import (
    build_answer_review_packet,
    generate_frozen_answer,
)
from src.evals.release_benchmark_plan import load_release_benchmark_plan
from src.evals.release_benchmark_registry import load_gold, load_registry

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


def test_review_packet_rechecks_source_prompt_and_answer_before_gold_disclosure():
    plan = load_release_benchmark_plan(FIXTURES / "plan_v1.json")
    registry = load_registry(FIXTURES / "registry_v1.json", ROOT, plan)
    gold = load_gold(FIXTURES / "gold_v1.json", registry)
    selected = [case for case in registry.cases
                if case.mode == "frozen" and case.modality in {"text", "pdf"}]
    rows = [generate_frozen_answer(
        case, ROOT,
        model_call=lambda messages, source=case.sources[0]: (
            '{"claims":[{"text":"Diagnostic claim",'
            f'"source_ids":["{source.source_id}"]}}]}}'
        ),
        provider="test-remote", model="fake", code_sha="a" * 40,
    ) for case in selected]
    bundle = {
        "schema_version": "release-benchmark-answer-pilot-bundle-v1",
        "code_sha": "a" * 40, "plan_digest": registry.plan_digest,
        "registry_digest": registry.digest, "gold_digest": gold.digest,
        "inference_network": "remote_model_api", "release_gate": "NO_GO",
        "cases": rows,
    }
    packet = build_answer_review_packet(bundle, registry, gold, ROOT)
    assert len(packet["cases"]) == 2
    assert packet["cases"][0]["aspect_rubric"]
    assert "aspect_rubric" not in str(rows[0]["messages"])
    assert packet["semantic_assessment"] == "pending_external_adjudication"
    altered = deepcopy(bundle)
    altered["cases"][0]["answer"] += " Extra unsupported sentence."
    with pytest.raises(ValueError, match="altered"):
        build_answer_review_packet(altered, registry, gold, ROOT)
    altered = deepcopy(bundle)
    altered["cases"][1]["source"]["page"] = 1
    with pytest.raises(ValueError, match="citation source"):
        build_answer_review_packet(altered, registry, gold, ROOT)
    altered = deepcopy(bundle)
    altered["cases"][0]["messages"][1]["content"] += " injected"
    with pytest.raises(ValueError, match="prompt or source"):
        build_answer_review_packet(altered, registry, gold, ROOT)
