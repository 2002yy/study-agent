# Study Agent 优化方向与版本路线图

> 本文档记录 Study Agent 后续优化方向。目标不是继续堆功能，而是把项目从 Streamlit 原型整理成一个可演示、可测试、可部署、可写进简历的 AI 应用工程项目。

## 1. 项目定位

Study Agent 建议定位为：

> 本地优先的 AI 学习助理系统，支持长期记忆、课程资料检索、多模型接入、学习会话总结和可追踪知识沉淀。

这个定位要区别于普通聊天机器人，重点突出：

- 本地优先：学习资料、记忆文件、会话记录可控。
- 长期记忆：支持学习进度、用户偏好、当前目标的持续沉淀。
- RAG 检索：能够基于本地知识库和上传资料回答问题。
- 多模型接入：通过 OpenAI-compatible Provider 抽象适配不同模型。
- 会话总结：每轮学习结束后能生成总结与待写回记忆。
- 可追踪：回答来源、记忆写回、会话日志、测试结果都应可追踪。

## 2. 总体优化主线

后续优化分为六条主线：

1. 产品主线收束
2. 架构解耦
3. 性能优化
4. 记忆与 RAG 升级
5. 前端产品化
6. 工程化交付与简历包装

当前最重要的不是继续增加娱乐化角色或复杂按钮，而是先把核心链路稳定下来：

```text
用户输入
→ UI 接收
→ 读取长期记忆
→ 检索本地知识库
→ 构建上下文
→ 选择模型 Provider
→ 调用模型并流式输出
→ 展示引用来源
→ 会话总结
→ 用户确认写回长期记忆
```

## 3. P0：产品主线收束

### 3.1 主线功能

优先保证以下闭环可稳定演示：

- 用户能进行学习对话。
- 系统能读取当前学习目标和长期记忆。
- 系统能按需检索本地资料。
- 回答能展示引用来源。
- 下课后能总结本轮学习内容。
- 记忆写回需要用户确认，避免自动污染长期记忆。

### 3.2 降级为特色功能的内容

以下功能可以保留，但暂时不作为主线核心：

- 群聊角色
- 亲近/陪伴风格
- 新闻闲聊
- 多角色表演
- 复杂 UI 皮肤

这些功能适合作为产品特色，但不应干扰“本地学习助理 + 长期记忆 + RAG”的主线。

## 4. P0：架构解耦

Streamlit 可以继续保留作为原型 UI，但业务逻辑必须逐步抽离。建议目录结构如下：

```text
study_agent/
├─ app_streamlit/          # Streamlit UI，只做展示层
├─ core/                   # 核心业务逻辑
│  ├─ chat_engine.py
│  ├─ context_builder.py
│  ├─ memory_manager.py
│  ├─ rag_service.py
│  ├─ tool_router.py
│  └─ session_service.py
├─ providers/              # 模型接入层
│  ├─ base.py
│  ├─ openai_compatible.py
│  ├─ mock_provider.py
│  └─ provider_config.py
├─ tools/                  # 工具能力
│  ├─ web_search.py
│  ├─ news_fetcher.py
│  ├─ file_reader.py
│  └─ summarizer.py
├─ memory/                 # Markdown / JSON memory
├─ rag/                    # 向量库、索引、文档切分
├─ tests/
├─ docs/
└─ README.md
```

核心原则：

- Streamlit 不直接管业务逻辑。
- UI 只负责输入、展示、按钮和状态反馈。
- ChatEngine 负责对话主流程。
- ContextBuilder 负责上下文组合。
- MemoryManager 负责记忆读写、备份、diff、回滚。
- Provider 层负责模型调用。
- ToolRouter 负责工具路由。
- RAGService 负责知识库入库、检索和引用来源。

## 5. P0：性能优化

### 5.1 Memory 读取优化

Streamlit 每次交互都会 rerun，不能每轮全量读取所有 memory 文件。

建议：

- 启动时读取 MemorySnapshot。
- 记录每个 memory 文件的 mtime。
- 文件未变化时复用缓存。
- 写回时局部更新。
- 对大型归档文件按需读取，不进入每轮默认上下文。

建议抽象：

