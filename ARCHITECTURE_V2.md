# ARCHITECTURE_V2.md

> Study Agent 目标架构  
> 基于对当前 `App.tsx` (1800 行)、`api.py` (2095 行) 的结构诊断  
> 不推倒重写，分批迁移

## 1. 当前问题根源

### 1.1 前端无单一状态拥有者

当前 `App.tsx` 维护 **26 个 useState** + **4 个 generation useRef** + **3 个 AbortController useRef** + **localStorage**。虽然定义了 `WorkspaceState`，但它只是 localStorage 序列化结构，不是实际运行状态的唯一来源。

```
App useState (26个)
  + 子组件 useState (ChatPanel, WechatPanel, NewsWorkspace, ...)
  + localStorage (SESSION_STORAGE_KEY)
  + ApiSnapshot (Promise.allSettled 批量 fetch)
  + 后端 Session (_state dict)
  + 后端文件 (config/*.yaml, chat/wechat_group.md, memory/*.md)
```

同一件事存在多份副本。

### 1.2 generation ref 承担了不该承担的职责

当前 `workspaceGeneration` 拆成了 4 个 ref，但：
- 回调里仍然用错 ref（onDone 用了 `wechatGenerationRef`，previewTool 用了 `wechatGenerationRef`）
- 新建操作时没有 abort 旧 controller
- 没有统一的 operation 注册/查询/取消机制

### 1.3 ID 分开了但领域实体没拆开

```
singleChatSessionId → 对应真实 Session（但 Session 不是 ChatThread）
wechatThreadId → 指向全局单文件群聊，不是独立 GroupThread
newsRunId → 前端局部自增，不是后端实体
```

### 1.4 后端一个巨型模块

`api.py` 2095 行，包含所有 endpoint 定义、Pydantic 模型、部分业务逻辑、文件路径常量。

### 1.5 持久化来源过多

```
浏览器 localStorage
Python _state (进程内存)
logs/current/*.md
logs/sessions/*.md
memory/*.md
config/*.yaml
chat/wechat_group.md (单文件群聊)
RAG JSON 索引
外部向量后端
```

## 2. 目标架构

### 2.1 整体分层

```
┌──────────────────────────────────────────────────────┐
│ React Frontend                                        │
│                                                       │
│ WorkspaceProvider (唯一状态源)                         │
│   ├── workspaceReducer (dispatch actions)             │
│   ├── operationRegistry (start/cancel/cancelAll)      │
│   └── serverQueryCache (TanStack Query 或自建)         │
│                                                       │
│ Feature Controllers (每个 feature 一个 controller)     │
│   ├── chatController.ts                               │
│   ├── groupChatController.ts                          │
│   ├── newsController.ts                               │
│   ├── toolController.ts                               │
│   ├── memoryController.ts                             │
│   ├── ragController.ts                                │
│   └── sessionController.ts                            │
│                                                       │
│ View Components (纯展示)                              │
│   ├── ChatPanel.tsx                                   │
│   ├── WechatPanel.tsx                                 │
│   ├── NewsWorkspace.tsx                               │
│   └── ...                                             │
└──────────────────────────────────────────────────────┘
          │
          ▼
┌──────────────────────────────────────────────────────┐
│ FastAPI Backend                                       │
│                                                       │
│ api/routes/ (thin, 只做参数提取和响应格式化)           │
│   ├── chat.py                                         │
│   ├── sessions.py                                     │
│   ├── group_chat.py                                   │
│   ├── news.py                                         │
│   ├── rag.py                                          │
│   ├── memory.py                                       │
│   ├── tools.py                                        │
│   └── settings.py                                     │
│                                                       │
│ application/ (use cases, orchestration)               │
│   ├── chat_service.py                                 │
│   ├── session_service.py                              │
│   ├── group_chat_service.py                           │
│   ├── news_service.py                                 │
│   ├── rag_service.py                                  │
│   ├── memory_service.py                               │
│   └── tool_service.py                                 │
│                                                       │
│ domain/ (纯数据，无依赖)                               │
│   ├── chat.py                                         │
│   ├── session.py                                      │
│   ├── group_chat.py                                   │
│   ├── news.py                                         │
│   ├── memory.py                                       │
│   ├── retrieval.py                                    │
│   └── operation.py                                    │
│                                                       │
│ infrastructure/ (外部依赖)                             │
│   ├── sqlite/ (repository implementations)            │
│   ├── markdown_export/ (人类阅读导出)                   │
│   ├── rag/ (检索索引)                                  │
│   ├── llm/ (LLM 调用封装)                              │
│   └── filesystem/ (safe_writer 等)                    │
└──────────────────────────────────────────────────────┘
```

