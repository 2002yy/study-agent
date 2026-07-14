"""Evidence-linked generator and candidate normalization for G2 closure input."""

from __future__ import annotations

import json
from typing import Any

from src.llm_client import ModelProfile, chat
from src.text_utils import strip_code_fences

STRUCTURED_CLOSURE_SCHEMA_VERSION = "learning-closure-candidates-v1"
_ALLOWED_TARGETS: dict[str, bool] = {
    "progress": True,
    "learner_profile": True,
    "current_focus": False,
    "revision_notes": True,
    "session_archive": True,
}
_ALLOWED_CONFIDENCE = {"low", "medium", "high"}
_NO_UPDATE_MARKERS = {
    "",
    "本轮无需更新",
    "（本轮无需更新）",
    "无更新",
}
_MEMORY_CHAR_LIMIT = 2400

_SYSTEM_PROMPT = """你是学习系统的结构化整理生成器。
只允许根据输入 JSON 中的 committed_learning_state、final_pedagogy_evaluation、evidence_ids、recent_dialogue 和 memory_context 生成候选。
不得把 excluded_uncommitted_turns、失败回合、planned state、用户仅口头声称“懂了”当作掌握证据。
confirmed_points 只能来自 committed_learning_state.confirmed_points；最终评估不是 accept 时，不得把其内容写成已掌握。
learner_profile 候选必须 learner_pending=true，不得诊断心理、健康或敏感属性。
每个候选必须给出 allowed_source_refs 中的 source_refs；没有来源就不要生成该候选。
严格输出一个 JSON 对象，不要 markdown：
{
  "schema_version": "learning-closure-candidates-v1",
  "summary_kind": "learning_summary 或 project_closure",
  "candidates": [
    {
      "target": "progress|learner_profile|current_focus|revision_notes|session_archive",
      "content": "简洁、可确认的候选内容",
      "confidence": "low|medium|high",
      "source_refs": ["allowed_source_refs 中的值"],
      "evaluation_refs": ["PedagogyEvalRun id，可为空"],
      "learner_pending": false
    }
  ]
}
不要输出 role_updates。没有可靠候选时 candidates 为空数组。"""


def generate_structured_closure_candidates(
    structured_input: dict[str, Any],
    memory_bundle: dict[str, str],
    role: str,
    mode: str,
    model_profile: ModelProfile = "pro",
) -> dict[str, Any]:
    """Call the model with bounded structured evidence, never the full transcript."""

    payload = dict(structured_input)
    memory_context = _bounded_memory_context(memory_bundle)
    allowed_refs = {
        str(item)
        for item in structured_input.get("allowed_source_refs", [])
        if str(item).strip()
    }
    allowed_refs.update(f"memory:{filename}" for filename in memory_context)
    payload["allowed_source_refs"] = sorted(allowed_refs)
    payload["memory_context"] = memory_context
    payload["voice_context"] = {"role": role, "mode": mode}
    raw = chat(
        [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {
                "role": "user",
                "content": json.dumps(payload, ensure_ascii=False, sort_keys=True),
            },
        ],
        temperature=0.0,
        model_profile=model_profile,
        response_format={"type": "json_object"},
        task_name="structured_learning_closure",
    )
    data = _parse_object(raw)
    return normalize_structured_closure_result(data, structured_input=payload)


