"""Session 状态管理 — 替代模块级全局变量"""

from dataclasses import dataclass, field


@dataclass
class SessionMeta:
    after_session_status: str = "none"
    wechat_status: str = "none"
    wechat_unread_cleared: bool = False
    wechat_interactive: str = "none"
    wechat_memory_capture: str = "disabled"
    wechat_memory_candidates: str = "none"
    interaction_mode: str = "standard"

    def reset(self):
        self.after_session_status = "none"
        self.wechat_status = "none"
        self.wechat_unread_cleared = False
        self.wechat_interactive = "none"
        self.wechat_memory_capture = "disabled"
        self.wechat_memory_candidates = "none"
        self.interaction_mode = "standard"
