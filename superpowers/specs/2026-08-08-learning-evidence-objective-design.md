# Study Agent Learning Evidence System 与 Objective 模型

> 文档类型：产品设计规范 / GrillMe 已锁定专项设计  
> 状态：locked  
> 日期：2026-08-08  
> 上位约束：`superpowers/specs/2026-08-07-product-design-direction-design.md`  
> 关联规范：
> - `superpowers/specs/2026-08-08-learning-event-ledger-authority-design.md`
> - `superpowers/specs/2026-08-08-offline-group-event-model-design.md`
> 适用范围：Learning Evidence System、Evidence 原子模型、Objective、Verification Contract 边界、Task/Route/Review/Group 的证据消费关系

---

## 1. 决策摘要

Study Agent 的 Learning Evidence 不是 Learning Task 上的几个附加字段，也不是某个教学模式内部的临时评分。

锁定：

> **Learning Evidence 应成为 Study Agent 的系统级一等公民。**

它负责保存和解释：

- 用户究竟表现出了什么能力；
- 该表现对应哪个明确学习目标；
- 原始依据在哪里；
- 系统如何判断；
- 判断由哪个 evaluator / rule 产生；
- 新证据如何支持、冲突或修正当前能力结论。

Learning Task、Route、Review、Group、Memory 等系统均不得各自重新解释完整聊天历史来建立第二套学习判断。

整体关系：

```text
用户真实行为 / 作品 / 练习 / 回答
              ↓
          Observation
              ↓
          Assessment
              ↓
       Learning Evidence
              ↓
     Evidence Aggregation / View
       ↙        ↓        ↘
Learning Task  Route     Review
       │                    │
       └──────→ Event Ledger

Group / 首页 / 其他 Surface
只消费受控 Evidence View 或由上层 Domain 产生的状态
```

硬原则：

> **Mastery 不是 Evidence。Mastery 是某个 Learning Task 在明确 Objective 与 Verification Contract 下，根据 Evidence System 视图推导出的目标相关状态。**

---

## 2. 为什么必须是 System，而不是 Evidence Store

`Store` 容易让实现退化为“把几条评分结果存进数据库”。

Learning Evidence System 至少承担：

- Evidence 生命周期与可追溯性；
- Observation / Assessment 分离；
- 来源与 evaluator provenance；
- Objective 绑定；
- 支持证据与冲突证据并存；
- 旧 Evidence 的历史保留；
- Evidence View / aggregation；
- Task / Route / Review / Group 的统一查询边界。

因此它是学习状态基础设施，而不只是持久化层。

---

## 3. Evidence 的原子定义

锁定定义：

> **一条 Learning Evidence = 用户在某个明确学习 Objective 上，于某一时刻产生的一次可追溯能力表现，以及系统对此表现的一次可审计判断。**

它不是：

- 一整个 Session；
- 一整个 Learning Task；
- 一整轮聊天；
- 一道题的题号本身；
- 一个简单 `mastered=true`；
- 一个脱离原始来源的模型结论。

一条正式 Evidence 在写入前必须回答五个问题：

1. **证明了什么？**
2. **用户实际做了什么？**
3. **系统怎么判断的？**
4. **原始依据在哪里，谁做了判断？**
5. **这个表现实际发生在什么时候？**

如果其中任意一项无法回答，该信息最多是 Candidate Signal，不应成为正式 Learning Evidence。

---

## 4. Evidence V1 五要素

V1 不追求几十个字段，只锁定五类不可缺少的语义。

```text
Objective
+
Observation
+
Assessment
+
Provenance
+
Time
```

概念 Schema：

```text
LearningEvidence

identity
  evidence_id

target
  objective_id
  task_context_id?

observation
  evidence_type
  observation
  observed_at

assessment
  outcome
  assessment
  evaluator_ref

provenance
  source_kind
  source_ref

validity
  status
```

字段名属于实现层，可调整；上述语义不可丢失。

---

## 5. Objective：Evidence 必须证明一个明确能力

Evidence 不应只绑定模糊 Task 名称。

错误：

```text
task = Spring 事务
```

这无法说明一条 Evidence 究竟证明：

- 会解释代理；
- 会判断传播机制；
- 会定位 self-invocation；
- 还是会实际排错。

因此锁定：

> **Objective 是 Evidence V1 的主要语义锚点。**

Objective 应表达可验证能力，例如：

