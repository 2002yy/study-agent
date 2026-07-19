from __future__ import annotations

import hashlib
import json
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Literal, Protocol

from src.llm_client import ModelProfile, get_client, get_model_name, get_provider_settings
from src.rag.answer_eval import (
    RagAnswerAssertion,
    RagAnswerCandidate,
    RagAnswerEvalCase,
    evaluate_answer_suite,
)

ReplayKind = Literal["real_provider", "synthetic_test"]
ReplayRunStatus = Literal[
    "completed",
    "partial_failure",
    "provider_unavailable",
]

_REPLAY_SYSTEM_PROMPT = """You are evaluating source-grounded answers for Study Agent.
Use only the evidence supplied in the user message. Never fill missing facts from memory.
Return one JSON object and no markdown fences:
{
  "refused": true or false,
  "answer": "concise answer or refusal",
  "assertions": [
    {"text": "one factual assertion", "cited_sources": ["exact-source-name.md"]}
  ]
}
Rules:
- If EVIDENCE_STATUS is not `found`, set refused=true and do not make the requested factual claim.
- If EVIDENCE_STATUS is `found`, answer only claims directly supported by EVIDENCE.
- cited_sources must use only exact SOURCE identifiers shown in EVIDENCE.
- Split materially different claims into separate assertions.
- Do not cite a source that does not support the assertion.
"""


@dataclass(frozen=True)
class ProviderUsage:
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None

    def to_dict(self) -> dict[str, int | None]:
        return asdict(self)


@dataclass(frozen=True)
class ProviderCompletion:
    content: str
    provider_profile: str
    model_name: str
    endpoint_fingerprint: str
    response_id: str
    finish_reason: str
    latency_seconds: float
    usage: ProviderUsage

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider_profile": self.provider_profile,
            "model_name": self.model_name,
            "endpoint_fingerprint": self.endpoint_fingerprint,
            "response_id": self.response_id,
            "finish_reason": self.finish_reason,
            "latency_seconds": round(self.latency_seconds, 6),
            "usage": self.usage.to_dict(),
        }


class ReplayProvider(Protocol):
    def complete(self, messages: list[dict[str, str]]) -> ProviderCompletion:
        ...


class OpenAICompatibleReplayProvider:
    """Use Study Agent's existing provider owner for a real answer replay."""

    replay_kind: ReplayKind = "real_provider"

    def __init__(
        self,
        *,
        provider_profile: str | None = None,
        model_profile: ModelProfile = "pro",
        temperature: float = 0.0,
        max_tokens: int = 700,
        timeout: float = 60.0,
    ) -> None:
        settings = get_provider_settings(provider_profile)
        self.provider_profile = settings.profile_name
        self.model_profile = model_profile
        self.model_name = get_model_name(
            model_profile,
            provider_profile=self.provider_profile,
        )
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.timeout = timeout
        self.endpoint_fingerprint = _fingerprint_endpoint(settings.base_url)
        self._client = get_client(provider_profile=self.provider_profile)

    def complete(self, messages: list[dict[str, str]]) -> ProviderCompletion:
        started = time.perf_counter()
        response = self._client.chat.completions.create(
            model=self.model_name,
            messages=messages,
            temperature=self.temperature,
            max_tokens=self.max_tokens,
            timeout=self.timeout,
            stream=False,
            response_format={"type": "json_object"},
        )
        latency = time.perf_counter() - started
        choice = response.choices[0]
        usage = getattr(response, "usage", None)
        return ProviderCompletion(
            content=choice.message.content or "",
            provider_profile=self.provider_profile,
            model_name=self.model_name,
            endpoint_fingerprint=self.endpoint_fingerprint,
            response_id=str(getattr(response, "id", "") or ""),
            finish_reason=str(getattr(choice, "finish_reason", "") or ""),
            latency_seconds=latency,
            usage=ProviderUsage(
                prompt_tokens=_optional_int(getattr(usage, "prompt_tokens", None)),
                completion_tokens=_optional_int(
                    getattr(usage, "completion_tokens", None)
                ),
                total_tokens=_optional_int(getattr(usage, "total_tokens", None)),
            ),
        )


@dataclass(frozen=True)
class ReplayRetrieval:
    status: str
    reason: str
    context: str
    results: tuple[Any, ...]


@dataclass(frozen=True)
class ParsedProviderAnswer:
    candidate: RagAnswerCandidate
    parse_error: str = ""


