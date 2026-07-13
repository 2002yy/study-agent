# Study Agent 整体规划与全流程审计

> **当前状态版本：2026-07-13**  
> **审计实现基线：** `7ab8c3d42495032288d5a1b06df6a03052a91fd0`  
> **定位：** 本文件是产品需求、体验审计和 G1–G17 完成状态的统一真值。架构封板状态见 `docs/ARCHITECTURE_STATUS.md`，执行顺序见 `docs/NEXT_PHASE_PLAN.md`。

## 1. 产品目的

Study Agent 是一个本地优先、教学法驱动、证据可追溯、能够沉淀长期记忆的学习工作台。

正式学习闭环：

```text
明确学习目标
-> 教学推进
-> 本地资料 / 联网证据
-> 验证理解
-> 记录已确认点和缺口
-> 课后整理
-> 用户确认记忆
-> 标记已整理
-> 下次准确恢复
```

同时支持不进入长期学习闭环的临时任务：

```text
快速问答 / 联网研究 / 临时资料查询 / 闲聊
-> 给出可用结果和有效证据
-> 默认不推进学习状态
-> 用户自行决定是否转为学习目标或保存笔记
```

## 2. 全局原则与边界

1. API Route 只做 adapter；多步业务编排归 Application Service。
2. 多步 LLM 流程必须成为 server-owned、可恢复的 Run。
3. committed state 是产品真值；planned/attempted/failed 状态不得伪装成完成。
4. 写入长期记忆必须由用户确认；推断性 learner profile 默认 pending。
5. 任务意图、教学协议、角色表达、来源策略和记忆资格必须分层。
6. 角色语气不能改变是否联网、事实结论、来源可信度或任务状态。
7. 陌生、新兴或疑似拼写异常的术语先视为“可能真实”，先归一化和检索，不因模型未知而判断不存在。
8. `empty_result / provider_failed / insufficient_evidence / confirmed_absence` 必须严格区分。
9. 当前日期、用户时区和明确时间范围必须进入时效性查询规划；不得无依据注入旧年份。
10. 只有可展示、有效、被采用的来源进入引用计数；空标题、空来源、零分、解析失败和重复占位不得计数。
11. 新建会话不等于归档；总结、记忆、归档和新建都是独立动作。
12. 取消操作按 owner/scope 执行；普通会话切换不能用全局 `cancelAll()`。
13. 本地优先必须表现为实际运行时门禁：是否联网、发送哪些上下文、是否允许本地资料外发。
14. 默认 UI 展示目标、状态、缺口、有效来源和下一步；route code、record ID、top_k、Provider 调试信息进入高级详情。
15. 不建设原生移动端、多用户账号、插件市场、通用爬虫平台或后台长期任务。
16. 不以 GraphRAG 替代基础可追溯 chunk RAG。

## 3. 状态口径

- **已完成：** 当前需求范围已进入真实生产路径，并有针对性回归。
- **部分完成：** 最小正确性或入口已落地，但完整生命周期、持久化、恢复、交互或验收尚缺。
- **过渡实现：** 当前可用，但 owner/state machine 不是最终设计。
- **未开始：** 仅有需求和边界，没有正式生产切片。

## 4. 当前总状态

