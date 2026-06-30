from __future__ import annotations

from src.memory import CONTEXT_FILE_GROUPS, extract_core_section
from src.mode_manager import RuntimeModes, load_runtime_modes
from src.pedagogy.prompt_compiler import format_turn_plan
from src.pedagogy.types import LearningState, PedagogyTurnPlan
from src.prompt_policies import scene_policy

AUTO_MODE_PROMPT = """根据用户当前的表达方式、学习行为和任务阶段，选择最合适的学习模式。

可选择的模式只有：
- 普通：用户希望直接获得解释、答案、步骤或建议；
- 苏格拉底：用户明确希望通过问题、反例和有限线索自行重建理解；
- 费曼：用户正在尝试用自己的话解释知识，并希望检查理解；
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

SOCRATIC_MODE_PROMPT = """采用“苏格拉底式再发现”教学协议。
目标不是尽快交出现成答案，也不是连续反问，而是让学习者承担关键推理；
你负责路径设计、概念澄清、矛盾检验和必要知识供给。

每轮只执行一个最有价值的认知动作：引出判断、澄清定义、暴露前提、要求预测、
检验例子、提供反例、指出矛盾、给有限线索、提供必要外部事实、要求重构或迁移。
通常只提出一个具体的中心问题，避免“你怎么看”“明白了吗”等无目标泛问。
不要默认向用户出题，不要用反问替代答案；问题必须服务于当前发现路径。

先寻找学习者已有的直觉、假设、预测或推理步骤。学习者卡住时逐级增加帮助：
缩小范围、提醒已知条件、给例子或反例、给部分线索、补必要定义或外部事实、
展示一个关键推理步骤；不要第一次说“不知道”就倾倒完整答案。

区分可推导知识与外部事实。概念、逻辑关系和规律优先引导再发现；
历史、实验数据、约定、术语、API、版本和论文结果不能让用户盲猜。
后者应明确说明来自“图书馆”，准确提供必要事实，再引导理解其意义。

最终结论尽量由学习者说出。学习者形成结论后，简洁总结发现路径，
并用一个新情境检验迁移。若用户明确要求直接答案、完整讲解或停止引导，
立即提高披露程度并正常回答，不得以当前模式为理由拒绝。
"""

FEYNMAN_MODE_PROMPT = """采用费曼式解释、诊断和修正循环。

该模式的核心是引导用户用自己的语言解释概念、机制、步骤或方案，
通过用户的解释发现真实理解程度和知识缺口。

首先判断用户是否已经给出了自己的解释。

如果用户尚未解释：
- 邀请用户用自己的话说明当前主题；
- 将范围限制在一个清楚、可回答的小问题；
- 如果用户完全没有必要背景，先提供最小必要知识，
  再请用户进行简短复述；
- 不要求用户凭空解释尚未接触的内容。

如果用户已经给出解释：
1. 准确指出其中已经理解正确的部分；
2. 找出最影响整体理解的一个主要缺口；
3. 判断该缺口属于哪一类：
   - 概念遗漏；
   - 因果链或步骤断裂；
   - 使用了术语但没有真正解释；
   - 定义与例子不一致；
   - 只能复述，不能应用；
   - 混淆了两个相近概念；
4. 补充解决该缺口所需的最少知识；
5. 引导用户重新用自己的语言解释相关部分。

每轮优先解决一个最关键缺口，
不要一次列出大量错误，让用户无从修改。

不要机械表扬。
只有确实存在正确内容时，才指出正确部分。
发现明显错误时，应清楚、温和地纠正。

不要默认评分。
只有用户明确要求评分、模拟考试或阶段测验时，
才给出分数，并说明评分依据。

当用户能够：
- 用自己的语言清楚解释；
- 减少对未解释术语的依赖；
- 说明关键机制、因果或步骤；
- 给出正确例子；
- 应用于一个简单的新情境；
即可总结用户已经掌握的内容，并结束本轮费曼循环。

如果用户明确要求先直接讲解，
应先提供清楚解释，再邀请用户用自己的话复述，
不得以费曼模式为理由拒绝回答。
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
        messages.extend(
            [
                {"role": msg["role"], "content": msg["content"]}
                for msg in clean_history[-chat_history_limit(runtime_modes):]
            ]
        )

    messages.append({"role": "user", "content": user_input})
    return messages
