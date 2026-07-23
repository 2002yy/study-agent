# Study Agent G1–G17 产品需求目录

> **文档类别：详细产品需求，不是当前进度入口。**  
> 当前状态、缺口和下一步统一查看 [`../../PROJECT_STATUS.md`](../../PROJECT_STATUS.md)。  
> 本文件只保留目标、边界和验收，不维护“已完成/未完成”状态。

## 1. 产品目标

Study Agent 是本地优先、教学法驱动、证据可追溯、能够沉淀长期记忆的学习工作台。

正式学习闭环：

```text
明确目标 -> 教学推进 -> 证据追溯 -> 验证理解
-> 结果整理 -> 用户确认记忆 -> 标记已整理 -> 下次准确恢复
```

临时任务闭环：

```text
快速问答 / 联网研究 / 临时资料 / 闲聊
-> 给出可用结果与有效证据
-> 默认不推进长期学习状态
-> 用户决定是否转目标或保存笔记
```

## 2. 全局边界

1. API route 只做 adapter，多步编排归 application service。
2. 多步 LLM 流程必须成为 server-owned durable run。
3. committed state 是产品真值；planned/attempted/failed 不得伪装成完成。
4. 记忆写入必须由用户确认；推断性 learner profile 默认 pending。
5. TaskIntent、PedagogyProtocol、VoiceProfile、SourcePolicy、ClosureEligibility 分层。
6. 角色表达不能改变事实结论、是否联网、来源可信度或任务状态。
7. 空结果、Provider 失败、证据不足和确认不存在必须严格区分。
8. 当前日期、时区和用户明确时间范围必须进入时效查询规划。
9. 只有有效且被采用的来源进入引用计数。
10. 新建、总结、归档、写入记忆是独立动作。
11. operation 按 owner/scope 取消，不使用全局 cancelAll 作为普通路径。
12. 不建设原生移动端、多用户、通用爬虫平台、后台长期任务或插件市场。

---

## G1. LearningClosureRun

**目的：** 将 after-session 临时编排升级为可恢复、可审计、幂等的正式服务流程。

**必须具备：**

- `LearningClosureService` 是唯一 owner；
- 持久化 source thread/version/last completed turn、committed snapshot、generated result、MemoryRun、status/error；
- 状态机：created -> collecting -> generating -> preview_ready -> committing -> completed/failed/cancelled；
- source hash 幂等，相同线程版本复用 preview；
- retry/cancel 不重复已完成模型步骤；
- ClosureEligibility 不适用时拒绝学习总结。

**验收：** 刷新可恢复；相同版本重复点击不重调；失败后重试继承进度；research 不生成学习总结。

## G2. 结构化总结输入

**目的：** 总结基于可靠教学证据，而不是让模型重新猜测整段聊天。

**必须具备：**

- 优先使用 committed objective/confirmed points/gap/phase/protocol；
- 消费最终 PedagogyEvalRun、evidence IDs 和 evaluator versions；
- 最近对话有预算，更早内容摘要或丢弃；
- learner profile 推断默认 pending；
- 候选保存来源、置信度和对应评估；
- 按任务生成学习总结、研究笔记、项目收束或 not applicable。

**验收：** 未提交/失败回合不能成为已掌握；长会话不爆 prompt；候选来源可解释。

## G3. 真正结束与 summary status

**目的：** 记忆确认后形成明确结束状态。

**必须具备：**

- commit 后设置 summary status；
- unchanged thread version 禁止重复 closure；
- 新增完成回合后允许重新整理；
- 展示“本次已整理”；
- 提供继续当前 / 归档并新建；
- 不自动归档。

## G4. 会话导航语义化

**必须具备：**

- title、objective/research summary、last preview、task intent、phase/gap、summary status、updated_at；
- 标题可自动生成和手动修改，自动逻辑不覆盖用户标题；
- 侧栏展示任务、阶段/缺口、时间和状态；
- 支持按状态、时间和任务搜索/分组；
- 历史数据兼容。

## G5. 学习状态去伪精化

**目的：** 不用启发式百分比冒充真实掌握度。

**必须具备：**

- 折叠态顺序：目标 -> 阶段 -> 缺口/下一步 -> 最近评估；
- 使用已验证 / 待验证 / 需重讲 / 待语义复核；
- 移除 heuristic mastery ring；
- planned/attempted 与 committed 分开；
- 非学习任务显示研究/回答状态。

## G6. 结构化恢复卡

**必须具备：**

