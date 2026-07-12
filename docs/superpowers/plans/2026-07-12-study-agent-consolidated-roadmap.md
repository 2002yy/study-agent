# Study Agent 整体规划（目的导向）

> 范围：汇总三轮远程复审 + 既有未完项，按产品目的组织，列出每项边界。
> 这是**需求地图**，不是任务级 TDD 计划。具体实现前再拆 Task。

## 产品目的（不变）

本地优先、教学法驱动、证据可追溯、能沉淀长期记忆的学习工作台。

核心闭环：

```
建立目标 -> 教学推进 -> 证据追溯 -> 验证理解
-> 课后总结 -> 确认记忆 -> 标记已总结 -> 下次准确恢复
```

## 全局边界

**不改：** 教学协议引擎（苏格拉底/费曼/项目/普通）、RAG 检索算法、记忆 safe-writer 机制、Provider 抽象、SQLite 迁移 ledger 已有字段语义。

**不做：** 原生移动端 App、多用户/账号、插件化市场、自动归档（归档永远用户选择）。

**原则：**
1. API Route 只做 adapter，业务编排必须在 Application Service。
2. 任何多步 LLM 流程必须是 server-owned 可恢复 Run（对齐 RagRun/MemoryRun/NewsRun/PedagogyEvalRun）。
3. 总结/记忆优先用结构化教学状态，原始聊天仅作补充。
4. 写入记忆必须用户确认；推断性内容标 `learner_pending`。
5. 普通用户不暴露内部文件名/参数；这些进"高级"。

## 已完成基线（P0，多轮）

教学法可视化、证据可追溯（实时+恢复逐轮 route/rag）、协议/阶段中文标签、路由 mode 校验、左侧会话列表+顶部学习条、after-session 端点+整理学习按钮、窄屏会话入口、记忆目标选项对齐、文档定位。

---

## G1. 课后总结成为正式可恢复服务流程

**目的：** after-session 从"路由里临时编排 LLM+记忆"升级为 server-owned 可恢复 Run，与现有 Run 体系一致。

**需求：**
- 新建 `LearningClosureService`（application service），路由只调 `service.create(session_id)`。
- `LearningClosureRun` 持久化：`source_thread_id / source_thread_version / source_last_turn_id / status / learning_snapshot / generated_summary / memory_run_id / commit_status / error`。
- 状态机：`created -> collecting -> generating -> preview_ready -> committing -> completed | failed | cancelled`。
- 幂等：`closure_source_hash = hash(thread_id + thread_version + latest_completed_turn_id)`；同版本已有 preview 直接复用，不重调 LLM。
- 失败恢复：生成中断后可重试，不重复消耗模型。
- 前端：暴露生成阶段状态（collecting/generating/preview_ready）。

**边界：**
- 做：后端新切片 + 持久化 + 幂等 + 路由瘦身。
- 不做：不改前端 MemoryPanel 的 preview/commit 机制（复用 MemoryRun）；不改 `generate_after_session_updates` 的 LLM 调用签名（G2 改其输入）。
- 不含：总结输入改造（G2）、真正结束动作（G3）。

**优先级：** P1　**依赖：** 无（先行）

---

## G2. 总结输入用结构化教学状态

**目的：** 总结基于可靠的教学状态而非"LLM 读原始聊天自行判断"，提升可信度。

**需求：**
- 优先喂入 committed `learning_state`：objective / confirmed_points / unresolved_gap / phase / protocol。
- 引用 `PedagogyEvalRun` 最终决定（通过/待复核/未通过）。
- 原始聊天限预算：最近 N 轮完整，更早服务器摘要或丢弃；长会话不爆 prompt。
- `learner_profile` 候选默认 `learner_pending=true`（推断非事实）；其余 target `false`。
- 每条候选记录依据来源（哪条 confirmed_point / 哪轮 eval）与置信度。

**边界：**
- 做：改 `generate_after_session_updates` 的 prompt 构造 + 候选元数据。
- 不做：不改教学协议/评估逻辑；不改记忆文件格式。
- 不含：prompt 预算的精确数值（先粗后调）。

**优先级：** P2　**依赖：** G1（在 LearningClosureService 内实现）

---

## G3. 真正的"结束学习"闭环动作

**目的：** "整理学习"不止生成候选，确认写入后真正结束本次学习。

**需求：**
- 确认写入后标记会话 `summary_status = summarized`。
- 写入后给选择：归档并新建下一会话 / 继续当前会话。
- "本次学习已结束"态展示。
- 阻止对已总结会话重复生成（除非对话有新轮次，即 thread_version 变化）。

**边界：**
- 做：ChatThread 加 `summary_status` 字段 + 状态迁移 + 前端结束流程按钮。
- 不做：不自动归档；不删会话。
- 不含：会话标题（G4）。

**优先级：** P3　**依赖：** G1, G2

---

## G4. 会话导航语义化

**目的：** 侧栏显示有意义的标题，而非 `chat_01J...md` 文件名。

