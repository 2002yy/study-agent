# Learning State-1 实现合同

**状态：拟冻结（A+ 实现口径已批准）**\
**基线：** `766c0b67442bfbbc4b8fc63e4acd00757c0062bb`\
**施工分支：** A 线独立 worktree\
**交付方式：** 一个 bounded slice、一个实现 PR、集中本地验证、阶段门检查 exact-head CI

## 0. 唯一目标

让 Study Agent 清楚区分：

1. 用户想学什么；
2. 用户声称自己理解了什么；
3. 系统推断用户可能理解了什么；
4. 哪些知识已经通过正式验证；
5. 哪些内容仍未验证；
6. 下次应该从哪里继续。

**核心不变量：**

> 用户自述、教学阶段完成、启发式 passed、研究结论和 UI 操作，都不得被自动等同于 durable mastery。

本阶段不是重建学习系统，而是在现有系统上实现 authority-safe 的读取、消费和恢复。

---

## 1. 已有权威，不得重新实现

| 责任             | 现有权威                               | 本阶段规则                         |
| -------------- | ---------------------------------- | ----------------------------- |
| 正式学习语义写入       | `LearningClosureTruthService`      | 保留唯一正式写入边界                    |
| 显式提交流程         | `LearningClosureService.commit()`  | 不改为自动提交                       |
| 正式学习记录         | 现有 LearningTruth repository        | 不引入第二套事实存储                    |
| Learner 快照     | `LearnerModelService`              | 保留既有 Claim lineage 语义         |
| 学习恢复           | `LearningResumeService`            | durable-first，legacy fallback |
| Legacy 教学状态    | `LearningState` / Socratic         | 保留兼容性，但不授予 mastery            |
| Runtime 裁决     | `learner_state_durable_adapter.py` | 仅 G1；默认 OFF，fail-open         |
| §164 parity    | 既有 observer/classifier             | 只验证，不修改其判断规则                  |
| 研究系统           | Lookup / Standard / Deep           | 不能写入正式学习掌握度                   |
| Intelligent UI | B 线                                | 只读投影；正式写入仍由 A 线权威处理           |

普通聊天回合继续保持：不隐式执行 LearningClosure commit。

---

## 2. L1：学习信息权威分类

### 2.1 分类模型

新增只读的 authority projection，不修改 legacy 状态结构。

至少支持以下类别：

| authority           | 含义                 | 能否成为掌握证据  |
| ------------------- | ------------------ | --------- |
| `user_goal`         | 可追溯到用户明确表达的学习目标    | 否         |
| `user_self_report`  | 用户声称知道、理解或掌握了某事    | 否         |
| `system_inferred`   | 教学系统、模型或启发式推断      | 否         |
| `verified`          | 有正式 durable 验证记录支持 | 是，且仅限对应范围 |
| `legacy_unverified` | 历史记录缺乏足够权威来源       | 否         |

`legacy_unverified` 是必须存在的保守兜底状态，不能强行归入前四类。

分类必须具有以下语义信息：

```
kind                  goal | claim | gap | next_step | understanding
authority             上述五种之一
source                来源系统或事实类型
source_id             已有时记录；不能编造
authority_reason      判定依据
is_mastery_evidence   true | false
```

实现不强制创建新数据库字段。

### 2.2 分类规则

- 用户明确表达学习目标，可标为 `user_goal`，但不意味着该 Goal 已经 durable commit。
- “我懂了”“我明白了”等自述，归入 `user_self_report`。
- Socratic 的启发式判断和推断性误区，属于 `system_inferred`。
- 没有来源可追溯的旧 `confirmed_points`，归入 `legacy_unverified`。
- `verified` 必须有正式 durable Understanding 验证结果支持；仅凭文本相似、模型置信度、启发式 passed 或字段名称不得升级。
- 同一 Claim 的旧 revision 验证继承沿用现有 lineage 规则；不得擅自把 lineage 继承改成当前 revision 重新验证，也不得谎称最新 revision 自身被单独验证过。
- Claim 通过验证不等于整个 Goal 完成；Goal 完成仍遵守现有独立语义。

