import pytest
import inspect
from src.llm_client import stream_chat, chat


def test_stream_chat_uses_stream_true():
    src = inspect.getsource(stream_chat)
    assert "stream=True" in src
    assert "yield" in src


def test_chat_still_non_streaming():
    src = inspect.getsource(chat)
    assert "stream=True" not in src
