# 系统不变量 (State Invariants)

> 这些是必须永远成立的条件，不是"目前大部分情况成立"。  
> 所有测试最终都应该锁定这些不变量，而不只是"某个 Bug 不再出现"。

## 1. Chat 不变量

### C1 — 单 Turn 唯一性
```
一个用户问题 → 一个 ChatTurn
中断 + 续写 → 同一 Turn
```
- ✅ 已满足: ChatTurn 是独立实体，SQLite upsert 确保同 turn_id 仅一条记录
- 验证: `test_chat_turn_lifecycle_updates_the_same_turn`
- 剩余边界: 无

### C2 — Turn 状态机
```
pending → streaming → completed
                   → interrupted
                       → streaming → completed (同一 turn.assistant_message 被更新)
                       → retry → 新 Turn (parent_turn_id = 旧 turn.id)
```
- ✅ 已满足: SQLite upsert 确保同 turn_id 仅一条记录；`test_chat_turn_lifecycle_updates_the_same_turn` 验证

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
- ✅ 已满足: SQLite `chat_threads` 始终包含所有 active session；`list_sessions` 按 `updated_at DESC` 排序
- 验证: `test_session_service.py` 验证列表完整性和顺序

### S2 — 归档后不可写
```
Archived Session 拒绝任何写入
包括: log(), commitTurn(), flush_current_session()
```
- ✅ 已满足: `archive_chat_thread` 设置 `status='archived'`，repository 层 `_require_active_thread` 拒绝写入
- 验证: `test_archived_chat_thread_rejects_new_turns`

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
- ✅ 已满足: `operationRegistry` 按 scope 管理；`start(scope)` 自动 cancel 同 scope 旧 operation + abort 旧 controller
- 验证: `operationRegistry.test.ts`

### A2 — Scope 隔离
```
开始单聊 → 只取消旧单聊（chatGenerationRef++）
开始群聊 → 只取消旧群聊（wechatGenerationRef++）
开始新闻 → 只取消旧新闻（newsGenerationRef++）
开始工具 → 只取消旧工具（toolGenerationRef++）
开始不同 scope 的操作不互斥
```
- ✅ 已满足: `operationRegistry` 按 scope 隔离；`test_operationRegistry.test.ts` 验证多 scope 并发

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
- ✅ 已满足: `operationRegistry` 按 scope 管理 generation；`chatController.isCurrentOperation()` 检查 scope + generation
- 验证: `operationRegistry.test.ts`

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
- ✅ 已满足: `operationRegistry.start(scope)` 在创建新 controller 前自动 abort 同 scope 旧 controller
- 验证: `operationRegistry.test.ts`

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
- ❌ 未解决: 只有全局单文件 `chat/wechat_group.md`，见 #8 表

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
- ✅ 已满足: 运行时事实 = SQLite `chat_threads` + `chat_turns`；Markdown 为单向兼容导入导出边界，非并发运行时来源
- 验证: `test_chat_service.py`、`test_session_service.py` 全套流程验证

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
- ✅ 已满足: 服务端 `commit_turn_endpoint` 返回明确 400/409 错误；前端 catch 块显示错误
- 验证: `test_session_service.py` 测试 commit 路径

## 8. 当前代码中未解决的不变量违反

| 违反 | 位置 | 严重性 |
|------|------|--------|
| newsRunId 仍不是后端实体 | NewsWorkspace.tsx | 中 — 当前来自 operationRegistry.operationId，下一步应切到 SQLite NewsRun.id |
| preview/commit 无 transaction_id | api.ts:259-271 | 中 — 可能提交过期预览 |
| 单一 wechat_group.md 文件 | wechat_state.py:26 | 高 — 无法支持多 GroupThread |
