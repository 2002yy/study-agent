# Async Deep-1 — 可恢复异步 Deep Research（冻结设计合同）

> 状态：**Proposed / Frozen for review**。本文件只描述设计与验收，不含实现。
> 基线：`codex/conversation-continuous-p0p1` @ `4ffa4452`。
>
> **重要**：原冻结的 A/B/C 验收门**继续保持 FAILED**。本文件不是把 A 的失败改成通过，
> 而是提出一项**新的产品契约**（异步长任务）及其**独立验收标准**。在新标准被正式批准、
> 或原标准真正通过之前，合并门保持关闭。

## 0. 要回答的两个问题（分开处理）

| 类别 | 问题 | 归属 |
| --- | --- | --- |
| **架构** | 一次研究超过五分钟，是否就必须被迫结束？ | **本文件（Async Deep-1）** |
| 性能 | 为什么平均单页读取约 44 秒，能否更快？ | 独立路线（本文件**不**重写 Reader） |

冻结的实测依据（`RESULT.md` §11）：一次 run 的 198.8 s 中，成功读取 67%、检索与失败读取 26%、
模型仅 6%，**单次成功读取约 44 s**。因此仅把上限从 195 s 提到 270 s 无法消除不确定性。

## 1. 代码级梳理：已有机制与缺口

### 1.1 可直接复用（**不**重造研究框架）

| 能力 | 现有实现 | 复用方式 |
| --- | --- | --- |
| 持久 run + 检查点 | `WebLookupRepository.checkpoint(...)` 已持久化 `research_context`（plan / notes / steps / steering / computations / incremental_budget）、`query_attempts`、`selected_sources`、`rejected_sources`、`items`、`warnings`、`stop_reason` | 恢复所需的**事实已经在库里**，无需新 schema 存研究状态 |
| 执行租约/身份 | `WebLookupService.begin_tool_trace(run_id) -> operation_id`；`cancel_requested(run_id, operation_id)`；`finish_cancel` | 作为「谁在执行这个 run」的权威身份与取消通道 |
| 协作式取消 | 执行器 `ensure_active()` 每步检查取消；`cancel_owned_by_turn(turn_id, wait_seconds)` | 显式“停止”立即进入既有取消流程 |
| 后台触发 | `DeepTriggerRunner`（启动扫描 + `SCAN_INTERVAL_SECONDS=15` 重扫、单 worker、keyset 分页）+ `DeepTriggerRepository.discover(...)` | **异步执行的调度底座**（Deep-3T 已具备） |
| 续跑服务 | `DeepContinuationService.continue_pending(...)`、`StandardContinuationService` | 恢复入口 |
| 陈旧操作回收 | `RuntimeRepository.recover_stale_operations(...)` | 进程重启后回收未结算的 operation |
| 转向/预算/计算 | `steering_plan`、`incremental_budget`（`grant` 幂等、`consumed` 不复位）、`computation_step` + 工具注册表 | 原样保留 |
| 视觉/费用拦截 | `attachment_vision` 与 `llm_client` 的单点 `llm_spend_guard` | 保留单点拦截，改为**持久账本**（见 §3.2） |

### 1.2 缺口（本设计要解决的）

| # | 缺口 | 现状 |
| --- | --- | --- |
| G1 | 研究执行与 HTTP/SSE 连接耦合 | 准备工作在请求生命周期内同步跑；断开即取消（`chat_routes` 准备轮询 → `cancel_owned_by_turn`） |
| G2 | 没有“长任务授权”概念 | 只有“本轮对话”，断开即等于放弃 |
| G3 | 费用账本进程级 | `llm_spend_guard` 的 `_reserved_cny` 是进程内存，重启归零 |
| G4 | 同 run 无显式互斥 | 触发器单 worker，但“手动恢复 + 定时扫描”可能并发进入同一 run |
| G5 | UI 无断线重连与异步状态 | 前端只按 SSE 流渲染，断线后无法重新附着 |
| G6 | 运行状态词表不含“暂停/等待” | `WebLookupRun.status ∈ {pending,running,partial,completed,failed,cancelled}` |

## 2. 冻结设计契约（Async Deep-1）

### 2.1 运行生命周期：run 与连接解耦

- 一次研究在**创建时**获得一个持久 run（现有 `WebLookupService.create`）；执行由**后台 worker**推进，
  不再依赖某个 HTTP 连接存活。
- HTTP/SSE 降级为**只读观察者**：订阅已有 run 的进度与增量，不驱动执行。
- 允许三种进入方式：交互式创建（默认即时轮询观察）、断线后重连观察、重启后由触发器发现并继续。
- **不新增研究框架**：执行仍由 `WebLookupService.execute/续跑路径` 完成，触发器只负责**唤醒**。