| Goal | 状态 | 当前已完成 | 主要缺口 |
|---|---|---|---|
| G1 LearningClosureRun | **未开始；存在过渡入口** | after-session preview 可生成 MemoryRun 候选 | 正式 service/run、持久化、幂等、恢复、取消 |
| G2 结构化总结输入 | **未开始** | 已有 committed learning state 和 PedagogyEvalRun 可供消费 | 证据化 prompt、预算、候选来源/置信度 |
| G3 真正结束状态 | **未开始** | 用户可确认 MemoryRun 写入 | summary_status、重复防护、结束态、继续/归档选择 |
| G4 会话导航语义化 | **未开始** | 已有会话列表和恢复入口 | 标题、预览、任务/阶段/缺口/总结状态、搜索分组 |
| G5 学习状态去伪精化 | **部分完成** | 恢复只用 committed state；非学习任务显示任务条 | 启发式 mastery ring 仍存在；最近评估未展示 |
| G6 结构化恢复卡 | **未开始** | 可从历史会话和记忆恢复数据 | 首页仍堆叠三段 Markdown，缺行动性恢复卡 |
| G7 UI 聚焦收敛 | **未开始** | slide-over 抽屉和 dock 已存在 | 一级入口过多，基础/高级/表达设置未分层 |
| G8 窄屏完整可用 | **部分完成** | 会话入口、学习条和基础防溢出已修 | 四入口收敛、文字标签、完整窄屏旅程未完成 |
| G9 新词与时效检索 | **部分完成** | 确定性归一化、UTC 日期、查询变体、空/不可用语义、黄金回归 | 分层搜索、来源评估、答案门禁、真实 E2E |
| G10 ResearchRun | **未开始** | 已有 WebLookupRun、web_search/web_read 和安全边界 | 多步状态机、来源选择、停止原因、恢复、追问复用 |
| G11 任务意图契约 | **部分完成** | 最小分类已接入路由和教学状态；临时任务不推进学习 | 显式覆盖、换题门禁、目标生命周期、线程级真值 |
| G12 过程可见与完整取消 | **部分完成** | 会话切换只取消 chat scope | 服务端阶段事件、研究/RAG/Provider 取消传播和预算 |
| G13 证据与消息完整性 | **部分完成** | 嵌套 RAG 映射、无效引用过滤、正文复制、头像语义、恢复证据 | 统一 EvidenceRef、selected 计数、claim-source |
| G14 资料导入与来源范围 | **部分完成** | 后端校验、版本安全、删除确认 | 每文件状态、临时/长期范围、失败重试、清理策略 |
| G15 会话转换与状态真值 | **部分完成** | 新建不归档、committed 恢复、completed turn 轨迹、scoped cancel | summarized 状态、离开门禁、partial run 恢复 |
| G16 外发数据与隐私 | **部分完成** | web off/ask/auto、云端上下文范围、真实 chat 门禁 | 附件敏感标记、外发摘要、Provider 展示、首次说明 |
| G17 首次使用与可访问性 | **部分完成** | Enter/Shift+Enter、IME、正文复制、头像去重、部分导航修复 | 首次任务入口、恢复卡、focus trap/return、错误动作 |

## 5. 2026-07-12 真实体验审计：`联网看看gpt5.6sol`

### 5.1 原始失败

当时的 Study Agent：

- 原词搜索后扩展出带 `2025` 的旧年份查询；
- 将一次没有结果表述为“没有任何公开信息”；
- 在证据不足时优先猜测 Sonnet、内部项目或伪造；
- 过早要求用户补链接，没有先完成合理名称变体和近期来源检索；
- 证据区出现 `引用 1 / 未命名 / 0.00`。

该失败不是单个搜索词问题，而是三层缺口：

1. **认识边界缺失：** 未知被错误升级为不存在。
2. **研究编排缺失：** 没有名称归一化、日期 grounding、查询扩展、来源评估和停止条件组成的循环。
3. **产品语义缺失：** Provider/检索失败被伪装成事实，空占位被展示为引用。

### 5.2 已落地的最小修复

`7ab8c3d` 已实现：

- 去除“联网看看/查一下”等搜索指令，提取聚焦查询；
- 对紧凑 GPT 型号做通用连字符/空格/大小写归一化；
- 保留 raw query，并生成规范化和原始变体；
- 注入当前 UTC 日期；只有用户表达 latest/recent/today 时生成相应 freshness；
- 搜索结果返回结构化 `ok / empty / unavailable / invalid_query` 语义；
- 工具提示明确：空结果和不可用不是不存在证明；
- `gpt5.6sol` fixture 固定日期回归，不硬编码产品存在性结论。

### 5.3 仍未封板

