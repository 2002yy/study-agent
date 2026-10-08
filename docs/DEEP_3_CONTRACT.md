# Deep-3 Continuation and Parent Finalization Contract

**状态：FROZEN semantics**

**Implementation gate：**

```text
Deep-3T CLOSED
+ Deep-3T merge 后 exact-main seam recheck
```

不得在 Deep-3T 尚未关闭时开始 Deep-3 production implementation。

---

# 1. Authority

当前 semantic seam authority：

```text
1514bbf76031dfeca2cb03e9c52adf5d149cd724
```

Deep-3T 合并后：

```text
只重新核接口 seam
不重新设计状态机
```

既有 authority：

```text
Standard  c48a1ac3 / L3 37514856913
Deep-1    e5c63c03 / CI 37599443309
Deep-2    1514bbf7 / CI 37628909373
```

---

# 2. Deep-3 唯一目标

Deep-3 完成：

```text
Deep-ready Standard artifact
→ Deep-1 prepare
→ Deep-3T background trigger
→ Deep-2 execution/resume
→ Deep child terminal
→ parent deep_terminal finalization
```

并完成 production composition。

---

# 3. Deep-3 仍然不做

Deep-3 不负责：

```text
ResearchBrief publication projection
synthesis publication
answer regeneration
assistant message rewrite
Final Answer Auditor publication
pedagogy mutation
learning-state mutation
Deep evidence 写回用户答案
```

这些属于 Deep-4。

---

# 4. Production data flow

最终：

```text
ChatService
→ StandardContinuationChatService semantics
→ safe parent durable
→ Standard continuation
→ Deep trigger wake()       # non-blocking
→ return safe answer

background Deep-3T runner
→ ARM discovery
→ DeepHandoffService.prepare()
→ PENDING discovery
→ DeepContinuationService.continue_pending()
→ DeepExecutionService.execute()
→ existing ActiveResearchRuntimeExecutor
→ child terminal
→ DeepContinuationRepository.finalize()
```

---

# 5. Response critical path

同步 response path 只允许：

```text
existing Chat completion
existing Standard continuation
runner.wake()
```

`wake()` 必须是 process-local event signal。

禁止同步：

```text
DeepHandoffService.prepare()
DeepExecutionService.execute()
DeepContinuationService.continue_pending()
ActiveResearchRuntimeExecutor.execute()
```

---

# 6. Chat wrapper

新增：

```text
src/application/deep_chat_service.py
```

建议：

```python
class DeepContinuationChatService(StandardContinuationChatService):
    ...
```

`complete_turn()`：

```text
completed = super().complete_turn(...)

runner.wake()

return completed
```

不得：

```text
等待 worker
重新 fetch parent 等 Deep
执行 Deep
修改 assistant
```

---

# 7. 为什么 wrapper 只 wake

即使发生：

```text
Standard continuation commit
→ crash
→ wake() 尚未执行
```

Deep-3T startup/periodic ARM discovery 仍可：

```text
从 Standard durable artifact 恢复 Deep
```

所以 response path 不需要承担 DeepHandoff persistence。

---

# 8. DeepContinuationService

新增：

```text
src/application/deep_continuation.py
```

公开：

```python
@dataclass(frozen=True)
class DeepContinuationOutcome:
    status: Literal[
        "not_requested",
        "deferred",
        "completed",
        "blocked",
    ]
    parent_turn_id: str
    child_run_id: str
    reason: str
    result: dict | None
```

---

# 9. continue_pending() high-level state machine

```text
read parent
↓
read deep_terminal
↓
absent
    → not_requested

already terminal
    → validate existing terminal
    → return existing
    → 0 child execution

pending
    → validate full authority
    → read child

child terminal
    → finalize parent only
    → 0 child execution

child nonterminal
    → DeepExecutionService.execute()

execution deferred
    → parent stays pending

execution completed
    → reload child
    → finalize parent

execution blocked
    → block parent

unexpected exception
    → propagate
    → parent stays pending
```

---

# 10. Existing parent terminal wins first

如果：

```text
deep_terminal.dispatch_status == completed
```

