# Deep-2 Detailed Implementation Contract

**状态：FROZEN**

**Seam authority：**

```text
exact-main:
41e2d6f9132b0e72b3cf058d913c304f9c066ea0
```

`41e2d6f9` 是 Deep-1 closeout 的 docs-only 后继；本合同已经重新基于该 exact-main 核对实际代码接口。

历史 authority 不变：

```text
Standard authority:
c48a1ac313e59ab0104364db519340f1460e84dc
L3 37514856913

Deep-1 authority:
e5c63c03c9ac77b273f2bfc158111ac676e9bc42
CI 37599443309
```

Deep-2 不得改写或取代上述 authority。

---

# 1. Deep-2 唯一目标

Deep-2 只完成：

```text
Deep-1 prepared child
→ validate Deep handoff + seed
→ attach Deep execution envelope
→ attach active ResearchState
→ expose Standard seed as normal assessment candidates
→ reuse durable seed bytes instead of network page read
→ invoke existing Claim Engine active runtime
→ resume same durable child after interruption
→ leave child in its existing runtime terminal state
```

Deep-2 **不负责**：

```text
automatic ChatService continuation
parent deep_terminal completed / blocked finalization
ResearchBrief publication projection
answer regeneration
assistant_message mutation
pedagogy mutation
learning_state mutation
publication authority
Deep phase final L3
```

Deep-2 实现完成后仍然是：

```text
production auto-continuation inert
publication_authority = false
```

自动 continuation 属于 Deep-3。

---

# 2. 已验证的现有 execution seam

## 2.1 Dispatcher

现有：

```text
ClaimEngineDispatchWebLookupService.execute(run_id)
```

行为：

```text
valid active Claim Engine state
→ ActiveResearchRuntimeExecutor.execute()

otherwise
→ legacy WebLookupService.execute()
```

因此 Deep-2 不建第二个 dispatcher / factory / gateway。

## 2.2 Claim Engine durable key

唯一 authority：

```text
research_context["claim_engine"]
```

通过：

```text
attach_claim_engine_state()
load_claim_engine_state()
```

读写。

## 2.3 Existing active runtime

唯一 active research engine：

```text
ActiveResearchRuntimeExecutor
```

Deep-2 不建立：

```text
DeepResearchLoop
DeepPlanner
DeepEvidenceGain
DeepSaturation
DeepStopGate
DeepResumeState
DeepCheckpoint
DeepRetryLedger
```

---

# 3. DeepExecution outcome

Deep-2 application service 对外 outcome 固定：

```python
DeepExecutionOutcome(
    status: Literal[
        "not_requested",
        "deferred",
        "completed",
        "blocked",
    ],
    parent_turn_id: str,
    child_run_id: str,
    reason: str,
)
```

含义：

```text
not_requested
    没有一个合法 pending Deep-1 handoff 需要执行

deferred
    同一 child 当前已有活跃 owner / 当前不能安全取得 execution ownership
    durable truth 仍可恢复

completed
    Deep child 已达到现有 runtime terminal
    注意：这不表示 parent deep_terminal 已 finalized

blocked
    deterministic integrity / admission failure
    0 active research dispatch
```

未知异常不得伪造为 `blocked`。

---

# 4. Parent authority

Deep-2 调用必须重新加载 server-owned parent。

要求：

```text
parent exists
parent.thread_id == caller thread_id
parent.status == completed
```

并读取：

```text
rag_snapshot.deep_terminal
```

Deep terminal 必须：

```text
schema valid
state == ESCALATE_DEEP
dispatch_status == pending
owner.thread_id == parent.thread_id
owner.turn_id == parent.id
publication_authority == false
```

若：

```text
不存在 Deep terminal
或 dispatch_status != pending
```

则：

```text
not_requested
```

但 malformed / owner mismatch / digest mismatch：

```text
blocked
```

不得当成 absent。

---

# 5. Deep-1 handoff 必须再次验证

Deep-2 不因为 Deep-1 已通过就盲信 durable bytes。

必须调用既有 Deep handoff validator，重新验证：

```text
handoff schema
reason
payload_sha256
publication_authority == false
parent_turn_id
standard_child_run_id
```

并要求：

```text
deep_terminal.child_run_id == Deep child.id
Deep child.owner_thread_id == parent.thread_id
Deep child.parent_run_id == handoff.standard_child_run_id
Deep child.query == handoff.query == parent.user_message
```

任一不符：

```text
blocked
0 dispatcher calls
0 network
0 model
```

---

# 6. Seed integrity

Deep child 中必须存在：

```text
research_context.deep.seed
```

schema：

```text
deep-seed-v1
```

必须重新验证：