### 2.2 前端目录结构（目标）

```
frontend/src/
├── app/
│   ├── AppShell.tsx           # 页面装配（~50行）
│   ├── WorkspaceProvider.tsx  # Context + reducer
│   ├── workspaceReducer.ts    # 所有状态变更的唯一入口
│   └── operationRegistry.ts   # 统一异步操作管理
│
├── features/
│   ├── chat/
│   │   ├── chatController.ts  # sendSingleChat, stop, retry, continue
│   │   ├── chatApi.ts         # sendChatStream, commitTurn
│   │   ├── chatReducer.ts     # messages, lastChat, streamRecovery
│   │   └── components/        # ChatPanel, MarkdownMessage, RoleAvatar
│   │
│   ├── sessions/
│   │   ├── sessionController.ts
│   │   └── sessionApi.ts
│   │
│   ├── group-chat/
│   │   ├── groupChatController.ts
│   │   ├── groupChatApi.ts
│   │   └── components/
│   │
│   ├── news/
│   │   ├── newsController.ts
│   │   ├── newsApi.ts
│   │   └── components/
│   │
│   ├── rag/
│   │   ├── ragController.ts
│   │   ├── ragApi.ts
│   │   └── components/
│   │
│   ├── memory/
│   │   ├── memoryController.ts
│   │   ├── memoryApi.ts
│   │   └── components/
│   │
│   ├── tools/
│   │   ├── toolController.ts
│   │   ├── toolApi.ts
│   │   └── components/
│   │
│   └── settings/
│       ├── settingsController.ts
│       └── components/
│
├── shared/
│   ├── apiClient.ts           # fetch 封装，SSE 解析
│   ├── errors.ts              # 错误类型和转换
│   ├── ids.ts                 # ID 生成
│   └── types.ts               # 所有 TypeScript 类型
```

### 2.3 后端目录结构（目标）

```
src/
├── api/
│   ├── app.py                 # FastAPI 实例创建，中间件，静态文件
│   ├── dependencies.py        # Depends() 注入
│   └── routes/
│       ├── chat.py            # POST /chat/stream
│       ├── sessions.py        # GET/POST /sessions/...
│       ├── group_chat.py      # /wechat/...
│       ├── news.py            # /news/...
│       ├── rag.py             # /rag/...
│       ├── memory.py          # /memory/...
│       ├── tools.py           # /tools/...
│       └── settings.py        # /runtime/settings
│
├── application/
│   ├── chat_service.py        # 单聊编排: route → rag → prompt → stream
│   ├── session_service.py     # session CRUD, flush, archive
│   ├── group_chat_service.py  # 群聊生命周期
│   ├── news_service.py        # 新闻 pipeline 编排
│   ├── rag_service.py         # RAG 查询和索引
│   ├── memory_service.py      # 记忆预览和提交
│   └── tool_service.py        # 工具预览和执行
│
├── domain/
│   ├── chat.py
│   ├── session.py
│   ├── group_chat.py
│   ├── news.py
│   ├── memory.py
│   ├── retrieval.py
│   └── operation.py
│
├── infrastructure/
│   ├── sqlite/
│   │   ├── database.py
│   │   ├── chat_repository.py
│   │   ├── group_repository.py
│   │   ├── news_repository.py
│   │   ├── operation_repository.py
│   │   └── settings_repository.py
│   ├── markdown_export/
│   │   ├── session_exporter.py
│   │   ├── group_exporter.py
│   │   └── news_exporter.py
│   ├── rag/                   # (现有)
│   ├── llm/                   # (llm_client.py + llm_router.py)
│   └── filesystem/
│       ├── safe_writer.py     # (现有)
│       └── backup_manager.py  # (现有)
│
└── (保留现有模块: role_manager, router, wechat_format, etc.)
```

