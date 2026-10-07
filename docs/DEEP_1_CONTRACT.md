# Deep Phase Frozen Architecture + Deep-1 Implementation Contract

**状态：FROZEN — implementation authority**

```text
Standard authority 基线
  Standard CLOSED at   c48a1ac313e59ab0104364db519340f1460e84dc
  formal L3            run 37514856913 / 3866 passed, 6 skipped

Deep implementation base
  = c48a1ac3 的纯 docs-only descendant

永久不变
  Standard L3 authority SHA = c48a1ac3
  不得声称新的 docs-only SHA 自己跑过 L3
```

---

## 0. Deep 的核心定义

Deep **不是** Standard + 更多 query + 更多 read + 更长 timeout。

Deep 是：

```text
Standard terminal artifact
    → server-owned Deep handoff
    → 现有 Claim Engine active runtime
    → claim planning
    → gap-aware multi-wave research
    → Evidence Gain
    → per-gap / per-claim saturation
    → Evidence Gate
    → durable ResearchBrief / Deep artifact
```

**Deep 不重新实现深度研究引擎。** 现有执行 authority：

```text
src/application/active_research_runtime.py     ActiveResearchRuntimeExecutor
src/web/research/evidence_gain.py
src/web/research/gap_planner.py
src/web/research/stop_gate.py
src/web/research/runtime.py
src/web/research/contracts.py
src/application/research_web_lookup_dispatch.py  ClaimEngineDispatchWebLookupService
```

这些已拥有 Deep 核心算法。**禁止再写第二套**：`DeepEvidenceGain` / `DeepSaturation` / `DeepGapPlanner` / `DeepResearchLoop` / `DeepStopGate`。

---

## 1. Deep Phase 分层

```text
Deep-1  Standard → Deep handoff + durable evidence seed + deterministic child identity
        + production inert
Deep-2  激活现有 ActiveResearchRuntimeExecutor + seed reuse + Deep budget
        + interruption / resume
Deep-3  自动 Standard → Deep continuation + durable Deep terminal artifact
        + fail-safe integration
Deep-4  ResearchBrief / synthesis projection + final integration / production cutover
        + Deep phase final L3
```

后续 slice 不得重新定义前一层 authority。

---

## 2. Deep 执行引擎 Authority Matrix

| Concern | Authority |
| --- | --- |
| Standard 是否结束 | `standard_continuation.result` |
| Standard unresolved fields | `result.unresolved_gaps` |
| Standard source bytes | Standard child durable journal |
| Deep 是否允许启动 | Deep admission |
| Deep claim decomposition | existing `RuntimeClaimPlanner` |
| Deep query construction | existing `gap_planner.py` |
| candidate assessment | existing active runtime |
| Evidence eligibility | existing `Evidence Gate` |
| Evidence Gain / saturation | existing `evidence_gain.py` |
| wave ceiling | `MAX_RESEARCH_WAVES = 8` |
| stop reason | existing `ResearchStopGate` |
| durable resume cursor | `ResearchRuntimeCursor` |
| external/model attempt fencing | existing runtime markers |
| Deep persistence | `WebLookupRepository` |
| publication authority | **NOT Deep** |
| assistant answer | existing ChatService；Deep-1/2/3 不得修改 |

```text
模型决定：claim decomposition / candidate semantic assessment / evidence extraction
程序决定：source identity / budget / eligibility / gain / saturation / stop / resume
         / publication authority
```

---

## 3. Standard → Deep 升级条件

Deep 只能消费**已 terminal 且完整验证的 Standard artifact**。允许升级必须**同时**满足：

```text
parent ChatTurn.status == completed
lookup_terminal.state == ESCALATE_STANDARD
lookup_terminal.dispatch_status == completed
standard_continuation.schema_version == standard-auto-continuation-v1
standard_continuation.publication_authority == false
Standard child identity / thread / source lineage 全部重新验证
Standard result.unresolved_gaps 非空
```

且 Standard stop 必须属于正常研究终态：

