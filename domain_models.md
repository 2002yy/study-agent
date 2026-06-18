# 领域模型定义 (Domain Models)

> Study Agent v0.8 → v0.9 领域实体定义  
> 本文件定义系统真实实体、ID、生命周期，是架构 v2 的语义基础。

## 1. 总览

```
ChatThread (1) ────────── (*) ChatTurn
GroupThread (1) ───────── (*) GroupMessage
NewsRun (1) ────────────── (*) NewsStage
ToolRun (1) ────────────── (*) ToolStage
MemoryTransaction (1) ──── (*) MemoryUpdate
Session (1) ────────────── (*) SessionEntry
Workspace (1) ──────────── (*) Operation (关联上述实体)
RetrievalIndex (1) ─────── (*) IndexOperation
```

每个领域对象有明确的所有权、ID 生成方、生命周期、持久化路径。

## 2. ChatThread (单人对话线程)

```typescript
type ChatThread = {
  id: string;                // 后端生成，格式: "sthread-xxx" 或 UUID
  status: "active" | "archived";
  settings_snapshot: ChatSettingsSnapshot;
  created_at: string;        // ISO 8601
  updated_at: string;
  version: number;           // 乐观锁
};
```

```python
@dataclass
class ChatThread:
    id: str
    status: str  # "active" | "archived"
    settings_snapshot: dict
    created_at: datetime
    updated_at: datetime
    version: int
```

**规则：**
- ID 由后端在第一个 Turn 创建时分配，通过 SSE `session` event 立即返回前端
- 切换 Thread = 切换全部 ChatPanel 状态
- 一个 Workspace 同时最多一个 active ChatThread

## 3. ChatTurn (单轮对话)

```python
@dataclass
class ChatTurn:
    id: str                      # 后端生成，稳定 ID
    thread_id: str               # 所属 ChatThread
    user_message: str
    assistant_message: str       # 完整或部分
    status: str                  # "streaming" | "completed" | "interrupted" | "failed"
    role: str
    mode: str
    model: str
    route_snapshot: dict
    rag_snapshot: dict
    parent_turn_id: str | None   # continuation 的上游 turn
    operation_id: str | None
    created_at: datetime
    updated_at: datetime
```

**关键不变量：**
1. 一个用户问题只对应一个 ChatTurn
2. 中断 + 续写更新**同一个** ChatTurn，不改 user_message，只更新 assistant_message
3. Turn 完成时有稳定 ID，不可变
4. continuation_of_turn_id 指向被继续的 turn_id，不是用户问题文本

**生命周期：**
```
创建 (pending) → 流式输出中 (streaming) → 完成 (completed)
                                        → 中断 (interrupted)
                                            → 续写 (streaming → completed)
                                            → 重试 (新 Turn, parent_turn_id)
```

## 4. GroupThread (群聊线程)

```python
@dataclass
class GroupThread:
    id: str                      # 后端生成 UUID
    status: str                  # "active" | "archived"
    title: str
    created_at: datetime
    archived_at: datetime | None
    version: int
    message_count: int
    unread_count: int
```

```python
@dataclass
class GroupMessage:
    id: str                      # 后端生成
    thread_id: str
    speaker: str                 # "用户" | 角色名 | "群聊"
    content: str
    status: str                  # "committed" | "streaming" | "failed"
    created_at: datetime
```

**关键不变量：**
1. GroupThread ID 决定实际消息集合
2. 切换 GroupThread = 切换全部群聊面板内容
3. 失败 pending 消息不能混入已提交消息
4. 群聊内容不再以单一文件 `chat/wechat_group.md` 作为主状态源

**当前状态：**
- 当前群聊只有一个全局文件 `chat/wechat_group.md`
- 没有真实 GroupThread 概念
- 需要迁移到 SQLite + Markdown 导出

## 5. NewsRun (新闻检索运行)

```python
@dataclass
class NewsRun:
    id: str                      # 后端生成 UUID，不是前端自增 "news-1"
    query: str
    stage: str                   # "searched" | "enriched" | "digested" | "discussed"
    status: str                  # "running" | "completed" | "failed" | "cancelled"
    safe_mode: bool
    items: list[dict]
    digest: str
    source_block: str
    article_coverage: dict
    warnings: list[str]
    group_thread_id: str | None  # discuss 阶段后关联的 GroupThread
    created_at: datetime
    updated_at: datetime
```

**关键不变量：**
1. 每次搜索必须产生真实 NewsRun（后端分配 ID）
2. 后续阶段（enrich/digest/discuss）只能更新该 Run
3. safe_mode 跳过正文读取 → 必须成为可见状态字段
4. NewsRun 不修改单聊 Session ID
5. NewsRun ID 由后端 `/news/search` 返回，前端不再自增

**阶段迁移：**
```
search → (enrich) → (digest) → (discuss)
  │         │           │           │
  ▼         ▼           ▼           ▼
searched  enriched   digested   discussed
```

每个阶段可以单独失败，上游结果保留。