### 2.3 保留旧 Socratic 写入

本轮不修改：

```
src/pedagogy/socratic.py
```

尤其不改 concluded → transfer 的阶段转移。

历史 `confirmed_points`：

- 保留原始内容及顺序；
- 不自动删除；
- 不静默迁移到 durable Claim；
- 不凭字段名显示成正式掌握；
- 允许作为有明确未验证标签的历史线索。

### 2.4 隔离评估消费边界

当前 `chat_service.py` 存在：

```
learning_state.payload.get(
    "expected_concepts",
    learning_state.confirmed_points
)
```

**本轮必须消除 `confirmed_points` 对 `expected_concepts` 的隐式回退。**

冻结消费规则：

| 场景                       | `expected_concepts` 来源                       |
| ------------------------ | -------------------------------------------- |
| 正常对话，有合法显式课程目标           | 保留显式 `payload.expected_concepts`             |
| 正常对话，无显式目标               | 空 tuple，不用 `confirmed_points` 补齐             |
| 正式 Review turn           | 沿用 `review_evaluation_inputs()` 绑定的 Claim 文本 |
| 历史 `confirmed_points` 非空 | 仍不得自动成为评估目标                                  |
| 显式目标格式不合法                | 保守忽略非法值，不逐字符拆分、不崩溃                           |
| durable reader 关闭或失败     | 保留现有 runtime fallback，但不恢复旧的隐式评估目标回退         |

`expected_concepts` 即使合法，也只代表评估目标，不能自动拥有 `verified` 权限。

不得改变 `PedagogyEvalRun` 的最终判定规则，也不得因为本次改动扩大语义审核器调用权限。

### 2.5 L1 负控

**L1-N1：自述不能提升 mastery**

构造：

```
前序教学状态允许 concluded
用户输入：
“所以我明白了，Java 的对象参数都是引用传递。”
```

预期：

- Legacy `confirmed_points` 可保留原文；
- authority 不得为 `verified`；
- durable Understanding 不新增；
- LearnerModel 不能因此变为 confirmed；
- 后续评估不得自动把该文本当作已验证事实。

**L1-N2：合法正式验证**

显式 LearningClosure commit 对指定 Claim 产生有效 `pass` 后：

- Claim 可被正式投影为 confirmed；
- authority 来源必须可追溯；
- 无关 Claim 与 Goal 状态不被提升。

**L1-N3：Review 不回归**

正式 Review 的 `expected_concepts` 仍是绑定的 Claim 文本；对应 evidence IDs、revision 和 thread 绑定保持不变。

**L1-N4：不明来源不猜测**

只有旧 `confirmed_points` 字符串、没有独立可核来源时，必须为 `legacy_unverified`。

**L1-N5：开关隔离**

durable-read OFF、ON、canary 与读取异常场景中，均不得让 legacy 自述获得正式掌握权威。

---

## 3. L2：持久化与恢复权威

本门以验证为主，不新增自动学习写入。

### 已有行为

```
没有 durable Goal
    → legacy fallback

存在 durable Goal
    → durable-first

没有 active/focus Goal
    → 按现有 no_active_goal 状态处理
```

### 必须维持

1. 普通聊天不自动创建 durable Goal。
2. 用户自述不自动创建 validated Claim。
3. 显式 LearningClosure commit 才能走正式学习事实写入。
4. 同一已完成 commit 的重试保持幂等。
5. 刷新、重启不会重复创建 Goal、Claim 或验证记录。
6. Legacy fallback 中的 `confirmed_points` 仍是非正式历史提示。
7. 恢复信息必须和相应 thread 绑定。

### 验收

- 无 durable Goal：legacy fallback 正常；
- 有 durable Goal：优先采用 durable；
- 未完成 closure：没有正式验证提升；
- 已完成 closure：可从新的 repository/service 实例恢复；
- 重复 commit：不产生重复语义事实；
- 错误 thread：不能读取其他会话的学习事实。