```text
seed.standard_child_run_id
== handoff.standard_child_run_id

canonical(seed.refs)
== canonical(handoff.seed_source_refs)
```

每个 `seed.sources[]`：

```text
url
content_sha256
content
fields
origin
```

必须满足：

```text
content is non-empty
sha256(full durable content) == content_sha256
```

refs 与 sources 的：

```text
url
digest
sorted(unique(fields))
origin
```

必须一致。

任何 durable contradiction：

```text
blocked
0 active dispatch
0 network
0 model
```

不得 silently drop。

---

# 7. Deep execution envelope

Deep-2 新增 child-local durable control plane：

```python
research_context["deep"]["execution"] = {
    "schema_version": "deep-execution-v1",
    "budget_profile": "deep-v1",
    "parent_turn_id": parent_turn_id,
    "handoff_sha256": deep_handoff_payload_sha256,
    "admitted_at": "<UTC ISO timestamp>",
    "deadline_at": "<UTC ISO timestamp>",
    "publication_authority": False,
}
```

其中：

```text
deadline_at = admitted_at + 180 seconds
```

第一次成功 admission 后：

```text
admitted_at immutable
deadline_at immutable
handoff_sha256 immutable
budget_profile immutable
```

retry 不得重置时钟。

---

# 8. Deep v1 budget

固定：

```python
ResearchBudget(
    max_candidates=40,
    max_reads=12,
    soft_timeout_seconds=120,
    hard_timeout_seconds=180,
    max_total_chars=80_000,
    candidates_used=0,
    reads_used=0,
    elapsed_seconds=0.0,
)
```

不得修改现有全局：

```text
research model-call budget
model attempts
Evidence Gain thresholds
saturation thresholds
wave ceiling
finalization reserve
```

---

# 9. Reference date

首次创建 active ResearchState 时：

```text
reference_date
= persisted original parent.created_at
  normalized to UTC
  .date().isoformat()
```

不得使用 Deep 实际启动时间重新解释：

```text
today
current
latest
```

问题的 reference date。

---

# 10. Claim Engine attach-once state machine

Deep-2 dispatch 前必须显式区分 Claim Engine durable 状态。

## 10.1 Key absent

```text
"claim_engine" not in research_context
AND deep.execution absent
```

表示首次 admission。

允许创建 empty active state。

## 10.2 Existing valid active state

若 Claim Engine：

```text
status == available
effective_mode == active
state.mode == active
```

则：

```text
reuse exact durable state
```

不得：

```text
replace with empty state
clear claims
clear gaps
clear evidence
clear cursor
reset budget
reset elapsed_seconds
```

## 10.3 Present but unavailable

例如：

```text
unsupported schema
invalid payload
parse failure
```

必须：

```text
blocked
```

**绝不调用 dispatcher。**

## 10.4 Present but non-active

例如：

```text
shadow
off
```

必须：

```text
blocked
```

**绝不调用 dispatcher。**

---

# 11. S6 fail-closed：禁止 legacy downgrade

这是 Deep-2 hard gate。

现有 generic dispatcher 会：

```text
invalid / non-active Claim Engine
→ _dispatch_state() == None
→ legacy WebLookupService
```

Deep-2 **不得允许这个 fallback 发生**。

因此 Deep-2 application layer 必须在 dispatcher 前使用与 dispatcher 相同的 Claim Engine load authority。

推荐将 dispatcher 当前内部 loader 暴露为一个 read-only shared helper，使：

```text
DeepExecutionService
和
ClaimEngineDispatchWebLookupService
```

共享同一 load semantics。

不得复制第二套 evidence-id / state-validation 逻辑。

规则：

```text
claim_engine absent
    → first attach

available + active
    → reuse

其他任何 present state
    → blocked
    → dispatcher invocation count = 0
```

---

# 12. First admission 必须原子 attach

首次 admission 必须把以下两个 durable facts **一次 CAS write** 写入同一个 child context：

```text
deep.execution
claim_engine
```

不得产生合法 crash window：

```text
execution exists / claim_engine missing
```

或：

```text
claim_engine exists / execution missing
```

因此 WebLookupRepository 可增加一个**最小 pending-context CAS seam**。

语义固定：

```text
run.id matches
status == pending
version == expected_version

UPDATE only:
    research_context
    updated_at
    version += 1
```

不得：

```text
开始 operation
修改 selected_sources
修改 query_attempts
修改 parent
创建新 child
```

CAS conflict：

```text
reload once
→ 若另一 caller 已建立合法 attach，则 reuse
→ 若 child 已 running，则 deferred
→ 若 durable pair 不一致，则 blocked
```

禁止无限 retry。

---

# 13. Initial active ResearchState

首次 admission 构造：

