# v0.3 验收文档

## 1. v0.3 目标

实现课后更新机制：根据本轮对话生成五类文件更新建议 → 用户预览 → 确认后安全写入。

## 2. 新增文件

| 文件 | 说明 |
|------|------|
| `src/safe_writer.py` | 安全写入：备份 → 临时文件 → 替换，支持追加和覆盖 |
| `src/after_session.py` | 课后更新生成器：调用 LLM 生成五类更新建议，JSON 解析 + fallback |

## 3. 修改文件

| 文件 | 改动 |
|------|------|
| `app.py` | 侧栏新增"生成课后更新预览"按钮；主区新增预览区（5 个 expander）；新增"确认写入长期记忆"按钮；使用 safe_writer 安全写入 |
| `src/session_logger.py` | 新增 `set_after_session_status()`；日志 session 级记录 `课后更新: none / preview_generated / written` |
| `src/llm_client.py` | 恢复 `chat()` 函数（与 `chat_stream()` 并存），供课后更新使用 |

## 4. 使用流程

### 4.1 正常聊天

与 v0.1/v0.2 相同：选角色、选模式、选模型，对话。

### 4.2 生成课后更新预览

1. 点击侧栏 **生成课后更新预览**
2. 系统使用 Pro 模型分析本轮对话，生成五类更新建议
3. 主区聊天下方出现 5 个 expander：

| expander | 内容 |
|----------|------|
| progress.md — 学习进度更新 | 本轮完成内容、进度推进、下次继续点 |
| learner_profile.md — 学习者档案更新 | 薄弱点、新偏好、常见误区 |
| current_focus.md — 当前焦点更新 | 优先任务、暂缓任务、禁止边界 |
| revision_notes.md — 修订笔记 | 需补充的文档/讲义 |
| session_archive.md — 本轮归档 | 关键结论、重要决策 |

**此步骤不写入任何文件。**

### 4.3 确认写入

1. 预览满意后，点击 **确认写入长期记忆**
2. 系统使用 `safe_writer.py` 安全写入：

| 更新字段 | 目标文件 | 写入方式 |
|----------|----------|----------|
| progress_update | `memory/progress.md` | 追加 |
| learner_profile_update | `memory/learner_profile.md` | 追加 |
| current_focus_update | `memory/current_focus.md` | **覆盖**（写入前自动备份） |
| revision_notes_update | `logs/revision_notes.md` | 追加 |
| session_archive_update | `logs/session_archive.md` | 追加 |

3. 写入成功后显示 `st.success("课后更新已写入。")`，聊天中追加 system message
4. 检查 `backups/memory_backups/` 确认旧版本已备份

### 4.4 JSON 解析失败时的 fallback

如果 LLM 返回的内容无法解析为 JSON：
- 前四个字段显示"JSON 解析失败，需要人工检查"
- `session_archive_update` 保存原始返回文本，供人工查看

## 5. 验收用例

| # | 步骤 | 预期 |
|---|------|------|
| 1 | 对话数轮后点"生成课后更新预览" | 出现 5 个 expander，内容不空 |
| 2 | 检查 `memory/progress.md` | **未被修改**（预览不写入） |
| 3 | 点"确认写入长期记忆" | 显示 `st.success`，聊天追加 system msg |
| 4 | 检查 `memory/progress.md` | 末尾追加了课后更新 |
| 5 | 检查 `memory/current_focus.md` | 内容已更新为最新 |
| 6 | 检查 `backups/memory_backups/` | 有 `current_focus_*.md.bak` 备份 |
| 7 | 检查 `logs/revision_notes.md` | 末尾有追加 |
| 8 | 检查 `logs/session_archive.md` | 末尾有追加 |
| 9 | 保存日志后查看 | 包含 `课后更新: written` |
| 10 | 新一轮对话不点任何更新按钮 | 保存后日志显示 `课后更新: none` |

## 6. v0.3 不包含的功能

- 微信群（v0.4）
- 自动模式路由（v0.5）
- 自动角色调度（v0.5）
- 头像、背景等视觉增强（v0.6）
- 陪伴强度开关（v0.7）
