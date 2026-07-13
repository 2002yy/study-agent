# Study Agent 架构边界附录

> **文档类别：稳定架构参考，不是当前进度入口。**  
> 当前状态、缺口和执行顺序统一查看 [`PROJECT_STATUS.md`](PROJECT_STATUS.md)。

本文件只记录各纵向切片的 authoritative owner 和架构边界。只有 owner、持久化边界或稳定不变量变化时才更新。

## 1. 状态含义

- **sealed**：在指定架构范围内已有唯一 owner、持久化、恢复和回归边界。
- **partial**：生产路径已存在，但完整生命周期或产品合同仍未封板。
- **transitional**：当前可用，但不是最终 owner/state machine。
- **legacy**：只为旧客户端或旧入口保留。

架构 sealed 不代表整个用户流程完成。例如 Chat/Session core 已 sealed，但会话标题、summary status 和恢复卡属于产品层后续工作。

## 2. Authoritative owners

| 纵向切片 | 架构状态 | Authoritative owner |
|---|---|---|
| Chat/Session core | sealed | FastAPI chat/session services + SQLite repositories + `chatController` |
| Pedagogy protocol | partial | pedagogy engine + committed `ChatThread.learning_state` |
| Pedagogy evaluation | sealed | `PedagogyEvalRun` repository/service + turn completion transaction |
| Task intent contract | partial | `src/task_contract.py` + route snapshot + task-aware pedagogy wrappers |
| GroupThread | sealed | group service/repository + `groupChatController` |
| NewsRun | sealed | news service/repository + `newsController` |
| ToolRun | sealed | tool service/repository + `toolController` |
| MemoryTransaction | sealed | `MemoryRun` + hash-locked commit + `memoryController` |
| Learning closure | transitional | after-session adapter + MemoryRun；最终 owner 将为 LearningClosureService/Run |
| RAG/KnowledgeBase | sealed | RagRun、document revision、index state、RAG controllers |
| WebLookup base run | sealed | `WebLookupService` + `WebLookupRepository` + `webLookupController` |
| Multi-step research | partial | 必须扩展现有 WebLookup owner，不新建重叠系统 |
| External data policy | partial | policy-aware chat preparation + runtime settings |
| Evidence presentation | partial | turn snapshots + frontend evidence helpers；统一 EvidenceRef 尚未封板 |
| Operation ownership | partial | operation registry + scoped controllers；服务端完整 cancel propagation 尚未封板 |
| App entry | sealed | composition-only `App.tsx` |
| AppShell | sealed | layout-only `AppShell` |
| Workspace Runtime | sealed | controller construction、recovery、persistence、view binding |
| Compatibility API | legacy | frozen `src/api/__init__.py` exports |
| Streamlit | legacy | `app.py`、`src/ui/*`，只接受兼容修复 |

## 3. 稳定架构原则

1. API route 只做 adapter，不拥有多步业务编排。
2. 多步流程由 application service 和 durable run 负责。
3. completed turn、committed learning state 和 PedagogyEvalRun 必须保持事务一致。
4. Memory 写入必须经过 preview/hash/confirm 边界。
5. RAG 索引使用 active/staging version 和失败不激活原则。
6. 研究能力扩展现有 WebLookup owner，避免 WebLookupRun/ResearchRun 双轨。
7. 新生产代码不得依赖 `src.api` compatibility facade。
8. Streamlit 不再承接新功能。
9. planned/attempted 状态不能覆盖 committed truth。
10. 普通会话切换不能全局取消无关 operation scope。

## 4. 兼容策略

- 旧 API/导出在迁移完成前保持可调用，但必须有 replacement coverage。
- 新 SQLite migration 必须递增 schema version，并保留 migration ledger。
- 历史行缺少新增字段时必须有安全默认值。
- 删除兼容入口前，同时更新测试、README、USER_GUIDE 和 `PROJECT_STATUS.md`。

## 5. 相关文档

- 当前状态与下一步：[`PROJECT_STATUS.md`](PROJECT_STATUS.md)
- 文档分类：[`README.md`](README.md)
- 技术栈：[`TECH_STACK.md`](TECH_STACK.md)
- 文件/数据状态模型：[`STATE_MODEL.md`](STATE_MODEL.md)
- 详细产品需求：[`superpowers/plans/2026-07-12-study-agent-consolidated-roadmap.md`](superpowers/plans/2026-07-12-study-agent-consolidated-roadmap.md)
