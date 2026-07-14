"""Build bounded, evidence-linked input for learning closure generation."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from src.domain.runtime_entities import ChatTurn
from src.repositories.pedagogy_eval_repository import PedagogyEvalRepository

CLOSURE_INPUT_SCHEMA_VERSION = "learning-closure-input-v1"
DEFAULT_RECENT_TURN_LIMIT = 6
DEFAULT_DIALOGUE_CHAR_BUDGET = 6000
DEFAULT_MESSAGE_CHAR_LIMIT = 1800

_COMMITTED_STATE_KEYS = (
    "protocol",
    "protocol_version",
    "objective",
    "phase",
    "learner_claim",
    "confirmed_points",
    "unresolved_gap",
    "attempted_examples",
    "hint_level",
    "library_facts_given",
    "turn_count",
)


def build_structured_closure_input(
    *,
    thread_id: str,
    closure_eligibility: str,
    task_contract: dict[str, Any],
    learning_state: dict[str, Any],
    all_turns: list[ChatTurn],
    completed_turns: list[ChatTurn],
    evaluation_repository: PedagogyEvalRepository | None = None,
    recent_turn_limit: int = DEFAULT_RECENT_TURN_LIMIT,
    dialogue_char_budget: int = DEFAULT_DIALOGUE_CHAR_BUDGET,
    message_char_limit: int = DEFAULT_MESSAGE_CHAR_LIMIT,
) -> dict[str, Any]:
    """Return deterministic structured input without treating failed work as truth."""

    safe_recent_limit = max(1, min(int(recent_turn_limit), 20))
    safe_budget = max(500, min(int(dialogue_char_budget), 20000))
    safe_message_limit = max(200, min(int(message_char_limit), 5000))
    committed_state = {
        key: learning_state[key]
        for key in _COMMITTED_STATE_KEYS
        if key in learning_state
    }
    final_evaluation = _final_evaluation(
        completed_turns,
        evaluation_repository=evaluation_repository,
    )
    recent_dialogue, used_chars = _recent_dialogue(
        completed_turns,
        turn_limit=safe_recent_limit,
        char_budget=safe_budget,
        message_char_limit=safe_message_limit,
    )
    included_turn_ids = {str(item["turn_id"]) for item in recent_dialogue}
    excluded_turns = [
        {"turn_id": turn.id, "status": turn.status}
        for turn in all_turns
        if turn.status != "completed"
    ]
    evidence_ids = sorted(
        {
            evidence_id
            for turn in completed_turns
            for evidence_id in _turn_evidence_ids(turn)
        }
        | set(_evaluation_evidence_ids(final_evaluation))
    )
    allowed_source_refs = _allowed_source_refs(
        committed_state=committed_state,
        final_evaluation=final_evaluation,
        evidence_ids=evidence_ids,
        recent_dialogue=recent_dialogue,
    )
    summary_kind = (
        "project_closure"
        if closure_eligibility == "project_summary"
        else "learning_summary"
    )
    return {
        "schema_version": CLOSURE_INPUT_SCHEMA_VERSION,
        "thread_id": thread_id,
        "summary_kind": summary_kind,
        "closure_eligibility": closure_eligibility,
        "task_contract": dict(task_contract),
        "committed_learning_state": committed_state,
        "final_pedagogy_evaluation": final_evaluation,
        "evidence_ids": evidence_ids,
        "recent_dialogue": recent_dialogue,
        "dialogue_budget": {
            "turn_limit": safe_recent_limit,
            "char_budget": safe_budget,
            "message_char_limit": safe_message_limit,
            "used_chars": used_chars,
            "included_completed_turns": len(included_turn_ids),
            "omitted_completed_turns": max(
                0, len(completed_turns) - len(included_turn_ids)
            ),
            "older_context_strategy": "dropped",
        },
        "excluded_uncommitted_turns": excluded_turns,
        "allowed_source_refs": allowed_source_refs,
        "candidate_policy": {
            "learner_profile_default_pending": True,
            "confirmed_points_source": "committed_learning_state_only",
            "failed_or_uncommitted_turns_are_not_mastery_evidence": True,
        },
    }


def _recent_dialogue(
    completed_turns: list[ChatTurn],
    *,
    turn_limit: int,
    char_budget: int,
    message_char_limit: int,
) -> tuple[list[dict[str, Any]], int]:
    selected_reversed: list[dict[str, Any]] = []
    used = 0
    for turn in reversed(completed_turns):
        if len(selected_reversed) >= turn_limit:
            break
        user_message = _truncate(turn.user_message, message_char_limit)
        assistant_message = _truncate(turn.assistant_message, message_char_limit)
        candidate_chars = len(user_message) + len(assistant_message)
        if selected_reversed and used + candidate_chars > char_budget:
            break
        if not selected_reversed and candidate_chars > char_budget:
            remaining = max(1, char_budget // 2)
            user_message = _truncate(user_message, remaining)
            assistant_message = _truncate(assistant_message, remaining)
            candidate_chars = len(user_message) + len(assistant_message)
        selected_reversed.append(
            {
                "turn_id": turn.id,
                "user_message": user_message,
                "assistant_message": assistant_message,
                "pedagogy_phase": str(turn.pedagogy_snapshot.get("phase") or ""),
                "evidence_ids": _turn_evidence_ids(turn),
            }
        )
        used += candidate_chars
    return list(reversed(selected_reversed)), used


def _final_evaluation(
    completed_turns: list[ChatTurn],
    *,
    evaluation_repository: PedagogyEvalRepository | None,
) -> dict[str, Any] | None:
    if evaluation_repository is None:
        return None
    for turn in reversed(completed_turns):
        run = evaluation_repository.get_for_turn(turn.id)
        if run is None:
            continue
        payload = asdict(run)
        payload["turn_id"] = turn.id
        return payload
    return None


def _turn_evidence_ids(turn: ChatTurn) -> list[str]:
    identifiers: set[str] = set()
    rag = turn.rag_snapshot if isinstance(turn.rag_snapshot, dict) else {}
    for item in rag.get("results", []) if isinstance(rag.get("results"), list) else []:
        if not isinstance(item, dict):
            continue
        for key in ("id", "evidence_id", "chunk_id", "source_id"):
            value = item.get(key)
            if value:
                identifiers.add(str(value))
        chunk = item.get("chunk")
        if isinstance(chunk, dict):
            for key in ("chunk_id", "source_path"):
                value = chunk.get(key)
                if value:
                    identifiers.add(str(value))
    route = turn.route_snapshot if isinstance(turn.route_snapshot, dict) else {}
    for key in ("evidence_ids", "selected_evidence_ids"):
        value = route.get(key)
        if isinstance(value, list):
            identifiers.update(str(item) for item in value if str(item).strip())
    return sorted(identifiers)


def _evaluation_evidence_ids(final_evaluation: dict[str, Any] | None) -> list[str]:
    if not final_evaluation:
        return []
    values: set[str] = set()
    evidence = final_evaluation.get("evidence")
    if isinstance(evidence, (list, tuple)):
        values.update(str(item) for item in evidence if str(item).strip())
    semantic = final_evaluation.get("semantic_result")
    if isinstance(semantic, dict):
        refs = semantic.get("evidence_refs")
        if isinstance(refs, (list, tuple)):
            values.update(str(item) for item in refs if str(item).strip())
    return sorted(values)


def _allowed_source_refs(
    *,
    committed_state: dict[str, Any],
    final_evaluation: dict[str, Any] | None,
    evidence_ids: list[str],
    recent_dialogue: list[dict[str, Any]],
) -> list[str]:
    refs = {
        f"learning_state.{key}"
        for key, value in committed_state.items()
        if value not in (None, "", [], {})
    }
    if final_evaluation:
        refs.add(f"pedagogy_eval:{final_evaluation['id']}")
    refs.update(f"evidence:{item}" for item in evidence_ids)
    refs.update(f"turn:{item['turn_id']}" for item in recent_dialogue)
    refs.update(
        {
            "memory:progress.md",
            "memory:learner_profile.md",
            "memory:current_focus.md",
        }
    )
    return sorted(refs)


def _truncate(text: str, limit: int) -> str:
    normalized = str(text or "").strip()
    if len(normalized) <= limit:
        return normalized
    return normalized[: max(1, limit - 1)].rstrip() + "…"
