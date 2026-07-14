"""Persistent GitHub-aware extension of the model-directed web tool agent."""

from __future__ import annotations

import json
from typing import Any

from src.llm_client import ModelProfile
from src.tools.web_agent import (
    WEB_TOOLS,
    WebToolAgent,
    WebToolTrace,
    _TOOL_SYSTEM_PROMPT,
    _env_flag,
    _env_int,
)
from src.web.query_normalizer import normalize_web_query

_PR_REVIEW_CONTEXT_TOOL = {
    "type": "function",
    "function": {
        "name": "github_pr_review_context",
        "description": (
            "Build one source-backed PR review evidence pack from immutable base/head, "
            "review threads, changed symbols, affected tests, and failed checks/jobs. "
            "Returns coverage and uncertainty and never an approval or correctness verdict."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "repo_url": {
                    "type": "string",
                    "description": "Public or explicitly approved GitHub repository URL.",
                },
                "number": {
                    "type": "integer",
                    "minimum": 1,
                    "description": "Pull request number.",
                },
                "max_files": {"type": "integer", "minimum": 1, "maximum": 50},
                "max_symbols": {"type": "integer", "minimum": 1, "maximum": 300},
                "max_comments": {"type": "integer", "minimum": 1, "maximum": 100},
                "max_reviews": {"type": "integer", "minimum": 1, "maximum": 100},
                "depth": {"type": "integer", "minimum": 1, "maximum": 4},
                "max_impact_files": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 100,
                },
                "max_edges": {"type": "integer", "minimum": 1, "maximum": 500},
            },
            "required": ["repo_url", "number"],
            "additionalProperties": False,
        },
    },
}


class PersistentWebToolAgent(WebToolAgent):
    """Add the composed PR review-context tool without widening the base gateway."""

    def resolve(
        self,
        user_input: str,
        *,
        model_profile: ModelProfile = "flash",
        conversation_context: str = "",
    ) -> WebToolTrace:
        if not _env_flag("WEB_TOOL_ENABLED", default=True):
            return WebToolTrace(enabled=False)
        query_context = normalize_web_query(user_input)
        system_prompt = (
            f"{_TOOL_SYSTEM_PROMPT}\n"
            "Use github_pr_review_context when the user asks for an integrated PR review, "
            "review risk context, unresolved-review mapping, or CI-to-change evidence. "
            "Prefer it over manually combining github_pr and github_change_impact. "
            "It is an evidence pack, not an approval, rejection, correctness, or bug verdict.\n"
            f"Current UTC date: {query_context.as_of_date}.\n"
            f"Canonical user query: {query_context.canonical_query}.\n"
            f"Candidate search variants: "
            f"{json.dumps(query_context.query_variants, ensure_ascii=False)}."
        )
        messages = [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": (
                    f"Conversation context:\n{conversation_context[-3000:]}\n\n"
                    f"User request:\n{user_input}"
                ),
            },
        ]
        try:
            calls = self.run_loop(
                messages,
                tools=[*WEB_TOOLS, _PR_REVIEW_CONTEXT_TOOL],
                execute_tool=self._execute,
                model_profile=model_profile,
                task_name="web_tool_planner",
                max_rounds=_env_int(
                    "WEB_TOOL_MAX_ROUNDS",
                    5,
                    minimum=1,
                    maximum=8,
                ),
            )
            return WebToolTrace(calls=tuple(calls))
        except Exception as exc:
            return WebToolTrace(error=f"{type(exc).__name__}: {exc}")

    def _execute(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if name != "github_pr_review_context":
            return super()._execute(name, arguments)
        method = self._optional(name)
        if method is None:
            return {"ok": False, "error": "github_pr_review_context_unavailable"}
        return method(
            str(arguments.get("repo_url", "")),
            int(arguments.get("number", 0)),
            max_files=int(arguments.get("max_files", 20)),
            max_symbols=int(arguments.get("max_symbols", 100)),
            max_comments=int(arguments.get("max_comments", 100)),
            max_reviews=int(arguments.get("max_reviews", 100)),
            depth=int(arguments.get("depth", 2)),
            max_impact_files=int(arguments.get("max_impact_files", 40)),
            max_edges=int(arguments.get("max_edges", 160)),
        )
