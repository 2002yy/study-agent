"""Research opening + progress narration ("研究开场") — display-only contract.

A ``ResearchApproach`` explains *how the agent intends to research*, never *what
it has proven*.  It therefore carries **no evidence authority**: it must never be
written into the Evidence Gate, must never turn a research goal into
``supported``, and must never be used as a factual citation in the answer.

This module deliberately does not touch ``standard-research-plan-v1`` (see
``src/web/research/standard_plan.py``), whose envelope is a strict four-key
contract.  The approach is a *separate* object with its own schema.

Three origins, in the contract's order of preference:

``model_plan``
    Projected from a plan the model already produced (no extra call).  Preferred.
``model_generated``
    One bounded completion produced the short opening (counts against budget).
``fallback``
    Deterministic, honest placeholder used only when nothing better exists.

Failure policy: nothing here may ever raise into the research path.  Callers use
the ``*_or_fallback`` helpers, which swallow generator errors.
"""

from __future__ import annotations

from typing import Any, Callable

APPROACH_SCHEMA = "research-approach-v1"

MODE_LOOKUP = "lookup"
MODE_STANDARD = "standard"
MODE_DEEP = "deep"
_MODES = (MODE_LOOKUP, MODE_STANDARD, MODE_DEEP)

STATUS_PENDING = "pending"
STATUS_READY = "ready"
STATUS_FAILED = "failed"
_STATUSES = (STATUS_PENDING, STATUS_READY, STATUS_FAILED)

ORIGIN_MODEL_PLAN = "model_plan"
ORIGIN_MODEL_GENERATED = "model_generated"
ORIGIN_FALLBACK = "fallback"
ORIGIN_DIRECTION_UPDATE = "direction_update"
_ORIGINS = (
    ORIGIN_MODEL_PLAN,
    ORIGIN_MODEL_GENERATED,
    ORIGIN_FALLBACK,
    ORIGIN_DIRECTION_UPDATE,
)

# Sentence/character budgets per mode (the contract's 1 / 1-2 / 2-3 sentences).
MAX_SUMMARY_CHARS = {MODE_LOOKUP: 140, MODE_STANDARD: 300, MODE_DEEP: 480}
MAX_FOCUS = 6
MAX_FOCUS_ITEM_CHARS = 32

# Filler that must never open a research summary.
_FILLER_MARKERS = (
    "让我看看",
    "让我帮你看看",
    "我来帮你看看",
    "稍等",
    "好的，",
    "嗯，",
    "please wait",
    "let me take a look",
)

# Completion/verification claims that must not appear in an *initial* opening:
# the opening describes intent, not results.  A ``direction_update`` may cite
# prior *progress* only when the caller has real research state to back it, so it
# is exempted here (see ``validate_approach(..., allow_progress_claims=True)``).
_PROGRESS_CLAIM_MARKERS = (
    "已完成",
    "已经完成",
    "已核验",
    "已经核验",
    "已证实",
    "已验证",
    "已读取",
    "我已经查到",
    "已找到",
    "已完成核验",
    "confirmed",
    "verified",
    "already completed",
)


def normalize_mode(mode: Any) -> str:
    """Map an unknown/legacy mode onto the three display modes."""

    value = str(mode or "").strip().lower()
    if value in _MODES:
        return value
    return MODE_STANDARD


def _clean_text(value: Any) -> str:
    return " ".join(str(value or "").split())


def _clean_focus(focus: Any) -> list[str]:
    if not isinstance(focus, (list, tuple)):
        return []
    out: list[str] = []
    seen: set[str] = set()
    for item in focus:
        text = _clean_text(item)
        if not text or text in seen:
            continue
        seen.add(text)
        out.append(text[:MAX_FOCUS_ITEM_CHARS])
        if len(out) >= MAX_FOCUS:
            break
    return out


