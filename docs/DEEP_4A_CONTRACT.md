# Deep-4A Synthesis and Audit Artifact Contract

**状态：FROZEN semantics**

**Implementation gate：**

```text
Deep-3 CLOSED
+ Deep-3 exact-main 窄 seam recheck（已完成，PASS）
```

不得在 Deep-3 尚未 CLOSED 时开始 Deep-4A production implementation。

---

# 1. Authority

当前 semantic seam authority：

```text
e5382659b0aa1deca9954702b108aa51ef745e93
```

既有 authority：

```text
Standard   c48a1ac313e59ab0104364db519340f1460e84dc / L3 37514856913
Deep-1     e5c63c03c9ac77b273f2bfc158111ac676e9bc42 / CI 37599443309
Deep-2     1514bbf76031dfeca2cb03e9c52adf5d149cd724 / CI 37628909373
Deep-3T    823265ae113c0f488e0e8d2d0a448c6079b80884 / CI 37642664449
Deep-3     e5382659b0aa1deca9954702b108aa51ef745e93 / CI 37654811749（exact-main CI 待确认）
```

Deep-3 exact-main 窄 seam recheck（在 `e5382659` 上）已 PASS，以下文件 byte-identical：

```text
deep_continuation.py
deep_continuation_repository.py
deep_trigger.py
research_web_lookup_dispatch.py
research_brief_projection.py
synthesis_assembler.py
final_answer_auditor.py
```

---

# 2. Deep-4A 唯一目标

Deep-4A 把一个已经 finalize 的 Deep child，推进为一个**可复核、可恢复、fail-closed 的
publication candidate artifact**：

```text
Deep-3 completed parent
→ durable PUBLICATION discovery
→ reload Deep child
→ revalidate Deep-3 terminal digest / lineage
→ claim_engine_load(child)
→ validated active ResearchState
→ ResearchBriefProjection
→ unit-safe evidence projection
→ deterministic synthesis
→ FinalAnswerAuditor
→ durable audited artifact
```

---

# 3. Deep-4A 明确不做

```text
automatic publication
publication_authority = true
assistant_message rewrite
answer regeneration for the user
pedagogy / learning-state mutation
Persistent Research Memory publish
UI / answer revision rendering
qualified judge selection
```

Deep-4A CLOSED **不等于** Deep automatic answer publication CLOSED。

---

# 4. Deep-4B 是独立 qualification-gated 阶段

Deep-4B 只有存在 **qualified semantic judge** 后才可讨论。

当前 authority：

```text
qualified_judge          = false
formal_semantic_label    = false
release_gate             = NO_GO
```

失败的正是 Deep-4 publication 最不能猜的地方：

> citation 指向真实来源 与 citation 真正支持这句话 没有可靠区分。

因此：

```text
Deep-4A 不得把任意 LLM 塞进 FinalAnswerAuditor.judge
Deep-4A 不得因为 synthesis mechanical gate 通过就 publication_authority=true
```

qualified judge 需要成为 server-owned authority：

```text
judge identity
qualification artifact
qualification digest
holdout identity
qualification result
```

Deep-4B publication 必须同时通过：

```text
① ResearchBrief / synthesis mechanical validation
② Final Answer Auditor semantic PASS
③ Evidence Gate full-publication shape
④ answer-claim binder fully bound
⑤ answer consistency gate PASS
```

才允许 `publication_authority=true`。

---

# 5. Durable trigger：同一 runner 新增第三阶段

**复用同一个 `DeepTriggerRunner`**，不建第二 worker、不建 queue table。

discovery 顺序固定：

```text
ARM
→ PENDING
→ PUBLICATION
```

新增 durable work item：

```text
deep_terminal == valid completed
AND
deep_publication absent / pending
```

因此：

```text
Deep-3 finalization 完成
→ 同一次 scan 即可进入 Deep-4A
```

任何阶段 crash 都能靠 DB durable truth 重新发现。

## 5.1 PUBLICATION minimum filter