def build_replay_messages(
    case: RagAnswerEvalCase,
    retrieval: ReplayRetrieval,
) -> list[dict[str, str]]:
    evidence_blocks: list[str] = []
    for result in retrieval.results:
        chunk = result.chunk
        source_name = Path(chunk.source_path).name
        evidence_blocks.append(
            f"SOURCE: {source_name}\n"
            f"TITLE: {chunk.title}\n"
            f"TEXT:\n{chunk.text.strip()}"
        )
    evidence = "\n\n---\n\n".join(evidence_blocks) or "(no eligible evidence)"
    limitation = retrieval.context.strip() if retrieval.status != "found" else ""
    user_content = (
        f"QUESTION:\n{case.query}\n\n"
        f"EVIDENCE_STATUS: {retrieval.status}\n"
        f"EVIDENCE_REASON: {retrieval.reason}\n"
        f"EVIDENCE:\n{evidence}"
    )
    if limitation:
        user_content += f"\n\nEVIDENCE_LIMITATION:\n{limitation}"
    return [
        {"role": "system", "content": _REPLAY_SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]


def parse_provider_answer(case_id: str, raw_text: str) -> ParsedProviderAnswer:
    cleaned = _strip_json_fence(raw_text)
    try:
        payload = json.loads(cleaned)
        if not isinstance(payload, dict):
            raise ValueError("provider answer must be a JSON object")
    except (json.JSONDecodeError, ValueError) as exc:
        stripped = raw_text.strip()
        fallback = RagAnswerCandidate(
            case_id=case_id,
            answer=stripped,
            cited_sources=(),
            refused=False,
            assertions=(
                RagAnswerAssertion(text=stripped, cited_sources=()),
            )
            if stripped
            else (),
        )
        return ParsedProviderAnswer(
            candidate=fallback,
            parse_error=f"{type(exc).__name__}: {exc}",
        )

    refused = bool(payload.get("refused", False))
    answer = str(payload.get("answer", "") or "").strip()
    assertions: list[RagAnswerAssertion] = []
    raw_assertions = payload.get("assertions", [])
    if isinstance(raw_assertions, list):
        for item in raw_assertions:
            if not isinstance(item, dict):
                continue
            text = str(item.get("text", "") or "").strip()
            if not text:
                continue
            raw_sources = item.get("cited_sources", [])
            sources = (
                tuple(str(source) for source in raw_sources if str(source).strip())
                if isinstance(raw_sources, list)
                else ()
            )
            assertions.append(
                RagAnswerAssertion(
                    text=text,
                    cited_sources=sources,
                )
            )
    cited_sources = _unique_sources(
        source
        for assertion in assertions
        for source in assertion.cited_sources
    )
    return ParsedProviderAnswer(
        candidate=RagAnswerCandidate(
            case_id=case_id,
            answer=answer,
            cited_sources=cited_sources,
            refused=refused,
            assertions=tuple(assertions),
        )
    )


def run_provider_answer_replay(
    *,
    cases: tuple[RagAnswerEvalCase, ...],
    retrieve_case: Callable[[RagAnswerEvalCase], ReplayRetrieval],
    provider: ReplayProvider,
    corpus_fingerprint: str,
) -> dict[str, Any]:
    case_rows: list[dict[str, Any]] = []
    candidates: list[RagAnswerCandidate] = []
    failed_cases: list[str] = []
    total_prompt_tokens = 0
    total_completion_tokens = 0
    total_tokens = 0
    usage_complete = True
    total_latency = 0.0

    for case in cases:
        retrieval = retrieve_case(case)
        messages = build_replay_messages(case, retrieval)
        prompt_fingerprint = _fingerprint_messages(messages)
        try:
            completion = provider.complete(messages)
        except Exception as exc:
            failed_cases.append(case.case_id)
            case_rows.append(
                {
                    "case_id": case.case_id,
                    "query": case.query,
                    "status": "provider_failed",
                    "retrieval_status": retrieval.status,
                    "retrieval_reason": retrieval.reason,
                    "prompt_fingerprint": prompt_fingerprint,
                    "error_type": type(exc).__name__,
                }
            )
            continue

        parsed = parse_provider_answer(case.case_id, completion.content)
        candidates.append(parsed.candidate)
        total_latency += completion.latency_seconds
        usage = completion.usage
        if (
            usage.prompt_tokens is None
            or usage.completion_tokens is None
            or usage.total_tokens is None
        ):
            usage_complete = False
        else:
            total_prompt_tokens += usage.prompt_tokens
            total_completion_tokens += usage.completion_tokens
            total_tokens += usage.total_tokens
        case_rows.append(
            {
                "case_id": case.case_id,
                "query": case.query,
                "status": "completed",
                "retrieval_status": retrieval.status,
                "retrieval_reason": retrieval.reason,
                "retrieved_sources": [
                    Path(result.chunk.source_path).name
                    for result in retrieval.results
                ],
                "prompt_fingerprint": prompt_fingerprint,
                "provider": completion.to_dict(),
                "parse_error": parsed.parse_error,
                "candidate": {
                    "answer": parsed.candidate.answer,
                    "refused": parsed.candidate.refused,
                    "cited_sources": list(parsed.candidate.cited_sources),
                    "assertions": [
                        {
                            "text": assertion.text,
                            "cited_sources": list(assertion.cited_sources),
                        }
                        for assertion in parsed.candidate.assertions
                    ],
                },
            }
        )

    status: ReplayRunStatus = (
        "completed" if not failed_cases else "partial_failure"
    )
    answer_quality: dict[str, Any] | None = None
    if not failed_cases and len(candidates) == len(cases):
        answer_quality = evaluate_answer_suite(cases, tuple(candidates)).to_dict()

    provider_rows = [row["provider"] for row in case_rows if "provider" in row]
    return {
        "schema_version": 1,
        "replay_kind": _replay_kind_for_provider(provider),
        "status": status,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "corpus_fingerprint": corpus_fingerprint,
        "prompt_template_fingerprint": hashlib.sha256(
            _REPLAY_SYSTEM_PROMPT.encode("utf-8")
        ).hexdigest(),
        "provider": _provider_identity(provider_rows),
        "cases": len(cases),
        "completed_cases": len(candidates),
        "failed_cases": failed_cases,
        "latency": {
            "total_seconds": round(total_latency, 6),
            "mean_seconds": (
                round(total_latency / len(candidates), 6)
                if candidates
                else 0.0
            ),
        },
        "usage": {
            "complete": usage_complete and bool(candidates),
            "prompt_tokens": total_prompt_tokens if usage_complete else None,
            "completion_tokens": total_completion_tokens if usage_complete else None,
            "total_tokens": total_tokens if usage_complete else None,
        },
        "answer_quality": answer_quality,
        "results": case_rows,
    }


def provider_unavailable_report(
    *,
    corpus_fingerprint: str,
    provider_profile: str,
    reason: str,
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "replay_kind": "real_provider",
        "status": "provider_unavailable",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "corpus_fingerprint": corpus_fingerprint,
        "prompt_template_fingerprint": hashlib.sha256(
            _REPLAY_SYSTEM_PROMPT.encode("utf-8")
        ).hexdigest(),
        "provider": {"provider_profile": provider_profile},
        "reason": reason,
        "cases": 0,
        "completed_cases": 0,
        "failed_cases": [],
        "answer_quality": None,
        "results": [],
    }


def _replay_kind_for_provider(provider: ReplayProvider) -> ReplayKind:
    if isinstance(provider, OpenAICompatibleReplayProvider):
        return "real_provider"
    return "synthetic_test"


def _provider_identity(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        return {}
    first = rows[0]
    return {
        "provider_profile": first.get("provider_profile", ""),
        "model_name": first.get("model_name", ""),
        "endpoint_fingerprint": first.get("endpoint_fingerprint", ""),
    }


def _fingerprint_endpoint(base_url: str) -> str:
    normalized = (base_url or "").strip().rstrip("/")
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]


def _fingerprint_messages(messages: list[dict[str, str]]) -> str:
    payload = json.dumps(
        messages,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _strip_json_fence(text: str) -> str:
    cleaned = (text or "").strip()
    if cleaned.startswith("```") and cleaned.endswith("```"):
        lines = cleaned.splitlines()
        if len(lines) >= 3:
            return "\n".join(lines[1:-1]).strip()
    return cleaned


def _optional_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _unique_sources(values) -> tuple[str, ...]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        source = str(value).strip()
        if not source or source in seen:
            continue
        seen.add(source)
        result.append(source)
    return tuple(result)
