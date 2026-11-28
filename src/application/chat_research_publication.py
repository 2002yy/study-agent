"""Read-backed inline research publication policy for chat turns.

No network effects: this module builds bounded evidence rows and generation
admission policy; the durable turn lifecycle remains in chat_service.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from src.application.chat_service import PreparedChatTurn


# Gate=BLOCK is known *before* generation (no eligible evidence rows, or no
# attempt budget). Generation still runs because its output is now delivered as
# a labelled draft instead of being discarded. Measured: the default answer call
# spends 1330-2083 hidden reasoning tokens (16-41s), so the blocked branch runs
# with thinking disabled. PARTIAL/PASS keep the production default.
THINKING_DISABLED_EXTRA_BODY: dict[str, dict[str, str]] = {
    "thinking": {"type": "disabled"}
}


def _answer_attempt_budget(prepared: Any) -> int:
    """Allowed answer-generation attempts for this turn (shared gate input)."""

    plan = prepared.answer_validation or {}
    raw_allowed = plan.get("allowed_attempts")
    try:
        allowed = 0 if raw_allowed == 0 else max(1, min(int(raw_allowed or 1), 2))
    except (TypeError, ValueError):
        allowed = 1
    semantic = ((getattr(prepared, "rag", {}) or {}).get("web_tools") or {}).get("semantics")
    if isinstance(semantic, dict):
        remaining = (
            6
            - int(semantic.get("model_calls", 0))
            - _route_generation_calls(prepared.route)
        )
        allowed = min(allowed, max(0, remaining))
    return allowed


def _evidence_rows_present(prepared: Any) -> bool:
    """Whether the turn carries any eligible evidence row (shared gate input)."""

    plan = prepared.answer_validation or {}
    raw_rows = plan.get("evidence_rows") or ()
    return any(isinstance(row, dict) for row in raw_rows)


def _answer_generation_extra_body(prepared: Any) -> dict[str, dict[str, str]] | None:
    """Return the per-turn generation policy.

    ``BLOCK`` (no evidence rows / no attempt budget) disables hidden reasoning;
    any other gate outcome keeps the production default. This is derived from the
    same two inputs the release gate uses, so the policy cannot drift away from
    the gate decision.

    ``RESEARCH_ANSWER_BOUNDED_POLICY=on`` is a diagnostic override (§40c): the
    gate-pass path also runs the bounded thinking-off policy, because the
    captured gate-pass answer calls returned empty content with thinking on
    (reasoning consumed the output budget). Default off: production unchanged.
    """

    if _answer_attempt_budget(prepared) < 1 or not _evidence_rows_present(prepared):
        return THINKING_DISABLED_EXTRA_BODY
    if _answer_bounded_policy_enabled():
        return THINKING_DISABLED_EXTRA_BODY
    return None


def _answer_bounded_policy_enabled() -> bool:
    """§40c diagnostic switch; unset/unknown keeps the production policy."""

    import os

    raw = (os.getenv("RESEARCH_ANSWER_BOUNDED_POLICY") or "").strip().lower()
    return raw in {"1", "true", "on", "yes"}


def _strict_research_publication_enabled() -> bool:
    """Keep the costly, claim-by-claim binder opt-in for audited workflows.

    Ordinary research publishes the generated answer after deterministic source
    checks. A read URL is provenance, *not* proof of every assertion in it.
    """

    import os

    return (os.getenv("RESEARCH_PUBLICATION_MODE") or "simple").strip().lower() == "strict"


def _configured_llm_provider() -> str:
    import os

    return os.getenv("LLM_PROVIDER_PROFILE", "openai").strip().lower() or "openai"


def answer_validation_active(prepared: PreparedChatTurn) -> bool:
    """True when the publication gate actually runs for this turn."""
    policy = prepared.route.get("external_data_policy")
    if isinstance(policy, dict) and policy.get("web_allowed") is False:
        return False
    return prepared.answer_validation is not None or _official_publication_required(prepared)


def _official_plan_for(user_input: str) -> Any | None:
    """The known-source plan for this question, if the reader owns it."""

    from src.web.research.official_resolver import official_plan

    return official_plan(user_input)


def _research_intent(route: dict[str, Any]) -> bool:
    """True when the routed task contract asked for external research."""

    contract = route.get("task_contract")
    return isinstance(contract, dict) and contract.get("task_intent") == "research"


def _official_publication_required(prepared: PreparedChatTurn) -> bool:
    from src.web.research.official_resolver import official_plan

    tools = (prepared.rag or {}).get("web_tools") or {}
    return bool(tools.get("enabled") and (official_plan(prepared.turn.user_message)
                or _research_intent(prepared.route)))


def _tool_read_validation_plan(
    trace: Any, question: str
) -> dict[str, Any] | None:
    """Publication rows for the pages this turn's tool loop actually read.

    A research turn normally receives its plan from a ResearchRun, whose
    claim-engine brief carries validated support rows. The inline tool loop has
    no such brief, so it used to fall through to a fixed refusal without ever
    calling the model - even after a successful read.

    Reading a page is not support for a claim, so these rows carry **no**
    supports/strong label. They carry the page body instead, and the binder
    grants support only when the claim itself is found in that body. Excerpts
    are taken around the question's own terms rather than from the page head, so
    a fact stated later in the article is visible to the binder.
    """

    from urllib.parse import urlsplit

    from src.web.tool_evidence import evidence_tool_calls

    calls = evidence_tool_calls(
        list(getattr(trace, "calls", ()) or ()),
        require_discovery=bool(getattr(trace, "require_discovery", True)),
    )
    rows: list[dict[str, Any]] = []
    for index, call in enumerate(calls[:8], start=1):
        result = call.get("result") if isinstance(call, dict) else None
        if not isinstance(result, dict):
            continue
        raw_arguments = call.get("arguments")
        arguments = raw_arguments if isinstance(raw_arguments, dict) else {}
        url = str(result.get("url") or arguments.get("url") or "").strip()
        body = str(result.get("content") or result.get("readme") or "")
        if not url or not body.strip():
            continue
        rows.append(
            {
                "evidence_id": f"tool_read_{index}",
                # One claim id for the turn: these reads answer the user's
                # question as a whole, not a decomposed research sub-claim.
                "claim_id": "inline_tool_read",
                "title": str(result.get("title") or url)[:200],
                "url": url,
                "source_role": "public_page",
                "source_cluster_id": urlsplit(url).netloc[:100],
                # Not a support relation: `strength` stays empty so the row
                # cannot authorize a claim by itself.
                "relation": "read",
                "strength": "",
                "locator": "",
                "anchored_spans": _question_excerpts(body, question),
                "caveats": ("read_by_inline_tool_loop",),
                "grounding_text": body[:12_000],
            }
        )
    if not rows:
        return None
    return {
        "evidence_rows": rows,
        "allowed_attempts": 1,
        "source": "inline_tool_loop",
    }


def inline_research_validation_plan(
    trace: Any,
    route: dict[str, Any],
    user_input: str,
    provided: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """The publication rows a research turn's own reads actually earned.

    Both preparation pipelines call this: the base ``ChatService`` and the
    external-data-policy pipeline that production uses. It lives here once
    because duplicating the condition is how the policy path lost its
    read-backed answer - it published a fixed refusal without ever calling
    the model, even though the turn had read a page.
    """

    if provided is not None:
        return provided
    if not _research_intent(route) or not trace.used:
        return None
    # Known-source turns keep their deterministic field publication: that seam
    # withholds model prose on purpose. It is the general research turn that
    # must not lose its answer.
    if _official_plan_for(user_input) is not None:
        return None
    return _tool_read_validation_plan(trace, user_input)


def _question_excerpts(body: str, question: str, *, limit: int = 3) -> tuple[str, ...]:
    """Excerpts from anywhere in the body that mention the question's terms.

    The head of a page is often navigation or an introduction; a fact the answer
    needs may sit far below it. Windows are taken around the first occurrences of
    the question's distinctive tokens, always including the head as a fallback.
    """

    text = str(body or "")
    if not text.strip():
        return ()
    windows: list[tuple[int, int]] = [(0, min(len(text), 300))]
    folded = text.casefold()
    tokens = [
        token
        for token in re.findall(r"[0-9a-z.]{4,}|[\u4e00-\u9fff]{2,}", question.casefold())
        if token
    ]
    for token in sorted(set(tokens), key=len, reverse=True)[:8]:
        position = folded.find(token)
        if position < 0:
            continue
        start = max(0, position - 80)
        end = min(len(text), position + 220)
        if any(start < used_end and used_start < end for used_start, used_end in windows):
            continue
        windows.append((start, end))
        if len(windows) >= limit:
            break
    return tuple(text[start:end] for start, end in windows)


def _route_generation_calls(route_snapshot: dict[str, Any]) -> int:
    try:
        calls = int(route_snapshot.get("answer_generation_calls", 0))
    except (TypeError, ValueError):
        return 0
    return max(0, min(calls, 1000))
