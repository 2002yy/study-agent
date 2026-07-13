# 学习工作台 UI 重构实现记录（方案 B，已归档）

> **归档状态：2026-07-13**  
> 本文件原为逐 Task、逐代码片段的实施计划。方案 B 主体已经落地，原始未勾选 checkbox 不再代表当前实现状态。详细历史步骤可从 Git 提交 `233e101f935d41e382762d453a30146022c84723` 查看；当前需求、审计和执行顺序以综合路线图、`docs/ARCHITECTURE_STATUS.md`、`docs/NEXT_PHASE_PLAN.md` 为准。

## 1. 原目标

将旧三列工程控制台重构为更聚焦的学习工作台：

- 会话导航和主对话成为稳定骨架；
- 学习目标、阶段、缺口和本轮教学动作可见；
- 本地 RAG 与联网证据逐轮追溯；
- 次要功能进入 slide-over 抽屉；
- 实时与刷新恢复使用同一数据合同；
- 桌面和窄屏都能访问核心功能。

## 2. 已完成的主体实现

### 2.1 后端响应与恢复

- [x] ChatResponse 和 stream done 事件暴露 compact pedagogy summary。
- [x] session turns 返回 pedagogy/route/rag snapshots。
- [x] 前端可按 turn 恢复教学动作和证据。
- [x] committed learning state 与完成回合在恢复中得到优先使用。

### 2.2 前端架构

- [x] `App.tsx` 保持 composition-only。
- [x] `AppShell` 保持 layout-only。
- [x] `WorkspaceRuntime`、controllers、recovery、view 的责任边界已拆分。
- [x] `workspaceReducer` 管理单一 active drawer。
- [x] 通用 `SlideOver` 组件和多个功能抽屉已落地。

### 2.3 学习状态与教学法展示

- [x] `LearningStrip` 展示顶部学习状态并支持展开。
- [x] `LearningPanel` 展示目标、协议/阶段、缺口、已确认点和本轮动作。
- [x] 协议、阶段、教学动作使用中文标签。
- [x] 阶段轨迹实时更新并可从会话恢复。
- [x] 非学习 TaskIntent 不再展示伪学习缺口，而显示临时任务状态。

### 2.4 证据轨迹

- [x] Assistant 消息挂接 turn evidence。
- [x] 本地 RAG 和 web tool trace 可展开查看。
- [x] 嵌套 RAG chunk 的标题与来源映射已修复。
- [x] 空标题/空来源/非正分/重复占位不进入本地引用。
- [x] 刷新后逐轮 route/rag/pedagogy evidence 可恢复。

### 2.5 会话、输入和操作

- [x] 左侧会话列表和会话历史抽屉可用。
- [x] 新建会话不再自动归档旧会话。
- [x] 普通会话转换只取消 chat scope。
- [x] Assistant 提供纯正文复制。
- [x] Enter 发送、Shift+Enter 换行、IME composition 防误发送。
- [x] 中断回复支持继续、重试和复制已有内容。
- [x] 角色头像使用装饰语义，避免屏幕阅读器重复角色名。

### 2.6 课后入口和设置

- [x] after-session preview API 可生成 MemoryRun 候选。
- [x] “整理学习”按钮可自动打开候选确认抽屉。
- [x] 设置中可配置联网 off/ask/auto 和云端上下文范围。
- [x] 窄屏会话入口和基础 dock 防溢出已修。

## 3. 方案 B 未完全达到的原始目标

主体布局已实现，但以下内容不能标为完成：

### 3.1 学习状态仍有伪精度

- [ ] `LearningPanel` 仍使用 `deriveMastery` 和 conic-gradient ring。
- [ ] 应改为 PedagogyEvalRun 的“已验证 / 待验证 / 需重讲 / 待语义复核”。
- [ ] planned/attempted 与 committed 状态尚未完整分层展示。

### 3.2 首页恢复仍是旧语义

- [ ] `home-brief` 仍直接展示 current_focus/progress/summary 三段 Markdown。
- [ ] 新用户缺少一屏内的任务类型入口。
- [ ] 老用户缺少目标、确认点/来源、缺口和下一步组成的恢复卡。

### 3.3 信息架构仍偏控制台

- [ ] 顶部仍展示 RAG、route 和 record ID。
- [ ] dock 一级按钮过多，尚未收敛为上传 / 会话 / 收束 / 更多。
- [ ] 设置未分为基础 / 高级 / 表达。
- [ ] MemoryPanel 普通态仍可能暴露内部文件名。

### 3.4 抽屉与可访问性未封板

- [ ] 通用 SlideOver 尚缺完整 focus trap。
- [ ] 关闭后焦点返回触发按钮未统一。
- [ ] 背景不可操作、抽屉间焦点栈仍需验证。
- [ ] 移动端图标仍有依赖 hover title 的位置。

### 3.5 证据数据合同仍是过渡形态

- [ ] 尚无统一 selected `EvidenceRef`。
- [ ] 查询、阅读、采用 web 来源和本地引用尚未统一分开计数。
- [ ] 尚无 claim-source 对应和 selected/rejected source 展示。

### 3.6 课后总结仍是过渡流程

- [ ] after-session 不是正式 `LearningClosureRun`。
- [ ] 尚无幂等 source hash、阶段恢复、summary status 和真正结束态。
- [ ] research/project 尚无各自的结果收束流程。

## 4. 当前组件事实

| 区域 | 当前实现 | 下一步 owner |
|---|---|---|
| App composition | 已封板 | Architecture Status |
| Workspace controller/recovery/view | 已封板 | Architecture Status |
| 学习条和学习面板 | 可用但展示部分完成 | G5 |
| 会话列表/转换 | 核心可用，语义部分完成 | G4/G15 |
| 证据轨迹 | 基础可用，统一合同未完成 | G13/G10 |
| 抽屉/dock | 基础可用，信息架构未收敛 | G7/G8/G17 |
| 首页恢复 | 旧 Markdown 快照 | G6/G17 |
| 整理学习 | 过渡入口 | G1/G2/G3 |
| 外发设置 | 最小策略可用 | G16 |

## 5. 当前不再使用的旧判断

以下原计划表述已经失效，不应再指导新实现：

- “方案 B 尚未开始”——错误，主体已经实现。
- “所有 checkbox 未勾选代表未完成”——错误，原计划没有随提交更新。
- “左侧固定 340px 学习面板是最终布局”——已进一步演进为会话侧栏 + 顶部学习条；旧设计只保留组件和视觉经验。
- “结束学习只需要按钮和 MemoryPanel”——不足，正式闭环需要 LearningClosureRun、结构化输入和 summary state。
- “证据轨迹只需列出搜索调用”——不足，必须区分查询、阅读、采用、拒绝和本地引用。

## 6. 后续执行入口

不再从本文件逐 Task 执行。后续顺序：

1. 综合路线图 P0 真实旅程复核。
2. G10 ResearchRun。
3. G1 LearningClosureRun。
4. G12 阶段事件与取消传播。
5. G2/G3 结构化总结和真正结束。
6. G4/G6 会话语义和恢复卡。
7. G5/G7/G8/G17 展示、信息架构、窄屏和可访问性收敛。

每次推进须同步更新综合路线图、`docs/ARCHITECTURE_STATUS.md`、`docs/NEXT_PHASE_PLAN.md` 和相关专项计划。
