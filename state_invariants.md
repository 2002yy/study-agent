# 系统不变量 (State Invariants)

> 这些是必须永远成立的条件，不是"目前大部分情况成立"。  
> 所有测试最终都应该锁定这些不变量，而不只是"某个 Bug 不再出现"。

## 1. Chat 不变量

### C1 — 单 Turn 唯一性
```
一个用户问题 → 一个 ChatTurn
中断 + 续写 → 同一 Turn
```
- 当前代码: `turn_id` + `merge_with_existing` 已实现，但只在 session_logger 层合并
- 目标: ChatTurn 是独立实体，`continuation_of_turn_id` 指向被继续的 turn

### C2 — Turn 状态机
```
pending → streaming → completed
                   → interrupted
                       → streaming → completed (同一 turn.assistant_message 被更新)
                       → retry → 新 Turn (parent_turn_id = 旧 turn.id)
```
- 当前违反: 续写后 session log 有两个独立 entry（P0-2 已部分修复，但仍是 message 层合并）

### C3 — Session ID 先于第一条 token
```
session event → route event → rag event → token* → done
```
- 当前代码: P1-2 已实现（session event 在 route 之前 yield）
- 验证点: 在任何 token 到达之前必须有 session_id

### C4 — 前端不伪造消息
```
页面消息 = 服务器返回的完整 SSE 流或错误信息
不预先插入、不事后拼接系统 prompt
```
- 当前代码: `setSingleChatMessages` 中正确，但 `buildContinuationHistory` 处理 transient 时需小心

### C5 — 完成 Turn 的 ID 不可变
```
Turn 完成后 turn_id 不可修改
任何后续请求引用已完成 Turn 时必须校验
```

## 2. Session 不变量

### S1 — Active Session 可见
```
Active Session 必须出现在 /sessions 列表中
```
- 当前可能违反: `/sessions` 只扫描磁盘文件，内存中的 session 可能不出现
- 应包含进程内 `_state` 中的 session

### S2 — 归档后不可写
```
Archived Session 拒绝任何写入
包括: log(), commitTurn(), flush_current_session()
```
- 当前: save() 后 `_state` 被清空，但无显式归档锁

### S3 — 切换 Session 原子替换
```
restoreSession(targetId) →
  1. cancelAllOperations()
  2. loadSessionDetail(targetId)
  3. 原子替换: messages, settings, route, rag, lastChat, streamRecovery
  4. 不清不撤: 不触动 GroupThread 和 NewsRun（它们在各自 scope）
```
- 当前: `applySessionDetail` 重置了 `ragSearch`, `newsResult`, `webLookup` 等
- 应该只重置 ChatThread 范围的状态

### S4 — Session 设置快照完整性
```
Session.settings_snapshot 必须包含:
  - chatSettings (5 字段)
  - ragSettings (4 字段)
  - ragEnabled
  - keepCurrentRole
  - conversationInstruction
缺失任一字段 → 标记 incomplete
```

## 3. Async 不变量

### A1 — Scope 互斥
```
一个 OperationScope 同时最多一个 active operation
开始新 operation → 取消同 scope 旧 operation
```
- 当前: 4 个 generation ref 已实现 "递增 ref ← 旧回调被跳过"
- 但旧 AbortController 仍然可能未 abort（`sendSingleChat` 中 `new AbortController()` 写了但没调用旧 controller.abort()）

### A2 — Scope 隔离
```
开始单聊 → 只取消旧单聊（chatGenerationRef++）
开始群聊 → 只取消旧群聊（wechatGenerationRef++）
开始新闻 → 只取消旧新闻（newsGenerationRef++）
开始工具 → 只取消旧工具（toolGenerationRef++）
开始不同 scope 的操作不互斥
```
- 当前代码: 基本满足（P0-1 已实现）

### A3 — Workspace 切换 cancelAll
```
startNewSession() / restoreSession() / archiveCurrentSession() →
  所有 scope 取消 + 所有 controller abort + 所有 busy 重置
```
- 当前代码: `cancelWorkspaceRuns()` 已实现

### A4 — 响应匹配
```
每个 SSE 回调必须检查 generation_id 和 operation_id
响应不匹配 → 静默丢弃（不是报错）
```
- 当前违反: `App.tsx:1031` onDone 检查 `wechatGenerationRef` 而非 `chatGenerationRef`（Bug!）
- 当前违反: `App.tsx:1181` previewTool 回调检查 `wechatGenerationRef` 而非 `toolGenerationRef`（Bug!）
- 当前违反: `App.tsx:1185` 同上
- 当前违反: `App.tsx:1261` callTool 回调检查 `wechatGenerationRef` 而非 `toolGenerationRef`（Bug!）
- 当前违反: `App.tsx:1268` 同上

### A5 — Controller 生命周期
```
每个 operation 开始:
  1. 递增自己的 generation ref
  2. 创建新 AbortController
  3. 旧 controller.abort()
  4. 新 controller 赋值给对应的 ref

每个 operation 结束 (finally):
  1. 如果当前 controller ref 仍指向此 controller → 置 null
```
- 当前: `sendSingleChat` 未调用 `chatAbortRef.current?.abort()` 就 new 新 controller

