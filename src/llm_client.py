from __future__ import annotations

import os
from typing import Callable, Iterator, Literal

from dotenv import load_dotenv

load_dotenv()

ModelProfile = Literal["flash", "pro"]
_client = None
_client_signature: tuple[str, str] | None = None


def _classify_error(e: Exception) -> str:
    try:
        from openai import (
            APIConnectionError,
            APITimeoutError,
            AuthenticationError,
            InternalServerError,
            NotFoundError,
            PermissionDeniedError,
            RateLimitError,
        )
    except ImportError:
        return f"API call failed: {e}"

    if isinstance(e, AuthenticationError):
        return f"API Key 无效或被拒: {e}"
    if isinstance(e, PermissionDeniedError):
        return f"API 权限不足 (403): {e}"
    if isinstance(e, NotFoundError):
        return f"模型名或端点不存在 (404): {e}"
    if isinstance(e, RateLimitError):
        return f"API 速率限制 (429)，请稍后重试: {e}"
    if isinstance(e, InternalServerError):
        return f"API 服务端错误 (5xx): {e}"
    if isinstance(e, APITimeoutError):
        return f"API 请求超时: {e}"
    if isinstance(e, APIConnectionError):
        return f"网络连接失败，请检查网络和 BASE_URL: {e}"
    return f"API call failed: {e}"


def reset_client() -> None:
    global _client, _client_signature
    _client = None
    _client_signature = None


def get_client():
    global _client, _client_signature

    from openai import OpenAI

    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    base_url = os.getenv("OPENAI_BASE_URL", "").strip()
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is missing.")
    if not base_url:
        raise RuntimeError("OPENAI_BASE_URL is missing.")

    signature = (api_key, base_url)

    if _client is not None and _client_signature == signature:
        return _client

    _client = OpenAI(
        api_key=api_key,
        base_url=base_url,
        timeout=30.0,
        max_retries=2,
    )
    _client_signature = signature
    return _client


def get_model_name(model_profile: ModelProfile | None = None) -> str:
    profile = (model_profile or os.getenv("DEFAULT_MODEL_PROFILE", "flash")).strip().lower()
    if profile == "pro":
        model = os.getenv("MODEL_PRO_NAME", "").strip()
        if not model:
            raise RuntimeError("MODEL_PRO_NAME is missing.")
        return model
    if profile == "flash":
        model = os.getenv("MODEL_FLASH_NAME", "").strip()
        if not model:
            raise RuntimeError("MODEL_FLASH_NAME is missing.")
        return model
    raise RuntimeError(f"Unsupported model profile: {profile}")


def stream_chat(
    messages: list[dict],
    temperature: float = 0.7,
    model_profile: ModelProfile | None = None,
    on_first_token: Callable[[], None] | None = None,
) -> Iterator[str]:
    if not messages:
        return

    client = get_client()
    model = get_model_name(model_profile)
    try:
        response = client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=temperature,
            stream=True,
        )
    except Exception as e:
        raise RuntimeError(_classify_error(e)) from e

    first_token_seen = False
    try:
        for chunk in response:
            delta = chunk.choices[0].delta
            if delta.content:
                if not first_token_seen:
                    first_token_seen = True
                    if on_first_token is not None:
                        on_first_token()
                yield delta.content
    except Exception as e:
        raise RuntimeError(_classify_error(e)) from e


def chat_stream(
    messages: list[dict],
    temperature: float = 0.7,
    model_profile: ModelProfile | None = None,
) -> Iterator[str]:
    yield from stream_chat(messages, temperature=temperature, model_profile=model_profile)


def chat(
    messages: list[dict],
    temperature: float = 0.7,
    model_profile: ModelProfile | None = None,
) -> str:
    if not messages:
        return ""

    client = get_client()
    model = get_model_name(model_profile)
    try:
        response = client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=temperature,
        )
        return response.choices[0].message.content or ""
    except Exception as e:
        raise RuntimeError(_classify_error(e)) from e