```text
ready_for_binding / plan_exhausted / budget_exhausted / deadline
/ conflict_requires_binding
```

含义：Standard 正常做完了，但证据仍不足，需要更深研究。

---

## 4. 明确不得升级的 Standard 结果

```text
cancelled / planner_invalid / planner_failed / result_unknown
integrity failure / owner mismatch / source mismatch / handoff mismatch
blocked continuation
```

行为：**0 Deep child、0 model call、0 search、0 read**。

Deep 不负责把 Standard 的执行故障包装成一次新研究机会。

---

## 5. Deep terminal 独立于 Standard terminal

绝不重新打开 `lookup_terminal` / `standard_continuation`。新增独立 namespace：

```python
deep_terminal = {
    "schema_version": "standard-deep-terminal-v1",
    "state": "ESCALATE_DEEP",
    "reason": "unresolved_after_standard",
    "dispatch_status": "pending",
    "owner": {...},
    "handoff": {...},
}
```

Standard 一旦 CLOSED：**永不再改写其 artifact**。Deep 是下游消费者。

---

## 6. Deep parent state machine

```text
absent
  ├─ Standard resolved            → not_requested
  ├─ Standard execution failure   → not_requested / blocked
  └─ valid unresolved Standard    → pending

pending
  ├─ Deep child terminal                 → completed
  ├─ deterministic integrity failure     → blocked
  └─ execution owner busy                → remains pending
```

同 Standard：**禁止 parent `pending → running`**。运行状态属于 Deep child / operation lease，不属于 parent terminal。

---

## 7. Deep handoff schema

```python
{
    "schema_version": "standard-deep-handoff-v1",
    "reason": "unresolved_after_standard",
    "query": <parent.user_message>,
    "parent_turn_id": ...,
    "standard_child_run_id": ...,
    "standard_source_run_id": ...,
    "standard_handoff_sha256": ...,
    "standard_result_sha256": ...,
    "unresolved_fields": [...],
    "gap_states": {...},
    "conflicts": [...],
    "known_assertion_refs": [...],
    "seed_source_refs": [{"url": ..., "content_sha256": ..., "fields": [...], "origin": ...}],
    "budget_profile": "deep-v1",
    "publication_authority": False,
    "payload_sha256": ...,
}
```

`payload_sha256` 必须覆盖除自身外的整个 canonical payload。

---

## 8. Handoff 中禁止保存 raw body

`chat_turn.rag_snapshot` 只能保存 URL / digest / field association / lineage / result state，**不得复制正文**。

Raw body 只能从 **Standard child durable journal** 读取。

```text
parent artifact = authority/control plane
child journal   = data plane
```

不得混成第二个 evidence store。

---

## 9. Standard evidence reuse 是硬合同

Deep 不允许“Standard 已读过该 URL，Deep 再 HTTP read 一次”。Deep-1 必须建立 durable seed。

来源仅限 Standard journal 中：

```text
observation.kind == read
observation.readable == true
entry.state == completed
body 非空
sha256(body) == observation.content_sha256
```

任一不满足 → **不得作为 Deep seed**。

若 handoff 声称的 seed source 与 durable journal 不一致 → **Deep admission BLOCKED，0 network**（不是静默丢弃后继续）。

---

## 10. Deep seed data plane

Raw seed 只放 Deep child `research_context`：

```python
deep_seed = {
    "schema_version": "deep-seed-v1",
    "standard_child_run_id": ...,
    "sources": [
        {"url": ..., "content_sha256": ..., "content": ..., "fields": [...], "origin": ...}
    ],
}
```

这些只是 **already-read source bytes**，**不是** support / claim evidence / primary source / independent cluster / publication authority。后续仍必须经过 candidate assessment → extraction → Evidence Gate 才能形成 Deep evidence。

---

## 11. Deep-1 不执行研究

Deep-1 完成后：

```text
Deep handoff durable ✅   Deep child durable ✅   Standard evidence seed durable ✅
0 search   0 read   0 model call   0 Evidence Gate   0 synthesis
```

