# 连续 Agent 对话 — 开发交接（Continuous Agent Handoff）

> 唯一职责：记录「连续 Agent 对话」方向的开发交接事实与缺口。
> **不**替代 `docs/PROJECT_STATUS.md`、`tests/stage_gates.json` 或任何既有发布门；不在此维护阶段状态机。
> 最近更新基线：`codex/conversation-continuous-p0p1` @ `20af1d99`（未合并 main）。

## 0. 三条冻结规则

1. **不得把离线验证写成生产验收通过。** 本文件记录的测试、SQLite、模拟网关与浏览器回归都是**离线/桩件**证据。真实模型与搜索提供商的端到端资格验证尚未进行，不得据此宣称生产可用或可合并。
2. **不得把六项能力的目标缩水成三个阶段 UI 开发。** Rev 3 与 Slice A 只是阶段性交付；六项能力（智能对话 UI、研究开场、边搜索边讲、中途补充不打断、多模态输入、Agent 工具执行）是整体目标，缺一不可。
3. **语义不得混淆。** `applied` = 约束已进入权威计划（`incorporated_in_round`），**不代表**追加任务已完成；`executing` 必须由真实搜索/读取/计算动作（`executed_in_round`）支撑，否则不得显示。

## 1. 产品目标

连续对话要真正承载完整 Agent 行为，六项能力缺一不可：

1. **智能对话 UI**：动态、可信数据驱动的组件（非静态排版）。
2. **研究开场**：Agent 交代研究方向，且与真实计划一致。
3. **边搜索边讲**：真实搜索/阅读/补查/分段事件进入同一对话流。
4. **中途补充、不打断**：后端执行、增量预算与恢复闭环。
5. **多模态输入**：附件基础设施统一到聊天输入区。
6. **Agent 工具执行**：受限 Python 计算与动态图表。

Rev 3（UI 整合）与 Slice A（连续研究运行时接线）只覆盖其中一部分。

## 2. 当前基线

| 项 | 值 |
| --- | --- |
| 分支 | `codex/conversation-continuous-p0p1` |
| 工作树 | `D:/study-agent-validation/conversation-continuous-p0p1` |
| main 基线 | `335fc9b7875b848f202122362f2e0f8b5a9db0ee` |
| 提交 1 | `3ff9e15ed432aab77e2cedcbb96d0dfaff7eaee3` feat(ui): integrate continuous research conversation timeline |
| 提交 2 | `b9bae33a` feat(research): durable mid-run steering, incremental budget and follow-up queue |
| 提交 3 | `20af1d99742b9ab6d800445afd11d1f494368dd2` fix(research): separate applied from executing and label queued tasks as pending-send |
| 提交 4 | `184ab1782ebe997bbaf35c87e24d35853d89d5b8` feat(ui): integrate #229 IME and scroll safety; add continuous-agent handoff |
| 提交 5 | Slice B（隔离执行器 + 计算协议 + 交互图表）；SHA 见该提交本身 |
| 远端 | `origin/codex/conversation-continuous-p0p1`；**无 PR** |
| 工作树状态 | 见写入本文件时的 `git status`；本文件随下一次实质开发提交一起推送 |

## 3. 已实现（按证据）