### 2.2 持久恢复：恢复依据

恢复时必须能重建：已完成搜索（`query_attempts`）、已读正文（`selected_sources` + notes）、
计划与状态（`deep.plan/steps/round_index`）、**未执行转向**（`steering[k].executed_in_round is None`）、
**计算版本**（`deep.computations[k].input_revision/status`）、**预算账本**（`incremental_budget`）、
以及该 run 的费用预留（见 §3.2）。

### 2.3 恢复执行：已完成工作不重复

- 恢复**不得**重跑已完成的搜索/读取：以 `query_attempts` 与 `selected_sources` 为事实，仅补齐
  `status == "pending"` 的计划任务与 `executed_in_round is None` 的转向任务。
- 计算按 `input_revision` 幂等：同一版本已有 `succeeded` 结果时不重复执行；仅在参数版本变化时重算。
- 恢复**不重置** `incremental_budget.consumed`（现有语义），也不重新发放初始额度。

### 2.4 预算与授权：暂停/恢复后仍可核对

- 研究的三类边界在暂停/恢复后必须一致可核对：
  1. **墙钟**（`incremental_budget.wall_seconds` 的授权与消耗，跨恢复累加）；
  2. **调用次数**（`model_calls/searches/reads` 的 `authorized` 与 `consumed`）；
  3. **费用**（§3.2 的持久预留）。
- **长任务授权**是显式的、有界的：授权时固定 `deadline`、`max_model_calls`、`max_spend_cny`；
  三者任一耗尽即进入**暂停**（不是失败）：保留 run、证据与待执行任务，状态如实显示。

### 2.5 UI：断线重连与真实状态

- **重连**：会话重开后按 run 身份取回进度（沿用 `GET /sessions/{id}/research-queue` 思路，
  新增/扩展为按 run 读取进度 + 最近的 steering/computation 事件）。
- 状态词表（新增，映射自既有事实，**不伪造**）：
  `running`（正在搜索/读取）、`waiting`（等待下一轮或等待授权）、`paused`（触及边界，可恢复）、
  `partial`（已有可用证据但未完成）、`completed`、`failed`、`cancelled`。
- 断线后页面必须能显示「研究仍在进行 / 已暂停 / 已完成的部分」，而不是清空成“未开始”。

### 2.6 安全与并发

- **同一 run 只能有一个执行者**：以 `operation_id` 作为租约；worker 在进入执行前必须成功
  `begin_tool_trace`（或等价的 CAS 获取）才能推进，杜绝“触发器 + 手动恢复”双跑。
- 进程重启：`recover_stale_operations` 回收陈旧租约后才允许重新接管。
- **取消优先**：任何时刻显式“停止”写入取消事实，执行器在下一步 `ensure_active()` 退出；
  取消后**不得**再发起付费调用（见 §3.1 的负控）。

## 3. 两条硬约束

### 3.1 断线 ≠ 取消，也 ≠ 无限授权

现状：前端断线会在准备阶段触发取消（`chat_routes` 轮询 → `cancel_owned_by_turn`；已有零费用回归
`tests/test_stream_disconnect_cancels_research.py`）。

冻结规则：

| 事件 | 即时交互模式 | 长任务模式（用户显式授权） |
| --- | --- | --- |
| 连接关闭 | **取消**（保持现状） | **不取消**：run 转入后台，受 `deadline`/调用次数/费用三重边界约束 |
| 显式“停止” | 立即取消 | 立即取消（更高优先） |
| 服务器重启 | — | 触发器发现并**恢复**；租约回收后才接管 |

关键：长任务不会因为浏览器关闭而无限延长——它只有**预先授权的那一份**边界。

### 3.2 费用账本必须持久化（当前是进程级）

现状：`src/llm_spend_guard.py` 的预留额是**进程内存**；恢复语义一旦引入，重启即归零，
等价于重新发放 ¥10。

冻结方案（设计级）：

1. **预留即落库**：每次付费调用前，以 `(scope_id, call_id)` 为键写入一条**预留记录**
   （`scope_id` = run/turn 身份，`call_id` = 幂等键），包含估算上界与时间。
2. **幂等扣额**：同一 `call_id` 的重复预留不重复计入；调用结束后以实际用量**只在首次**结算
   （或按“预留不退还”的现有保守策略保留）。
