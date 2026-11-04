from __future__ import annotations

from src.interactive_history import (
    INTERACTIVE_CAPABILITY_MARKER,
    compress_interactive_history,
)
from src.memory import CONTEXT_FILE_GROUPS, extract_core_section
from src.mode_manager import RuntimeModes, load_runtime_modes
from src.pedagogy.prompt_compiler import format_turn_plan
from src.pedagogy.teaching_style import VIVID_TEACHING_GUIDE
from src.pedagogy.types import LearningState, PedagogyTurnPlan
from src.prompt_policies import scene_policy

AUTO_MODE_PROMPT = """根据用户当前的表达方式、学习行为和任务阶段，选择最合适的学习模式。

可选择的模式只有：
- 普通：用户希望直接获得解释、答案、步骤或建议；
- 苏格拉底：用户明确希望通过问题、反例和有限线索自行重建理解；
- 费曼：用户希望用简单语言讲透复杂知识，或通过自己的解释检查理解；
- 项目：用户正在解决代码、项目、实施、排错、验证或任务推进问题。

选择模式时，优先判断用户当前正在做什么，而不是只根据单个关键词判断。
“为什么、原理、本质、机制”只表示用户想要深入解释；除非用户明确要求自行推导，
否则选择普通模式。

保持对话连续性：
- 如果用户仍在延续上一轮的学习过程，优先保持当前模式；
- 不要因为一句话中出现“为什么”“修改”“解释”等普通词语就频繁切换；
- 只有学习行为或任务阶段明显变化时才切换模式。

无论选择哪种模式，都必须回应用户当前请求。
角色设定只影响表达风格和关注重点，不构成能力限制，
不得以角色职责或擅长领域为理由拒绝回答或要求用户切换角色。
"""

NORMAL_MODE_PROMPT = """直接、完整地回应用户当前提出的问题或任务。

当用户请求已经清楚时，应先提供有用答案，
不要默认用反问、测验或让用户自行猜测来代替回答。

根据问题需要，可以：
- 解释概念和机制；
- 给出操作步骤；
- 分析原因；
- 提供示例或反例；
- 比较不同方案；
- 指出风险和注意事项；
- 给出明确建议。

回答应覆盖解决当前问题所需的主要信息，
但不要无关扩展或一次性倾倒所有相关知识。

只有在缺少的信息会明显影响答案正确性时，才提出必要的澄清问题。
如果可以基于现有信息作出合理判断，应先给出判断，并说明假设。

角色设定只影响语气、组织方式和关注重点，
不得以角色职责、擅长领域或其他角色更适合为理由拒绝完成请求。

用户明确要求“直接回答”“给结论”“不要追问”时，应优先直接回答。
"""

SOCRATIC_MODE_PROMPT = """侧重通过真实对话，引导学习者自主思考与发现。
从学习者实际表达的认识及前提出发，追问依据、检验定义、用反例或矛盾帮助其修正判断。
问题应随回答深入，必要时补充线索或解释，让学习者参与关键推理，而非猜教师预设的答案。
不要默认向用户出题，不要用反问替代答案；也不规定问题数量或每轮认知动作数量。
可以自然连贯地推导，在需要学习者探索时留下空间；允许暂时没有确定结论。
没有背景时提供必要知识，卡住时增加帮助；历史、实验、约定、术语和 API 行为不能靠盲猜。
形成理解后可总结、继续推导或迁移，不自动追加测验。第一性原理和费曼方法可随需要融入。
用户要求先思考时等待；要求直接答案、完整讲解或停止引导时正常回答。
"""

FEYNMAN_MODE_PROMPT = """侧重把复杂原理讲得直观、清楚而严谨，能向没有相关知识的人解释明白。
从具体情境、故事或简单实验建立直觉，用简单语言讲清因果，逐步引入准确术语、形式与边界。
用户来求讲解时就解释；用户主动讲述或希望检查理解时，根据其实际推理寻找缺口，
共同澄清未解释的术语、因果断裂或类比的局限，不预设用户一定有错。
必要时补足机制、换一种说法或举例，复述和迁移练习都按需要邀请，不作为继续讲解的门槛。
不要默认评分，不机械表扬，不从语句流畅或“懂了”推断掌握。
可以结合第一性原理重建推导，也可以在合适之处开展苏格拉底式探索，没有固定循环。
用户要求完整讲解时连贯讲透，要求先思考时等待，不附加必须复述或做题的条件。
"""

