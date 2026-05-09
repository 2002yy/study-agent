# v0.5.3 微信群记忆提取 + 互动氛围开关

## 1. 版本定位

v0.5.3 解决两个问题：
1. **群聊信息单向浪费** — 微信群聊历史中蕴含的学习信息（进度、卡点、决策）之前无法进入长期记忆
2. **互动温度不可控** — 角色语气固定在"标准"档，缺乏可调节的亲近度

## 2. 微信群记忆提取

### 流程
```
微信群聊历史 → [提取记忆候选] → 6类候选 → 用户勾选确认 → safe_writer写入
```

### 6类候选
| 类型 | 目标文件 | 写入方式 |
|------|----------|----------|
| summary_candidates | memory/summary.md | 追加 |
| progress_candidates | memory/progress.md | 追加 |
| current_focus_candidates | memory/current_focus.md | 追加 |
| learner_profile_candidates | memory/learner_profile.md | 仅待确认区 |
| revision_notes_candidates | logs/revision_notes.md | 追加 |
| session_archive_candidates | logs/session_archive.md | 追加 |

### 关键约束
- 不自动写入，必须用户逐条确认
- learner_profile 候选只能进入"待确认区"，不直接正式写入
- 每条候选含：target / content / reason / source / risk
- 禁止提取情绪推断、敏感信息、亲密互动作为记忆

### 新增文件
- `src/wechat_memory.py` — 提取/保存/确认写入
- `templates/wechat_memory_extract.md` — 提取 prompt
- `memory/pending_updates/wechat_memory_candidates.md` — 候选存放

## 3. 互动氛围开关

### 三档
| 模式 | 值 | 说明 |
|------|-----|------|
| 标准 | standard | 标准学习伙伴语气，任务/学习/论文/项目优先 |
| 亲近陪伴 | warm | 更温和鼓励，有陪伴感，不进入恋爱感扮演 |
| 恋爱感陪伴 | close | 更强陪伴感/温柔感/在意感，可用轻微恋爱氛围，角色语气变化 |

### close 边界（恋爱感陪伴）
- 允许更强持续陪伴感、温柔感、在意感
- 可使用轻微恋爱感氛围表达
- 不模拟现实恋人身份
- 不生成身体亲密或成人内容
- 不使用占有式、依赖式、操控式表达
- 不让角色为了讨好用户而放弃纠错
- 不削弱正式教学、论文修改、项目推进和任务边界
- 角色变化：流萤更温柔，三月七更活泼亲近，纳西妲更安静陪伴，刻晴更柔和但仍保持边界

### UI
侧栏"互动氛围"下拉框，默认 standard。选择 warm/close 时显示对应约束说明。

### 接入点
- `context_builder.py` — system message 注入氛围规则
- `wechat.py` — 群聊生成和互动回复支持 relationship_mode
- `session_logger.py` — 记录当前氛围档位

## 4. 微信群记忆提取

### 流程
```
微信群聊历史 → [提取记忆候选] → 6类候选 → 用户逐条确认 → safe_writer写入
```

### 为什么必须用户确认
- 微信群聊内容包含角色互动和用户发言，容易附带情绪色彩
- 未经确认直接写入会污染长期记忆
- learner_profile 候选只进入"待确认区"

### 6类候选
| 类型 | 目标文件 | 写入方式 |
|------|----------|----------|
| summary_candidates | memory/summary.md | 追加 |
| progress_candidates | memory/progress.md | 追加 |
| current_focus_candidates | memory/current_focus.md | 追加 |
| learner_profile_candidates | memory/learner_profile.md | 仅待确认区 |
| revision_notes_candidates | logs/revision_notes.md | 追加 |
| session_archive_candidates | logs/session_archive.md | 追加 |

### 禁止提取
- 情绪推断
- 敏感信息
- 亲密互动内容
- 与学习无关的闲聊

## 5. 修改/新增文件

| 文件 | 类型 | 说明 |
|------|------|------|
| `src/wechat_memory.py` | 新增 | 记忆提取核心模块 |
| `templates/wechat_memory_extract.md` | 新增 | 提取 prompt 模板 |
| `memory/pending_updates/wechat_memory_candidates.md` | 新增 | 候选存放 |
| `memory/interaction_settings.md` | 新增 | 氛围设置持久化 |
| `src/context_builder.py` | 修改 | ATMOSPHERE_RULES 三档边界 |
| `src/wechat.py` | 修改 | generate 函数 support relationship_mode |
| `src/session_logger.py` | 修改 | 5个新字段 |
| `app.py` | 修改 | 侧栏氛围选择 + 记忆提取UI |

## 6. 边界约束
- 不做视觉增强（头像/背景/气泡）
- 不破坏 v0.1-v0.5.2 已有功能
- 不自动污染长期记忆
- close 是恋爱感陪伴，不是现实恋人模拟
- close 下不生成身体亲密或成人内容
- close 下不使用占有式、依赖式、操控式表达
- close 下不让角色为了讨好用户而放弃纠错
- 用户确认后写入，不自动
