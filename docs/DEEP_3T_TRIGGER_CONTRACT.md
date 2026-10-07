# Deep-3T Durable Trigger Contract

**状态：FROZEN**

## 1. Authority

Implementation-seam authority：

```text
exact-main
1514bbf76031dfeca2cb03e9c52adf5d149cd724
```

既有 authority：

```text
Standard
  c48a1ac313e59ab0104364db519340f1460e84dc
  L3 37514856913

Deep-1
  e5c63c03c9ac77b273f2bfc158111ac676e9bc42
  CI 37599443309

Deep-2
  1514bbf76031dfeca2cb03e9c52adf5d149cd724
  CI 37628909373
```

Deep-3T 不取代上述 authority。

---

# 2. 为什么存在 Deep-3T

当前 production composition：

```text
ChatService
→ StandardContinuationChatService
→ StandardContinuationService
```

Standard continuation 同步运行在：

```text
complete_turn()
```

之后。

Deep 不能照搬：

```text
complete_turn()
→ DeepExecutionService.execute()
```

因为 Deep hard window：

```text
180s
```

若同步执行，会把整个 Deep research latency 放进 HTTP / SSE response critical path。

因此必须先建立：

```text
durable intent
→ non-blocking wake
→ process-local worker
→ durable rediscovery
```

Deep-3T 只解决这一件事。

---

# 3. Deep-3T 唯一目标

建立一个：

```text
不新增 DB table
不新增 research queue schema
不复制 Deep lease/resume
不修改 research semantics
```

的 durable trigger。

状态来源仍是已有数据库事实：

```text
A. 已完成 Standard、尚未建立 Deep terminal 的 Deep-ready parent

或

B. deep_terminal.dispatch_status == pending
```

worker 自身不是 authority。

---

# 4. 非目标

Deep-3T 不负责：

```text
Deep child execution semantics
Deep parent finalization
Deep parent blocked/completed state transition
ResearchBrief
synthesis
publication
answer regeneration
assistant_message mutation
pedagogy
learning state
Deep-4
```

也不建立：

```text
DeepQueue table
DeepJob table
DeepLease
DeepRetryLedger
DeepScheduler state
DeepWorkerCursor
```

---

# 5. Trigger 的 durable truth

v1 没有独立 queue row。

存在两类 durable work item。

## 5.1 ARM candidate

父 turn 已经：

```text
status == completed

lookup_terminal:
  state == ESCALATE_STANDARD
  dispatch_status == completed

standard_continuation:
  schema_version == standard-auto-continuation-v1
  publication_authority == false

deep_terminal:
  absent
```

并且：

```text
standard_continuation.result.unresolved_gaps
```

非空。

已知明确不升级的 stop：

```text
cancelled
planner_invalid
planner_failed
result_unknown
```

不得成为 ARM candidate。

其他 nonempty-gap 状态允许进入 `DeepHandoffService.prepare()`，由 Deep-1 authority 最终决定：

```text
prepared
not_requested
blocked
```

trigger repository 不复制 `decide_deep_handoff()`。

## 5.2 PENDING candidate

父 turn 已有：

```text
deep_terminal.schema_version == standard-deep-terminal-v1
deep_terminal.state == ESCALATE_DEEP
deep_terminal.dispatch_status == pending
```

这是现成 Deep work item。

---

# 6. 为什么需要 ARM recovery

正常 production 路径可能是：

```text
Standard continuation committed
→ process crash
→ DeepHandoffService.prepare() 尚未发生
```

如果 trigger 只扫描 `deep_terminal=pending`：

```text
这个 parent 永远不会进入 Deep
```

因此 Deep-3T 必须同时恢复：

```text
Standard completed + unresolved + no Deep terminal
```

这个 crash window。

---

# 7. Trigger repository

新增：

```text
src/repositories/deep_trigger_repository.py
```

职责仅为只读 discovery。

建议 API：

```python
@dataclass(frozen=True)
class DeepTriggerItem:
    kind: Literal["arm", "pending"]
    parent_turn_id: str
    thread_id: str


class DeepTriggerRepository:
    def discover(
        self,
        *,
        arm_limit: int = 8,
        pending_limit: int = 16,
    ) -> tuple[DeepTriggerItem, ...]:
        ...
```

---

# 8. Discovery ordering

每个 scan：

```text
① ARM candidates
② PENDING candidates
```

原因：

```text
新恢复出的 ARM
→ DeepHandoffService.prepare()
→ 可以在同一 scan 的 PENDING discovery 中被看到
```

因此一次 wake 可以完成：