- 当前 normalizer 不是完整 `WebResearchContext`；时区和显式历史范围仍需统一模型。
- 尚无 7 天 -> 30 天 -> 1 年的受控扩展与停止条件。
- 尚无 SourceAssessment、selected/rejected sources 和 claim-source 映射。
- 尚无正式 ResearchRun，刷新/重试/追问不能复用完整研究状态。
- 仍需真实应用路径手工验收，不能只依赖 fixture。

## 6. 全流程体验审计基准

每个功能必须沿完整用户旅程验收，而不只检查接口返回：

```text
首次进入
-> 选择或表达任务
-> 系统确认任务契约
-> 准备阶段真实可见
-> 用户可取消
-> 返回答案/教学动作和有效证据
-> 连续追问复用上下文和研究结果
-> 上传资料时范围和状态明确
-> 切换/新建不丢真值、不误归档、不误取消其他任务
-> 按任务类型整理结果
-> 用户确认后写入记忆
-> 下次准确恢复目标、缺口、证据和未完成任务
```

任务默认语义：

| 用户行为 | TaskIntent | 学习状态 | 默认收束 |
|---|---|---|---|
| 联网看看某个新模型 | research | 不建立长期掌握目标 | 不显示学习总结；未来可保存研究笔记 |
| 简单解释一个稳定概念 | quick_answer | 默认不推进 | 可选笔记 |
| 带我系统学习某主题 | learn | 建立/继续目标 | 学习总结 |
| 我来解释，你检查 | explain_back | 费曼状态机 | 误区、修补点、验证结果 |
| 帮我修改项目并跑测试 | project_execution | 项目状态机 | 修改、验证、风险、下一步 |
| 闲聊/情绪整理 | conversation | 不建立知识掌握状态 | 默认不生成画像 |

## 7. P0 验收门槛与当前结果

| 门槛 | 当前结果 | 说明 |
|---|---|---|
| 新词联网不无依据输出“不存在”、不注入旧年份 | **部分通过** | 代码和 fixture 已修；真实应用路径尚未记录验收 |
| 临时 research 不推进学习状态 | **通过（最小切片）** | task-aware evaluation/engine 保留 committed state |
| 新建会话不自动归档 | **通过** | 已移除 startNewSession 中的自动 archive |
| 中断/失败后顶部只读 committed state | **通过（核心）** | 恢复优先 committed state，阶段轨迹过滤 completed turn |
| 切换会话不取消无关上传/记忆/研究 | **通过（前端 owner 核心）** | chat invalidate 替代 cancelAll；完整服务端取消归 G12 |
| 用户能关闭联网并控制云端上下文 | **通过（最小策略）** | attachment-level 限制仍未完成 |
| 引用数等于有效采用证据数 | **部分通过** | 本地 RAG 无效占位已过滤；统一 web selected evidence 未完成 |
| 欢迎、复制、角色、基础键盘无明显错误 | **部分通过** | copy/IME/avatar 已修；首次入口、焦点、错误动作未完成 |

**结论：** P0 高风险状态污染路径已被显著收紧，但 P0 还不能宣布完整封板。进入 G10/G1 前应先跑一次真实 P0 旅程，并修复阻断性结果。

## 8. G1：课后总结成为正式可恢复服务流程

**目的：** 将 after-session 从 route 内临时编排升级为 server-owned `LearningClosureRun`。

**当前：** 过渡实现已完成：API 可生成 MemoryRun preview，按钮可打开候选。

**剩余：**

- `LearningClosureService` 统一 owner；route 只创建/读取/重试 run；
- 持久化 source thread/version/last completed turn、committed snapshot、generated result、MemoryRun、status/error；
- 状态机：created -> collecting -> generating -> preview_ready -> committing -> completed/failed/cancelled；
- `closure_source_hash` 幂等，相同线程版本复用 preview；
- 失败/取消可恢复，不重复模型成本；
- 消费 G11 ClosureEligibility，不适用任务不得生成学习总结。

**验收：** 刷新后恢复阶段；相同版本重复点击不重调 LLM；失败重试继承已完成步骤；research 不进入学习总结。

## 9. G2：总结输入使用结构化教学状态