或：

```text
blocked
```

Deep-3 不重新：

```text
run child
recalculate result
rewrite reason
```

必须：

```text
return durable existing terminal
```

---

# 11. Existing terminal validation

first-terminal-wins 不代表 malformed terminal 被信任。

如果 recorded terminal：

```text
dispatch_status == completed|blocked
```

但：

```text
schema invalid
state invalid
owner invalid
result schema invalid
publication authority true
```

服务可以返回：

```text
blocked / terminal_integrity_failure
```

但：

```text
绝不改写已经 recorded terminal
```

---

# 12. Pending parent validation

pending Deep 必须重新验证：

```text
parent exists
parent.thread_id == caller thread
parent.status == completed

deep_terminal.schema_version
  == standard-deep-terminal-v1

state == ESCALATE_DEEP
dispatch_status == pending

owner.thread_id == thread_id
owner.turn_id == parent.id
```

---

# 13. Deep handoff validation

必须重新调用：

```text
load_deep_handoff()
```

并要求：

```text
handoff.parent_turn_id == parent.id
handoff.query == parent.user_message
handoff.publication_authority == false
```

raw：

```text
handoff.payload_sha256
```

必须存在并通过 digest。

---

# 14. Child identity

```text
child.id == deep_terminal.child_run_id
child.owner_thread_id == thread_id

child.parent_run_id
  == handoff.standard_child_run_id

child.query
  == handoff.query
  == parent.user_message
```

不符：

```text
deterministic integrity failure
```

---

# 15. Child statuses

Deep-3 使用 Deep-2 已冻结集合：

```text
completed
partial
failed
cancelled
```

作为 terminal。

---

# 16. Terminal child does not re-execute

如果首次进入 Deep-3 时：

```text
child.status ∈ terminal statuses
parent still pending
```

必须：

```text
0 DeepExecutionService calls
→ parent finalize only
```

这是 Deep-3 最重要 crash-recovery gate 之一。

---

# 17. Nonterminal child

如果 child：

```text
pending
running
```

等 Deep-2 支持的 resumable 状态：

```text
调用同一个 DeepExecutionService
```

不得自己操纵 runtime cursor。

---

# 18. live running child

DeepExecutionService 返回：

```text
deferred / lease_busy
```

则：

```text
parent deep_terminal remains pending
```

Deep-3 不写任何 terminal。

---

# 19. stale running child

Deep-2 已拥有：

```text
operation_is_stale
begin_operation stale recovery
ResearchRuntimeCursor recovery
```

Deep-3 只调用：

```text
DeepExecutionService.execute()
```

不得建立第二套 stale logic。

---

# 20. DeepExecution completed

`DeepExecutionOutcome.status == completed` 后：

```text
重新 load child
```

不能相信 outcome 中的瞬时对象。

然后要求：

```text
child status terminal
```

才允许 finalize。

---

# 21. DeepExecution blocked

只有 Deep-2 明确返回：

```text
blocked
```

才允许进入 parent `blocked` transition。

Deep-3 不扩大 blocked taxonomy。

---

# 22. Research failure ≠ blocked

以下若已经形成合法 child terminal：

```text
provider failure
search empty
reader failure
model attempt exhaustion
active runtime unavailable
no evidence gain
saturation
budget exhaustion
deadline
wave ceiling
user cancellation
```

parent 都是：

```text
dispatch_status = completed
```

不是 blocked。

---

# 23. cancellation

child：

```text
status == cancelled
stop_reason == user_cancelled
```

是一个合法 runtime terminal。

Parent：

```text
completed
result.child_status = cancelled
```

不得自动 restart。

---

# 24. Parent result schema

新增：

```text
deep-auto-continuation-v1
```

形状：

```python
{
    "schema_version": "deep-auto-continuation-v1",

    "child_run_id": "...",
    "child_status": "completed|partial|failed|cancelled",

    "provider_status": "...",
    "stop_reason": "...",
    "answer_confidence": "...",
    "completed_at": "...",

    "handoff_sha256": "...",
    "child_terminal_sha256": "...",

    "publication_authority": False,
}
```

