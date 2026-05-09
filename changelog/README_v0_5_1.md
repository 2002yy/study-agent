# 个人学习 Agent 系统 v0.5.1 稳定性回补说明

## 1. 版本定位

v0.5.1 不是新的主功能阶段，而是对 v0.1–v0.5 的稳定性、可控性和长期使用体验进行回补。

此前系统已经完成：

- v0.1：基础网页对话、角色/模式/模型手动选择、Session 日志保存
- v0.2：长期记忆读取与上下文拼装
- v0.3：课后更新预览、确认写入、安全备份
- v0.4：微信群反馈生成、未读查看、群聊归档
- v0.5：自动模式路由、自动角色调度、自动模型选择

v0.5.1 的目标是：

> 让系统从"能用"进入"长期稳定可用"。

本版本重点补齐以下能力：

- 系统健康检查
- 配置前置校验
- 流式输出
- 当前会话临时保存
- 课后更新分项确认
- current_focus 写入前对比
- learner_profile 待确认机制
- 路由置信度与命中关键词
- memory summary 压缩层
- 微信群长度限制与状态头

---

## 2. 本版本新增/增强内容

### 2.1 系统健康检查

新增系统健康检查能力，用于检查项目关键文件、目录和配置是否完整。

检查范围包括：

- `.env` 是否存在
- API Key 是否配置
- Flash / Pro 模型名是否配置
- `memory/*.md` 是否存在
- `roles/*.md` 是否存在
- `chat/wechat_unread.md` 是否存在
- `chat/wechat_group.md` 是否存在
- `logs/sessions/` 是否可写
- `backups/memory_backups/` 是否存在

相关文件：

```
src/health_check.py
```

用途：
- 启动前检查
- 页面侧栏检查
- 排查配置缺失
- 避免用户只看到 Streamlit 报错

### 2.2 配置前置校验

新增配置读取与校验模块，避免将配置错误留到 API 调用时才暴露。

相关文件：

```
src/config.py
```

配置检查内容：

- OPENAI_API_KEY
- OPENAI_BASE_URL
- MODEL_FLASH_NAME
- MODEL_PRO_NAME
- DEFAULT_MODEL_PROFILE

目标：
- 页面启动时即可提示配置问题
- 避免 `llm_client.py` 同时承担配置校验和 API 调用
- 让错误信息更清晰

### 2.3 流式输出

新增流式输出能力。

原先回复方式：

> 等待完整回复生成完成 → 一次性显示

v0.5.1 支持：

> 模型边生成 → 页面边显示

相关改动：

- `src/llm_client.py`
- `app.py`

新增能力：
- `chat_stream()`

保留原有能力：
- `chat()`

使用原则：
- 普通聊天优先使用 `chat_stream()`
- 课后更新、微信群生成、结构化 JSON 任务仍使用 `chat()`
- 避免流式输出破坏结构化解析

### 2.4 当前会话临时保存

新增当前会话临时保存机制，防止用户忘记点击"结束本轮并保存日志"导致记录丢失。

相关位置：

```
logs/current_session.md
```

行为：
- 每次用户输入和 Agent 回复后，自动追加到 `logs/current_session.md`
- 用户点击"结束本轮并保存日志"后，正式归档到 `logs/sessions/`
- 归档后可清理或重置当前临时会话

目标：
- 防止浏览器刷新导致会话丢失
- 提高长期使用可靠性
- 为后续恢复未完成会话留接口

### 2.5 课后更新分项确认

v0.3 中课后更新采用整体确认写入。v0.5.1 改为分项确认。

可单独勾选：

- progress_update
- learner_profile_update
- current_focus_update
- revision_notes_update
- session_archive_update

优势：
- 避免不合适的 learner_profile 更新污染长期画像
- 避免 current_focus 被错误覆盖
- 允许用户只保存本轮真正有价值的部分

### 2.6 current_focus 写入前对比

`memory/current_focus.md` 是当前任务边界文件，风险较高。

v0.5.1 增加写入前对比：