def normalize_structured_closure_result(
    value: dict[str, Any],
    *,
    structured_input: dict[str, Any],
) -> dict[str, Any]:
    allowed_refs = {
        str(item)
        for item in structured_input.get("allowed_source_refs", [])
        if str(item).strip()
    }
    final_evaluation = structured_input.get("final_pedagogy_evaluation")
    final_evaluation_id = (
        str(final_evaluation.get("id"))
        if isinstance(final_evaluation, dict) and final_evaluation.get("id")
        else ""
    )
    final_decision = (
        str(final_evaluation.get("final_decision"))
        if isinstance(final_evaluation, dict)
        else ""
    )
    candidates: list[dict[str, Any]] = []
    raw_candidates = value.get("candidates")
    if not isinstance(raw_candidates, list):
        raise ValueError("Structured closure result must contain candidates[]")
    seen_targets: set[str] = set()
    for raw in raw_candidates:
        if not isinstance(raw, dict):
            continue
        target = str(raw.get("target") or "").strip()
        content = str(raw.get("content") or "").strip()
        if target not in _ALLOWED_TARGETS or content in _NO_UPDATE_MARKERS:
            continue
        if target in seen_targets:
            continue
        source_refs = _valid_refs(raw.get("source_refs"), allowed_refs)
        if not source_refs or not _target_is_grounded(
            target,
            source_refs,
            final_evaluation_id=final_evaluation_id,
            final_decision=final_decision,
        ):
            continue
        evaluation_refs = _evaluation_refs(
            raw.get("evaluation_refs"),
            final_evaluation_id=final_evaluation_id,
        )
        if (
            final_evaluation_id
            and f"pedagogy_eval:{final_evaluation_id}" in source_refs
            and final_evaluation_id not in evaluation_refs
        ):
            evaluation_refs.append(final_evaluation_id)
        confidence = str(raw.get("confidence") or "low").strip().lower()
        if confidence not in _ALLOWED_CONFIDENCE:
            confidence = "low"
        has_committed_source = any(
            ref.startswith("learning_state.") or ref.startswith("memory:")
            for ref in source_refs
        )
        has_accepted_evaluation = (
            final_decision == "accept"
            and final_evaluation_id in evaluation_refs
        )
        if confidence == "high" and not (
            has_committed_source or has_accepted_evaluation
        ):
            confidence = "medium"
        learner_pending = target == "learner_profile" or raw.get("learner_pending") is True
        candidates.append(
            {
                "target": target,
                "content": content,
                "confidence": confidence,
                "source_refs": source_refs,
                "evaluation_refs": sorted(evaluation_refs),
                "learner_pending": learner_pending,
            }
        )
        seen_targets.add(target)
    return {
        "schema_version": STRUCTURED_CLOSURE_SCHEMA_VERSION,
        "summary_kind": str(structured_input.get("summary_kind") or "learning_summary"),
        "input_schema_version": str(structured_input.get("schema_version") or ""),
        "candidates": candidates,
        "candidate_count": len(candidates),
    }


def structured_candidates_to_memory_updates(
    generated: dict[str, Any],
) -> list[dict[str, Any]]:
    """Freeze candidate provenance into the MemoryRun payload."""

    updates: list[dict[str, Any]] = []
    candidates = generated.get("candidates")
    if not isinstance(candidates, list):
        return updates
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        target = str(candidate.get("target") or "")
        content = str(candidate.get("content") or "").strip()
        if target not in _ALLOWED_TARGETS or not content:
            continue
        updates.append(
            {
                "target": target,
                "content": content,
                "append": _ALLOWED_TARGETS[target],
                "learner_pending": target == "learner_profile"
                or candidate.get("learner_pending") is True,
                "confidence": str(candidate.get("confidence") or "low"),
                "source_refs": list(candidate.get("source_refs") or []),
                "evaluation_refs": list(candidate.get("evaluation_refs") or []),
                "provenance_schema_version": STRUCTURED_CLOSURE_SCHEMA_VERSION,
            }
        )
    return updates


def _parse_object(raw: str) -> dict[str, Any]:
    cleaned = strip_code_fences(raw)
    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise ValueError("Structured closure model returned invalid JSON") from exc
    if not isinstance(parsed, dict):
        raise ValueError("Structured closure model returned a non-object")
    return parsed


def _bounded_memory_context(memory_bundle: dict[str, str]) -> dict[str, str]:
    result: dict[str, str] = {}
    for filename in ("progress.md", "learner_profile.md", "current_focus.md"):
        content = str(memory_bundle.get(filename) or "").strip()
        if not content or content.startswith("[文件不存在"):
            continue
        result[filename] = (
            content
            if len(content) <= _MEMORY_CHAR_LIMIT
            else content[: _MEMORY_CHAR_LIMIT - 1].rstrip() + "…"
        )
    return result


def _valid_refs(value: Any, allowed_refs: set[str]) -> list[str]:
    if not isinstance(value, list):
        return []
    return sorted(
        {
            str(item)
            for item in value
            if str(item).strip() and str(item) in allowed_refs
        }
    )


def _evaluation_refs(value: Any, *, final_evaluation_id: str) -> list[str]:
    if not final_evaluation_id or not isinstance(value, list):
        return []
    return [final_evaluation_id] if final_evaluation_id in {str(item) for item in value} else []


def _target_is_grounded(
    target: str,
    source_refs: list[str],
    *,
    final_evaluation_id: str,
    final_decision: str,
) -> bool:
    refs = set(source_refs)
    accepted_eval_ref = bool(
        final_evaluation_id
        and final_decision == "accept"
        and f"pedagogy_eval:{final_evaluation_id}" in refs
    )
    if target == "progress":
        return accepted_eval_ref or bool(
            refs
            & {
                "learning_state.objective",
                "learning_state.confirmed_points",
                "learning_state.unresolved_gap",
                "learning_state.phase",
                "memory:progress.md",
            }
        )
    if target == "current_focus":
        return accepted_eval_ref or bool(
            refs
            & {
                "learning_state.objective",
                "learning_state.unresolved_gap",
                "learning_state.phase",
                "memory:current_focus.md",
                "memory:progress.md",
            }
        )
    return True