Deep child 只是待执行。

---

## 12. Deep child identity

```text
request_id = "deep-handoff:" + parent_turn_id + ":" + standard_child_run_id
child id   = "deep-" + sha256(request_id)[:24]
```

continue / retry / process restart 必须得到**同一个 child**，不得生成第二个 Deep run。

---

## 13. Deep lineage

```text
Deep child.query            = parent.user_message
Deep child.owner_thread_id  = parent.thread_id
Deep child.parent_run_id    = standard_child_run_id
```

```text
Lookup source run → Standard child → Deep child
```

Deep 不允许直接跳回 Lookup run 当 parent。

---

## 14. Deep v1 Budget — phase-level frozen target

Deep-1 本身不消费预算；Deep-2 必须使用：

```python
DEEP_V1_BUDGET = ResearchBudget(
    max_candidates=40,
    max_reads=12,
    soft_timeout_seconds=120,
    hard_timeout_seconds=180,
    max_total_chars=80_000,
)
```

Standard 已读过的 seed **不计入 Deep `reads_used`**（未发生新的物理读取）。

---

## 15. Deep clock

Deep 是独立 tier：`Lookup 30s / Standard 60s / Deep 180s`。

**不是** `Deep deadline = parent.created_at + 270s`。Deep clock 从 **Deep execution admission** 开始。

理由：Standard 能正常结束但留下 gap，本身就是进入下一 tier 的资格事实；不能因 Lookup/Standard 已合法花掉各自预算，就让 Deep 一启动立即过期。

---

## 16. Deep v1 不扩大模型调用 authority

**Deep v1 不修改** `PHASE_RESEARCH_MODEL_CALL_BUDGET` / `MAX_RESEARCH_MODEL_ATTEMPTS` / `ResearchModelGateway` retry contract。

若以后发现 Deep 总是先耗尽 model budget 远早于 read/time budget，再开独立 calibration slice。不得为“看起来更深”直接扩大模型调用上限。

---

## 17. Evidence Gain authority

完全复用 `src/web/research/evidence_gain.py`。六种 substantive gain 不变：

```text
new_eligible_evidence / new_independent_cluster / better_source_role
new_contradiction / new_provenance_lead / claim_status_improvement
```

永远不算 gain：只是多了 URL / 只是多了 search result / `result_count` 增长 / 同 cluster 重复证据 / 重复读同一来源。

Deep 不新增 `LLM says "this was useful"` 这种 gain authority。

---

## 18. Saturation authority

```text
普通 claim/gap：连续 2 个 query batch 无 substantive gain → saturated
critical / conflict：允许额外 1 batch → 最多 3 个连续 no-gain batch
```

仍受 `MAX_RESEARCH_WAVES = 8` 约束。

不得创建全局 `no_gain_counter` 代替 per-claim/per-gap counters。

---

## 19. Stop authority

完全复用 `ResearchStopGate`，优先级不改：

```text
1 unavailable
2 Evidence Gate PASS
3 hard budget exhausted
4 no actionable gaps
5 all actionable saturated
6 wave ceiling
7 continue
```

尤其：**wave limit reached ≠ saturation**，不得伪装成 `evidence_saturated`。

---

## 20. interruption / resume

完全复用 `ResearchRuntimeCursor` / `inflight_model_call` / `inflight_external_call` / `gain_history` / `wave_index` / `no_gain_batches_by_claim` / `no_gain_batches_by_gap`，以及 `recover_interrupted_model_attempt()` / `recover_interrupted_external_attempt()`。

Deep 禁止再写 `DeepResumeState` / `DeepCheckpoint` / `DeepRetryLedger`。

---

## 21. Publication boundary

Deep-1 / Deep-2 / Deep-3：`publication_authority = False` **恒成立**。

Evidence Gate PASS **不等于**“可以发布给用户作为最终权威答案”。Evidence authority 与 publication authority 仍分离。

当前自动语义 judge 没有 qualified authority，因此 Deep phase **不得**偷偷通过一个新 LLM reviewer 绕开既有 release gate。