## 4. Memory 不变量

### M1 — 预览 = 提交
```
预览内容和提交内容必须相等
通过 transaction_id + preview_hash 确保
```
- 当前: preview 和 commit 各自独立发送 `updates` 数组
- 缺少: transaction_id, preview_hash

### M2 — 批量原子性
```
批量提交:
  - 全部成功: status = "committed"
  - 部分成功: status = "partial", errors[] 列出失败的
  - 全部失败: status = "failed"
任一步失败 → 成功的不回滚，失败的不静默丢弃
```
- 当前: 逐文件写入，已是最小原子单元

### M3 — 错误精确对应
```
每个失败项通过 target + action 唯一标识
前端通过 target 匹配到用户看到的具体候选项
```

## 5. Group 不变量

### G1 — Thread 决定消息
```
GroupThread ID 决定消息集合
切换 Thread → 切换全部群聊内容
```
- 当前违反: 只有全局单文件 `chat/wechat_group.md`

### G2 — 失败消息隔离
```
发送失败的消息标记为 failed
不能与已提交消息混在同一集合
```
- 当前: 失败时把错误信息写进 content 本身，而不是标记 status

### G3 — 未读状态一致性
```
未读消息数 = 上次标记已读后新增的消息数
标记已读后 has_unread = false
```
- 当前: 通过 `wechat_unread.md` 文件跟踪，基本正确

## 6. News 不变量

### N1 — 真实 Run ID
```
每次 /news/search → 后端返回 news_run_id
后续 enrich/digest/discuss 引用该 run_id
```
- 当前状态: NewsWorkspace 已改用 operationRegistry 的 `operationId`，不再自增 `newsRunIdRef`；但这仍不是后端持久化 `NewsRun.id`。
- newsRunId 是前端局部自增，不是后端实体

### N2 — 阶段锁定
```
enrich 只能处理 search 阶段的 items
digest 只能处理 enrich 阶段的 items（或 search 阶段 + 无 enrich）
discuss 只能处理 digest 的结果
各阶段不可跳过不可逆序
```
- 当前: 逻辑基本正确，但靠前端局部 state 维护阶段

### N3 — Safe Mode 可见
```
safe_mode 跳过正文读取 → 必须在 UI 显示
作为 NewsRun 的字段，不是 inference
```
- 当前: 只在提示文案中静态显示，不是服务器返回的状态

### N4 — Run 隔离
```
NewsRun 不修改单聊 Session ID
NewsRun 可以关联 GroupThread（discuss 后），但不创建 ChatThread
```

## 7. 持久化不变量

### P1 — 单一事实来源
```
运行时事实: SQLite（目标） / 进程内 _state（当前）
长期记忆: memory/*.md
人类阅读导出: logs/sessions/*.md
配置: config/*.yaml
每个数据有且仅有一个权威来源
```
- 当前违反: localStorage、进程 `_state`、`logs/current/*.md`、`logs/sessions/*.md` 各有各的版本

### P2 — 提交原子性
```
flush → 要么完整写入 current 文件，要么完全不写
save → 要么完整写入 archive 文件，要么完全不写
```
- 当前: `safe_write_text` 提供原子写入

### P3 — 无静默失败
```
任何写入失败必须:
  1. 记录日志
  2. 返回错误
  3. 不丢失用户数据
```
- 当前: `commitTurn` 的 catch 块静默丢弃错误

## 8. 当前代码中已发现的不变量违反

| 违反 | 位置 | 严重性 |
|------|------|--------|
| onDone 检查 wechatGenerationRef | App.tsx:1031 | 中 — 单聊 done/mid-stream wechat generation 不匹配时回调被跳过 |
| previewTool 检查 wechatGenerationRef | App.tsx:1181,1185,1261,1268 | 高 — 工具预览和调用被群聊 generation 影响 |
| sendSingleChat 未 abort 旧 controller | App.tsx:967 | 低 — 旧 HTTP 连接可能继续 |
| /sessions 不包含内存中 session | api.py | 中 — 首轮中断后列表不可见 |
| newsRunId 仍不是后端实体 | NewsWorkspace.tsx | 中 — 当前来自 operationRegistry.operationId，下一步应切到 SQLite NewsRun.id |
| preview/commit 无 transaction_id | api.ts:259-271 | 中 — 可能提交过期预览 |
| 单一 wechat_group.md 文件 | wechat_state.py:26 | 高 — 无法支持多 GroupThread |
## Verified 2026-06-20: Chat and Session SQLite slice

- One Chat request creates one SQLite `ChatTurn`; continuation and partial commit update that same `turn_id`.
- `turn_id` ownership is checked against `thread_id`; cross-thread continuation is rejected.
- Active threads appear in Session lists before Markdown export.
- Archived threads are write-locked by the Repository.
- Session restore returns full messages, avatar roles, settings, route/RAG snapshots, conversation instruction, and Turn lifecycle metadata.
- Markdown is a one-way compatibility import/export boundary, not a concurrent runtime source.
