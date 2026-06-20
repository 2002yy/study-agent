import asyncio
from types import SimpleNamespace

from src import llm_client


def test_get_provider_settings_uses_profile_specific_env(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER_PROFILE", "deepseek")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "deepseek-key")
    monkeypatch.setenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1")
    monkeypatch.setenv("DEEPSEEK_MODEL_FLASH_NAME", "deepseek-chat")
    monkeypatch.setenv("DEEPSEEK_MODEL_PRO_NAME", "deepseek-reasoner")
    monkeypatch.setenv("DEEPSEEK_DEFAULT_MODEL_PROFILE", "pro")
    monkeypatch.setenv("DEEPSEEK_TIMEOUT_SECONDS", "45")
    monkeypatch.setenv("DEEPSEEK_MAX_RETRIES", "3")

    settings = llm_client.get_provider_settings()

    assert settings.profile_name == "deepseek"
    assert settings.api_key == "deepseek-key"
    assert settings.base_url == "https://api.deepseek.com/v1"
    assert settings.flash_model == "deepseek-chat"
    assert settings.pro_model == "deepseek-reasoner"
    assert settings.default_profile == "pro"
    assert settings.timeout_seconds == 45.0
    assert settings.max_retries == 3


def test_chat_passes_extended_request_options(monkeypatch):
    captured = {}

    class _FakeCompletions:
        def create(self, **kwargs):
            captured.update(kwargs)
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content="ok"))]
            )

    fake_client = SimpleNamespace(
        chat=SimpleNamespace(completions=_FakeCompletions())
    )

    monkeypatch.setattr(llm_client, "get_client", lambda provider_profile=None: fake_client)
    monkeypatch.setattr(
        llm_client,
        "get_model_name",
        lambda model_profile=None, provider_profile=None: "fake-model",
    )

    result = llm_client.chat(
        [{"role": "user", "content": "hi"}],
        temperature=0.2,
        model_profile="pro",
        max_tokens=321,
        timeout=12.5,
        response_format="json_object",
        provider_profile="openrouter",
        task_name="after_session",
    )

    assert result == "ok"
    assert captured["model"] == "fake-model"
    assert captured["temperature"] == 0.2
    assert captured["max_tokens"] == 321
    assert captured["timeout"] == 12.5
    assert captured["response_format"] == {"type": "json_object"}
    assert captured["stream"] is False


def test_stream_chat_uses_task_defaults(monkeypatch):
    captured = {}
    state = {"closed": False}

    class _FakeResponse:
        def __iter__(self):
            yield SimpleNamespace(
                choices=[SimpleNamespace(delta=SimpleNamespace(content="A"))]
            )
            yield SimpleNamespace(
                choices=[SimpleNamespace(delta=SimpleNamespace(content="B"))]
            )

        def close(self):
            state["closed"] = True

    class _FakeCompletions:
        def create(self, **kwargs):
            captured.update(kwargs)
            return _FakeResponse()

    fake_client = SimpleNamespace(
        chat=SimpleNamespace(completions=_FakeCompletions())
    )

    monkeypatch.setattr(llm_client, "get_client", lambda provider_profile=None: fake_client)
    monkeypatch.setattr(
        llm_client,
        "get_model_name",
        lambda model_profile=None, provider_profile=None: "fake-model",
    )

    chunks = list(
        llm_client.stream_chat(
            [{"role": "user", "content": "hi"}],
            temperature=None,
            model_profile="flash",
            task_name="llm_router",
        )
    )

    assert "".join(chunks) == "AB"
    assert captured["temperature"] == 0.0
    assert captured["max_tokens"] == 240
    assert captured["timeout"] == 20.0
    assert captured["response_format"] == {"type": "json_object"}
    assert captured["stream"] is True
    assert state["closed"] is True


def test_stream_chat_can_cancel_and_closes_response(monkeypatch):
    state = {"closed": False, "checks": 0}

    class _FakeResponse:
        def __iter__(self):
            yield SimpleNamespace(
                choices=[SimpleNamespace(delta=SimpleNamespace(content="A"))]
            )
            yield SimpleNamespace(
                choices=[SimpleNamespace(delta=SimpleNamespace(content="B"))]
            )

        def close(self):
            state["closed"] = True

    class _FakeCompletions:
        def create(self, **kwargs):
            return _FakeResponse()

    fake_client = SimpleNamespace(
        chat=SimpleNamespace(completions=_FakeCompletions())
    )

    monkeypatch.setattr(llm_client, "get_client", lambda provider_profile=None: fake_client)
    monkeypatch.setattr(
        llm_client,
        "get_model_name",
        lambda model_profile=None, provider_profile=None: "fake-model",
    )

    def should_cancel():
        state["checks"] += 1
        return state["checks"] > 1

    chunks = list(
        llm_client.stream_chat(
            [{"role": "user", "content": "hi"}],
            should_cancel=should_cancel,
            timeout=10.0,
        )
    )

    assert chunks == ["A"]
    assert state["closed"] is True


def test_async_stream_chat_uses_async_provider_and_closes_response(monkeypatch):
    captured = {}
    state = {"closed": False}

    class _FakeResponse:
        async def __aiter__(self):
            yield SimpleNamespace(
                choices=[SimpleNamespace(delta=SimpleNamespace(content="A"))]
            )
            yield SimpleNamespace(
                choices=[SimpleNamespace(delta=SimpleNamespace(content="B"))]
            )

        async def close(self):
            state["closed"] = True

    class _FakeCompletions:
        async def create(self, **kwargs):
            captured.update(kwargs)
            return _FakeResponse()

    fake_client = SimpleNamespace(
        chat=SimpleNamespace(completions=_FakeCompletions())
    )

    monkeypatch.setattr(
        llm_client,
        "get_async_client",
        lambda provider_profile=None: fake_client,
    )
    monkeypatch.setattr(
        llm_client,
        "get_model_name",
        lambda model_profile=None, provider_profile=None: "fake-model",
    )

    async def consume():
        return [
            chunk
            async for chunk in llm_client.async_stream_chat(
                [{"role": "user", "content": "hi"}],
                temperature=None,
                model_profile="flash",
                task_name="llm_router",
            )
        ]

    chunks = asyncio.run(consume())

    assert chunks == ["A", "B"]
    assert captured["stream"] is True
    assert captured["timeout"] == 20.0
    assert state["closed"] is True