```text
Standard terminal
→ Deep-1 handoff
→ Deep execution/finalization consumer
```

无需下一次 timer。

---

# 9. ARM discovery 不承担 integrity authority

SQL 只做：

```text
候选发现
```

不做：

```text
Deep-1 semantic validation
handoff digest validation
seed validation
lineage validation
```

这些仍全部属于：

```text
DeepHandoffService.prepare()
```

因此 repository 可以使用已有 JSON storage 做 coarse filtering。

---

# 10. ARM minimum filter

必须至少满足：

```text
chat_turn.status == completed

lookup_terminal.state == ESCALATE_STANDARD
lookup_terminal.dispatch_status == completed

standard_continuation.schema_version
  == standard-auto-continuation-v1

standard_continuation.publication_authority == false

deep_terminal absent

result.unresolved_gaps is a non-empty array
```

已知 `NON_UPGRADE_STOP_REASONS` 应从：

```text
src/web/research/deep_handoff.py
```

复用，不复制第二套常量。

如果 stop reason 是已知 non-upgrade：

```text
不发现
```

未知 stop reason：

```text
可发现
→ DeepHandoffService.prepare()
→ Deep-1 按自己的规则 blocked
```

---

# 11. PENDING minimum filter

只发现：

```text
deep_terminal schema exact
state == ESCALATE_DEEP
dispatch_status == pending
```

已经：

```text
completed
blocked
```

的 parent 不进入 trigger。

---

# 12. Malformed terminal

Deep-3T discovery 不负责修复任意数据库 corruption。

例如：

```text
deep_terminal = "garbage"
```

不是合法 PENDING work item。

不得：

```text
猜测
覆盖
修复
```

显式执行路径中的 Deep-3 core 仍必须 fail closed。

---

# 13. Runner

新增：

```text
src/application/deep_trigger.py
```

核心对象：

```python
class DeepTriggerRunner:
    ...
```

v1 固定：

```text
worker concurrency = 1
scan interval       = 15 seconds
ARM batch           = 8
PENDING batch       = 16
```

这是 background research v1 的保守并发上限。

---

# 14. 为什么 concurrency=1

Deep 每次可能占：

```text
model
network
reader
up to 180s wall window
```

Study Agent 当前不是多租户 research cluster。

v1 不为吞吐量引入：

```text
parallel Deep workers
fair scheduler
priority queue
resource broker
```

以后若要增加并发：

```text
单独合同
```

---

# 15. Runner 不保存 durable queue

worker 内部最多保存：

```text
thread
wake event
stop event
```

不得保存：

```text
authoritative pending IDs
retry counts
job states
leases
```

每次 scan 都重新从 DB discovery。

---

# 16. wake()

API：

```python
runner.wake()
```

必须：

```text
non-blocking
O(process-local)
不调用 model
不调用 network
不运行 DeepExecutionService
不等待 worker
```

实现语义：

```text
set wake event
return
```

---

# 17. response-path hard gate

Production 激活后：

```text
safe answer durable
→ runner.wake()
→ return response
```

同步 request thread 禁止：

```text
DeepHandoffService.prepare()
DeepExecutionService.execute()
DeepContinuationService.continue_pending()
```

这些全部在 worker thread。

因此：

```text
Deep 180s
```

永远不进入：

```text
complete_turn latency
HTTP response latency
SSE done latency
```

的同步等待链。

---

# 18. “post-response”的精确定义

本合同的 authority 是：

> Deep research runs off the synchronous response critical path after the safe answer is durably committed.

不要求：

```text
TCP final byte acknowledged
```

之后 worker 才能开始。

允许：

```text
parent durable completed
→ wake worker
→ worker 与 HTTP flush 并发
```

因为：

```text
request thread 不等待
assistant_message 不可变
Deep publication_authority=false
```

---

# 19. Worker lifecycle

状态机：

```text
STOPPED
  start()
    ↓
RUNNING
  wake / timer
    ↓
SCANNING
  scan complete
    ↓
RUNNING

RUNNING / SCANNING
  stop()
    ↓
STOP_REQUESTED
    ↓
STOPPED
```

`start()` 必须 idempotent。

重复：

```text
start()
```

不得创建第二条 worker thread。

---

# 20. Startup recovery

Production activation 后：

```text
application startup
→ runner.start()
→ immediate scan
```

不得等第一个 15s interval。

因此 process restart 后：

```text
ARM candidate
PENDING candidate
```

都会自动重新发现。

---

# 21. Periodic recovery

runner 在无 wake 时：

```text
每 15 秒
```

重新 scan。

原因：

