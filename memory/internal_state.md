# 内部状态

## 当前运行模式
- memory_mode: preview
- route_mode: auto_rule
- debug_mode: false
- safe_mode: false
- performance_mode: standard
- entry_mode: wechat

## 当前阶段
- current_version: v0.7.2
- active_task: 代码质量全面收口，拆解 wechat.py，版本一致性修复
- next_version: v0.7.3

## 规则边界
- 不自动污染长期记忆。
- 不绕过用户确认写入。
- 不让群聊替代正式学习。
- 不让互动氛围削弱纠错和任务边界。
- safe_mode=true 时禁止写入长期记忆。
