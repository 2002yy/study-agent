# Migration Plan — Architecture V2

> 从当前 `bc9d81c` 状态出发，分 5 批迁移到目标架构。  
> 每批独立可发布、可验证、可回滚。

## Implementation status — 2026-06-19

- Batch 1: operation registry is active for chat, group, tool, and news scopes. NewsWorkspace no longer owns a separate run counter or AbortController.
- Batch 2: Workspace reducer/provider skeleton exists, and active chat/group/news ids are now reducer-owned in App.
- Batch 3: FastAPI is split into `src/api/app.py`, `src/api/routes/*`, `src/api/models/*`, and `src/application/helpers.py`; compatibility re-exports remain in `src/api/__init__.py`.
- Batch 4: SQLite runtime schema and repository foundation exists for ChatThread/ChatTurn and NewsRun. Existing APIs still use the legacy runtime stores until the next migration step.

## 总览

| 批次 | 内容 | 预计改动范围 | 风险 |
|------|------|------------|------|
| 1 | 停止状态膨胀 + operation registry | App.tsx (~100行), 3个新文件 | 低 |
| 2 | 前端 Workspace Reducer | App.tsx 拆为 reducer + controllers | 中 |
| 3 | 拆后端 api.py | api.py → routes + services | 低（不改行为） |
| 4 | SQLite 接管运行时实体 | 新 infrastructure/sqlite/ | 中 |
| 5 | 重新实现 continuation 和恢复 | ChatTurn 实体 + 完整生命周期 | 中高 |

## Batch 1: 停止状态膨胀 + operation registry + 修已知 bug

**目标**: 不再新增 useState/useRef/generation，现有 bugs 修复，建立 operation registry。

### 1.1 修复已发现的不变量违反

| Bug | 修复 |
|-----|------|
| onDone 检查 wechatGenerationRef (App.tsx:1031) | 改为 chatGenerationRef |
| previewTool 检查 wechatGenerationRef (App.tsx:1181,1185) | 改为 toolGenerationRef |
| callTool 检查 wechatGenerationRef (App.tsx:1261,1268) | 改为 toolGenerationRef |
| sendSingleChat 未 abort 旧 controller | 在 new AbortController() 前加旧 abort |

### 1.2 实现 operationRegistry

新建 `frontend/src/app/operationRegistry.ts`:

```typescript
type OperationScope = 
  | "chat" | "group" | "news" | "tool"
  | "rag-search" | "rag-upload" | "memory" | "session-transition";

type OperationState = {
  id: string;
  scope: OperationScope;
  status: "running" | "cancelling" | "completed" | "failed";
  ownerId?: string;
  controller: AbortController;
  generationId: number;
  startedAt: number;
};

// 单例
const registry = {
  operations: new Map<string, OperationState>(),
  
  start(scope, ownerId?): { operationId: string; controller: AbortController; generationId: number },
  cancel(scope): void,
  cancelAll(): void,
  isCurrent(operationId, generationId): boolean,
  getActive(scope): OperationState | null,
};
```

### 1.3 迁移现有 generation ref 到 registry

将 4 个 generation ref 的使用替换为 registry 调用:

```
chatGenerationRef.current++  →  registry.start("chat")
chatGenerationRef.current    →  registry.getActive("chat")?.generationId
wechatGenerationRef.current++ →  registry.start("group")
newsGenerationRef.current++   →  registry.start("news")
toolGenerationRef.current++   →  registry.start("tool")
cancelWorkspaceRuns()         →  registry.cancelAll()
```

### 1.4 输出物

- `frontend/src/app/operationRegistry.ts` (新建)
- `frontend/src/app/types.ts` (OperationScope, OperationState 类型)
- `frontend/src/App.tsx` (修改: 替换 generation ref 为 registry，修 bug)

### 1.5 验证

- TypeScript `tsc -b` 零错误
- vitest 全部通过
- 手动: 单聊发送 → 中断 → 群聊发送 → 两者互不干扰
- 手动: 工具预览 → 发送单聊 → 工具预览结果不受影响

---

## Batch 2: 前端 Workspace Reducer + feature controllers

**目标**: App.tsx 从 1800 行降到 ~300 行，所有业务逻辑移到 controllers。

### 2.1 建立 workspaceReducer

```typescript
// frontend/src/app/workspaceReducer.ts
type WorkspaceAction = 
  | { type: "CHAT_SEND"; ... }
  | { type: "CHAT_TOKEN"; ... }
  | { type: "CHAT_DONE"; ... }
  | { type: "SESSION_RESTORE"; ... }
  | ...;

type WorkspaceState = {
  // Chat thread
  chatMessages: ChatMessage[];
  chatSessionId?: string;
  lastChat: ChatResponse | null;
  streamRecovery: StreamRecovery | null;
  
  // Group thread
  groupThreadId?: string;
  groupContent: string;
  
  // News
  newsState: NewsWorkspaceState;
  
  // UI
  input: string;
  wechatInput: string;
  newsQuery: string;
  
  // Settings
  chatSettings: ChatSettings;
  ragSettings: RagSettings;
  ragEnabled: boolean;
  
  // Operations
  operations: Record<string, boolean>; // scope → isRunning
};
```

