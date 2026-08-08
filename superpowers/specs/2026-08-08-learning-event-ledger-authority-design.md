# Study Agent Learning Event Ledger 与事件权限模型

> 文档类型：产品设计规范 / GrillMe 已锁定专项设计  
> 状态：locked  
> 日期：2026-08-08  
> 上位约束：`superpowers/specs/2026-08-07-product-design-direction-design.md`  
> 关联规范：`superpowers/specs/2026-08-08-offline-group-event-model-design.md`  
> 适用范围：Learning Event Ledger、事件生命周期、Active Event Set、Event Delivery、Attention Policy、Event Authority、LLM/规则边界、Learning Evidence 与状态真值

---

## 1. 决策摘要

Study Agent 的 Learning Event 不应被设计成“模型觉得发生了什么”的日志，也不应成为一个永久堆积、任何消费者都能随意解释的消息队列。

当前锁定模型：

> **Event 表示当前或历史上发生过、具有可追溯依据、可能改变未来用户体验的状态信号。**

> **Event History 与 Active Event Set 分离。历史可以保留，只有仍然有效的 Active Event 才能驱动产品行为。**

> **Event validity 与 Event delivery 分离。看过、呈现过，不等于事件已经解决。**

> **LLM 可以做语义理解、Assessment 与候选判断，但不能直接拥有高价值学习事实的写入权。**

> **每一种 Trusted Event 必须有明确 Event Authority。**

整体链路：

```text
用户行为 / 系统变化 / 外部真实变化
                ↓
           Observation
                ↓
      ┌─────────┴─────────┐
      ↓                   ↓
确定性规则           Semantic Evaluator
      ↓                   ↓
System Fact         Assessment / Evidence
      └─────────┬─────────┘
                ↓
          Domain Authority
                ↓
           Trusted Event
                ↓
           Event Ledger
                ↓
        Active Event Set
                ↓
        Attention Policy
       ↙        ↓        ↘
    首页       群聊      通知
```

---

## 2. Event Ledger 不是永久待办箱

Learning Event Ledger 必须有生命周期，不能只有 `created_at`。

但需要避免把“事实是否仍有效”和“这个事实是否已经展示给用户”混在一个状态里。

因此事件本身的生命周期锁定为：

```text
active
resolved
superseded
expired
dismissed
```

### 2.1 active

事件当前仍成立，且可能影响未来产品行为。

例如：

```text
review_due(task=A)
```

用户尚未完成复习，该事件保持 `active`。

### 2.2 resolved

事件对应的问题已经通过真实状态变化解决。

例如：

```text
review_due(task=A)
↓
用户完成复习并形成有效复习证据
↓
resolved
```

### 2.3 superseded

后来的、更可信或更新的事实使旧事件失效。

这是学习系统尤其重要的状态。

例如：

```text
review_due(task=A)
↓
mastery_evidence_added(task=A)
↓
review_completed(task=A)
```

原来的 `review_due` 不应该继续等待消费，而应被新的状态覆盖：

```text
status = superseded
superseded_by = <new event/state transition>
```

核心原则：

> **学习状态不是邮件；新的事实有权覆盖旧信号。**

### 2.4 expired

事件没有被显式解决，但已经超过有意义的行动窗口。

例如：

- 一个已经过去很久的临时提醒；
- 一个过期的资料更新信号；
- 一个已经失去上下文价值的短期 Relationship Event。

### 2.5 dismissed

用户明确要求忽略、不再提示或撤销该事件对应的建议。

`dismissed` 是用户控制，不应与模型自动判断混淆。

---

## 3. 删除 `consumed` 作为 Event 生命周期

此前候选状态中包含 `consumed`，本轮正式删除。

原因：一个 Event 未来可能同时影响：首页、群聊、学习路线和通知。

因此“被某个 Surface 用过一次”不能代表该 Event 已经无效。

硬原则：

> **Seen ≠ Resolved。**

例如首页展示：

```text
Spring 事务现在适合复习
```

只能说明：

```text
home = surfaced
```

不能说明：

```text
review_due = resolved
```

事件事实生命周期与呈现状态必须分离。

---

## 4. Event History 与 Active Event Set

逻辑上必须区分：

```text
Event History
= 过去发生过什么

Active Event Set
= 现在还有什么值得行动
```

物理实现可以使用同一张表，但查询层必须严格。

只有以下事件允许进入 Active Event Set：