```python
build_research_state(
    mode="active",
    questions=(),
    claims=(),
    evidence=(),
    evidence_links=(),
    source_clusters=(),
    gaps=(),
    conflict_gaps=(),
    budget=DEEP_V1_BUDGET,
    trace=(),
    brief=None,
    reference_date=parent_reference_date,
    known_evidence_ids=(),
)
```

特别注意：

> **Standard seed 不直接进入 `ResearchState.evidence`。**

seed 此时仍只是 durable bytes。

---

# 14. Absolute Deep clock

现有 active runtime：

```text
base_elapsed = state.budget.elapsed_seconds
elapsed = base_elapsed + current-process monotonic delta
```

单独使用会漏掉进程宕机时间。

Deep context 存在合法：

```text
deep.execution.schema_version == deep-execution-v1
```

时，active runtime 的 Deep-specific 最小 seam 必须：

```text
durable_elapsed = state.budget.elapsed_seconds
wall_elapsed =
    max(0, utc_now - deep.execution.admitted_at)

base_elapsed =
    max(durable_elapsed, wall_elapsed)

elapsed() =
    base_elapsed + current_process_monotonic_delta
```

因此：

```text
crash 90 秒
→ restart
→ 这 90 秒仍消耗 Deep hard window
```

非 Deep run：

```text
行为 bit-semantically unchanged
```

---

# 15. Invalid execution envelope

若 runtime 已进入 Deep child，但 execution envelope：

```text
schema invalid
deadline invalid
deadline != admitted_at + 180s
publication_authority != false
handoff hash mismatch
```

则必须在：

```text
model call
search
page read
```

之前 fail closed。

不得 fallback 到普通 active/legacy research。

---

# 16. Seed candidate 不是 completed read

明确禁止：

```text
seed ingest
→ RuntimeReadOutcome(success)
→ completed_read_ids
```

原因已由 exact-main 验证：

```text
assessment exclusion includes cursor.completed_read_ids
```

预标后 seed 会失去正常 assessment 资格。

---

# 17. Seed candidate 必须先获得 claim-specific semantic eligibility

Deep seed：

```text
不是 evidence
不是 supports
不是 contradiction
不是 source role
不是 cluster
```

必须正常经过：

```text
candidate pool
→ claim-specific candidate assessment
→ ranking
→ scheduler eligibility
```

之后才有资格 materialize。

---

# 18. Seed query binding seam

这是 exact-main seam audit 新增的 hard requirement。

现有：

```text
_candidates_for_claim(cursor, claim_id)
```

仅选择：

```text
candidate.query_ids
∩
planned_query_ids_for_claim
```

因此 seed 不能只加入：

```text
cursor.candidates
```

同时 `query_ids=()`。

否则：

```text
永远不会进入 assessment
```

---

# 19. Seed binding 的确切位置

每个 wave：

```text
claim planning complete
→ _append_gap_queries(cursor, state)
→ bind Deep seed candidates
→ checkpoint
→ external search
```

也就是 seed binding 必须发生在：

```text
_append_gap_queries()
之后
第一条 search external call 之前
```

这样：

```text
seed 占 candidate pool
search duplicate 可 merge
assessment 能看到 seed
```

---

# 20. Actionable claim binding

当前 wave：

```text
actionable_claim_ids
= claims referenced by _ordered_gaps(state)
```

即保持现有：

```text
open/searching
non-context
```

语义。

每个 seed candidate 绑定：

```text
所有当前 actionable claims 的 planned query IDs
```

而不是：

```text
Standard fields → Deep claim id
```

`fields` 只保留 provenance。

---

# 21. Seed binding 必须 wave-idempotent

后续 wave 可能产生新的 planned queries。

因此 seed binding 每个 wave 都重新执行：

```text
existing seed candidate
→ merge new eligible query IDs
→ merge corresponding intents
```

不得复制 candidate。

---

# 22. Seed candidate identity

URL identity 使用现有：

```text
canonicalize_url()
```

新建 seed candidate 的 deterministic ID：

```text
deep_seed_
+ sha256(canonical_url)[:16]
```

candidate 初始 shape：

```python
RuntimeCandidate(
    id=deterministic_seed_id,
    url=canonical_url,
    title=canonical_url,
    snippet="",
    source="deep_seed",
    published_at="",
    query_ids=current_actionable_query_ids,
    intents=current_actionable_query_intents,
    providers=("deep_seed",),
    first_seen_rank=stable_seed_index,
    discovery_method="deep_seed",
    discovery_depth=0,
)
```

---

# 23. Seed 占 candidate budget

Seed candidate：

```text
计入 len(cursor.candidates)
```

因此自然占：

```text
max_candidates = 40
```

不得为 seed 建第二套免费 candidate pool。

---