---

## 22. assistant / learning boundary

Deep-1 / Deep-2 / Deep-3 不得修改 `parent.aassistant_message`、重新调用 answer model、重跑 pedagogy、修改 `learning_state`、增加 `answer_generation_calls`。

用户已经得到的安全答案**不能因为 Deep 失败而变成 500**。

---

## 23. Deep-1 OWNS

```text
Standard final artifact validation
Deep eligibility decision
Deep handoff construction + digest
Deep terminal persistence
deterministic Deep child creation
Standard durable source → Deep seed projection
exactly-once retry
```

---

## 24. Deep-1 DOES NOT OWN

```text
active runtime execution / claim planning / search / read / candidate assessment
evidence extraction / Evidence Gain / saturation / Evidence Gate / ResearchBrief
Synthesis / Final Answer Auditor / automatic Standard→Deep execution
runtime_repository activation / ChatService / UI / publication
```

---

## 25. Deep-1 新模块

```text
NEW src/web/research/deep_handoff.py        decide_deep_handoff(...) / load_deep_handoff(...)
                                            纯函数，无 DB / network
NEW src/web/research/deep_seed.py           project_standard_seed(...)
                                            输入 validated Standard child ledger
                                            输出 DeepSeedSource[]（URL / body / digest / field provenance）
NEW src/repositories/deep_handoff_repository.py
                                            atomic parent terminal write / deterministic child create
                                            / idempotent lookup
NEW src/application/deep_handoff.py         DeepHandoffService.prepare(...)
                                            只做 validate → decide → seed → persist
                                            绝不调用 gateway / model
```

---

## 26. Deep-1 result

```python
@dataclass(frozen=True)
class DeepHandoffOutcome:
    status: Literal["not_requested", "prepared", "blocked"]
    parent_turn_id: str
    child_run_id: str
    reason: str
    handoff_sha256: str
```

没有 `running` / `researching` / `completed` —— Deep-1 根本不执行研究。

---

## 27. Deep-1 transaction

创建 handoff + child 必须以 server persistence 为 authority。禁止 caller 传入 `unresolved_fields` / Standard child id / source digests / budget / query。

调用方只允许：

```python
prepare(parent_turn_id=..., thread_id=...)
```

所有其他事实重新从 DB 加载。

---

## 28. Parent mutation boundary

Deep-1 只能新增 `rag_snapshot.deep_terminal`。必须逐 bit 保持 `lookup_terminal` / `standard_continuation` / `aassistant_message` / `route_snapshot` / `pedagogy_snapshot` 不变。

---

## 29. Deep-1 Negative Controls

```text
D1  Standard 全部 resolved → no Deep
D2  Standard cancelled → no Deep
D3  planner_failed → no Deep
D4  result_unknown → no Deep
D5  Standard continuation blocked → no Deep
D6  handoff digest tampered → blocked / 0 network
D7  Standard child identity mismatch → blocked
D8  source run lineage mismatch → blocked
D9  source body hash mismatch → blocked
D10 wrong thread → blocked
D11 duplicate prepare → same Deep child
D12 duplicate prepare → no duplicate seed
D13 parent raw rag_snapshot 不含 body
D14 seed body 只来自 durable Standard journal
D15 publication_authority false
D16 Standard artifacts bit-for-bit unchanged
D17 aassistant_message unchanged
D18 0 gateway calls
D19 0 model calls
D20 no claim_engine active state attached
D21 Deep child parent_run_id == Standard child run id
D22 Deep child query == original parent user_message
```

---

## 30. Deep-1 Allowed Files

```text
NEW  src/web/research/deep_handoff.py
NEW  src/web/research/deep_seed.py
NEW  src/application/deep_handoff.py
NEW  src/repositories/deep_handoff_repository.py
NEW  tests/test_deep_handoff.py
NEW  tests/test_deep_seed.py
NEW  tests/test_deep_handoff_service.py
OPTIONAL  docs/DEEP_1_CONTRACT.md
OPTIONAL  docs/PROJECT_STATUS.md
```

