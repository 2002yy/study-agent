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
| 远端 | `origin/codex/conversation-continuous-p0p1` = `20af1d99`；**无 PR** |
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

## 4. 验证事实（离线，命令可复现）

工作树 `D:/study-agent-validation/conversation-continuous-p0p1`；Python 解释器用主工作树 venv。

| 范围 | 命令要点 | 结果 |
| --- | --- | --- |
| Ruff | `python -m ruff check <changed files>` | PASS |
| mypy baseline | `python -m mypy --explicit-package-bases src/` + `python tools/check_mypy_baseline.py --log <log> --baseline config/mypy_baseline.json --outcome failure` | current=122, baseline=128, **NEW=0**（resolved 6） |
| 后端影响集 | `pytest tests/test_research_steering.py tests/test_research_interaction.py tests/test_incremental_research_budget.py tests/test_web_lookup_deep_research.py tests/test_web_lookup_run.py tests/test_web_lookup_research_contract.py tests/test_research_answer_streaming.py tests/test_chat_research_run_owner.py tests/test_persistent_web_agent.py tests/test_chat_service.py tests/test_research_follow_up.py tests/test_research_recovery.py tests/test_active_research_runtime.py tests/test_standard_research.py -q` | **259 passed**（~4m15s） |
| 前端单测 | `frontend: npx vitest run src` | **484 passed / 111 files** |
| 前端类型/构建 | `npx tsc -b`；`npm run build` | PASS |
| 连续对话 E2E | `npx playwright test --config=playwright.conversation.config.ts` | **2 passed × 2 视口**（desktop 1440×900 / mobile 390×844） |
| 全量 fixture E2E | `npx playwright test` | **79 passed**（chromium/mobile/narrow + firefox + webkit） |
| 手工断言 | E2E 内含 `streams==1`、`queue==1`、`steering==[两条]`、无横向溢出、无重复全局状态条 | PASS |

> 这些是**离线桩件**证据（脚本化 gateway / 内存+SQLite / 模拟 SSE），不是真实 provider 生产验收。

## 5. 尚未验证（合并门阻塞项）

- **真实搜索提供商**：修改关键词后实际查询是否改变、来源质量与补查是否真的发生。
- **证据复用**：有效资料保留、失效资料退出结论来源（当前仅脚本化验证）。
- **动态预算**：按真实新增工作扩容、补充 ID 幂等（仅在脚本化流程验证）。
- **状态一致性**：UI、SQLite、实际执行轨迹三者吻合。
- **真实模型自主工具选择**与研究质量（需额度恢复后）。
- **连续输出**：开场、工具过程、研究结果在同一对话的真实链路（当前为桩件）。

## 6. 兼容性债务

- **PR #229（OPEN，head `1784c0fdcfaaa2a9d6cea66c881b01213f2804cc`）必须保留，不得被 Rev 3 覆盖。** 其文件恰为 `ChatPanel.tsx`(+12/−2) 与 `ChatPanel.test.tsx`(+79/−7)。需**逐项提取**（禁止整体 cherry-pick）：
  1. `composingRef` 组合生命周期守卫（`onCompositionStart/End`）。
  2. 会话切换时 `setIsAtBottom(true)` 的滚动锁重置。
  3. `正在生成 · 回到最新` 文案。
  4. 上述三项对应的 3 个测试。
  Rev 3 目前仅含基础 `keyCode===229` IME 守卫。
- **#224 独立产品质量工作线**：与本方向分离，本分支不得混入。
- 既有 UI 分支 `codex/conversation-first-ui`（Rev 2，基于旧 main）与 `codex/reading-notebook-ui`（RP-1）不属于本分支范围。

## 7. 下一阶段

- **Slice A 收尾**：整合 #229 三项行为与测试（见 §6），完成一次聚合验证。
- **Slice B — Agent 工具执行闭环**：受限 Python 执行环境 + 计算结果协议 + 可信结果转交互图表 + 连续流接线，一并设计。
  - 目标不是「加一个图表组件」，而是让 Agent 能**决定何时计算**、在**受限沙箱**执行、**验证计算结果**、并把可信结果转为**可交互图表**。
- **Slice C — 统一多模态输入**：附件基础设施统一到聊天输入区。
- 无需等额度重置：Python 沙箱、工具协议、结构化图表、前端渲染与模拟研究流程均可先离线实现；真实模型自主工具选择与研究质量留待额度恢复后验收。

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