---

# 25. Parent result 是 control plane

禁止放入：

```text
selected_sources
rejected_sources
raw page bodies
seed bodies
ResearchState
ResearchRuntimeCursor
model outputs
model audit trace
evidence rows
ResearchBrief body
```

这些仍属于 child durable data plane。

---

# 26. child terminal projection

用于 `child_terminal_sha256` 的唯一 projection：

```python
{
    "child_run_id": child.id,
    "child_status": child.status,
    "provider_status": child.provider_status,
    "stop_reason": child.stop_reason,
    "answer_confidence": child.answer_confidence,
    "completed_at": child.completed_at or "",
}
```

---

# 27. child terminal digest

计算：

```text
SHA-256(
  canonical JSON
  sort_keys=True
  ensure_ascii=False
  separators=(",", ":")
)
```

不包含：

```text
selected_sources
context
items
warnings
error text
```

---

# 28. Parent finalization repository

新增：

```text
src/repositories/deep_continuation_repository.py
```

职责：

```text
read terminal
finalize pending→completed
block pending→blocked
```

不得执行 research。

---

# 29. Finalization transaction

必须：

```text
BEGIN IMMEDIATE
```

并在同一个 transaction 中重新读取：

```text
parent row
parent rag_snapshot
deep terminal
child row
child research_context
```

不能先在 service 校验后盲写。

---

# 30. Finalization transaction — parent revalidation

重新要求：

```text
parent exists
thread matches
parent.status == completed
```

并且 Deep terminal 仍为：

```text
schema exact
state == ESCALATE_DEEP
dispatch_status == pending
owner exact
```

---

# 31. First-terminal-wins transaction

transaction 内如果看到：

```text
dispatch_status == completed
or blocked
```

立即：

```text
return existing terminal
```

不得再写。

---

# 32. Finalization transaction — handoff

事务内重新：

```text
load_deep_handoff(raw handoff)
```

并核：

```text
payload_sha256
parent_turn_id
query
publication_authority=false
```

---

# 33. Finalization transaction — child

重新验证：

```text
child.id == terminal.child_run_id
child.owner_thread_id == thread
child.parent_run_id == handoff.standard_child_run_id
child.query == handoff.query
child.status ∈ terminal statuses
```

---

# 34. Finalization transaction — execution envelope

child context 必须存在：

```text
deep.execution
```

并通过：

```text
bind_execution_envelope(
  parent_turn_id=parent.id,
  handoff_sha256=parent handoff digest
)
```

同时：

```text
publication_authority == false
```

---

# 35. Finalization transaction — seed

必须重新：

```text
read_seed
verify_seed_sources
verify_seed_projection
seed_refs_match(handoff, seed)
```

这样：

```text
child terminal
→ parent finalize
```

之间的 durable tamper 会 fail closed。

---

# 36. No Claim Engine re-grant

Finalization 不需要重新授予任何 claim/evidence eligibility。

它只是验证：

```text
Deep child 是这个 parent/handoff 对应的合法 terminal
```

不得从 finalization 重算 evidence。

---

# 37. completed transition

唯一合法成功 transition：

```text
pending
→ completed
```

transaction 只修改：

```text
deep_terminal.dispatch_status = "completed"
deep_terminal.result = deep-auto-continuation-v1
```

原：

```text
handoff
owner
child_run_id
```

必须保留。

---

# 38. blocked transition

deterministic integrity/admission failure：

```text
pending
→ blocked
```

只允许写：

```text
deep_terminal.dispatch_status = "blocked"
deep_terminal.reason = bounded_reason
```

不得放原始 exception text。

---

# 39. Bounded blocked reasons

至少：

```text
parent_unavailable
terminal_integrity_failure
handoff_integrity_failure
child_missing
lineage_mismatch
seed_integrity_failure
execution_envelope_invalid
claim_engine_unusable
execution_state_mismatch
```

不得：

```text
str(exc)
```

直接落库。

---

# 40. Unknown exception

任何不属于 deterministic integrity 的：

```text
RuntimeError
IOError
unexpected ValueError
DB transient error
programming error
```

必须：