---

## 31. Deep-1 Forbidden Files

```text
src/application/standard_*.py
src/repositories/standard_*.py
src/web/research/standard_*.py
src/application/active_research_runtime.py
src/application/research_web_lookup_dispatch.py
src/web/research/evidence_gain.py
src/web/research/gap_planner.py
src/web/research/stop_gate.py
src/web/research/runtime.py
src/web/research/contracts.py
src/web/research/phase_budget.py
src/application/chat_service.py
src/application/runtime_repository.py
official_publication.py / synthesis_assembler.py / final_answer_auditor.py
DB migrations / frontend
```

若 Deep-1 发现必须碰这些：**STOP → 合同假设错误 → 回来调整**。

---

## 32. Deep-1 本地验收

```bash
python -m pytest -q tests/test_deep_handoff.py tests/test_deep_seed.py tests/test_deep_handoff_service.py

python -m pytest -q tests/test_deep_handoff.py tests/test_deep_seed.py \
  tests/test_deep_handoff_service.py tests/test_standard_continuation.py \
  tests/test_standard_execution.py tests/test_web_lookup_run.py

python -m ruff check src/web/research/deep_handoff.py src/web/research/deep_seed.py \
  src/application/deep_handoff.py src/repositories/deep_handoff_repository.py tests/test_deep_*.py

git diff --check
```

本地不主动跑 full pytest。

---

## 33. CI 说明

`ci_scope.py` 尚无 Deep category。Deep-1 **不允许**为了赶快而伪装成 standard、把 Deep 文件塞进 `standard_research_loop`、或把整个 research-backend 映射到一个窄 impact set。

若 PR CI 因未知 Deep 路径 fallback 到 full pytest：**接受一次安全 fallback**。之后单独冻结 Deep CI routing，再让后续 Deep slice 使用 named impact set。

不能为了省 6 分钟降低 scope correctness。

---

## 34. Deep-1 Review Gate

```text
G1  Standard terminal 是唯一入口
G2  no failure→Deep laundering
G3  Deep terminal 与 Standard terminal 分离
G4  child deterministic
G5  lineage Standard child → Deep child
G6  seed 来自 durable journal
G7  seed digest rehash
G8  no body in parent
G9  no publication authority
G10 no Standard mutation
G11 no assistant mutation
G12 0 network
G13 0 model
G14 exactly-once
G15 forbidden files untouched
```

全部通过 ⇒ `Deep-1 = MERGE-READY`。

---

## 35. Deep-2 已冻结边界

Deep-2 才允许：attach empty active `ResearchState`（`mode = active`）、apply `DEEP_V1_BUDGET`、ingest Deep seed as already-read candidates、invoke existing `ClaimEngineDispatchWebLookupService` → `ActiveResearchRuntimeExecutor`。

核心负控：**Standard seed URL 不得再次 network read**。seed 可以 assessment / extraction / Evidence Gate，但不能重新 fetch。

若现有 active runtime 缺少 “already-read seed ingestion seam”，Deep-2 可以增加**最小 ingestion seam**；不得重写 runtime。

---

## 36. Deep-3 已冻结边界

Deep-3 才做：automatic pending Deep continuation；lease busy → deferred；crash → same child resume；terminal → parent `deep_terminal` completed；Deep failure → 已完成的用户答案仍安全。

同 Standard：parent 不使用 `running`。

---

## 37. Deep-4 已冻结边界

Deep-4 才允许接 `ResearchBriefProjection` / `SynthesisAssembler` / `FinalAnswerAuditor` / Persistent Research Memory。

原则：reuse existing components，不复制实现。但在 qualified publication authority 没建立以前：

```text
Deep synthesis = auditable draft/artifact
publication_authority = false
Deep phase CLOSED ≠ Release GO
```

---

## 38. Stop Conditions

