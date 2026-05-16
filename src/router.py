from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from src.mode_manager import RuntimeModes
from src.model_stats import suggest_model_by_rules
from src.log_utils import get_logger

Role = Literal["march7", "keqing", "nahida", "firefly"]
Mode = Literal["普通", "苏格拉底", "费曼", "项目", "论文", "概念地图"]
Model = Literal["flash", "pro"]

_YAML_CONFIG = Path(__file__).resolve().parent.parent / "config" / "routing_rules.yaml"
_MD_FALLBACK = Path(__file__).resolve().parent.parent / "templates" / "routing_rules.md"

FALLBACK_RULES = [
    (["概念图", "关系图", "知识结构", "概念关系", "对比"], "nahida", "概念地图", "pro", "概念梳理", 60),
    (["实现", "修改", "代码", "bug", "报错", "测试", "方案", "部署", "配置"], "keqing", "项目", "pro", "项目推进", 90),
    (["我来讲", "你听我解释", "检查我理解", "复述"], "nahida", "费曼", "pro", "费曼复述", 70),
    (["论文", "摘要", "章节", "参考文献", "论点"], "keqing", "论文", "pro", "论文修改", 80),
    (["累", "复盘", "收尾", "简单总结", "休息"], "firefly", "普通", "flash", "复盘收尾", 40),
    (["入门", "开始学", "先问我", "新手", "零基础"], "march7", "苏格拉底", "flash", "入门引导", 50),
]

FALLBACK_DEFAULT: tuple[str, str, str, str] = ("nahida", "普通", "flash", "无匹配规则，使用默认")


@dataclass
class RoutingConfig:
    rules: list
    default_role: str
    default_mode: str
    default_model: str
    default_reason: str


def _load_rules_from_yaml() -> RoutingConfig | None:
    if not _YAML_CONFIG.is_file():
        return None
    try:
        import yaml

        data = yaml.safe_load(_YAML_CONFIG.read_text(encoding="utf-8"))
        rules = []
        for rule in data.get("rules", []):
            rules.append(
                (
                    rule.get("keywords", []),
                    rule.get("role", ""),
                    rule.get("mode", ""),
                    rule.get("model", ""),
                    rule.get("reason", ""),
                    rule.get("priority", 50),
                )
            )
        default_cfg = data.get("default", {})
        return RoutingConfig(
            rules=rules or [],
            default_role=default_cfg.get("role", "nahida"),
            default_mode=default_cfg.get("mode", "普通"),
            default_model=default_cfg.get("model", "flash"),
            default_reason=default_cfg.get("reason", "无匹配规则，使用默认"),
        )
    except Exception as e:
        get_logger().warning("YAML routing rules load failed: %s", e)
        return None


def _load_rules_from_markdown(text: str) -> list:
    rules = []
    blocks = re.split(r"\n## rule\n", text)
    for block in blocks[1:]:
        kw_match = re.search(r"keywords:\s*(.+)", block)
        role_match = re.search(r"role:\s*(\S+)", block)
        mode_match = re.search(r"mode:\s*(\S+)", block)
        model_match = re.search(r"model:\s*(\S+)", block)
        reason_match = re.search(r"reason:\s*(.+)", block)
        pri_match = re.search(r"priority:\s*(\d+)", block)
        if all([kw_match, role_match, mode_match, model_match, reason_match]):
            priority = int(pri_match.group(1)) if pri_match else 50
            rules.append(
                (
                    [kw.strip() for kw in kw_match.group(1).split(",")],
                    role_match.group(1),
                    mode_match.group(1),
                    model_match.group(1),
                    reason_match.group(1),
                    priority,
                )
            )
    return rules


def _load_rules() -> list:
    yaml_cfg = _load_rules_from_yaml()
    if yaml_cfg and yaml_cfg.rules:
        return yaml_cfg.rules
    if _MD_FALLBACK.is_file():
        parsed = _load_rules_from_markdown(_MD_FALLBACK.read_text(encoding="utf-8"))
        if parsed:
            return parsed
    return FALLBACK_RULES