### 2.4 前端状态分类

**服务器状态**（使用 TanStack Query 或自建 cache）:
```
queryKey: ["chat-thread", threadId]
queryKey: ["group-thread", threadId]
queryKey: ["news-run", runId]
queryKey: ["memory-status"]
queryKey: ["rag-status"]
queryKey: ["sessions"]
queryKey: ["runtime-settings"]
```

**UI 状态**（workspaceReducer 管理）:
```
input, wechatInput, newsQuery
selectedPanel
isSending, isWechatBusy, isNewsBusy, etc.
streamRecovery
uploadState
error messages
```

**状态归属原则:**
- 服务器返回的 → 以服务器为准，放 cache
- 用户输入的 → UI 状态
- 从服务器衍生但需要前端展示的 → UI 状态（从 cache 读取）
- localStorage → 只用于页面恢复，不用于运行时权威来源

### 2.5 异步操作设计

```typescript
type OperationScope =
  | "chat"
  | "group"
  | "news"
  | "rag-search"
  | "rag-upload"
  | "tool"
  | "memory"
  | "session-transition";

type OperationState = {
  operationId: string;
  scope: OperationScope;
  status: "idle" | "running" | "cancelling" | "completed" | "failed";
  ownerId?: string;
  abortController: AbortController;
};

// 注册器 API
const registry = {
  start(scope: OperationScope, ownerId?: string): { operationId: string; controller: AbortController },
  cancel(scope: OperationScope): void,
  cancelAll(): void,
  isRunning(scope: OperationScope): boolean,
  getActive(scope: OperationScope): OperationState | null,
};
```

**规则:**
- `start("chat")` → 自动 cancel 旧 chat operation
- `start("group")` → 自动 cancel 旧 group operation
- 不同 scope 不互斥
- `cancelAll()` → 只在 session 切换时调用
- `start("session-transition")` → 在所有 cancelAll 完成后调用

### 2.6 持久化分层

```
┌──────────────────────────────────────┐
│ SQLite 数据库 (运行时权威来源)         │
│ - chat_threads, chat_turns           │
│ - group_threads, group_messages      │
│ - news_runs                          │
│ - tool_runs                          │
│ - operations                         │
│ - settings_snapshots                 │
└──────────────────────────────────────┘
          │ 自动导出
          ▼
┌──────────────────────────────────────┐
│ Markdown 文件 (人类阅读/长期记忆)      │
│ - memory/*.md                        │
│ - logs/sessions/*.md (archive)       │
│ - chat/archive/*.md (group archive)  │
│ - news/audit/*.md                    │
└──────────────────────────────────────┘
          │ 配置
          ▼
┌──────────────────────────────────────┐
│ YAML 配置 (启动/运行态)               │
│ - config/runtime_state.yaml          │
│ - config/frontend_settings.yaml      │
│ - config/prompt_config.yaml          │
└──────────────────────────────────────┘
```

### 2.7 Workspace Reducer 设计

```typescript
type WorkspaceAction =
  | { type: "CHAT_SEND"; question: string }
  | { type: "CHAT_TOKEN"; token: string }
  | { type: "CHAT_ROUTE"; route: RouteInfo }
  | { type: "CHAT_RAG"; rag: RagInfo }
  | { type: "CHAT_DONE"; response: ChatResponse }
  | { type: "CHAT_INTERRUPT"; error: string }
  | { type: "CHAT_CONTINUE"; turnId: string }
  | { type: "GROUP_SEND"; message: string }
  | { type: "GROUP_REPLY"; reply: string }
  | { type: "GROUP_DONE"; response: WechatMessageResponse }
  | { type: "NEWS_SEARCH_RESULT"; items: NewsItem[] }
  | { type: "NEWS_ENRICH_RESULT"; items: NewsItem[] }
  | { type: "NEWS_DIGEST_RESULT"; digest: DigestState }
  | { type: "NEWS_DISCUSS_RESULT"; discussion: string }
  | { type: "SESSION_TRANSITION"; sessionId: string }
  | { type: "SESSION_RESTORE"; detail: SessionDetailResponse }
  | { type: "SETTINGS_UPDATE"; settings: Partial<ChatSettings> }
  | { type: "RAG_SETTINGS_UPDATE"; settings: Partial<RagSettings> }
  | { type: "INPUT_CHANGE"; text: string }
  | { type: "OPERATION_START"; scope: OperationScope }
  | { type: "OPERATION_END"; scope: OperationScope };

function workspaceReducer(state: WorkspaceState, action: WorkspaceAction): WorkspaceState {
  // 所有状态变更的单一入口
}
```

