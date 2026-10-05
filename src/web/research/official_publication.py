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
from src.web.tool_evidence import evidence_tool_calls

LABELS = {"project": "项目", "version": "版本", "distribution_uploaded_at": "PyPI 包首次上传时间",
          "release_date": "发布日期", "changes": "该版本变更", "paper_id": "arXiv ID",
          "title": "论文标题", "authors": "元数据列出的作者", "first_submission": "首次提交记录",
          "citation_date": "论文元数据日期", "official_positioning": "官方定位（原文）"}


def publish_official_fields(query: str, calls: list[dict[str, Any]], candidate: str) -> tuple[str, dict[str, Any]]:
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
            start, end = field.get("start"), field.get("end")
            if key not in LABELS or key in seen or not isinstance(value, str) or not value.strip():
                continue
            if type(start) is not int or type(end) is not int or not 0 <= start < end <= len(body):
                continue
            if body[start:end] != f"{key}: {value}":
                continue
            seen.add(key)
            lines.append(f"- {LABELS[key]}：{value}")
            refs.append({"field": key, "value": value, "url": result.get("url"),
                         "content_sha256": digest, "transport_sha256": result["transport_sha256"],
                         "source_span": [start, end], "quote": body[start:end],
                         "kind": "parsed_official_metadata_field"})
            if isinstance(field.get("source_binding"), dict):
                refs[-1]["source_binding"] = field["source_binding"]
    if refs:
        sources = list(dict.fromkeys(str(ref["url"]) for ref in refs))
        answer = "以下仅包含本次官方来源实际提供的字段：\n\n" + "\n".join(lines)
        answer += "\n\n来源：" + "；".join(f"[官方记录]({url})" for url in sources)
        answer += "\n\n未取得的字段及性能比较尚未核实，不补写。"
    else:
        answer = "本次尚未取得能逐事实支持所问内容的记录，暂不能给出已核实的结论。相邻版本、搜索摘要和模型记忆不作为支持。"
    audit = {"schema_version": "official-field-publication-v2", "status": "field_backed" if refs else "abstained",
             "candidate_answer_sha256": hashlib.sha256(candidate.encode()).hexdigest(),
             "published_answer_sha256": hashlib.sha256(answer.encode()).hexdigest(),
             "assertion_refs": refs, "model_prose_published": False, "formal_semantic_label": False}
    return answer, audit