```text
能解释为什么 @Transactional 依赖代理调用

能判断 self-invocation 是否会经过代理

能解释 REQUIRED 与 REQUIRES_NEW 的事务边界差异

能在一段新代码中定位典型事务失效原因
```

而不是章节目录：

```text
Spring 事务简介
@Transactional
传播机制
隔离级别
```

核心句式：

> **用户能够做 X。**

而不是：

> 学习 X。

---

## 6. V1 暂不建立完整 Concept Graph

Objective 需要比 Task 更精确，但 V1 不应因此立即建设完整知识图谱。

建议 V1：

```text
objective_id
+
task_context_id
+
可选 concept_ref
```

以后 Objective 与跨 Task 复用关系稳定后，再评估 Concept Graph。

当前禁止同时引入复杂：

- Concept Graph；
- Task Graph；
- Route Graph；
- Objective DAG；

四套图结构。

必要的 Objective 前置关系可以先保留轻量扩展位，例如：

```text
prerequisite_objective_ids?
```

但 V1 不建立独立图引擎。

---

## 7. Observation：用户实际上做了什么

Observation 必须尽量靠近可追溯事实。

正确示例：

```text
observation_type = user_explanation

用户自主指出：
内部 this 调用没有重新经过 Spring 创建的代理对象。
```

或：

```text
observation_type = practice_answer

用户判断：
REQUIRES_NEW 内层事务可以独立于外层事务提交。
```

源码学习：

```text
observation_type = code_explanation

用户指出：
ServiceA.this.methodB() 直接进入目标对象，未重新经过 proxy。
```

项目学习：

```text
observation_type = artifact

用户提交的修复将事务边界移至独立 Bean，并通过对应回归测试。
```

禁止只保存：

```text
用户理解得很好
```

因为这已经属于 Assessment。

硬边界：

> **Observation 是发生了什么；Assessment 是系统如何理解它。**

Observation 不应因为后续 evaluator 变化而被改写。

---

## 8. 原始内容优先使用 source_ref 追溯

Evidence 不默认复制整轮聊天正文。

推荐：

```text
observation:
用户正确指出 this 调用绕过 proxy。

source_ref:
chat_turn:turn_893
```

必要时可保存最小 excerpt，但完整原始材料应由 source_ref 指向真实 owner。

原因：

- 避免同一聊天被复制多份；
- 降低 Evidence 数据膨胀；
- 避免隐私数据重复；
- 方便删除/迁移原始数据；
- 允许以后重新评估原始 Observation；
- 保持 Provenance 清晰。

如果以后“一次 Observation → 多条 Evidence”成为常态，可以再抽独立 Observation Store；V1 不为此提前增加一级 durable entity。

---

## 9. Evidence Type：用户以什么方式表现能力

`Evidence Type` 与 `Assessment Outcome` 必须分开。

V1 建议保持少量能力表现类型：

```text
self_report
recognition
explanation
reasoning
application
transfer
artifact
correction
```

含义：

### 9.1 self_report

用户明确说：

```text
这个我会了
这个我不懂
```

这是用户自述，不等于系统验证。

### 9.2 recognition

用户能够识别、选择、判断基本概念或答案。

### 9.3 explanation

用户能够用自己的话说明一个概念或机制。

### 9.4 reasoning

用户能够解释 why、因果链、推导或关键机制。

### 9.5 application

用户能够在直接场景中使用所学内容。

### 9.6 transfer

用户能够在变化后的新场景中迁移能力。

### 9.7 artifact

代码、作业、作品、设计或其他成果体现能力。

### 9.8 correction

用户能够发现并纠正自己或 Agent 的错误。

重要原则：

> **接触过 ≠ 理解了 ≠ 能独立使用。**

不同 Evidence Type 表示不同能力层次，不能统一折叠成一个“答对/答错”。

---

## 10. Assessment Outcome：这次表现说明了什么

V1 不建议将所有表现强行转成 `passed / failed`。

推荐最小 Outcome：

```text
supporting
conflicting
insufficient
```

### supporting

这次表现对目标能力提供正证据。

### conflicting

这次表现与已有能力结论或期待发生实质冲突。

### insufficient

本次行为不足以支持有效能力结论。

例如用户仅说：

```text
“嗯，懂了。”
```

可以记录：

```text
evidence_type = self_report
outcome = insufficient for verified mastery
```

用户自述仍然是有价值信息，但不能伪装成验证后的 mastery。

同一个 Evidence Type 可以产生不同 Outcome：

```text
explanation + supporting
explanation + conflicting
```

