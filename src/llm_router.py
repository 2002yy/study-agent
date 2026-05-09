"""LLM router fallback for low-confidence hybrid routing only."""

from __future__ import annotations

import json
import time

from src.llm_client import ModelProfile, chat
from src.model_stats import estimate_tokens, record_llm_router_call

VALID_ROLES = {"march7", "keqing", "nahida", "firefly"}
VALID_MODES = {"普通", "苏格拉底", "费曼", "项目", "论文", "概念地图"}
VALID_MODELS = {"flash", "pro"}
VALID_CONFIDENCE = {"high", "medium", "low"}

PROMPT = """你是一个路由器，只负责判断用户请求更适合哪个学习配置。
只返回 JSON，不要解释。

可选 role:
- march7: 入门、轻互动、启动困难
- keqing: 项目、代码、执行、边界
- nahida: 本质、机制、概念梳理
- firefly: 复盘、收尾、疲惫陪伴

可选 mode:
- 普通
- 苏格拉底
- 费曼
- 项目
- 论文
- 概念地图

可选 model_profile:
- flash
- pro

输出格式:
{"role":"nahida","mode":"普通","model_profile":"flash","confidence":"medium","reason":"..."}
"""


def route_by_llm(user_input: str, model_profile: ModelProfile = "flash") -> dict | None:
    """Return an LLM-based routing dict or None on failure."""
    if not user_input.strip():
        return None

    messages = [
        {"role": "system", "content": PROMPT},
        {"role": "user", "content": f"用户请求: {user_input}"},
    ]

    try:
        t0 = time.time()
        raw = chat(messages, temperature=0.0, model_profile=model_profile)
        elapsed = time.time() - t0
        record_llm_router_call(elapsed, estimate_tokens(user_input) + 100)
    except Exception:
        return None

    cleaned = raw.strip()
    if cleaned.startswith("```"):
        lines = [line for line in cleaned.splitlines() if not line.startswith("```")]
        cleaned = "\n".join(lines)

    try:
        data = json.loads(cleaned)
    except Exception:
        return None

    if (
        data.get("role") not in VALID_ROLES
        or data.get("mode") not in VALID_MODES
        or data.get("model_profile") not in VALID_MODELS
        or data.get("confidence") not in VALID_CONFIDENCE
    ):
        return None

    return {
        "role": data["role"],
        "mode": data["mode"],
        "model_profile": data["model_profile"],
        "confidence": data.get("confidence", "low"),
        "reason": data.get("reason", "LLM Router fallback"),
        "router_type": "llm",
    }
