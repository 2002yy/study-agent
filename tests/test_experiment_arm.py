from __future__ import annotations

import pytest

import src.web.tool_gateway as gateway_module
from src.news.article_fetcher import ArticleReadResult
from src.tools import web_agent
from src.web import experiment_arm
from src.web.tool_gateway import GeneralWebGateway

URL = "https://example.com/item"


class _NoGitHub:
    def supports(self, _url: str) -> bool:
        return False


def _gateway() -> GeneralWebGateway:
    return GeneralWebGateway(
        github_reader=_NoGitHub(),  # type: ignore[arg-type]
        github_snapshotter=object(),  # type: ignore[arg-type]
    )


def _web_read_tool(tools: list[dict]) -> dict:
    return next(
        tool for tool in tools if tool.get("function", {}).get("name") == "web_read"
    )


def test_unset_arm_is_production(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(experiment_arm.ARM_ENV, raising=False)

    assert experiment_arm.experiment_arm() == ""
    assert web_agent.web_tools_for_arm() is web_agent.WEB_TOOLS
    for feature in ("platform", "discussion", "comments", "video"):
        assert experiment_arm.feature_allowed(feature) is True


def test_arm_a_advertises_only_page_reads(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(experiment_arm.ARM_ENV, "a")

    read = _web_read_tool(web_agent.web_tools_for_arm())
    properties = read["function"]["parameters"]["properties"]

    assert properties["mode"]["enum"] == ["auto", "http", "browse"]
    for key in (
        "start_seconds",
        "video_seconds",
        "include_ocr",
        "include_discussion",
        "max_comments",
        "comment_page",
    ):
        assert key not in properties
    assert "video" not in read["function"]["description"]
    assert "comments" not in read["function"]["description"]


def test_arm_b_advertises_comments_but_not_video(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(experiment_arm.ARM_ENV, "b")

    read = _web_read_tool(web_agent.web_tools_for_arm())
    properties = read["function"]["parameters"]["properties"]

    assert properties["mode"]["enum"] == ["auto", "http", "browse", "comments"]
    assert "include_discussion" in properties
    assert "video_seconds" not in properties
    assert "video" not in read["function"]["description"]


def test_arm_c_keeps_every_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(experiment_arm.ARM_ENV, "c")

    read = _web_read_tool(web_agent.web_tools_for_arm())
    properties = read["function"]["parameters"]["properties"]

    assert properties["mode"]["enum"] == ["auto", "http", "browse", "video", "comments"]
    assert read["function"]["description"] == web_agent._WEB_READ_DESCRIPTION


def test_arm_a_gateway_rejects_the_new_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(experiment_arm.ARM_ENV, "a")
    gateway = _gateway()

    for kwargs in (
        {"mode": "video"},
        {"mode": "comments"},
        {"include_discussion": True},
    ):
        result = gateway.read(URL, **kwargs)
        assert result["ok"] is False
        assert result["error_code"] == "arm_disabled"


def test_arm_a_does_not_reach_the_platform_api(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(experiment_arm.ARM_ENV, "a")

    def forbidden(*_args: object, **_kwargs: object) -> dict:
        raise AssertionError("platform reader must not run in arm A")

    monkeypatch.setattr("src.web.platform_readers.read", forbidden)
    monkeypatch.setattr(
        gateway_module,
        "fetch_article_read_result",
        lambda *_args, **_kwargs: ArticleReadResult(
            ok=False, requested_url=URL, reason="empty_cache_entry"
        ),
    )

    result = _gateway().read(URL, mode="http")

    assert result["ok"] is False
    assert result["error_code"] == "fetch_failed"


def test_arm_b_allows_comments_and_rejects_video(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(experiment_arm.ARM_ENV, "b")
    monkeypatch.setattr(
        gateway_module,
        "_read_comments",
        lambda url, page, limit, timeout: {"ok": True, "url": url, "comments": 1},
    )

    comments = _gateway().read(URL, mode="comments")
    video = _gateway().read(URL, mode="video")

    assert comments["ok"] is True
    assert video["error_code"] == "arm_disabled"


def test_arm_c_allows_video(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(experiment_arm.ARM_ENV, "c")
    monkeypatch.setattr(
        gateway_module,
        "_read_video",
        lambda url, max_chars, timeout, **_kwargs: {
            "ok": True,
            "url": url,
            "content": "transcript",
        },
    )

    result = _gateway().read(URL, mode="video")

    assert result["ok"] is True


def test_an_unknown_arm_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(experiment_arm.ARM_ENV, "z")

    assert experiment_arm.experiment_arm() == experiment_arm.INVALID_ARM
    assert experiment_arm.feature_allowed("platform") is False
    assert _gateway().read(URL, mode="video")["error_code"] == "arm_disabled"