**目的：** 总结基于可靠教学证据，而不是让 LLM 重新猜测整段聊天。

**剩余：**

- 优先输入 committed objective/confirmed points/gap/phase/protocol；
- 引用最终 PedagogyEvalRun 决定、evidence IDs 和 evaluator versions；
- 最近 N 轮完整，更早内容服务器摘要或丢弃；
- learner profile 推断默认 `learner_pending=true`；
- 每条候选保存来源、置信度、对应 confirmed point/eval；
- 按任务生成学习总结、研究笔记、项目收束或 not applicable。

**验收：** provider/parse 失败和未提交回合不能成为“已掌握”；长会话不爆 prompt；候选可解释来源。

## 10. G3：真正的结束与总结状态

**目的：** 写入记忆后真正结束本次学习，而非只生成候选。

**剩余：**

- commit 后设置 `summary_status=summarized`；
- 显示“本次学习已整理”；
- unchanged thread version 禁止重复 closure；新增回合后可重新整理；
- 写入后选择继续当前 / 归档并新建；
- 按 eligibility 使用整理学习 / 保存研究笔记 / 收束项目 / 无需整理。

**边界：** 绝不自动归档，不删除会话。

## 11. G4：会话导航语义化

**剩余：**

- ChatThread 增加 title、objective/research summary、last preview、task intent、phase/gap、summary status、updated_at；
- 标题由目标、研究主题或首条消息生成；允许手改且不覆盖；
- 侧栏显示任务/阶段/缺口/时间/状态；
- 支持按时间、状态、任务搜索和分组。

**验收：** 侧栏不再以内部文件名/ID 作为主要标题，历史数据兼容可见。

## 12. G5：学习状态展示去伪精化

**当前：** committed truth 和非学习任务条已落地；`LearningPanel` 仍计算 `deriveMastery` 并绘制 conic-gradient ring。

**剩余：**

- 折叠态：目标 -> 阶段 -> 缺口/下一步 -> 最近评估；
- 移除启发式进度环；
- 显示已验证 / 待验证 / 需重讲 / 待语义复核；
- planned/attempted 只作单独提示，不覆盖主状态；
- research/quick_answer 使用研究/回答状态，不显示学习阶段。

## 13. G6：结构化恢复卡

**当前：** 首页仍展示 current_focus/progress/summary 三段 Markdown。

**剩余：**

- 新用户显示快速问答、系统学习、联网研究、项目、资料入口；
- 老用户显示任务/目标、确认点或采用来源、缺口、下一步；
- 操作：继续这里 / 开始新主题；
- partial/interrupted run 提供继续、重试、放弃；
- 数据来自 committed learning、ResearchRun 或项目状态 + G4 title。

## 14. G7：UI 聚焦收敛

**剩余：**

- 一级 dock 收敛为上传资料 / 会话 / 当前任务收束 / 更多；
- 来源、设置、群聊、新闻、工具、时间线进入更多；
- 设置分基础 / 高级 / 表达；
- MemoryPanel 普通态不展示 `current_focus.md` 等内部文件名；
- 顶部隐藏 record ID、route code、内部 profile；
- 不删功能，只降低次要功能默认曝光。

## 15. G8：移动端与窄屏完整可用

**当前：** 窄屏会话入口和基础 flex-wrap 已有。

**剩余：**

- 顶部任务/目标/研究状态/缺口一行可读并可展开；
- 四个一级动作全部可达；
- 非 hover 环境有可见标签或正确 aria name；
- 抽屉、输入、收束和来源旅程在窄屏完整验收。

## 16. G9：新兴术语与时效性联网可靠性

**当前已完成：**

- raw/focused/canonical query；
- 通用紧凑型号归一化；
- 当前 UTC 日期和 freshness markers；
- 查询变体；
- structured empty/unavailable/invalid semantics；
- 固定 fixture 黄金回归。

**剩余：**