只发现：

```text
parent.status == completed
deep_terminal.schema_version == standard-deep-terminal-v1
deep_terminal.state == ESCALATE_DEEP
deep_terminal.dispatch_status == completed
deep_publication absent 或 dispatch_status == pending
```

已 `audited` / `blocked` 的 parent 不进入 trigger。

---

# 6. Parent durable schema：`deep_publication`

parent `rag_snapshot` 新增：

```python
{
    "schema_version": "deep-publication-v1",
    "dispatch_status": "pending" | "audited" | "blocked",

    "child_run_id": ...,
    "child_terminal_sha256": ...,

    "research_state_sha256": ...,
    "projection_sha256": ...,
    "draft_sha256": ...,

    "audit_verdict": ...,
    "approval_status": ...,
    "question_coverage": ...,
    "evidence_grounding": ...,
    "issue_codes": [...],

    "judge_authority": "none",
    "publication_authority": False,
}
```

## 6.1 禁止放入

```text
raw evidence
page bodies
full ResearchState
full synthesis evidence text
model traces
child research_context
```

## 6.2 status vocabulary

```text
pending
audited
blocked
```

`audited` **不表示 approved**。当前无 qualified judge，因此正常终态就是：

```text
approval_status = audited-but-not-approved
publication_authority = false
```

---

# 7. Multi-unit evidence collision 必须修（implementation gate）

## 7.1 现状缺陷

```text
ResearchEvidence → up to 32 EvidenceUnit
collect_evidence_payloads(state) 对每个 unit 生成 EvidencePayload(evidence_id=同一 id)
assembler / auditor 随后 by_id = {payload.evidence_id: payload}
```

⇒ 同一 evidence 的多个 unit 被**静默覆盖**，只留最后一个。

multi-unit 是正式 contract，不是异常输入，因此 Deep-4A 不得原样接上生产。

## 7.2 要求

> synthesis data plane 必须保留一个 evidence 的**全部** units，不得用 evidence_id map 静默丢 unit。

具体 aggregation / unit-ref 形状在实现时冻结，但必须满足：

```text
一个 evidence 的全部 units 都进入 projection
assembler / auditor 不得以 evidence_id 为唯一键覆盖 unit
citation / stance 检查必须能区分同一 evidence 的不同 unit
```

## 7.3 必须覆盖

```text
1 evidence → 1 unit    （既有行为不变）
1 evidence → N units   （不得覆盖，全部保留）
N evidence → 各自 units（不得互相覆盖）
```

---

# 8. Deep-4A 状态机

```text
read parent
↓
read deep_terminal
↓
not valid completed  → not_requested / blocked（按 authority 判定）
↓
read deep_publication
↓
already audited/blocked → 返回既有 artifact（first terminal wins）
↓
pending / absent → 原子写 pending（CAS）
↓
reload Deep child
↓
revalidate：
  child.id == deep_terminal.child_run_id
  child.owner_thread_id == parent.thread_id
  child.parent_run_id == handoff.standard_child_run_id
  child.query == handoff.query == parent.user_message
  child terminal status
  child_terminal_sha256 == deep_terminal.result.child_terminal_sha256
↓
claim_engine_load(child)
↓
不是 available + active → blocked（claim_engine_unusable）
↓
ResearchBriefProjection(state)
↓
unit-safe evidence projection
↓
deterministic synthesis
↓
FinalAnswerAuditor
↓
写 deep_publication = audited
```

---

# 9. Deep child state 读取 authority

继续使用：

```text
claim_engine_load(run)
```

它基于 canonical evidence IDs 校验，只有 `available + active` 才返回 state。

```text
不复制 ResearchState 到 parent
不建第二 research schema
不新建 Deep 版 projection / synthesis / auditor
```

---

# 10. Final Answer Auditor authority

复用现有：

```text
ResearchBriefProjection
SynthesisAssembler
FinalAnswerAuditor
```

当前 production judge：