# 24. Search duplicate merge

Seed 在 search 前已经存在。

若 search 后发现同 canonical URL：

```text
_merge_runtime_candidates()
→ 同一个 candidate
→ merge search query ids / intents / providers
```

不得创建第二个同 URL candidate。

不得因为 search 又看到 URL 而删除 seed-backed bytes。

---

# 25. Standard fields 不授予 eligibility

以下是禁止行为：

```text
fields=["release_date"]
→ 自动把 source 绑定给 release-date claim
```

Deep claim decomposition 是新的模型结果。

Standard：

```text
fields
origin
```

仅是 provenance。

---

# 26. Seed-backed candidate lookup

运行时必须能根据：

```text
candidate canonical URL
```

找到对应 durable seed source。

匹配 authority：

```text
canonical URL
```

不是：

```text
candidate ID
```

因为 search merge 后 candidate identity metadata 可以扩展，但 source URL identity 不变。

---

# 27. Content-available truth

必须区分：

```text
reader-chain terminal
```

与：

```text
content already durably available
```

定义：

```text
seed_materialized_ids =
    selected_sources where:
        final_backend == "deep_seed"
        AND read_status == "read"

content_available_ids =
    cursor.completed_read_ids
    UNION
    seed_materialized_ids
```

**注意：**

`content_available_ids` 只用于：

```text
physical-content reuse / extraction restore / reread suppression
```

不得用于 initial assessment exclusion。

---

# 28. Assessment exclusion 不得改成 content_available

仍保持现有：

```text
cursor.completed_read_ids
+ already-ranked-for-this-claim
```

因为一个已 materialize 的 seed：

```text
仍可能需要对 later/new claim 做第一次 assessment
```

不能因为 bytes 已有就获得/失去另一 claim 的 semantic eligibility。

---

# 29. Physical read planning

read plan 中：

```text
rankings_for_plan
```

不得重新计划 `content_available_ids` 的 physical page read。

同时 extraction restore 必须允许：

```text
content_available seed
+ valid per-claim RankedCandidate
→ extraction target
```

因此现有：

```text
_restore_completed_read_targets()
```

可以最小泛化为：

```text
content_available ids
```

但仍必须保持原原则：

> bytes reuse 永远不授予另一 claim semantic eligibility；恢复 binding 必须来自该 claim 自己的 ranking。

---

# 30. LOCAL MATERIALIZE 的正确分流位置

不得仅插在：

```text
read_site_specialist_step()
```

之前。

正确顺序是：

```text
candidate planned for physical content
→ already content_available? skip physical read
→ ensure_active
→ ensure hard budget
→ resolve candidate

IF candidate is seed-backed:
    LOCAL MATERIALIZE
ELSE:
    physical max_reads gate
    MIN_READ_SECONDS gate
    reader scheduling
    specialist/default chain
```

原因：

```text
seed materialization != physical read
```

因此不能被：

```text
successful_reads >= max_reads
```

错误挡住。

---

# 31. Seed 仍受 hard time window

LOCAL MATERIALIZE 虽然不需要：

```text
MIN_READ_SECONDS
```

但不得绕过：

```text
hard timeout
research finalization reserve boundary
```

规则：

```text
hard budget exhausted
→ no materialization

research_seconds_left <= 0
→ no new materialization
```

不得侵占 finalization reserve 启动新研究工作。

---

# 32. Seed 仍受 char budget

LOCAL MATERIALIZE 必须检查：

```text
remaining_chars =
max_total_chars - used_chars
```

若：

```text
remaining_chars <= 0
```

则不能 materialize。

Deep-visible content：

```text
source_limit =
min(6000, remaining_chars)

content =
full durable seed body[:source_limit]
```

只对实际 Deep-visible chars 收费。

---

# 33. used_chars durable 计算

现有 network chars：

```text
ACTIVE_RESEARCH_METRICS.reads[].content_chars
```

仍保留。

额外加：

```text
所有已 persisted Deep seed source record 中
read.content 的实际长度
```

要求：

```text
final_backend == deep_seed
read_status == read
```

同 candidate 只计一次。

因此 crash/restart 后 seed char consumption 不会归零。

---

# 34. LOCAL MATERIALIZE 不增加 reads_used

materialization：

```text
successful_reads 不增加
state.budget.reads_used 不增加
```

即使：

```text
reads_used == max_reads
```

只要：

```text
hard/research window仍开放
char budget仍有空间
```

已选中的 seed 仍可以 LOCAL MATERIALIZE。

---

# 35. LOCAL MATERIALIZE 禁止产生外部 attempt

LOCAL MATERIALIZE 必须是：

