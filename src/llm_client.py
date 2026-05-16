from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Any, Callable, Iterator, Literal

from dotenv import load_dotenv

load_dotenv()

ModelProfile = Literal["flash", "pro"]
ProviderProfile = Literal["openai", "deepseek", "openrouter", "siliconflow", "local"]
ResponseFormat = Literal["json_object"]

_client = None
_client_signature: tuple[str, str, int] | None = None

_SUPPORTED_PROVIDER_PROFILES = {
    "openai",
    "deepseek",
    "openrouter",
    "siliconflow",
    "local",
}
_PROVIDER_ENV_PREFIX = {
    "openai": "OPENAI",
    "deepseek": "DEEPSEEK",
    "openrouter": "OPENROUTER",
    "siliconflow": "SILICONFLOW",
    "local": "LOCAL",
}
_PROVIDER_BASE_URL_DEFAULTS = {
    "openai": "",
    "deepseek": "https://api.deepseek.com/v1",
    "openrouter": "https://openrouter.ai/api/v1",
    "siliconflow": "https://api.siliconflow.cn/v1",
    "local": "http://127.0.0.1:8000/v1",
}
_TASK_DEFAULTS: dict[str, dict[str, Any]] = {
    "llm_router": {
        "temperature": 0.0,
        "max_tokens": 240,
        "timeout": 20.0,
        "response_format": "json_object",
    },
    "after_session": {
        "temperature": 0.3,
        "max_tokens": 1200,
        "timeout": 45.0,
        "response_format": "json_object",
    },
}


@dataclass(frozen=True)
class ProviderSettings:
    profile_name: str
    api_key: str
    base_url: str
    flash_model: str
    pro_model: str
    default_profile: str
    timeout_seconds: float
    max_retries: int


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


def _normalize_provider_profile(provider_profile: str | None = None) -> str:
    profile = (
        (provider_profile or os.getenv("LLM_PROVIDER_PROFILE", "openai"))
        .strip()
        .lower()
    )
    if profile not in _SUPPORTED_PROVIDER_PROFILES:
        raise RuntimeError(f"Unsupported provider profile: {profile}")
    return profile


def _provider_env_name(profile_name: str, suffix: str) -> str:
    return f"{_PROVIDER_ENV_PREFIX[profile_name]}_{suffix}"


def _first_env(*names: str, default: str = "") -> str:
    for name in names:
        value = os.getenv(name, "").strip()
        if value:
            return value
    return default


def _env_int(*names: str, default: int) -> int:
    value = _first_env(*names)
    if not value:
        return default
    try:
        return int(value)
    except ValueError:
        return default


def _env_float(*names: str, default: float) -> float:
    value = _first_env(*names)
    if not value:
        return default
    try:
        return float(value)
    except ValueError:
        return default


def get_provider_settings(provider_profile: str | None = None) -> ProviderSettings:
    profile_name = _normalize_provider_profile(provider_profile)
    default_base_url = _PROVIDER_BASE_URL_DEFAULTS.get(profile_name, "")

    api_key = _first_env(
        _provider_env_name(profile_name, "API_KEY"),
        "OPENAI_API_KEY",
        default="local" if profile_name == "local" else "",
    )
    base_url = _first_env(
        _provider_env_name(profile_name, "BASE_URL"),
        "OPENAI_BASE_URL",
        default=default_base_url,
    )
    flash_model = _first_env(
        _provider_env_name(profile_name, "MODEL_FLASH_NAME"),
        "MODEL_FLASH_NAME",
    )
    pro_model = _first_env(
        _provider_env_name(profile_name, "MODEL_PRO_NAME"),
        "MODEL_PRO_NAME",
    )
    default_profile = _first_env(
        _provider_env_name(profile_name, "DEFAULT_MODEL_PROFILE"),
        "DEFAULT_MODEL_PROFILE",
        default="flash",
    ).lower()
    timeout_seconds = _env_float(
        _provider_env_name(profile_name, "TIMEOUT_SECONDS"),
        "LLM_TIMEOUT_SECONDS",
        default=30.0,
    )
    max_retries = _env_int(
        _provider_env_name(profile_name, "MAX_RETRIES"),
        "LLM_MAX_RETRIES",
        default=2,
    )

    if not api_key:
        raise RuntimeError(f"{_provider_env_name(profile_name, 'API_KEY')} is missing.")
    if not base_url:
        raise RuntimeError(
            f"{_provider_env_name(profile_name, 'BASE_URL')} is missing."
        )
    if not flash_model:
        raise RuntimeError(
            f"{_provider_env_name(profile_name, 'MODEL_FLASH_NAME')} is missing."
        )
    if not pro_model:
        raise RuntimeError(
            f"{_provider_env_name(profile_name, 'MODEL_PRO_NAME')} is missing."
        )

    return ProviderSettings(
        profile_name=profile_name,
        api_key=api_key,
        base_url=base_url,
        flash_model=flash_model,
        pro_model=pro_model,
        default_profile=default_profile,
        timeout_seconds=timeout_seconds,
        max_retries=max_retries,
    )


def get_client(provider_profile: str | None = None):
    global _client, _client_signature

    from openai import OpenAI

    settings = get_provider_settings(provider_profile)
    signature = (
        settings.api_key,
        settings.base_url,
        settings.max_retries,
    )

    if _client is not None and _client_signature == signature:
        return _client

    _client = OpenAI(
        api_key=settings.api_key,
        base_url=settings.base_url,
        timeout=settings.timeout_seconds,
        max_retries=settings.max_retries,
    )
    _client_signature = signature
    return _client