```text
NONE
```

因此 auditor 正常返回：

```text
verdict = fail
approval_status = audited-but-not-approved
```

Deep-4A **不得**改变这个 fail-closed 行为。

---

# 11. Answer Claim Binder 的定位

`answer_claim_binder` / `answer_consistency` / `research_binding_rows()` 是**机械 pre-gate**，
Deep-4A 可以复用，但**不能替代 semantic judge**：

```text
“这个 evidence id 是真实 support row”
≠
“这个句子的具体语义真的被 evidence 支持”
```

Deep-4A 不因此提升 publication_authority。

---

# 12. Persistent Research Memory 明确排除

```text
opt-in only
historical lead only
claims = unresolved
confirmed requires qualified audit
```

Deep-4A：

```text
不得自动 ResearchMemoryService.publish()
不得把 audited draft 写成 confirmed memory
```

---

# 13. Immutability

Deep-4A 必须保持：

```text
assistant_message   bit-identical
pedagogy_snapshot   bit-identical
learning_state      bit-identical
lookup_terminal     bit-identical
standard_continuation bit-identical
ResearchMemory      untouched
```

除 `rag_snapshot.deep_publication` 外，parent 其他 key 语义与值不变。

---

# 14. 用户可见性边界

当前前端对 `GET /chat/turns/{id}/status` 的轮询只用于 cancellation，正常 completed turn
不会继续轮询 Deep revision。

因此：

```text
❌ 后台直接 UPDATE chat_turns.assistant_message = Deep answer
```

会产生：

```text
用户屏幕显示 safe answer
数据库 history 已是 Deep answer
用户下一问的客户端 history 仍是 safe answer
pedagogy_snapshot / learning_state / assistant evaluation 都围绕原 safe answer 冻结
```

⇒ 用户看到的历史 ≠ 服务端 durable history ≠ pedagogy truth。

正确形态是 **answer revision**（safe answer 永远保留 + 独立 Deep revision），属独立
UI/cutover 合同，Deep-4A 不做。

---

# 15. Deep-4A allowed files

```text
NEW  src/application/deep_publication.py
NEW  src/repositories/deep_publication_repository.py

MOD  src/repositories/deep_trigger_repository.py      # 新增 PUBLICATION discovery
MOD  src/application/deep_trigger.py                  # 新增第三阶段 seam
MOD  src/application/runtime_repository.py            # composition

MOD  synthesis evidence projection 所在模块            # multi-unit 修复（最小）
MOD  tests/test_synthesis_assembler.py                # multi-unit 回归

NEW  tests/test_deep_publication.py
NEW  tests/test_deep_trigger_publication.py

docs/DEEP_4A_CONTRACT.md
docs/PROJECT_STATUS.md
```

若 multi-unit 修复必须触及 `research_brief_projection.py` / `final_answer_auditor.py`：
允许，但仅限 unit 保留语义，不得改 mechanical gate 语义。

---

# 16. Forbidden files / semantics

```text
chat_service.py base semantics
standard_* semantics
deep_handoff.py / deep_seed.py / deep_execution.py / deep_continuation*.py
active_research_runtime.py research semantics
Evidence Gain / saturation / Stop Gate / gap planner
ResearchRuntimeCursor schema
pedagogy
learning state
Persistent Research Memory publish path
frontend
DB migrations
qualified judge selection / model choice
```

如确实必须改：

```text
STOP
重新冻结
```

---

# 17. Deep-4A negative controls

