# AR-1A：静止态语义合同（Static Answer State）

**当前阅读说明（2026-10-24）**：本合同的静态知识、动态事件、读取绑定与修订相关实现已通过 #272 集成进入 main；“已合并”不代表真实模型的动态语义质量或正式发布流程已经取得产品 GO。**本文件是架构合同，不是进度记录**；当前准确状态、L3 欠账和 CL-M3 下一门见 [PROJECT_STATUS.md](PROJECT_STATUS.md)。

## 0. 为什么需要两套语义

同一个运行时里有两个不同的问题，不能共用一个枚举：

| | 静止态（Static） | 运动态（Motion） |
| --- | --- | --- |
| 核心问题 | 现在知道什么？ | 正在发生什么变化？ |
| 关注对象 | 知识、结论、证据、条件、缺口 | 搜索、阅读、核验、修订、中断、恢复 |
| 时间特征 | 某一版本下成立的状态快照 | 跨时间持续发生的事件与状态变化 |
| 回答能力 | 给出稳定知识、已有证据支持的解释 | 根据新发现修订、补充和撤回结论 |
| 证据权限 | 经核验与发布门禁决定能否正式发布 | 产生候选证据与**修订提议**，不能自行授权 |
| 主要产物 | 可审计的当前答案状态 | 可追踪的研究与修订过程 |

**边界规则（冻结）**：运动态只能**提议**结论变化；静止态的结论必须由当前条件、经过验证的证据与发布门禁共同确定。运动态不得直接写入正式事实。

## 1. 三组互不混用的词汇（`src/web/research/answer_state.py`）

| 组 | 取值 | 回答的问题 |
| --- | --- | --- |
| 内容类型 `CONTENT_KINDS` | `knowledge` / `evidence` / `conditional` / `unverified` | 这条陈述**是什么** |
| 核验结果 `VERIFICATION_STATES` | `supported` / `conflict` / `insufficient` / `pending_verification` / `withheld` | 它**被核到哪一步** |
| 生命周期 `LIFECYCLE_VIEWS` | `current` / `superseded` / `retracted` / `closed` | 它**还能不能作为当前答案被读** |
| 运行状态 `MOTION_STATES` | `planning` / `searching` / `reading` / `verifying` / `revising` / `blocked` / `cancelled` / `completed` | 研究**正在做什么** |

三组之间**没有共享取值**（有测试钉住）。例如：

- 「研究已经完成」≠「结论已被证实」：`research_state.status = completed` 的 run，若没有真实引用，其陈述核验结果是 `pending_verification`，不是 `supported`。
- 「正在核验」≠「现在没有可回答的东西」：`motion = verifying` 时，已 `supported` 的陈述仍在 `current_statements()` 里。

## 2. 静止态快照（`StaticAnswerSnapshot`）

一次快照包含：`run_id` / `turn_id` / `statements[]` / `conditions[]` / `gaps[]` / `research_state` / `content_version`。

- `StatementState`：`reply_id, kind, verification, lifecycle, text, content_version, reason, source_refs`
- `current_statements()`：仍在 `current` 且非 `withheld`/`conflict` 的陈述（可展示）
- `verified_statements()`：其中 `supported` 的部分（可作为已核验结论）
- `gaps[]`：**静止态向运动态提出的补证目标**（`missing_evidence` / `unverified_claim` / `unread_attachment`）——双向反馈的静态端

快照是**只读**的：它读现有 `steering_replies`（`stage`/`citations`/`stale`/`lifecycle`/`analysis_state`/`result_state`），不写任何状态；序列化格式 `static-answer-v1`。

## 3. 修订提议与状态转换（`src/web/research/answer_revision.py`）

修订只有四种动作，**不可合并为单一 `stale=true`**：

| 动作 | 含义 | 对回复的影响 |
| --- | --- | --- |
| `keep` | 未受影响 | 无变化 |
| `stale` | 尚不能确定是否成立 | `stale=true`，版本递增，仍 `open` |
| `retract` | 不再作为当前结论 | `lifecycle=retracted`，正文追加撤回标记，历史保留 |
| `replace` | 已有足够依据的新内容 | 新正文替换旧正文，旧正文进 `revision_history`，版本递增 |

**`RevisionProposal` 只是提议**，字段：`target_reply_id`、`target_content_version`、`action`、`reason`、`research_revision`、`research_round/notes`、`replacement`、`source_refs`、`strict`、`proposed_by`。

确定性门禁（`evaluate()`）：

1. 目标必须是该回复，且版本必须等于 `target_content_version`（并发写入不被覆盖）；
2. 提议的研究状态 `(round, notes)` 不得**旧于**回复已反映的状态（revision 哈希是身份，不是排序）；
3. `retracted` / `superseded` 是终态：迟到写入不能复活；
4. `replace` 的新正文必须通过普通发布规则（含具体断言无来源 → 拒绝；严格模式必须有来源）；
5. 同一提议重复应用 → 版本已变 → 拒绝（幂等）。