OpenCode Deep-1 遇到以下任一情况立即停止：需要改 Standard / 需要改 active runtime / 需要真正联网 / 需要模型调用 / 需要新 DB table / 需要改 Evidence Gain / 需要改 saturation / 需要改 Stop Gate / 需要改 budget constants / 需要改 ChatService / 需要改 runtime factory / 需要赋予 publication authority / 需要进入 synthesis。

---

## 39. Commit Discipline

```text
完整 Deep-1 bounded slice → focused → adjacent impact → ruff/diff
→ 一次 commit → 一次 push → exact-head CI → semantic review
```

不做：一个测试一个 commit / 一个负控一次 push / 等一次 CI 再改两行。

---

## 40. Deep 的一句话目标

不是“给模型更多时间上网”，而是：

> **当 Standard 已经诚实地告诉系统“这里仍有未解决的证据缺口”之后，复用已有证据，通过持久化的多波次 gap research，只在真正产生 Evidence Gain 时继续，在无增益时机械饱和停止，并且任何中断都能从 durable state 精确恢复。**

路线修正：Evidence Gain / saturation / interruption-resume **已在仓库中实现**。Deep 的工作量因此从“造研究引擎”收缩成“**把 Standard 的成果可信地送进已有研究引擎**”。


---

# Deep-1 Retry & Integrity Addendum

**状态：FROZEN**

本节补充 Deep-1 §7 / §9 / §12 / §27 / §29 / §34。若与较宽泛表述冲突，**以本节为准**。

## A. Durable terminal 是 retry 的第一 authority

prepare(parent_turn_id, thread_id) 首先读取
rag_snapshot.deep_terminal。

`	ext
不存在 → fresh admission path
已存在 → retry path
`

不得重新执行 fresh admission 决策后覆盖已有 terminal。

## B. Existing terminal 分流规则

### B1. dispatch_status == blocked

这是**完整终态**。必须：

`	ext
return blocked
child_run_id   = existing.child_run_id or ""
reason         = existing.reason
handoff_sha256 = existing.handoff.payload_sha256 or ""
`

不得：重新构造 handoff / 重新 project seed / 重新验证 Standard eligibility /
重新创建 child / 改变 reason / 把 blocked 改成 pending 或 prepared。

blocked terminal 可以合法拥有 handoff = {} 与缺失的 child_run_id，因此
**blocked terminal 不要求 load_deep_handoff() 成功**。

> **first blocked terminal wins.**

### B2. dispatch_status == pending

这是 prepared Deep child 的 durable authority。retry 必须重新验证：

`	ext
terminal schema / state == ESCALATE_DEEP / owner
handoff schema / payload_sha256 / publication_authority == false
child exists / child id == terminal.child_run_id / child owner
child parent lineage / child query
child deep seed exists
handoff.seed_source_refs == child.deep.seed.refs
`

全部成立 → prepared；任一失败 → locked（bounded integrity reason）。
**不得重新创建第二个 child。**

### B3. 其他 dispatch_status

Deep-1 合法 durable vocabulary 仅 pending / locked。其他值 →
locked("handoff_integrity_failure")，不得猜测。

## C. Retry outcome stability

对未被篡改的 durable terminal，重复调用 prepare() 必须保持
status / parent_turn_id / child_run_id /
eason / handoff_sha256 稳定。

`	ext
successful first prepare: handoff_sha256 = H
successful retry:         handoff_sha256 = H
`

不得因 load_deep_handoff() 返回去掉 digest 的 projection 而变成空串。
权威 hash 从 existing["handoff"]["payload_sha256"] 读取。

## D. Deep handoff payload integrity

load_deep_handoff() 验证的是 deep_terminal.handoff，**不是** Standard continuation 的旧 handoff。
必须验证 schema_version /
eason / publication_authority / payload_sha256。
任何 payload 字段被修改但 digest 未同步 → blocked。

## E. 两种 integrity 分开命名

`	ext
D6-S  upstream Standard handoff integrity
        standard_continuation.handoff_sha256 == standard child ledger.handoff_sha256
D6-D  durable Deep handoff integrity
        deep_terminal.handoff.payload_sha256 == canonical_digest(deep_terminal.handoff)
`