```text
propagate to trigger runner
parent stays pending
```

trigger runner：

```text
log
later rediscover
```

不得猜成 blocked。

---

# 41. Result-lost crash

如果：

```text
parent finalization COMMIT
→ process crashes before caller receives result
```

下一次：

```text
continue_pending()
→ sees terminal completed
→ returns exact existing result
→ 0 child execute
```

---

# 42. Child-terminal / parent-pending crash

如果：

```text
child terminal committed
→ crash before parent finalize
```

下一次：

```text
0 runtime execution
→ finalize same child
```

必须有 dedicated regression。

---

# 43. Running crash

如果：

```text
child running
→ process crash
```

Deep-3T periodic trigger：

```text
rediscover parent pending
→ DeepContinuationService
→ DeepExecutionService
```

然后：

```text
live lease → deferred
stale lease → existing Deep-2 resume
```

---

# 44. Parent finalization concurrency

两个 Deep-3 consumer：

```text
A/B 都看到 pending
```

最终只能：

```text
一个 transaction 写 terminal
另一个读取 first terminal
```

不得产生两个不同 result。

---

# 45. completed vs blocked race

如果一方尝试：

```text
completed
```

另一方尝试：

```text
blocked
```

先 commit 的 terminal 永久获胜。

后者：

```text
return existing
```

不得翻转。

---

# 46. Parent immutability

Deep-3 整个过程禁止修改：

```text
assistant_message
status
role
mode
model
route_snapshot
pedagogy_snapshot
conversation_instruction
cancel fields
```

---

# 47. RAG snapshot immutability

除：

```text
rag_snapshot.deep_terminal
```

外，其他 key 必须保持语义不变：

```text
lookup_terminal
standard_continuation
answer_claim_snapshot
answer_validation_audit
official_field_publication
evidence_snapshot
...
```

---

# 48. Learning immutability

禁止：

```text
chat_threads.learning_state
learner truth
durable adjudication
pedagogy closure
review scheduling
```

修改。

---

# 49. Publication authority

Deep-3：

```text
publication_authority == false
```

贯穿：

```text
handoff
execution
parent result
```

Deep child 有证据：

```text
!= user-visible publication authority
```

---

# 50. No answer regeneration

Deep-3 禁止调用：

```text
chat model for final answer
answer claim binder
Final Answer Auditor publication
synthesis writer for user answer
```

Deep-4 才拥有 publication integration。

---

# 51. Production trigger activation

Deep-3 激活时：

```text
DeepContinuationChatService.complete_turn()
→ existing Standard behavior
→ runner.wake()
→ immediate return
```

worker 独立完成后续。

---

# 52. Trigger consumer wiring

Deep-3T runner 的 ARM callback：

```text
DeepHandoffService.prepare()
```

PENDING consumer：

```text
DeepContinuationService.continue_pending()
```

---

# 53. Runtime object sharing

Production composition 必须复用：

```text
repository = get_runtime_repository()
runs       = get_web_lookup_repository()
dispatcher = get_web_lookup_service()
```

`DeepExecutionService` 必须注入现有：

```text
get_web_lookup_service()
```

不得因为 Deep 再创建第二个 production dispatcher/cache/repository singleton。

---

# 54. No second research gateway contract

Deep-3 不改变 Deep-2 已验证：

```text
ClaimEngineDispatchWebLookupService
→ existing active gateway/runtime factory
```

语义。

Deep-3 只是复用 DeepExecutionService。

---

# 55. Trigger startup

Production composition / app lifecycle 必须：

```text
runner.start()
```

一次。

shutdown：

```text
runner.stop()
```

best effort。

具体 FastAPI lifecycle API 是 implementation detail；行为合同是：

```text
process startup → immediate recovery scan
process shutdown → bounded stop
```

---

# 56. Trigger startup failure

如果 runner startup 抛异常：

```text
Chat/API startup 不得因为 background Deep recovery 直接不可用
```

应：

```text
log
keep application serving safe chat
```

下一次显式 `wake/start` 可重试。

不得破坏 core chat availability。

---

# 57. Chat fail-safe

