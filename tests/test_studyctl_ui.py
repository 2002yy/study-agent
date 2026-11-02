"""`studyctl ui` turns a running instance into one usable URL.

The token never needs to reach the browser by hand: the command rebuilds the
fragment URL from the receipt plus `.env`, and refuses to open a page whose
token the server would reject.
"""

from __future__ import annotations

import pytest

from tools.studyctl import (
    CLIError,
    build_ui_url,
    describe_ui,
    mask_ui_url,
    read_env_value,
)


def test_ui_url_carries_the_token_as_a_fragment():
    url = build_ui_url("http://127.0.0.1:5174", "abc123")

    assert url == "http://127.0.0.1:5174/#token=abc123"


def test_ui_url_escapes_tokens_that_would_break_the_fragment():
    url = build_ui_url("http://127.0.0.1:5174/", "a b&c=d")

    assert url == "http://127.0.0.1:5174/#token=a%20b%26c%3Dd"


def test_ui_url_without_a_token_stays_a_plain_address():
    assert build_ui_url("http://127.0.0.1:5174/", "") == "http://127.0.0.1:5174"


def test_env_reader_takes_one_key_and_normalises_quotes(tmp_path):
    env = tmp_path / ".env"
    env.write_text(
        "# comment\nOTHER=1\nSTUDY_AGENT_API_TOKEN='quoted-secret'\n"
        'DOUBLE="double-secret"\n',
        encoding="utf-8",
    )

    assert read_env_value(env, "STUDY_AGENT_API_TOKEN") == "quoted-secret"
    assert read_env_value(env, "DOUBLE") == "double-secret"
    assert read_env_value(env, "MISSING") == ""
    assert read_env_value(tmp_path / "absent.env", "ANY") == ""


def test_ui_reports_not_running_instead_of_inventing_an_address(tmp_path):
    with pytest.raises(CLIError) as failure:
        describe_ui(tmp_path)

    assert failure.value.kind == "not_running"


def test_ui_never_opens_a_page_the_server_would_reject(tmp_path, monkeypatch):
    (tmp_path / "logs" / "launcher").mkdir(parents=True)
    (tmp_path / "logs" / "launcher" / "receipt.json").write_text(
        '{"backend_url": "http://127.0.0.1:1", "frontend_url": "http://127.0.0.1:2"}',
        encoding="utf-8",
    )
    (tmp_path / ".env").write_text("STUDY_AGENT_API_TOKEN=probe\n", encoding="utf-8")
    monkeypatch.setenv("STUDY_AGENT_API_TOKEN", "probe")
    opened: list[str] = []
    monkeypatch.setattr("tools.studyctl.webbrowser.open", opened.append)

    with pytest.raises(CLIError) as failure:
        describe_ui(tmp_path, open_browser=True)

    assert failure.value.kind == "ui_auth_failed"
    assert opened == []


def test_ui_returns_the_url_with_its_auth_verdict(tmp_path, monkeypatch):
    (tmp_path / "logs" / "launcher").mkdir(parents=True)
    (tmp_path / "logs" / "launcher" / "receipt.json").write_text(
        '{"backend_url": "http://127.0.0.1:1", "frontend_url": "http://127.0.0.1:2"}',
        encoding="utf-8",
    )
    (tmp_path / ".env").write_text("STUDY_AGENT_API_TOKEN=saved\n", encoding="utf-8")
    monkeypatch.delenv("STUDY_AGENT_API_TOKEN", raising=False)

    data = describe_ui(tmp_path)

    assert data["url"].endswith("#token=***")
    assert data["token_masked"] is True
    assert data["token_present"] is True
    # Nothing listens on port 1, so the verdict must say so rather than "ok".
    assert data["auth"].startswith("unreachable") or data["auth"].startswith("http_")
    assert data["hint"]


def test_full_url_requires_the_explicit_show_token_flag(tmp_path, monkeypatch):
    (tmp_path / "logs" / "launcher").mkdir(parents=True)
    (tmp_path / "logs" / "launcher" / "receipt.json").write_text(
        '{"backend_url": "http://127.0.0.1:1", "frontend_url": "http://127.0.0.1:2"}',
        encoding="utf-8",
    )
    (tmp_path / ".env").write_text("STUDY_AGENT_API_TOKEN=saved\n", encoding="utf-8")
    monkeypatch.delenv("STUDY_AGENT_API_TOKEN", raising=False)

    data = describe_ui(tmp_path, show_token=True)

    assert data["url"] == "http://127.0.0.1:2/#token=saved"
    assert data["token_masked"] is False


def test_masking_keeps_everything_but_the_secret():
    assert (
        mask_ui_url("http://127.0.0.1:5174/#token=abc123")
        == "http://127.0.0.1:5174/#token=***"
    )
    assert mask_ui_url("http://127.0.0.1:5174") == "http://127.0.0.1:5174"
