# 微信群状态

## 设定说明

- 每次生成新的课后群聊（append_wechat_messages），可见性状态会重置。
- 这意味着每轮群聊是一个新的"线程"。
- user_has_joined_group: false
  **在本轮群聊线程内**，用户是否已现身、惊讶是否已触发。
- 用户在本轮群聊第一次发言时，四人会轻微惊讶。
- 惊讶只在本轮触发一次。下一轮新群聊生成后，重新进入"未读反馈区"。

## 可见性状态（本轮线程内）
- user_has_joined_group: false
- first_join_reaction_done: false
- mode: interactive_group

## 长期记忆提取设置
- memory_capture_enabled: true
- memory_capture_mode: manual

## 最近一次记忆提取
- last_capture_time: 暂无
- last_capture_source: 暂无
- last_capture_status: none

## 群聊边界
- 群聊用于课后反馈、复盘、轻互动和学习动力。
- 不替代正式教学。
- 不进行无关剧情闲聊。
- 不编造用户没有表达过的感受。
- 互动氛围 close 模式下可恋爱感陪伴，但禁止成人内容和现实恋人身份模拟。