- **连续对话 UI（Rev 3）**：研究状态只保留对话内一处（`AnswerProgress` 挂在 assistant 消息），`ChatResearchRecovery` 在状态已内联时不再重复全局状态条；补充回执、下一轮任务卡、研究正文同属一条对话流；输入区收敛为「调整当前研究 / 完成后再做」，发送与停止独立；搜索过程默认折叠。
- **Deep 中途转向**：`_deep_consume_steering` → `steering_plan.revise_deep_plan` 在安全检查点修订计划；`effective_query` 生效；受限语义（来源限制、Python、任务替换、措辞调整）显式拒绝而非静默当关键词。
- **补充 ID 幂等**：`request_id` 去重；同 ID 不同内容拒绝；取消中拒绝接收。
- **队列持久化**：`conversation_queue` 落 SQLite，`merge_queued_followups` 防陈旧 checkpoint 覆盖；`pending_followups` 以「完成且匹配 turn」判定交付，未确认交付重启后不重复执行。
- **增量预算**：`incremental_budget` 由部署策略经环境变量 `WEB_RESEARCH_STEERING_BUDGET_POLICY` 显式启用（无常量/百分比默认）；按 `steering_id` 幂等授权，复用既有任务不重复发放；不重置计数器。
- **真实执行状态**：`research_interaction.deep_steering_status` 严格区分 `pending / applied / executing / late`。
- **补充≠证据**：`steering_answer_instruction` 以 `authority=user_task_requirements_not_evidence` 注入回答指令；`evidence_tool_calls` 不将其计为证据。
- **撤销影响面**：关键词纠正（「不是 X，是 Y」）只淘汰受影响证据（归档 `superseded_notes/superseded_sources`），保留其余有效资料。
- **前端**（Rev 3）：`api.ts`/`chatController.ts`/`types.ts`/`WorkspaceView.tsx`/`ChatPanel.tsx`/`AnswerProgress.tsx`/`ChatResearchRecovery.tsx`/`researchApproach.ts` + 新增 `e2e/conversation-continuous.spec.ts`、`playwright.conversation.config.ts`。
- **Slice B 后端**：
  - `src/tools/python_isolation.py`：Docker 硬化执行器（`--network none`、`--read-only`、`--tmpfs` 限额、`--memory/--cpus/--pids-limit`、`--cap-drop ALL`、`--security-opt no-new-privileges`、非 root、nofile 限额），独立 watchdog 超时后 `docker rm -f` 终止整个执行单元；**隔离不可用即 fail-closed**，绝不回退宿主 Python。
  - `src/tools/computation.py`：权威结果协议（`schema_version/run_id/tool_run_id/status/input_revision/source_refs/engine/result`），非法图表数据（越界、非有限数、错列、嵌套）在服务端拒绝。
  - `src/tools/deterministic_compute.py`：受控算术/统计解释器（AST 白名单，**不使用 `eval/exec`**，禁属性/下标/导入/语句/推导式），可离线确定性计算。
  - `src/tools/compute_tools.py`：在既有 `ToolRegistry` 上注册 `deterministic_compute` 与 `isolated_python`；两者都返回绑定身份的协议信封，由既有 `ToolService` 持久化与审计。
  - 预算接线：`incremental_budget.load_incremental_policy(python_isolation_available=...)`；`python_runs` 仅在真实隔离运行时可用时开放，**未删除原有保护条件**。
  - **研究路径接线（有界工具决策）**：`src/web/research/computation_step.py` 只接受声明式计算请求（拒绝自由代码）；Deep 执行器在每轮 `revise` 的 `compute` 判定处调用 `_deep_apply_computation`，绑定 `run_id/tool_run_id/input_revision/source_refs`（来源取自本轮实际使用的笔记），结果落 `deep["computations"]`（上限 20）；请求 `isolated_python` 而隔离不可用时记为 `blocked`，**绝不降级为确定性计算**。
  - **`computation` SSE 发射**：`chat_routes._latest_computation` 只透出已绑定的权威信封（不泄露内部 `round/at`），研究进度循环按 `tool_run_id` 去重后发出 `computation` 事件。
- **Slice B 前端**：`types.ts` 的 `ComputationPayload`、`features/answer-ui/computation.ts`（客户端镜像校验）、`InteractiveComputation.tsx`（柱状/折线/数据表切换，保留单位/来源/版本，参数变更触发**服务端**重算，过期结果标记 stale 不回写）；`api.ts`/`chatController.ts` 新增 `computation` SSE 事件通道；`ChatPanel` 在消息内渲染。不执行任何模型提供的 HTML/JS/回调。

## 4. 验证事实（离线，命令可复现）

工作树 `D:/study-agent-validation/conversation-continuous-p0p1`；Python 解释器用主工作树 venv。

| 范围 | 命令要点 | 结果 |
| --- | --- | --- |
| Ruff | `python -m ruff check <changed files>` | PASS |
| mypy baseline | `python -m mypy --explicit-package-bases src/` + `python tools/check_mypy_baseline.py --log <log> --baseline config/mypy_baseline.json --outcome failure` | current=122, baseline=128, **NEW=0**（resolved 6） |
| 后端影响集 | `pytest tests/test_research_steering.py tests/test_research_interaction.py tests/test_incremental_research_budget.py tests/test_web_lookup_deep_research.py tests/test_web_lookup_run.py tests/test_web_lookup_research_contract.py tests/test_research_answer_streaming.py tests/test_chat_research_run_owner.py tests/test_persistent_web_agent.py tests/test_chat_service.py tests/test_research_follow_up.py tests/test_research_recovery.py tests/test_active_research_runtime.py tests/test_standard_research.py -q` | **259 passed**（~4m15s） |
| 前端单测 | `frontend: npx vitest run src` | **494 passed / 112 files** |
| 前端类型/构建 | `npx tsc -b`；`npm run build` | PASS |
| 连续对话 E2E | `npx playwright test --config=playwright.conversation.config.ts` | **2 passed × 2 视口**（含 Slice B 计算卡片、数据表切换、来源/版本） |
| 全量 fixture E2E | `npx playwright test` | **79 passed**（chromium/mobile/narrow + firefox + webkit） |
| 手工断言 | E2E 内含 `streams==1`、`queue==1`、`steering==[两条]`、无横向溢出、无重复全局状态条 | PASS |
| Slice B 后端 | `pytest <见上> -q` | **320 passed, 0 skipped**（隔离运行时可用时；含 6 项真实容器负控与 2 项 Deep→真实隔离 Python 端到端） |

### Slice B 真实隔离安全验收（2026-10-15，本机 Docker Desktop / Linux 容器）