def validate_approach(
    approach: Any,
    *,
    previous: dict[str, Any] | None = None,
    allow_progress_claims: bool = False,
) -> dict[str, Any]:
    """Return a normalized copy or raise ``ValueError``.

    Deterministic checks only: envelope, enum membership, per-mode length,
    empty/duplicate summaries, filler openings, and unverified completion claims.
    """

    if not isinstance(approach, dict):
        raise ValueError("invalid research approach envelope")
    if approach.get("schema") != APPROACH_SCHEMA:
        raise ValueError("research approach schema mismatch")
    mode = normalize_mode(approach.get("mode"))
    status = str(approach.get("status") or "").strip()
    if status not in _STATUSES:
        raise ValueError("invalid research approach status")
    origin = str(approach.get("origin") or "").strip()
    if origin not in _ORIGINS:
        raise ValueError("invalid research approach origin")

    summary = _clean_text(approach.get("summary"))
    focus = _clean_focus(approach.get("focus"))
    if status == STATUS_READY:
        if not summary:
            raise ValueError("ready approach requires a summary")
        if len(summary) > MAX_SUMMARY_CHARS[mode]:
            raise ValueError("research approach summary too long")
        lowered = summary.lower()
        if any(marker.lower() in lowered for marker in _FILLER_MARKERS):
            raise ValueError("research approach must not open with filler")
        if not allow_progress_claims and any(
            marker.lower() in lowered for marker in _PROGRESS_CLAIM_MARKERS
        ):
            raise ValueError("research approach must not claim unverified completion")
        if previous is not None:
            prior = _clean_text(previous.get("summary"))
            if prior and prior == summary:
                raise ValueError("research approach duplicated the previous summary")

    try:
        sequence = max(0, int(approach.get("sequence") or 0))
    except (TypeError, ValueError):
        raise ValueError("invalid research approach sequence") from None

    return {
        "schema": APPROACH_SCHEMA,
        "root_run_id": _clean_text(approach.get("root_run_id")),
        "turn_id": _clean_text(approach.get("turn_id")),
        "mode": mode,
        "status": status,
        "summary": summary,
        "focus": focus,
        "origin": origin,
        "sequence": sequence,
    }


def seed_approach(
    *,
    mode: Any,
    root_run_id: str = "",
    turn_id: str = "",
) -> dict[str, Any]:
    """The creation-time placeholder: honest, empty, never a template claim.

    ``status='pending'`` means "no opening yet"; the UI shows the existing
    deterministic tool progress until a real summary is attached.
    """

    return validate_approach(
        {
            "schema": APPROACH_SCHEMA,
            "root_run_id": root_run_id,
            "turn_id": turn_id,
            "mode": normalize_mode(mode),
            "status": STATUS_PENDING,
            "summary": "",
            "focus": [],
            "origin": ORIGIN_FALLBACK,
            "sequence": 0,
        }
    )


def project_from_plan(
    *,
    mode: Any,
    summary: Any,
    focus: Any = (),
    root_run_id: str = "",
    turn_id: str = "",
    sequence: int = 1,
) -> dict[str, Any]:
    """Preferred path: reuse natural language the model already produced."""

    return validate_approach(
        {
            "schema": APPROACH_SCHEMA,
            "root_run_id": root_run_id,
            "turn_id": turn_id,
            "mode": normalize_mode(mode),
            "status": STATUS_READY,
            "summary": summary,
            "focus": focus,
            "origin": ORIGIN_MODEL_PLAN,
            "sequence": sequence,
        }
    )


def _compose_summary(mode: str, names: list[str]) -> str:
    joined = "、".join(names)
    if mode == MODE_LOOKUP:
        return f"我会先核对 {joined} 的官方说明。"
    if mode == MODE_DEEP:
        return (
            f"我会先建立关于 {joined} 的候选清单，再分别验证并补全尚未明确的部分，"
            "最后标明证据不足的地方。"
        )
    return f"我会分别核对 {joined}，并通过检索补全尚未解决的部分。"


