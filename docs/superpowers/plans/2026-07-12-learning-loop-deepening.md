# 学习闭环深化计划（复审后续）

> **状态说明（2026-07-13）：** 本文件已从“初始实现清单”更新为当前闭环状态记录。架构与全产品审计分别以 `docs/ARCHITECTURE_STATUS.md` 和 `2026-07-12-study-agent-consolidated-roadmap.md` 为准。

**Goal:** 补齐“明确任务 -> 教学/研究推进 -> 有效证据 -> 用户验证 -> 结果整理 -> 确认记忆 -> 准确恢复”的完整闭环，并避免临时问答、联网研究和闲聊污染长期学习状态。

**审计基准提交:** `7ab8c3d42495032288d5a1b06df6a03052a91fd0`

**测试命令:** 后端 `$env:PYTHONPATH="."; python -m pytest -q`；前端在 `frontend/` 运行 `npx vitest run` 和 `npm run build`。

---

## 1. 已完成的基础闭环能力

- [x] 教学阶段轨迹实时更新与会话恢复。
- [x] 逐轮 `route_snapshot / rag_snapshot / pedagogy_snapshot` 恢复。
- [x] 协议、阶段和本轮教学动作可见。
- [x] `PedagogyEvalRun` 接入真实完成事务，失败不能静默推进阶段。
- [x] 左侧会话列表 + 顶部可展开学习状态条。
- [x] 窄屏会话入口和基础防溢出。
- [x] 路由 `selected_mode` 非法值校验与自动回退（原 P0.11）。
- [x] after-session preview API 可生成 MemoryRun 候选。
- [x] “整理学习”按钮可自动生成候选并打开记忆抽屉。
- [x] MemoryRun 仍保持预览/用户确认/安全写入边界。

> 重要：after-session 入口和按钮“可用”不等于正式学习闭环已完成。当前仍是过渡式编排，没有 `LearningClosureRun`、幂等恢复和会话 `summary_status`。

---

## 2. 2026-07-12 至 2026-07-13 新增的正确性基础

### 2.1 任务契约（G11 最小切片）

- [x] 在教学协议推进前识别 `quick_answer / research / learn / explain_back / project_execution / conversation / organize`。
- [x] `research / quick_answer / conversation` 不推进 confirmed points、阶段或缺口。
- [x] 活跃学习中的普通追问可继承当前学习目标。
- [x] 前端对非学习任务显示任务状态，而不是伪学习状态。
- [x] 当前学习型总结入口只对支持的 closure eligibility 展示。
- [ ] 用户显式覆盖 TaskIntent。
- [ ] 明显换题时提供“临时回答 / 切换目标 / 新建会话”。
- [ ] 学习目标生命周期：proposed / confirmed / modified / suspended / completed / abandoned。
- [ ] 将稳定任务契约持久化为 ChatThread 级真值，而不只依赖逐轮 route snapshot。

### 2.2 会话与状态真值（G15 最小切片）

- [x] 新建会话不再自动归档旧会话。
- [x] 恢复时优先读取 committed learning state。
- [x] 阶段历史只采纳 completed turn。
- [x] 会话切换只取消 chat scope，不再默认 `cancelAll()`。
- [ ] 会话状态完整区分 active / summarized / archived。
- [ ] partial ResearchRun、MemoryRun preview、未完成上传的离开门禁与恢复。
- [ ] 总结、归档和新建之间的完整产品选择流。

### 2.3 外发策略与联网正确性（G9/G16 最小切片）

- [x] 联网策略：关闭 / 每次询问 / 自动。
- [x] 云端上下文：仅当前问题 / 最近对话 / 允许本地资料片段。
- [x] 策略进入真实 chat preparation 路径，而非只存在设置 UI。
- [x] 紧凑型号名称的确定性归一化和查询变体。
- [x] 注入当前 UTC 日期；空结果和 Provider 不可用不等于实体不存在。
- [x] `gpt5.6sol` 固定日期黄金回归，不硬编码产品存在性结论。
- [ ] 附件级“禁止联网 / 禁止云端 / 禁止记忆 / 仅本地模型”。
- [ ] 发起外部请求前的完整外发摘要与 Provider 展示。
- [ ] 多步来源评估、受控时间窗口扩展和最终答案证据门禁。

### 2.4 证据与交互完整性（G13/G17 最小切片）

- [x] 嵌套 RAG chunk 标题/来源读取。
- [x] 空标题/空来源/非正分/重复占位不计入本地引用。
- [x] Assistant 复制只复制正文。
- [x] 角色头像使用装饰语义，屏幕阅读器不重复角色名。
- [x] Enter 发送、Shift+Enter 换行、IME composition 防误发。
- [x] 删除长期知识文档需要确认。
- [ ] 统一 `EvidenceRef`、selected evidence 计数和 claim-source 对应。
- [ ] 新用户任务入口与老用户结构化恢复卡。
- [ ] 抽屉 focus trap、关闭后焦点返回和可操作错误提示。

---

## 3. 原 P1 状态复核