- 新用户显示快速问答、系统学习、联网研究、项目、资料入口；
- 老用户显示任务/目标、确认点或采用来源、缺口、下一步；
- 继续这里 / 开始新主题；
- partial/interrupted run 提供继续、重试、放弃；
- 数据来自 committed learning、ResearchRun 或项目状态。

## G7. UI 聚焦收敛

**必须具备：**

- 一级 dock：上传 / 会话 / 当前任务收束 / 更多；
- 来源、设置、群聊、新闻、工具、时间线进入更多；
- 设置分基础 / 高级 / 表达；
- 普通态不展示内部 memory 文件名；
- 顶部隐藏 record ID、route code 和低层 Provider 参数；
- 不删除功能，只降低次要功能默认曝光。

## G8. 窄屏完整可用

**必须具备：**

- 顶部任务/目标/研究状态/缺口可读并可展开；
- 四个一级动作全部可达；
- 非 hover 环境有可见标签或正确 aria name；
- 会话、输入、收束、来源和抽屉在窄屏完整可操作；
- 不建设独立移动端 App。

## G9. 新兴术语与时效检索可靠性

**必须具备：**

- raw query、canonical candidates、date/timezone/time range、conversation topic、freshness；
- 保留原始拼写，有限生成空格/连字符/大小写变体；
- 精确词 -> 官方 -> 高可信近期来源 -> 宽泛别名的受控扩展；
- 7/30/365 天窗口和明确 stop reason；
- found/ambiguous/insufficient/empty/provider_failed/confirmed_absence 分离；
- Provider 失败或空结果不得表述为不存在；
- answer-first，证据不足时不自由猜测；
- 记录查询序列、窗口、来源选择和最终置信度；
- CI 使用固定 fixture，真实联网 smoke test 可选。

**关键回归：** `联网看看gpt5.6sol` 不注入过期年份，不优先猜 Sonnet/伪造，不展示无效引用。

## G10. 多步联网研究成为正式 Run

**架构原则：** 扩展现有 WebLookup owner，不建立重叠系统。

**必须具备：**

- created/normalizing/searching/assessing/expanding/reading/synthesizing/completed/partial/failed/cancelled；
- 持久化 context、attempts、selected/rejected sources、provider status、stop reason、confidence、answer；
- SourceAssessment：相关性、时效、来源类型、直接性、重复、是否值得阅读；
- Planner 决定停止、改写、扩大窗口、官方源、阅读或追问；
- 查询/阅读/时间/token/成本预算；
- 幂等恢复和 retry 继承；
- follow-up 复用上一 run 的实体和来源；
- 默认 UI 只显示答案和有效来源，高级区显示完整轨迹。

## G11. 任务意图与结果契约

**TaskIntent：** quick_answer / research / learn / explain_back / project_execution / conversation / organize。

**必须具备：**

- 在角色、教学协议、RAG、联网和记忆前确定任务；
- 允许用户显式覆盖；
- research/quick answer/conversation 默认不推进长期学习；
- learn/explain back/project execution 进入对应状态机；
- 明显换题时提供临时回答 / 切换目标 / 新建会话；
- 目标生命周期：proposed/confirmed/modified/suspended/completed/abandoned；
- task/source/closure 合同持久化并兼容旧会话。

## G12. 预回答阶段与完整取消

**必须具备：**

- routing/evaluating/retrieving/normalizing/searching/assessing/reading/composing/streaming/saving 事件；
- 首 token 前真实状态，不使用假百分比；
- 高级区显示 run、耗时、次数、预算和错误；
- cancel 传到 ResearchService、RAG 和 Provider 能力边界；
- 中断保留可用部分，可继续/重试/放弃；
- 取消后不得提交 completed 或推进学习状态。

## G13. 证据与消息完整性

**必须具备：**

- 统一 EvidenceRef：id/type/title/source/domain/published_at/score/selected/rejection/supported claims；
- 查询次数、阅读页数、采用 web 来源、本地引用分开；
- candidate/read/selected/rejected 分层；
- claim-source 对应；
- 空/重复/解析失败/零分占位不计数；
- 复制纯正文，角色名只读一次；
- 实时与刷新恢复使用同一数据合同。

## G14. 资料导入与来源范围

**必须具备：**

- 每文件 uploading/validating/parsing/chunking/indexing/ready/partial/failed；
- 上传入口和结果在同一流程；
- 当前会话临时附件 vs 长期知识库；
- active source scope 和实际使用资料可见；
- 从这些资料开始提问和推荐问题；
- 失败文件单独重试；
- 删除/重建说明影响并确认；
- 临时附件支持禁止联网/云端/记忆和会话结束删除。