```text
0 gateway.read
0 read_site_specialist_step
0 run_chain
0 RuntimeExternalAttemptStart
0 begin_external_attempt
0 finish_external_attempt
0 record_read_chain_attempt
0 breaker update
0 retry ledger
```

并且：

```text
不得制造假的 RuntimeReadOutcome
```

---

# 36. LOCAL MATERIALIZE persisted source shape

必须复用现有：

```text
_source_record()
_upsert_source()
```

以保证后续 evidence identity / extraction shape 一致。

调用语义：

```python
_source_record(
    candidate,
    plan_item,
    raw_read={
        "ok": True,
        "status": "read",
        "url": candidate.url,
        "content": materialized_content,
    },
    final_backend="deep_seed",
    retrieval_attempts=[],
)
```

注意：

现有 `_source_record()` 对空 attempts 不持久化 `retrieval_attempts` key。

因此 durable source **不要求**存在：

```text
retrieval_attempts=[]
```

---

# 37. LOCAL MATERIALIZE 不伪造 retrieval_state

Deep-2 v1 中：

```text
raw_read.retrieval_state
```

对 seed **省略**。

原因：

```text
没有发生 retrieval
```

不得伪造：

```text
native_http ok
browser ok
```

也不向现有 retrieval-state vocabulary 新塞 `"seed"`。

provenance 由：

```text
final_backend = "deep_seed"
materialization block
```

表达。

---

# 38. Materialization provenance

seed source record 额外增加：

```python
record["materialization"] = {
    "schema_version": "deep-seed-materialization-v1",
    "kind": "deep_seed",
    "origin": "standard_seed",
    "standard_origin": seed_source["origin"],
    "source_content_sha256": seed_source["content_sha256"],
    "materialized_chars": len(materialized_content),
    "truncated": len(materialized_content) < len(full_seed_body),
}
```

这里：

```text
source_content_sha256
```

是**完整 Standard durable body** 的 hash。

不得声称它是被截断后的 6000-char materialization hash。

---

# 39. Checkpoint ordering

LOCAL MATERIALIZE：

```text
construct record
→ _upsert_source(selected_sources, record)
→ used_chars += materialized chars
→ update_budget(reads_used=successful_reads)  # unchanged
→ checkpoint()
```

checkpoint 后：

```text
content is durable
```

随后才允许 extraction。

---

# 40. Crash before materialization checkpoint

若：

```text
local bytes loaded in memory
→ process crash
→ source record 未 checkpoint
```

retry：

```text
再次 LOCAL MATERIALIZE 相同 durable bytes
```

允许。

因为：

```text
0 network
0 reads_used
deterministic content
```

不是重复外部操作。

---

# 41. Crash after materialization checkpoint

若：

```text
seed source persisted
→ crash before extraction
```

resume：

```text
candidate ∈ content_available_ids
→ 0 network
→ 不再次 materialize/charge chars
→ 从该 claim 自己的 persisted ranking 恢复 extraction target
```

---

# 42. Later wave reread suppression

任何已经 seed-materialized candidate：

```text
不得再次进入 page physical read
```

即使后续：

```text
新 wave
新 query
同 URL search result
新 claim binding
```

bytes 仍复用原 durable source。

---

# 43. Lead-read hard guard

这是 seed no-reread 的补充 hard gate。

现有 lead subsystem 也可以安排 page read。

Deep-2 v1 **不实现 seed local lead-discovery**。

因此：

```text
所有 seed-backed candidate IDs
```

必须从：

```text
physical lead-read scheduling
```

中排除。

不得发生：

```text
seed assessed as lead_only
→ lead planner
→ network read same seed URL
```

未来若要利用 seed bytes 做 lead discovery：

```text
单独 bounded slice + 新合同
```

Deep-2 v1 不做。

---

# 44. Late-tail assessment

Late-tail assessment 仍保持：

```text
claim-specific semantic assessment
```

Seed 不因为 local bytes 可用而自动获得 late-tail eligibility。

不得用 `content_available_ids` 代替其 semantic exclusion authority。

---

# 45. Evidence extraction

LOCAL MATERIALIZE 后的 seed source：

```text
与正常 read-backed source 一样
```

进入现有 extraction。

不得增加 Deep-specific extractor。

---

# 46. Evidence Gate

Seed extraction 后仍必须经过既有：

```text
Evidence Gate
```

Standard seed 绝不直接产生：

```text
eligible evidence
supports
contradicts
source cluster authority
claim resolution
```

---

# 47. Evidence Gain

Deep-2 完全复用已有六类 Evidence Gain：

```text
new_eligible_evidence
new_independent_cluster
better_source_role
new_contradiction
new_provenance_lead
claim_status_improvement
```

以下仍不是 gain：

```text
仅有 seed candidate
仅有 read/materialized bytes
仅有新 URL
仅有 search result
same-cluster repeat
```