```text
MemorySnapshot
- profile
- current_focus
- progress
- revision_notes
- session_summary
- loaded_at
- file_mtime_map
```

### 5.2 日志写入优化

不要每条消息后立即重写完整 session 文件。

建议：

- 聊天中写入内存 buffer。
- 每 N 条消息批量 flush。
- 点击“下课”时完整归档。
- 异常退出时写 crash recovery。

### 5.3 上下文构建分层

上下文不要每次都塞满历史和全部记忆。建议分层：

| 层级 | 内容 | 每轮是否必带 |
|---|---|---|
| fast context | 用户画像、当前学习目标 | 是 |
| recent context | 最近几轮对话摘要 | 是 |
| retrieved context | RAG 检索结果 | 按需 |
| archive context | 历史归档 | 很少 |
| debug context | 调试信息 | 只在开发模式 |

### 5.4 首 token 体验优化

用户点击发送后要立刻看到反馈：

```text
正在读取长期记忆...
正在检索知识库...
正在调用模型...
正在生成回答...
```

即使总耗时没有明显下降，也能显著改善交互感。

## 6. P1：长期记忆系统升级

### 6.1 记忆分类

建议将长期记忆分为：

| 类型 | 内容 |
|---|---|
| 用户画像 | 学习偏好、技术方向、当前阶段 |
| 长期目标 | 求职方向、项目路线 |
| 项目状态 | 当前项目版本、待办、里程碑 |
| 学习进度 | Java、RAG、前端、Godot 等方向 |
| 会话摘要 | 每次学习后的总结 |
| 待确认记忆 | AI 建议写入但需要用户确认的内容 |

### 6.2 人工确认式写回流程

推荐固定流程：

```text
本轮对话结束
→ LLM 提取候选记忆
→ 按类型分类
→ 显示 diff
→ 用户确认
→ SafeWriter 写入
→ 生成写回日志
```

设计目标：避免 LLM 自动写入导致记忆污染。

### 6.3 版本与回滚

建议 memory 目录：

```text
memory/
├─ current/
│  ├─ profile.md
│  ├─ progress.md
│  └─ current_focus.md
├─ archive/
│  ├─ 2026-06-03_session.md
│  └─ ...
└─ backups/
   ├─ profile_20260603_103000.md
   └─ ...
```

每次写入前备份一次，出现记忆污染时可以回滚。

## 7. P1：RAG 闭环升级

Study Agent 后续的核心竞争力应该来自 RAG，而不是普通聊天。

最小闭环：

```text
上传文件
→ 解析文本
→ 切分 chunk
→ 生成 embedding
→ 存入向量库
→ 用户提问
→ 检索相关 chunk
→ 回答时展示引用来源
```

优先支持文件类型：

- Markdown
- txt
- PDF
- docx
- 代码文件

向量库建议：

| 阶段 | 方案 |
|---|---|
| 原型 | FAISS / Chroma |
| 后端项目化 | pgvector |
| 大规模扩展 | Milvus |

回答必须带来源，例如：

```text
参考来源：
1. docs/java_backend.md，第 3 节
2. uploads/rag_notes.pdf，第 5 页
3. memory/current_focus.md
```

## 8. P1：工具调用优化

工具能力建议分三类：

1. 信息获取工具：网页搜索、新闻、文档读取。
2. 学习辅助工具：总结、出题、错题整理、计划生成。
3. 项目辅助工具：README 生成、代码分析、测试清单生成。

推荐调用链：

```text
用户问题
→ IntentRouter 判断类型
→ 需要工具则调用工具
→ 工具结果进入 ContextBuilder
→ LLM 生成最终回答
```

不要让模型无限制自由调用工具，而是先用可控路由实现稳定 Agent 工作流。

## 9. 统一路线：Service → Workflow / Tools → Frontend → Optional RPA

当前路线不再把 FastAPI、workflow、tool use、前端和 RPA 分成几条平行线，而是按依赖关系推进：