因此：

> **Evidence Type = 用户采用了什么表现形式。**

> **Outcome = 这次表现对 Objective 说明了什么。**

---

## 11. Assessment 必须可解释

Assessment 不能只保存：

```text
passed = true
```

至少应能够解释为什么。

例如：

```text
Assessment
- 正确识别 proxy bypass
- 正确区分代理对象与目标对象
- 尚未说明事务传播行为

Outcome
supporting
```

这样以后 Task、用户解释、调试和 evaluator 重评才有依据。

---

## 12. Provenance：Evidence 必须回答“凭什么”

每条 Evidence 必须能回到原始依据。

建议 source_kind 示例：

```text
chat_turn
practice_run
learning_activity
artifact
code_artifact
external_assessment
```

示例：

```text
source_kind = chat_turn
source_ref  = turn_123
```

源码：

```text
source_kind = code_artifact
source_ref  = github_snapshot:abc123:file.py:L40-L72
```

费曼复述：

```text
source_kind = learning_activity
source_ref  = feynman_session_32
```

用户上传作品：

```text
source_kind = artifact
source_ref  = submission_218
```

用户问：

> 为什么系统认为我动态代理基础不足？

未来系统必须能够通过 Evidence → source_ref 回到真实上下文，而不是回答“AI 分析认为”。

---

## 13. Evaluator 本身也必须有 Provenance

除了原始 Observation 来源，还必须知道：

> 谁做了判断？

例如：

```text
evaluator_kind = semantic
evaluator_version = pedagogy-evaluator-v3
prompt_version = 7
```

或：

```text
evaluator_kind = deterministic
rule = unit_test_result
rule_version = 2
```

这样以后 evaluator 升级时才能区分：

- 用户能力真的变化；
- 还是判断器变化。

现有 `pedagogy_eval_runs` 已有 evaluator / prompt / schema version 思路，后续实现应优先复用或迁移，而不是再创建一套无版本判断。

---

## 14. Time：核心是 observed_at

Learning Evidence 的关键时间不是数据库插入时间，而是：

> **能力表现实际什么时候发生。**

因此至少需要语义：

```text
observed_at
```

例如用户 8 月 5 日完成一次费曼复述，系统 8 月 8 日重新分析旧 Session：

```text
observed_at = Aug 5
recorded_at = Aug 8
```

不能把 8 月 8 日伪装成新的学习行为。

`recorded_at / assessed_at` 可作为审计 metadata，但学习轨迹主要使用 `observed_at`。

---

## 15. Evidence 不因时间直接删除

旧 Evidence 仍然代表真实历史表现。

例如：

```text
3 月：transfer supporting
5 月：transfer conflicting
5 月：复习
5 月：transfer supporting
```

系统应保留完整轨迹。

时间影响的是：

- 当前相关性；
- Review Scheduler；
- 是否需要新验证；
- 当前 Evidence View 的解释。

而不是简单：

```text
30 天后 Evidence expired
```

硬原则：

> **知识可能遗忘，但历史证据不能被删除来模拟遗忘。**

---

## 16. Evidence 状态

V1 状态保持克制：

```text
active
invalidated
superseded
```

### active

Evidence 本身真实有效，可参与当前聚合。

### invalidated

后来确认这条 Evidence 本身不应成立，例如：

- 测试答案配置错误；
- source_ref 错位；
- evaluator 输入拿错用户；
- artifact 已确认不是用户作品；
- 数据损坏。

### superseded

谨慎使用。

主要用于：

- 同一 Observation 被新版 Assessment 正式重评；
- 旧 Assessment 被明确的新 Assessment 取代。

普通情况：

```text
昨天答对
今天答错
```

不是 supersede。

两次都是有效历史 Evidence，应并存，由 Evidence View 解释“当前表现不稳定”。

---

## 17. Evidence 允许冲突存在

Study Agent 不应强迫每个知识点时刻处于：

```text
会 / 不会
```

二选一。

真实状态可能是：

```text
原理解释：强
简单应用：强
复杂迁移：冲突
边界条件：薄弱
```

Evidence System 必须允许支持与冲突 Evidence 同时存在。

例如：

```text
Objective: 理解 REQUIRES_NEW

支持证据
✓ 能解释独立事务
✓ 简单案例判断正确

冲突证据
△ 外层异常场景判断错误

Evidence View
待验证
薄弱点：异常传播与提交边界
```

这比伪精确的“掌握度 71%”更有学习价值。

---

