from __future__ import annotations

from src.pedagogy.types import KnowledgeKind

EXTERNAL_FACT_MARKERS = (
    "哪一年", "何时提出", "谁提出", "发表时间", "发布日期", "论文结果",
    "实验数据", "具体数值", "法律条款", "api 名称", "api名称", "版本",
)
DIAGNOSTIC_MARKERS = ("报错", "异常", "bug", "故障", "排查", "为什么失败")
PROCEDURAL_MARKERS = ("怎么做", "步骤", "实现", "配置", "部署", "操作")


def classify_knowledge(user_input: str) -> KnowledgeKind:
    text = user_input.lower()
    if any(marker in text for marker in DIAGNOSTIC_MARKERS):
        return "diagnostic"
    if any(marker in text for marker in EXTERNAL_FACT_MARKERS):
        return "empirical"
    if any(marker in text for marker in PROCEDURAL_MARKERS):
        return "procedural"
    if any(marker in text for marker in ("术语", "命名", "约定", "定义为")):
        return "conventional"
    return "derivable"
