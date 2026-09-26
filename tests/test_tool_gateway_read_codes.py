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

    result = gateway.read("https://example.com/item")

    assert result["ok"] is False
    assert result["error"] == reason
    assert result["error_code"] == expected
    assert "private detail" not in result["error_code"]