## 18. 不采用简单线性掌握分数

V1 不采用：

```text
explanation +20
transfer +30
failed -15
=> mastery 83%
```

原因：不同 Evidence 类型、难度、独立程度、时间与迁移价值不能简单线性相加。

例如：

```text
5 次简单 recognition 全对
```

不一定比：

```text
1 次复杂 transfer 成功
```

更强。

当前优先输出可解释状态：

```text
学习中
待验证
已掌握
需要复习
存在冲突证据
```

以及具体 Evidence View，而不是伪精确百分比。

---

## 19. Mastery 属于 Task Domain，不属于 Evidence

禁止：

```text
Evidence:
mastery = true
```

正确关系：

```text
Evidence
- explanation supporting
- application supporting
- transfer supporting
        ↓
Evidence View
        ↓
Learning Task Domain
        ↓
Task / Objective State
```

同一批 Evidence 对不同 Learning Task 的含义可能不同。

例如 Evidence 表明：

```text
explanation = strong
reasoning = strong
application = moderate
transfer = none
```

对于 Task：

```text
“能解释 self-invocation 为什么失效”
```

可能已足够。

但对于 Task：

```text
“能独立排查生产环境 Spring 事务失效”
```

明显不够。

因此：

> **是否掌握没有脱离目标的绝对答案。**

---

## 20. 用户明确自述的权限

用户说：

```text
“这个我已经会了。”
```

系统应尊重该输入，并允许路线立即低成本调整。

但 Evidence 语义应是：

```text
evidence_type = self_report
source = USER_EXPLICIT
```

而不是：

```text
mastered = true
```

这样既保持用户路线选择权，又不伪造系统验证。

---

## 21. Task / Route / Review / Group 的消费边界

### 21.1 Learning Task

消费 Evidence View，根据 Objective 与 Verification Contract 决定当前状态。

### 21.2 Route Engine

消费：

```text
Task State
+
Evidence Summary / View
```

不得自行重读聊天历史后建立第二套 evaluator。

### 21.3 Review System

查询某 Objective 最近有哪些 Evidence，再决定：

- 是否进入复习窗口；
- 需要哪种验证；
- 哪个薄弱点优先。

不得自己重新解释完整 Session。

### 21.4 Group Orchestrator

只能消费受控 Evidence View 或由 Learning Domain 派生出的 Trusted Event。

例如它可以得到：

```text
explanation = strong
transfer = weak
```

然后自然表达：

```text
“这个原理你已经解释清楚了，现在更值得看一个新场景。”
```

但 Group Orchestrator 无权自行读取聊天并写：

```text
user_mastered = true
```

---

## 22. Objective 的来源模型

Objective 不要求用户手填。

锁定：

> **Objective 采用“Agent 自动生成 + 系统约束 + 用户低成本纠正”的混合模型。**

与 Learning Task 原则保持一致：

> **用户只管学，系统负责 bookkeeping。**

用户明确目标是最高边界；Agent 默认负责拆分可验证 Objective。

---

## 23. Objective 不是章节目录，也不能无限细碎

Objective 必须表达能力，而不是知识目录。

正确：

```text
能根据题目正确理解积分区域
能写出一种正确积分次序的积分限
能完成对应累次积分计算
能判断交换积分次序是否更简单
```

错误：

```text
二重积分简介
曲边区域
积分次序
交换积分次序
```

另一个极端也禁止：

```text
知道 proxy
知道 this
知道 propagation
知道 @Transactional
...
```

否则 Task 会变成几十个隐藏 Todo。

推荐默认：

> **一个 Learning Task 维护约 3–7 个当前关键 Objective。**

不是硬数据库上限，而是产品粒度约束。

---

## 24. Objective 分 required / supporting / optional

为了防止 Agent 无限扩大 Task 完成门槛，锁定三类：

```text
required
supporting
optional
```

### required

不满足就无法合理声称当前 Task 目标达成。

### supporting

有助于理解或稳定掌握，但不是完成当前 Task 的必要条件。

### optional

扩展学习，只有用户继续深入时才进入当前路线。

硬边界：

> **Required Objective 集合不能被 Agent 无声扩张。**

如果学习过程中发现真正新的必要能力，应通过 Task Domain 的受控重规划产生，并允许用户低成本纠正。

---

## 25. Objective 来源优先级

### 第一优先：用户明确目标

例如用户说：

```text
“我只想搞懂为什么事务失效，不需要学完整 Spring AOP。”
```