def summarize_plan(
    *,
    mode: Any,
    fields: Any,
    root_run_id: str = "",
    turn_id: str = "",
    sequence: int = 1,
) -> dict[str, Any]:
    """Preferred path when a model plan already exists.

    Projects the plan's **own** unresolved field names into a short, honest
    direction.  Deterministic: **no extra model call**, and the four-key plan
    envelope is never touched.  Degrades to :func:`fallback_approach` when the
    plan carries no usable field names (never invents facts).
    """

    resolved_mode = normalize_mode(mode)
    names = _clean_focus(fields)
    if not names:
        return fallback_approach(
            mode=resolved_mode, root_run_id=root_run_id, turn_id=turn_id, sequence=sequence
        )
    limit = MAX_SUMMARY_CHARS[resolved_mode]
    summary = _compose_summary(resolved_mode, names)
    # Deterministic length guard: drop trailing fields until it fits the mode
    # budget, so validation can never reject a projection we ourselves produced.
    while names and len(summary) > limit:
        names = names[:-1]
        summary = _compose_summary(resolved_mode, names) if names else ""
    if not summary:
        return fallback_approach(
            mode=resolved_mode, root_run_id=root_run_id, turn_id=turn_id, sequence=sequence
        )
    return project_from_plan(
        mode=resolved_mode,
        summary=summary,
        focus=names,
        root_run_id=root_run_id,
        turn_id=turn_id,
        sequence=sequence,
    )


def fallback_approach(
    *,
    mode: Any,
    root_run_id: str = "",
    turn_id: str = "",
    sequence: int = 1,
) -> dict[str, Any]:
    """Degraded hint.  Honest, generic, and never a research judgement."""

    return validate_approach(
        {
            "schema": APPROACH_SCHEMA,
            "root_run_id": root_run_id,
            "turn_id": turn_id,
            "mode": normalize_mode(mode),
            "status": STATUS_READY,
            "summary": "我会先查找相关资料，核对来源后再给出经过核验的回答。",
            "focus": [],
            "origin": ORIGIN_FALLBACK,
            "sequence": sequence,
        }
    )


def direction_update(
    *,
    previous: dict[str, Any],
    summary: Any,
    focus: Any = (),
    mode: Any | None = None,
    sequence: int | None = None,
) -> dict[str, Any]:
    """Mode upgrade / steering: continue, never re-open.

    Carries the *new* direction only, keeps the original binding, and advances
    the sequence so clients can order it.
    """

    prior = validate_approach(previous, allow_progress_claims=True) if previous else None
    resolved_mode = normalize_mode(mode if mode is not None else (prior or {}).get("mode"))
    next_sequence = (
        int(sequence)
        if sequence is not None
        else int((prior or {}).get("sequence") or 0) + 1
    )
    return validate_approach(
        {
            "schema": APPROACH_SCHEMA,
            "root_run_id": (prior or {}).get("root_run_id", ""),
            "turn_id": (prior or {}).get("turn_id", ""),
            "mode": resolved_mode,
            "status": STATUS_READY,
            "summary": summary,
            "focus": focus,
            "origin": ORIGIN_DIRECTION_UPDATE,
            "sequence": next_sequence,
        },
        previous=prior,
        allow_progress_claims=True,
    )


_PROMPT = (
    "任务：生成用户可见的简短研究方向说明。\n"
    "要求：\n"
    "1. 用第一人称自然语言说明将如何解决当前问题。\n"
    "2. 明确最重要的研究维度和验证重点。\n"
    "3. 根据问题复杂度输出 1~3 句（lookup 1 句，standard 1~2 句，deep 2~3 句）。\n"
    "4. 不要输出“让我看看”“稍等”等空泛过渡语。\n"
    "5. 不要声称已执行尚未执行的工具操作。\n"
    "6. 不要提前给出未验证的事实、排名或结论。\n"
    "7. 不要请求用户批准；生成后研究流程自动继续。\n"
    "8. 如果已有研究进展，只说明新增方向，不重复开场。\n"
    "9. 不输出内部推理过程。\n"
    '只返回 JSON：{"summary": str, "focus": [str, ...]}。'
)


