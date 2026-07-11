"""Model-directed web-search and page-reading tool loop."""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from typing import Any, Callable

from src.llm_client import ModelProfile, run_tool_loop
from src.web.tool_gateway import GeneralWebGateway


WEB_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": "Search the public web for current or external information. Returns titles, URLs and snippets.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Focused web search query."},
                    "max_results": {"type": "integer", "minimum": 1, "maximum": 8},
                },
                "required": ["query"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "web_read",
            "description": "Read a public HTTP(S) web page selected from search results. Never use for private, local, or credentialed URLs.",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "Public HTTP(S) URL to read."},
                    "max_chars": {"type": "integer", "minimum": 500, "maximum": 12000},
                },
                "required": ["url"],
                "additionalProperties": False,
            },
        },
    },
]

_TOOL_SYSTEM_PROMPT = """You are the web-research planner for a chat response.
Use tools only when the user needs current, niche, externally verifiable, or explicitly requested web information. Do not search for casual conversation, writing, or stable knowledge. Search first, then read only the most relevant public result when needed. Never use tools for private/local URLs. If no tool is needed, reply exactly NO_TOOL_NEEDED. After receiving tool results, call further tools only if needed; otherwise reply exactly TOOL_RESEARCH_COMPLETE."""


def _env_flag(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class WebToolTrace:
    calls: tuple[dict[str, Any], ...] = ()
    error: str = ""
    enabled: bool = True

    @property
    def used(self) -> bool:
        return bool(self.calls)

    def context_block(self) -> str:
        if not self.calls:
            return ""
        blocks = ["【模型联网工具结果】"]
        for call in self.calls:
            name = str(call.get("name", "web_tool"))
            result = call.get("result", {})
            blocks.append(f"工具 {name}：\n{json.dumps(result, ensure_ascii=False)}")
        return "\n\n".join(blocks)

    def to_dict(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "used": self.used,
            "calls": list(self.calls),
            "error": self.error,
        }


class WebToolAgent:
    def __init__(
        self,
        gateway: GeneralWebGateway | None = None,
        run_loop: Callable[..., list[dict[str, Any]]] = run_tool_loop,
    ) -> None:
        self.gateway = gateway or GeneralWebGateway()
        self.run_loop = run_loop

    def resolve(
        self,
        user_input: str,
        *,
        model_profile: ModelProfile = "flash",
        conversation_context: str = "",
    ) -> WebToolTrace:
        if not _env_flag("WEB_TOOL_ENABLED", default=True):
            return WebToolTrace(enabled=False)
        messages = [
            {"role": "system", "content": _TOOL_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": f"Conversation context:\n{conversation_context[-3000:]}\n\nUser request:\n{user_input}",
            },
        ]
        try:
            calls = self.run_loop(
                messages,
                tools=WEB_TOOLS,
                execute_tool=self._execute,
                model_profile=model_profile,
                task_name="web_tool_planner",
                max_rounds=3,
            )
            return WebToolTrace(calls=tuple(calls))
        except Exception as exc:
            # Tool support differs by provider. A failed planning pass must never
            # make the normal chat turn unavailable.
            return WebToolTrace(error=f"{type(exc).__name__}: {exc}")

    def _execute(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if name == "web_search":
            query = str(arguments.get("query", ""))
            max_results = int(arguments.get("max_results", 5))
            return {"results": self.gateway.search(query, max_results=max_results)}
        if name == "web_read":
            return self.gateway.read(
                str(arguments.get("url", "")),
                max_chars=int(arguments.get("max_chars", 6000)),
            )
        return {"error": f"unknown_tool:{name}"}


_default_agent = WebToolAgent()


def resolve_web_tools(
    user_input: str,
    *,
    model_profile: ModelProfile = "flash",
    conversation_context: str = "",
) -> WebToolTrace:
    return _default_agent.resolve(
        user_input,
        model_profile=model_profile,
        conversation_context=conversation_context,
    )


def web_tools_disabled(*_args: Any, **_kwargs: Any) -> WebToolTrace:
    """Safe default for isolated service construction and unit tests."""
    return WebToolTrace(enabled=False)