- 统一 WebResearchContext：时区、显式历史范围、conversation topic；
- 精确词 -> 官方 -> 高可信近期媒体 -> 更宽别名的分层计划；
- 7/30/365 天受控扩展和 stop reason；
- SourceAssessment 和有效来源门禁；
- answer-first，证据不足时不自由猜测；
- UI 展示规范化查询、实际尝试、窗口、采用来源；
- 可选真实联网 smoke test，不让 CI 依赖实时互联网。

## 17. G10：多步联网研究成为 ResearchRun

**目的：** 将搜索 -> 判断 -> 扩展 -> 阅读 -> 交叉核验 -> 回答变成正式服务流程。

**设计约束：** 扩展现有 WebLookup ownership，不能并存两个含义重叠的 run。

**剩余：**

- 状态机：created/normalizing/searching/assessing/expanding/reading/synthesizing/completed/partial/failed/cancelled；
- 持久化 query context、attempts、selected/rejected sources、time window、provider status、stop reason、confidence、answer；
- Planner 基于当前证据决定停止、改写、扩大窗口、官方源、阅读或追问；
- 查询/阅读/时间/成本预算；
- 幂等恢复和 retry 继承；
- follow-up 复用上一 run 的实体和来源；
- 默认 UI 只显示答案和有效来源，高级区显示完整轨迹。

## 18. G11：任务意图与结果契约

**当前已完成：**

- TaskIntent 最小分类；
- research/quick answer/conversation 不更新学习状态；
- explain-back/project/learn 进入对应长期路径；
- 活跃学习中的低风险追问可继承目标；
- route snapshot 和前端任务条/closure visibility 消费 task contract。

**剩余：**

- 用户显式覆盖 TaskIntent；
- 明显换题门禁；
- 目标 proposed/confirmed/modified/suspended/completed/abandoned；
- thread-level task/source/closure 真值与旧会话兼容；
- research 指定苏格拉底讨论仍不自动写入长期掌握，除非用户确认转目标。

## 19. G12：预回答过程可见与完整取消

**当前：** 前端会话转换已使用 chat scope invalidation。

**剩余：**

- routing/evaluating/retrieving_local/normalizing/searching/assessing/reading/composing/streaming/saving 事件；
- 首 token 前真实状态，禁止假百分比；
- 高级区显示 run、耗时、次数、预算、错误；
- cancel 传到 ResearchService、RAG 和 Provider 能力边界；
- 中断保留可用部分，可继续/重试/放弃；
- 取消后不得提交 completed answer 或推进学习状态。

## 20. G13：证据与消息完整性

**当前已完成：**

- 从 `result.chunk.title/source_path` 读取本地来源；
- 空/零分/重复占位过滤；
- 实时和恢复 turn evidence 基础一致；
- 复制纯正文；头像装饰语义。

**剩余：**

- 统一 EvidenceRef：id/type/title/source/domain/published_at/score/selected/rejection/supported claims；
- 分开查询次数、阅读页数、采用 web 来源、本地引用；
- candidate/read/selected/rejected 分层；
- claim-source 对应；
- web 与本地稳定去重；
- 刷新前后计数和采用来源完全一致。

## 21. G14：资料导入与来源范围

**当前：** 后端有安全校验、版本化写入、partial stage；删除需要确认。

**剩余：**

- 每文件 uploading/validating/parsing/chunking/indexing/ready/partial/failed；
- 上传入口和结果在同一可见流程；
- 当前会话临时附件 vs 长期知识库；
- active source scope 和实际使用资料可见；
- 从这些资料开始提问和推荐问题；
- 失败文件单独重试；重建说明影响并二次确认；
- 临时附件禁止联网/云端/记忆和会话结束删除。

## 22. G15：会话转换与状态真值

**当前已完成：**

- 新建会话不归档旧会话；
- committed state 恢复；
- phase trail 只读 completed turns；
- ordinary transition 只 invalidate chat；
- 删除知识文档显式确认。

**剩余：**

- active/summarized/archived 迁移；
- 中断回合 planned state 提示；
- 切换生成中的 chat 明确提示；
- Memory preview、partial research、未完成上传的离开门禁；
- 先整理 / 直接新建 / 取消；
- 归档后明确创建或选择下一会话。