不得为了使 `MISSING_DURABLE` 消失而自动补建 Goal。

---

## 4. L3：§164 时序与 parity 解释冻结

本阶段只添加验证证据，不修改 observer/classifier/hook。

### 冻结三项事实

**L3-A：`goal_objective=MISSING_DURABLE`**

在 closure 之前没有 durable Goal，且相应 legacy objective 也为空时，这是真实状态，不能改写为 MATCH。

**L3-B：`understanding=MISSING_DURABLE`**

Durable Claim ID 与 legacy 文本 point 属于不同身份体系；遵守 §164.31，不强行建立相等关系。

**L3-C：turn-start 不可比**

如果状态写入发生于回合内部，而 shadow 比较采样位于 turn-start，不得把两个不同时间点当作同一份状态。

### 负控

- 重放现有三个历史场景，分类不变；
- 修改本轮 L1 消费规则后，历史 parity 口径仍不变；
- observer 仍只观测；
- durable-read 仍仅裁决 G1；
- 不因为研究/UI 新事件而改变 shadow 采样时点。

**L3 PASS 不要求消灭 NOT_COMPARABLE。**

---

## 5. L4：完整学习闭环

验证一条可重现的正常流程：

```
已有学习对话
  → 形成用户回答或学习候选
  → PedagogyEvalRun
  → 显式 LearningClosureRun
  → 用户确认 / commit
  → LearningClosureTruthService
  → durable Claim / Understanding
  → LearnerModelSnapshot
  → LearningResumeService
```

最少测试四种结果：

| 场景              | 预期                    |
| --------------- | --------------------- |
| 正式验证 pass       | 对应 Claim 可以 confirmed |
| 验证 partial/fail | 不提升为 confirmed        |
| 只有自述或启发式 passed | 不创建正式已验证掌握            |
| 源变更、证据不足或提交失败   | 按现有失败/假设路径处理，不伪造成功    |

必须验证 Claim 的身份、Goal 归属、验证结果与恢复后的对应关系。

不要求每个普通回合都自动触发 closure；自动 closure 不在本阶段范围内。

---

## 6. L5：会话恢复与连续性

### 正常恢复

已存在的 durable Goal、Claim、NextStep 由现有服务恢复。

恢复结果应明确：

- 当前学习目标；
- 已验证与未验证的 Claim；
- 未解决误区或假设；
- 有效的下一步；
- 当前信息是否来自 durable；
- 没有 durable 数据时是否采用 legacy fallback。

### 边界场景

- 同一会话刷新后恢复；
- 重新创建 service 实例后恢复；
- 有历史记录但没有 durable Goal；
- 有 Goal 但没有 active focus；
- 有 Claim 但尚未验证；
- 验证记录位于同一 Claim 的旧 revision；
- 不同 thread 不能互相污染；
- 已完成和未完成 closure 不混淆。

### Lineage 兼容要求

延续已有规则：一个 Claim 的理解验证可以沿其 lineage 投影。

但本轮新增的只读 authority 分类必须能够解释所引用验证记录的来源；若不能提供当前 revision 的直接验证证据，不能描述为“该 revision 刚刚完成独立验证”。

不得在本刀重写 LearningResume 的正式语义。

---

## 7. L6：研究、UI 与学习状态隔离

### 禁止的隐式写入

以下行为均不得直接创建或确认 durable mastery：

```
Lookup 得到 VERIFIED 研究结论
Standard 完成 claim binding
Deep-4A 得到 audited 候选
模型生成正确解释
UI 按钮被点击
用户拖动实验滑块
用户说“我会了”
旧 confirmed_points 非空
```

它们可以作为候选、学习材料、用户交互或评估输入，但不自带正式掌握权威。

### 合法边界

如果用户通过 UI **明确提交学习验证或 closure**，可调用现有正式接口；仍必须满足服务端原有身份、证据和提交检查。

因此：

