from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from src.rag import build_rag_index
from src.rag.answer_eval import RagAnswerEvalCase, RagExpectedClaim
from src.rag.provider_replay import (
    OpenAICompatibleReplayProvider,
    ProviderCompletion,
    ProviderUsage,
    ReplayRetrieval,
    build_replay_messages,
    parse_provider_answer,
    run_provider_answer_replay,
)
from src.rag.service import search_documents


class _SyntheticProvider:
    replay_kind = "synthetic_test"

    def complete(self, messages):
        user = messages[-1]["content"]
        if "EVIDENCE_STATUS: found" in user:
            content = json.dumps(
                {
                    "refused": False,
                    "answer": "A Session uses a connection pool and explicit timeout settings still matter.",
                    "assertions": [
                        {
                            "text": "Session uses a connection pool.",
                            "cited_sources": ["requests.md"],
                        },
                        {
                            "text": "Explicit timeout settings still matter.",
                            "cited_sources": ["requests.md"],
                        },
                    ],
                }
            )
        else:
            content = json.dumps(
                {
                    "refused": True,
                    "answer": "The supplied evidence does not support that fact.",
                    "assertions": [],
                }
            )
        return ProviderCompletion(
            content=content,
            provider_profile="synthetic",
            model_name="fixture-model",
            endpoint_fingerprint="fixture-endpoint",
            response_id="fixture-response",
            finish_reason="stop",
            latency_seconds=0.01,
            usage=ProviderUsage(
                prompt_tokens=10,
                completion_tokens=5,
                total_tokens=15,
            ),
        )


def _answerable_case() -> RagAnswerEvalCase:
    return RagAnswerEvalCase(
        case_id="answerable",
        query="How does Session pooling work and what timeout setting matters?",
        answerable=True,
        expected_sources=("requests.md",),
        expected_claims=(
            RagExpectedClaim(
                claim_id="pool",
                match_terms=("Session", "connection pool"),
                support_sources=("requests.md",),
            ),
            RagExpectedClaim(
                claim_id="timeout",
                match_terms=("timeout",),
                support_sources=("requests.md",),
            ),
        ),
    )


def _unanswerable_case() -> RagAnswerEvalCase:
    return RagAnswerEvalCase(
        case_id="unanswerable",
        query="Which exact GPU is required?",
        answerable=False,
        expected_sources=(),
        expected_claims=(),
    )


def test_synthetic_replay_cannot_be_reported_as_real_provider(tmp_path):
    document = tmp_path / "requests.md"
    document.write_text(
        "A Session uses a connection pool. Explicit timeout settings still matter.",
        encoding="utf-8",
    )
    index = build_rag_index([document], max_chars=300, overlap_chars=0)
    found_results = tuple(
        search_documents(index, _answerable_case().query, top_k=2, retrieval_mode="hybrid")
    )

    def retrieve_case(case):
        if case.answerable:
            return ReplayRetrieval(
                status="found",
                reason="fixture",
                context="",
                results=found_results,
            )
        return ReplayRetrieval(
            status="insufficient",
            reason="missing_explicit_anchor_concepts",
            context="The active corpus does not support the requested fact.",
            results=(),
        )

    report = run_provider_answer_replay(
        cases=(_answerable_case(), _unanswerable_case()),
        retrieve_case=retrieve_case,
        provider=_SyntheticProvider(),
        corpus_fingerprint="fixture-corpus",
    )

    assert report["replay_kind"] == "synthetic_test"
    assert report["status"] == "completed"
    assert report["answer_quality"]["answerability_accuracy"] == 1.0
    assert report["answer_quality"]["mean_citation_recall"] == 1.0
    assert report["usage"] == {
        "complete": True,
        "prompt_tokens": 20,
        "completion_tokens": 10,
        "total_tokens": 30,
    }


def test_real_provider_adapter_records_usage_without_persisting_api_key(monkeypatch):
    class _FakeCompletions:
        def create(self, **_kwargs):
            return SimpleNamespace(
                id="response-1",
                choices=[
                    SimpleNamespace(
                        finish_reason="stop",
                        message=SimpleNamespace(
                            content='{"refused":true,"answer":"no evidence","assertions":[]}'
                        ),
                    )
                ],
                usage=SimpleNamespace(
                    prompt_tokens=12,
                    completion_tokens=4,
                    total_tokens=16,
                ),
            )

    fake_client = SimpleNamespace(
        chat=SimpleNamespace(completions=_FakeCompletions())
    )
    monkeypatch.setattr(
        "src.rag.provider_replay.get_provider_settings",
        lambda _profile=None: SimpleNamespace(
            profile_name="deepseek",
            api_key="super-secret-key",
            base_url="https://provider.example/v1",
        ),
    )
    monkeypatch.setattr(
        "src.rag.provider_replay.get_model_name",
        lambda _model_profile, provider_profile=None: "real-model",
    )
    monkeypatch.setattr(
        "src.rag.provider_replay.get_client",
        lambda provider_profile=None: fake_client,
    )

    provider = OpenAICompatibleReplayProvider(provider_profile="deepseek")
    completion = provider.complete(
        [{"role": "user", "content": "Return JSON."}]
    )
    serialized = json.dumps(completion.to_dict())

    assert provider.replay_kind == "real_provider"
    assert completion.provider_profile == "deepseek"
    assert completion.model_name == "real-model"
    assert completion.usage.total_tokens == 16
    assert "super-secret-key" not in serialized
    assert "provider.example" not in serialized


def test_insufficient_replay_prompt_exposes_no_citable_evidence():
    case = _unanswerable_case()
    messages = build_replay_messages(
        case,
        ReplayRetrieval(
            status="insufficient",
            reason="missing_explicit_anchor_concepts",
            context="Do not present a direct answer as grounded in the user's materials.",
            results=(),
        ),
    )

    user_message = messages[-1]["content"]
    assert "EVIDENCE_STATUS: insufficient" in user_message
    assert "(no eligible evidence)" in user_message
    assert "SOURCE:" not in user_message


def test_malformed_provider_json_is_not_silently_treated_as_a_refusal():
    parsed = parse_provider_answer("case-1", "not-json")

    assert parsed.parse_error
    assert parsed.candidate.refused is False
    assert parsed.candidate.answer == "not-json"