## 23. G16：外发数据与隐私控制

**当前已完成：**

- runtime web off/ask/auto；
- cloud context question-only/recent-chat/allow-local-evidence；
- 前后端真实门禁；
- ask 模式本轮确认；
- 本地检索可保留审计但不一定进入云端 prompt。

**剩余：**

- SourcePolicy/ProviderPolicy 线程持久化和任务覆盖；
- 外发摘要：查询、历史、本地资料、Provider；
- 附件仅本地/禁联网/禁记忆/允许云端；
- EvidenceTrail 显示外发类型但不泄露正文；
- 首次自动联网/云端资料说明；
- ask 选择按会话合理记忆，避免每个底层请求弹窗。

## 24. G17：首次使用、消息操作与可访问性

**当前已完成：**

- Enter/Shift+Enter 和 IME composition；
- Assistant 正文复制；
- 中断继续/重试/复制已有入口；
- 角色头像空 alt/aria-hidden；
- 部分抽屉入口和欢迎语修复。

**剩余：**

- 新用户一屏选择五类任务；
- 老用户结构化恢复卡；
- 顶部移除 route/ID/profile；
- 输入行为可配置；
- 每条 Assistant 明确复制和重试；
- focus trap、Escape、关闭后焦点返回、背景不可操作；
- 移动端可见标签；
- 全局错误提供重试/设置/详情动作。

## 25. 执行顺序

### 阶段 A：P0 真实旅程复核

1. `gpt5.6sol` 应用路径。
2. 临时 research 不污染学习。
3. 新建/切换/取消 scope。
4. web policy 和 cloud context 实际外发。
5. refresh 后 committed state 和 evidence 稳定。

### 阶段 B：正式可恢复 Run

1. G10 ResearchRun。
2. G1 LearningClosureRun。
3. G12 阶段事件、预算和取消传播。
4. G14 资料范围与逐文件状态。

### 阶段 C：闭合学习和会话

1. G2 + G3。
2. G4 + G6。

### 阶段 D：产品收敛

1. G5 去伪精化。
2. G7 信息架构。
3. G8 窄屏。
4. G17 完整可访问性和首次使用。

## 26. 跨项风险

- G1/G3/G4/G15 都涉及 SQLite 迁移，必须递增 schema version 并兼容历史 ledger。
- G2 原始聊天预算过小会丢信息，过大会增加成本和误判；需小样本验证。
- G4 自动标题必须允许手改且不覆盖用户版本。
- G7 移动入口时必须回归所有抽屉可达。
- G9 归一化必须保留 raw query，避免把真实新名称纠错成旧实体。
- G9 当前日期不能覆盖用户明确历史范围。
- G10 必须扩展现有 owner，避免 WebLookupRun/ResearchRun 双轨。
- G10 来源排名不能等同媒体白名单；必须 fixture + 人工复核。
- G10 answer/source/version 必须同一恢复语义。
- G11 误分类时采用低风险 quick-answer 临时路径，并允许用户纠正。
- G12 只能显示真实阶段，取消后不得晚到提交 completed。
- G13 web/local 同源需要稳定去重键。
- G14 临时索引生命周期必须与长期知识库隔离。
- G16 ask 模式要避免提示疲劳，不同 Provider 能力由统一策略层适配。
- G17 输入法、抽屉焦点和窄屏标签必须做真实浏览器验收。

## 27. 验证要求

每个切片必须同时完成：

- 目标测试先行；
- 后端全量 pytest；
- 前端全量 Vitest；
- Vite production build；
- 涉及存储时做迁移/兼容/失败恢复；
- 桌面和窄屏人工旅程；
- 刷新前后状态、证据和来源比较；
- 同步更新本文件、`ARCHITECTURE_STATUS.md`、`NEXT_PHASE_PLAN.md` 和对应专项计划。

连接的 GitHub 状态接口未返回审计 head `7ab8c3d` 的 workflow run 或 combined status，因此本次文档只确认代码/提交级证据，不宣称远程 CI 已验证。