```text
status = active
```

以下消费者默认只能读取 Active Event Set：

- 首页主动提示；
- Group Orchestrator；
- Notification Policy；
- 学习路线主动推荐；
- 复习建议系统。

禁止把所有历史 Event 全量塞给 LLM 再让模型自行判断哪些还有效。

事件有效性应由所属 Domain 预先确定。

---

## 5. Event 不是 Telemetry

Event Ledger 不应该记录每一次技术状态变化。

硬门槛：

> **如果这个事件被 Agent 知道后，不会改变未来某一次用户体验，它就不应该进入 Learning Event Ledger。**

通常不值得进入 Ledger：

```text
RAG query completed
user sent message
token stream finished
CI polling tick
route recalculated with no meaningful user-visible difference
```

可能值得进入 Ledger：

```text
review_due
unfinished_question
route_replanned with meaningful next-step change
source_updated for currently studied source
current source CI changed to failed
learning_goal_reached
prerequisite_gap_confirmed
deadline_near
```

Telemetry、性能、调用链等技术事件属于 Lab / Observability，不应污染学习事件系统。

---

## 6. Dedupe 与 Supersede

Active Event Set 不得通过重复 append 无限增长。

建议每个 Event 具有逻辑 `dedupe_key`。

例如：

```text
review_due:task_123
```

同一个 Task 连续触发多次 review_due 时，不应产生：

```text
review_due #1
review_due #2
review_due #3
review_due #4
```

并全部保持 active。

应通过事件类型自身的策略：

- 更新；
- 合并；
- supersede；

保证 Active Event Set 中只有当前最有行动价值的信号。

重要原则：

> **Event Ledger 可以保留历史，但 Active Event Set 不能积累逻辑重复项。**

---

## 7. Event validity 的 Owner

Group Orchestrator、首页、Notification Policy 等消费者没有权力自行修改学习事实。

锁定原则：

> **Event validity 属于产生该事件的 Domain；Presentation 属于消费者。**

例如：

```text
Review Scheduler
↓
产生 / resolve review_due

Route Engine
↓
产生 route_replanned

Learning Task Domain
↓
产生 task_created / task_mastered / task_state_changed

Evidence Domain
↓
产生 evidence_added / evidence_invalidated
```

Group Orchestrator 只能决定：

> “这个 active Event 值不值得现在通过群聊表达？”

不能决定：

> “我觉得这个 review_due 已经过期，所以我把它删掉。”

这样可以防止每个消费者拥有一套自己的 validity 逻辑。

---

## 8. Event Delivery 与 Attention Policy

一个 Event 可以影响多个产品 Surface，但不能让每个 Surface 独立产生重复提醒。

因此锁定：

> **Event validity 与 Event delivery 严格分离。**

建议 Delivery 语义至少能表达：

```text
surface = home | group | notification
state   = surfaced | acknowledged
surfaced_at
presentation_key
```

实现上 V1 可以暂时采用轻量字段或 JSON，不强制立即建立独立表；但概念上必须分离。

### 8.1 一个 Event 可以影响多个 Surface

例如：

```text
hard_goal_completed
```

可能同时导致：

- 首页路线状态更新；
- 群聊伙伴给予关系反馈。

这不是重复提醒，因为两个 Surface 承担不同作用。

### 8.2 同一时刻只有一个主要主动呈现渠道

锁定原则：

> **事实可以被多个 Surface 使用，但同一时刻只能有一个主要主动呈现渠道。**

推荐默认优先级：

```text
1. 当前 Learning Session 内自然处理
2. 首页 / 当前 Learning Task
3. 群聊社会化呈现
4. 应用外通知
```

越往后，介入门槛越高。

---

## 9. 首页、群聊与通知的职责

### 9.1 首页

首页是最低侵入的默认主动 Surface。

适合：

- 当前 Learning Task；
- unfinished question；
- review_due；
- route_replanned；
- deadline_near；
- 下一步建议。

首页默认拥有大部分学习型 Event 的主要呈现优先级。

### 9.2 群聊

Group Orchestrator 没有“提醒所有 Event”的职责。

只有当通过角色关系、多视角讨论或伙伴感呈现能产生额外价值时，Event 才适合进入群聊。

适合：

- hard_goal_completed；
- meaningful learning breakthrough；
- prolonged project milestone；
- 某个值得多视角解释的 unresolved learning event；
- 有真实关系连续性价值的 Relationship Event。

