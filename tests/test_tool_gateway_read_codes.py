from __future__ import annotations

import pytest

import src.web.tool_gateway as tool_gateway_module
from src.news.article_fetcher import ArticleReadResult
from src.web.tool_gateway import GeneralWebGateway


class _NonGitHubReader:
    def supports(self, _url: str) -> bool:
        return False


@pytest.mark.parametrize(
    ("reason", "expected"),
    [
        ("unsafe_or_empty_url", "invalid_url"),
        ("unsafe_redirect_target", "blocked"),
        ("non_html_resource", "unsupported"),
        ("empty_cache_entry", "fetch_failed"),
        ("all_backends_failed", "provider_failed"),
        ("exception:TimeoutError:private detail", "provider_failed"),
        ("future_reason", "other"),
    ],
)
def test_general_web_read_exposes_only_bounded_error_code(
    monkeypatch: pytest.MonkeyPatch,
    reason: str,
    expected: str,
) -> None:
    monkeypatch.setattr(
        tool_gateway_module,
        "fetch_article_read_result",
        lambda *_args, **_kwargs: ArticleReadResult(
            ok=False,
            requested_url="https://example.com/item",
            reason=reason,
        ),
    )
    gateway = GeneralWebGateway(
        github_reader=_NonGitHubReader(),  # type: ignore[arg-type]
        github_snapshotter=object(),  # type: ignore[arg-type]
    )

    # mode="http" pins the article-fetcher path. The default "auto" read
    # falls back to the browser and may legitimately succeed on this URL,
    # which is not what this test is about (bounded failure codes).
    result = gateway.read("https://example.com/item", mode="http")

    assert result["ok"] is False
    assert result["error"] == reason
    assert result["error_code"] == expected
    assert "private detail" not in result["error_code"]


def test_a_video_read_gets_a_video_sized_budget(monkeypatch: pytest.MonkeyPatch) -> None:
    """The page budget is 10 s; a video read needs the section plus its fetch."""

    seen: dict[str, float] = {}

    def fake_read_video(
        url: str, max_chars: int, timeout: float, **_kwargs: object
    ) -> dict[str, object]:
        seen["timeout"] = timeout
        return {"ok": True, "kind": "video", "url": url, "content": "transcript"}

    monkeypatch.setattr(tool_gateway_module, "_read_video", fake_read_video)
    gateway = GeneralWebGateway(
        github_reader=_NonGitHubReader(),  # type: ignore[arg-type]
        github_snapshotter=object(),  # type: ignore[arg-type]
    )

    result = gateway.read(
        "https://www.bilibili.com/video/BV1Va4y167wd", mode="video", video_seconds=180
    )

    assert result["ok"] is True
    assert seen["timeout"] >= 180.0


def test_a_video_budget_stays_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, float] = {}

    def fake_read_video(
        url: str, max_chars: int, timeout: float, **_kwargs: object
    ) -> dict[str, object]:
        seen["timeout"] = timeout
        return {"ok": True, "kind": "video", "url": url, "content": "transcript"}

    monkeypatch.setattr(tool_gateway_module, "_read_video", fake_read_video)
    gateway = GeneralWebGateway(
        github_reader=_NonGitHubReader(),  # type: ignore[arg-type]
        github_snapshotter=object(),  # type: ignore[arg-type]
    )

    gateway.read(
        "https://www.bilibili.com/video/BV1Va4y167wd",
        mode="video",
        video_seconds=100_000,
    )

    assert seen["timeout"] <= 660.0
