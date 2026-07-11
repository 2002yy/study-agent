# 学习工作台 UI 重构设计（方案 B：双栏专注 + 学习伴侣栏）

- 日期：2026-07-12
- 状态：已确认（方案 B + 决策点 a）
- 范围：前端表现层重构 + 一个后端小改（ChatResponse 补 pedagogy 摘要）

## 1. 背景与动机

study agent 的差异化核心是**教学法驱动的对话**（苏格拉底/费曼/项目/普通四协议 + 学习状态机 + 学习者应答评估 + 掌握度门控）。但现有 UI 把教学法仅当作侧栏两行指标读数，学习者看不到自己的学习轨迹；刚加入的模型自主联网工具（`web_search`/`web_read`）在路由面板只显示"已调用 N 次"，搜了什么、读了什么完全不可见；右侧 Inspector 8 个只读面板纵向堆叠，核心信息被埋。

本次重构以教学法为核心重新组织工作台，让学习状态一等公民化、联网工具可追溯、信息架构清晰化。

## 2. 目标

1. 教学法可视化：学习目标 / 阶段阶梯 / 掌握度 / 当前缺口 / 已确认点常驻可见。
2. 联网工具可追溯：每条 assistant 回复内联展示 RAG 引用 + web 工具调用轨迹。
3. 信息架构重排：次要面板（群聊/新闻/工具/会话/记忆/设置）降级为按需 slide-over。
4. 全面重构 UI：三列 -> 双栏，保留深青主题与手搓 CSS 风格。

非目标：不改后端业务逻辑、不改 controllers/API 契约（除决策点 a 的小补字段）、不引入 router/状态库/UI 库。

## 3. 布局

`styles.css` 三列网格改为两列：

```css
.app-shell {
  grid-template-columns: 340px 1fr;
}
```

```
┌──────────────┬──────────────────────────────────────────┐
│  学习面板     │  顶栏：标题 + 路由meta + dock[群聊][新闻]  │
│  (340px)     │        [工具][会话][记忆][⚙设置]  会话#x │
│              ├──────────────────────────────────────────┤
│ 学习目标      │   对话区（消息 + 内联证据轨迹）            │
│ 阶段阶梯 ●○○○ │                                          │
│ 掌握度环 62%  │                                          │
│ 当前缺口 ⚠    │                                          │
│ 已确认点 ✓✓   │                                          │
│ 本轮动作 标签  │                                          │
│ ─────────    │                                          │
│ 记忆快照 ▸    │                                          │
│              ├──────────────────────────────────────────┤
│              │  输入框                          [发送]   │
└──────────────┴──────────────────────────────────────────┘
```

## 4. 学习面板（左栏）

数据源：`lastChat.route.learning_state`（提交后的 `LearningState`）+ `lastChat.route`（role/mode/model）+ 既有 `memoryStatus`。

| 区块 | 组件 | 字段 | 空态 |
|---|---|---|---|
| 学习目标 | `ObjectiveCard` | `learning_state.objective` | "发一条学习请求以建立目标" |
| 阶段阶梯 | `PhaseStepper` | `protocol` 决定阶段序列；`phase` 高亮当前；已完成打勾 | 协议未定时隐藏 |
| 掌握度环 | `MasteryRing`（SVG） | 派生：`confirmed_points` 数 + 阶段进度 + `turn_count`；旁标"已确认 N 点 / 提示级别 L0-5" | 0% |
| 当前缺口 | `GapAlert` | `unresolved_gap` + `hint_level` | "无未解决缺口" |
| 已确认点 | `ConfirmedPoints` | `confirmed_points` 列表 -> ✓ chip | "尚未确认知识点" |
| 本轮动作 | `TurnMoveBadge` | `move` + `mode`/`protocol`（见 §7 决策 a） | - |
| 记忆快照 | `MemorySnapshot`（折叠） | current_focus/progress/summary 预览（迁自旧 Sidebar） | - |

`MasteryRing` 派生公式（初版，可在实现期微调）：
`mastery = 0.5 * (confirmed_points / max(1, confirmed + gap)) + 0.5 * (phase_index / total_phases)`，钳到 [0,1]。

阶段序列需在实现期从各 protocol planner（`src/pedagogy/socratic.py`/`feynman.py`/`project.py`/`direct.py`）核实确切阶段名与顺序。

## 5. 对话栏 + 内联证据轨迹（中栏）

- **顶栏**：标题 + 路由 meta（mode·role·model 紧凑 pill）+ dock 图标按钮（触发抽屉）+ 会话 ID。
- **消息**：每条 assistant 消息体下方加可折叠 `EvidenceTrail`：
  - `TurnMoveBadge`：协议·动作（如"苏格拉底·追问"）。
  - **RAG 引用**：`[1][2]` 编号 chip（来自 `rag.results`/`debug.results`），点击展开 title/url/score。
  - **联网工具轨迹**：遍历 `rag.web_tools.calls`：
    - `web_search` -> 🔍 "query" + 结果标题/url（前 3 条，来自 `result.results[]`）。
    - `web_read` -> 📄 url + 内容截断预览（来自 `result.content`，截 300 字）。
  - `web_tools.error` 非空 -> 红色错误条。
  - `web_tools.enabled === false` -> "联网工具已关闭"灰条（仅在曾启用时显示）。
- **流式中断恢复条**、**composer**（textarea + 发送/停止）、**回到最新按钮**：保留现有实现。

