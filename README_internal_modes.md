# 内部模式说明

> 本文件描述当前真实代码中的运行态模式字段。  
> 当前对应版本：`v0.7.2`

## 1. 当前模式字段

| 字段 | 说明 | 当前可选值 |
|------|------|-----------|
| `relationship_mode` | 互动氛围 | `standard / warm / close` |
| `wechat_mode` | 微信群状态 | `unread_feedback / first_user_join / interactive_group` |
| `memory_mode` | 记忆读写权限 | `readonly / preview / confirm_write / locked` |
| `route_mode` | 路由模式 | `auto_rule / hybrid` |
| `debug_mode` | 是否显示调试信息 | `true / false` |
| `safe_mode` | 是否禁止写入长期记忆 | `true / false` |
| `performance_mode` | 性能模式 | `fast / standard / deep` |
| `entry_mode` | 主入口模式 | `wechat / single` |

## 2. 状态文件

| 文件 | 存储内容 |
|------|----------|
| `memory/internal_state.md` | `memory_mode / route_mode / debug_mode / safe_mode / performance_mode / entry_mode / version` |
| `memory/interaction_settings.md` | `relationship_mode` |
| `chat/wechat_state.md` | `wechat_mode / user_has_joined / first_join_reaction_done / memory_capture` |

## 3. 当前行为边界

### relationship_mode

1. `standard`: 标准学习伙伴语气
2. `warm`: 更温和、更鼓励，但不进入恋爱角色扮演
3. `close`: 更强陪伴感，但仍不能削弱学习边界

### memory_mode

1. `readonly`: 只读
2. `preview`: 可生成预览，不可正式写入
3. `confirm_write`: 用户确认后允许写入
4. `locked`: 完全锁定

### route_mode

1. `auto_rule`: 规则优先自动路由
2. `hybrid`: 规则 + LLM router 混合

### performance_mode

1. `fast`: 偏速度
2. `standard`: 平衡
3. `deep`: 偏深度

## 4. 当前注意事项

1. `safe_mode=true` 时禁止长期记忆写入
2. `preview` 不是正式写入模式
3. 微信群联网搜索会影响 `wechat_mode`、群聊记录和 notice 队列
4. 版本状态以 `memory/internal_state.md` 和 `src/mode_manager.py` 为准
