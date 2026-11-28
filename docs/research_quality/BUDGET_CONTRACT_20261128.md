# 研究预算契约（2026-11-28）

基线：`main@15f42bd2` 之后的本轮修改。目标不是取消费用控制，而是把
「防止模型失控」和「让模型有足够决策机会」分开。

## 1. 三层预算

| 层 | 内容 | 是否硬边界 |
| --- | --- | --- |
| 第一层：不可突破 | 用户授权费用账本、安全/权限、用户取消、最大运行时间 | 是 |
| 第二层：宽松失控保护 | 模型轮数、工具次数、搜索/读取次数、重复调用 | 否，达到后收尾 |
| 第三层：模型判断 | 证据是否足够、缺口是否闭合、下一步价值 | 由模型决定 |

费用账本仍是唯一的硬费用边界：每个付费请求在发出前执行 `reserve_call()`，
按最坏情况预留；研究调用次数放宽不会让请求绕过账本。

## 2. 实际生效的额度

### 2.1 自主研究（本轮的数值）

| 限制 | 普通 | Deep |
| --- | --- | --- |
| 研究模型调用 | 12 | 30 |
| 研究轮数 | 12 | 30 |
| 搜索 | 12 | 30 |
| 阅读 | 20 | 60 |
| 工具总次数 | 40 | 120 |
| 研究时间 | 300s | 1800s |
| 单轮规划输出 | 4096 tokens | 4096 tokens |
| 最终答案输出 | 8192 tokens | 16384 tokens |
| 最终答案时间预留 | 180s | 180s |
| 最终答案费用预留 | 按价格/上下文/输出上限动态计算 | 同左 |

环境变量仍可单独覆盖：`WEB_AUTONOMOUS_MAX_*` 与
`WEB_AUTONOMOUS_DEEP_MAX_*`；上限分别放宽到 60/60/60/80/200/3600。
最终答案费用预留默认用 `reservation_cny()` 按实际价格、保守的 60k 字符答案上下文
和 8k/16k 输出上限计算；`WEB_AUTONOMOUS_ANSWER_RESERVE_CNY` /
`WEB_AUTONOMOUS_DEEP_ANSWER_RESERVE_CNY` 可显式覆盖。它是研究循环的**停止阈值**，
不是预扣款：实际扣款仍由 `reserve_call()` 在每次请求前按最坏情况预留。

### 2.2 全 turn 模型调用上限

旧的 `research + answer generation > 6` 硬编码已移除。新上限是
`RESEARCH_TURN_MAX_MODEL_CALLS`，默认 **64**，允许 8–256。它只是防止循环
写坏的护栏，不是研究预算：

- 自主普通：12 研究 + 1 回答 + 最多 2 次 binder ≈ 15；
- 自主 Deep：30 + 1 + 2 ≈ 33；
- 仍低于 64。

### 2.3 普通语义研究

| 模式 | 时间 | 读取 | 查询 | 字符上限 |
| --- | --- | --- | --- | --- |
| Lookup | 60s | 3 | 2 | 16k |
| Standard | 300s | 20（8 基础 + 12 恢复） | 12 | 48k |

Standard 的 `finalization_reserve` 是 15s：搜索/读取在答案窗口前停止。

### 2.4 RQCE Deep

本轮**未改** RQCE 的冻结 profile：`max_candidates=40`、`max_reads=12`、
`soft_timeout=450s`、`hard_timeout=600s`、`max_total_chars=80k`。它与自主
Deep 是两条不同的预算契约；把 RQCE 一并放宽到 1800s/60 reads 会改变
`DeepExecution` 的持久化 envelope 和现有验收测试，需要单独决策。

### 2.5 通用 web tool fallback

`_web_tool_total_budget()` 仍为 120s、`WEB_TOOL_MAX_ROUNDS` 3 轮。它是
非自主的短流程 fallback，不是 Deep 研究循环；本轮未改。

## 3. 达到限制后的行为

| 停止原因 | 行为 |
| --- | --- |
| 模型调用预算 | 返回已有证据，进入答案生成 |
| 搜索/读取/工具配额 | 该工具返回 `budget_exhausted`，模型仍可用其他工具或总结 |
| 时间上限 | 停止新工具，保留已读证据 |
| 费用预留不足 | `spend_reserve`：在吃掉最终答案费用前停止研究 |
| 无进展/重复 | 重复查询返回 `duplicate_query`；重复读取返回缓存正文（`cached: true`），不消耗阅读额度 |

重复保护只阻止完全相同的查询（含 site_key）和同一有效读取请求；读取身份包含
URL、章节锚点、读取模式、视频时间段、OCR、评论页码、讨论开关和 `max_chars`。
重复读取返回缓存正文（`cached: true`），不是错误；更深的 `max_chars`、不同章节、
不同视频段、开启 OCR、翻评论页都允许再次读取。失败读取仍可重试。

## 4. 与成熟 Agent 的对照

- **Codex** `065e18b0` `codex-rs/core/src/session/turn.rs` L737–925：
  上下文接近上限时先压缩再继续，而不是直接结束；模型准备结束才走 Stop hook。
- **OpenCode** `eeeeaa0d` `runner/llm.ts` L263–282：`steps` 只有配置了才生效；
  达到步数后 `toolChoice:"none"`，要求总结已完成/未完成/下一步。
- **DSH** `4b399c39` `agent-loop/src/agent.ts` L330–425：核心循环只负责
  执行与后续输入，外层策略决定预算；社区出现过长轮次高消耗案例，说明外层
  预算仍必要。
- **Claude Code / Agent SDK**：核心源码未公开；官方文档区分单次输出、
  任务 token 预算和 SDK 轮数/费用限制，并提示预算过小会让模型缩小任务范围
  或提前停止。本仓库按此原则把预算从“每次研究 4/5 次”放宽到“12/30 次”，
  同时保留费用硬边界；不声称审查了其内部循环源码。

## 5. 验证

- 预算契约测试：`test_autonomous_research.py`、`test_agent_boundaries.py`、
  `test_llm_tool_loop_continuation.py`、`test_research_recovery.py`、
  `test_chat_research_publication.py`、`test_semantic_recovery.py`。
- 影响集 **231 passed**；Ruff 干净；mypy baseline 112/125 通过。
- 免费验证：旧 `research_model_call_budget_exhausted` 在 6 次时不再触发；
  默认 64 次才触发；自主普通/Deep 的提示词、轮数、搜索/读取/工具/时间均已
  按新值断言。
- 无付费调用；账本未变化。

## 6. 已知限制

1. 这些数值是**本轮建议的安全上限**，不是实测最优值；真实成本与质量曲线仍
   需要三类任务的端到端实验。
2. 费用预留按 CNY 估算，依赖账本 pricing；没有 experiment cap 时只做调用
   与时间预留，费用由 `reserve_call` 硬限制兜底。
3. RQCE Deep 与通用 web tool fallback 仍是旧额度；本轮只统一了全 turn 上限，
   没有强行把三条路径改成同一组数字。
4. 重复查询保护是精确匹配；改写后的同义查询仍会消耗搜索额度，是否语义去重需要
   真实样本再决定。重复读取按有效参数区分，不做语义去重。