3. **权威剩余额度**：`剩余 = 授权上限 − Σ(该 scope 的预留+结算)`，**从库读取**，进程内存只作缓存。
4. **恢复不重发**：恢复运行时读取该 scope 的既有预留，不重置、不叠加新的 ¥10。
5. **fail-closed 不变**：配置了上限但缺少价格 → 拒绝调用；跨进程一致。
6. 存储：新增一次 SQLite 迁移（下一个可用版本号），只增**账本表**，不改研究状态表。

## 4. 最小影响文件清单（实现阶段预计）

| 层 | 文件 | 变更性质 |
| --- | --- | --- |
| 执行与检查点 | `src/application/web_lookup_service.py` | 执行入口可被后台唤醒；暂停/恢复语义；不重跑已完成工作 |
| 编排 | `src/application/deep_trigger.py`、`src/repositories/deep_trigger_repository.py` | 复用为主；增加“长任务授权”候选的发现条件 |
| 续跑 | `src/application/deep_continuation.py` | 复用；补齐“未执行转向/未完成计算”的继续条件 |
| 路由 | `src/api/routes/chat_routes.py`、`src/api/routes/web_lookup_routes.py` | 断线不再无条件取消（仅在非长任务模式）；新增按 run 的进度订阅端点 |
| 准备路径 | `src/application/chat_service.py`、`src/application/policy_chat_service.py`、`src/tools/persistent_web_agent.py` | 长任务模式下**不再同步等待**研究完成，改为派发 + 观察 |
| 费用 | `src/llm_spend_guard.py` + 新迁移 | 进程账本 → 持久预留账本（§3.2） |
| 前端 | `frontend/src/features/chat/chatController.ts`、`single-chat/ChatPanel.tsx`、`answer-ui/AnswerProgress.tsx`、`api.ts` | 重连、状态词表、暂停/恢复入口 |
| 文档/验收 | `docs/ASYNC_DEEP_1_CONTRACT.md`（本文件） | — |

**明确不做**：不重写 Reader/抓取链路（性能另立路线）；不改 Evidence Gate、计算工具语义、
角色切换、学习状态权威。

## 5. 负控矩阵（实现阶段必须通过）

| # | 负控 | 期望 |
| --- | --- | --- |
| N1 | 连接关闭（长任务模式） | run **继续**，且不超过授权 deadline/调用数/费用 |
| N2 | 连接关闭（即时模式） | 保持现状：取消，不再发起付费调用 |
| N3 | 显式“停止” | 立即取消；取消后 0 付费调用 |
| N4 | 进程重启 | 触发器发现并恢复；**不重复**已完成搜索/读取 |
| N5 | 恢复时的费用 | 剩余额度取自持久账本；**不重新发放**授权额度 |
| N6 | 双执行者并发 | 第二个执行者被租约拒绝（同一 run 不双跑） |
| N7 | 恢复后遇到未执行转向 | 该转向被继续执行或如实标记未执行；不伪造完成 |
| N8 | 授权边界耗尽 | 进入 `paused`，保留证据与待办；用户可恢复 |
| N9 | 同一计算版本重复恢复 | 计算幂等，不重复执行 |
| N10 | 预算账本损坏/缺失 | fail-closed：暂停并如实报告，不默认无限 |

## 6. 两层验收标准（拟议；需正式批准）

| 模式 | 标准 | 与原 A/B/C 的关系 |
| --- | --- | --- |
| **即时交互验收** | 300 s 内能：启动研究、展示**真实**进度、接受补充、给出明确状态；**未完成不得谎称成功** | 原 A 场景在此模式下的**通过条件仍按原标准**（新参数触发新计算等）；未达到就继续 FAILED |
| **异步完整任务验收** | 在**另行授权**的总时间与费用上限内完成：搜索 → 补查 → 重算 → 图表，且**可从持久状态恢复**、断线不丢、重启不重跑、费用不重发 | 需独立用例与独立授权；**不用于**把原 A 的 FAIL 改判 |

## 7. 未决问题（交 Operator）

1. 长任务授权的默认上限（墙钟/调用数/费用）取值，以及在 UI 中如何显式授权？
2. `paused` 是新增枚举，还是复用 `partial` + 说明？（影响既有状态消费方）
3. 费用账本的 `scope_id` 粒度：按 run、按 turn，还是按会话？
4. 异步完整任务验收的**时间与费用上限**由谁定、按什么依据？
5. 性能路线的优先级：来源优先级 / 单页读取超时 / 证据复用（本文件不覆盖）。

## 8. 非目标与边界

- 本文件**不**改变研究质量门、Evidence Gate、预算语义、学习状态权威或角色系统。
- 本文件**不**声称原 A/B/C 已通过；合并门继续关闭，直到新标准获批或原标准真正通过。
- 本阶段**不**修改生产代码、不申请付费模型调用、不跑 L3、不创建 PR。
