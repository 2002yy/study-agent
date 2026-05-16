import json
from pathlib import Path
from src.llm_client import chat, ModelProfile
from src.safe_writer import safe_write_text, append_text_safely
from src.mode_manager import load_runtime_modes, is_memory_write_allowed
from src.text_utils import strip_code_fences

ROOT = Path(__file__).resolve().parent.parent
TEMPLATE_FILE = ROOT / "templates" / "wechat_memory_extract.md"
CANDIDATES_FILE = ROOT / "memory" / "pending_updates" / "wechat_memory_candidates.md"
CANDIDATES_JSON = ROOT / "memory" / "pending_updates" / "wechat_memory_candidates.json"
GROUP_FILE = ROOT / "chat" / "wechat_group.md"

CANDIDATE_KEYS = [
    "summary_candidates",
    "progress_candidates",
    "current_focus_candidates",
    "learner_profile_candidates",
    "revision_notes_candidates",
    "session_archive_candidates",
]


def _load_prompt() -> str:
    if TEMPLATE_FILE.is_file():
        return TEMPLATE_FILE.read_text(encoding="utf-8").strip()
    return "从微信群聊记录中提取长期记忆候选，输出JSON。"


def extract_memory_candidates(
    wechat_content: str = "",
    memory_bundle: dict[str, str] | None = None,
    model_profile: ModelProfile = "pro",
) -> dict:
    empty = {k: [] for k in CANDIDATE_KEYS}

    modes = load_runtime_modes()
    if not modes.memory_capture_enabled:
        return empty

    if not wechat_content and GROUP_FILE.is_file():
        raw = GROUP_FILE.read_text(encoding="utf-8")
        last_lines = raw.split("\n")[-80:]
        wechat_content = "\n".join(last_lines)

    if not wechat_content:
        return empty

    prompt = _load_prompt()
    context = [prompt]

    if memory_bundle:
        for key, label in [("current_focus.md", "当前焦点"), ("summary.md", "摘要")]:
            content = memory_bundle.get(key, "")
            if content and not content.startswith("[文件不存在"):
                context.append(f"\n【参考：{label}】\n{content[:300]}")

    messages = [
        {"role": "system", "content": "\n".join(context)},
        {
            "role": "user",
            "content": f"【微信群聊内容】\n{wechat_content[:4000]}\n\n请提取记忆候选，输出纯JSON。",
        },
    ]

    raw = chat(messages, temperature=0.3, model_profile=model_profile)
    cleaned = strip_code_fences(raw)

    try:
        data = json.loads(cleaned)
    except Exception:
        return {k: [] for k in CANDIDATE_KEYS}

    result = {}
    for key in CANDIDATE_KEYS:
        candidates = data.get(key, [])
        if not isinstance(candidates, list):
            candidates = []
        result[key] = candidates
    return result


def format_candidates_markdown(candidates: dict) -> str:
    lines = ["# 待确认的微信群记忆候选\n"]
    lines.append("> 由微信记忆提取生成。所有候选需人工确认后才移入正式 memory 文件。\n")

    labels = {
        "summary_candidates": "summary_candidates",
        "progress_candidates": "progress_candidates",
        "current_focus_candidates": "current_focus_candidates",
        "learner_profile_candidates": "learner_profile_candidates",
        "revision_notes_candidates": "revision_notes_candidates",
        "session_archive_candidates": "session_archive_candidates",
    }
    for key in CANDIDATE_KEYS:
        items = candidates.get(key, [])
        lines.append(f"## {labels[key]}")
        if not items:
            lines.append("暂无\n")
        else:
            for item in items:
                target = item.get("target", "")
                content = item.get("content", "")
                reason = item.get("reason", "")
                source = item.get("source", "")
                risk = item.get("risk", "")
                lines.append(f"- **target**: {target}")
                lines.append(f"  - content: {content}")
                lines.append(f"  - reason: {reason}")
                lines.append(f"  - source: {source}")
                lines.append(f"  - risk: {risk}")
                lines.append("")
    return "\n".join(lines)


def save_candidates(candidates: dict) -> None:
    md = format_candidates_markdown(candidates)
    safe_write_text(CANDIDATES_FILE, md)
    safe_write_text(
        CANDIDATES_JSON, json.dumps(candidates, ensure_ascii=False, indent=2)
    )


def load_candidates() -> dict:
    if CANDIDATES_JSON.is_file():
        try:
            data = json.loads(CANDIDATES_JSON.read_text(encoding="utf-8"))
            result = {}
            for key in CANDIDATE_KEYS:
                result[key] = data.get(key, [])
            return result
        except Exception:
            pass
    return {k: [] for k in CANDIDATE_KEYS}


def append_manual_memory_candidate(speaker: str, text: str) -> dict:
    candidates = load_candidates()
    item = {
        "content": f"[来自群聊引用] {speaker}: {text}",
        "reason": "用户手动引用",
        "source": "wechat_manual_citation",
        "risk": "manual",
    }
    candidates.setdefault("session_archive_candidates", []).append(item)
    save_candidates(candidates)
    return candidates


def apply_candidate_to_memory(
    key: str, index: int, relationship_mode: str = "standard"
) -> str:
    modes = load_runtime_modes()

    if not is_memory_write_allowed(modes):
        if modes.safe_mode:
            return "[安全模式] 禁止写入长期记忆"
        if modes.memory_mode == "locked":
            return "[锁定模式] 长期记忆已锁定"
        return "[只读模式] 不允许写入"

    candidates = load_candidates()
    items = candidates.get(key, [])
    if index < 0 or index >= len(items):
        return ""
    item = items[index]
    content = item.get("content", "")
    reason = item.get("reason", "")
    risk = item.get("risk", "none")

    # Reject forbidden content
    forbidden = ["依赖", "离不开", "只喜欢", "最爱", "永远", "占有"]
    for kw in forbidden:
        if kw in content:
            return f"[拒绝] 候选内容含禁止词: {kw}"

    if key == "learner_profile_candidates":
        entry = f"### 待确认观察 (来源: 微信群)\n\n- {content}\n  - 原因: {reason}\n  - risk: {risk}"
        target = ROOT / "memory" / "learner_profile.md"
        append_text_safely(target, entry)
        return str(target)

    if key == "summary_candidates":
        target = ROOT / "memory" / "summary.md"
    elif key == "progress_candidates":
        target = ROOT / "memory" / "progress.md"
    elif key == "current_focus_candidates":
        target = ROOT / "memory" / "pending_updates" / "current_focus_candidate.md"
    elif key == "revision_notes_candidates":
        target = ROOT / "logs" / "revision_notes.md"
    elif key == "session_archive_candidates":
        target = ROOT / "logs" / "session_archive.md"
    else:
        return ""

    entry = f"## 微信群提取\n\n- {content}\n  - 原因: {reason}\n  - 来源群聊"
    if key == "current_focus_candidates":
        entry = f"# 待确认焦点 (来源: 微信群)\n\n- {content}\n  - 原因: {reason}\n\n> 此文件为候选，请人工确认后合并到 current_focus.md。"
        safe_write_text(target, entry)
    else:
        append_text_safely(target, entry)
    return str(target)