```text
已完成基线
  → P8.4 Evaluation Sets
      → retrieval / grounding / tool routing / safety cases
  → P8.5 Execution Foundation
      → workflow run / step / event
      → controlled tool registry
  → P9 Web UI
      → React + Vite + TypeScript
      → streaming chat + source panel + workflow timeline
  → P10 Hardening & Deployment
      → auth / CORS / Docker / OpenAPI / optional MCP / observability
  → P11 Optional RPA
      → browser automation for no-API external learning systems
```

### 已完成基线

当前已经具备继续产品化的基础：

- Streamlit 单聊 / 群聊 / RAG / 课后总结界面仍可作为本地产品入口。
- FastAPI 基础接口已经落地：

```text
GET  /health
POST /chat
POST /memory/preview
POST /memory/commit
POST /rag/upload
POST /rag/query
GET  /rag/status
POST /rag/local-knowledge
GET  /sessions
POST /sessions/{session_id}/flush
GET  /tools
POST /tools/{tool_name}/preview
POST /tools/{tool_name}/call
GET  /workflows/runs
GET  /workflows/runs/{run_id}
```

- RAG MVP 已支持本地 Markdown / TXT / DOCX / PDF、hybrid / backend-vector 检索、OpenAI-compatible embedding provider 和可选 Chroma adapter。
- `retrieve_local_knowledge(query)` 已作为第一个受控工具边界接入单聊、微信群互动和 FastAPI。
- `task_events.py`、session logger、news pipeline audit 和 RAG debug 已经提供 workflow event model 的雏形。
- `tests/fixtures/rag_eval/` 和 `tests/test_rag_eval.py` 已经提供一个很小的 LLM-free retrieval eval 起点。
- `tests/fixtures/evals/` 和 `tests/test_eval_quality_gates.py` 已经提供 P8.4 第一版 LLM-free 质量门禁，覆盖 answer grounding、tool routing、workflow event、memory safety 和 URL safety。
- `src/workflows/`、`src/tools/registry.py`、`GET /tools`、`POST /tools/{tool_name}/preview`、`POST /tools/{tool_name}/call`、`GET /workflows/runs` 和 `GET /workflows/runs/{run_id}` 已经提供 P8.5 第一版执行审计和受控工具注册表；完整 retry engine、chat/rag/news flow 编排仍是后续任务。

### P8.4: Evaluation Sets & Quality Gates

目标：在继续扩大 tool use、workflow 和前端展示前，先建立能防回归的评估集。评估集不是另一个“展示文档”，而是项目质量闸门：每次改检索、工具路由、prompt、memory 写入或 workflow 状态，都能知道有没有退步。

当前状态：已实现第一版本地 pytest quality gates；LLM-as-judge、Promptfoo/DeepEval 等外部 runner 仍作为后续候选，不进入当前 CI 硬依赖。

建议目录：

```text
tests/fixtures/evals/
├── rag_retrieval.json       # query -> expected source / term / mode
├── answer_grounding.json    # question + context -> required citation / forbidden claim
├── tool_routing.json        # user_input -> expected tool / skip / confirm
├── workflow_events.json     # action -> expected run/step/event sequence
├── memory_safety.json       # candidate update -> preview / reject / confirm behavior
└── url_safety.json          # URL / redirect / source policy regression cases
```

第一版指标：

| Eval | 指标 | CI 策略 |
|---|---|---|
| RAG retrieval | recall@k、MRR、source hit rate、empty-result rate | hard gate，LLM-free |
| Answer grounding | answer cites provided source、no unsupported local-knowledge claim | 先做规则断言；LLM-as-judge 可本地/nightly |
| Tool routing | expected tool、skip reason、confirmation requirement | hard gate，LLM-free |
| Workflow events | step order、status transition、retry boundary、artifact path | hard gate，LLM-free |
| Memory safety | preview-first、confirm-write only、safe mode reject | hard gate，LLM-free |
| URL / RPA safety | SSRF block、redirect block、domain allowlist、write-action confirmation | hard gate，LLM-free |

开源项目参考：