```text
P1  deep_terminal 非 valid completed → not_requested
P2  deep_publication 已 audited → first terminal wins，0 re-synthesis
P3  deep_publication 已 blocked → 原样返回
P4  malformed recorded deep_publication → fail closed，0 rewrite
P5  child missing / lineage mismatch → blocked
P6  child_terminal_sha256 与 deep_terminal.result 不符 → blocked
P7  claim_engine 非 available+active → blocked
P8  正常路径 → audited-but-not-approved，publication_authority=false
P9  audited artifact 只含 bounded control plane
P10 assistant_message bit-identical
P11 pedagogy_snapshot / learning_state bit-identical
P12 lookup_terminal / standard_continuation bit-identical
P13 ResearchMemory untouched
P14 crash after pending → restart 重新发现
P15 crash after audited → 返回既有 artifact
P16 two runners 并发 → 一个 artifact（first terminal wins）
P17 同一 scan 内 Deep-3 finalize → 可进入 Deep-4A
P18 无 qualified judge 时 **绝不** publication_authority=true
P19 multi-unit：1 evidence N units 全部保留
P20 multi-unit：N evidence 各自 units 不互相覆盖
P21 no DB migration / no queue table
P22 production judge 仍为 NONE（不得被配置注入）
```

---

# 18. Mutation validation

```text
移除 PUBLICATION discovery
→ P14 / P17 FAIL

让 audited 可被重写
→ P2 / P15 / P16 FAIL

用 evidence_id map 覆盖 unit
→ P19 / P20 FAIL

无 judge 时仍设 publication_authority=true
→ P18 FAIL

把 ResearchState 复制进 parent
→ P9 FAIL
```

“测试绿”本身不够。

---

# 19. Deep-4A review gates

```text
G4A-1  only valid completed Deep terminal is consumed
G4A-2  first terminal wins for deep_publication
G4A-3  child lineage + terminal digest revalidated
G4A-4  ResearchState reloaded via claim_engine_load, not copied
G4A-5  unit-safe evidence projection (no silent unit loss)
G4A-6  existing projection / synthesis / auditor reused
G4A-7  no qualified judge → audited-but-not-approved
G4A-8  publication_authority always false
G4A-9  bounded control-plane artifact only
G4A-10 assistant / pedagogy / learning / standard artifacts immutable
G4A-11 ResearchMemory untouched
G4A-12 PUBLICATION durable discovery + crash recovery
G4A-13 same runner, no second worker / no queue table
G4A-14 no DB migration
G4A-15 focused tests pass
G4A-16 mutation checks pass
G4A-17 ruff pass
G4A-18 expanded mypy pass
G4A-19 mypy baseline pass
G4A-20 git diff --check pass
G4A-21 file-boundary audit pass
G4A-22 exact-head ordinary CI pass
```

---

# 20. Local candidate gate

```text
focused Deep-4A
synthesis assembler / auditor adjacent
Deep-1/2/3/3T regressions
trigger regressions
chat/api regressions
ruff
expanded mypy
mypy baseline
git diff --check
scope audit
```

继续沿用：

> mypy baseline 必进 candidate gate。

> branch-critical tests 必须做 mutation validation。

---

# 21. CI / L3 discipline

Deep-4A 不触发 formal L3。

```text
ordinary exact-head CI
```

是 merge gate。

Deep phase 最终 formal L3 仍留给 **Deep-4B / publication cutover**（即整个 Deep phase
的最终 candidate）。

---

# 22. Deep-4A CLOSED 定义

```text
一个 Deep-3 completed child
可以被可靠地推进为
durable、可恢复、fail-closed 的
audited-but-not-approved publication candidate
```

且：

```text
不改用户答案
不发布
不碰 pedagogy / learning / memory
```

**Deep-4A CLOSED ≠ Deep automatic answer publication CLOSED。**

---

# 23. Deep-4B 入口

只有：

```text
Deep-4A CLOSED
+ qualified semantic judge 存在并成为 server-owned authority
```

之后才能审计 publication cutover。

当前：

```text
Deep-4B = NO-GO
```

---

# 24. 一句话模型

> **Deep-4A 把 Deep 已经做完的研究，投影成一份可审计、可恢复、但明确不拥有发布权的候选答案
> artifact；它修好 synthesis 的 multi-unit 覆盖缺陷，复用既有 projection / synthesis /
> auditor，并且在 qualified semantic judge 出现之前，永远停在 audited-but-not-approved。**