def load_routing_config() -> RoutingConfig:
    yaml_cfg = _load_rules_from_yaml()
    if yaml_cfg:
        return yaml_cfg
    return RoutingConfig(
        rules=_load_rules(),
        default_role=FALLBACK_DEFAULT[0],
        default_mode=FALLBACK_DEFAULT[1],
        default_model=FALLBACK_DEFAULT[2],
        default_reason=FALLBACK_DEFAULT[3],
    )


def _match(input_text: str, rules: list | None = None) -> tuple[Role, Mode, Model, str, list[str], int] | None:
    if rules is None:
        rules = _load_rules()
    text = input_text.lower()
    best = None
    best_priority = -1
    best_count = 0
    for keywords, role, mode, model, reason, *_priority in rules:
        priority = _priority[0] if _priority else 50
        matched = [kw for kw in keywords if kw in text]
        if not matched:
            continue
        if (priority > best_priority
                or (priority == best_priority and len(matched) > best_count)):
            best = (role, mode, model, reason, matched, len(matched))
            best_priority = priority
            best_count = len(matched)
    return best


def route_request(
    user_input: str,
    selected_role: str,
    selected_mode: str,
    selected_model: str,
    runtime_modes: RuntimeModes,
) -> dict:
    routing_config = load_routing_config()
    mode_is_auto = selected_mode in ("auto", "自动")
    matched = _match(user_input, routing_config.rules)
    default_role: Role = routing_config.default_role  # type: ignore[assignment]
    default_mode: Mode = routing_config.default_mode  # type: ignore[assignment]
    default_model: Model = routing_config.default_model  # type: ignore[assignment]
    default_reason = routing_config.default_reason

    if matched:
        auto_role, auto_mode, auto_model, auto_reason, hit_kw, kw_count = matched
        confidence = "high" if kw_count >= 2 else "medium"
    else:
        auto_role, auto_mode, auto_model, auto_reason = (
            default_role,
            default_mode,
            default_model,
            default_reason,
        )
        hit_kw = []
        confidence = "low"

    llm_used = False
    llm_valid = False
    if confidence == "low" and runtime_modes.allow_llm_router:
        has_auto = (
            selected_role == "auto"
            or mode_is_auto
            or selected_model == "auto"
        )
        if has_auto:
            try:
                from src.llm_router import route_by_llm

                llm_result = route_by_llm(user_input)
                if llm_result:
                    llm_used = True
                    llm_valid = True
                    auto_role = llm_result["role"]
                    auto_mode = llm_result["mode"]
                    auto_model = llm_result["model_profile"]
                    auto_reason = llm_result.get("reason", auto_reason)
                    confidence = "medium"
                    hit_kw = ["[LLM]"]
            except Exception as e:
                get_logger().warning("LLM router fallback failed: %s", e)
                pass

    # Model selection with performance_mode awareness
    if selected_model != "auto":
        model_profile = selected_model
    elif runtime_modes.performance_mode == "deep":
        model_profile = "pro"
    elif runtime_modes.performance_mode == "fast":
        high_risk_kw = ["论文", "代码", "报错", "架构", "机制"]
        if any(kw in user_input.lower() for kw in high_risk_kw):
            model_profile = "pro"
        else:
            model_profile = "flash"
    else:
        # standard: matched rule's model takes priority, fallback to rule-based suggestion
        rule_model = suggest_model_by_rules(user_input, runtime_modes.performance_mode)
        model_profile = auto_model or rule_model

    role = selected_role if selected_role != "auto" else auto_role
    mode = selected_mode if not mode_is_auto else auto_mode

    reasons = []
    reasons.append(f"role={role}")
    reasons.append(f"mode={mode}")
    reasons.append(f"model={model_profile}")
    reasons.append(f"source={auto_reason}")

    return {
        "role": role,
        "mode": mode,
        "model_profile": model_profile,
        "reason": " | ".join(reasons),
        "manual_override": (
            selected_role != "auto" or not mode_is_auto or selected_model != "auto"
        ),
        "confidence": confidence,
        "matched_keywords": hit_kw,
        "llm_router_used": llm_used,
        "llm_router_valid": llm_valid,
    }