不适合机械搬运：

- 所有 deadline；
- 所有 route change；
- 所有 source update；
- 所有 review_due。

### 9.3 应用外通知

门槛最高。

一个 Event 只有在满足以下条件时才有资格进入 external notification：

```text
高价值
+
时间敏感
+
用户已明确 opt-in
+
没有更低侵入渠道能够及时处理
```

外部通知不得成为 DAU 或角色存在感工具。

---

## 10. Observation、Assessment、Evidence、Event 必须分层

Study Agent 不能把用户一句话直接解释成高价值学习事实。

锁定四层概念：

```text
Observation
↓
Assessment
↓
Learning Evidence
↓
Domain State Transition / Trusted Event
```

### 10.1 Observation

Observation 表示“发生了什么”，尽可能保留原始、可追溯事实。

例如：

```text
user_submitted_answer
user_explained_concept
practice_result
task_switched
source_updated
deadline_changed
session_ended
```

`user_explained_concept` 只说明用户进行了“解释”这个行为，不说明解释正确。

### 10.2 Assessment

Assessment 对 Observation 做语义或规则评价。

例如：

```text
objective = 解释 self-invocation 为什么失效

assessment:
- correctly identified proxy bypass
- distinguished target object from proxy
- missed nested transaction consequence

confidence = high
```

Assessment 是判断，不是最终 Task 真值。

### 10.3 Learning Evidence

当 Assessment 满足某类证据标准后，可以形成可追溯 Learning Evidence。

例如：

- understanding evidence；
- transfer evidence；
- misconception evidence；
- recall evidence；
- practice evidence。

### 10.4 Trusted Event / State Transition

由明确 Domain Authority 根据：

```text
当前状态
+
已有 Evidence
+
本轮 Evidence / System Fact
+
必要的用户确认
```

决定是否产生高价值状态变化或 Trusted Event。

---

## 11. 规则与 LLM 的权限边界

Study Agent 不采用“所有 Event 由规则产生”或“所有 Event 由 LLM 产生”的单一路线。

锁定原则：

> **事件事实尽量由确定性规则产生；LLM 负责解释、归类和提出候选，不直接拥有高价值学习事实的写入权。**

### 11.1 适合确定性规则直接产生的 Event

典型包括：

- `review_due`；
- `deadline_near`；
- `source_updated`；
- `task_switched`；
- `task_created`；
- `task_completed_by_user`；
- `route_replanned`；
- `index_completed`；
- 可验证 CI/source state change。

### 11.2 需要语义判断的 Candidate / Evidence

典型包括：

- `misconception_detected`；
- `understanding_evidence_added`；
- `transfer_evidence_added`；
- `prerequisite_gap_candidate`；
- `unfinished_question_candidate`；
- 用户解释是否真正覆盖关键概念。

这些可以由 Semantic Evaluator 参与，但应先产出 Assessment / Candidate / Evidence，而不是直接修改高价值 Task 真值。

---

## 12. Candidate 与 Confirmed 分离

LLM 的语义推断可以产生 Candidate Signal。

例如：

```text
prerequisite_gap_candidate
subject = Java dynamic proxy
confidence = 0.72
```

它不应立即变成：

```text
prerequisite_gap_confirmed
```

Candidate 可以通过以下方式升级：

- 后续自然对话验证；
- 既有 Learning Evidence 交叉确认；
- 用户明确纠正或确认；
- 小型迁移/验证活动；
- deterministic domain rule 接受。

硬边界：

> **模型推测不能因为“置信度很高”就自动成为长期学习事实。**

---

## 13. Confidence 不是权限

禁止使用单一阈值：

```text
confidence > 0.8
→ 自动写入学习事实
```

原因：模型自报的 0.82 不是可信概率，也不能替代产品风险判断。

是否允许自动写入，应综合：

```text
confidence
+
event policy
+
evidence requirements
+
事件风险等级
```

### 13.1 低风险动作

例如 Task 归属判断。

高置信时可以自动调整，并提供 Undo / 低成本纠正。

### 13.2 中风险判断

例如 prerequisite gap candidate。

可以影响推荐，但不能直接改变用户长期能力事实。

### 13.3 高风险判断

例如：

```text
用户已掌握某概念
```

绝不能仅依据 LLM confidence 自动确认。

需要更强 Learning Evidence，必要时结合用户确认。

---

