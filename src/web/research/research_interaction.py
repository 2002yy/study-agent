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
from src.web.tool_evidence import _public_url
from src.web.research.interim_analysis import analysis_sources, interim_revision, validate_interim_analysis


def _source_excerpts(run: Any, deep: Mapping[str, Any]) -> list[dict[str, str]]:
    """Project live Deep notes backed by successful reads, never search snippets.

    These are attributed page excerpts, not synthesized or verified conclusions.
    A new snapshot removes notes invalidated by steering; no authority is written.
    """
    records = {}
    for record in run.selected_sources:
        if not isinstance(record, dict):
            continue
        assessment = record.get("assessment") or {}
        item = record.get("item") or {}
        if isinstance(assessment, dict) and isinstance(item, dict):
            records[str(assessment.get("url") or item.get("url") or "")] = record
    excerpts: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    notes = deep.get("notes")
    for note in reversed(notes[-80:] if isinstance(notes, list) else []):
        if not isinstance(note, dict) or note.get("superseded"):
            continue
        requested_url = str(note.get("url") or "")
        record = records.get(requested_url, {})
        read = record.get("read") or {}
        assessment = record.get("assessment") or {}
        if not isinstance(read, dict) or not isinstance(assessment, dict):
            continue
        if assessment.get("worth_reading") is not True or read.get("status") != "read":
            continue
        if str(read.get("ok")).lower() != "true" or read.get("error") or read.get("answer_eligible") is False:
            continue
        if read.get("requested_url") and read["requested_url"] != requested_url:
            continue
        try:
            url = _public_url(read.get("url") or requested_url) if _public_url(requested_url) else ""
        except ValueError:
            continue
        text = " ".join(str(note.get("facts") or "").split())[:280]
        question = " ".join(str(note.get("sub_question") or "").split())[:160]
        body = " ".join(str(read.get("content") or read.get("readme") or "").split())
        if not url or (url, question) in seen or not text or text not in body:
            continue
        seen.add((url, question))
        excerpts.append({
            "id": f"{run.id}:excerpt:" + hashlib.sha256(f"{url}:{text}:{question}".encode()).hexdigest()[:20],
            "url": url, "title": str(note.get("title") or url)[:160], "text": text,
            "requested_url": requested_url,
            "kind": "source_excerpt",
            "question": question,
        })
    return list(reversed(excerpts))


def _reading_material(run: Any, deep: Mapping[str, Any]) -> dict[str, Any]:
    """Organize excerpts by actual plan questions; body coverage is not support."""
    excerpts = _source_excerpts(run, deep)
    plan = deep.get("plan")
    corrections = deep.get("corrections")
    old_terms = [str(change.get("old") or "").casefold() for change in
                 (corrections if isinstance(corrections, list) else []) if isinstance(change, dict)]
    excerpts = [excerpt for excerpt in excerpts if not any(
        term and term in excerpt["question"].casefold() for term in old_terms
    )]
    questions: list[str] = []
    for task in plan[:12] if isinstance(plan, list) else []:
        if not isinstance(task, dict) or task.get("status") in {"superseded", "cancelled"}:
            continue
        question = " ".join(str(task.get("sub_question") or "").split())[:160]
        if question and question not in questions and not any(term and term in question.casefold() for term in old_terms):
            questions.append(question)
    # Reserve one slot per question before filling spare slots. A comparison
    # must not hide one side simply because the other side has more sources.
    selected: list[dict[str, str]] = []
    for question in questions:
        matching = [excerpt for excerpt in excerpts if excerpt["question"] == question]
        if matching:
            selected.append(matching[-1])
        if len(selected) == 3:
            break
    for excerpt in reversed(excerpts):
        if len(selected) == 3:
            break
        if excerpt not in selected:
            selected.append(excerpt)
    covered = {excerpt["question"] for excerpt in excerpts}
    return {
        "findings": selected,
        "reading_gaps": [question for question in questions if question not in covered][:3],
        "interim_analysis": _interim_projection(deep, excerpts),
    }


def _interim_projection(deep: Mapping[str, Any], excerpts: list[dict[str, str]]) -> dict[str, Any] | None:
    candidate = deep.get("interim_analysis")
    if not isinstance(candidate, dict) or candidate.get("revision") != interim_revision(dict(deep)):
        return None
    sources = analysis_sources([{
        "url": excerpt["requested_url"], "facts": excerpt["text"],
        "sub_question": excerpt["question"], "title": excerpt["title"],
    } for excerpt in excerpts])
    analysis = validate_interim_analysis(candidate, sources)
    if analysis is None:
        return None
    canonical = {source["source_id"]: next((
        excerpt["url"] for excerpt in excerpts
        if excerpt["requested_url"] == source["url"] and excerpt["question"] == source["question"]
    ), source["url"]) for source in sources}
    return {"status": "provisional", "text": analysis["text"], "citations": [{
        "url": canonical[citation["source_id"]], "title": citation["title"], "quote": citation["quote"],
    } for citation in analysis["citations"]]}


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


def deep_steering_status(item: Mapping[str, Any], *, active: bool) -> str:
    """Map one durable receipt to its honest user-visible state.

    ``applied`` means the constraint entered the authoritative plan (the plan
    was revised), while ``executing`` additionally requires a real search/read
    action to have happened.  A terminal run whose constraint was incorporated
    but never executed is still ``applied`` — the run-level partial warning, not
    the receipt, carries the "not executed" fact.
    """

    executed = item.get("executed_in_round") is not None
    incorporated = item.get("incorporated_in_round") is not None
    if executed and active:
        return "executing"
    if executed or incorporated:
        return "applied"
    return "pending" if active else "late"


def interaction_event(run: Any) -> dict[str, Any]:
    context = run.research_context if isinstance(run.research_context, dict) else {}
    deep = context.get("deep") or {}
    if not isinstance(deep, dict):
        deep = {}
    active = run.status in {"pending", "running"}
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
                "status": deep_steering_status(item, active=active),
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
        **_reading_material(run, deep),
        "budget_extension": "configured"
        if isinstance(deep.get("incremental_budget"), dict)
        else "not_configured",
    }