`merge_steering_replies()` 现在把 `retracted` 与 `superseded` 同等保护：迟到的 `open` 快照记 `retracted_reopen`，正文冻结。

## 4. 前端

- `ChatResearchReply.lifecycle` 增加 `retracted`；
- `researchReplies.ts`：`retracted` 与 `superseded` 一样是**单向**的（版本不倒退即可生效），并显示「已撤回，不再作为当前结论」；
- 撤回/过时的内容不再作为当前结论展示，但正文与原因仍可追溯。

## 5. 明确不做

- 不新建第二套事实/回答数据库：复用 `steering_replies`、`AnswerSegment`、版本与合并链。
- 不用字符串包含关系证明语义矛盾：受影响的判定来自**研究状态与条件**，语义判定留给模型提议 + 确定性门禁。
- 不在本轮接运动态（AR-1B）、协调器（AR-1C）、UI 双语义（AR-1D）、真实验收（AR-1E）。
- 不调用付费模型。

## 6. 后续切片（按依赖）

| 片 | 内容 | 依赖 AR-1A 的哪一部分 |
| --- | --- | --- |
| AR-1B | 运动态事件合同（事件种类、因果、阻塞/取消/恢复）+ 事件→提议的接线清单 | `RevisionProposal`、`gaps` 指令 |
| AR-1C | 双语义协调器：事件 → 重判 → 新快照（版本转换规则） | `snapshot_from_replies` + `apply_proposals` |
| AR-1D | UI：可靠答案 + 真实进度 + 局部修订视图 | 前端 `retracted`/`stale` 展示 |
| AR-1E | 真实 DeepSeek/搜索/图片多轮验收 | 全部 |

## 7. AR-1C-3 发布接线（冻结）

### 7.1 读取身份随读取一起落地

一次读取在**发生的那一刻**决定身份，而不是在事件构造时反推：

- `read_id` 由 `(run_id, 规范化 URL, 轮次, 第几次尝试)` 派生，不含时间戳，所以重放得到同一身份而不是孪生事件；
- 第几次尝试来自记录上持久化的 `read_history`（上限 10 条），Deep 路径按 URL 就地覆盖也不会把第二次读取压成第 1 次；
- 状态、轮次、摘录哈希与身份一起写进该次读取，事件、摘要、恢复三处读的是**同一个事实**。

持久化沿用 `WebLookupRepository.checkpoint()` 的单条版本校验 UPDATE：读取记录与事件同批落地，不新增第二套事务。

### 7.2 可读不等于可发布

| 绑定 | 能展示旧引用 | 能承载**新正文** |
| --- | --- | --- |
| 旧式（`url` + 引文 `content_sha256`） | 是 | 否（`binding_not_publication_grade`） |
| 新式（另含 `read_id` + `read_excerpt_sha256`） | 是 | 是 |

理由：展示旧答案时我们只是在复述它当时的引用；写入新正文时我们要回答"这句话来自**哪一次读取**"。答不出来的绑定不能授权发布，但也不清空历史。

### 7.3 冲突 = 模型判断 + 外壳校验

| 步骤 | 谁 |
| --- | --- |
| 取页面并记录说了什么 | 外壳（读取带 `read_id`） |
| 判断两段话**在同一件事上**矛盾 | 模型，必须给出 `claim` |
| 判断矛盾对答案是否重要 | 既有证据质量门 |
| 校验双方都指向真实读取、真实目标、有效版本 | 外壳（`conflict_producer.build_conflict_event`） |
| 执行被授权的修订 | 协调器 |
| 写新措辞 | 模型 |

拒绝码是**具名事实**而不是布尔：`conflict_unexplained`、`old_quote_not_in_reply`、`old_source_not_cited`、`source_not_read` / `read_id_not_found` / `quote_not_in_read`、`same_source`、`quotes_identical`、`read_not_newer`、`target_missing` / `target_not_current`。

**"两页数字不同"不是冲突**：没有 `claim` 一律拒绝。冲突只**撤回**、不**生成**替代正文——冲突的含义是"我们不知道哪边对"，这正好是替换的反面。

`EVIDENCE_CONFLICT` 的撤回权需要 `verified is True` **且** 显式 `target_reply_id`；原先按 `source_refs` 与 `conflicting_urls` 的交集撤回已删除（那让未校验的主张凭一个 URL 就能撤掉答案）。

### 7.4 本轮不做

- 不在切片内调用模型（无付费运行）：`conflict_claims` 由 planner 输出携带，缺失即无行为变化；
- 不新增事件种类（仍是六类）、不新增事件游标、不新增事实库；
- 全量 L3 推迟到 2026-10-22（当日授权：不跑全量），本轮只做聚焦测试与子阶段集成。
