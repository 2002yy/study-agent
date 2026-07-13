# Study Agent 技术栈与工程亮点

> **文档类别：稳定技术参考，不是当前进度入口。**  
> 当前状态、缺口和下一步统一查看 [`PROJECT_STATUS.md`](PROJECT_STATUS.md)。  
> 架构 owner 与兼容边界查看 [`ARCHITECTURE_STATUS.md`](ARCHITECTURE_STATUS.md)。

本文用于说明当前主架构、核心工程能力和对外项目表达。Streamlit 只作为 legacy compatibility 入口，不代表当前产品架构。

## 1. 项目定位

Study Agent 是一个本地优先、教学法驱动、证据可追溯、支持长期记忆的 AI 学习工作台。

它不是简单的“输入 Prompt -> 返回答案”，而是将以下能力组织为可恢复的学习与研究流程：

- 任务意图识别；
- 教学协议和学习状态机；
- 学习者回答评估；
- 本地 RAG；
- 联网搜索和来源追溯；
- 会话与运行状态恢复；
- 用户确认后写入长期记忆；
- 多 Provider 模型接入和外发数据控制。

对外一句话：

> A local-first AI learning workbench built with React, FastAPI and SQLite, combining pedagogy-aware state machines, durable research/RAG runs, source-traceable evidence and user-confirmed long-term memory.

## 2. 当前技术栈

| 层级 | 技术 / 模块 | 责任 |
|---|---|---|
| Frontend | React 18 + TypeScript + Vite | 工作台、会话导航、学习状态、证据轨迹、设置和抽屉 UI |
| Frontend state | Feature controllers + reducer + recovery hooks | 各功能 owner、异步 operation、刷新恢复和本地 UI 缓存 |
| API | FastAPI + Pydantic | HTTP/SSE adapter、输入校验、响应合同 |
| Application | Python application services | Chat、Group、News、Tool、Memory、RAG、WebLookup 等业务编排 |
| Persistence | SQLite + ordered migrations | durable runs、会话、评估、索引状态和版本迁移 |
| LLM | OpenAI-compatible client | OpenAI、DeepSeek、OpenRouter、SiliconFlow、本地兼容服务 |
| Pedagogy | Protocol engine + PedagogyEvalRun | 苏格拉底、费曼、项目、直接讲解和证据化学习评估 |
| Task semantics | TaskIntent / SourcePolicy / ClosureEligibility | 临时任务与长期学习状态分离 |
| RAG | BM25 + vector + RRF + optional reranker | 本地资料加载、切块、检索、融合、引用和评测 |
| Web research | WebLookupRun + search/read gateways | 日期感知查询、查询尝试、来源评估和研究状态 |
| Long-term memory | Markdown + MemoryRun + safe writer | 可读记忆、预览/确认写入、hash 一致性和备份 |
| Security | SSRF guards + secret scanning + policy gates | URL 安全、密钥防泄漏、联网和云端上下文控制 |
| Quality | pytest + Ruff + mypy + Vitest + Vite build | 后端、前端、类型、Lint、构建和 CI |
| Packaging | pip-tools + package helper | 锁定依赖、排除用户数据和运行产物 |

## 3. 当前主架构

```text
React feature views
        ↓
Feature controllers / operation registry / recovery
        ↓
FastAPI routes (adapter only)
        ↓
Application services
        ↓
Repositories / provider gateways / policies
        ↓
SQLite durable state + Markdown long-term memory + RAG indexes
```

### 3.1 Frontend ownership

- `App.tsx`：composition-only 入口；
- `AppShell`：layout-only；
- `WorkspaceRuntime`：组合 controllers、recovery 和 views；
- feature controller：拥有对应 API 调用、busy/error 和 operation scope；
- reducer：管理当前会话、run ID、drawer 等 UI 状态；
- localStorage：仅用于 UI 恢复缓存，不是服务端业务真源。

### 3.2 Backend ownership

- route 不拥有多步业务流程；
- application service 是编排 owner；
- repository 负责 durable state 和 compare-and-set；
- gateway 隔离模型、搜索、网页读取和向量后端；
- policy 层负责任务、证据披露、外发上下文和安全边界。

## 4. Durable run 架构

项目用 server-owned run 表达可恢复的多步流程：

- `NewsRun`；
- `ToolRun`；
- `MemoryRun`；
- `RagRun`；
- `WebLookupRun`；
- `PedagogyEvalRun`；
- 后续 `LearningClosureRun`。

通用原则：

1. run 有稳定 ID；
2. 状态和阶段持久化；
3. 刷新后可读取；
4. 失败、部分成功和取消不可伪装成完成；
5. mutation 使用 expected state/version 防止并发覆盖；
6. 正常运行轨迹不塞进 warning；
7. API 只创建、读取、重试或取消 run。

## 5. 教学法与任务契约

### 5.1 教学协议