def get_model_name(
    model_profile: ModelProfile | None = None,
    provider_profile: str | None = None,
) -> str:
    settings = get_provider_settings(provider_profile)
    profile = (model_profile or settings.default_profile).strip().lower()
    if profile == "pro":
        return settings.pro_model
    if profile == "flash":
        return settings.flash_model
    raise RuntimeError(f"Unsupported model profile: {profile}")


def _task_key(task_name: str) -> str:
    return re.sub(r"[^A-Z0-9]+", "_", task_name.strip().upper())


def _task_default(task_name: str | None, field_name: str) -> Any:
    if not task_name:
        return None
    return _TASK_DEFAULTS.get(task_name.strip().lower(), {}).get(field_name)


def _task_env_value(task_name: str | None, suffix: str) -> str:
    if not task_name:
        return ""
    return os.getenv(f"{_task_key(task_name)}_{suffix}", "").strip()


def _resolve_temperature(
    temperature: float | None,
    task_name: str | None,
) -> float:
    if temperature is not None:
        return temperature
    task_value = _task_env_value(task_name, "TEMPERATURE")
    if task_value:
        try:
            return float(task_value)
        except ValueError:
            pass
    task_default = _task_default(task_name, "temperature")
    if task_default is not None:
        return float(task_default)
    return 0.7


def _resolve_max_tokens(
    max_tokens: int | None,
    task_name: str | None,
) -> int | None:
    if max_tokens is not None:
        return max_tokens
    task_value = _task_env_value(task_name, "MAX_TOKENS")
    if task_value:
        try:
            return int(task_value)
        except ValueError:
            pass
    task_default = _task_default(task_name, "max_tokens")
    if task_default is not None:
        return int(task_default)
    global_value = os.getenv("LLM_MAX_TOKENS", "").strip()
    if global_value:
        try:
            return int(global_value)
        except ValueError:
            pass
    return None


def _resolve_timeout(
    timeout: float | None,
    task_name: str | None,
    model_profile: ModelProfile | None,
    provider_profile: str | None,
) -> float:
    if timeout is not None:
        return timeout
    task_value = _task_env_value(task_name, "TIMEOUT_SECONDS")
    if task_value:
        try:
            return float(task_value)
        except ValueError:
            pass
    task_default = _task_default(task_name, "timeout")
    if task_default is not None:
        return float(task_default)

    normalized_model = (model_profile or "").strip().upper()
    if normalized_model:
        model_timeout = os.getenv(f"{normalized_model}_TIMEOUT_SECONDS", "").strip()
        if model_timeout:
            try:
                return float(model_timeout)
            except ValueError:
                pass

    return get_provider_settings(provider_profile).timeout_seconds


def _resolve_response_format(
    response_format: ResponseFormat | None,
    task_name: str | None,
) -> dict[str, str] | None:
    resolved = response_format or _task_default(task_name, "response_format")
    if resolved == "json_object":
        return {"type": "json_object"}
    return None


def _build_request_kwargs(
    *,
    messages: list[dict],
    temperature: float | None,
    model_profile: ModelProfile | None,
    provider_profile: str | None,
    task_name: str | None,
    max_tokens: int | None,
    timeout: float | None,
    response_format: ResponseFormat | None,
    stream: bool,
) -> dict[str, Any]:
    resolved_model_profile = model_profile or None
    kwargs: dict[str, Any] = {
        "model": get_model_name(
            resolved_model_profile,
            provider_profile=provider_profile,
        ),
        "messages": messages,
        "temperature": _resolve_temperature(temperature, task_name),
        "stream": stream,
        "timeout": _resolve_timeout(
            timeout,
            task_name,
            resolved_model_profile,
            provider_profile,
        ),
    }

    resolved_max_tokens = _resolve_max_tokens(max_tokens, task_name)
    if resolved_max_tokens is not None:
        kwargs["max_tokens"] = resolved_max_tokens

    resolved_response_format = _resolve_response_format(response_format, task_name)
    if resolved_response_format is not None:
        kwargs["response_format"] = resolved_response_format

    return kwargs


def stream_chat(
    messages: list[dict],
    temperature: float | None = 0.7,
    model_profile: ModelProfile | None = None,
    on_first_token: Callable[[], None] | None = None,
    max_tokens: int | None = None,
    timeout: float | None = None,
    response_format: ResponseFormat | None = None,
    provider_profile: str | None = None,
    task_name: str | None = None,
) -> Iterator[str]:
    if not messages:
        return

    client = get_client(provider_profile=provider_profile)
    request_kwargs = _build_request_kwargs(
        messages=messages,
        temperature=temperature,
        model_profile=model_profile,
        provider_profile=provider_profile,
        task_name=task_name,
        max_tokens=max_tokens,
        timeout=timeout,
        response_format=response_format,
        stream=True,
    )
    try:
        response = client.chat.completions.create(**request_kwargs)
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


def chat(
    messages: list[dict],
    temperature: float | None = 0.7,
    model_profile: ModelProfile | None = None,
    max_tokens: int | None = None,
    timeout: float | None = None,
    response_format: ResponseFormat | None = None,
    provider_profile: str | None = None,
    task_name: str | None = None,
) -> str:
    if not messages:
        return ""

    client = get_client(provider_profile=provider_profile)
    request_kwargs = _build_request_kwargs(
        messages=messages,
        temperature=temperature,
        model_profile=model_profile,
        provider_profile=provider_profile,
        task_name=task_name,
        max_tokens=max_tokens,
        timeout=timeout,
        response_format=response_format,
        stream=False,
    )
    try:
        response = client.chat.completions.create(**request_kwargs)
        return response.choices[0].message.content or ""
    except Exception as e:
        raise RuntimeError(_classify_error(e)) from e
