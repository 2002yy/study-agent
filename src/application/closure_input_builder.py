"""Build bounded, evidence-linked input for learning closure generation."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any, Protocol

from src.domain.runtime_entities import ChatTurn
from src.domain.review_turn import read_review_snapshot
from src.pedagogy.evaluation import PedagogyEvalRun

CLOSURE_INPUT_SCHEMA_VERSION = "learning-closure-input-v1"
DEFAULT_RECENT_TURN_LIMIT = 6
DEFAULT_DIALOGUE_CHAR_BUDGET = 6000
DEFAULT_MESSAGE_CHAR_LIMIT = 1800
DEFAULT_GITHUB_LEARNING_SOURCE_LIMIT = 8

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
_PROJECT_STATE_KEYS = (
    "current_stage",
    "next_action",
    "objective",
    "known_facts",
    "acceptance_criteria",
    "completed_deliverables",
    "failed_tests",
    "blockers",
    "milestones",
    "artifacts",
    "project_validation_passed",
    "validation_required",
    "last_response_violations",
)
_GITHUB_LEARNING_TOOL_NAMES = {
    "github_search",
    "github_snapshot",
    "github_structure",
    "github_impact",
}
_PROJECT_STRING_LIMIT = 1200
_PROJECT_COLLECTION_LIMIT = 20


class EvaluationRepository(Protocol):
    def get_for_turn(self, turn_id: str) -> PedagogyEvalRun | None: ...


def build_structured_closure_input(
    *,
    thread_id: str,
    closure_eligibility: str,
    task_contract: dict[str, Any],
    learning_state: dict[str, Any],
    all_turns: list[ChatTurn],
    completed_turns: list[ChatTurn],
    evaluation_repository: EvaluationRepository | None = None,
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
    committed_project_state = _committed_project_state(learning_state)
    final_evaluation = _final_evaluation(
        completed_turns,
        evaluation_repository=evaluation_repository,
    )
    review_fields = {}
    if completed_turns and "review" in completed_turns[-1].route_snapshot:
        answer = completed_turns[-1]
        binding = read_review_snapshot(answer.route_snapshot["review"], phase="answer")
        prompt = next((item for item in completed_turns if item.id == binding.prompt_turn_id), None)
        if prompt is None or read_review_snapshot(prompt.route_snapshot.get("review"), phase="prompt") != binding:
            raise ValueError("Review closure prompt binding mismatch")
        if prompt.assistant_message != binding.question or binding.thread_id != thread_id:
            raise ValueError("Review closure source mismatch")
        exact_eval = evaluation_repository.get_for_turn(answer.id) if evaluation_repository else None
        if exact_eval is None:
            raise ValueError("Review closure requires exact answer evaluation")
        final_evaluation = {**asdict(exact_eval), "turn_id": answer.id}
        review_fields["review_attempt"] = {
            "binding": binding.to_dict(), "answer_turn_id": answer.id, "evaluation_id": exact_eval.id,
        }
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
    github_learning_sources = _github_learning_sources(completed_turns)
    allowed_source_refs = _allowed_source_refs(
        committed_state=committed_state,
        committed_project_state=committed_project_state,
        final_evaluation=final_evaluation,
        evidence_ids=evidence_ids,
        recent_dialogue=recent_dialogue,
        github_learning_sources=github_learning_sources,
    )
    summary_kind = (
        "project_closure"
        if closure_eligibility == "project_summary"
        else "learning_summary"
    )
    return {
        **review_fields,
        "schema_version": CLOSURE_INPUT_SCHEMA_VERSION,
        "thread_id": thread_id,
        "summary_kind": summary_kind,
        "closure_eligibility": closure_eligibility,
        "task_contract": dict(task_contract),
        "committed_learning_state": committed_state,
        "committed_project_state": committed_project_state,
        "final_pedagogy_evaluation": final_evaluation,
        "evidence_ids": evidence_ids,
        "github_learning_sources": github_learning_sources,
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
            "project_facts_source": "committed_project_state_only",
            "failed_or_uncommitted_turns_are_not_mastery_evidence": True,
            "project_validation_passed_must_be_true_to_claim_validation": True,
            "durable_claim_requires_explicit_semantic_closure": True,
            "durable_claim_requires_commit_pinned_github_source": True,
            "legacy_confirmed_points_never_auto_promote_to_claim": True,
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
                "pedagogy_move": str(turn.pedagogy_snapshot.get("move") or ""),
                "evidence_ids": _turn_evidence_ids(turn),
            }
        )
        used += candidate_chars
    return list(reversed(selected_reversed)), used


def _final_evaluation(
    completed_turns: list[ChatTurn],
    *,
    evaluation_repository: EvaluationRepository | None,
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


def _github_learning_sources(
    completed_turns: list[ChatTurn],
    *,
    limit: int = DEFAULT_GITHUB_LEARNING_SOURCE_LIMIT,
) -> list[dict[str, str]]:
    """Project only immutable, replayable GitHub source reads into closure input."""

    bounded_limit = max(1, min(int(limit), 20))
    sources: list[dict[str, str]] = []
    seen: set[tuple[str, str, str]] = set()
    for turn in reversed(completed_turns):
        rag = turn.rag_snapshot if isinstance(turn.rag_snapshot, dict) else {}
        web_tools = rag.get("web_tools")
        if not isinstance(web_tools, dict):
            continue
        calls = web_tools.get("calls")
        if not isinstance(calls, list):
            continue
        for call_index, call in reversed(list(enumerate(calls))):
            if not isinstance(call, dict):
                continue
            name = str(call.get("name") or "").strip()
            if name not in _GITHUB_LEARNING_TOOL_NAMES:
                continue
            arguments = call.get("arguments")
            result = call.get("result")
            if not isinstance(arguments, dict) or not isinstance(result, dict):
                continue
            if result.get("ok") is False:
                continue
            repo_url = str(arguments.get("repo_url") or "").strip()
            query = str(
                arguments.get("query")
                or arguments.get("symbol")
                or ""
            ).strip()
            commit_sha = str(result.get("commit_sha") or "").strip()
            if not repo_url or not query or not commit_sha:
                continue
            identity = (repo_url, query, commit_sha)
            if identity in seen:
                continue
            seen.add(identity)
            source_ref = f"github_source:{turn.id}:{call_index}"
            sources.append(
                {
                    "source_ref": source_ref,
                    "turn_id": turn.id,
                    "tool_name": name,
                    "repo_url": repo_url,
                    "query": query,
                    "commit_sha": commit_sha,
                }
            )
            if len(sources) >= bounded_limit:
                return sources
    return sources


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
    committed_project_state: dict[str, Any],
    final_evaluation: dict[str, Any] | None,
    evidence_ids: list[str],
    recent_dialogue: list[dict[str, Any]],
    github_learning_sources: list[dict[str, str]],
) -> list[str]:
    refs = {
        f"learning_state.{key}"
        for key, value in committed_state.items()
        if value not in (None, "", [], {})
    }
    refs.update(
        f"project_state.{key}"
        for key, value in committed_project_state.items()
        if value not in (None, "", [], {})
    )
    if final_evaluation:
        refs.add(f"pedagogy_eval:{final_evaluation['id']}")
    refs.update(f"evidence:{item}" for item in evidence_ids)
    refs.update(f"turn:{item['turn_id']}" for item in recent_dialogue)
    refs.update(
        item["source_ref"]
        for item in github_learning_sources
        if item.get("source_ref")
    )
    return sorted(refs)


def _committed_project_state(learning_state: dict[str, Any]) -> dict[str, Any]:
    payload = learning_state.get("payload")
    if not isinstance(payload, dict):
        return {}
    result: dict[str, Any] = {}
    for key in _PROJECT_STATE_KEYS:
        if key not in payload:
            continue
        normalized = _bounded_project_value(payload[key])
        if normalized not in (None, "", [], {}):
            result[key] = normalized
    return result


def _bounded_project_value(value: Any, *, depth: int = 0) -> Any:
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, (int, float)):
        return value
    if isinstance(value, str):
        return _truncate(value, _PROJECT_STRING_LIMIT)
    if isinstance(value, (list, tuple)):
        return [
            normalized
            for item in list(value)[:_PROJECT_COLLECTION_LIMIT]
            if (normalized := _bounded_project_value(item, depth=depth + 1))
            not in (None, "", [], {})
        ]
    if isinstance(value, dict) and depth < 2:
        result: dict[str, Any] = {}
        for raw_key, raw_value in list(value.items())[:_PROJECT_COLLECTION_LIMIT]:
            normalized = _bounded_project_value(raw_value, depth=depth + 1)
            if normalized not in (None, "", [], {}):
                result[_truncate(str(raw_key), 120)] = normalized
        return result
    return _truncate(str(value), _PROJECT_STRING_LIMIT)


def _truncate(text: str, limit: int) -> str:
    normalized = str(text or "").strip()
    if len(normalized) <= limit:
        return normalized
    return normalized[: max(1, limit - 1)].rstrip() + "…"