def generate_approach(
    completion: Callable[..., str],
    *,
    mode: Any,
    query: str,
    context: Any = None,
    root_run_id: str = "",
    turn_id: str = "",
    previous: dict[str, Any] | None = None,
    sequence: int = 1,
    timeout: float = 8.0,
    max_tokens: int = 320,
) -> dict[str, Any]:
    """Conditional path: one bounded completion produces the opening.

    Raises on any failure so the caller can fall back; the ``*_or_fallback``
    wrapper is the safe entry point.
    """

    import json

    resolved_mode = normalize_mode(mode)
    request = {
        "mode": resolved_mode,
        "question": _clean_text(query),
        "focus_hint": _clean_focus(context),
        "previous_summary": _clean_text((previous or {}).get("summary")),
    }
    text = completion(
        [
            {"role": "system", "content": _PROMPT},
            {"role": "user", "content": json.dumps(request, ensure_ascii=False)},
        ],
        temperature=0,
        model_profile="flash",
        max_tokens=max_tokens,
        timeout=timeout,
        response_format="json_object",
        request_max_retries=0,
    )
    payload = json.loads(text)
    if not isinstance(payload, dict):
        raise ValueError("research approach generator returned non-object")
    return validate_approach(
        {
            "schema": APPROACH_SCHEMA,
            "root_run_id": root_run_id,
            "turn_id": turn_id,
            "mode": resolved_mode,
            "status": STATUS_READY,
            "summary": payload.get("summary"),
            "focus": payload.get("focus"),
            "origin": ORIGIN_MODEL_GENERATED,
            "sequence": sequence,
        },
        previous=previous,
    )


def generate_approach_or_fallback(
    completion: Callable[..., str] | None,
    *,
    mode: Any,
    query: str,
    context: Any = None,
    root_run_id: str = "",
    turn_id: str = "",
    previous: dict[str, Any] | None = None,
    sequence: int = 1,
    timeout: float = 8.0,
    max_tokens: int = 320,
) -> tuple[dict[str, Any], bool]:
    """Fail-open entry point.  Returns ``(approach, model_call_spent)``.

    A missing completion, a timeout, empty content, or an invalid payload all
    degrade to :func:`fallback_approach`; research must never be blocked by the
    opening.
    """

    if completion is None:
        return (
            fallback_approach(
                mode=mode, root_run_id=root_run_id, turn_id=turn_id, sequence=sequence
            ),
            False,
        )
    try:
        return (
            generate_approach(
                completion,
                mode=mode,
                query=query,
                context=context,
                root_run_id=root_run_id,
                turn_id=turn_id,
                previous=previous,
                sequence=sequence,
                timeout=timeout,
                max_tokens=max_tokens,
            ),
            True,
        )
    except Exception:
        return (
            fallback_approach(
                mode=mode, root_run_id=root_run_id, turn_id=turn_id, sequence=sequence
            ),
            True,
        )


def approach_event(
    approach: Any,
    *,
    root_run_id: str = "",
    turn_id: str = "",
) -> dict[str, Any] | None:
    """The wire payload for the ``research`` SSE event.

    Only the display subset is emitted.  ``root_run_id``/``turn_id`` are bound
    from the run at emit time so stored approaches need not know their own id.
    """

    if not isinstance(approach, dict) or approach.get("schema") != APPROACH_SCHEMA:
        return None
    status = str(approach.get("status") or "").strip()
    if status not in _STATUSES:
        # Corrupted persisted data suppresses the whole opening; it must never
        # raise into, or partially leak through, the research progress path.
        return None
    raw_sequence = approach.get("sequence")
    if not isinstance(raw_sequence, int) or isinstance(raw_sequence, bool):
        return None
    if raw_sequence < 0:
        return None
    sequence = raw_sequence
    return {
        "status": status,
        "summary": _clean_text(approach.get("summary")),
        "focus": _clean_focus(approach.get("focus")),
        "origin": str(approach.get("origin") or ""),
        "sequence": sequence,
        "mode": normalize_mode(approach.get("mode")),
        "root_run_id": _clean_text(root_run_id) or _clean_text(approach.get("root_run_id")),
        "turn_id": _clean_text(turn_id) or _clean_text(approach.get("turn_id")),
    }