- 镜像固定：`python@sha256:57cd7c3a7a273101a6485ba99423ee568157882804b1124b4dd04266317710de`（本地已存在，未静默拉取），经 `STUDY_AGENT_PYTHON_IMAGE` 指定。
- 命令：`pytest tests/test_python_isolation.py -q -rs` → **11 passed（0 skipped）**；`pytest tests/test_web_lookup_deep_research.py -q -rs` → **18 passed（0 skipped）**。
- 覆盖并通过：正常隔离计算；宿主专有文件不可读且宿主环境变量未继承；外部网络请求失败；无限循环超时被杀；无限内存被 `--memory` 限制；无限输出被读时限流并可截断。
- 修复项（本轮）：① 宿主隔离负控改用宿主专有标记（不再用容器自带的 `/etc/passwd`）；② 运行输出改为**读时限流**并终止越界写入单元，不再先整体缓冲；③ 生产接线默认使用环境解析的 runner（非 `NullRunner`），且 `isolated_python` 的代码由**服务端从声明式请求生成**（模型不提供代码）；④ `python_runs` 改为**执行尝试**即占用（失败/超时计入，隔离不可用而未启动不计）。

> 隔离运行时的真实负控（宿主文件/网络/内存/无限循环/输出上限）只有在可用 Docker/WSL2 时才会执行；当前本机 Docker 守护进程未运行，故**未通过**，且未用宿主进程凑数。

> 这些是**离线桩件**证据（脚本化 gateway / 内存+SQLite / 模拟 SSE），不是真实 provider 生产验收。

## 5. 尚未验证（合并门阻塞项）

- **真实搜索提供商**：修改关键词后实际查询是否改变、来源质量与补查是否真的发生。
- **证据复用**：有效资料保留、失效资料退出结论来源（当前仅脚本化验证）。
- **动态预算**：按真实新增工作扩容、补充 ID 幂等（仅在脚本化流程验证）。
- **状态一致性**：UI、SQLite、实际执行轨迹三者吻合。
- **真实模型自主工具选择**与研究质量（需额度恢复后）。
- **连续输出**：开场、工具过程、研究结果在同一对话的真实链路（当前为桩件）。
- **Slice B 隔离执行**：真实容器负控**已通过**（见 §4 安全验收）。计算工具接线已通（Deep 执行器按 planner 有界 `compute` 判定调用，服务端生成隔离程序，结果落库并经由 `computation` SSE 透出）。仍是脚本化 planner 驱动“Agent 何时计算”的决策，真实模型自主决策质量留待额度恢复。

## 6. 兼容性债务

- **#229 已逐项提取（提交 4）**：`composingRef` 组合生命周期守卫、会话切换 `setIsAtBottom(true)`、`正在生成 · 回到最新` 文案及 3 个测试均已进入 Rev 3。PR #229 本身仍未合并，合并门需确认其收口方式。
- **#224 独立产品质量工作线**：与本方向分离，本分支不得混入。
- 既有 UI 分支 `codex/conversation-first-ui`（Rev 2，基于旧 main）与 `codex/reading-notebook-ui`（RP-1）不属于本分支范围。

## 7. 下一阶段

- **Slice B 收尾**：把 `deterministic_compute`/`isolated_python` 接入 Deep 研究工具路径（Agent 在有界决策中选择计算工具）、后端发射 `computation` SSE、并用真实容器跑通负控。
- **Slice C — 统一多模态输入**：附件基础设施统一到聊天输入区。
- 之后进行**六项能力一起工作的完整真实任务验收**。
- 无需等额度重置：工具协议、结构化图表、前端渲染、模拟流程均可先离线实现；真实模型自主工具选择、研究质量与真实容器执行留待环境/额度就绪后验收。

### Python 安全边界（冻结）

| 项目 | 决定 |
| --- | --- |
| 工具注册与审计 | 复用 `ToolRegistry` / `ToolService` |
| Python 执行 | 独立操作系统级隔离容器（优先 Linux 容器） |
| 网络 | 执行容器无网络（`--network none`） |
| 文件系统 | 不挂载仓库/凭据/主机目录；根文件系统只读 |
| 临时数据 | 仅容器内有上限的 tmpfs |
| CPU/内存/进程 | 操作系统级硬限制 |
| 超时与取消 | 独立 watchdog，超时终止整个执行单元 |
| 可用库 | 固定镜像、固定版本、按需白名单 |
| 隔离不可用 | Fail closed，绝不回退宿主 Python |
| 确定性计算 | 受控解释器（禁 `eval/exec`），且不冒称完整 Python |

## 8. 合并门（出现以下证据前不得合并）

| 验收项 | 要求 |
| --- | --- |
| 真实转向 | 修改关键词后，实际查询改变（真实 provider） |
| 证据复用 | 已有有效资料保留，失效资料退出结论来源 |
| 动态预算 | 根据新增工作扩容，补充 ID 幂等 |
| 连续输出 | 开场、工具过程、研究结果处于同一对话（真实链路） |
| 状态一致性 | UI、SQLite、实际执行轨迹吻合 |
| `applied`/`executing` | 严格区分；`executing` 有真实工具动作支撑 |
| #229 兼容 | IME 组合生命周期、滚动锁、对应测试全部补入 Rev 3 |
| 桌面与移动端 | 单测、真实栈 E2E、滚动与停止行为通过 |
| 门禁 | 精确 head 的 required CI 绿；不沿用旧 head 绿灯 |

> 在本文件记录的事实之外，不得宣称 Slice A 或整个前后端方案已经可以合并。
