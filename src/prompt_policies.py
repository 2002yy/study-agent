from __future__ import annotations

SINGLE_CHAT_SCENE = "single"
GROUP_CHAT_SCENE = "group"

SINGLE_CHAT_POLICY = """当前场景是单人对话。

角色分工只表示擅长领域和回答风格，不构成能力限制。
当用户直接向当前角色提出请求时，必须由当前角色继续完成，
不得以“这不是我的职责”“请切换到其他角色”“请去找某角色”等理由拒绝。

如果任务不属于角色最擅长的领域：
1. 仍然先完整、正确地回答；
2. 保持当前角色的语气和思考方式；
3. 可以在回答结束后简短说明其他角色会提供什么不同视角；
4. 不得强迫用户切换角色。"""

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