## 14. Event Authority

每种 Trusted Event 都必须明确谁有权产生、resolve 或 supersede 它。

建议 Authority 示例：

| Event | Authority |
| --- | --- |
| `review_due` | Review Scheduler / Review Domain |
| `deadline_near` | Planning Domain |
| `source_updated` | Evidence / Source Domain |
| `task_created` | Learning Task Domain |
| `task_state_changed` | Learning Task Domain |
| `route_replanned` | Route Engine |
| `understanding_evidence_added` | Pedagogy / Evidence Domain |
| `transfer_evidence_added` | Pedagogy / Evidence Domain |
| `task_mastered` | Learning Task Domain based on sufficient evidence and policy |
| `relationship_milestone` | Relationship Domain |
| `group_message_created` | Group Chat Domain |

具体名称允许实现层调整，但单一 Authority 原则不可破坏。

禁止：

- Group Orchestrator 顺手写 `task_mastered`；
- Memory extractor 顺手改 Learning Route；
- Notification Policy 改 Event validity；
- 任意 Prompt 直接修改跨 Domain 真值。

---

## 15. Event 来源信任等级

在现有 `origin` 可追溯原则基础上，Learning Event 判断层进一步区分以下来源语义：

```text
SYSTEM_FACT
USER_EXPLICIT
ASSESSED
INFERRED
```

### 15.1 SYSTEM_FACT

系统可验证事实，例如：

- 时间到达；
- deadline；
- Git SHA 变化；
- CI 状态；
- 用户真实操作；
- Task 实际状态变化。

可直接驱动与该事实权限相符的状态。

### 15.2 USER_EXPLICIT

用户明确表达的事实、意图或自我判断。

例如：

> “这个我会了。”

可信事实是：

> 用户自述自己会了。

不自动等于：

> 系统已证实掌握。

### 15.3 ASSESSED

由 evaluator 从真实用户行为中得出的证据性判断。

例如：

- Feynman explanation passed；
- transfer example succeeded；
- recurring misconception detected。

可以成为 Learning Evidence。

### 15.4 INFERRED

模型推测。

只能用于：

- 提建议；
- 生成 Candidate；
- 决定下一步验证；
- 调整临时教学策略。

不能直接修改高价值长期学习事实。

---

## 16. Memory 与 Event 必须分开

Memory 与 Event 是两个不同产品对象。

```text
Memory
= 可检索的历史上下文、用户偏好、稳定事实、学习摘要等

Event
= 当前或历史上真实发生、并可能驱动行动的状态信号
```

禁止直接：

```text
Memory
→ Trusted Event
```

推荐链路：

```text
Memory
→ 作为 Assessment 输入
→ Evidence / Candidate
→ Domain Authority
→ Event
```

否则旧记忆会反复重新触发主动行为。

---

## 17. Relationship Event 也受相同权限约束

角色关系事件不能因为 LLM 想延续气氛就升级成长期用户事实。

例如用户说：

> “今天好累。”

可以形成短期 Observation：

```text
user_reported_tiredness
at = 2026-08-08
```

但不能自动升级为：

```text
user_trait = 容易疲惫
```

Relationship Domain 可以依据真实历史产生短期、可过期的 Relationship Event，但必须保留来源与时间边界。

---

## 18. Group Orchestrator 是 Event 消费者，不是事实 Owner

Group Orchestrator 可以：

- 查询 Active Event Set；
- 结合 Delivery 状态避免重复提醒；
- 判断是否值得社会化表达；
- 选择 0–N 个角色；
- 分配动态认知职责；
- 物化真正的 Group Message；
- 正确保持安静。

Group Orchestrator 不可以：

- 创建未经 Authority 确认的 mastery truth；
- resolve / supersede Learning Event；
- 根据 NPC 自己的对话修改用户能力；
- 把 `INFERRED` 推测升级为 `SYSTEM_FACT`；
- 为了生成群聊而伪造 Event。

---

## 19. 当前建议的最小 Event 数据语义

实现前应保留以下概念，但本规范不强制精确字段名：

```text
Event
├─ event_id
├─ event_type
├─ subject_type
├─ subject_id
├─ status
│   ├─ active
│   ├─ resolved
│   ├─ superseded
│   ├─ expired
│   └─ dismissed
├─ created_at
├─ expires_at
├─ dedupe_key
├─ superseded_by
├─ authority
├─ origin / trust_class
├─ source_ref
└─ payload
```

