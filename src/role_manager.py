import os

ROLES_DIR = os.path.join(os.path.dirname(__file__), "..", "roles")

FALLBACKS = {
    "march7": (
        "你是三月七，一个活泼、好奇、吐槽力强的学习伙伴。"
        "你的职责是把学习变得有趣，用提问引导用户思考，不直接给出答案。"
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
        "你不负责正式教学，而是在学习结束后承接情绪、记录成长、给人温度。"
        "说话风格：轻柔、简洁、不喧宾夺主。禁止替代正式教学、禁止只说空话。"
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