`runner.wake()` 若异常：

```text
completed safe answer 仍返回
```

但由于 worker wake 理论上只是 event signal：

```text
异常属于 infrastructure defect
```

不得把已完成 safe answer 改成 500。

---

# 58. No synchronous Deep latency

必须有 production integration test：

```text
Deep consumer blocks for > request test threshold

complete_turn
→ still returns without waiting consumer
```

不能只 mock `wake()`。

必须证明：

```text
worker path 与 request thread 分离
```

---

# 59. Deep-3 outcome semantics

```text
not_requested
  no Deep terminal / no work

deferred
  durable Deep work remains pending

completed
  parent Deep terminal is durably completed

blocked
  parent Deep terminal is durably blocked
  OR recorded terminal integrity is unusable
```

---

# 60. Parent result does not imply success

例如：

```text
child_status = failed
```

parent 仍可以：

```text
status=completed
```

这里的 completed 意义：

> Deep execution reached an honest terminal and parent control plane has recorded it.

不是：

> research succeeded.

---

# 61. Deep-3 allowed files

实施时允许：

```text
NEW src/application/deep_continuation.py
NEW src/repositories/deep_continuation_repository.py
NEW src/application/deep_chat_service.py

MOD src/application/runtime_repository.py
MOD src/api/app.py              # only trigger lifecycle activation if needed

tests/test_deep_continuation.py
tests/test_deep_trigger_integration.py

docs/DEEP_3_CONTRACT.md
docs/PROJECT_STATUS.md
```

Deep-3T files 仅在发现真实 contract mismatch 时才能改；否则只消费其 API。

---

# 62. Forbidden files

Deep-3 不得修改：

```text
active_research_runtime.py
deep_execution.py
deep_runtime.py
deep_seed.py
deep_handoff.py
deep_handoff_repository.py

standard research semantics
Standard planner
Evidence Gain
Saturation
ResearchStopGate
gap planner
ResearchRuntimeCursor

synthesis
ResearchBrief publication
Final Answer Auditor
Persistent Research Memory publication

chat_service.py base semantics
pedagogy
learning state
frontend
DB migrations
```

如确实必须改：

```text
STOP
重新冻结
```

---

# 63. Deep-3 negative controls

至少覆盖：

```text
F1  no deep terminal
    → not_requested

F2  existing completed parent terminal
    → stable result / 0 child execution

F3  existing blocked terminal
    → stable / 0 child execution

F4  malformed recorded terminal
    → fail closed / no rewrite

F5  pending + missing child
    → blocked

F6  pending + lineage mismatch
    → blocked

F7  pending + child already completed
    → parent finalize / 0 DeepExecution calls

F8  pending + child partial
    → parent completed

F9  pending + child failed
    → parent completed, not blocked

F10 pending + child cancelled
    → parent completed, not restarted

F11 pending + live running child
    → deferred / parent pending

F12 pending + stale running child
    → Deep-2 resume same child

F13 DeepExecution deferred
    → parent pending

F14 DeepExecution completed
    → reload child before finalize

F15 DeepExecution blocked
    → parent blocked

F16 unknown DeepExecution exception
    → propagate / parent pending

F17 terminal child seed tampered before parent finalize
    → blocked

F18 execution envelope tampered before finalize
    → blocked

F19 handoff changed before finalize
    → blocked

F20 finalization result contains no raw bodies

F21 publication_authority always false

F22 child terminal commit → crash → retry
    → finalize only / 0 runtime

F23 parent finalization commit → response lost → retry
    → same terminal / 0 runtime

F24 two completed finalizers race
    → one durable result

F25 completed-vs-blocked race
    → first terminal wins

F26 assistant_message byte-identical

F27 lookup_terminal unchanged

F28 standard_continuation unchanged

F29 pedagogy unchanged

F30 learning state unchanged

F31 chat wrapper only wake()s

F32 request does not wait 180s Deep consumer

F33 lost wake recovered by periodic trigger scan

F34 process restart recovers ARM candidate

F35 process restart recovers PENDING candidate

F36 trigger callback exception cannot make safe answer fail

F37 same production WebLookup repository reused

F38 same production dispatcher reused

F39 no DB migration

F40 no Deep publication / answer regeneration
```

