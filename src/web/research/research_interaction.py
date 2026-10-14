"""Display-only projection of durable research work and steering receipts.

No model call, evidence admission, or answer publication is performed here.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any
import hashlib

from src.web.research.steering import (
    active_steering_entries,
    is_active_claim_engine_context,
)


def steering_supported(context: Mapping[str, Any]) -> bool:
    return (
        is_active_claim_engine_context(context)
        or context.get("research_mode") == "deep"
    )


def steering_answer_instruction(calls: Any, original: str) -> str:
    """Carry user task changes into synthesis separately from external evidence."""
    metadata: dict[str, Any] = next(
        (
            call.get("result", {})
            for call in calls
            if call.get("name") == "research_steering"
        ),
        {},
    )
    if metadata.get(
        "authority"
    ) != "user_task_requirements_not_evidence" or not metadata.get("entries"):
        return original
    text = "\n".join(
        f"- {'已执行补查' if entry.get('executed') else '本轮未执行，不得声称已完成'}：{entry.get('content', '')}"
        for entry in metadata["entries"]
    )
    return f"{original}\n\n用户在本轮研究期间更新了任务要求（不是事实证据）：\n当前问题：{metadata.get('effective_query', '')}\n{text}\n回答必须遵守更新后的问题；资料不足的新增范围必须明确说明。".strip()


def interaction_event(run: Any) -> dict[str, Any]:
    context = run.research_context if isinstance(run.research_context, dict) else {}
    deep = context.get("deep") or {}
    if not isinstance(deep, dict):
        deep = {}
    receipts = [
        {"id": item["id"], "content": item.get("content", ""), "status": item["status"]}
        for item in active_steering_entries(context)
    ]
    for item in deep.get("steering", []):
        if not isinstance(item, dict):
            continue
        receipts.append(
            {
                "id": item.get("id")
                or f"{item.get('received_at', '')}:{item.get('content', '')}",
                "content": item.get("content", ""),
                "status": (
                    "executing"
                    if item.get("executed_in_round") is not None
                    and run.status in {"pending", "running"}
                    else "applied"
                    if item.get("executed_in_round") is not None
                    else "late"
                    if run.status not in {"pending", "running"}
                    else "applied"
                    if item.get("incorporated_in_round") is not None
                    else "pending"
                ),
            }
        )
    blocks: list[dict[str, str]] = []
    for step in deep.get("steps", []):
        if not isinstance(step, dict) or not step.get("text"):
            continue
        # Existing Deep steps are already durable, bounded process summaries.
        blocks.append(
            {
                "block_id": f"{run.id}:step:"
                + hashlib.sha256(
                    f"{step.get('at', '')}:{step.get('kind', '')}:{step['text']}".encode()
                ).hexdigest()[:20],
                "text": str(step["text"])[:300],
            }
        )
    queries = len(run.query_attempts)
    sources = len(run.selected_sources)
    text = {
        "searching": f"正在检索资料，已执行 {queries} 次查询；找到的链接还需要阅读和核对。",
        "assessing": f"正在筛选 {sources} 个候选来源，确认哪些值得继续阅读。",
        "reading": "正在读取候选来源的正文；读取成功仍不代表已支持结论。",
        "synthesizing": "正在整理已读资料，检查差异和仍缺少的信息。",
        "gating": "正在核对答案与来源，尚未核验的内容不会作为正式结论发布。",
        "cancelled": "研究已停止，已完成的过程记录保留。",
        "failed": "本轮研究未能完成，请查看错误或补充更明确的条件。",
        "completed": "本轮研究执行已结束，结论与来源以回答中的核验结果为准。",
    }.get(run.stage)
    if text:
        blocks.append(
            {"block_id": f"{run.id}:{run.stage}:{queries}:{sources}", "text": text}
        )
    return {
        "steering_supported": steering_supported(context),
        "steering": receipts,
        "narration": blocks[-12:],
        "budget_extension": "configured"
        if isinstance(deep.get("incremental_budget"), dict)
        else "not_configured",
    }