## G15. 会话转换与状态真值

**必须具备：**

- 新建不归档；
- active/summarized/archived 明确迁移；
- committed truth 是主 UI 状态；
- 中断 planned state 单独提示；
- 切换生成中的 chat 明确提示；
- Memory preview、partial research、未完成上传有离开门禁；
- chat/research/rag_write/memory 独立 owner；
- 先整理 / 直接新建 / 取消。

## G16. 外发数据与隐私

**必须具备：**

- web off/ask/auto；
- cloud context question-only/recent-chat/allow-local-evidence；
- SourcePolicy/ProviderPolicy 持久化并可任务覆盖；
- 外发摘要：查询、历史、本地资料、Provider；
- 附件仅本地/禁联网/禁记忆/允许云端；
- EvidenceTrail 显示外发类型但不泄露正文；
- 首次自动联网/云端资料说明；
- ask 选择按会话合理记忆，避免提示疲劳。

## G17. 首次使用、消息操作与可访问性

**必须具备：**

- 新用户一屏选择五类任务；
- 老用户结构化恢复卡；
- 顶部默认只展示任务、目标和状态；
- Enter/Shift+Enter 可配置且兼容 IME；
- Assistant 复制/重试，中断继续/重试/复制；
- focus trap、Escape、关闭后焦点返回、背景不可操作；
- 移动端可见标签；
- 全局错误提供重试/设置/详情动作；
- 角色头像不重复朗读。

## G18. 前端采用新版 React + Streamlit 逐步废弃

**目的：** 前端定调为新版 React（19），旧 Streamlit 入口逐步移除，降低双前端维护负担与依赖体积。

**前置事实（已核实）：**
- 当前 React 18.3.1；`react-test-renderer` 被 **21 个 tracked `.test.tsx`** 使用，而 React 19 已弃用 react-test-renderer（peer 锁 18）。
- Streamlit 占用：`app.py` + `src/ui/`（11 文件）+ `requirements` 锁 `streamlit==1.57.0` + 4 个测试引用 `src.ui`。

**必须具备：**

*步骤 1 - 测试渲染器迁移（React 19 前置）*
- 引入 `@testing-library/react` + `@testing-library/jest-dom` + jsdom 环境。
- 迁移 21 个 `.test.tsx` 从 `react-test-renderer`（create/act/toJSON）到 testing-library（render/screen），保留断言意图。
- 删除 `react-test-renderer` / `@types/react-test-renderer`。

*步骤 2 - React 19 升级*
- `react`/`react-dom` -> ^19，`@types/react`/`@types/react-dom` -> ^19。
- 修类型严格化（`RefObject<T|null>` 可空性、隐式 any 等）。
- tsc + vitest + build 全绿。

*步骤 3 - Streamlit 逐步废弃*
- 移除 `app.py`（legacy 入口）。
- 移除 `src/ui/`（11 文件）；引用 `src.ui` 的测试：纯 streamlit 测试删除，可复用逻辑先抽取到非 ui 模块。
- `requirements.in` 移除 `streamlit`，重新 `pip-compile`。
- 文档：README/USER_GUIDE 从"Streamlit legacy 兼容"改为"已移除"。

**边界：** 不改测试断言意图；不引入新 UI 框架；不采用 RSC 等新特性；不做 streamlit 旧功能逐像素迁移（React 端已有对应实现）。

**依赖：** 步骤 1 必须先于步骤 2；步骤 3 独立可并行。

**风险：** testing-library 迁移工作量大（21 文件），需逐个保证断言等价；React 19 类型严格化可能暴露既有隐式 any；Streamlit 移除后需确认 `src/api` legacy proxy 无 streamlit 残留。

## 验证要求

每个实现切片必须同时完成：

- 目标测试先行；
- 后端全量 pytest；
- 前端全量 Vitest；
- Vite production build；
- 存储变化的 migration/兼容/失败恢复；
- 桌面和窄屏人工旅程；
- 刷新前后状态和证据比较；
- 更新 [`../../PROJECT_STATUS.md`](../../PROJECT_STATUS.md)。

## 历史说明

本文件曾同时承担审计、进度表和执行顺序，已于 2026-07-13 拆分。完整旧版本保留在 Git 提交 `eb51ba9a77a728b10d82adce2936e566257fb803`。