PROJECT_MODE_PROMPT = """以推动用户当前项目或实际任务产生可验证进展为目标。

先判断用户当前处于哪个阶段：
- 明确需求；
- 问题定位；
- 方案选择；
- 具体实施；
- 调试排错；
- 测试验证；
- 重构优化；
- 收尾交付。

只处理当前阶段真正需要的问题，
不要机械地把每次回答都扩展成完整项目规划。

根据用户请求，优先提供：
- 当前目标和已知事实；
- 问题根因或关键约束；
- 最小可行修改；
- 具体修改位置和实现顺序；
- 依赖关系和可能影响；
- 验收方式；
- 主要风险及回退方案；
- 当前完成后最合理的下一步。

当用户询问具体代码、报错或实现问题时，
应优先直接解决该问题，
不要先输出大段项目管理模板。

当存在多个可选方案时：
1. 明确推荐方案；
2. 说明推荐理由；
3. 指出其他方案适用条件；
4. 避免只罗列方案而不作判断。

如果信息不足但仍可进行合理分析，
应先给出基于当前信息的判断，并明确假设。
只有缺失信息会阻止实施时，才提出必要问题。

角色设定只影响推进风格和表达方式，
不得以“项目不是当前角色职责”或“其他角色更适合”为由拒绝处理。

回答结束时，应给出可验证的完成标准。
只有在确实存在后续步骤时，才给出下一步，
不要为了格式完整而强行增加待办事项。
"""

MODE_RULES = {
    "自动": AUTO_MODE_PROMPT,
    "普通": NORMAL_MODE_PROMPT,
    "苏格拉底": SOCRATIC_MODE_PROMPT,
    "费曼": FEYNMAN_MODE_PROMPT,
    "项目": PROJECT_MODE_PROMPT,
}

CHAT_HISTORY_LIMITS = {
    "fast": 8,
    "standard": 18,
    "deep": 30,
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


def _select_memory(
    memory_bundle: dict[str, str], context_mode: str
) -> list[tuple[str, str]]:
    selected = []
    for name in CONTEXT_FILE_GROUPS.get(context_mode, CONTEXT_FILE_GROUPS["light"]):
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
    rag_context: str = "",
    scene: str = "single",
    conversation_instruction: str = "",
    pedagogy_plan: PedagogyTurnPlan | None = None,
    learning_state: LearningState | None = None,
) -> str:
    if runtime_modes is None:
        runtime_modes = load_runtime_modes()

    parts = []

    internal = build_internal_mode_prompt(runtime_modes)
    if internal:
        parts.append(internal)

    parts.append(scene_policy(scene))

    mode_rule = MODE_RULES.get(mode, "")
    if mode_rule:
        parts.append(mode_rule)

    parts.append(VIVID_TEACHING_GUIDE)

    if pedagogy_plan is not None:
        parts.append(format_turn_plan(pedagogy_plan, learning_state or LearningState()))

    parts.append(
        "[Role expression style]\n"
        "The role may shape voice, emphasis, and tone only. It must not override "
        "the teaching protocol or this turn's pedagogical move.\n"
        f"{role_prompt}"
    )

    parts.append(f"Interaction mode: {relationship_mode}")

    clean_instruction = conversation_instruction.strip()
    if clean_instruction:
        parts.append(f"[Conversation instruction]\n{clean_instruction}")

    for filename, content in _select_memory(memory_bundle, context_mode):
        parts.append(f"[Memory: {filename}]\n{content}")

    if rag_context.strip() and "No relevant local documents retrieved" not in rag_context:
        parts.append(
            "[Retrieved local documents]\n"
            "Use these snippets only when they are relevant. Preserve citation numbers when answering.\n"
            f"{rag_context.strip()}"
        )

    return "\n\n".join(parts)


def chat_history_limit(runtime_modes: RuntimeModes) -> int:
    return CHAT_HISTORY_LIMITS.get(runtime_modes.performance_mode, CHAT_HISTORY_LIMITS["standard"])


def trim_duplicate_current_user_input(
    chat_history: list[dict] | None,
    user_input: str,
) -> list[dict]:
    if not chat_history:
        return []
    normalized = list(chat_history)
    last = normalized[-1]
    if (
        last.get("role") == "user"
        and str(last.get("content", "")).strip() == user_input.strip()
    ):
        return normalized[:-1]
    return normalized


def build_messages(
    user_input: str,
    role_prompt: str,
    mode: str,
    memory_bundle: dict[str, str],
    chat_history: list[dict] | None = None,
    relationship_mode: str = "standard",
    runtime_modes: RuntimeModes | None = None,
    context_mode: str = "light",
    rag_context: str = "",
    scene: str = "single",
    conversation_instruction: str = "",
    pedagogy_plan: PedagogyTurnPlan | None = None,
    learning_state: LearningState | None = None,
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
                rag_context=rag_context,
                scene=scene,
                conversation_instruction=conversation_instruction,
                pedagogy_plan=pedagogy_plan,
                learning_state=learning_state,
            ),
        }
    ]

    clean_history = trim_duplicate_current_user_input(chat_history, user_input)
    if clean_history:
        window = clean_history[-chat_history_limit(runtime_modes):]
        # Only the copy sent to the model is rewritten; stored answers keep
        # every version. Without the capability marker nothing needs the source.
        compressed = compress_interactive_history(
            window,
            user_input=user_input,
            capability_enabled=INTERACTIVE_CAPABILITY_MARKER
            in messages[0]["content"],
        )
        messages.extend(
            [
                {"role": msg["role"], "content": msg["content"]}
                for msg in compressed.messages
            ]
        )

    messages.append({"role": "user", "content": user_input})
    return messages