- 旧 current_focus
- 新 current_focus

目标：
- 防止当前任务边界被误改
- 让用户清楚知道系统准备把焦点改成什么
- 保持项目推进的可控性

### 2.7 learner_profile 待确认机制

`learner_profile.md` 只应该记录稳定、可复用的学习偏好和常见误区。

v0.5.1 增加规则：

**允许记录：**
- 学习偏好
- 讲解偏好
- 常见误区
- 反复出现的薄弱点
- 已确认的工作习惯

**禁止记录：**
- 敏感信息
- 未经确认的人格判断
- 一次性情绪状态
- 过度推断
- 无依据标签

实现方式：
- learner_profile 更新先进入"待确认区"
- 用户确认后再写入正式记录
- 不再默认把模型生成的画像直接追加进长期文件

### 2.8 路由置信度与命中关键词

v0.5 的自动路由已经可以判断角色、模式和模型。v0.5.1 增加：

- `confidence`
- `matched_keywords`

路由结果现在包含：

- role
- mode
- model_profile
- reason
- manual_override
- confidence
- matched_keywords

示例：

```
角色：nahida
模式：苏格拉底
模型：pro
置信度：high
命中关键词：为什么 / 底层 / 机制
原因：用户询问底层机制，适合本质提炼与引导式解释。
```

用途：
- 让自动判断更透明
- 方便调试路由规则
- 低置信度时提醒用户可手动覆盖

### 2.9 memory summary 压缩层

随着长期记忆增长，直接拼接所有 memory 文件会导致上下文膨胀。

v0.5.1 新增：

```
memory/summary.md
```

作用：
- 保存当前系统最核心状态
- 减少每轮上下文负担
- 避免 `progress.md` 无限增长后拖慢调用

summary.md 主要包含：
- 当前版本阶段
- 当前优先任务
- 用户稳定偏好
- 最近关键决策
- 禁止乱动边界
- 下一阶段计划

上下文读取优先级：
1. `summary.md`
2. `current_focus.md`
3. `learner_profile.md` 的核心区
4. `progress.md` 的最近记录

### 2.10 微信群长度限制与状态头

v0.4 已经支持微信群未读与归档。v0.5.1 增加群聊收敛规则。

`chat/wechat_unread.md` 顶部增加状态头：

```markdown
# 微信群未读消息

- 生成时间：
- 状态：unread
- 阶段：v0.5
```

群聊长度规则：
- 每个角色 1–2 段
- 每段不超过约 120 字
- 总长度控制在约 800 字以内

生成依据优先级：
- session_archive_update
- progress_update
- current_focus_update

避免直接基于完整聊天记录过度发挥。

---

## 3. 本版本涉及的主要文件

### 新增或重点修改的源码文件

- `src/config.py`
- `src/health_check.py`
- `src/llm_client.py`
- `src/session_logger.py`
- `src/router.py`
- `src/after_session.py`
- `src/wechat.py`
- `src/memory.py`
- `src/context_builder.py`
- `src/backup_manager.py`
- `src/update_validator.py`

### 新增或重点修改的状态文件

- `memory/summary.md`
- `memory/current_focus.md`
- `memory/learner_profile.md`
- `memory/progress.md`
- `logs/current_session.md`
- `chat/wechat_unread.md`
- `chat/wechat_group.md`

### 备份目录

- `backups/memory_backups/`

---

## 4. 使用流程

### 4.1 启动项目

```powershell
pip install -r requirements.txt
Copy-Item .env.example .env   # 编辑填入真实 key
streamlit run app.py
```

浏览器打开 `http://localhost:8501`

### 4.2 检查系统状态

启动后先查看侧栏中的"系统健康检查"。

应确认：
- 配置文件正常
- 模型名称正常
- memory 文件存在
- roles 文件存在
- logs 可写
- chat 文件存在
- backup 目录存在

如果有缺失项，先修复配置或文件，再继续使用。

### 4.3 正常对话

侧栏可选择：