### P1.1 after-session 自动候选端点

- [x] `POST /sessions/{session_id}/after-session/preview` 已接入。
- [x] 可基于会话生成 MemoryRun 候选并返回前端。
- [x] 相关 API/前端类型和回归已加入。
- [~] 这是过渡入口；尚未迁移为正式 `LearningClosureService/Run`。

### P1.2 “整理学习”按钮 + MemoryPanel 自动填充

- [x] 顶栏按钮可生成候选、自动打开记忆抽屉。
- [x] 候选进入现有 MemoryRun 预览/确认机制。
- [~] 按任务类型的研究笔记/项目收束尚无独立后端 closure 流程。

### P1.3 恢复卡

- [ ] 未完成。当前 `home-brief` 仍展示 current_focus/progress/summary 三段 Markdown。
- [ ] 新用户仍缺少一屏内的“快速问答 / 系统学习 / 联网研究 / 项目 / 资料”任务入口。
- [ ] 老用户恢复尚未统一读取 committed learning/research/project state。

### P1.4 最近评估决定显示

- [ ] 未完成。LearningPanel 仍展示启发式 mastery ring。
- [ ] 应改为 `已验证 / 待验证 / 需重讲 / 待语义复核`，只消费最终 committed evaluation。

---

## 4. 当前闭环主线

### P1-A：正式 LearningClosureRun（G1）

- [ ] 新建 `LearningClosureService` 和 repository。
- [ ] SQLite 持久化 source thread/version/last completed turn、committed snapshot、生成结果、MemoryRun、状态和错误。
- [ ] 状态机：created -> collecting -> generating -> preview_ready -> committing -> completed/failed/cancelled。
- [ ] `closure_source_hash` 幂等；相同线程版本复用 preview。
- [ ] 失败重试不重复调用已完成步骤。
- [ ] 按 ClosureEligibility 拒绝不适用的学习总结。

### P1-B：结构化总结输入（G2）

- [ ] 优先使用 committed objective / confirmed points / gap / phase / protocol。
- [ ] 引用最终 PedagogyEvalRun 决定和 evidence IDs。
- [ ] 原始聊天设置明确预算，只作为补充。
- [ ] learner profile 推断默认 pending。
- [ ] 每条候选记录来源、置信度和对应评估。

### P1-C：真正结束状态（G3）

- [ ] MemoryRun commit 后写入 `summary_status=summarized`。
- [ ] 线程无新增完成回合时禁止重复生成。
- [ ] 显示“本次学习已整理”。
- [ ] 提供继续当前 / 归档并新建；绝不自动归档。

### P1-D：ResearchRun 与准备阶段（G10/G12）

- [ ] 把多步搜索升级为唯一 server-owned ResearchRun。
- [ ] 保存查询尝试、来源评估、选中/拒绝来源、停止原因和答案置信度。
- [ ] 首 token 前显示真实 routing/retrieving/searching/reading/composing 阶段。
- [ ] 取消信号传到研究循环、RAG 和 Provider 能力边界。
- [ ] 刷新后恢复 partial/failed/cancelled 状态和已有结果。

---

## 5. P2/P3 产品收敛

### 会话与恢复（G4/G6）

- [ ] 会话 title、task intent、last preview、phase/gap、summary status、updated_at。
- [ ] 自动标题可手动改，后续不覆盖用户标题。
- [ ] 按状态/时间/任务搜索和分组。
- [ ] 结构化恢复卡与 interrupted/partial run 操作。

### 学习状态去伪精化（G5）

- [ ] 删除启发式 mastery ring 和 conic-gradient 进度表现。
- [ ] 折叠态顺序改为目标 -> 阶段 -> 缺口/下一步 -> 最近评估。
- [ ] attempted/planned 与 committed 分开展示。

### UI 聚焦与窄屏（G7/G8/G17）

- [ ] 一级 dock 收敛为上传 / 会话 / 当前任务收束 / 更多。
- [ ] 其余功能进入“更多”，但保持全部可达。
- [ ] 设置分基础 / 高级 / 表达层。
- [ ] 顶部隐藏 route code、记录 ID、内部参数。
- [ ] 完成窄屏可见标签、抽屉焦点、错误动作和首次使用入口。

---

## 6. 最新执行顺序

1. 完成 P0 真实旅程回归：新词联网、临时研究不污染、会话切换、外发策略、刷新证据。
2. G10 ResearchRun。
3. G1 LearningClosureRun。
4. G12 阶段事件与取消传播。
5. G2 + G3 结构化总结和真正结束。
6. G4 + G6 会话语义和恢复卡。
7. G5 + G7 + G8 + G17 产品收敛。
8. G14 临时资料与逐文件导入体验。

每个切片需同步更新本文件、`docs/ARCHITECTURE_STATUS.md`、`docs/NEXT_PHASE_PLAN.md` 和综合路线图。当前连接返回的 audited head 没有远程 workflow run，因此不能把远程 CI 标为已验证；下一次功能提交前后均应运行后端全量、前端全量、生产构建和桌面/窄屏人工旅程。
