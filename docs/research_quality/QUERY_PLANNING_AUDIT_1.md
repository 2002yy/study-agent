# QP-1A：现有模型查询规划链路审计（2026-10-28）

> 目的：确认生产聊天到底用不用模型做查询规划、调用入口在哪里、预算是什么，
> 以及上一轮 Search-to-Answer 基线究竟测到了哪一层。只读审计，无模型调用。

## 生产调用路径

```text
src/application/runtime_repository.py:225
    get_web_tool_agent() -> PersistentWebToolAgent
src/application/runtime_repository.py:312
    resolve_web_tools = web_agent.resolve
src/tools/persistent_web_agent.py:583
    ResearchSemanticSession(semantic_completion, deadline=..., task_identity=...)
src/tools/persistent_web_agent.py:596
    decision = session.interpret(episode, user_input, history=..., active_task_exists=...)
src/web/semantic_recovery.py:279
    interpret() -> ResearchDecision{intent, subject, unresolved_questions, proposed_queries}
```

即：**聊天里的联网研究确实由模型决定查询**，不是把用户原句直接丢给搜索引擎。

## 现有约束（确定性部分）

| 约束 | 位置 | 值 |
| --- | --- | --- |
| 每个 session 最多 stage 数 | `src/web/semantic_recovery.py:215` | 3（1 次 interpret + 至多 2 次 relevance） |
| 单次调用超时 | 同上 `:224` | `min(5.0, deadline - now)` |
| 上下文上限 | 同上 `:221` | `CONTEXT_CAP` |
| 查询条数 | `interpret()` 指令 | 2–3 条，每条 2–8 个实词 |
| 查询与 RQ 绑定 | `ResearchDecision.parse` | `proposed_queries[].rq_id` 必须是已有 RQ |
| 取消与截止 | `should_cancel` / `deadline` | 由 host 传入 |

## 关键组件与现状

| 组件 | 现状 |
| --- | --- |
| `ResearchSemanticSession.interpret()` | **生产在用**，输出 `proposed_queries` |
| `ResearchSemanticSession.relevance()` | 生产在用；指令已明确「字典页定义与具名对象无关」 |
| `SemanticQueryPlanner` / `plan_queries`（`src/web/semantic_planner.py`） | 仅被自身与测试引用，**生产无调用点** |
| `WebToolAgent.search`（`src/tools/web_agent.py:407`） | 把调用方传入的 `query` 直接交给 `gateway.search_detailed`，无规划 |
| `query_normalizer` | 归一化/变体，不抽取实体或关键词 |

## 与 Search-to-Answer 基线的关系（测量边界）

上一轮基线（`SEARCH_TO_ANSWER_BASELINE_1.md`）是**直接调用 `gateway.search_detailed(用户整句)`**，
没有经过 `PersistentWebToolAgent`，也没有模型参与。因此它测到的是：

- **网关在原始整句下的下限**（Bing 退化为单词匹配、DDG 表现更好）；
- 不是「生产模型规划器生成的查询质量」。

结论修正：**基线证明的是「网关不会自己改写查询」，不能证明「生产规划器失效」。**
生产规划器的真实查询质量目前**未被测量**——这正是 QP-1C 要回答的问题。

## 对 QP-1B 的直接含义

现有指令已经具备：2–3 条短查询、2–8 实词、RQ 绑定、优先官方、使用 `as_of_date`。
本次只改三处语义要求，不改 schema、解析、预算或调用方式：

1. **实体锚定**：查询必须保留用户点名的作品/角色/型号/版本；
2. **任务焦点**：保留「配装 / 对比 / 自动战斗 / 版本说明」等意图词；
3. **官方域条件化**：`site:` 仅在「该事实由该发布方拥有且域名已知」时使用；
   社区知识（配装、打法、实战）改为检索社区与实测来源。

第 3 点针对的正是基线里暴露的形态：用官方站回答社区经验问题，会拿到官网首页而不是攻略。

## 非范围

- 不新增 `SemanticQueryPlanner` 的生产接线；
- 不改 `ResearchDecision.parse`、RQ 冻结规则、任务身份或调用预算；
- 不改 `GeneralWebGateway` 的检索与读取实现。