- 角色：自动 / 三月七 / 刻晴 / 纳西妲 / 流萤
- 模式：自动 / 普通 / 苏格拉底 / 费曼 / 项目 / 论文
- 模型：自动 / Flash / Pro

推荐默认全部"自动"。系统会根据输入自动选择角色、模式和模型。

### 4.4 查看路由结果

每轮自动路由后，侧栏路由调试面板显示：
- 最终角色/模式/模型
- 路由原因
- 置信度
- 命中关键词
- 是否手动覆盖
- 锁定当前路由

如果路由不符合预期，可以手动选择或勾选"本轮锁定"。

### 4.5 课后更新

1. 点击"生成课后更新预览"
2. 检查五类更新
3. 按需勾选需要写入的项目
4. 查看 current_focus 写入前对比
5. 确认写入长期记忆
6. 检查写入验证面板

### 4.6 微信群反馈

完成课后更新后：
1. 选择群聊风格（简短/标准/稍微有温度）
2. 生成微信群反馈
3. 查看未读消息
4. 清空未读消息

注意：
- `wechat_unread.md` 只保存未读消息
- `wechat_group.md` 保存完整群聊历史
- 清空未读不会清空完整群聊存档

### 4.7 保存会话日志

点击"结束本轮并保存日志"，归档到 `logs/sessions/`。

当前会话自动临时保存到 `logs/current_session.md`。

---

## 5. 验收用例

### 测试 1：系统健康检查
启动后查看健康检查，全部通过。

### 测试 2：流式输出
输入普通问题，回复逐步显示而非一次性。

### 测试 3：自动路由
输入"CNN 为什么要参数共享"，路由→nahida/苏格拉底/pro，置信度 high/medium。

### 测试 4：手动覆盖
手动选三月七+苏格拉底+Flash，输入论文相关，系统尊重手动选择。

### 测试 5：课后更新分项确认
取消 learner_profile_update 勾选，该文件不被修改。

### 测试 6：current_focus 写入前对比
生成课后更新后，页面显示新旧 current_focus 对比。

### 测试 7：memory summary 生效
询问当前项目状态，Agent 回答版本阶段和重点。

### 测试 8：微信群长度限制
生成群聊，内容围绕 session，长度合理，有状态头。

### 测试 9：当前会话临时保存
对话后查看 `logs/current_session.md`，内容存在，中文不乱码。

---

## 6. 本版本不包含的内容

- 头像
- 聊天背景
- 聊天气泡
- 仿微信群 UI
- 角色立绘
- 自动 LLM Router
- 复杂多 Agent 协作
- 陪伴强度开关
- 恋爱模式
- 语音输入输出
- 数据库存储
- 云端同步

这些内容后续可放入：
- v0.6：视觉增强
- v0.7：陪伴强度开关

---

## 7. 当前版本状态

- 当前版本：v0.5.1
- 阶段性质：稳定性回补
- 核心目标：提高长期使用的安全性、可控性、可调试性
- 下一阶段建议：不要立刻做复杂新功能，先完成 v0.5.1 回归测试
- 后续计划：v0.6 视觉增强

---

## 8. 回归测试建议

1. 启动 Streamlit
2. 查看系统健康检查
3. 测试 Flash 简单问答
4. 测试 Pro 复杂问答
5. 测试自动路由
6. 测试手动覆盖
7. 测试流式输出
8. 测试 current_session 临时保存
9. 测试课后更新预览
10. 测试分项确认写入
11. 测试 current_focus 对比
12. 测试 learner_profile 不被误写
13. 测试微信群反馈生成
14. 测试未读清空
15. 测试 session 日志归档
16. 检查 backups/memory_backups/

全部通过后，可认为 v0.5.1 稳定。

---

## 9. 维护原则

后续继续开发时，应遵守以下原则：

1. 先稳定，再美化
2. 先可恢复，再自动化
3. 先可解释，再智能化
4. 先保存真实进度，再生成角色反馈
5. 长期记忆不允许无确认污染
6. 用户手动选择永远优先于自动判断
7. 所有写入必须可备份、可回看、可恢复
