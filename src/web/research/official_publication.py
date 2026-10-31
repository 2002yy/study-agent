"""Conservative publication seam for known-source queries.

Publishes server-parsed fields with exact source spans. Model prose is withheld;
no relevance label or unqualified model judge can authorize extra assertions.
"""
from __future__ import annotations

import hashlib
import re
from typing import Any
from urllib.parse import urlsplit

from src.web.research.official_resolver import official_plan, valid_candidate
from src.web.tool_evidence import evidence_tool_calls, tool_evidence_items

LABELS = {"project": "项目", "version": "版本", "distribution_uploaded_at": "PyPI 包首次上传时间",
          "release_date": "发布日期", "changes": "该版本变更", "paper_id": "arXiv ID",
          "title": "论文标题", "authors": "元数据列出的作者", "first_submission": "首次提交记录",
          "citation_date": "论文元数据日期", "official_positioning": "官方定位（原文）"}


ABSTENTION = (
    "本次尚未取得能逐事实支持所问内容的记录，暂不能给出已核实的结论。"
    "相邻版本、搜索摘要和模型记忆不作为支持。"
)


def _failed_reads(calls: list[dict[str, Any]]) -> int:
    """How many bounded read failures this turn already recorded."""

    from src.web.tool_evidence import tool_call_errors

    return len(tool_call_errors(calls))


def publish_official_fields(
    query: str,
    calls: list[dict[str, Any]],
    candidate: str,
    *,
    attachment_present: bool = False,
    screenshot_read: bool = True,
    strict: bool = False,
    tool_error: str = "",
) -> tuple[str, dict[str, Any]]:
    plan = official_plan(query)
    refs: list[dict[str, Any]] = []
    lines = []
    seen = set()
    for call in evidence_tool_calls(calls):
        result = call.get("result") or {}
        requested_url = str((call.get("arguments") or {}).get("url") or "")
        if not plan or not valid_candidate(query, requested_url) or result.get("method") != "official_metadata_http_v2":
            continue
        if urlsplit(str(result.get("url") or "")).hostname != urlsplit(requested_url).hostname:
            continue
        if plan.version and result.get("source_version") != plan.version:
            continue
        body = str(result.get("content") or "")
        digest = hashlib.sha256(body.encode()).hexdigest()
        if result.get("content_sha256") != digest or not re.fullmatch(r"[0-9a-f]{64}", str(result.get("transport_sha256") or "")):
            continue
        for field in result.get("official_fields") or []:
            key = field.get("field")
            value = field.get("value")
            start_span, end_span = field.get("start"), field.get("end")
            if key not in LABELS or key in seen or not isinstance(value, str) or not value.strip():
                continue
            if type(start_span) is not int or type(end_span) is not int or not 0 <= start_span < end_span <= len(body):
                continue
            if body[start_span:end_span] != f"{key}: {value}":
                continue
            seen.add(key)
            lines.append(f"- {LABELS[key]}：{value}")
            refs.append({"field": key, "value": value, "url": result.get("url"),
                         "content_sha256": digest, "transport_sha256": result["transport_sha256"],
                         "source_span": [start_span, end_span],
                         "quote": body[start_span:end_span],
                         "kind": "parsed_official_metadata_field"})
            if isinstance(field.get("source_binding"), dict):
                refs[-1]["source_binding"] = field["source_binding"]

    layered_audit: dict[str, Any] | None = None
    if refs:
        sources = list(dict.fromkeys(str(ref["url"]) for ref in refs))
        answer = "以下仅包含本次官方来源实际提供的字段：\n\n" + "\n".join(lines)
        answer += "\n\n来源：\n" + "\n".join(f"[官方记录]({url})" for url in sources)
        answer += "\n\n未取得的字段及性能比较尚未核实，不补写。"
        status = "field_backed"
    elif strict:
        answer = ABSTENTION
        status = "abstained"
    elif not candidate.strip() and (read_items := tool_evidence_items(calls)):
        # An actual read is not proof of relevance or factual support. Still,
        # calling it "no records" hides the progress this turn already made.
        excerpts = [
            (str(item.get("url") or ""), " ".join(str(item.get("snippet") or "").split())[:240])
            for item in read_items
            if str(item.get("snippet") or "").strip()
        ][:2]
        if excerpts:
            answer = (
                "本轮已读取以下来源，但尚未逐事实核实它们是否回答了研究问题；"
                "下列内容仅是网页摘录，不是已验证结论：\n\n"
                + "\n".join(f"- 来源：{url}\n  摘录：{excerpt}" for url, excerpt in excerpts)
                + "\n\n未确认的结论不依据搜索摘要或模型记忆补写。"
            )
            status = "read_excerpt_unverified"
        else:
            answer = ABSTENTION
            status = "abstained"
    else:
        # No field-backed record. Publish only statements that do not need a
        # source, withhold every specific claim, and state the gaps. A specific
        # fact is never relabelled as knowledge.
        from src.web.research.answer_layers import classify_draft, compose

        published, withheld = classify_draft(
            candidate,
            attachment_present=attachment_present,
            screenshot_read=screenshot_read,
        )
        gaps: list[str] = []
        # The trace already explains why reads failed; a failed call itself is
        # dropped from the sanitized calls, so this is the durable signal.
        if str(tool_error or "").strip():
            gaps.append(str(tool_error).strip()[:200])
        failed = _failed_reads(calls)
        if failed and not str(tool_error or "").strip():
            gaps.append(
                f"有 {failed} 个来源本次未能成功读取（例如 403 或空缓存），"
                "因此与这些来源相关的具体事实无法核对。"
            )
        if attachment_present and not screenshot_read:
            gaps.append("尚未读到图中信息，因此没有引用截图中的任何数值或文字。")
        layered = compose(published, withheld, gaps=gaps)
        layered_audit = layered.audit()
        if layered.knowledge_published:
            answer = layered.text
            status = "layered_without_evidence"
        else:
            answer = ABSTENTION
            status = "abstained"

    audit = {
        "schema_version": "official-field-publication-v2",
        "status": status,
        "layered": layered_audit,
        "candidate_answer_sha256": hashlib.sha256(candidate.encode()).hexdigest(),
        "published_answer_sha256": hashlib.sha256(answer.encode()).hexdigest(),
        "assertion_refs": refs,
        "model_prose_published": bool(layered_audit and layered_audit.get("knowledge_published")),
        "formal_semantic_label": False,
    }
    return answer, audit
