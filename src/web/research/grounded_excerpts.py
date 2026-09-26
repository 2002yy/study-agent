"""§40d grounded answer input: bounded, traceable excerpts per evidence row.

The generation prompt used to carry only ledger metadata (relation / strength /
anchor / url), so the model could not see what an evidence row actually says.
With ``RESEARCH_ANSWER_GROUNDED_INPUT=on`` every eligible row also gets a
bounded excerpt from the page that was actually read, preferring the anchor's
surroundings and falling back to the page head, under a per-row and a total
character cap. Pure functions; no model, no I/O.
"""

from __future__ import annotations

import os

GROUNDED_INPUT_ENV = "RESEARCH_ANSWER_GROUNDED_INPUT"
EXCERPT_RADIUS = 200
EXCERPT_MAX_CHARS = 400
EXCERPT_TOTAL_CHARS = 6000

# Output shape contract (§40d): keep the generation inside the binder's frozen
# segment budget with margin instead of raising that budget.
ANSWER_SHAPE_CONTRACT = (
    "输出形状约束：最多 12 个实质性段落/条目；每段只表达一个主要结论；"
    "引用（evidence_id 或 [web-n]）放在对应段内；不要把一个结论拆成大量短碎段；"
    "直接回答问题，不要输出研究流程说明。"
)


def grounded_input_enabled() -> bool:
    raw = (os.getenv(GROUNDED_INPUT_ENV) or "").strip().lower()
    return raw in {"1", "true", "on", "yes"}


def grounded_excerpt(
    content: str,
    *,
    anchor: str = "",
    radius: int = EXCERPT_RADIUS,
    max_chars: int = EXCERPT_MAX_CHARS,
) -> str:
    """Bounded excerpt around the anchor, else the page head."""

    text = " ".join(str(content or "").split())
    if not text:
        return ""
    if max_chars <= 0:
        return ""
    anchor = " ".join(str(anchor or "").split())
    start = -1
    if anchor:
        start = text.find(anchor)
        if start < 0 and len(anchor) > 40:
            start = text.find(anchor[:40])
    if start < 0:
        return text[:max_chars]
    begin = max(0, start - radius)
    end = min(len(text), start + len(anchor) + radius)
    excerpt = text[begin:end]
    if begin > 0:
        excerpt = "…" + excerpt
    if end < len(text):
        excerpt = excerpt + "…"
    if len(excerpt) > max_chars + 2:
        # Keep the closing boundary marker when the cap bites.
        excerpt = excerpt[: max_chars + 1] + "…"
    return excerpt


__all__ = [
    "ANSWER_SHAPE_CONTRACT",
    "EXCERPT_MAX_CHARS",
    "EXCERPT_RADIUS",
    "EXCERPT_TOTAL_CHARS",
    "GROUNDED_INPUT_ENV",
    "grounded_excerpt",
    "grounded_input_enabled",
]
