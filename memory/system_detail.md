# 系统架构

## 总控模式

单总控 Orchestrator + 多角色适配器（v1 不做自治多 Agent）。

## 技术栈

| 层 | 选型 |
|---|---|
| 语言 | Python |
| UI | Streamlit |
| LLM 接口 | OpenAI-compatible SDK |
| 状态存储 | Markdown 文件 |
| 配置 | .env |
| 模型选择 | Flash / Pro 手动切换 |

## 角色系统

| 角色 | 职责 | 触发场景 |
|------|------|----------|
| 三月七 | 学习启动 | 开场、提问引导 |
| 刻晴 | 任务收束 | 目标模糊、边界不清 |
| 纳西妲 | 本质提炼 | 概念理解、结构整理 |
| 流萤 | 课后陪伴 | 收尾、情绪承接 |

## 数据流

```
用户输入 → app.py
  → role_manager（读角色 prompt）
  → llm_client.chat(model_profile)（调用 LLM）
  → 显示回复
  → session_logger.log()（内存记录）
  → 用户点保存 → session_logger.save()（写文件）
```

## 当前限制

- v0.2：长期记忆只读不写
- 无流式输出
- 无自动路由