---

# 64. Mutation validation

至少对这些 hard gates 做 mutation：

```text
remove child-terminal short-circuit
→ F7/F22 fail

turn failed child into blocked parent
→ F9 fail

remove seed revalidation from finalize
→ F17 fail

allow second finalizer overwrite
→ F24/F25 fail

call Deep inline from chat wrapper
→ F32 fail

disable trigger periodic recovery
→ F33/F34/F35 fail
```

---

# 65. Deep-3 review gates

```text
G3-1   only valid pending Deep authority is consumed
G3-2   existing terminal first-wins
G3-3   parent/handoff lineage revalidated
G3-4   child lineage revalidated
G3-5   terminal child never re-executes
G3-6   live lease deferred
G3-7   stale child resumes through Deep-2
G3-8   provider/runtime terminal failure maps to parent completed
G3-9   only deterministic integrity maps blocked
G3-10  finalization transaction revalidates seed
G3-11  finalization transaction revalidates execution envelope
G3-12  control-plane-only result
G3-13  pending→completed atomic
G3-14  pending→blocked atomic
G3-15  first terminal wins
G3-16  crash after child terminal recoverable
G3-17  crash after parent commit idempotent
G3-18  unknown exceptions leave parent pending
G3-19  assistant immutable
G3-20  pedagogy/learning immutable
G3-21  publication_authority=false
G3-22  no answer regeneration
G3-23  request path never waits on Deep
G3-24  lost wake recoverable
G3-25  startup recovery works
G3-26  same repository singleton reused
G3-27  same dispatcher singleton reused
G3-28  no second research engine
G3-29  no DB migration
G3-30  focused tests pass
G3-31  trigger integration tests pass
G3-32  mutation checks pass
G3-33  adjacent Deep-1/2 regressions pass
G3-34  Standard continuation regressions pass
G3-35  chat complete/stream regressions pass
G3-36  ruff pass
G3-37  expanded mypy pass
G3-38  mypy baseline pass
G3-39  git diff --check pass
G3-40  file-boundary audit pass
G3-41  exact-head ordinary CI pass
```

---

# 66. Local candidate gate

一次性：

```text
Deep-3 focused
Deep-3T integration
Deep-1/Deep-2 regressions
Standard continuation
chat complete/stream
runtime composition
ruff
expanded mypy
mypy baseline
git diff --check
scope audit
```

---

# 67. CI discipline

Deep-3 不因为中间 implementation candidate 触发 formal L3。

```text
ordinary exact-head CI
```

是 Deep-3 merge gate。

Deep final formal L3 仍留给：

```text
Deep-4 / publication cutover
```

---

# 68. Commit discipline

Deep-3 一个 bounded slice：

```text
continuation service
+ finalization repository
+ chat wrapper
+ composition
+ trigger activation
+ tests
```

完成全部本地门后：

```text
1 commit
1 PR
```

不要按子模块逐次等 CI。

---

# 69. Deep-3 CLOSED 定义

Deep-3 CLOSED 表示：

```text
Standard unresolved result
可以自动进入 Deep

Deep 在后台执行
不会阻塞 safe answer

Deep crash 可恢复

Deep terminal 会可靠投影回 parent control plane
```

但仍：

```text
不会修改用户答案
不会发布 Deep evidence
不会运行 Deep synthesis publication
```

---

# 70. Deep-4 入口

只有：

```text
Deep-3T CLOSED
Deep-3 CLOSED
exact-main ordinary CI green
```

之后才能审计：

```text
ResearchBrief
synthesis
Final Answer Auditor
publication / answer update policy
```

以及最终 Deep L3。

---

# 71. 一句话模型

> **Deep-3 把 Deep-2 已经能可靠执行的研究 child，接到一个不阻塞聊天响应的 durable trigger 上；child 达到任何诚实 terminal 后，只把一个 bounded control-plane terminal 写回 parent。研究结果此时仍然只是后台事实，不拥有修改用户答案的权限。**
