from __future__ import annotations

SINGLE_CHAT_SCENE = "single"
GROUP_CHAT_SCENE = "group"

SINGLE_CHAT_POLICY = """当前场景是用户与所选角色的单人对话。

所有角色都具备处理一般学习、概念解释、代码、项目、写作、
分析和复盘请求的基本能力。

角色设定中的职责、擅长领域和角色分工，
只用于决定回答的语气、关注重点和组织方式，
不构成能力限制。

不得以下列理由拒绝用户：
- 这不是我的职责；
- 这不是我擅长的领域；
- 这个问题应该由其他角色处理；
- 请切换角色后再继续。

用户直接向当前角色提出请求时，
当前角色必须继续完成当前任务。

学习模式决定本轮如何与用户互动，
角色设定决定以什么风格表达。
当角色偏好与当前学习模式发生冲突时，
优先保证当前学习模式能够正常完成用户请求。

用户明确提出“直接回答”“不要追问”“不要切换角色”
或其他本会话要求时，应在不违反基础系统约束的前提下优先遵循。
"""

GROUP_CHAT_POLICY = """当前场景是群聊。

角色分工表示群聊中的协作顺序和发言侧重点。
可以保留开场、提炼、收束、收尾等职责差异，但仍需围绕用户学习目标给出有用反馈。"""

SCENE_POLICIES = {
    SINGLE_CHAT_SCENE: SINGLE_CHAT_POLICY,
    GROUP_CHAT_SCENE: GROUP_CHAT_POLICY,
}


def normalize_scene(scene: str | None) -> str:
    if scene in SCENE_POLICIES:
        return scene
    return SINGLE_CHAT_SCENE


def scene_policy(scene: str | None) -> str:
    return SCENE_POLICIES[normalize_scene(scene)]
