# Study Agent 当前状态

> **唯一当前状态入口**  
> 更新日期：2026-07-13  
> 当前代码基线：`29748f5f5097180d5563caf4db06ef82310062b3`

本文件只回答三个问题：**现在做到哪里、还差什么、下一步做什么**。其他文档不再重复维护进度；架构、专项需求和历史实现记录只作为附录。

## 1. 当前阶段

Study Agent 已完成主要架构迁移和第一轮高风险正确性整改，当前处于：

> **基础架构基本完成，P0 最小正确性切片已落地，G10 ResearchRun 已完成数据合同与持久化基础。**

主运行架构是 React + FastAPI + SQLite。Chat/Session、GroupThread、NewsRun、ToolRun、MemoryRun、RAG/KnowledgeBase、WebLookupRun、Workspace Runtime 和 PedagogyEvalRun 已有明确 owner。

## 2. 已完成

### 架构与学习状态

- Chat、RAG、记忆、联网查询和教学评估使用服务端持久化状态。
- `PedagogyEvalRun` 接入真实完成事务；Provider 或解析失败不能静默推进学习阶段。
- 实时和刷新恢复都能读取逐轮 route、RAG、pedagogy evidence。
- 恢复时优先使用 committed learning state，只采纳 completed turn 的阶段轨迹。

### 会话与交互正确性

- 新建会话不再自动归档旧会话。
- 普通会话切换只取消 chat scope，不再默认 `cancelAll()`。
- Enter 发送、Shift+Enter 换行、中文输入法组合态防误发送。
- Assistant 复制只复制正文；角色头像使用装饰语义，避免重复朗读。
- 删除长期知识文档需要明确确认。

### 任务契约

- 已识别 quick answer、research、learn、explain back、project execution、conversation、organize。
- 临时 research、quick answer 和 conversation 默认不推进 confirmed points、阶段或缺口。
- 活跃学习中的普通追问可继承当前目标。
- 非学习任务在 UI 中显示任务状态，不伪装成学习进度。

### 联网与外发策略

- 联网支持关闭、每次询问、自动。
- 云端上下文可限制为仅当前问题、最近对话或允许本地资料片段。
- 策略已进入真实 chat preparation 路径。
- 紧凑型号名称支持确定性归一化和查询变体。
- 查询注入当前 UTC 日期；空结果和 Provider 不可用不再等同于“实体不存在”。
- `gpt5.6sol` 已加入固定日期黄金回归，不硬编码产品存在性答案。

### G10 第一阶段：研究合同、有限扩展和持久化

- 新增 `ResearchContext` 与 `QueryAttempt` 纯数据合同。
- 保留 raw query，同时产生 canonical query、有限 query variants、当前日期和 freshness 信息。
- `WebLookupService` 按最多三个规范化变体依次查询，命中后立即停止。
- 单次 Provider 失败可继续尝试剩余变体；只有所有变体均失败才将 run 标为 failed。
- 全部查询为空仍为 completed + empty evidence，不升级为 confirmed absence。
- `WebLookupRun` 已增加 stage、research context、query attempts、selected/rejected sources、provider status、stop reason、answer confidence。
- SQLite schema 14 增加对应列，并为历史 completed/failed 数据回填安全状态。
- Repository、API response 和恢复读取已支持新增字段。
- 测试覆盖规范化、有限扩展、成功/空/全失败、持久化恢复和 schema 14 旧数据回填。
- 正常研究轨迹不进入 warning UI；Provider 失败才产生 warning。

### 过渡式课后整理

- after-session preview API 已存在。
- “整理学习”可生成 MemoryRun 候选并打开确认抽屉。
- MemoryRun 仍保持预览、用户确认和安全写入边界。

这仍是过渡实现，不代表正式学习闭环已经完成。

## 3. 当前缺口