```text
wake event 可能丢失于 process crash
live lease owner 可能后来变 stale
worker callback 可能发生 transient exception
```

durable DB state 才是恢复依据。

---

# 22. 不 busy-loop

一轮 scan 完成后：

```text
没有新 wake
→ 等待完整 scan interval
```

即使存在：

```text
lease_busy
```

也不得立即无限 retry。

---

# 23. ARM callback

Runner 注入：

```python
arm(parent_turn_id, thread_id)
```

Deep-3 activation 时绑定：

```text
DeepHandoffService.prepare
```

outcome：

```text
prepared
not_requested
blocked
```

---

# 24. ARM outcome

```text
prepared
→ 同轮继续 PENDING discovery

not_requested
→ 不执行 consumer

blocked
→ 不执行 consumer
```

Deep-3T 不修改 outcome。

---

# 25. PENDING consumer

Runner 注入：

```python
consume(parent_turn_id, thread_id)
```

Deep-3 activation 后绑定：

```text
DeepContinuationService.continue_pending
```

Deep-3T 本身不懂 child/runtime/finalization。

---

# 26. Consumer outcome

Trigger runner 只区分：

```text
completed
blocked
deferred
not_requested
```

处理：

```text
completed
blocked
not_requested
→ 本轮结束，继续下一个 item

deferred
→ 保持 durable truth
→ 不 tight-loop
→ 后续周期重新发现
```

---

# 27. Callback exception

任何：

```text
Exception
```

从 ARM / consumer 逃出：

```text
记录日志
不修改 parent
不改成 blocked
继续 runner
```

因为 trigger layer 不拥有 integrity taxonomy。

---

# 28. Trigger 不持久化错误

禁止新增：

```text
deep_trigger_error
deep_trigger_attempts
deep_trigger_retry_count
```

未知 trigger exception：

```text
durable work item stays pending
```

即可恢复。

---

# 29. Multi-process safety

两个进程可能同时 scan 同一 parent。

Deep-3T 不提供 distributed lock。

authority 由既有层保证：

```text
DeepHandoffService
  deterministic child
  first terminal
  idempotent prepare

DeepExecutionService
  WebLookupRun operation lease
  stale recovery

DeepContinuationRepository
  pending→terminal transaction
  first terminal wins
```

所以：

```text
duplicate trigger ≠ duplicate authoritative work
```

---

# 30. Runner shutdown

`stop()`：

```text
set stop event
wake thread
best-effort bounded join
```

不得：

```text
cancel Deep child
rewrite parent
mark job failed
```

若 process 在 consumer 中结束：

```text
Deep child cursor / operation lease
+ parent pending
```

负责下次恢复。

---

# 31. Shutdown timeout

v1：

```text
join wait <= 1 second
```

如果 worker 正在 blocking Deep call：

```text
process shutdown 不等待 180s
```

thread 必须：

```text
daemon=True
```

durable state 承担恢复。

---

# 32. Deep-3T implementation slice production-inert

Deep-3T CLOSED 前只允许实现：

```text
repository discovery
runner lifecycle
wake
periodic scan
ARM callback seam
PENDING consumer seam
tests
```

不得修改：

```text
get_chat_service()
StandardContinuationChatService
FastAPI app lifecycle
production composition
```

因此 Deep-3T 合并不会自动启动 Deep。

---

# 33. Deep-3T allowed files

```text
NEW src/application/deep_trigger.py
NEW src/repositories/deep_trigger_repository.py
NEW tests/test_deep_trigger.py
docs/DEEP_3T_TRIGGER_CONTRACT.md
docs/PROJECT_STATUS.md
```

必要时允许极小测试 fixture 文件。

---

# 34. Forbidden files

Deep-3T 不得修改：

```text
active_research_runtime.py
deep_execution.py
deep_runtime.py
deep_handoff.py
deep_seed.py
deep_handoff_repository.py

standard_continuation.py
standard_execution_repository.py
standard_chat_service.py

chat_service.py
runtime_repository.py
api/app.py
chat_routes.py

ResearchStopGate
Evidence Gain
gap planner
synthesis
auditor
pedagogy
learning
frontend
DB migrations
```

如果实现认为必须修改其中之一：

```text
STOP
合同假设错误
```

---

# 35. Deep-3T negative controls

必须至少覆盖：