---

# 48. Saturation

完全复用现有：

```text
normal: 2 consecutive no-gain batches
critical/conflict: +1 batch
```

Deep-2 不改。

---

# 49. Wave ceiling

完全复用：

```text
MAX_RESEARCH_WAVES = 8
```

wave ceiling 仍不等于 saturation。

---

# 50. Stop Gate

继续复用现有 ResearchStopGate priority。

Deep-2 不加入：

```text
Deep-specific stop reason priority
```

---

# 51. Model budget

Seed：

```text
assessment
extraction
```

照常花现有 research model-call budget。

只有 physical page bytes 是复用的。

不得：

```text
seed bytes 免费
→ model calls 也免费
```

---

# 52. Runtime cursor authority

继续使用：

```text
ResearchRuntimeCursor
load_runtime_cursor()
recover_interrupted_model_attempt()
recover_interrupted_external_attempt()
```

Deep-2 禁止新建 resume schema。

---

# 53. Runtime cursor 不保存 seed body

Seed body authority 始终是：

```text
research_context.deep.seed.sources
```

Runtime cursor 只持有：

```text
candidate identity
query binding
runtime state
```

不得复制 full seed body 到 cursor。

---

# 54. First-dispatch runtime revalidation

DeepExecutionService 在 dispatcher 前验证一次。

Active runtime 在真正开始模型/外部工作前，还必须重新验证 Deep-specific：

```text
execution envelope
seed schema
seed body hashes
```

用于关闭：

```text
service validate
→ DB/context tamper
→ runtime execute
```

之间的 TOCTOU。

失败：

```text
0 model
0 network
```

---

# 55. Deep child terminal

Deep-2 认为以下 child status 是 terminal：

```text
completed
partial
failed
cancelled
```

若调用时 child 已 terminal：

```text
return completed
0 dispatcher calls
```

不得因为 generic WebLookupRepository 某些 terminal 状态“可 resumable”就自动重新研究。

Deep-3 再决定 parent 如何映射这些 terminal。

---

# 56. Running child

若 child：

```text
status == running
```

且现有 operation owner 尚有效：

```text
deferred("lease_busy")
```

不得建立第二个 active operation。

若 existing operation stale：

```text
复用现有 begin_operation stale-recovery authority
```

不得新建 lease subsystem。

---

# 57. Pending child

若：

```text
pending
+ valid execution envelope
+ valid active state
```

调用 existing dispatcher。

---

# 58. Attach race

两个 caller 同时首次启动：

```text
A/B 都看到 absent
A CAS attach succeeds
B CAS attach conflicts
```

B：

```text
reload durable child
→ 看到合法 execution + active state
→ 不重新 attach
```

随后 operation lease 保证：

```text
最多一个 active executor
```

---

# 59. Deep clock on resume

每次 active runtime invocation：

```text
wall_elapsed
```

重新由原始 `admitted_at` 计算。

不得：

```text
retry_at
restart_at
new operation start
```

成为新的 Deep tier clock origin。

---

# 60. Deep-2 不修改 parent

整个 Deep-2：

```text
parent rag_snapshot bit-identical
assistant_message bit-identical
route_snapshot bit-identical
pedagogy_snapshot bit-identical
learning_state untouched
```

尤其：

```text
deep_terminal.dispatch_status
```

仍保持：

```text
pending
```

Deep-3 才 finalize。

---

# 61. Publication authority

所有 Deep-2 新 durable shapes：

```text
publication_authority = false
```

且：

```text
Evidence Gate PASS
!= publication authority
```

---

# 62. No automatic production activation

Deep-2 不允许改：

```text
ChatService
StandardContinuationChatService
runtime_repository production composition
```

DeepExecutionService 可以在测试/显式调用中运行。

自动调用属于 Deep-3。

---

# 63. Deterministic integrity failure

以下可以 `blocked`：

```text
parent/terminal owner mismatch
Deep handoff digest failure
child lineage mismatch
seed refs mismatch
seed body hash mismatch
invalid Deep execution envelope
Claim Engine present-but-invalid
Claim Engine non-active
execution/state asymmetric attach
```

---

# 64. Runtime/research outcome 不是 integrity blocked

以下不是 admission integrity failure：

```text
provider unavailable
search empty
reader failure
model attempt exhaustion
no evidence gain
saturation
hard budget
wave ceiling
user cancellation
```

它们属于 existing active runtime outcome。

不得改写为 Deep admission `blocked`。

---

# 65. Unexpected exception

Deep-2 application layer：

```text
不得把未知 Python exception 猜成 deterministic blocked
```

未知异常：

```text
propagate
parent unchanged
```

