from __future__ import annotations

from typing import Any

from src.tools.web_agent import WEB_TOOLS, WebToolAgent


class FakeGateway:
    def github_structure(
        self,
        repo_url: str,
        symbol: str,
        *,
        ref: str = "",
        max_results: int = 20,
    ) -> dict[str, Any]:
        return {
            "ok": True,
            "repository": "openai/example",
            "ref": ref or "main",
            "symbol": symbol,
            "max_results": max_results,
            "definitions": [{"name": symbol}],
        }


def test_github_structure_tool_schema_is_registered():
    names = [tool["function"]["name"] for tool in WEB_TOOLS]

    assert "github_structure" in names
    tool = next(
        tool for tool in WEB_TOOLS if tool["function"]["name"] == "github_structure"
    )
    assert tool["function"]["parameters"]["required"] == ["repo_url", "symbol"]


def test_web_tool_agent_dispatches_github_structure():
    agent = WebToolAgent(gateway=FakeGateway())  # type: ignore[arg-type]

    result = agent._execute(
        "github_structure",
        {
            "repo_url": "https://github.com/openai/example",
            "symbol": "prepare_chat_turn",
            "ref": "main",
            "max_results": 7,
        },
    )

    assert result["ok"] is True
    assert result["symbol"] == "prepare_chat_turn"
    assert result["max_results"] == 7
    assert result["definitions"][0]["name"] == "prepare_chat_turn"


def test_web_tool_agent_reports_unavailable_structure_gateway():
    agent = WebToolAgent(gateway=object())  # type: ignore[arg-type]

    result = agent._execute(
        "github_structure",
        {"repo_url": "https://github.com/openai/example", "symbol": "Thing"},
    )

    assert result == {"ok": False, "error": "github_structure_unavailable"}