```text
T1  valid ARM parent is discovered

T2  Standard resolved / unresolved_gaps empty
    → not discovered

T3  cancelled/planner_invalid/planner_failed/result_unknown
    → not ARM-discovered

T4  unknown stop + unresolved gaps
    → ARM-discovered
    → Deep-1 decides blocked

T5  valid pending deep_terminal
    → PENDING-discovered

T6  deep terminal completed
    → not discovered

T7  deep terminal blocked
    → not discovered

T8  start() twice
    → exactly one worker

T9  start()
    → immediate scan, no initial 15s delay

T10 wake()
    → returns without invoking callback inline

T11 wake()
    → worker scan occurs promptly

T12 ARM prepared
    → newly pending Deep can be consumed in same scan cycle

T13 ARM not_requested
    → consumer not called

T14 ARM blocked
    → consumer not called

T15 consumer deferred
    → durable parent untouched
    → later scan sees it again

T16 consumer completed
    → next discovery no longer returns it

T17 consumer raises unexpected exception
    → runner survives
    → next cycles continue

T18 process-style runner restart
    → same durable pending item rediscovered

T19 stop()
    → no parent/child status mutation

T20 bounded batch respected

T21 two runner instances see same item
    → trigger layer performs no authoritative duplicate write

T22 no new DB table / migration

T23 Deep-3T merge changes no production composition

T24 non-trigger existing repository behavior unchanged
```

---

# 36. Mutation requirement

关键 tests 必须做变异验证，至少：

```text
remove periodic rediscovery
→ restart/deferred recovery test fails

make wake call consumer inline
→ non-blocking test fails

remove terminal filter
→ completed/blocked discovery test fails

remove ARM recovery
→ Standard-complete/no-Deep crash test fails
```

“测试绿”本身不够。

---

# 37. Deep-3T review gates

```text
G3T-1   DB state is the durable queue authority
G3T-2   no new queue table
G3T-3   ARM crash window recoverable
G3T-4   pending Deep recoverable
G3T-5   worker concurrency exactly 1
G3T-6   start idempotent
G3T-7   startup immediate scan
G3T-8   15s periodic recovery
G3T-9   wake non-blocking
G3T-10  no callback inline on response thread
G3T-11  no trigger-layer lease/retry ledger
G3T-12  callback exceptions leave durable state untouched
G3T-13  deferred is retriable through rediscovery
G3T-14  shutdown bounded
G3T-15  multi-process duplicate trigger safe by downstream authority
G3T-16  production remains inert
G3T-17  focused tests pass
G3T-18  mutation checks pass
G3T-19  ruff pass
G3T-20  mypy baseline pass
G3T-21  git diff --check pass
G3T-22  file-boundary audit pass
G3T-23  exact-head ordinary CI pass
```

---

# 38. Local candidate gate

```text
focused Deep-3T tests
repository adjacent tests
Deep-1 / Deep-2 regressions touching terminal discovery
ruff
expanded mypy
mypy baseline
git diff --check
scope audit
```

继续沿用：

> mypy baseline 必进 candidate gate。

以及：

> branch-critical tests 必须做 mutation validation。

---

# 39. CI discipline

Deep-3T：

```text
不跑 formal L3
```

若 CI classifier 没有 Deep-3T category：

```text
ordinary full pytest fallback
```

是允许的。

---

# 40. Commit discipline

一次 bounded slice：

```text
trigger repository
+ runner
+ tests
+ docs
→ 一次本地 candidate gate
→ 一个 implementation commit
→ 一个 PR
```

不要按：

```text
scanner
worker
wake
tests
```

拆成四个 CI cycle。

---

# 41. Deep-3T CLOSED 定义

Deep-3T CLOSED 只代表：

```text
Study Agent 已拥有一个
durable-state-backed
non-blocking
restart-recoverable
periodic Deep trigger mechanism
```

并且它：

```text
尚未生产激活
尚未执行 Deep
尚未 finalize parent
```

---

# 42. Deep-3 prerequisite

只有：

```text
Deep-3T merged
exact-main ordinary CI green
Deep-3T CLOSED recorded
```

后，才允许 Deep-3 production composition。

Deep-3 implementation 前必须对新 exact-main 做一次**窄 seam recheck**：

```text
trigger API 未漂移
DeepExecutionService 未漂移
deep_terminal schema 未漂移
WebLookup terminal fields 未漂移
```

不重做整个 Deep-3 设计。

---

# 43. 一句话模型

> **Deep-3T 不把任务“放进一个新队列”；数据库里已经完成的 Standard artifact 和 pending Deep terminal 本身就是队列。后台 runner 只是周期性重新发现这些 durable facts，并把它们交给已有 Deep-1/Deep-3 authority，因此 wake 丢失、进程崩溃或 worker 重启都不会丢掉 Deep 工作。**