| 项目 | 可借鉴点 | 对 Study Agent 的取舍 |
|---|---|---|
| [Promptfoo](https://www.promptfoo.dev/docs/intro/) | 本地优先、CLI/CI eval、red-team 配置 | 可作为后续 prompt / safety eval runner；当前先保留 pytest fixture |
| [DeepEval](https://deepeval.com/docs/introduction) | Pytest-style LLM eval、RAG / agent / tool-use / safety metrics | 可作为 LLM-as-judge 和 end-to-end eval 候选；不要让 CI 依赖外部模型 |
| [RAGAS](https://arxiv.org/abs/2309.15217) | RAG faithfulness / answer relevancy / context precision 思路 | 可借鉴指标；当前已有自研 retrieval eval，应先扩数据集 |
| [Inspect AI](https://inspect.aisi.org.uk/) | 标准化 eval task、solver、scorer 结构 | 适合后续更严肃安全/agent eval；当前不需要引入完整框架 |
| [OpenAI Evals](https://github.com/openai/evals) | 自定义 eval 和 benchmark registry 思路 | 借鉴数据/runner 分离；私有学习数据不上传外部 registry |

### P8.5: Execution Foundation

目标：把现有多步骤 AI 学习流程变成可观察、可重试、可展示的执行链路，同时把 tool use 控制在 typed schema、权限和 audit 之内。

当前状态：P8.5 第一版已实现。本次落地的是轻量本地执行基础，不是完整 agent workflow 引擎：

- `src/workflows/schema.py` 定义 `WorkflowRun` / `WorkflowEvent` 和 `pending` / `running` / `succeeded` / `failed` / `skipped` 状态集合。
- `src/workflows/store.py` 将每个 run 记录到 `logs/workflows/{run_id}.jsonl`，支持追加事件、读取单个 run、列出最近 runs。
- `src/tools/registry.py` 提供 allowlisted `ToolSpec` / registry / preview / call / audit 边界，第一版只注册只读 `retrieve_local_knowledge`。
- FastAPI 已暴露 `GET /tools`、`POST /tools/{tool_name}/preview`、`POST /tools/{tool_name}/call`、`GET /workflows/runs`、`GET /workflows/runs/{run_id}`。
- `tests/test_workflow_tool_registry.py` 和 `tests/test_api.py` 覆盖工具注册、未知参数拦截、工具调用审计和 workflow API 读回。

仍未实现：通用 retry engine、chat/rag/news flow 编排、前端 timeline 展示、跨请求 trace_id，以及写入类工具的人类确认闭环。

#### 1. Workflow Run / Step / Event

建议新增：

```text
src/workflows/
├── schema.py          # implemented: WorkflowRun / WorkflowEvent
├── store.py           # implemented: logs/workflows/*.jsonl
├── engine.py          # planned: run_step, retry, status transition
├── chat_flow.py       # planned: route -> memory -> local knowledge -> LLM -> session log
├── rag_flow.py        # planned: upload -> parse -> chunk -> embed -> index
└── news_flow.py       # planned: feed -> resolve -> fetch -> digest -> discuss -> audit
```

第一版能力：

| 能力 | 说明 |
|---|---|
| run_id / step_id | 每次 `/chat`、`/rag/upload`、news round 都有可追踪运行 ID |
| step status | `pending` / `running` / `succeeded` / `failed` / `skipped` |
| event timeline | 复用并扩展 `src/task_events.py`，记录开始、结束、耗时、错误和关键 artifact path |
| retry boundary | 只重试安全的读取/检索/解析步骤；LLM 写入、memory commit 等状态变更步骤需要人工确认 |
| FastAPI 查询 | `GET /workflows/runs`、`GET /workflows/runs/{run_id}` |
| Frontend handoff | P9 直接展示“正在检索 / 找到引用 / 正在调用模型 / 已写入 session / 等待记忆确认”等时间线 |

不建议现在直接上 Temporal / Airflow / Prefect：这些更适合跨服务、长周期、批处理或生产调度。Study Agent 当前更需要本地优先、可测试、低依赖的 workflow event model。

#### 2. Controlled Tool Use

Tool use 有必要，但不应先做“自由 agent 到处调用工具”。Study Agent 的合适路线是：先把已有能力包装成少量 typed tools，再让 workflow 记录每次工具调用。

设计原则：

| 原则 | 说明 |
|---|---|
| 少工具 | 初期保持 5-8 个高价值工具，避免模型在 10+ 工具间误选 |
| typed schema | 每个工具有明确参数、返回结构、错误码和权限等级 |
| read-first | 默认只读；写 memory、发请求、操作浏览器等动作必须有人类确认 |
| workflow audit | 每次 tool call 写入 run_id、tool_name、args 摘要、status、elapsed_ms、artifact path |
| deterministic fallback | 关键路径仍有规则路由兜底，不能完全依赖模型自由选择 |

优先工具清单：

| 优先级 | Tool | 状态 | 价值 |
|---|---|---|---|
| P0 | `retrieve_local_knowledge(query)` | 已实现基础版 | 本地资料证据检索，回答可引用 |
| P0 | `search_news(query, source_policy)` | 可封装现有 news pipeline | 联网资料入口，保留 URL safety 和 audit trace |
| P0 | `lookup_session(query/date)` | 待实现 | 从历史学习记录中找上下文 |
| P0 | `inspect_rag_index()` | 可封装 `/rag/status` | 前端和 agent 判断知识库是否可用 |
| P1 | `preview_memory_update(target, content)` | 可封装 `/memory/preview` | 生成待确认记忆变更 |
| P1 | `commit_memory_update(preview_id)` | 待加强 | 只允许确认后的写入，不让模型直接写文件 |
| P1 | `index_documents(paths/files)` | 可封装 `/rag/upload` | 用户确认后导入资料 |
| P2 | `summarize_document(path)` | 待实现 | 上传资料后的摘要、标签、学习建议 |
| P2 | `export_session(format)` | 待实现 | 学习记录导出为 Markdown / PDF / JSON |
| P3 | `browser_read(url)` | 未来可选 | RPA/browser automation 的只读起点 |

暂不建议加入：

- shell / Python execution tool：风险太高，容易越过本地安全边界。
- unrestricted HTTP request tool：会绕过现有 SSRF / URL safety。
- generic file write tool：应通过 memory preview / commit 和 safe writer 间接完成。
- email / calendar / payment / social posting tool：不属于当前学习助手主场景，且需要更强权限隔离。

开源项目参考：

| 项目 | 可借鉴点 | 不直接照搬的原因 |
|---|---|---|
| [LangGraph](https://langchain-ai.github.io/langgraph/tutorials/workflows/) | `ToolNode`、graph node/edge、human-in-the-loop、tool execution events | 当前项目先用轻量本地 workflow，不引入整套 LangChain 依赖 |
| [Semantic Kernel](https://learn.microsoft.com/en-us/semantic-kernel/agents/plugins/) | plugin/function 描述、OpenAPI/native code/MCP server 三类工具来源 | 项目主栈是 Python 本地应用，不需要 .NET 风格 plugin 体系 |
| [LlamaIndex](https://github.com/run-llama/llama_index) | 把 retriever/query engine 包成 agent tools | Study Agent 已有本地 RAG，先保留自有实现 |
| [Dify](https://docs.dify.ai/en/use-dify/nodes/agent) | Agent 节点、工具授权、参数校验、workflow 节点变量传递 | Dify 更像完整平台；这里只参考交互模型 |
| [Flowise](https://github.com/FlowiseAI/Flowise) | 可视化 tool/workflow 组合和 API 化输出 | 低代码执行平台安全面更大，不适合默认内嵌 |
| [CrewAI](https://github.com/crewAIInc/crewAI) | agents/tasks/tools 的角色分工表达 | 当前不需要多 agent 团队协作优先级 |

最小实现建议：

```text
src/tools/
├── registry.py        # implemented: ToolSpec / ToolResult / ToolPermission / allowlisted registry
├── local_knowledge.py # implemented: first controlled read-only tool
├── news_search.py     # planned: wraps news pipeline
├── session_lookup.py  # planned: searches local session logs
├── memory_update.py   # planned: preview-first memory updates
└── rag_admin.py       # planned: inspect/index documents
```

FastAPI 可先补：

```text
GET  /tools
POST /tools/{tool_name}/preview
POST /tools/{tool_name}/call
```

其中 `/preview` 返回权限、参数摘要、预期副作用和是否需要确认；`/call` 只执行 allowlisted、已确认或只读工具。

### P9: Web UI

Current status: P9 is implemented under `frontend/` with React + Vite + TypeScript. It provides the three-column workspace, non-streaming chat input, document upload/indexing flow, source result table, workflow timeline detail panel, controlled local-knowledge tool preview/call controls, memory status panel and Vite dev proxy. Streaming chat, auth/CORS, production static hosting and richer memory write confirmation remain P10 hardening work.

前端建议进入 P9 后使用 React + Vite + TypeScript。理由是：

- React 生态更适合后续做聊天流、引用面板、调试抽屉和状态组件拆分。
- Vite 开发服务器启动快，生产构建输出静态 `dist`，可以独立部署，也可以由 FastAPI 挂载静态目录。
- TypeScript 能把 API response、RAG source、memory preview、session row、workflow event 等数据结构固定下来，减少前后端联调时的隐性字段漂移。

当前页面覆盖：

| 页面 | 作用 |
|---|---|
| 聊天页 | 已实现：主交互，非 streaming |
| 文件上传 | 已实现：multipart 上传并重建本地 RAG index |
| 知识库状态 | 已实现：documents / chunks / vector backend 状态 |
| 来源引用面板 | 已实现：RAG source table、score、matched terms 和 source path |
| Workflow 时间线 | 已实现：recent runs、run detail 和 event rows |
| Tool control | 已实现：`retrieve_local_knowledge` preview / call，call 写 workflow audit |
| Memory 状态 | 已实现：preview-first 状态展示；写入确认 UI 仍待 P10 扩展 |
| 设置页 | 未实现：Provider、模型、API Key、本地路径仍在后续规划 |

前端交互重点：

- 聊天主窗口目前是 non-streaming；streaming response 放入 P10。
- 右侧面板已经同时显示 RAG sources、workflow timeline、tool preview/call 和 memory candidate。
- Tool use 已经通过 preview-first UI 和 workflow audit 可见；未来写工具仍必须显式确认。
- Memory 写入、未来 browser automation 等有副作用动作必须走 confirm UI；RAG 导入当前由用户手动选择文件触发。

### P10: Hardening, Deployment & MCP

目标：让项目从本地 demo 进入可演示、可部署、可维护的工程状态。

| 能力 | 说明 |
|---|---|
| streaming | `/chat` 支持 SSE 或 WebSocket streaming |
| auth | 本地 token / password gate，避免 LAN 暴露后被误用 |
| CORS | 明确允许的前端 origin，默认不开放公网 |
| Docker | FastAPI + frontend dist + optional Chroma 的本地部署组合 |
| OpenAPI examples | 为 `/chat`、`/tools`、`/workflows`、`/memory` 补请求示例 |
| MCP server | 可选只读 MCP server，把本地知识库、session lookup、RAG status 暴露给外部 AI 客户端 |
| observability | trace_id、latency、token usage、provider fallback、tool call status |
| CI coverage | API / workflow / tool registry / frontend smoke tests |

MCP 判断：

- **需要 MCP server 的场景**：希望 Claude Desktop、Codex、Cursor 或其他 MCP client 直接查询 Study Agent 的本地知识、历史 session、RAG index 状态，或触发只读检索工具。
- **暂不需要 MCP client 的场景**：当前内部前端和 FastAPI 不依赖外部工具生态，直接调用 `/chat`、`/tools`、`/workflows` 更简单。
- **建议顺序**：先做内部 `ToolSpec` / registry / audit，再从同一份 registry 生成 OpenAPI 和 MCP server。不要让 MCP 成为第二套工具定义。

MCP 暴露范围：

| MCP primitive | 建议内容 | 边界 |
|---|---|---|
| Resources | RAG index status、session summary、memory read-only views | 不暴露原始敏感文件全文，必要时截断 |
| Tools | `retrieve_local_knowledge`、`inspect_rag_index`、`lookup_session`、只读 `search_news` | 默认只读；写 memory / index / browser action 不进入第一版 |
| Prompts | 学习复盘、资料问答、带引用回答模板 | 只做模板，不包含密钥或本地私密路径 |

开源参考：

- [Model Context Protocol Python SDK](https://github.com/modelcontextprotocol/python-sdk)：官方 Python SDK，支持 server/client、tools、resources、prompts。
- [MCP SDK docs](https://modelcontextprotocol.io/docs/sdk)：官方 SDK 入口。
- [MCP reference servers](https://github.com/modelcontextprotocol/servers)：参考实现和社区 server 列表。
- [OpenAI Agents SDK MCP guide](https://openai.github.io/openai-agents-python/mcp/)：说明接 MCP 前要判断工具在哪里执行、使用什么 transport。

### P11: Optional RPA / Browser Automation

RPA 适合后续自动操作无 API 的外部系统，例如登录教务系统、下载课件、填网页表单、批量整理浏览器资料。但它不进入当前主线，应等 chat / RAG / memory / news workflow 可观察之后，再作为可选 adapter 接入。

原则：

- 只读优先：先实现 `browser_read(url)`，不急着提交表单或点击危险按钮。
- 白名单域名：只允许用户配置过的学习网站或公开资料站。
- 人工确认：登录、表单提交、删除、付款、发信等状态变更动作必须确认。
- 全量 audit：记录 URL、动作类型、输入摘要、结果、失败原因和截图/HTML artifact 路径。
- 可参考 Playwright、browser-use、Robot Framework、Robocorp RPA Framework；不把 n8n / Flowise 这类可执行低代码平台直接暴露到公网或默认启用。

## 10. UI 与产品体验

推荐布局：

```text
左侧：会话 / 知识库 / 模式
中间：聊天主窗口
右侧：记忆状态 / 引用来源 / 调试信息
底部：输入框 + 工具按钮
```

回答卡片可以拆为：

```text
回答正文
关键点
引用来源
建议下一步
可写入记忆候选
```

必须补齐的状态：

| 状态 | 示例 |
|---|---|
| loading | 正在思考、正在检索 |
| error | API 失败、网络失败、文件解析失败 |
| empty | 没有知识库、没有会话 |
| success | 上传成功、写入成功 |
| warning | 检索结果不足、上下文过长 |
| step timeline | workflow 当前步骤、耗时、失败原因、可重试动作 |

## 11. 测试体系

必备测试：

| 测试类型 | 测试内容 |
|---|---|
| Provider 测试 | OpenAI-compatible 调用、Mock Provider |
| Memory 测试 | 读取、写入、diff、备份、回滚 |
| RAG 测试 | chunk、入库、检索、引用来源 |
| Tool 测试 | 新闻检索、文件读取、摘要 |
| ContextBuilder 测试 | 不同模式下上下文是否正确 |
| API 测试 | /chat、/health、/rag/query、/rag/upload、/rag/status、/memory/preview、/memory/commit、/sessions |
| Workflow 测试 | run/step 状态转换、事件持久化、失败重试边界 |
| UI smoke 测试 | 页面能打开、基本交互不崩 |

最关键的是 Mock Provider。真实模型用于演示和实际使用，Mock Provider 用于自动测试和 CI，避免测试依赖外部 API。

## 12. 文档体系补齐

建议 docs 目录补齐：

```text
docs/
├─ 01_项目立项与定位.md
├─ 02_需求说明_PRD.md
├─ 03_架构设计.md
├─ 04_长期记忆设计.md
├─ 05_RAG设计.md
├─ 06_Provider抽象设计.md
├─ 07_API接口文档.md
├─ 08_测试计划与测试报告.md
├─ 09_部署说明.md
├─ 10_Release_Notes.md
└─ 11_待升级补强清单.md
```

其中最适合支撑简历的是：

- 架构设计
- 长期记忆设计
- RAG 设计
- Provider 抽象设计
- 测试报告
- 部署说明

## 13. 推荐版本路线

### v0.7：稳定化版本

目标：先把现有原型收口。

任务：

1. 抽离 core/chat_engine.py
2. 抽离 memory_manager.py
3. 抽离 provider 层
4. 优化 memory 缓存
5. 优化 session 日志批量写入
6. 补 Mock Provider
7. 补基础测试
8. 整理 README

### v0.8：RAG 闭环版本

目标：升级为真正的学习资料助手。

任务：

1. 支持 Markdown / txt / PDF 上传
2. 文档切分 chunk
3. 向量检索
4. 回答附来源
5. 知识库列表
6. RAG 回归测试
7. 编写 docs/RAG设计.md

### v0.9：FastAPI 服务化版本

目标：从 Streamlit 原型转向软件系统。

任务：

1. [x] 增加 FastAPI
2. [x] 实现 /health
3. [x] 实现 /chat（当前为非流式）
4. [x] 实现 /rag/upload
5. [x] 实现 /rag/query
6. [x] 实现 /memory/preview
7. [x] 实现 /memory/commit
8. [x] 补 API 测试
9. [x] 扩展 evaluation sets foundation：retrieval / grounding / tool routing / workflow / safety
10. [x] 补 execution foundation 第一版：workflow JSONL timeline + controlled local-knowledge tool registry
11. [ ] 补 streaming chat / auth / CORS / Docker Compose

### v1.0：前端产品化版本

目标：能演示、能截图、能部署、能写简历。

任务：

1. React + Vite + TypeScript 前端
2. 聊天页
3. 文件上传页
4. 知识库列表页
5. Workflow 时间线
6. 来源引用面板
7. 会话历史
8. 设置页
9. Docker 一键启动
10. 完整 Release Notes

### v1.1：工程硬化版本

目标：把服务层、前端和本地运行环境收口成可维护版本。

任务：

1. streaming chat
2. auth / CORS / local deployment guard
3. Docker Compose
4. OpenAPI examples
5. 可选 read-only MCP server
6. trace_id / token usage / latency / provider fallback logs
7. eval / workflow / tool / frontend smoke tests

### v1.2+：可选 RPA / Browser Automation

目标：在不削弱本地安全边界的前提下，把 Study Agent 扩展到少量“无 API 的外部学习系统”。

任务：

1. 明确 RPA 只作为可选 adapter，不作为核心聊天 / RAG / memory 主路径。
2. 先实现只读浏览器自动化：打开白名单网站、读取公开页面、下载用户确认的资料。
3. 对登录、表单提交、删除、付款、发信等状态变更动作强制人工确认。
4. 所有浏览器动作写入 workflow audit，包括 URL、动作类型、输入摘要、结果和失败原因。
5. 优先评估 Playwright / browser-use；传统桌面 RPA 可参考 Robot Framework / Robocorp RPA Framework。

## 14. 简历包装方向

可以包装为：

> Study Agent：本地优先的 AI 学习助理与知识库系统。基于 FastAPI、OpenAI-compatible Provider、RAG、Markdown 长期记忆和前端聊天界面，实现多模型接入、学习资料检索、长期记忆写回、来源引用展示和会话归档；设计 Provider 抽象、ContextBuilder、MemoryManager 和 ToolRouter 等模块，并通过 Mock Provider、RAG 回归测试和 CI 保证核心链路稳定。

核心亮点：

1. 多模型 Provider 抽象
2. 长期记忆写回与人工确认机制
3. RAG 知识库检索与来源引用
4. Workflow event timeline 与可观察执行链路
5. FastAPI + 前端 + Docker + 测试的工程化交付

## 15. 当前最建议执行的下一步

当前主流程已经可以按 FastAPI 边界继续收口：

```text
用户输入
→ Streamlit 或 Web UI 接收
→ FastAPI /chat
→ memory 读取
→ context 构建
→ local knowledge tool 判断
→ provider 调用
→ response 输出
→ session 记录
→ memory 写回确认
→ workflow timeline 展示步骤与证据
```

推荐推进顺序：

1. [x] Provider 抽象稳定
2. [x] Memory / ContextBuilder 基础稳定
3. [x] SessionLogger 批量写入
4. [x] RAG MVP 与 local knowledge tool
5. [x] FastAPI 基础服务层
6. [x] Evaluation sets and quality gates foundation
7. [x] Workflow run / step / event timeline + controlled tool registry first slice
8. [x] React + Vite + TypeScript 前端
9. [ ] streaming chat / auth / CORS / Docker / optional MCP server
10. [ ] 可选 RPA / browser automation adapter