Deep-3 的 fail-safe wrapper 以后负责保护 chat delivery。

---

# 66. Allowed production-code surface

Deep-2 bounded slice 允许：

| 文件 | 权限 |
|---|---|
| `NEW src/application/deep_execution.py` | Deep-2 admission / attach / explicit execution service |
| `NEW src/web/research/deep_runtime.py` | Deep execution envelope、seed runtime helpers、absolute-clock helpers |
| `src/application/active_research_runtime.py` | **仅** seed bind / content-available / local materialize / Deep absolute-clock 最小 seam |
| `src/application/research_web_lookup_dispatch.py` | **仅**暴露 shared Claim Engine load authority，关闭 S6 drift；不得改 legacy dispatch semantics |
| `src/repositories/web_lookup_repository.py` | **仅** pending child context CAS attach helper |
| Deep-2 tests | 新增 focused / integration / runtime seam tests |
| docs | `DEEP_2_CONTRACT.md` + Current Action 更新 |

---

# 67. Forbidden files / semantics

Deep-2 不得修改：

```text
src/application/deep_handoff.py
src/repositories/deep_handoff_repository.py
src/web/research/deep_handoff.py
src/web/research/deep_seed.py

Evidence Gain implementation
gap planner semantics
ResearchStopGate priority
ResearchRuntimeCursor schema
ResearchState schema
phase/model budget constants
reader backend chain definitions
synthesis assembler
ResearchBriefProjection
FinalAnswerAuditor
Persistent Research Memory
ChatService
runtime production composition
frontend
DB migrations
```

如实现发现必须修改其中任一：

```text
STOP
合同假设错误
```

---

# 68. Existing non-Deep regression invariant

无：

```text
deep.execution
```

的 active Claim Engine run：

```text
absolute-clock behavior unchanged
seed behavior absent
reader planning unchanged
read budget unchanged
lead scheduling unchanged
```

Legacy path：

```text
bit-semantically unchanged
```

---

# 69. Deep-2 negative controls

必须至少覆盖：

```text
E1  no Deep terminal → not_requested / 0 dispatch

E2  malformed Deep terminal → blocked / 0 dispatch

E3  Deep handoff digest tampered → blocked / 0 dispatch

E4  Deep child wrong owner/parent/query → blocked

E5  seed ref mismatch → blocked

E6  seed body digest mismatch → blocked / 0 model / 0 network

E7  claim_engine absent + execution absent
    → atomic first attach

E8  claim_engine present unavailable
    → blocked / dispatcher not called
    → legacy path count = 0

E9  claim_engine shadow/non-active
    → blocked / dispatcher not called

E10 claim_engine active + execution absent
    → blocked

E11 execution exists + claim_engine absent
    → blocked

E12 valid active retry
    → same admitted_at / same deadline / same ResearchState

E13 crash downtime counts against elapsed_seconds

E14 seed is NOT preinserted into completed_read_ids

E15 seed receives actionable planned query IDs

E16 seed enters claim assessment

E17 Standard fields do not directly bind Deep claims

E18 seed counts against max_candidates

E19 search duplicate seed URL does not create second candidate

E20 seed selected for content
    → gateway.read calls = 0

E21 seed selected
    → RuntimeExternalAttemptStart count unchanged

E22 seed selected
    → breaker/retry ledger unchanged

E23 seed selected
    → reads_used unchanged

E24 seed selected
    → visible chars count against max_total_chars

E25 reads_used already at max_reads
    → eligible seed may still materialize

E26 char budget exhausted
    → seed does not materialize

E27 research window closed
    → seed does not start new materialization

E28 persisted source has:
       read_status=read
       final_backend=deep_seed
       materialization-v1 provenance

E29 no fake retrieval_state

E30 crash before materialization checkpoint
    → local deterministic rematerialize
    → 0 network

E31 crash after materialization checkpoint before extraction
    → no rematerialize charge
    → no network
    → extraction resumes

E32 later wave
    → materialized seed never physical-read again

E33 newly bound claim
    → bytes reuse allowed only after that claim has its own ranking

E34 seed candidate excluded from physical lead-read scheduling

E35 seed alone does not become evidence

E36 seed extraction still requires Evidence Gate

E37 Evidence Gain semantics unchanged

E38 saturation semantics unchanged

E39 8-wave ceiling unchanged

E40 active runtime interrupted model attempt
    → existing recovery used

E41 active runtime interrupted external attempt
    → existing recovery used

E42 terminal child
    → second Deep-2 call does not execute runtime again

E43 concurrent first admission
    → one execution envelope
    → one active state
    → one operation owner

E44 parent deep_terminal remains pending

E45 assistant_message unchanged

E46 pedagogy / learning state unchanged

E47 publication_authority false

E48 ordinary non-Deep active runtime regression unchanged

E49 legacy dispatch regression unchanged
```