## 6. ToolRun (工具运行)

```python
@dataclass
class ToolRun:
    id: str                      # preview 时后端返回
    tool_name: str
    args: dict
    args_hash: str
    status: str                  # "preview" | "succeeded" | "failed" | "blocked"
    preview: dict | None
    result: dict | None
    reason: str
    elapsed_ms: int
    created_at: datetime
```

**关键不变量：**
1. 预览返回 `run_id`，正式调用必须传入该 `run_id`
2. 前端不重复发送 args —— args 以服务器端记录的为准
3. 工具预览不会因为单聊开始而失效
4. 工具调用不会清空新闻摘要

**当前问题：**
- 前端 `callLocalKnowledge` 同时发 `run_id` 和完整 `args`
- 应该只发 `run_id`，服务器用 `run_id` 查找之前预览的 args

## 7. MemoryTransaction (记忆写入事务)

```python
@dataclass
class MemoryTransaction:
    id: str                      # 后端生成
    status: str                  # "previewed" | "committed" | "partial" | "failed"
    updates: list[MemoryUpdate]
    preview_hash: str            # 预览内容 hash，提交时校验
    results: list[MemoryCommitResult]
    errors: list[MemoryCommitError]
    created_at: datetime
```

**关键不变量：**
1. 预览返回 `transaction_id` + `preview_hash`
2. 提交只接受 `transaction_id` + `preview_hash`
3. 预览内容必须等于提交内容（通过 hash 校验）
4. 批量提交：全部成功 / 明确部分成功 / 全部失败
5. 失败候选通过 `candidate_id` 精确对应

## 8. Operation (异步操作注册)

```python
@dataclass
class Operation:
    id: str
    scope: str          # "chat" | "group" | "news" | "rag-search" | "rag-upload" | "tool" | "memory" | "session-transition"
    status: str         # "idle" | "running" | "cancelling" | "completed" | "failed"
    owner_id: str       # 关联实体 ID（ChatThread.id / NewsRun.id 等）
    abort_token: str    # 用于取消
    created_at: datetime
```

**规则：**
- 一个 scope 同时最多一个 active operation
- 不同 scope 不互相使回调失效
- Workspace 切换才 cancelAll
- 每个响应必须匹配 operation_id 和 owner_id

## 9. RetrievalIndex (检索索引)

```python
@dataclass
class RetrievalIndex:
    id: str
    version: int
    local_status: str      # "ready" | "building" | "error"
    vector_status: str     # "synced" | "stale" | "error"
    document_count: int
    chunk_count: int
    updated_at: datetime
```

```python
@dataclass
class IndexOperation:
    id: str
    status: str
    local_stage: str       # "chunking" | "indexing" | "done" | "failed"
    vector_stage: str      # "pending" | "uploading" | "synced" | "failed"
    error: str | None
    document_count: int
    chunk_count: int
    created_at: datetime
```

**关键不变量：**
1. 上传操作有唯一 `operation_id`，前端据此查询真实阶段
2. 上传失败时错误信息精确对应阶段（local vs vector）

## 10. 实体关系图

```
Workspace
  ├── activeChatThreadId ──────── ChatThread
  │                                 └── ChatTurn*
  ├── activeGroupThreadId ─────── GroupThread
  │                                 └── GroupMessage*
  ├── activeNewsRunId ─────────── NewsRun
  │                                 └── NewsStage*
  ├── Operation* (关联上述实体)
  ├── RetrievalIndex
  └── MemoryTransaction*
```

## 11. 当前代码中存在的实体 vs 应有的实体

| 概念 | 当前表示 | 目标表示 |
|------|----------|----------|
| ChatThread | `singleChatSessionId` (string) | ChatThread (domain object) |
| ChatTurn | session entry in `_state` | ChatTurn (domain object with stable ID) |
| GroupThread | `chat/wechat_group.md` (单文件) | GroupThread + GroupMessage (SQLite) |
| NewsRun | `newsRunIdRef.current++` (前端自增) | NewsRun (后端 UUID) |
| ToolRun | `previewId` (前端 string) | ToolRun (后端 UUID) |
| MemoryTransaction | 无 | MemoryTransaction (preview_hash) |
| Operation | 4 个 generation ref | Operation registry |

## 12. ID 生成职责

| 实体 | ID 生成方 | ID 格式 | 返回时机 |
|------|----------|---------|---------|
| ChatThread | 后端 | UUID / "sthread-xxx" | 第一个 SSE session event |
| ChatTurn | 后端 | UUID | SSE route event 之前 |
| GroupThread | 后端 | UUID | 创建 Group 时 |
| GroupMessage | 后端 | UUID | 发送消息时 |
| NewsRun | 后端 | UUID | /news/search 响应 |
| ToolRun | 后端 | UUID | /tools/.../preview 响应 |
| MemoryTransaction | 后端 | UUID | /memory/preview 响应 |
| Operation | 前端 | UUID | 发起操作时 |