### 2.8 AppShell 目标形态

```tsx
export default function AppShell() {
  return (
    <WorkspaceProvider>
      <div className="app-shell">
        <Sidebar />
        <ChatPage />
        <Inspector />
        <ErrorBanner />
      </div>
    </WorkspaceProvider>
  );
}
```

AppShell 不再包含任何业务 handler。

## 3. 关键决策记录

### D1: 为什么选 SQLite 而不是 PostgreSQL
- 本地单用户应用
- 零运维
- 可以直接从 Python 和（未来）Electron 访问
- 容易导出为 Markdown

### D2: 为什么不做微服务
- 单用户本地应用
- 模块边界清晰即可
- 模块化单体 → 需要时分拆也容易

### D3: 为什么 Markdown 继续保留
- 人类可直接阅读
- Git 友好
- 不需要数据库工具就能看历史
- 作为 SQLite 的导出格式，不是主存储

### D4: 为什么是 workspaceReducer 而不是 Redux/Zustand
- React useReducer 零依赖
- 足够覆盖当前状态复杂度
- 如需迁移到 Zustand，reducer 逻辑可直接复用

## 4. 与当前代码的对照

| 当前 | 目标 | 迁移批次 |
|------|------|---------|
| App.tsx 1800 行 | AppShell 50 行 + feature controllers | Batch 2-3 |
| 26 个 useState | workspaceReducer + serverQueryCache | Batch 2 |
| 4 个 generation ref | operationRegistry | Batch 1 |
| api.py 2095 行 | routes/ + application/ | Batch 3 |
| session_logger._state | SQLite chat_turns | Batch 4 |
| chat/wechat_group.md | SQLite group_messages + export | Batch 4 |
| localStorage workspace | serverQueryCache + localStorage 仅用于恢复 | Batch 2 |
## Implementation status 2026-06-21: Chat/Session and Web GroupThread sealed

- Chat HTTP and SSE routes now call `ChatService`; they no longer import the `src.api` compatibility locator, the LLM client, or `session_logger`.
- `ChatThread` and `ChatTurn` are persisted through `RuntimeRepository` in SQLite before generation begins.
- Turn state transitions are now `pending -> streaming -> completed/interrupted`, and continuation updates the same Turn ID.
- Session list/detail/new/archive/flush now read from SQLite through `SessionService`.
- Legacy Markdown is imported into SQLite once. Current/archive Markdown files are compatibility exports and are no longer runtime truth.
- Schema changes use ordered migrations. Schema v3 adds Chat operation/archive ownership and recovery fields.
- Chat partial recovery carries the server-issued operation ID end to end; stale tabs cannot interrupt a newer continuation.
- Session detail keeps superseded Turns for audit while excluding them from the user-visible message projection.
- The React root now mounts `WorkspaceProvider`; Chat thread/messages/last response/interruption recovery are owned by its reducer and exposed through `chatController`.
- Chat/Session is sealed. Except for confirmed bugs, its service, state model, and controller are frozen while the next vertical slices migrate.
- Schema v4, `GroupRepository`, and `GroupChatService` now own Web GroupThread runtime state, message operation CAS, unread counts, reset/archive, recovery, and search.
- FastAPI WeChat routes use dependency-injected Group services and no longer import the `src.api` compatibility locator or write runtime Markdown. Legacy three-file state is imported once; Markdown remains archive output.
- `groupChatController` owns Web Group input, busy/error, optimistic stream, stop, mark-read, opening, and reset orchestration; `App.tsx` only wires it to the panel.
- News discuss remains a legacy NewsRun stage, but its Group output now enters SQLite only through `GroupChatService`.
- The legacy Streamlit WeChat UI remains on its compatibility file path and is not considered part of the sealed React/FastAPI runtime.
- NewsRun, ToolRun, Memory, and their existing persistence flows remain frozen on the legacy path and are not claimed as migrated.