- Direct：直接讲解；
- Socratic：通过问题和提示引导重建；
- Feynman：让学习者解释，再诊断缺口；
- Project：围绕真实项目推进、验证和交付。

`ChatThread.learning_state` 保存 committed objective、phase、confirmed points 和 unresolved gap。完成回合、学习状态和评估结果保持事务一致。

### 5.2 PedagogyEvalRun

评估采用 deterministic-first：

- 明确错误或不满足条件时不调用模型；
- 歧义主张进入结构化 semantic evaluator；
- 保存 evaluator/prompt/schema version、证据 IDs、confidence 和 final decision；
- Provider/parse failure 进入 `needs_semantic_review`；
- 没有 accepted evidence 时不能推进 transfer/complete/deliver。

### 5.3 TaskIntent

顶层任务至少区分：

- quick answer；
- research；
- learn；
- explain back；
- project execution；
- conversation；
- organize。

临时 research、quick answer 和 conversation 默认不推进长期学习状态。角色只影响表达，不决定事实、来源或状态迁移。

## 6. RAG 工程能力

当前 RAG 主要能力：

- Markdown/TXT/DOCX/PDF 加载与安全校验；
- 稳定 document identity + revision identity；
- source-traceable chunks；
- BM25 lexical retrieval；
- configurable embeddings；
- vector backend abstraction 和可选 Chroma；
- reciprocal-rank fusion；
- duplicate suppression、source diversity 和 metadata filters；
- optional reranker 及 latency/cost budget；
- active/staging index version 和失败不激活；
- Recall/MRR/nDCG 统一评测；
- pedagogy-aware private query plan。

详细边界见 [`RAG.md`](RAG.md)。

## 7. 联网研究

联网研究基于 WebLookup owner 演进，不建立重复系统。

当前合同包括：

- raw/canonical query；
- bounded query variants；
- current date/freshness；
- query attempts；
- provider status；
- selected/rejected sources；
- deterministic SourceAssessment；
- stop reason；
- evidence confidence；
- durable stage。

来源评估只判断可用性、相关性、直接性、时效字段、重复和是否值得阅读，不用媒体白名单冒充事实判断。事实可信度需要正文阅读、交叉核验和 claim-source 对应。

## 8. 长期记忆

长期记忆仍使用可读 Markdown，但写入受 `MemoryRun` 保护：

1. 生成候选；
2. 用户预览；
3. hash 锁定候选版本；
4. 用户确认；
5. safe writer 备份并原子写入；
6. 保存写入结果。

典型目标：

- current focus；
- progress；
- summary；
- learner profile；
- project context；
- task board。

推断性 learner profile 不应直接当事实写入。

## 9. 多 Provider 与外发控制

Provider 抽象支持：

- OpenAI；
- DeepSeek；
- OpenRouter；
- SiliconFlow；
- local OpenAI-compatible endpoint。

运行时可控制：

- 联网关闭 / 每次询问 / 自动；
- 云端只发送当前问题 / 最近对话 / 允许本地资料；
- 模型档位、温度、token 和 timeout；
- 本地检索与云端上下文的边界。

API Key 仅来自环境配置，不进入仓库、日志或证据轨迹。

## 10. 安全与质量

### 安全

- URL scheme、DNS、私网/loopback/link-local 等 SSRF 检查；
- 每次 redirect 重新校验；
- 正文大小、字符数和重定向深度限制；
- detect-secrets CI hard gate；
- `.env` 和用户数据排除；
- 文档类型、MIME、magic bytes、archive expansion 校验；
- 删除和破坏性操作显式确认。

### 质量门禁

CI 运行：

- pytest；
- Ruff；
- package helper；
- detect-secrets；
- mypy soft check；
- frontend Vitest；
- Vite production build。

存储变化还需要 migration、旧数据回填、失败恢复和并发状态测试。

## 11. Legacy compatibility

以下内容只作兼容，不再承接新功能：

- `app.py` 和 `src/ui/*` Streamlit 入口；
- `src.api` compatibility exports；
- 旧 Markdown/YAML 状态视图；
- 已废弃的 `/news/lookup` 等 adapter。

删除 legacy 前必须有替代路径、迁移说明和回归覆盖。

## 12. 对外项目亮点表述

可以重点表达：

1. 将通用聊天升级为教学法驱动的可恢复学习状态机；
2. 用 PedagogyEvalRun 阻止模型失败或关键词命中导致的虚假掌握；
3. 用 durable run + SQLite migration 管理研究、RAG、记忆和工具流程；
4. 建立 active/staging RAG index，避免失败重建污染线上检索；
5. 将联网查询拆成日期感知规划、Provider 状态、来源评估和证据选择；
6. 通过 SourcePolicy 和 cloud-context policy 落实本地优先；
7. 使用 React feature controllers 和 FastAPI application services 明确 owner；
8. 使用测试、Lint、secret scan、前端构建和迁移回归形成工程门禁。
