"""Audited, bounded model boundary for research-only semantic calls.

This module deliberately does not persist anything.  It reuses the existing
OpenAI-compatible provider configuration, disables provider-hidden retries for
research calls, and exposes explicit attempt markers/audits so the runtime
owner can checkpoint before and after every external call.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
import time
from typing import Any, Callable, Generic, Mapping, TypeVar

from src.llm_client import ModelProfile, get_client, get_model_name, get_provider_settings

RESEARCH_MODEL_AUDIT_SCHEMA_VERSION = "research-model-call-audit-v1"
MAX_RESEARCH_MODEL_ATTEMPTS = 2

_JSON_OBJECT_CONTRACT_SUFFIX = (
    "\n\nOutput contract (STRICT, must match exactly):\n"
    "Return ONE JSON object with EXACTLY the keys and shapes defined by this "
    "JSON schema:\n{schema}\n"
    "No prose, no markdown fence, no extra keys."
)


def with_json_object_contract(
    messages: list[dict[str, str]],
    schema: Mapping[str, Any],
) -> list[dict[str, str]]:
    """Carry a JSON-schema contract in the system prompt for ``json_object`` transport.

    Used only when the provider does not support wire-level ``json_schema``
    response_format. The strict Python parser downstream keeps final authority;
    this only restores the schema information the wire format can no longer carry.
    """
    if not isinstance(messages, list) or not messages:
        raise ValueError("json_object contract requires messages")
    first = messages[0]
    if not isinstance(first, Mapping) or first.get("role") != "system":
        raise ValueError("json_object contract requires a leading system message")
    suffix = _JSON_OBJECT_CONTRACT_SUFFIX.format(
        schema=json.dumps(schema, ensure_ascii=False, indent=1)
    )
    contract_messages = list(messages)
    contract_messages[0] = dict(first)
    contract_messages[0]["content"] = str(first.get("content", "")) + suffix
    return contract_messages


def merge_research_extra_body(
    base: Mapping[str, Any] | None,
    override: Mapping[str, Any] | None,
) -> dict[str, Any] | None:
    """Merge provider extra_body settings; ``None`` inputs stay transparent."""
    if not override:
        if isinstance(base, Mapping):
            return dict(base)
        return None
    merged = dict(override)
    if isinstance(base, Mapping):
        merged.update(base)
    return merged

T = TypeVar("T")
StructuredParser = Callable[[Any], T]
AttemptStartedHook = Callable[["ResearchModelAttemptStart"], None]
AttemptFinishedHook = Callable[["ResearchModelCallAudit"], None]


@dataclass(frozen=True)
class ResearchModelAttemptStart:
    call_id: str
    logical_call_id: str
    purpose: str
    provider_profile: str
    model_profile: str
    model_name: str
    attempt: int
    started_at: str
    response_schema_version: str
    input_sha256: str
    input_chars: int
    data_categories: tuple[str, ...] = ()
    data_counts: tuple[tuple[str, int], ...] = ()
    schema_version: str = RESEARCH_MODEL_AUDIT_SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "call_id": self.call_id,
            "logical_call_id": self.logical_call_id,
            "purpose": self.purpose,
            "provider_profile": self.provider_profile,
            "model_profile": self.model_profile,
            "model_name": self.model_name,
            "attempt": self.attempt,
            "started_at": self.started_at,
            "response_schema_version": self.response_schema_version,
            "input_sha256": self.input_sha256,
            "input_chars": self.input_chars,
            "data_categories": list(self.data_categories),
            "data_counts": dict(self.data_counts),
        }

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "ResearchModelAttemptStart":
        data = _strict_mapping(
            raw,
            {
                "schema_version",
                "call_id",
                "logical_call_id",
                "purpose",
                "provider_profile",
                "model_profile",
                "model_name",
                "attempt",
                "started_at",
                "response_schema_version",
                "input_sha256",
                "input_chars",
                "data_categories",
                "data_counts",
            },
            "research model attempt",
        )
        if data.get("schema_version") != RESEARCH_MODEL_AUDIT_SCHEMA_VERSION:
            raise ValueError("unsupported research model audit schema")
        return cls(
            call_id=_required_text(data.get("call_id"), 300, "call_id"),
            logical_call_id=_required_text(
                data.get("logical_call_id"), 300, "logical_call_id"
            ),
            purpose=_required_text(data.get("purpose"), 100, "purpose"),
            provider_profile=_required_text(
                data.get("provider_profile"), 100, "provider_profile"
            ),
            model_profile=_required_text(
                data.get("model_profile"), 50, "model_profile"
            ),
            model_name=_required_text(data.get("model_name"), 200, "model_name"),
            attempt=_bounded_int(data.get("attempt"), 1, MAX_RESEARCH_MODEL_ATTEMPTS, "attempt"),
            started_at=_required_text(data.get("started_at"), 100, "started_at"),
            response_schema_version=_required_text(
                data.get("response_schema_version"), 200, "response_schema_version"
            ),
            input_sha256=_sha256_text_field(data.get("input_sha256")),
            input_chars=_bounded_int(data.get("input_chars"), 0, 10_000_000, "input_chars"),
            data_categories=_text_tuple(data.get("data_categories"), 20, 100),
            data_counts=_counts_tuple(data.get("data_counts"), 30),
        )


@dataclass(frozen=True)
class ResearchModelCallAudit:
    call_id: str
    logical_call_id: str
    purpose: str
    provider_profile: str
    model_profile: str
    model_name: str
    attempt: int
    started_at: str
    completed_at: str
    elapsed_seconds: float
    status: str
    response_schema_version: str
    input_sha256: str
    input_chars: int
    response_sha256: str = ""
    response_chars: int = 0
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None
    finish_reason: str = ""
    error_type: str = ""
    data_categories: tuple[str, ...] = ()
    data_counts: tuple[tuple[str, int], ...] = ()
    schema_version: str = RESEARCH_MODEL_AUDIT_SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "call_id": self.call_id,
            "logical_call_id": self.logical_call_id,
            "purpose": self.purpose,
            "provider_profile": self.provider_profile,
            "model_profile": self.model_profile,
            "model_name": self.model_name,
            "attempt": self.attempt,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "elapsed_seconds": self.elapsed_seconds,
            "status": self.status,
            "response_schema_version": self.response_schema_version,
            "input_sha256": self.input_sha256,
            "input_chars": self.input_chars,
            "response_sha256": self.response_sha256,
            "response_chars": self.response_chars,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "total_tokens": self.total_tokens,
            "finish_reason": self.finish_reason,
            "error_type": self.error_type,
            "data_categories": list(self.data_categories),
            "data_counts": dict(self.data_counts),
        }

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "ResearchModelCallAudit":
        data = _strict_mapping(
            raw,
            {
                "schema_version",
                "call_id",
                "logical_call_id",
                "purpose",
                "provider_profile",
                "model_profile",
                "model_name",
                "attempt",
                "started_at",
                "completed_at",
                "elapsed_seconds",
                "status",
                "response_schema_version",
                "input_sha256",
                "input_chars",
                "response_sha256",
                "response_chars",
                "input_tokens",
                "output_tokens",
                "total_tokens",
                "finish_reason",
                "error_type",
                "data_categories",
                "data_counts",
            },
            "research model audit",
        )
        if data.get("schema_version") != RESEARCH_MODEL_AUDIT_SCHEMA_VERSION:
            raise ValueError("unsupported research model audit schema")
        status = _required_text(data.get("status"), 50, "status")
        if status not in {"completed", "attempt_failed"}:
            raise ValueError("invalid research model audit status")
        return cls(
            call_id=_required_text(data.get("call_id"), 300, "call_id"),
            logical_call_id=_required_text(
                data.get("logical_call_id"), 300, "logical_call_id"
            ),
            purpose=_required_text(data.get("purpose"), 100, "purpose"),
            provider_profile=_required_text(
                data.get("provider_profile"), 100, "provider_profile"
            ),
            model_profile=_required_text(
                data.get("model_profile"), 50, "model_profile"
            ),
            model_name=_required_text(data.get("model_name"), 200, "model_name"),
            attempt=_bounded_int(data.get("attempt"), 1, MAX_RESEARCH_MODEL_ATTEMPTS, "attempt"),
            started_at=_required_text(data.get("started_at"), 100, "started_at"),
            completed_at=_required_text(data.get("completed_at"), 100, "completed_at"),
            elapsed_seconds=_bounded_float(
                data.get("elapsed_seconds"), 0.0, 3600.0, "elapsed_seconds"
            ),
            status=status,
            response_schema_version=_required_text(
                data.get("response_schema_version"), 200, "response_schema_version"
            ),
            input_sha256=_sha256_text_field(data.get("input_sha256")),
            input_chars=_bounded_int(data.get("input_chars"), 0, 10_000_000, "input_chars"),
            response_sha256=_optional_sha256(data.get("response_sha256")),
            response_chars=_bounded_int(
                data.get("response_chars"), 0, 10_000_000, "response_chars"
            ),
            input_tokens=_optional_nonnegative_int(data.get("input_tokens")),
            output_tokens=_optional_nonnegative_int(data.get("output_tokens")),
            total_tokens=_optional_nonnegative_int(data.get("total_tokens")),
            finish_reason=_optional_text(data.get("finish_reason"), 100),
            error_type=_optional_text(data.get("error_type"), 200),
            data_categories=_text_tuple(data.get("data_categories"), 20, 100),
            data_counts=_counts_tuple(data.get("data_counts"), 30),
        )


@dataclass(frozen=True)
class ResearchModelResult(Generic[T]):
    status: str
    value: T | None
    audits: tuple[ResearchModelCallAudit, ...]
    reason: str = ""

    @property
    def completed(self) -> bool:
        return self.status == "completed" and self.value is not None


class ResearchModelGateway:
    """Execute strict JSON semantic calls with explicit bounded attempts."""

    def __init__(
        self,
        *,
        provider_profile: str | None = None,
        model_profile: ModelProfile = "flash",
        model_name: str | None = None,
        client: Any = None,
        timeout_seconds: float | None = None,
        max_attempts: int = MAX_RESEARCH_MODEL_ATTEMPTS,
        now: Callable[[], str] | None = None,
        monotonic: Callable[[], float] | None = None,
    ) -> None:
        self.provider_profile = (
            provider_profile or os.getenv("LLM_PROVIDER_PROFILE") or "openai"
        ).strip().lower()
        self.model_profile = model_profile
        self._model_name = model_name
        self._client = client
        self._timeout_seconds = timeout_seconds
        self.max_attempts = max(1, min(int(max_attempts), MAX_RESEARCH_MODEL_ATTEMPTS))
        self._now = now or _utc_now
        self._monotonic = monotonic or time.monotonic

    def complete_structured(
        self,
        *,
        logical_call_id: str,
        purpose: str,
        messages: list[dict[str, str]],
        audit_payload: Mapping[str, Any],
        response_schema_version: str,
        parse: StructuredParser[T],
        data_categories: tuple[str, ...] = (),
        data_counts: Mapping[str, int] | None = None,
        max_tokens: int = 800,
        temperature: float = 0.0,
        timeout_seconds: float | None = None,
        on_attempt_started: AttemptStartedHook | None = None,
        on_attempt_finished: AttemptFinishedHook | None = None,
        attempt_start: int = 1,
        extra_body: Mapping[str, Any] | None = None,
    ) -> ResearchModelResult[T]:
        call_root = _required_text(logical_call_id, 300, "logical_call_id")
        normalized_purpose = _required_text(purpose, 100, "purpose")
        schema = _required_text(response_schema_version, 200, "response_schema_version")
        if not messages:
            raise ValueError("research model call requires messages")
        if not callable(parse):
            raise TypeError("research model call requires a parser")
        attempt_start = _bounded_int(attempt_start, 1, self.max_attempts, "attempt_start")

        model_name = self._resolved_model_name()
        timeout = self._resolved_timeout()
        if timeout_seconds is not None:
            timeout = min(timeout, max(1.0, min(float(timeout_seconds), 120.0)))
        payload_json = json.dumps(
            dict(audit_payload), ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        input_hash = _sha256_text(payload_json)
        categories = tuple(
            dict.fromkeys(
                _required_text(item, 100, "data category") for item in data_categories
            )
        )
        counts = tuple(
            sorted(
                (
                    _required_text(key, 100, "data count key"),
                    _bounded_int(value, 0, 10_000_000, "data count"),
                )
                for key, value in (data_counts or {}).items()
            )
        )
        audits: list[ResearchModelCallAudit] = []

        for attempt in range(attempt_start, self.max_attempts + 1):
            call_id = f"{call_root}:attempt:{attempt}"
            started_at = self._now()
            marker = ResearchModelAttemptStart(
                call_id=call_id,
                logical_call_id=call_root,
                purpose=normalized_purpose,
                provider_profile=self.provider_profile,
                model_profile=str(self.model_profile),
                model_name=model_name,
                attempt=attempt,
                started_at=started_at,
                response_schema_version=schema,
                input_sha256=input_hash,
                input_chars=len(payload_json),
                data_categories=categories,
                data_counts=counts,
            )
            if on_attempt_started is not None:
                on_attempt_started(marker)

            started = self._monotonic()
            raw = ""
            response_hash = ""
            response_chars = 0
            input_tokens: int | None = None
            output_tokens: int | None = None
            total_tokens: int | None = None
            finish_reason = ""
            error_type = ""
            value: T | None = None
            status = "attempt_failed"
            try:
                request_kwargs: dict[str, Any] = {}
                if extra_body is not None:
                    request_kwargs["extra_body"] = dict(extra_body)
                response = self._request_client().chat.completions.create(
                    model=model_name,
                    messages=messages,
                    temperature=float(temperature),
                    max_tokens=max(1, min(int(max_tokens), 4000)),
                    response_format={"type": "json_object"},
                    timeout=timeout,
                    stream=False,
                    **request_kwargs,
                )
                raw = str(response.choices[0].message.content or "")
                response_hash = _sha256_text(raw)
                response_chars = len(raw)
                finish_reason = _bounded_text(
                    getattr(response.choices[0], "finish_reason", "") or "", 100
                )
                input_tokens, output_tokens, total_tokens = _usage_tokens(
                    getattr(response, "usage", None)
                )
                decoded = json.loads(_strip_json_fence(raw))
                value = parse(decoded)
                status = "completed"
            except Exception as exc:  # provider + schema/parse errors share bounded retry
                error_type = type(exc).__name__

            audit = ResearchModelCallAudit(
                call_id=call_id,
                logical_call_id=call_root,
                purpose=normalized_purpose,
                provider_profile=self.provider_profile,
                model_profile=str(self.model_profile),
                model_name=model_name,
                attempt=attempt,
                started_at=started_at,
                completed_at=self._now(),
                elapsed_seconds=max(0.0, self._monotonic() - started),
                status=status,
                response_schema_version=schema,
                input_sha256=input_hash,
                input_chars=len(payload_json),
                response_sha256=response_hash,
                response_chars=response_chars,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                total_tokens=total_tokens,
                finish_reason=finish_reason,
                error_type=error_type,
                data_categories=categories,
                data_counts=counts,
            )
            if on_attempt_finished is not None:
                on_attempt_finished(audit)
            audits.append(audit)
            if status == "completed" and value is not None:
                return ResearchModelResult(
                    status="completed",
                    value=value,
                    audits=tuple(audits),
                )

        return ResearchModelResult(
            status="unavailable",
            value=None,
            audits=tuple(audits),
            reason="model_call_attempts_exhausted",
        )

    def _request_client(self) -> Any:
        client = self._client or get_client(provider_profile=self.provider_profile)
        with_options = getattr(client, "with_options", None)
        if not callable(with_options):
            raise RuntimeError("research model client cannot disable hidden retries")
        return with_options(max_retries=0)

    def _resolved_model_name(self) -> str:
        if self._model_name:
            return _required_text(self._model_name, 200, "model_name")
        return get_model_name(
            self.model_profile,
            provider_profile=self.provider_profile,
        )

    def _resolved_timeout(self) -> float:
        if self._timeout_seconds is not None:
            return max(1.0, min(float(self._timeout_seconds), 120.0))
        settings = get_provider_settings(self.provider_profile)
        return max(1.0, min(float(settings.timeout_seconds), 120.0))


def _usage_tokens(usage: Any) -> tuple[int | None, int | None, int | None]:
    if usage is None:
        return None, None, None
    prompt = _usage_value(usage, "prompt_tokens")
    completion = _usage_value(usage, "completion_tokens")
    total = _usage_value(usage, "total_tokens")
    return prompt, completion, total


def _usage_value(usage: Any, key: str) -> int | None:
    value = usage.get(key) if isinstance(usage, Mapping) else getattr(usage, key, None)
    return _optional_nonnegative_int(value)


def _strip_json_fence(value: str) -> str:
    text = value.strip()
    if text.startswith("```") and text.endswith("```"):
        lines = text.splitlines()
        if len(lines) >= 3:
            return "\n".join(lines[1:-1]).strip()
    return text


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256_text(value: str) -> str:
    return sha256(value.encode("utf-8")).hexdigest()


def _strict_mapping(
    raw: Mapping[str, Any], allowed: set[str], label: str
) -> dict[str, Any]:
    if not isinstance(raw, Mapping):
        raise TypeError(f"{label} must be an object")
    data = dict(raw)
    extra = set(data) - allowed
    missing = allowed - set(data)
    if extra:
        raise ValueError(f"{label} has unknown fields")
    if missing:
        raise ValueError(f"{label} is missing fields")
    return data


def _required_text(value: Any, limit: int, label: str) -> str:
    text = _bounded_text(value, limit)
    if not text:
        raise ValueError(f"{label} must be non-empty")
    return text


def _optional_text(value: Any, limit: int) -> str:
    return _bounded_text(value, limit) if value is not None else ""


def _bounded_text(value: Any, limit: int) -> str:
    return " ".join(str(value or "").split())[:limit]


def _bounded_int(value: Any, minimum: int, maximum: int, label: str) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{label} must be an integer")
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be an integer") from exc
    if parsed < minimum or parsed > maximum:
        raise ValueError(f"{label} is out of range")
    return parsed


def _bounded_float(value: Any, minimum: float, maximum: float, label: str) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be numeric") from exc
    if parsed != parsed or parsed < minimum or parsed > maximum:
        raise ValueError(f"{label} is out of range")
    return parsed


def _optional_nonnegative_int(value: Any) -> int | None:
    if value is None:
        return None
    return _bounded_int(value, 0, 1_000_000_000, "token count")


def _sha256_text_field(value: Any) -> str:
    text = _required_text(value, 64, "sha256")
    if len(text) != 64 or any(ch not in "0123456789abcdef" for ch in text.lower()):
        raise ValueError("invalid sha256")
    return text.lower()


def _optional_sha256(value: Any) -> str:
    text = _optional_text(value, 64)
    return _sha256_text_field(text) if text else ""


def _text_tuple(value: Any, max_items: int, item_limit: int) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)) or len(value) > max_items:
        raise ValueError("invalid text sequence")
    return tuple(_required_text(item, item_limit, "sequence item") for item in value)


def _counts_tuple(value: Any, max_items: int) -> tuple[tuple[str, int], ...]:
    if not isinstance(value, Mapping) or len(value) > max_items:
        raise ValueError("invalid data counts")
    return tuple(
        sorted(
            (
                _required_text(key, 100, "data count key"),
                _bounded_int(count, 0, 10_000_000, "data count"),
            )
            for key, count in value.items()
        )
    )


__all__ = [
    "MAX_RESEARCH_MODEL_ATTEMPTS",
    "RESEARCH_MODEL_AUDIT_SCHEMA_VERSION",
    "ResearchModelAttemptStart",
    "ResearchModelCallAudit",
    "ResearchModelGateway",
    "ResearchModelResult",
]