---

# 70. Deep-2 review gates

Deep-2 只有全部满足才 CLOSED：

```text
G2-1  consumes exact Deep-1 pending authority
G2-2  handoff/child/seed integrity fail closed
G2-3  Claim Engine absent vs invalid explicitly separated
G2-4  invalid/non-active Claim Engine can never downgrade to legacy
G2-5  execution envelope + active state attach atomically
G2-6  attach-once / stable admitted_at
G2-7  absolute Deep wall clock survives crash
G2-8  existing ResearchRuntimeCursor resume authority reused

G2-9  seed candidate not pre-marked completed
G2-10 seed bound to actionable Deep planned queries
G2-11 seed participates in normal claim assessment
G2-12 Standard fields grant no semantic authority
G2-13 seed occupies max_candidates
G2-14 duplicate URL merges

G2-15 local materialize happens before physical-read gates
G2-16 seed uses 0 network
G2-17 seed creates 0 external attempt markers
G2-18 seed consumes 0 reads_used
G2-19 seed consumes actual char budget
G2-20 materialized source shape is compatible with existing extraction

G2-21 content-available truth prevents reread
G2-22 crash-after-materialize resumes extraction
G2-23 seed cannot leak into physical lead-read path
G2-24 extraction + Evidence Gate remain mandatory

G2-25 Evidence Gain unchanged
G2-26 saturation unchanged
G2-27 Stop Gate unchanged
G2-28 wave ceiling unchanged
G2-29 model budget unchanged
G2-30 normal reader chain unchanged

G2-31 parent stays pending
G2-32 no publication
G2-33 no assistant mutation
G2-34 no pedagogy/learning mutation
G2-35 no automatic ChatService activation

G2-36 focused tests pass
G2-37 adjacent active-runtime / dispatch regressions pass
G2-38 ruff pass
G2-39 mypy baseline pass
G2-40 git diff --check pass
G2-41 file-boundary audit pass
G2-42 exact-head ordinary CI pass
```

---

# 71. Local candidate gate

Deep-2 candidate push 前本地最低门：

```text
focused Deep-2 tests
adjacent active-runtime tests
dispatch tests
Deep-1 regression tests
ruff
expanded mypy / repository mypy baseline gate
git diff --check
scope/file-boundary audit
```

继续执行已经固化的规则：

> **mypy baseline 是 candidate gate，不得再只跑 ruff + focused。**

---

# 72. CI discipline

Deep-2 当前无专门 CI category。

如果分类器因为新路径 fallback 到 ordinary full pytest：

```text
允许一次安全 fallback
```

不为减少一次 CI 而修改 classifier。

Deep-2 本身：

```text
不触发 formal L3
```

formal Deep L3 留到最终 Deep production authority cutover。

---

# 73. Commit discipline

一次完整 bounded slice：

```text
实现全部 Deep-2 frozen scope
→ focused
→ adjacent
→ mypy baseline
→ ruff/diff/scope
→ 一个 implementation commit
→ 一个 PR CI
```

不要：

```text
seed candidate 一个 commit
materialize 一个 commit
clock 一个 commit
然后每次等 CI
```

---

# 74. Deep-2 CLOSED 的定义

Deep-2 CLOSED 只表示：

```text
Deep-1 prepared child
已经可以安全进入现有 active research runtime

Standard seed:
可被正常 assessment
可零网络复用 bytes
可过 extraction / Evidence Gate

Deep:
有独立 budget
有绝对 wall clock
有 crash-resume
```

Deep-2 CLOSED **不表示**：

```text
用户答案自动等待 Deep
parent terminal 已完成
Deep answer 已发布
Release GO
```

---

# 75. Deep-3 入口条件

只有 Deep-2：

```text
merged
exact-main ordinary CI green
Deep-2 CLOSED recorded
```

之后才能重新基于新的 exact-main 做 Deep-3 seam audit。

Deep-3 的入口事实将是：

```text
parent deep_terminal pending
Deep child durable
Deep child either:
    running/resumable
    or terminal
```

Deep-3 才拥有：

```text
automatic continuation
parent finalization
safe-chat fail-safe composition
```

---

# 76. 一句话实现模型

> **Deep-2 不是“重新抓一遍 Standard 已经抓过的网页”，而是把 Standard 已持久化的网页字节作为普通 Deep candidate 重新接受语义审查；只有当现有 scheduler 真正认为它值得用于某个 Deep claim 时，才从 durable seed 本地 materialize 内容，零网络、零 read slot，然后继续走原有 extraction、Evidence Gate、Evidence Gain、saturation 与 crash-resume。**