Agent 不得偷偷扩成完整 AOP 课程。

### 第二优先：Learning Task Domain / Agent Planner

根据用户目标自动生成 Objective Proposal。

### 第三优先：真实 Learning Evidence

学习过程中发现原 Objective 太粗、缺少关键能力或粒度不合理时，可以提出重构。

### 第四优先：教材 / 课程 / 源码结构 / 外部资料

只提供候选 Objective，不自动成为 Task 完成门槛。

---

## 26. Objective Proposal 与 Objective Set 分离

LLM 可以提出：

```text
Objective Proposal
```

但 Learning Task Domain 才拥有正式：

```text
Objective Set
```

建议链路：

```text
用户目标
↓
Task Intent
↓
Agent Planner
↓
Objective Proposal
↓
Learning Task Domain
检查：
- 是否超出用户目标
- 是否可验证
- 是否重复
- 是否粒度合理
- required / supporting / optional
↓
Objective Set
```

这样可以防止 LLM 因“多学一点总没坏处”不断扩大范围。

---

## 27. Objective 必须有稳定 Identity

Evidence 会引用 Objective，因此 Objective 不能因为一句文案改写就换 ID。

例如：

```text
昨天：
解释 Spring self-invocation 为什么导致事务失效

今天：
说明内部调用为何绕过 Spring 事务代理
```

语义相同，应保持同一 `objective_id`。

因此概念上区分：

```text
objective_id
canonical_intent
display_text
```

显示文案可优化；语义 Identity 必须稳定。

如果 Objective 真正发生语义变化，应创建新 Objective，并将旧 Objective 标记为 retired / superseded，而不是改写旧目标使历史 Evidence 看起来一直在证明新目标。

---

## 28. Objective 可以动态变化，但不能让用户永远学不完

Objective 是 Agent 当前对“完成这个 Task 需要什么能力”的结构化假设，因此允许动态调整。

但禁止：

```text
昨天 required = O1 O2 O3
今天模型一重算 required = O1 O2 O3 O4 O5 O6
```

并且不向用户解释。

动态变化必须遵守：

- 用户目标边界；
- required 集合防膨胀；
- 新增项分类；
- 低成本纠正；
- 历史 Objective / Evidence 不被篡改。

---

## 29. Verification Contract 是 Objective 的必要语义

Objective 不能只写：

```text
“理解 REQUIRES_NEW”
```

至少必须能够表达：

> **什么类型的 Evidence 才足以支持这个 Objective。**

示例：

```text
Objective
能解释 REQUIRED 与 REQUIRES_NEW 的事务边界差异

Verification Contract
- explanation supporting required
- application 或 transfer 至少一种 supporting
- self_report 单独不足
```

因此 Objective 不只告诉系统“学什么”，还告诉 Evidence System：

> **什么样的真实表现算够。**

当前仅锁定 Verification Contract 必须存在；其严格程度、Evidence 组合规则、是否要求 transfer 等细节留给下一轮 Grill，不在本文件提前决定。

---

## 30. Feynman / Socratic 等应服务于 Evidence 获取

以后不再把 Feynman、Socratic 等视为孤立的“学习模式开关”。

例如：

```text
Objective Verification Contract
需要 explanation evidence
↓
Agent 选择 Feynman restatement
↓
用户自然复述
↓
形成 explanation Evidence
```

因此：

- Feynman / Socratic = pedagogy / verification strategy；
- Project / Paper = task type；
- Concept Map = activity / output；

它们不应混在同一“模式”枚举里承担相同产品语义。

---

## 31. Objective 应表达行为层次

Objective 不应只有：

```text
concept = JWT
```

而应表达预期行为：

```text
解释 JWT access / refresh token 的职责差异

设计基本 token refresh 流程

在新场景中判断 token revoke 问题
```

语义上需要区分：

```text
identify
explain
compare
reason
apply
transfer
debug
design
```

不要求 V1 一定实现为独立 `verb` 字段，但 Objective 文本与 Verification Contract 必须体现能力层次。

---

## 32. 用户纠正 Objective 的方式必须极轻

普通用户不应看到 Objective CRUD 管理器。

自然语言即可：

```text
“这个我不想学。”
“这个考试不考。”
“我重点是会做题，不需要证明。”
“这个我已经会了。”
```

系统调整后只需轻提示，例如：

```text
已调整目标：跳过事务隔离级别，当前重点保留事务失效排查。
```

用户不负责维护隐藏学习项目管理结构。

---

