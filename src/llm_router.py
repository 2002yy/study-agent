"""LLM router fallback for low-confidence hybrid routing only."""

from __future__ import annotations

import json
import time

from src.llm_client import ModelProfile, chat
from src.model_stats import estimate_tokens, record_llm_router_call
from src.text_utils import strip_code_fences
from src.log_utils import get_logger

VALID_ROLES = {"march7", "keqing", "nahida", "firefly"}
VALID_MODES = {"普通", "苏格拉底", "费曼", "项目"}
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
- 普通：用户希望获得解释、答案、步骤、分析或建议。即使包含“为什么、原理、本质”，
  只要没有明确要求自行推导，通常也选择普通。
- 苏格拉底：用户明确希望通过问题、反例、线索和逐步引导自行形成理解，
  或当前对话已经处于持续的再发现过程。不要仅因用户问“为什么”就选择苏格拉底。
- 费曼：用户正在用自己的语言解释知识，希望检查理解、发现缺口并重新表达。
- 项目：用户主要目标是实施、代码、排错、测试、方案选择或交付。

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
        raw = chat(
            messages,
            temperature=None,
            model_profile=model_profile,
            task_name="llm_router",
        )
        elapsed = time.time() - t0
        record_llm_router_call(elapsed, estimate_tokens(user_input) + 100, model_profile)
    except Exception as e:
        get_logger().warning("llm_router chat failed: %s", e)
        return None

    cleaned = strip_code_fences(raw)

    try:
        data = json.loads(cleaned)
    except Exception as e:
        get_logger().warning("llm_router JSON parse failed: %s", e)
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