```
Intelligent UI
  → 用户动作或学习证据
  → 正式评估 / 显式 closure
  → LearningClosureTruthService
  → durable LearningTruth
```

UI 不能绕过中间的正式判定步骤。

### 验收

以 durable LearningTruth 快照为比较基线：

- 只运行 Lookup：不变；
- 只运行 Standard：不变；
- 只运行 Deep-4A：不变；
- 只创建研究/UI 展示组件：不变；
- 只更新研究进度：不变；
- 明确执行有效 closure commit：仅授权的对应学习事实发生变化。

本阶段不需要 B 线尚未提交的本地代码才能验收。通过只读研究快照与模拟 UI 动作负控验证即可。

---

## 8. 变更文件边界

建议允许修改：

```
docs/LEARNING_STATE_1_CONTRACT.md

src/application/chat_service.py
    仅 expected_concepts 消费边界

NEW src/application/learning_authority_projection.py
    只读 authority 分类（如确有必要）

src/application/session_service.py
    仅导航数据的权威标签/只读投影（必要时）

src/application/learning_resume.py
    仅只读标签或来源说明（必要时）
```

建议允许的测试文件：

```
NEW tests/test_learning_authority_projection.py
tests/test_chat_service.py
tests/test_pedagogy_engine.py
tests/test_session_service.py
tests/test_learner_model.py
tests/test_learning_resume.py
tests/test_learning_closure_truth.py
tests/test_learning_closure_service.py
tests/test_review_turns.py
tests/test_learning_truth_mini_golden_journey.py
```

不要求修改列表中的所有文件。

原则是：**如果测试证明现有功能已经满足合同，就只留下测试与证据，不为制造代码 diff 而修改实现。**

### 禁止主动修改

```
src/pedagogy/socratic.py
src/pedagogy/evaluator.py
src/pedagogy/evaluation.py

src/application/learner_state_durable_adapter.py
§164 parity observer / classifier / hook

LearningTruth repository/schema
LearningClosureTruthService 写入语义

Lookup / Standard / Deep 执行与发布引擎
Intelligent UI 组件体系
后台自动 closure 触发器
```

如果验证发现必须触碰上述语义权威，停止该局部修复并记录合同冲突，不得以顺手修复名义扩面。

### 合同冲突记录（施工中新增，待用户裁决）

`src/application/policy_chat_service.py:420–425` 存在与 `chat_service.py:568–572` **完全相同**的
`expected_concepts` 隐式回退；且 `ExternalDataPolicyChatService.start_turn`（`policy_chat_service.py:277`）
**override** 了 `ChatService.start_turn`，而生产服务 `StandardContinuationChatService`
（`get_chat_service()` 返回）正是其子类。因此**只改 `chat_service.py` 无法消除生产路径的隐式回退**。

按 §2.4 的规则（消除 `confirmed_points` 对 `expected_concepts` 的隐式回退）语义一致性要求，
本刀将**同一规则同时应用于 `policy_chat_service.py`**。该文件不在「禁止主动修改」列表内，
但不在「建议允许修改」列表内，故如实登记为范围说明（scope note），供用户复核。

---

## 9. 强制回归矩阵

| 编号  | 测试目标                      | 通过条件                   |
| --- | ------------------------- | ---------------------- |
| T01 | 用户仅说“懂了”                  | 不 confirmed            |
| T02 | 启发式 concluded             | Legacy 可变化，durable 不变  |
| T03 | legacy confirmed 被读取      | 标为未验证                  |
| T04 | 无显式 expected_concepts     | 不从 legacy confirmed 回退 |
| T05 | 显式课程目标                    | 仍能成为评估目标               |
| T06 | 正式 Review                 | 原有绑定与评估输入正常            |
| T07 | 有效 durable pass           | 对应 Claim confirmed     |
| T08 | durable partial/fail      | 不 confirmed            |
| T09 | 无 durable Goal            | legacy fallback        |
| T10 | 有 durable Goal            | durable-first          |
| T11 | durable 旧 revision 验证     | 保持既有 lineage 投影        |
| T12 | 重启与重复 commit              | 不丢状态、不重复写入             |
| T13 | thread 身份隔离               | 不串学习事实                 |
| T14 | §164 三种既有状态               | 观察口径不变                 |
| T15 | durable-read OFF / canary | 不出现隐式新写入               |
| T16 | Lookup / Standard / Deep  | 不创建 mastery            |
| T17 | 普通 UI 操作                  | 不创建 mastery            |
| T18 | 显式 closure commit         | 正式写入链正常                |