以及独立 Delivery 语义：

```text
EventDelivery
├─ event_id
├─ surface
│   ├─ home
│   ├─ group
│   └─ notification
├─ state
│   ├─ surfaced
│   └─ acknowledged
├─ surfaced_at
└─ presentation_key
```

V1 不要求一次实现所有字段，但不能通过一个无语义约束的 `type + payload JSON` 万能表绕过 Domain owner 与 lifecycle。

---

## 20. V1 事件类型应保持克制

不要一次建立几十种 Event。

V1 建议优先验证少量高价值类型，例如：

```text
review_due
unfinished_question
route_replanned
learning_goal_reached
prerequisite_gap_confirmed
source_updated
deadline_near
hard_goal_completed
relationship_milestone
```

总量应控制在约 10 类以内，先证明这些 Event 能产生真实、有价值的用户体验，再扩展。

---

## 21. 当前明确禁止的实现

1. 不允许 LLM 直接输出 `task_mastered=true` 并写入长期真值。
2. 不允许 `confidence > threshold` 单独决定高价值事实写入。
3. 不允许所有历史 Event 全量交给消费者自行判断 validity。
4. 不允许首页、群聊、通知各自维护重复的 Event 有效性规则。
5. 不允许一个 Event 被三个 Surface 独立主动提醒三次。
6. 不允许把 `surfaced` 当作 `resolved`。
7. 不允许 Group Orchestrator 修改 Learning Task 真值。
8. 不允许 Memory 直接触发 Trusted Event 而绕过 Assessment / Authority。
9. 不允许把 Telemetry 塞进 Learning Event Ledger。
10. 不允许 Active Event Set 通过重复 append 无限增长。
11. 不允许低权限 `INFERRED` 推测污染高权限长期学习事实。
12. 不允许建立一个新的“超级 LearningStateAgent”同时拥有评估、事件、路线、记忆、复习、群聊和通知全部权限。

---

## 22. 验收原则

未来实现 Event Ledger 时，至少应有以下边界测试或人工验收：

### 22.1 生命周期

- 新事件默认进入 `active`；
- 后续真实状态可将旧事件标记为 `resolved` 或 `superseded`；
- 过期事件不再进入 Active Event Set；
- dismissed 事件不再主动呈现；
- History 仍可审计旧事件。

### 22.2 去重

- 同一 `dedupe_key` 不产生多个同时 active 的逻辑重复 Event；
- 新事实能正确 supersede 旧事件；
- 事件重放或启动补算保持幂等。

### 22.3 Delivery

- 首页 `surfaced` 后 Event 仍保持 active，直到真实问题解决；
- 群聊不会因为首页已提醒而重复正式提醒；
- notification 必须经过更高门槛；
- 没有真实 Message 时不产生 fake unread。

### 22.4 Authority

- Group Orchestrator 不能修改 mastery 状态；
- Notification Policy 不能 resolve Event；
- Memory extractor 不能直接写 route/mastery truth；
- 每类 Trusted Event 都能追溯 Authority 与 source。

### 22.5 LLM 边界

- “我懂了”不会自动变成已掌握；
- 高 confidence 推测不会绕过 Evidence policy；
- Semantic Evaluator 输出错误时不会直接污染 Task 真值；
- Candidate 可以被后续 Evidence 否定或升级。

---

## 23. 当前尚未锁定

以下问题继续 GrillMe，不应在实现中提前拍板：

1. Learning Evidence 是否成为独立一等公民，以及最小数据模型；
2. Evidence 的强度、冲突、撤销和时间衰减策略；
3. `task_mastered` 是否需要用户最终确认，哪些情况可以自动确认；
4. Review Scheduler 的具体间隔学习算法；
5. Active Event Set 的查询 API 与物理表结构；
6. Delivery 是否独立建表还是 V1 暂存 JSON；
7. Attention Policy 的精确优先级与升级时间窗口；
8. Relationship Event 的过期时间与长期关系状态升级规则；
9. Event Ledger 与未来 Learning Task / Route 数据模型的具体外键结构。

---

## 24. 一句话原则

如果未来实现出现冲突，优先使用以下原则判断：

> **LLM 可以看懂学习，但不能自己宣布学习事实；Event 可以驱动主动行为，但只有仍然有效、来源可追溯、权限正确的 Trusted Event 才能进入 Active Event Set。**
