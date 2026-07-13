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

    def github_impact(
        self,
        repo_url: str,
        symbol: str,
        *,
        ref: str = "",
        depth: int = 2,
        max_files: int = 30,
        max_edges: int = 120,
    ) -> dict[str, Any]:
        return {
            "ok": True,
            "repository": "openai/example",
            "ref": ref or "main",
            "symbol": symbol,
            "depth": depth,
            "max_files": max_files,
            "max_edges": max_edges,
            "files": [{"path": "src/app.py"}],
            "tests": [{"path": "tests/test_app.py"}],
        }


def test_github_structure_and_impact_tool_schemas_are_registered():
    names = [tool["function"]["name"] for tool in WEB_TOOLS]

    assert "github_structure" in names
    assert "github_impact" in names
    structure = next(
        tool for tool in WEB_TOOLS if tool["function"]["name"] == "github_structure"
    )
    impact = next(
        tool for tool in WEB_TOOLS if tool["function"]["name"] == "github_impact"
    )
    assert structure["function"]["parameters"]["required"] == [
        "repo_url",
        "symbol",
    ]
    assert impact["function"]["parameters"]["required"] == [
        "repo_url",
        "symbol",
    ]


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


def test_web_tool_agent_dispatches_github_impact_with_budgets():
    agent = WebToolAgent(gateway=FakeGateway())  # type: ignore[arg-type]

    result = agent._execute(
        "github_impact",
        {
            "repo_url": "https://github.com/openai/example",
            "symbol": "prepare_chat_turn",
            "ref": "main",
            "depth": 3,
            "max_files": 18,
            "max_edges": 90,
        },
    )

    assert result["ok"] is True
    assert result["depth"] == 3
    assert result["max_files"] == 18
    assert result["max_edges"] == 90
    assert result["tests"][0]["path"] == "tests/test_app.py"


def test_web_tool_agent_reports_unavailable_structure_and_impact_gateways():
    agent = WebToolAgent(gateway=object())  # type: ignore[arg-type]

    structure = agent._execute(
        "github_structure",
        {"repo_url": "https://github.com/openai/example", "symbol": "Thing"},
    )
    impact = agent._execute(
        "github_impact",
        {"repo_url": "https://github.com/openai/example", "symbol": "Thing"},
    )

    assert structure == {"ok": False, "error": "github_structure_unavailable"}
    assert impact == {"ok": False, "error": "github_impact_unavailable"}
