from __future__ import annotations

from src.memory import extract_core_section
from src.mode_manager import RuntimeModes, load_runtime_modes

MODE_RULES = {
    "自动": "",
    "普通": "",
    "苏格拉底": "一次只追问一个关键问题，让用户自己推导结论。",
    "费曼": "先肯定，再指出漏洞，最后给出改进建议和评分。",
    "项目": "聚焦目标、边界、最小修改点、验收方式和风险。",
    "论文": "关注论点、证据、结构和表达，不直接代写。",
    "概念地图": "输出概念定义、层级关系、常见混淆和学习顺序。",
}

MEMORY_SELECTION = {
    "fast": ["index.md", "current_focus.md"],
    "light": ["index.md", "current_focus.md", "summary.md", "learner_profile.md"],
    "deep": [
        "index.md",
        "current_focus.md",
        "summary.md",
        "learner_profile.md",
        "progress.md",
        "project_context.md",
        "task_board.md",
    ],
    "archive": [
        "index.md",
        "current_focus.md",
        "summary.md",
        "learner_profile.md",
        "progress.md",
        "project_context.md",
        "task_board.md",
        "archive_summary.md",
        "agent.md",
        "system_detail.md",
    ],
}


def build_internal_mode_prompt(modes: RuntimeModes) -> str:
    parts = []
    if modes.safe_mode:
        parts.append("Safe mode is on. Do not suggest long-term memory writes.")
    if modes.memory_mode == "readonly":
        parts.append("Memory is read-only.")
    elif modes.memory_mode == "locked":
        parts.append("Memory is locked.")
    return "\n".join(parts)


def _select_memory(memory_bundle: dict[str, str], context_mode: str) -> list[tuple[str, str]]:
    selected = []
    for name in MEMORY_SELECTION.get(context_mode, MEMORY_SELECTION["light"]):
        content = memory_bundle.get(name, "")
        if not content or content.startswith("[missing:"):
            continue
        if context_mode == "light" and name == "learner_profile.md":
            content = extract_core_section(content)
        selected.append((name, content))
    return selected


def build_system_prompt(
    role_prompt: str,
    mode: str,
    memory_bundle: dict[str, str],
    relationship_mode: str = "standard",
    runtime_modes: RuntimeModes | None = None,
    context_mode: str = "light",
) -> str:
    if runtime_modes is None:
        runtime_modes = load_runtime_modes()

    parts = [role_prompt]
    mode_rule = MODE_RULES.get(mode, "")
    if mode_rule:
        parts.append(mode_rule)

    parts.append(f"Interaction mode: {relationship_mode}")

    internal = build_internal_mode_prompt(runtime_modes)
    if internal:
        parts.append(internal)

    for filename, content in _select_memory(memory_bundle, context_mode):
        parts.append(f"[Memory: {filename}]\n{content}")

    return "\n\n".join(parts)


def build_messages(
    user_input: str,
    role_prompt: str,
    mode: str,
    memory_bundle: dict[str, str],
    chat_history: list[dict] | None = None,
    relationship_mode: str = "standard",
    runtime_modes: RuntimeModes | None = None,
    context_mode: str = "light",
) -> list[dict]:
    if runtime_modes is None:
        runtime_modes = load_runtime_modes()

    messages = [
        {
            "role": "system",
            "content": build_system_prompt(
                role_prompt=role_prompt,
                mode=mode,
                memory_bundle=memory_bundle,
                relationship_mode=relationship_mode,
                runtime_modes=runtime_modes,
                context_mode=context_mode,
            ),
        }
    ]

    if chat_history:
        messages.extend(
            [{"role": msg["role"], "content": msg["content"]} for msg in chat_history[-8:]]
        )

    messages.append({"role": "user", "content": user_input})
    return messages