**需求：**
- `ChatThread` 加 `title`（由 objective 或首条用户消息生成）、`objective_summary`、`last_message_preview`、`current_phase`、`unresolved_gap`、`summary_status`、`updated_at`。
- 侧栏行展示：标题 + 阶段/缺口 + 时间 + 状态徽标（未总结/已总结/已归档）。
- 标题生成：首轮后由 learning_state.objective 或首条消息截断生成；可手动改。
- 搜索 + 分组（按状态/时间）。

**边界：**
- 做：ChatThread 加字段 + 生成 + 侧栏展示。
- 不做：不改会话存储格式（仅加列/迁移）；不做标签系统。
- 不含：跨会话知识图谱。

**优先级：** P4　**依赖：** G3（summary_status）

---

## G5. 学习状态展示去伪精化

**目的：** 不再用启发式百分比误导，改用真实评估状态。

**需求：**
- LearningStrip 折叠态顺序：**目标 -> 阶段 -> 缺口/下一步 -> 最近评估**；协议名降为次级 badge。
- 移除"本轮理解进度"圆环的伪百分比；改用 PedagogyEvalRun 决定：`✓已验证 / ○待验证 / !需重讲 / ?待语义复核`。
- 展开态保留目标/已确认点/缺口/阶段轨迹，去掉推算环。

**边界：**
- 做：展示层（LearningStrip/LearningPanel）改。
- 不做：不改评估逻辑、不改 `deriveMastery`（保留函数但 UI 不再用作进度）。
- 不含：学习者能力模型（真百分比等 Learner Model 再做）。

**优先级：** P2　**依赖：** 无

---

## G6. 恢复卡（结构化"上次学习"）

**目的：** 老用户恢复时看行动性恢复卡，而非三段原始 Markdown。

**需求：**
- 老用户首页恢复卡：目标 / 已确认点 / 当前缺口 / 下一步 + `[继续这里] [开始新主题]`。
- 新用户保留快捷提问引导。
- 卡片数据来自 `lastChat.route.learning_state` + 会话 title(G4)。

**边界：**
- 做：ChatPanel home-brief 区改。
- 不做：不改后端恢复数据。
- 不含：跨会话复习计划。

**优先级：** P2　**依赖：** G4（title/objective）

---

## G7. UI 聚焦收敛

**目的：** 减少次要功能曝光，让产品像学习工具而非控制台。

**需求：**
- dock 收敛为 4 个一级：上传资料 / 会话 / 整理学习 / 更多。
- "更多"菜单：来源与知识库 / 设置 / 群聊 / 新闻 / 工具 / 工作流时间线。
- 设置分"基础"（角色/教学模式/模型档位/RAG 开关）与"高级"折叠（top_k/min_score/检索模式/上下文层/氛围）。
- MemoryPanel 高级详情才显示 `current_focus.md` 等文件名；普通态用友好标签（本次学习进度/下一次重点/学习偏好…）。
- 角色与氛围移入"表达"设置区，不再作主产品卖点文案。

**边界：**
- 做：信息架构 + 设置分层 + 标签友好化。
- 不做：不删任何功能（都进"更多"）；不砍群聊/新闻。
- 不含：主题/换肤。

**优先级：** P2　**依赖：** 无

---

## G8. 移动端/窄屏完整可用

**目的：** 窄屏不丢失核心差异化功能。

**需求：**
- 窄屏会话入口（P0 已恢复 dock 按钮+抽屉）。
- 顶部学习状态条窄屏可用（目标/阶段/缺口一行+展开）。
- dock 窄屏防溢出（P0 已做 flex-wrap）。
- "整理学习"按钮窄屏可见可达。

**边界：**
- 做：响应式适配。
- 不做：不做原生 App、不做独立移动端布局。
- 不含：离线 PWA。

**优先级：** P2（部分 P0 已做）　**依赖：** 无

---

## 执行顺序（建议）

```
G1 (P1 架构)  ->  G2 (P2 总结输入)  ->  G3 (P3 结束动作)
                                        |
G5 (P2 展示去伪)  G7 (P2 收敛)  G8 (P2 窄屏)   并行可做
G4 (P4 会话语义) 依赖 G3
G6 (P2 恢复卡) 依赖 G4
```

- **第一批：** G1（最大、解锁 G2/G3）。
- **第二批：** G2 + G3（闭合真正结束流程）。
- **第三批：** G5/G7/G8（展示与聚焦，互相独立）。
- **第四批：** G4 -> G6（会话语义 + 恢复卡）。

## 跨项风险

- **G1 持久化**：新增 `LearningClosureRun` 表需 SQLite 迁移（SCHEMA_VERSION +1），必须不破坏既有 ledger。
- **G3 summary_status**：ChatThread 加字段同样需迁移；状态迁移要兼容历史会话（默认 `unsummarized`）。
- **G2 prompt 预算**：粗值可能影响总结质量，需小样本验证后调参。
- **G4 标题生成**：首轮自动生成可能不准；必须允许手动改 + 不覆盖用户已改。
- **G7 收敛**：移动现有 dock 到"更多"不能丢入口，需回归每个抽屉可达。