两者都是必要条件，但不是同一件事，不得用同一个测试混在一起。

## F. Seed ref canonical equality

authority shape 固定为 {url, content_sha256, fields, origin}。
seed_refs_match() 必须比较全部四个语义字段：

`	ext
(canonical_url, content_sha256, sorted(unique(fields)), origin)
`

不得只比较 (url, digest)。URL / digest / fields 增删替换 / origin 任一变化均为 mismatch。
字段顺序不是语义差异（["a","b"] == ["b","a"]）；重复 field 不产生新 authority
（["a","a"] == ["a"]）。

## G. Seed data-plane integrity

对每个
eadable == true 的 Standard read observation，必须存在 matching read entry、
entry.state == completed、body 非空、sha256(body) == observation.content_sha256。

`	ext
missing / non-completed entry / unreadable observation / non-read observation / empty body
    → not seed-eligible → skip

body exists AND recorded digest exists AND sha256(body) != recorded digest
    → durable authority 自相矛盾 → SeedIntegrityError → blocked → no Deep child creation
`

不得降级为普通 skip。

## H. Fresh path ordering

`	ext
1 load parent
2 verify completed parent
3 verify completed Standard terminal
4 verify Standard continuation schema / authority
5 classify Standard stop reason
6 load Standard child
7 load Standard child ledger
8 revalidate full lineage
9 project + verify seed
10 build Deep handoff
11 deterministic child identity
12 create/reuse child
13 persist parent deep_terminal
14 return prepared
`

关键约束：**任何 integrity failure in steps 1–9 → 0 Deep child**。

## I. Child-created / terminal-not-yet-written crash window

允许 create_child SUCCESS → crash → deep_terminal 尚未写入。恢复时必须靠
deterministic child id + create_request_id 复用同一个 child：

`	ext
retry → fresh path revalidation → create_child returns same child → persist deep_terminal
`

不得生成 orphan sibling。这属于 recoverable crash window，**不要求新跨表事务或 DB migration**。

## J. Parent terminal persistence rule

DeepHandoffRepository.persist()：existing valid deep_terminal → **first terminal wins**，不得覆盖。
fresh write 只能新增
rag_snapshot.deep_terminal；其余 parent 内容语义及值不变
（lookup_terminal / standard_continuation / assistant_message /
route_snapshot / pedagogy_snapshot）。

## K. Retry negative controls

`	ext
R1 pending Deep handoff payload 被改、digest 未改        → retry blocked
R2 seed ref URL 改变 + handoff digest 重算              → retry blocked
R3 seed ref digest 改变 + handoff digest 重算           → retry blocked
R4 seed ref fields 改变 + handoff digest 重算           → retry blocked
R5 seed ref origin 改变 + handoff digest 重算           → retry blocked
R6 blocked terminal retry → 仍 blocked / reason bit-stable / 不要求 valid handoff
R7 prepared terminal retry → same child_run_id / same handoff_sha256 / no new child
R8 crash after child creation before parent terminal → retry reuses same child
     → exactly one Deep descendant
R9 unknown dispatch_status → blocked / no new child
`

## L. Exactly-once 的精确定义

> **无论 caller retry、进程崩溃还是重复请求，最终 durable graph 中至多存在一个 Deep child，
> parent terminal 的第一合法终态不被重写，并且相同 durable truth 返回相同的 outcome identity。**

`	ext
one request_id / one deterministic child id / at most one Deep child
one parent deep_terminal / first terminal wins
stable blocked reason / stable prepared child id / stable handoff hash
`

## M. Deep-1 merge gate 增补

`	ext
G14a deterministic child identity
G14b create_request_id idempotency
G14c pending retry revalidates handoff + seed
G14d blocked retry preserves first terminal
G14e retry preserves child_run_id
G14f retry preserves handoff_sha256
G14g crash window cannot create sibling child
`

全部通过才算 G14 PASS。