## 6. Slide-over 抽屉（次要面板降级）

通用 `SlideOver.tsx`：右浮层 + 半透明遮罩 + Esc/遮罩点击关闭，同时只开一个。

| dock 按钮 | 抽屉内容（迁自旧 Inspector） |
|---|---|
| 群聊 | `WechatPanel` |
| 新闻 | `NewsWorkspace` |
| 工具 | `ToolPanel` |
| 会话 | `SessionsPanel` |
| 记忆 | `MemoryPanel`（写回工作台） |
| ⚙ 设置 | 旧 Sidebar 全部设置（role/mode/model/perf/relationship/RAG/存为默认） |

`RoutePanel`（回答检查器）折叠进 `EvidenceTrail` 的"本次回答详情"展开区（保留路由指标可查）。`RoadmapPanel`（静态迁移信息）移入"关于"或移除。

## 7. 决策点 a：本轮认知动作 `move` 的来源（已选 a）

`move` 位于 `pedagogy_snapshot`，原本只在 session detail 的 `turns[]` 里，不在 `lastChat`。

**选定方案 a（后端小改）**：在 `ChatResponse` 与 SSE `done` 事件补一个紧凑 `pedagogy` 摘要：

```jsonc
// ChatResponse 增字段
{
  "reply": "...",
  "session_id": "...",
  "turn_id": "...",
  "route": { ... },
  "rag": { ... },
  "pedagogy": {
    "mode": "socratic",
    "move": "give_hint",
    "disclosure_level": 2,
    "phase": "probe"
  }
}
```

- 取自 `prepared.turn.pedagogy_snapshot`（已在 `start_turn` 构建）。
- SSE `done` 事件 payload 同步增加 `pedagogy`。
- 前端 `ChatResponse` 类型与 `lastChat` 同步加 `pedagogy?`。
- 后端加 API 测试：`ChatResponse.pedagogy` 非空且字段正确。

## 8. 组件清单

**新增**：`LearningPanel`、`ObjectiveCard`、`PhaseStepper`、`MasteryRing`、`GapAlert`、`ConfirmedPoints`、`TurnMoveBadge`、`EvidenceTrail`、`WebToolCallCard`、`SlideOver`、`SettingsDrawer`。

**重构**：
- `AppShell.tsx` / `styles.css`：3 列 -> 2 列网格 + 抽屉样式 + 学习卡片 + 掌握度环 + 证据 chip。
- `Sidebar.tsx`：拆分 -> 设置迁入 `SettingsDrawer`、记忆快照迁入 `LearningPanel`、导航锚点删除。
- `ChatPanel.tsx`：加 `EvidenceTrail`（assistant 消息下）+ 顶栏 dock 图标。
- 各 Inspector 面板：包进 `SlideOver`，由 dock 按钮触发。
- `workspaceReducer.ts`：增 `activeDrawer: string | null` + `OPEN_DRAWER`/`CLOSE_DRAWER` 动作。
- `types.ts`：用强类型 `LearningState`/`PedagogyTurnPlan`/`WebToolCall`/`PedagogySummary` 替换 `Record<string,unknown>`（route/rag/pedagogy 相关）。

## 9. 状态管理

沿用现有手搓 reducer（`WorkspaceProvider` + `workspaceReducer`）。新增：
- `activeDrawer: DrawerId | null`
- 动作 `OPEN_DRAWER(id)` / `CLOSE_DRAWER()`
- 学习面板读既有 `lastChat`、`sessionDetail`、`memoryStatus`，无需新数据源。

`DrawerId = "group" | "news" | "tools" | "sessions" | "memory" | "settings" | null`。

## 10. 样式

扩 `styles.css`，保留深青主题与纯 CSS 风格：
- 两列网格 + 响应式断点更新（≤1100px 学习面板折叠为顶栏摘要；≤760px 单列堆叠）。
- `.slide-over` + `.slide-over-backdrop` 过渡（transform translateX）。
- `.learning-card`、`.mastery-ring`（SVG conic/stroke）、`.phase-stepper`、`.gap-alert`、`.evidence-trail`、`.citation-chip`、`.web-call-card`。

## 11. 测试

- vitest：`LearningPanel`（渲染学习状态各态）、`EvidenceTrail`（RAG + web 工具调用渲染 + error 态）、`SlideOver`（开关 + Esc + 遮罩关闭）、`workspaceReducer`（OPEN/CLOSE_DRAWER）、`MasteryRing`（派生数值）。
- 后端：`ChatResponse.pedagogy` 字段存在且正确的 API 测试（决策 a）。
- 回归：现有 544 个测试全绿；现有前端测试（如有）全绿。

## 12. 兼容与迁移

- 仅重组表现层，controllers/API 不动（除决策 a 补字段，向后兼容可选字段）。
- `pedagogy` 为可选字段，旧前端忽略不报错。
- 上传入口保留（迁入设置抽屉或顶栏按钮）。
- 路由指标可查性保留（EvidenceTrail"本次回答详情"）。

## 13. 风险

- 阶段序列需核实：若 protocol planner 的 phase 集合与预设不符，`PhaseStepper` 退化为"当前阶段高亮 + 已知阶段列表"。
- `MasteryRing` 派生公式为启发式，实现期可用真实掌握度评估数据校准。
- 抽屉与既有 controller 状态交互需验证（群聊/新闻流式不受抽屉开关影响）。