### 2.2 建立 feature controllers

每个 controller 是一个 hook:

```
useChatController(dispatch, state) → { send, stop, retry, continue }
useGroupChatController(dispatch, state) → { send, reset, markRead }
useNewsController(dispatch, state) → { search, enrich, digest, discuss }
useToolController(dispatch, state) → { preview, call }
useSessionController(dispatch, state) → { new, restore, archive }
```

### 2.3 建立 serverQueryCache

对服务器数据（sessions, ragStatus, memoryStatus 等），用简单的 cache:

```typescript
function useServerQuery<T>(key: string, fetcher: () => Promise<T>, deps: unknown[]): {
  data: T | null;
  isLoading: boolean;
  error: string | null;
  refresh: () => Promise<void>;
}
```

### 2.4 拆分 App.tsx

```
App.tsx → 
  WorkspaceProvider.tsx (context + reducer)
  AppShell.tsx (页面装配)
  features/chat/chatController.ts
  features/group-chat/groupChatController.ts
  features/news/newsController.ts
  features/sessions/sessionController.ts
  features/tools/toolController.ts
```

### 2.5 输出物

- `frontend/src/app/WorkspaceProvider.tsx`
- `frontend/src/app/workspaceReducer.ts`
- `frontend/src/app/serverQueryCache.ts`
- controller hooks × 6
- AppShell 简化

### 2.6 验证

- TypeScript 零错误，vitest 全部通过
- 页面行为与迁移前完全一致
- localStorage 恢复正常
- Session 切换正常

---

## Batch 3: 拆后端 api.py

**目标**: api.py 从 2095 行降到 ~200 行。不改 API 行为，只移动代码。

### 3.1 拆分策略

```
src/api.py (2095 行)
  ↓
src/api/
  app.py          (~100 行: FastAPI 创建, middleware, mount)
  dependencies.py (~80 行: get_session, get_modes 等 Depends)

src/api/routes/
  chat.py         (chat_stream_endpoint, commit_turn_endpoint)
  sessions.py     (list, detail, new, archive, flush)
  group_chat.py   (wechat endpoints)
  news.py         (news endpoints)
  rag.py          (RAG endpoints)
  memory.py       (memory endpoints)
  tools.py        (tool endpoints)
  settings.py     (runtime settings)
  health.py       (health endpoint)

src/application/
  chat_service.py
  session_service.py
  group_chat_service.py
  news_service.py
  rag_service.py
  memory_service.py
  tool_service.py
```

### 3.2 Pydantic 模型迁移

```
src/api/models/
  chat.py
  session.py
  rag.py
  ...
```

或保留在各自 route 文件顶部（如 FastAPI 惯例）。

### 3.3 输出物

- `src/api/` 目录树
- `src/application/` 目录树  
- `src/api.py` 改为 re-export 或直接删除

### 3.4 验证

- pytest 全部通过（相同测试集）
- API 行为不变（请求/响应格式完全一致）
- 导入路径正确

---

## Batch 4: SQLite 接管运行时实体

**目标**: ChatThread、ChatTurn、GroupThread、GroupMessage、NewsRun、ToolRun 等运行时实体从进程内存/文件迁移到 SQLite。

### 4.1 Schema 设计

```sql
CREATE TABLE chat_threads (
  id TEXT PRIMARY KEY,
  status TEXT NOT NULL DEFAULT 'active',
  settings_snapshot TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  version INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE chat_turns (
  id TEXT PRIMARY KEY,
  thread_id TEXT NOT NULL REFERENCES chat_threads(id),
  user_message TEXT NOT NULL,
  assistant_message TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT 'pending',
  role TEXT NOT NULL,
  mode TEXT NOT NULL,
  model TEXT NOT NULL,
  route_snapshot TEXT NOT NULL DEFAULT '{}',
  rag_snapshot TEXT NOT NULL DEFAULT '{}',
  parent_turn_id TEXT,
  operation_id TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE group_threads (
  id TEXT PRIMARY KEY,
  status TEXT NOT NULL DEFAULT 'active',
  title TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL,
  archived_at TEXT,
  version INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE group_messages (
  id TEXT PRIMARY KEY,
  thread_id TEXT NOT NULL REFERENCES group_threads(id),
  speaker TEXT NOT NULL,
  content TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'committed',
  created_at TEXT NOT NULL
);

CREATE TABLE news_runs (
  id TEXT PRIMARY KEY,
  query TEXT NOT NULL,
  stage TEXT NOT NULL DEFAULT 'searched',
  status TEXT NOT NULL DEFAULT 'running',
  safe_mode INTEGER NOT NULL DEFAULT 0,
  items TEXT NOT NULL DEFAULT '[]',
  digest TEXT NOT NULL DEFAULT '',
  source_block TEXT NOT NULL DEFAULT '',
  article_coverage TEXT NOT NULL DEFAULT '{}',
  warnings TEXT NOT NULL DEFAULT '[]',
  group_thread_id TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE tool_runs (
  id TEXT PRIMARY KEY,
  tool_name TEXT NOT NULL,
  args_hash TEXT NOT NULL,
  args TEXT NOT NULL DEFAULT '{}',
  status TEXT NOT NULL DEFAULT 'preview',
  preview TEXT,
  result TEXT,
  reason TEXT NOT NULL DEFAULT '',
  elapsed_ms INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL
);
```

