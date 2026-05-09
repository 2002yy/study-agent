# v0.2 验收文档

## 1. v0.2 目标

让 Agent 每次回答前自动读取 `memory/` 下的长期状态文件，使回复体现当前学习上下文。**只读不写。**

## 2. 新增文件

| 文件 | 说明 |
|------|------|
| `src/memory.py` | 读取 memory/ 下全部 `.md` 文件，返回 bundle |
| `src/context_builder.py` | 拼装 LLM 上下文：角色 prompt + 模式规则 + 长期记忆 + 对话历史 |
| `memory/agent.md` | 系统说明 |
| `memory/learner_profile.md` | 学习者档案（偏好、常用任务、薄弱点） |
| `memory/progress.md` | 学习进度 |
| `memory/current_focus.md` | 当前焦点（优先任务 / 暂缓 / 禁止边界） |
| `memory/project_context.md` | 项目上下文与结构 |
| `memory/system_detail.md` | 系统架构说明 |

## 3. 修改文件

| 文件 | 改动 |
|------|------|
| `app.py` | 导入 `read_memory_bundle` + `build_messages`；侧栏新增"当前记忆状态"折叠预览；`build_messages` 替代手动拼 prompt；`log()` 传入 `memory_enabled` |
| `src/session_logger.py` | `log()` 新增 `memory_enabled` 参数；保存时记录"长期记忆: enabled"及文件列表 |

## 4. 验收方法

### 4.1 启动

```powershell
streamlit run app.py
```

### 4.2 侧栏记忆状态

页面加载后，侧栏"当前记忆状态"折叠区应展示：
- **学习进度** (progress.md 前 6 行)
- **当前焦点** (current_focus.md 前 6 行)
- **学习者档案** (learner_profile.md 前 6 行)

### 4.3 对话测试

提问：

> 现在做到哪一版了？

预期 Agent 回复应体现：
- v0.1 已完成
- 当前 v0.2 长期记忆读取
- 暂缓任务：课后更新、微信群、自动路由等

### 4.4 日志验收

1. 对话后点击侧栏"结束本轮并保存日志"
2. 检查 `logs/sessions/` 下生成的 `.md` 文件
3. 确认每条日志记录包含：

```markdown
- 长期记忆: enabled
  - agent.md
  - learner_profile.md
  - progress.md
  - current_focus.md
  - project_context.md
  - system_detail.md
```

### 4.5 异常保护

删除 `memory/progress.md`，刷新页面。侧栏应显示 `st.warning` 或占位内容，**页面不崩溃**。

## 5. v0.2 不包含的功能

- 自动写入 memory（留到 v0.3）
- 课后更新
- 微信群
- 自动模式路由
- 自动角色调度
- 头像、背景等视觉增强
