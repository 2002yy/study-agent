"""Owned DeepSeek-only SDK session, explicit configuration and no live default.

The caller supplies DEEPSEEK_* values; no dotenv/global-client access or fallback
to OPENAI_* exists. Creating a session does not submit a model request.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from types import TracebackType
from typing import Any, Awaitable, Callable

from src.application.conversation_answer_generator import BoundedAnswerGenerator
from src.application.conversation_answer_runner import AnswerLimits, ModelAnswerRequest
from src.application.conversation_decision_runner import (
    DecisionAdmission,
    ModelDecisionRequest,
)
from src.application.conversation_deepseek_transport import (
    DeepSeekConversationTransport,
)


@dataclass(frozen=True)
class DeepSeekConversationSettings:
    api_key: str = field(repr=False)
    model: str
    base_url: str = "https://api.deepseek.com/v1"

    def __post_init__(self) -> None:
        if (
            not isinstance(self.api_key, str)
            or not self.api_key.strip()
            or len(self.api_key) > 4096
            or not isinstance(self.model, str)
            or not self.model.strip()
            or len(self.model) > 200
            or not isinstance(self.base_url, str)
            or self.base_url.rstrip("/")
            not in {
                "https://api.deepseek.com",
                "https://api.deepseek.com/v1",
            }
        ):
            raise ValueError("invalid DeepSeek-only configuration")

    @classmethod
    def from_environment(
        cls, values: Mapping[str, str], *, model_profile: str = "flash"
    ) -> DeepSeekConversationSettings:
        if model_profile not in {"flash", "pro"}:
            raise ValueError("invalid DeepSeek model profile")

        def required(name: str) -> str:
            value = values.get(name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"missing {name}")
            return value.strip()

        return cls(
            required("DEEPSEEK_API_KEY"),
            required(f"DEEPSEEK_MODEL_{model_profile.upper()}_NAME"),
            values.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1").strip(),
        )


ModelRequest = ModelDecisionRequest | ModelAnswerRequest


class DeepSeekConversationSession:
    """Single-use owned client; close after the host has stopped its streams.

    No shared global SDK client is modified or closed. Existing runner admission
    and deployment-specific real-spend reservation remain required by the host.
    """

    def __init__(
        self,
        settings: DeepSeekConversationSettings,
        *,
        client_factory: Callable[..., Any] | None = None,
    ) -> None:
        if not isinstance(settings, DeepSeekConversationSettings):
            raise ValueError("invalid DeepSeek settings")
        self._settings = settings
        self._factory = client_factory
        self._client: Any = None
        self._http_client: Any = None
        self._transport: DeepSeekConversationTransport | None = None
        self._started = self._closed = False

    async def __aenter__(self) -> DeepSeekConversationSession:
        if self._started or self._closed:
            raise RuntimeError("DeepSeek session already consumed")
        self._started = True
        factory = self._factory
        if factory is None:
            import httpx
            from openai import AsyncOpenAI

            factory = AsyncOpenAI
            self._http_client = httpx.AsyncClient(
                follow_redirects=False, trust_env=False
            )
        try:
            options: dict[str, Any] = {}
            if self._http_client is not None:
                options["http_client"] = self._http_client
            self._client = factory(
                api_key=self._settings.api_key,
                base_url=self._settings.base_url,
                max_retries=0,
                timeout=30.0,
                organization="",
                project="",
                webhook_secret="",
                **options,
            )
            self._transport = DeepSeekConversationTransport(
                self._client, self._settings.model
            )
        except BaseException:
            await self.aclose()
            raise
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        if self._closed:
            return
        self._closed = True
        client, self._client = self._client, None
        http_client, self._http_client = self._http_client, None
        self._transport = None
        try:
            if client is not None:
                await client.close()
        finally:
            if http_client is not None and not http_client.is_closed:
                await http_client.aclose()

    async def _invoke(self, request: ModelRequest) -> str:
        transport = self._transport
        if self._closed or transport is None:
            raise RuntimeError("DeepSeek session is not open")
        return await transport(request)

    @property
    def transport(self) -> Callable[[ModelRequest], Awaitable[str]]:
        if self._closed or self._transport is None:
            raise RuntimeError("DeepSeek session is not open")
        return self._invoke

    def answer_generator(
        self, budget: DecisionAdmission, limits: AnswerLimits = AnswerLimits()
    ) -> BoundedAnswerGenerator:
        return BoundedAnswerGenerator(self.transport, budget, limits)