## 33. 首页不展示完整 Objective 清单

首页继续围绕当前学习行动，而不是 Todo List。

推荐：

```text
继续学习

排查 Spring 事务失效

当前：
为什么 self-invocation 绕过代理

下一步：
用一个实际代码场景验证
```

完整 Objective Set 只在“学习路线 / 目标详情”中按需展开。

---

## 34. 当前明确禁止的实现

1. 不允许 `task.mastered = true` 成为没有 Evidence 链的单字段真值。
2. 不允许 Group / Route / Review 各自重新读完整聊天并建立第二套能力判断。
3. 不允许 Evidence 只保存 `passed / failed` 而没有 Objective、Observation 与 Provenance。
4. 不允许 Observation 和 Assessment 混成一句“用户理解很好”。
5. 不允许 evaluator 升级后改写用户原始 Observation。
6. 不允许通过删除旧 Evidence 来模拟遗忘。
7. 不允许普通“今天答错”篡改“昨天确实答对”的历史事实。
8. 不允许单纯模型 confidence 自动升级为 mastery。
9. 不允许 Objective 只是章节目录。
10. 不允许 Agent 无声增加大量 required Objective。
11. 不允许教材目录自动成为 Task 完成标准。
12. 不允许因为显示文案改写就生成新的 Objective Identity。
13. 不允许 V1 为了 Evidence 立即建设完整 Concept Graph / Objective DAG。
14. 不允许 self_report 单独伪装成 verified mastery。
15. 不允许普通用户手工维护 Objective CRUD 作为正常学习流程。

---

## 35. V1 验收原则

后续实现至少需要验证：

### 35.1 Evidence 可追溯

任一 Evidence 都能回答：

- Objective 是什么；
- 用户做了什么；
- Assessment 为什么这样判断；
- source_ref 指向哪里；
- evaluator / rule 是谁；
- observed_at 是什么时候。

### 35.2 Observation 不可被 Assessment 改写

重新评估同一原始行为时，Observation 保持稳定，新的 Assessment 有独立版本依据。

### 35.3 冲突 Evidence 可并存

历史 supporting 与近期 conflicting Evidence 不互相删除，Evidence View 能表达当前不稳定状态。

### 35.4 Mastery 可解释

任何 Task / Objective 的“已掌握”状态都能回溯到满足 Verification Contract 的 Evidence，而不是直接模型标签。

### 35.5 Objective 范围受控

Agent 新增 Objective 时不能无声扩大 required 完成门槛。

### 35.6 用户纠正有效

用户可以通过自然语言低成本：

- 跳过某 Objective；
- 调整重点；
- 声明已有基础；
- 改变当前 Task 边界。

### 35.7 各消费者不建立第二套 Evidence Owner

Task、Route、Review、Group 只能消费统一 Evidence View 或领域状态，不得各自实现新的语义 evaluator。

---

## 36. 与现有代码的迁移原则

当前仓库已有：

- `learning_state`；
- `pedagogy_eval_runs`；
- MemoryRun；
- Learning Session / Closure；
- EvidenceRuntime；
- committed learning truth 相关边界。

后续实施前必须先做 domain inventory，确认：

- 哪些现有字段已经承担 Observation / Assessment / Evidence 角色；
- `pedagogy_eval_runs` 哪些结构可直接复用；
- 当前 `EvidenceRuntime` 的“evidence”主要偏来源/RAG 证据，是否需要命名或边界区分；
- 哪些历史学习状态只是 summary，不能直接升级成正式 Learning Evidence；
- 不创建第二套与现有 durable owner 冲突的状态。

本规范当前只定义产品与领域语义，不代表已确定数据库表名、API schema 或迁移顺序。

---

## 37. 今日停止点 / 下一轮 Grill 入口

截至 2026-08-08，本专项已锁定：

- Learning Evidence System 为系统级一等公民；
- Evidence 原子单位；
- V1 五要素；
- Evidence Type / Outcome 分离；
- Provenance 与 evaluator version；
- observed_at 语义；
- 冲突 Evidence 与历史保留；
- Mastery 属于 Task Domain；
- Objective 的来源、粒度、Identity、required/supporting/optional；
- Objective Proposal 与 Objective Set 分离；
- Verification Contract 必须存在。

下一轮尚未锁定的问题：

> **Verification Contract 到底应该有多严格？**

尤其：

> “能独立使用”是否必须要求 transfer Evidence？

该问题留到后续 Grill，不在今天继续扩展。