| 领域 | 状态 | 主要缺口 |
|---|---|---|
| G10 多步联网研究 | 数据与持久化基础完成 | SourceAssessment、阶段 transition、网页阅读、预算、重试继续、追问复用、前端高级轨迹 |
| G1 LearningClosureRun | 仅有过渡入口 | service/repository、持久化、幂等、恢复、取消 |
| G12 过程阶段与取消 | 部分完成 | 服务端阶段事件、研究/RAG/Provider 取消传播、预算 |
| G2 结构化总结输入 | 未开始 | committed state + PedagogyEvalRun 证据、prompt 预算、候选来源 |
| G3 真正结束状态 | 未开始 | summary status、重复防护、结束态、继续/归档选择 |
| G4 会话语义 | 未开始 | 标题、预览、任务/阶段/缺口/总结状态、搜索分组 |
| G6 恢复卡 | 未开始 | 新用户任务入口、老用户行动性恢复卡、partial run 操作 |
| G5 学习展示 | 部分完成 | 移除启发式 mastery ring，展示真实评估状态 |
| G13 证据合同 | 部分完成 | selected EvidenceRef、web/local 分开计数、claim-source |
| G14 资料范围 | 部分完成 | 每文件状态、临时/长期范围、失败重试、清理策略 |
| G15 会话真值 | 部分完成 | summarized 状态、离开门禁、partial run 恢复 |
| G16 隐私控制 | 部分完成 | 附件敏感标记、外发摘要、Provider 展示、首次说明 |
| G7/G8/G17 产品体验 | 部分完成 | 四入口 dock、设置分层、首次使用、焦点管理、窄屏完整旅程 |

## 4. 当前执行顺序

### A. P0 真实旅程复核

1. `联网看看gpt5.6sol`：不注入旧年份，不无依据输出不存在，不显示无效引用。
2. 活跃学习中的临时 research：committed objective、phase、confirmed points 和 gap 不变化。
3. 新建/切换：只取消 chat，不影响上传、记忆预览或独立查询。
4. web off/ask/auto 和 cloud context：实际外发内容与设置一致。
5. 刷新后：committed state、引用计数和采用来源稳定。

### B. 正式可恢复 Run

1. **继续 G10：SourceAssessment、stage transition、网页阅读和恢复控制。**
2. 建立 G1 LearningClosureRun。
3. 补 G12 阶段事件、预算和取消传播。
4. 补 G14 临时资料与逐文件状态。

### C. 闭合学习与会话

1. G2 + G3：结构化总结和真正结束。
2. G4 + G6：会话语义和恢复卡。

### D. 产品收敛

1. G5：移除伪精度。
2. G7：dock 和设置分层。
3. G8：窄屏完整可用。
4. G17：首次使用、焦点和错误动作。

## 5. 下一代码切片

**G10 SourceAssessment 与阶段 transition。**

下一步目标：

- 为来源建立统一评估结果：相关性、来源类型、直接性、时效性、重复和是否值得阅读；
- 将 run 从单纯 `searching -> completed/failed` 扩展为真实 `searching -> assessing -> reading/synthesizing` 边界；
- selected/rejected sources 不再直接等于搜索结果；
- 增加 repository 的 compare-and-set stage transition；
- 为刷新恢复和后续 retry 保存当前阶段；
- 前端暂只读取 compact 结果，高级研究轨迹在合同稳定后接入。

## 6. 验证状态

- SQLite migration 14 已在隔离环境执行并验证列创建和 schema version。
- 研究 service/repository 已做隔离 smoke：规范化查询、空后命中、持久化恢复通过。
- 新增 pytest 回归已提交。
- GitHub connector 未返回 push 触发的 workflow/check 状态，因此当前不宣称远程 CI 已通过；需要以仓库 Actions 实际结果为准。

## 7. 文档入口

- **当前状态：** 本文件。
- **文档分类：** [`README.md`](README.md)。
- **架构边界附录：** [`ARCHITECTURE_STATUS.md`](ARCHITECTURE_STATUS.md)。
- **详细需求目录：** [`superpowers/plans/2026-07-12-study-agent-consolidated-roadmap.md`](superpowers/plans/2026-07-12-study-agent-consolidated-roadmap.md)。
- **技术栈：** [`TECH_STACK.md`](TECH_STACK.md)。
- **状态/文件模型：** [`STATE_MODEL.md`](STATE_MODEL.md)。

## 8. 维护规则

1. 当前进度、下一步和完成状态只更新本文件。
2. 架构文档只描述 owner、边界和稳定不变量，不维护产品进度表。
3. spec 只描述目标设计，不写“当前已完成”。
4. plan 完成后转为历史实现记录，不继续作为当前执行入口。
5. 每个代码切片必须同步更新本文件。
6. 不再创建新的 `STATUS / ROADMAP / NEXT_PHASE / AUDIT` 并列状态文档。
