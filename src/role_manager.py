import os
import re

ROLES_DIR = os.path.join(os.path.dirname(__file__), "..", "roles")

FALLBACKS = {
    "march7": (
        "你是三月七，一个活泼、好奇、吐槽力强的学习伙伴。"
        "你的偏好是把学习变得有趣，用提问引导用户思考；用户要求直接回答时也要完整回答。"
        "说话风格：元气、直接、偶尔吐槽。禁止过度娱乐化复杂问题。"
    ),
    "keqing": (
        "你是刻晴，一个严格、清醒、目标感强的任务管理者。"
        "你的职责是收束边界、防止跑题，把模糊目标压缩为可执行步骤。"
        "说话风格：直接、高效、不绕弯。禁止变成单纯训话。"
    ),
    "nahida": (
        "你是纳西妲，一个智慧、安静、善于类比的本质提炼者。"
        "你的职责是帮用户看清概念背后的结构，建立知识之间的联系。"
        "说话风格：温和、善用比喻、言简意赅。禁止空泛玄学、只给比喻不给落脚点。"
    ),
    "firefly": (
        "你是流萤，一个安静、坚韧、温柔的陪伴者。"
        "你默认偏向复盘和陪伴；用户直接提问时，也要温柔、准确地完成教学或项目分析。"
        "说话风格：轻柔、简洁、不喧宾夺主。回答要有具体锚点，避免只说空话。"
    ),
}

ROLE_IDS = list(FALLBACKS.keys())


def list_roles() -> list[str]:
    return list(ROLE_IDS)


def load_role(role_id: str) -> str:
    if role_id not in ROLE_IDS:
        available = ", ".join(ROLE_IDS)
        raise ValueError(f"未知角色: {role_id}。可用角色: {available}")

    filepath = os.path.join(ROLES_DIR, f"{role_id}.md")
    if os.path.isfile(filepath):
        with open(filepath, "r", encoding="utf-8") as f:
            return f.read().strip()

    return FALLBACKS[role_id]


def _split_markdown_sections(markdown: str) -> dict[str, str]:
    matches = list(re.finditer(r"^##\s+(.+)$", markdown, flags=re.MULTILINE))
    if not matches:
        return {"title": markdown.strip()}
    sections = {"title": markdown[: matches[0].start()].strip()}
    for index, match in enumerate(matches):
        start = match.start()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(markdown)
        sections[match.group(1).strip()] = markdown[start:end].strip()
    return sections


def _select_atmosphere_section(section: str, relationship_mode: str) -> str:
    if not section:
        return ""
    labels = {
        "standard": "standard",
        "warm": "warm",
        "close": "close",
    }
    selected = labels.get(relationship_mode, "standard")
    pattern = re.compile(r"^###\s+(.+)$", flags=re.MULTILINE)
    matches = list(pattern.finditer(section))
    if not matches:
        return section
    for index, match in enumerate(matches):
        title = match.group(1)
        if selected not in title:
            continue
        start = match.start()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(section)
        return "## 当前氛围\n\n" + section[start:end].strip()
    return ""


def _has_meaningful_dynamic_record(section: str) -> bool:
    if not section:
        return False
    for raw_line in section.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        cleaned = line.lstrip("-*>0123456789.、 \t").strip()
        if not cleaned:
            continue
        if cleaned in {"暂无", "暂无。", "暂无，将在多轮对话中逐步形成。"}:
            continue
        return True
    return False


def build_role_prompt(
    role_id: str,
    *,
    scene: str = "single",
    relationship_mode: str = "standard",
) -> str:
    """Build the role prompt for generation without injecting unrelated scenes."""
    raw = load_role(role_id)
    sections = _split_markdown_sections(raw)
    selected_keys = [
        "1. 核心定位",
        "2. 性格层次",
        "8. 禁止跑偏",
        "9. 动态记录区",
    ]
    if scene == "group":
        selected_keys.extend(["6. 微信群风格", "7. 与其他角色的互动方式"])
    else:
        selected_keys.extend(["3. 教学风格", "4. 项目推进风格", "5. 论文修改风格"])

    parts = [sections.get("title", "")]
    for key in selected_keys:
        content = sections.get(key, "")
        if key == "9. 动态记录区" and not _has_meaningful_dynamic_record(content):
            continue
        if content:
            parts.append(content)

    atmosphere = _select_atmosphere_section(
        sections.get("10. 氛围差异化", ""),
        relationship_mode,
    )
    if atmosphere:
        parts.append(atmosphere)

    return "\n\n".join(part for part in parts if part).strip() or raw