### 必要变异负控

至少要证明以下破坏会被测试抓住：

```
M1 恢复 confirmed_points 默认回退
   → T04 FAIL

M2 把 legacy confirmed 当 verified
   → T03 FAIL

M3 允许用户自述提升 durable mastery
   → T01/T02 FAIL

M4 破坏正式 Review expected_concepts 绑定
   → T06 FAIL

M5 禁用 durable-first
   → T10 FAIL

M6 允许研究或 UI 绕过 closure 写入
   → T16/T17 FAIL
```

不要求对已有、未发生变更的全部学习系统进行重新 mutation qualification。

---

## 10. 验收顺序

### Gate A：基线与合同

- 记录 exact base SHA；
- 保留既有 worktree 修改；
- 确认文件范围；
- 冻结本合同；
- 不改 §164 仪器。

### Gate B：L1 A+ 实现

一次完成：

- authority 只读分类；
- `confirmed_points` 评估回退隔离；
- legacy 展示标签；
- 正式 Review 与 durable 验证兼容测试。

### Gate C：L2–L6 验证

- 运行 T07–T18；
- 仅针对真实失败做定点修复；
- 不能为通过测试而改写既有状态解释；
- 已通过的功能无需重做。

### Gate D：集中本地验证

至少包含：

```
Learning State-1 focused tests
Chat/Pedagogy impact set
LearnerModel / LearningResume
LearningClosure / Review
§164 原有关键回归

ruff
expanded mypy
mypy baseline
git diff --check
scope audit
```

`mypy baseline` 不允许退化。

### Gate E：候选冻结

- 一个 bounded implementation PR；
- 尽量一个功能提交；
- 记录 exact head；
- 汇总 T01–T18 结果；
- 汇总 mutation 结果；
- 普通 CI 在 exact head 成功；
- 不为每个小修复反复提交或触发 CI。

仅在仓库现有阶段门明确要求时触发正式 L3。

---

## 11. 完成定义

Learning State-1 可以 CLOSED，当且仅当：

1. 用户自述不会被误认为正式掌握；
2. Legacy 状态仍可兼容读取；
3. `confirmed_points` 不再隐式作为评估目标回喂；
4. 正式 Review 语义未回归；
5. durable Claim 验证和既有 lineage 语义保持正确；
6. 学习目标、验证记录和下一步能够恢复；
7. §164 时序与异构投影解释保持不变；
8. 普通聊天、三层检索、Intelligent UI 不会隐式写入 mastery；
9. 关键负控具有变异敏感性；
10. 本地集中回归和 exact-head CI 达到约定验收门。

**不要求：**

- 所有 legacy 数据迁移为 durable；
- `MISSING_DURABLE` 消失；
- 所有学习回合自动 closure；
- 所有知识都能由模型自动证明已掌握；
- 自动复习调度上线；
- B 线 Intelligent UI 完成；
- Deep-4B 获得发布资格。

---

## 12. 下一阶段接口

A 线向 B 线提供只读学习状态，不暴露新的直接写入入口。

最小接口语义：

```
learning_view:
  goal
  claims
  authority
  unresolved
  next_step
  provenance
  validation_status
```

B 线可以展示、筛选、交互或收集练习结果。

正式的学习事实更新必须重新进入现有 LearningClosure 提交与验证流程。

两条线先分别 CLOSED，再考虑 Learning × Intelligent UI 的端到端合并验收。