### 4.2 Repository 接口

```python
# src/infrastructure/sqlite/chat_repository.py
class ChatRepository:
    def create_thread(self, thread: ChatThread) -> ChatThread: ...
    def get_thread(self, thread_id: str) -> ChatThread | None: ...
    def archive_thread(self, thread_id: str) -> None: ...
    def create_turn(self, turn: ChatTurn) -> ChatTurn: ...
    def update_turn_reply(self, turn_id: str, reply: str, status: str) -> None: ...
    def get_turn(self, turn_id: str) -> ChatTurn | None: ...
    def get_thread_turns(self, thread_id: str) -> list[ChatTurn]: ...
```

### 4.3 Markdown 导出

在 SQLite 写入成功后，自动导出对应 Markdown 文件：

```python
# src/infrastructure/markdown_export/session_exporter.py
def export_session_to_markdown(thread_id: str) -> Path: ...
def export_group_to_markdown(thread_id: str) -> Path: ...
def export_news_to_markdown(run_id: str) -> Path: ...
```

### 4.4 迁移现有数据

一次性脚本将：
- `logs/sessions/*.md` → SQLite chat_turns
- `chat/wechat_group.md` → SQLite group_messages
- memory/*.md 保持不变（长期记忆）

### 4.5 输出物

- `src/infrastructure/sqlite/` 完整实现
- `src/infrastructure/markdown_export/` 导出器
- `scripts/migrate_to_sqlite.py`
- 所有 repository 接口和实现

### 4.6 验证

- 所有现有 session log 可读取
- 群聊内容可读取和续写
- 新建 session/group/news 正确写入 SQLite
- Markdown 导出与旧格式兼容
- pytest 全部通过

---

## Batch 5: 重新实现 continuation 和恢复

**目标**: 基于真实 Turn ID，ChatTurn 完整生命周期。

### 5.1 Turn 生命周期

```
POST /chat/stream
  → 后端创建 pending ChatTurn
  → 立即返回 { thread_id, turn_id, operation_id }
  → SSE 输出 token...
  → 完成: status = "completed"
  → 中断: status = "interrupted" (partial reply 已保存)
  → 继续: POST /chat/stream { continuation_of_turn_id: turn_id }
    → 找到 interrupted Turn
    → 继续生成 (同一 turn_id)
    → 追加 reply
    → 完成: status = "completed"
```

### 5.2 恢复流程

```
POST /sessions/{id}/restore
  → 返回 { thread_id, turns[], settings_snapshot }
  → 前端用线程内所有 turns 重建 messages
  → 如果有 status = "interrupted" 的 turn
    → 显示 "继续生成" 和 "重试" 按钮
    → 继续 = 同一 turn
    → 重试 = 新 turn (parent_turn_id)
```

### 5.3 前端改动

- `streamRecovery` 不再需要在前端临时保存 reply
- `buildContinuationHistory` 逻辑简化到后端
- `commitTurn` 从显式调用变为 streaming 流程内置（后端自动处理）

### 5.4 输出物

- 修改 `POST /chat/stream` 行为
- 新增 `POST /sessions/{id}/restore` endpoint
- 简化前端 recover/continue 逻辑
- 移除前端 `streamRecovery` state

### 5.5 验证

- 首次提问 → 中断 → 页面显示 "继续生成"
- 继续生成 → 同一 turn 的 assistant_message 被更新
- 刷新页面 → 恢复 session → 显示正确的 interrupted/continued 状态
- 中断 → 重试 → 创建新 turn（parent_turn_id 指向旧 turn）
- 不应出现重复用户消息

## 禁止在迁移期间做的事

1. **不新增** useState 到 App.tsx
2. **不新增** generation ref
3. **不新增** AbortController ref
4. **不在** api.py 中新增 endpoint（新 endpoint 必须放 routes/）
5. **不在** catch 块中静默丢弃错误（除非是 AbortError）
6. **不绕过** operationRegistry 直接操作 generation ref
7. **不新增** 全局单例（用 Depends 注入）

## 每批完成标准

- TypeScript `tsc -b` 零错误
- vitest 全部通过
- pytest 全部通过（排除 LLM 依赖的 2 个）
- 手动冒烟: 单聊 → 群聊 → 新闻 → 工具 → Session 切换
- `git diff --stat` 在预期范围内
