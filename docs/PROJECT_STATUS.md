# Study Agent 当前状态

> **唯一冷启动/交接入口。** 本文保留已核实的现状、开放阻断和下一执行片；细节证据在 [2026-11-17 收口记录](research_quality/RETRIEVAL_LEAN_EXECUTION_20261117.md)、对应 PR、精确提交 CI 和 Git 历史。稳定规则以 [AGENTS.md](../AGENTS.md)、[产品迭代规则](PRODUCT_ITERATION_POLICY.md) 为准。
>
> **产品目标**：体验接近 ChatGPT 的通用聊天与研究 Agent，覆盖自然聊天、自主研究、持续交互、智能 UI、多模态和工具执行；教学是专业场景。**部署仍限可信环境的单用户**；多用户身份/数据/费用隔离未实现。

## 0. Current Handoff（2026-11-20，冷启动）

> **当前收口**：#572 波次进度上下文已在精确 HEAD `6191d8f6`、CI `44696107007` 成功且无阻断审阅后合入 `main@93ec4c7`；#573 评估结果上下文原 HEAD `37df4222`、CI `44697525596` 同样成功，但主线变化造成文档并列插入冲突。已保留双方交接、将 #573 重挂到新主线并验证组合影响集 **155 passed / 89.70s**；仍须新精确 HEAD CI 才能合并。后续只在两个上下文都收口后开始新语义片。

### 2026-11-20 研究波次增益与发现进度结算收归实时上下文（独立 P3 静态片）

- **范围**：新增 `ActiveWaveProgressContext`，将 `execute()` 尾部交错的 Evidence Gain、逐 claim/gap 饱和计数、lead 发现增量判定和 `metrics.wave_progress` 有界记账统一收归单一执行上下文。lead 读取前的三个计数保存为只含整数的 `DiscoveryProgressSnapshot`，结算时重新读取唯一 `ActiveRuntimeLiveValues` 的最新 state/cursor/context，沿用原 `_wave_gap_provenance` 来源归因；删除执行器重复的 `_is_discovery_candidate`，执行器仅保留两次显式调用。与 `ActiveWaveSettlementContext` 的后续 steering/停止决定明确分工。
- **冻结契约**：以持久化波次开始时的原 state 为 gain baseline、以 `active_gap_ids` 为处理目标；新候选/域线索只能延迟本波饱和，**不能假冒证据增益，也不能重置既有 no-gain 计数**。无进展时逐 claim/gap 只增加一次，增益历史总是追加；诊断字段、最近 `MAX_RESEARCH_WAVES` 条截断、旧列表别名和 checkpoint 前写入顺序均保留。执行器原 `checkpoint() → research-window end → checkpoint() → timing flush → wave settlement` 调用位置完全不动；不改变恢复 schema、读取/模型/预算结算、证据门禁及发布资格。
- **验证**：新增 7 项直接负控，覆盖无进展饱和、三种发现信号、真实证据进展、跨 checkpoint live 重绑与有界诊断、归因异常前不写入；初始 6 项与主动研究执行器、波次基线/停止/settlement、checkpoint 会话及预算影响集 **119 passed / 98.19s**，随后补充异常负控并单独运行新专项 **7 passed**。全库 Ruff、编译、差异检查通过，mypy **115/125、无新增**。本片 `priority=P3`、`loop=static`、`owner=research/wave-progress`、`dynamic_evidence=not_run`、`budget_authorization=not_applicable`、`decision=engineering-only`；无真实搜索或付费模型，不能据此声称用户回答质量提升。
- **交接**：起点 `main@472cc7b`，独立分支 `codex/research-wave-progress-context-20261120`。此改动仅创建清晰的可变状态所有权、未迁移持久化权威；须以新 PR 的精确 HEAD CI 与无阻断审阅验收。#570 读取链测试、#562 late-tail 诊断、#571 旧研究记忆退役各有独立 PR，不挪用其未合代码。下一片优先收口开放 PR，再看 assessment 结果缓存与外部调度的可变状态交界，不扩张为模型预算重写。
- **主线整合复核**：原 PR HEAD `d0e9d3c4` 精确 CI `44611274220` 成功；随后 #570 和 #562 依次合入 `main@58b5894`。本片生产代码及专项测试自动合并，唯一冲突为 handoff 并列新增段落，已完整保留；组合下主动研究执行器、wave progress、late-tail 诊断、波次基线/settlement、checkpoint、读取链、检索结果 **119 passed / 77.84s**，全库 Ruff、编译、差异检查通过，mypy **115/125、无新增**。重挂后的精确 PR HEAD CI 尚须重新验收，不能沿用 `d0e9d3c4` 绿灯。
- **最终合并**：PR #572 精确 HEAD `6191d8f6589b02e5bb9db2a77e44a8a2e0a4570f` 的 CI `44696107007` 成功、reviews/threads 均为空，使用 SHA 保护 squash 合并为 `main@93ec4c721cc4af673f223b5baf7bfd8ce4757040`。以上历史“尚须验收”已由此状态更新取代。

### 2026-11-20 候选评估恢复缓存与排名归档收归显式上下文（独立 P3 静态片）

- **范围**：新增 `ActiveAssessmentResultContext`，把每波原本散落在执行器内的既有评估缓存恢复、逐 claim 的历史排名复用、成功评估合并与两份缓存投影归为单一 wave-local 工作状态。原普通 assessment 与 `_late_admission_tail` 共用 `record_assessment_result()`，集中实现 `旧结果合并 → rank_candidate_pool → selection trace 排名 → claim_rankings → assessments 缓存 → assessed_inputs 缓存 → 持久化上下文字典键`。原 `_assessment_store`、`_assessment_inputs_store` 与 `_ranked_from_dict` 实现和两枚持久化键定义迁入新模块；执行器保留同名键的导入出口，避免外部引用形状变化。
- **冻结契约**：在每波 `checkpoint(stage="assessing")` 后只恢复一次本波缓存副本，继续从 saved ranking 排除已评估 candidate；在可能的 checkpoint/context 重新绑定后，成功归档写入唯一 `ActiveRuntimeLiveValues.current_context()` 的最新字典；两个原有共享缓存和 `claim_rankings` 的对象引用仍由 late-tail、读取计划、lead 计划共同消费。原模型 policy/attempt/budget 准入、候选窗口筛选、普通/late-tail 模型调用、异常归档、checkpoint 时点/次数、候选排序、审计字段、来源与 Evidence Gate/发布完全不动；排名失败时不提前写入归档缓存。
- **验证**：新增 6 项直接负控覆盖持久化排名恢复与 alias、跨 checkpoint context 重绑、普通与 late-tail 两入口同一投影、无效旧缓存、排名失败前无部分写入；完整主动研究执行器、late-tail、候选 pipeline/ranking、选择轨迹、checkpoint 和模型尝试影响集 **139 passed / 74.33s**，专项 **6 passed**。全库 Ruff、编译及差异检查通过，mypy **115/125、无新增**。本片 `priority=P3`、`loop=static`、`owner=research/assessment-results`、`dynamic_evidence=not_run`、`budget_authorization=not_applicable`、`decision=engineering-only`；无真实搜索、付费模型和质量动态比较。
- **交接**：起点 `main@58b5894`，独立分支 `codex/research-assessment-results-context-20261120`；#572 波次进度 PR 的精确 HEAD CI `44696107007` 在本轮首次查询仍 `in_progress`，未合并，当前片不挪用其代码。该分支应独立取得精确 PR HEAD CI 与无阻断审阅，之后再与 #572 主线先后关系整合。下批先收口开放的上下文 PR，再考虑读计划与评估结果消费端的隐式参数，不扩大为模型预算/恢复 schema 迁移。
- **#571 主线重挂**：旧研究记忆栈退役 #571 已入 `main@c58ed4e`；本片重挂无冲突，差异仍只包括评估结果上下文、执行器归档调用、专项测试和本交接。新基线下再次验证完整候选评估与运行时影响集 **139 passed / 77.93s**；全库 Ruff、编译、差异检查通过，mypy **115/125、无新增**。该本地新提交和后续远端精确 PR HEAD 仍须独立 CI 验收。
- **#572 后续主线重挂**：#573 原精确 HEAD `37df42227487707ab19d1b28373715dc1fc386fb` 的 CI `44697525596` 成功且无阻断审阅。#572 合并后主线为 `93ec4c7`，仅此 handoff 同位置插入冲突；生产代码自动合并。本批将保留两批已冻结契约，补跑组合后的主动研究执行器、波次结算与评估归档影响集；新的 PR HEAD 必须单独完成 CI 才可合并。
- **组合验证完成**：基于 `main@93ec4c7` 重挂后的 #573 候选包含两组上下文；主动研究执行器、late-tail、候选 pipeline/ranking、选择轨迹、checkpoint、模型尝试、评估归档、wave progress/baseline/settlement 共 **155 passed / 89.70s**。全库 Ruff、编译和差异检查通过；mypy **115/125、无新增**。无真实模型/搜索或预算支出，`decision=engineering-only`。新远端 PR HEAD 的 CI 成功和无阻断审阅仍为最终合并门禁。

### 2026-11-20 读取链五组集成测试复用现有执行场景（独立 P3 静态减负片）

- **范围**：将 `test_active_research_runtime.py` 中五组历史 cutover 测试的重复环境变量、SQLite 仓库、待运行任务、模型/读取网关组装，统一复用同文件既有的 `_a2e_run()` 真实执行器场景。保留五个独立用例及全部断言，分别覆盖 HTTP tier 回退后单源、原生读取足够时不回退、tier 禁用、Wigolo 真实调用按次结算、候选/后端审计唯一性。原执行器路径和 run ID 保持不变，不再重复维护同一套场景搭建。
- **冻结契约**：测试专用工厂仍对每例使用独立 SQLite 和 `_TrackingRepository`、原 `_StructuredClient`、原生读取模拟与 Wigolo backend；明确保留禁用 tier 的 `escalation=None`、调用前清空 HTTP envelope 的次序及全部后续计费断言。工厂额外关闭未在这些用例中开启的 breaker 开关，避免测试受前序环境泄露影响。**不改生产代码**，不改研究状态/恢复、checkpoint 次数或顺序、外部调用、预算结算、证据门禁与发布。
- **证据/边界**：改动前五个用例 **5 passed / 6.13s**；改动后完整主动研究执行器、读取链单一权威、升级配置与读取调度影响集 **110 passed / 94.67s**（包含原五例）。测试文件 **+32/-56，净删 24 行**；全库 Ruff、编译、差异检查及 mypy 基线 **115/125、无新增**。本片只收敛测试造景，`priority=P3`、`loop=static`、`owner=retrieval/tests`、`dynamic_evidence=not_run`、`budget_authorization=not_applicable`、`decision=engineering-only`；不能由静态测试净减行数推断真实研究质量提升。独立分支 `codex/read-chain-test-scenario-reuse-20261120`，基于 `main@d12766b`；精确 PR HEAD CI 和审阅仍须单独验收。
- **主线整合更新**：原 PR HEAD `ecc742da` 的精确 CI `44599153892` 已成功，但 #556、#569、#563、#561 进入主线后旧 HEAD 不再可合并。现重挂至 `main@2c58833`，仅并列保留 handoff 文本，测试代码无冲突；重新验证主动研究执行器、读取链单一权威、HTTP 升级与读取调度 **110 passed / 95.29s**，全库 Ruff、编译及差异检查通过，仍须新精确 HEAD CI 和审阅验收。
- **波次恢复基线后续重挂**：提交前 `main` 又合并 #564，已将本片重挂至 `main@cc82b44`（测试代码依然零冲突）；在该组合下补测本片五项读取链、波次恢复上下文五项、真实崩溃恢复及单一读取权威，共 **17 passed / 11.19s**。此前 110 项影响集属于 #564 之前的基线，不能单独充当最新主线的完整验证；以本 PR 新精确 HEAD CI 补齐门禁。
- **#566/#567 主线整合**：#567 检索结果上下文与 #566 四阶段取消回归进入 `main@472cc7b` 后，本片再次重挂；仅 `PROJECT_STATUS.md` 的顶部交接发生并列新增冲突，已保留三批交接，执行器测试代码自动合并。主动研究执行器、检索结果、读取链单一权威、读取调度、恢复波次基线及 checkpoint 会话联合影响集 **111 passed / 96.73s**；全库 Ruff、编译和差异检查通过，mypy **115/125、无新增**。重挂后的精确 PR HEAD 必须重新等待 CI 和审阅收口，旧 CI 不再适用。
- **下一片**：先收口开放的恢复/预算/搜索上下文 PR；下次只清理剩余有明确重复的数据搭建，不重新包装已独立拥有的上下文。

### 2026-11-20 主动研究四阶段取消回归共用场景搭建（独立 P3 静态测试片）

- **范围**：原 `test_active_research_runtime.py` 的 claim 规划、搜索后端、读网关、证据提取四项取消测试分别重建 SQLite 仓库、pending 研究运行、测试客户端和服务，再执行同一个取消终态断言。现在使用 `stage=model/search/read/extract` 参数化保留四项独立场景及各自唯一 run ID/数据库，按阶段只注入对应的取消回调。测试净删 **36 行**，无新辅助层、无删减四种中断时机。
- **冻结契约**：模型规划依然在第一次模型调用中取消；搜索场景依然在 `search_exact()` 内取消后返回原搜索结果；读取场景依然在读网关入口取消；提取场景只在第三次结构化模型调用中取消。四种路径都经过真实 `ClaimEngineDispatchWebLookupService.execute()` 和持久化 SQLite，继续核对 `cancelled` 状态/阶段、`user_cancelled` 原因及模型/外部尝试 inflight 清空。**不更改**生产代码、注入时点、恢复游标、checkpoint、预算入账、证据或发布；不把四种取消语义折叠成单一测试。
- **交接**：原四项 **4 passed**，参数化后四项仍 **4 passed**；完整主动研究执行器、研究取消、浏览器断联取消及 PR143 取消栅栏影响集 **97 passed / 87.00s**。全库 Ruff、测试编译和差异检查通过，mypy **115/125、无新增**。基于 `main@6fdc6cc`，独立分支 `codex/research-cancel-stage-fixture-20261120`；`priority=P3`、`loop=static`、`owner=research/tests`、`dynamic_evidence=not_run`、`budget_authorization=not_applicable`、`decision=engineering-only`。不宣称真实研究质量改善；独立 PR 的精确 HEAD CI 与审阅为合并门禁。
- **主线整合更新**：原 PR HEAD `ebc9b312` 的精确 CI `44593124965` 已全绿；随着 #556、#569、#563、#561 合并，重挂到 `main@2c58833`。唯一冲突是本 handoff 同位置插入段落，已同时保留主线和本片记录，取消测试代码无冲突；重新跑完整执行器及四组取消相邻集 **97 passed / 88.40s**，全库 Ruff、编译及差异检查通过。旧 HEAD 绿灯不得替代重挂后的精确 PR HEAD CI。
- **#564 交叉验证**：随后恢复波次基线上下文 #564 合并，本片再次重挂到 `main@cc82b44`，测试代码仍无冲突；取消四阶段、真实崩溃恢复、波次基线上下文及取消栅栏相邻集 **22 passed / 5.42s**。之前 `main@2c58833` 的 97 项全模块验证与本次交叉负控各自限定基线；新精确 PR HEAD 的 CI 仍是最终合并门禁。
- **下一片**：在研究提取准入与失败归档的并行 PR 独立收口后，再从执行器中已确认重复的成功/失败来源摘要写入找收敛机会，优先净删实际重复路径。

### 2026-11-20 无生产调用方的历史研究记忆整链退役（独立 P3 静态片）

- **调用图/范围**：`ResearchMemoryService` 无 `src/`、工具入口、API 路由或应用装配调用方；唯一实例化处是 `tests/test_research_memory.py`。移除该服务、专属 `ResearchMemoryRepository`、`persistent_memory.py` 的历史记录模型及整份专项测试，连同 `research_memory` impact set、`research-memory-stack` stage gate 和其余阶段门里对已删除测试的引用。现行研究状态、证据投影、恢复、发布没有调用这套持久化历史线索能力。
- **仅保留真实调用**：离线 `studyctl research inspect` 原来从历史模型文件借用 `known_research_evidence_ids`；现在统一由现行 `src/web/research/state.py` 计算允许证据 ID，研究调度与离线诊断共用同一份权威快照映射，不保留历史记忆适配层。`test_studyctl_research.py` 的真实运行状态样例改在自己的测试内建立，不再跨测试导入已退役的专用场景。
- **数据/冻结边界**：SQLite v24 迁移是已经发布的不可变历史，`research_memory_*` 旧表定义保留以维持旧库 schema 版本序列及现存数据，不引入 DROP TABLE、回填或迁移重排。没有新增产品入口、旧模块兼容导出或新配置。恢复检查点、预算结算、来源身份、证据权威与研究发布均不变。`priority=P3`、`loop=static`、`owner=research/retired-memory`、`dynamic_evidence=not_run`、`budget_authorization=not_applicable`、`decision=engineering-only`；以精确 PR HEAD CI 和审阅为合并门槛。

### 2026-11-20 G13 旧证据归一化包与专属测试成组退役（独立 P3 静态片）

- **可达性与范围**：`src/evidence/evidence_ref.py` 仅被 `tests/test_evidence_ref.py` 导入；其 `normalize_evidence`、RAG/工具/研究归一化、去重和过滤函数在现行 `src/`、`tools/`、前端与 CI 中均无调用。删除整份 195 行旧实现、106 行专属测试及空 `src/evidence/__init__.py`；无现行路由、导出适配层、配置项或阶段门条目需要保留。历史 RQCE 任务书仍只作为当时入口快照，不作为当前可用模块清单。
- **权威与负控**：正式 ChatTurn 证据事实与选择/拒绝原因仍由 `src/domain/evidence.py` 的 `EvidenceRefV1`/`EvidenceSnapshotV1` 及其现行回归测试拥有；研究证据验收、SourceEvidence、引用发布和预算均不变。本次只去掉孤立的历史归一化实现，不删除任何实用数据路径，也不引入兼容壳。`priority=P3`、`loop=static`、`owner=evidence/legacy-projection`、`dynamic_evidence=not_run`、`budget_authorization=not_applicable`、`decision=engineering-only`。
- **验收边界**：验证现行 `test_evidence_snapshot*`、`test_chat_turn_evidence_snapshot.py`、`test_active_research_evidence_projection.py` 和 `test_verified_citation_projection.py`，并由精确 PR HEAD CI 守护全库无旧模块引用；不宣称研究质量提升。

### 2026-11-20 提取目标恢复准入归入现有结果缓冲区（独立 P3 静态片）

- **范围**：`ActiveResearchResultBuffers.admit_extraction_target()` 从已有的 `selected_sources` 活记录查找候选，核对实际读取成功状态，再检查逐 claim 的 `eligible` / `extractor_failed` 完成标记和旧单项 `extraction` 兼容标记。执行器的提取循环只请求符合条件的来源，随后保持原有模型预算检查、提取、归档和 checkpoint 操作；删去只在此处使用的 `_source_by_candidate`、`_read_status` 两个孤立 helper。**未新增上下文类或第二份来源快照**。
- **冻结契约**：保持首次匹配候选的查找语义、同一来源字典的对象别名和 `read.status == read` 限制；成功读取后即使某 claim 被跳过，也仍在任何模型调用前创建原 `extractions` 映射。已有逐 claim 成功/失败不重复提取，未完成状态可重试；仅当本 claim 没有逐项记录时才考虑旧单项摘要，并且仅对同 claim 的成功/失败跳过。**不改**恢复游标格式、检查点数量/时点、预算入账/结算、模型尝试编号、外部检索读取、证据资格与发布。
- **测试与交接**：新增结果缓冲区直接测试 **12 passed**，覆盖同源引用、未读来源不写入、逐 claim 完成/重试、旧单项兼容与重复候选的首次匹配；主动研究执行器、恢复、证据接纳、checkpoint、波次结算及发布合计 **121 passed / 103.38s**（包含上述 12 项）。全库 Ruff、编译、差异检查通过，mypy **115/125、无新增**。初始基线 `main@76b42a5`，PR 创建时因独立前端 #560 合并，已重挂至 `main@6fdc6cc`；分支 `codex/research-extraction-target-admission-20261120`。`priority=P3`、`loop=static`、`owner=evidence/extraction-admission`、`dynamic_evidence=not_run`、`budget_authorization=not_applicable`、`decision=engineering-only`。精确 PR HEAD CI 尚待核验；不将离线静态回归宣称为真实研究质量改善。
- **下一片**：待此片完成精确 CI 与审阅后，再沿已有的提取成功/失败上下文逐步清理失败归档中的隐式写入；不与仍待独立收口的提取失败归档 PR 混合。

### 2026-11-20 研究波次基线的恢复状态收归显式上下文（独立 P3 静态片）

- **现状/范围**：执行器每波开始时原先直接连续读写 `live.cursor.wave_id/active_gap_ids`、`live.context[claim_engine_wave_baseline]`，随后调用 checkpoint 并解析持久化基线。新增 `ActiveWaveBaselineContext`，只接收唯一 `ActiveRuntimeLiveValues` 和既有有序 gap 选择器；`begin_if_needed()` 负责波次身份与初始状态快照，`restore()` 总从最新 live context 读取并按原证据 ID 允许表还原状态。执行器仍在原条件下、原位置调用一次 checkpoint，诊断调用者标签也不变；不缓存 checkpoint/恢复/steering 可能重绑的旧字典。
- **冻结契约**：新波写入顺序仍是 `wave_id + active_gap_ids → 基线序列化 → checkpoint → 基线反序列化`；同一波恢复绝不覆盖读/提取前基线（防止崩溃后 Evidence Gain 假阴性），缺失或无效基线仍抛 `ValueError`。序列化失败时 cursor 已更新、context 尚未写基线的部分效果保持一致。没有第二个预算/状态/持久化权威；模型与搜索/读取次数、checkpoint 次数/时点、预算结算、Evidence Gate 与发布均不变。
- **静态证据**：新增 5 项可直接运行的波次边界负控（初始/重复波、checkpoint context 重绑、缺损基线和序列化部分失败），`python -m unittest discover -s tests -p test_research_runtime_wave_baseline.py` **5 passed**。既有 `test_crash_after_extraction_preserves_wave_baseline_and_gain` 继续负责真实 SQLite 崩溃恢复/读取次数集成验证，需由精确 PR HEAD CI 覆盖。`priority=P3`、`loop=static`、`owner=research/state-recovery`、`dynamic_evidence=not_run`、`budget_authorization=not_applicable`、`decision=engineering-only`。
- **交接/下一片**：独立于 #556 读取预算投影、#561 提取失败记录、#562 late-tail 诊断的执行区段；待精确 HEAD CI 与审阅通过后再合并。下一步继续检查波次恢复和调度之间的可变值边界，不扩大为 schema 或 checkpoint 语义迁移。

### 2026-11-20 检索结果与查询审计的共享写入收归显式上下文（独立 P3 静态片）

- **现状/范围**：主动研究执行器的搜索循环里，外部尝试耗尽与普通搜索结果分别内联更新 canonical failure、`RuntimeQueryOutcome`、按 URL 去重的候选池及面向前端的 `query_attempts` 审计列表。新增 `ActiveSearchOutcomeContext`，显式绑定唯一 `ActiveRuntimeLiveValues`、唯一 `ActiveResearchResultBuffers`、run/operation 身份与本次选择轨迹。两种分支的写入均在这个上下文内依原顺序完成；原 `_merge_runtime_candidates` 算法原样迁至相邻模块，执行器主文件净移出约 150 行。仍通过最新 live owner 取预算、cursor 和 steering，绝不使用上次 checkpoint 前的快照。
- **冻结契约**：尝试耗尽维持 `failure → unavailable query outcome → 审计列表 → checkpoint`；真实搜索维持 `外部尝试完成 checkpoint → ensure_active → (若 unavailable 则 failure) → query outcome + candidate merge → 查询审计列表 → checkpoint`。保留故障 logical call、`attempt_id`、provider code、`run_attempt`、operation ID、steering 归因、provider audit schema、URL 去重/容量与选择轨迹；候选合并或审计投影失败时，原先已写入内存的失败记录和游标状态仍保留，不提前提交后续步骤。不改任何模型、搜索、读取调用，外部尝试开始/结束标记、持久化 schema、checkpoint 次数/位置、预算结算、Evidence Gate 或发布。
- **静态证据与 CI 修复**：新增 6 项直接运行的负控，覆盖尝试耗尽、正常/失败搜索、重绑后的最新额度与 context、相同 URL 合并和部分失败次序；`python -m unittest discover -s tests -p test_research_runtime_search_outcomes.py` **6 passed**。旧 HEAD `6fe3006` 的 backend CI 还发现 `test_selection_trace.py` 从已搬迁的执行器模块导入私有合并函数，以及新专项测试多余的 `typing.Any`（Ruff F401）。已让原选择轨迹测试直接导入现行搜索结果 owner、删去多余导入；单独执行该合并契约测试通过、编译和差异检查通过。既有 `test_active_research_runtime.py` 仍负责真实持久化操作、取消/恢复、搜索失败和多波调度的端到端回归，须由新 PR 精确 HEAD CI 验收。本地缺少 pytest/Ruff/openai，不冒称完整影响集通过。`priority=P3`、`loop=static`、`owner=research/search-orchestration`、`dynamic_evidence=not_run`、`budget_authorization=not_applicable`、`decision=engineering-only`。
- **交接/下一片**：与 #556 读取预算、#561 提取失败、#562 late-tail、#564 波次基线、#565 提取目标准入各自位于不同执行区段；交接文档可能有顺序冲突。待本片单独完成 CI/审阅后合并；继续逐批抽离检索/读取调度交界面的共享写入，不迁移预算或恢复权威。

### 2026-11-20 研究崩溃恢复测试场景搭建去重（独立 P3 静态测试片）

- **范围**：`test_active_research_runtime.py` 中规划模型成功后崩溃、双 claim 提取中断、评估模型中断、提取第 2 次尝试后进程死亡四项恢复回归，各自重复创建 `ActiveResearchGateway`、`ActiveResearchRuntimeExecutor` 与 `ClaimEngineDispatchWebLookupService`。新增测试专用 `_service_with_runtime_components()`，显式接收既有模型网关、可选故障注入组件和搜索后端；四项测试仅替换重复工厂构造，保留原有自定义故障包装器、持久化 SQLite、恢复重试与全部断言。
- **冻结契约**：相同模型网关及故障注入组件仍跨 `service.execute()` 调用复用；默认每次网关创建独立 `_SearchBackend` / `_ReadGateway`，双 claim 场景仍显式使用原 `_ProvenanceSearchBackend` 对象。所有故障发生位置、异常类型、重试的逻辑调用 ID、attempt 次数、恢复游标、持久化状态及预算结算均由原测试继续核对。**不改任何生产代码、持久化 schema、CI 注册、真实模型/检索调用或产品行为**，不删除四项具有不同契约的恢复测试。
- **验证/交接**：修改前四项恢复场景 **4 passed**；修改后完整主动研究执行器模块 **83 passed**（包含原四项），重挂到最新主线后再次 **83 passed / 164.20s**；全库 Ruff、测试模块编译、差异检查通过，mypy **115/125、无新增**。工厂定义与四处调用净删约 23 行，保留每种崩溃时序独立断言。独立分支 `codex/research-crash-test-fixture-20261120`，从 `main@a1dd6159` 重挂至 `main@18c852a8`，包含已合并的 #552/#553/#555/#557/#558，未修改上述 PR 的生产代码。`priority=P3`、`loop=static`、`owner=research/tests`、`dynamic_evidence=not_run`、`budget_authorization=not_applicable`、`decision=engineering-only`；不以测试去重宣称用户体验改善，尚须精确 PR HEAD CI 与审阅验收。
- **下一片**：本片精确 CI 与审阅收口后，再检查提取失败与成功归档之间剩余的共享状态写入；checkpoint 和预算结算仍保持执行器的原边界。

### 2026-11-20 证据提取失败状态与游标归档收归上下文（独立 P3 静态片）

- **范围**：新增 `ExtractionFailureContext`，把执行器三条提取失败分支重复的“同一来源记录的逐 claim `extractor_failed` 摘要 → 最新游标追加规范化失败记录”集中为一次明确操作。其依赖仅为执行期唯一 `ActiveRuntimeLiveValues`，每次现场读取 `current_cursor()/current_context()`，不缓存可被恢复或 checkpoint 替换的引用；源记录仍由原 `ActiveResearchResultBuffers` 及执行器持有，调用时显式传入。
- **冻结契约**：策略禁止仍是 `policy_blocked` 和 `policy:{logical_call_id}`，调用前模型尝试耗尽仍是 `model_attempts_exhausted`，提取器未完成仍按原 reason 映射 `extraction_failed`/`model_attempts_exhausted`；三者 phase 均为 `extracting`，item 为 candidate ID，detail 保持原原因。严格保留 **来源摘要先写 → 失败审计追加游标 → 立即 checkpoint → 跳过当前绑定** 的顺序；审计投影失败时保留已写来源摘要但不提前改游标。多 claim 的其他摘要、旧单项 `extraction`、Evidence Gate、source ID、模型重试上限、计费/持久化形状和 checkpoint 次数与时点不变。错误分类、模型准入、实际 checkpoint 和异常处理仍由执行器负责。
- **验证/交接**：新增六项真实 failure projection 单元负控覆盖三类错误与提取器特殊理由、去重审计 ID、来源别名、恢复后的最新游标/运行轮次以及审计异常的部分效果；完整主动研究执行器、模型策略/尝试、checkpoint、证据接纳及失败投影影响集 **118 passed / 112.00s**。全库 Ruff、编译和差异检查通过，mypy **115/125、无新增**。`priority=P3`、`loop=static`、`owner=evidence/failure-audit`、`dynamic_evidence=not_run`、`budget_authorization=not_applicable`、`decision=engineering-only`；未运行真实搜索或付费模型。独立分支 `codex/research-extraction-failure-context-20261120`，基于 `main@18c852a8`，与 #559 测试工厂去重的生产代码零交集；仍需精确 PR HEAD CI、审阅和合并门禁。
- **主线整理**：#561 原 HEAD `b14b7159` 的精确 PR CI `44589370461` 已成功，但主线新增 #559/#560；本批只解决 `PROJECT_STATUS.md` 同位置交接文字冲突，保留两项独立记录并重挂至 `main@6fdc6cc`。重挂后提取失败、完整主动研究执行器、模型策略/尝试、checkpoint、证据接纳及失败投影/契约扩展影响集 **137 passed / 104.32s**；全库 Ruff、编译、差异检查通过，mypy **115/125、无新增**。旧 CI 不作新 HEAD 验收依据，须按新精确 HEAD 独立核验。
- **#565 合并后的交叉修正**：`main@3b6e6ad` 已由 `ActiveResearchResultBuffers.admit_extraction_target()` 初始化逐 claim 摘要；本片三条失败分支改用 `ExtractionFailureContext.record()` 后，执行器原本保留的局部 `extractions = source_record["extractions"]` 变为未使用，Ruff 明确报 F841。只删除这一行死赋值，不修改映射初始化的原时点及任何恢复、预算、失败归档或 checkpoint 契约。叠加后的失败归档、结果缓冲、完整执行器、checkpoint、证据接纳和失败投影影响集 **113 passed / 116.20s**，全库 Ruff、编译、差异检查通过。仍须新精确 HEAD CI 验收。
- **下一片**：检查提取阶段的 `claim/candidate` 绑定与恢复跳过判定是否仍有隐式共享依赖；如状态转移已清楚，则继续清理相邻测试中的重复故障造景。

### 2026-11-20 合格提取结果的证据接纳顺序收归显式上下文（独立 P3 静态片）

- **范围**：新增 `ExtractedEvidenceAcceptanceContext`，在抽取器返回已验证的 `ExtractedEvidenceLink` 后，接管同一来源记录的逐 claim 提取摘要、首条合格的旧单项摘要、基于当前 selected/rejected 缓冲区的证据 ID 解析，以及最新 `ResearchState` 和读取游标的绑定。执行器仅显式传入 `source_record/candidate_id/claim_id/link` 并在接纳返回后原位 `checkpoint()`；上下文只引用现有的 `ActiveRuntimeLiveValues` / `ActiveResearchResultBuffers` 所有者，不缓存可能被恢复替换的状态快照。
- **冻结契约**：严格维持 `extractions[claim] → extraction（首条合格保留）→ evidence ID → ResearchState evidence link → read_outcomes evidence_id → checkpoint`，来源字典和结果列表的对象别名不变，多个 claim 仍能共用同一已读来源。若证据 ID 解析或状态投影抛异常，保留原有先写来源摘要的部分内存效果，尚未进行的状态或游标更新不得提前发生；异常由原执行器故障处理接管。不改恢复持久化字段、checkpoint 次数与时点、读取/模型预算结算、Evidence Gate、发布或实际外部调用。
- **验证与交接**：新增四项直接测试覆盖来源别名和更新次序、恢复后的状态/游标替换、多 claim 单项摘要保留、证据 ID 及状态投影失败后的部分效果。完整主动研究执行器、证据投影、来源附着与 checkpoint 影响集 **114 passed**，随后新增的一项失败负控在直接测试文件 **4 passed**，合计不重复 **115** 项；全库 Ruff、编译、差异检查通过，mypy **115/125、无新增**。`priority=P3`、`loop=static`、`owner=evidence/acceptance`、`dynamic_evidence=not_run`、`budget_authorization=not_applicable`、`decision=engineering-only`；仅工程静态验证，无付费模型、真实读取或产品质量对比。分支 `codex/extracted-evidence-acceptance-20261120`，由 `main@c5174e19` 重挂至 `main@a1dd6159`（#554 News 清理，运行时代码无交集），与 #556 读取预算投影及其他待验收 PR 分离；候选精确 HEAD 的 CI、审阅和合并门禁仍待确认。
- **下一片**：在本片的精确 HEAD 门禁收口后，优先清点相邻提取失败分支的重复测试造景，避免把失败归档与证据接纳一起扩大成一次语义迁移。

### 2026-11-20 前端旧布局状态收敛源码快照测试退役（P3 静态减负）

- `frontendStateConsolidation.test.ts` 两项测试只扫描 `workspaceReducer`、`WorkspaceView`、SettingsPanel 与学习会话源码，证明旧 `selectedPanel` / `START_NEW_CHAT_SESSION` / `Sidebar` / `Inspector` 字符串和已删除文件不再出现。它们不执行 reducer 或渲染界面，属于已完成布局迁移的防回退专项。
- 整体删除该 43 行历史源码测试，不留只验证旧文件已被删除的空壳。保留 `workspaceReducer.test.ts` 的真实状态转换、SettingsPanel 组件测试、`onboarding-settings.spec.ts` 的实际菜单与设置操作，以及 `AppBoundary.test.ts` 中仍在使用的应用/布局职责约束。当前没有专属适配层、配置或 CI 显式注册需要联动删除；生产组件、路由与状态逻辑不变。
- `priority=P3`、`loop=static`、`owner=UI/tests`、`dynamic_evidence=not_run`、`budget_authorization=not_applicable`、`decision=engineering-only`。本片只减少重复/过时测试，精确 PR HEAD CI 验收前不宣称产品质量改善。

### 2026-11-20 模型尝试编号由实时审计上下文统一计算（独立 P3 静态片）

- **范围**：`ActiveModelAttemptContext.next_attempt_number(logical_call_id)` 每次从当前 `ActiveRuntimeLiveValues.current_cursor()` 取得恢复后游标，调用既有 `_model_attempt_start` 计算下一编号。`execute()` 内规划、候选评估、证据提取三处原来直接读取外围 `live.cursor` 的调用改为上下文委托；别处显式传游标的独立 helper 不受影响。原 `started/finished` 回调、硬预算检查与“发送前 checkpoint、完成后仅内存记账”顺序不变。
- **冻结契约**：按完整 `logical_call_id` 读取已完成审计和恢复后的 `interrupted_unknown`，单逻辑调用最多两次；第三次在模型 I/O 前抛 `_ModelAttemptBudgetExhausted`，异常仍由各阶段原分支处理。计算编号本身不修改游标、不预占预算、不持久化、不调用模型；不更改检查点次数/顺序、恢复格式、检索读取、证据发布或任何外部可见结果。
- **证据/交接**：新增“恢复后中断尝试仍消耗编号、第三次拒绝且无副作用”负控，先失败于上下文缺失方法、实现后模型上下文专项 **8 passed**；主动研究/预算/恢复/Deep 主影响集 **216 passed**，基础运行时与失败契约相邻集 **50 passed**，两组不重复合计 **266 passed**。全库 Ruff、差异检查和 mypy **115/125、无新增**。基于 `main@7a5f0461` 的 `codex/model-attempt-number-live-20261120` 独立分支；#548、#550 仍在各自精确 CI 验收，不借用其结果。`priority=P3`、`loop=static`、`owner=model/attempt-budget`、`dynamic_evidence=not_run`、`budget_authorization=not_applicable`、`decision=engineering-only`；未产生真实模型调用或付费。
- **主线重挂（#548 合并后）**：原读重试诊断 PR #548 已合入 `main@ff619094`；本片源代码自动合并，保留两批交接记录，并将本段置顶以降低后续 #550 独立交接的冲突风险。新候选的模型/主动研究/预算/Deep/读取重试影响集 **228 passed**，基础运行时与失败契约 **50 passed**，合计 **278 passed**。新精确 PR HEAD CI 必须独立成功，旧运行号 `44573181445` 不作新 SHA 验收依据。
- **最新整合**：#549、#550、#551、#554 均已合入 `main@a1dd6159`；本批 #552 仅将交接文档的并列新增节合并到主线，模型尝试实现与负控无额外修改。旧 `c263a0b0` 的绿色 CI 不替代重挂后精确 HEAD 验收。

### 2026-11-20 三类读取共享波次预算投影上下文（独立 P3 静态片）

- **范围**：新增 `ReadWaveBudgetContext`，将 Deep 本地材料化、普通证据读取和 lead 读取三处重复的 `updated_runtime_budget(state, cursor, elapsed_seconds, reads_used)` 调用收敛为 `read_budget.project()`。每波绑定同一个既有 `ReadWaveQuotaContext`、运行期唯一的 `ActiveRuntimeLiveValues` 与预算时钟，调用时读取最新 state/cursor，不缓存 checkpoint/steering 恢复前快照。投影只返回新 `ResearchState`，执行器仍独占 `live.state` 回写、读取历史及持久化。
- **冻结契约**：Deep 材料化只计字符、不计读槽，投影→读取历史→checkpoint；普通物理读取在成功时计槽与字符、来源 upsert/视觉附着后投影→带 resolution 的读取历史→checkpoint；lead 成功读取计槽与字符、投影→checkpoint 后才做政策及模型发现。失败读取不增加槽；读取准入逐次取当前额度上限。`updated_runtime_budget` 的候选计数上限、读数、耗时算法不变；不更改任何 checkpoint 调用点/顺序、恢复 schema、模型及外部读取次数、发布资格、读取历史或诊断键。
- **验证**：新增预算投影正/负控，连同 Deep seed/续接、lead 发现、完整主动研究执行器、读取额度/预算时钟、checkpoint 与读取投影影响集在原候选 **173 passed**；重挂至 `main@c5174e1`、纳入 #550 新 checkpoint 会话和 #551 真实执行器场景后 **174 passed**。新候选全仓 Ruff、编译和差异检查通过，mypy **115/125、无新增**。未触发共享 schema 或生产权威切换，不运行 L3 全量；相关验证均为离线静态证据。
- **边界**：该上下文没有第二份预算/游标/持久化权威，也不接管 checkpoint；硬预算终止仍走执行器既有不带 reads_used 覆盖的通用投影。新增纯单元负控验证旧状态不变、恢复后 state/cursor 双重重绑定、Deep 零读槽、物理与 lead 共享计数、只采样一次 elapsed、不写诊断/游标。最初基于 `main@ff619094`；在 #549/#551/#550 合并后，保留其全部代码和交接并重挂到 `main@c5174e1`，仅交接文档同一插入点冲突；与开放中的 #552/#553 不叠加代码。独立分支 `codex/read-wave-budget-projection-20261120`。`priority=P3`、`loop=static`、`owner=read-budget/orchestration`、`dynamic_evidence=not_run`、`budget_authorization=not_applicable`、`decision=engineering-only`；没有真实搜索或付费模型调用。

- **主线整理**：#556 原 HEAD `56e6b964` 的精确 CI `44580739112` 已成功；主线随后新增 #552/#553/#555/#557/#558/#559/#560。只合并 `PROJECT_STATUS.md` 的并列交接节，运行时代码自动重挂至 `main@6fdc6cc`。重挂后完整执行器、Deep、lead、读取额度/时钟/投影及 checkpoint 影响集 **174 passed / 101.04s**，全库 Ruff、编译、差异检查通过，mypy **115/125、无新增**。旧 CI 不适用于新的 HEAD，必须重新核验。
- **再次重挂**：#565 提取目标准入合入 `main@3b6e6ad` 后，本片代码和交接记录再次自动重挂，无冲突。提取准入的更改不涉及读取预算三处写入；叠加后读取预算、来源准入、完整主动执行器和 checkpoint 影响集 **102 passed / 93.79s**，Ruff、编译与差异检查通过。新 PR HEAD 仍需独立 CI，原 174 项回归只能作为此前基线证据。

### 2026-11-20 读取重试与 inventory 诊断聚合提取（独立 P3 静态片）

- **范围**：将主动研究执行器的 `_inventory_fetch_with_retry` 和 `_accumulate_fetch_metrics` 归到 `research_runtime_fetch_retry_observation`，统一负责 sitemap/inventory 的四元组→可重试 payload 适配，以及原生读取/清单读取分别写入 `read_retry`、`inventory_fetch` 的有界诊断聚合。执行器仍通过原函数名称兼容导入，网关路径和域定向路径的调用点不变。没有新建可变状态持有者；每次调用显式接收当前上下文与剩余时间。
- **冻结契约**：读取重试的 `off`/`window_aware` 准入、每次 12 秒和 1,500,000 字节的 inventory 入场参数、transport 异常与空正文映射、最终四元组返回、retry/backoff/timing 指标的逐次舍入、8 条原因截断，及两类独立诊断键均保持原规则。**不改**真实重试次数、读槽/研究预算、模型次数、检查点时点/顺序、恢复游标与证据发布；此模块也不决定任何模型预算。
- **验证与边界**：新增负控检查上下文替换后计数互不污染、诊断长度和逐次舍入；原重试准入专项 **12 passed**，连同完整主动研究执行器、域定向、读取升级与选择器影响集不重复合计 **163 passed**。全库 Ruff、编译和差异检查通过；mypy 当前 **115** 项既有问题，低于基线 **125**，无新增。基于 `main@7a5f0461` 的独立 `codex/fetch-retry-observation-owner-20261120` 分支；`priority=P3`、`loop=static`、`owner=retrieval/fetch-observation`、`dynamic_evidence=not_run`、`budget_authorization=not_applicable`、`decision=engineering-only`，未运行真实搜索、视觉或付费模型。
### 2026-11-20 检查点会话显式依赖与最新状态绑定（独立 P3 静态片）

- **范围**：新增 `ActiveRuntimeCheckpointSession`，在一次研究执行中持有仓库操作标识、结果缓冲、预算时钟回调与唯一 `ActiveRuntimeLiveValues`；每次 checkpoint 现场读取最新 `state/cursor/context`，即时构造 `ActiveRuntimeCheckpointContext`，按原逻辑准备/绑定/持久化并仅在写入成功后采用仓库返回的上下文。执行器的内部 `checkpoint()` 继续保留原计时边界、`_checkpoint_caller()` 栈深及异常 `finally` 记录，不移动实际调用点。
- **冻结契约**：保持 `stage → budget → runtime cursor → claim state → metrics → repository write → durable context rebind` 顺序；准备失败仍绑定已经完成的部分状态但禁止持久化，写入失败不采用新的仓库上下文。保留 repo-CAS/steering 合并、checkpoint 次数和时点、观测字段、预算/模型/读取次数、恢复持久化形状、Evidence Gate 与最终发布。**唯一可变状态所有者仍是 `ActiveRuntimeLiveValues`**，会话不缓存任何旧快照。
- **证据/交接**：新增两项负控覆盖跨 checkpoint 的三种实时值替换、仓库 steering 合并及序列化故障后部分投影；`test_research_runtime_checkpoint_context.py` **5 passed**，主动执行/恢复/预算/波次等影响集 **153 passed**，Deep 续接/steering/窗口诊断相邻集 **101 passed**，两组不重复合计 **254 passed**。全库 Ruff、差异检查与 mypy **115/125、无新增**。基于 `main@7a5f0461` 独立 `codex/checkpoint-persistence-session-20261120`，与尚在 CI 的 #548 读取重试诊断拆分不同职责；须取得此分支精确 PR HEAD CI 和审阅门禁才能合并。`priority=P3`、`loop=static`、`owner=research/checkpoint-recovery`、`dynamic_evidence=not_run`、`budget_authorization=not_applicable`、`decision=engineering-only`；未运行真实搜索、付费模型或动态产品比较。
- **主线重挂（#548 合并后）**：#548 的精确 CI 五项成功，已 squash 至 `main@ff619094`。本片仅顶部交接段落存在冲突，保留两批记录，运行时源代码自动合并。新候选含 #548 的读取重试模块，主动研究/恢复/预算/波次及读取重试 **165 passed**，Deep 续接/steering/窗口诊断 **101 passed**，合计 **266 passed**；mypy **115/125、无新增**。须按重挂后的精确 PR HEAD 重新验证远端 CI，旧运行号 `44571779039` 不作新 SHA 门禁依据。

### 2026-11-20 研究 steering 旧测试转发入口与重复幂等测试退役（P3 静态减负）

- `active_research_runtime.py` 仅为历史测试重导出的 `_apply_pending_active_steering` 没有生产调用；真正实现属于 `src.web.research.steering`，运行时经 `ActiveResearchSteeringContext.apply_pending()` 使用。删除这个测试专用入口，同时删除同文件中未被运行时/测试调用的 `_steering_graph_ids`、`_checkpoint_now_ms` 导入；不动上游实现或真实 steering 流程。
- 删除 `test_active_research_runtime.py` 中直接调用旧导出、模拟重复执行的 43 行专项；其幂等行为仍由真实执行器的下波应用测试及 checkpoint 前/后崩溃恢复双场景验证。为保留“同一波两条不同用户指令”的独有覆盖，将实际执行器测试强化为一次接收两条指令，并断言每条恰好一份 user claim、critical gap 与对应 ID。
- 无专属环境开关、CI 单独入口、兼容适配文件或配置引用；研究预算、持久化、checkpoint、用户指令和模型/搜索调用不改。`priority=P3`、`loop=static`、`owner=orchestration/tests`、`dynamic_evidence=not_run`、`budget_authorization=not_applicable`、`decision=engineering-only`。本地无 pytest/ruff；候选精确 HEAD CI 及审阅未验收。不以工程减负宣称产品质量提升。

### 2026-11-20 发现与深页定向诊断写入集中到实时上下文（独立 P3 静态片）

- **范围**：新增 `ActiveDiscoveryDiagnosticsContext`，将执行器中分散的 lead-discovery 计数、deeper targeting 策略/页面意图/最近记录写入归为一个诊断所有者。上下文仅持有本次执行的 `ActiveRuntimeLiveValues`，每次写入都从 `current_context()` 读取最新持久化字典，绝不缓存可能被恢复/检查点替换的指标引用；执行器不再保留 `_lead_metrics`、`_bump_lead_metric`、`_record_deeper_targeting` 的另一套实现。
- **冻结契约**：`metrics.lead_discovery` 各字段的计数、负增量不扣减，`metrics.deeper_targeting` 策略/意图计数、字段裁剪与最近 8 条保留完全不变；不改变模型/读取调用、额度、选源、定向策略、游标、持久化键、checkpoint 时点/顺序、证据发布与外部诊断。专门负控检查上下文替换、无 gap、策略计数及最近记录边界。
- **静态验证**：新增三项诊断上下文负控均通过；主动研究执行器、深页定向、读取观测和检查点影响集 **116 passed**，全库 Ruff、编译、差异检查和 mypy **115/125、无新增**。本片只重定位诊断写入，并显式依附可替换的 live context，没有任何付费或在线验证。
- **基线/边界**：独立 `codex/discovery-diagnostics-context-20261120` 分支基于 `main@45efaaff`，与仍在 CI 的 #544 视觉附着和 #545 读取测试场景去重无生产逻辑依赖。`priority=P3`、`loop=static`、`owner=diagnostics/discovery`、`dynamic_evidence=not_run`、`budget_authorization=not_applicable`、`decision=engineering-only`；无真实付费模型、外部搜索或产品动态比较。须在本地影响集、Ruff、mypy 基线通过后提交独立 PR，并以精确 PR HEAD CI 与审阅收口。

### 2026-11-19 读取来源记录与视觉附着顺序收归显式上下文（独立 P3 静态片）

- **范围**：新增 `ReadSourceEvidenceContext`，在读取投影成功/失败后统一执行 `upsert_selected_source(record)`；仅成功正文再读取声明式视觉证据，并把视觉单元附着到同一 `record`。该上下文持有结果缓冲区及视觉读取入口，调用时显式接收最新 `context`、`state` 和候选规范 URL，不捕获可被恢复/检查点替换的旧状态。
- **冻结契约**：原有顺序“来源 upsert → 成功时尝试视觉读取并追加诊断 → 更新运行预算 → 记录读取历史 → checkpoint”不变。失败正文不触发视觉，视觉空结果不增加字段；视觉读取 helper 的异常隔离、视觉预算门和诊断记录位置不变，持久化键、调用次数、模型/检索策略及发布规则均不改变。新增纯单元负控检查上载前别名、失败/空结果、状态/上下文替换，以及原真实执行器视觉影响测试。
- **证据**：新增三项纯单元负控并覆盖原真实执行器视觉影响集；来源投影、发布、读取额度与主动研究执行器合计 **105 passed**，全库 Ruff、编译、差异检查及 mypy **115/125、无新增**。均为静态离线验证，不将它们描述为真实模型或图像质量证据。
- **依赖/交接**：本片以 `#542` 的来源 upsert 所有权为前置，在 `codex/read-source-visual-context-20261119` 单独分支开发；允许先以 #542 分支为临时 base 建立**仅含视觉附着差异**的堆叠 PR，待 #542 精确 CI 全绿并安全合入主线后，才将本片重挂到最新 `main` 并以更新后的精确 HEAD 单独验收。`priority=P3`、`loop=static`、`owner=evidence/visual-read`、`dynamic_evidence=not_run`、`budget_authorization=not_applicable`、`decision=engineering-only`；没有真实模型、付费视觉或外网读取。

### 2026-11-20 无调用方手工熔断兼容入口退役（P3 静态减负）

- 旧 `PerRunBreaker.mark_open()` 是向后兼容的人工“后端全域熔断”入口，其唯一仓内调用方为 `test_health_breaker.py` 中 3 项专属兼容测试；从无实际 reader/执行器/配置/CI 调用。Wigolo provider 的 `mark_circuit_open()` 也没有任何仓内调用者，内部 `_circuit_open` 初始为假且仅由该孤儿方法改写，故其 `fetch()` 分支不可达。
- 成组删除两个手动熔断方法、Wigolo 不可达分支、breaker 的通配 host 回退/常量/旧转移标记，以及 3 项仅证明旧入口自身可用的测试；不添加替代兼容层。现行 `PerRunBreaker` 的每 `(backend, host)` 真实失败计数、关闭/打开/半开/冷却转换与 deadline 拒绝仍保留，后端预检与读取失败形态不变。
- 为冻结运行诊断字段形状，仍保留 `retrieval_policy` / breaker snapshot 中原有 `legacy: false` 键（现行路径一直为 false）；不变更持久化 schema、预算、checkpoint、真实调用量或可见结果。没有与旧手工入口绑定的环境开关、配置或阶段门条目需要删除。`priority=P3`、`loop=static`、`owner=retrieval/health-breaker`、`dynamic_evidence=not_run`、`budget_authorization=not_applicable`、`decision=engineering-only`；候选须以其精确 HEAD CI 与审阅验收。

### 2026-11-19 来源记录写入收敛至结果缓冲区（独立 P3 静态片）

- **范围**：将执行器内两个物理读取/耗尽路径的 `_upsert_source(selected_sources, record)` 改为唯一结果缓冲区 `ActiveResearchResultBuffers.upsert_selected_source(record)`；把原候选 ID 去重/原位置替换算法移入 `research_runtime_result_buffers.upsert_source_record`，供现有 Deep 本地材料化保持同样的显式列表写回。执行器不再定义另一份 `_upsert_source`。
- **状态与恢复契约**：`selected_sources` 仍只由 `ActiveResearchResultBuffers` 持有并被 checkpoint/publisher 共享；列表身份、原位置替换、新候选追加和记录本身的对象身份全部保留。特别冻结“来源先 upsert，视觉证据后附着到同一个 `record`”的顺序；后续附着的 `visual_units` 必须能从该列表读取。没有引入副本、第二持有者、新的持久化键、额外 checkpoint 或模型/读取调用。
- **验证与边界**：新增结果缓冲区回归，验证同候选替换顺序、列表/记录别名、视觉挂载后可见性；已有 Deep 材料化、证据投影、发布、波次结算与研究执行完整影响集 **120 passed**；Ruff、差异检查和 mypy **115/125、无新增**通过。分支 `codex/research-source-write-owner-20261119`，基线 `main@a1875ee1`；`priority=P3`、`loop=static`、`owner=evidence/source-records`，`dynamic_evidence=not_run`、`budget_authorization=not_applicable`。不修改来源读取内容、证据评分、最终发布规则或昂贵的真实模型/搜索链路。仍须以精确 PR HEAD CI 和审阅独立验收。
- **后续最小片**：再拆分读取成功后的视觉单元附着与其诊断，保持来源写入完成后才调用视觉读取，并保留视觉失败不影响成功正文的语义。

### 2026-11-19 读取选择器与视觉读点测试场景去重（独立 P3 静态片）

- **范围**：`test_read_site_selector.py` 和 `test_read_site_visual_evidence.py` 原先各自通过 `importlib` 动态加载同一大型执行器测试模块，重复创建相同的 SQLite 运行、结构化假模型、短文读取网关和升级后端。新增 `tests/research_read_site_scenarios.py` 中的 `run_read_site_scenario()`，共用一次模块导入及完全相同的离线执行构造；各测试仍独立设置 hint/vision 开关、上下文和 SQLite 文件并保留原断言。
- **冻结契约**：只重构测试搭建，不改研究运行时、模型、读取路由、视觉预算、持久化、检查点、证据发布或外部调用。原 selector + visual 测试按原名收集 **20 项**；连同完整主动研究执行器影响集 **104 passed**。全库 Ruff、编译和差异检查通过；没有付费模型、真实搜索/视觉或动态比较。本片 `priority=P3`、`loop=static`、`owner=tests/read-site`、`dynamic_evidence=not_run`、`budget_authorization=not_applicable`、`decision=engineering-only`。
- **基线与收口**：最初基于 `main@34edd8a4` 的独立 `codex/read-site-test-scenario-20261119` 分支；#542 合并后整合到 `main@45efaaff`，仅交接顶部并列新增节出现文本冲突，保留两节内容。与仍在验收的视觉上下文 #544 没有生产代码依赖。新精确 PR HEAD 的 CI 和审阅须独立验收；不能拿旧 CI 或本地静态回归替代。

### 2026-11-19 移动端与输入框历史 CSS 字符串测试退役（P3 静态减负）

- 删除 `mobileLayoutContract.test.ts`（2 项）和 `composerLayoutContract.test.ts`（2 项）。两者只读取 CSS 文本，查 `flex-wrap`、`44px`、`grid-row` 等固定声明；CSS 换一种等价写法也会误报，实际渲染不正确却保留这些字面量时也会漏报。
- 产品契约改由既有 Playwright 真实布局验证承接：`composer-layout.spec.ts` 覆盖导航的 3 个操作按钮尺寸、发送按钮框内位置和窄屏水平溢出；`chat-role-settings.spec.ts` 验证角色面板位于输入框上方、输入和发送可见；`accessibility-responsive.spec.ts` 验证视口收缩后输入/发送可达、触控尺寸与键盘焦点。额外将“更多”弹出层**左右边界确实处于当前视口内**接到现有浏览器用例，不再断言 CSS 原字符串。
- 不改运行时 CSS、布局、控制器或业务行为；旧测试无独占 helper、适配层、配置或显式 CI 注册，无需保留空壳。仅工程性减负，`priority=P3`、`loop=static`、`owner=UI/tests`、`dynamic_evidence=not_run`、`budget_authorization=not_applicable`、`decision=engineering-only`；精确 PR HEAD CI 验收前不宣称产品改进。

### 2026-11-19 公平读取规划共享状态收归上下文（独立 P3 静态片）

- **范围**：将 `_fair_read_plan()` 内约 210 行的读槽/claim 绑定/来源簇/冲突预留排程逻辑收进 `research_runtime_read_plan_context.FairReadPlanContext`；原函数仅保留调用接口与确定性 claim 顺序。两个原本隐式捕获外围可变集合的内部函数改为上下文方法；每个波次创建新实例，历史簇映射先复制，禁止回写调用方持有的簇集合。
- **冻结契约**：一份候选物理读取一次、多个 claim 可绑定各自提取目标；历史簇不可重复耗读槽；critical→major→conflict 排程和无冲突时预留返还、硬读额度及现有 trace/diagnostics 调用顺序不变。**不改**检查点时点/顺序、预算结算、模型次数、恢复游标/持久化字段、证据整理和发布。
- **静态证据**：改动前纯读取规划/冲突预留/调度 **16 passed**；改动后新增状态隔离负控，纯调度 **17 passed**、完整主动执行影响模块 **84 passed**、其余读取/恢复/检查点/模型尝试/预算相关模块 **96 passed**，均为当前候选树，组合 **180 passed**。Ruff、差异检查及 mypy 基线 **115/125、无新增**。一次过宽组合测试因环境明显变慢而中断，后拆成等价的不重复模块集逐项通过；不宣称本地 L3 全量测试完成。
- **基线/下一步**：`main@9fa4e3f6`（包含已合并 #527/#529 和其他窗口 #526/#528），分支 `codex/research-fair-read-plan-context-20261119`。#528 只改前端迁移面板、样式、CI 分类及主线交接，研究代码无冲突；该主线的内容已经保留。本片 `priority=P3`，`loop=static`，`owner=retrieval/read-planning`，`dynamic_evidence=not_run`，`budget_authorization=not_applicable`；未运行付费模型、真实搜索或动态产品比较。完成干净提交与独立 PR 后须以该精确 HEAD CI 和审阅收口，不借用之前主线 CI。
- **主线重整合**：#533 旧 HEAD `dbc757cd` 的 CI `44533206436` 已全部通过，但随后主线新增 #516/#520 等独立变更，导致交接文档冲突。仅将本片运行时代码、独立测试及此节交接增量重挂到 `main@57f0ad1e`，保留主线其他交接及 P1 空白终态防护。重挂后的精确 PR HEAD 必须重新取得 CI 全绿、无阻断审阅和可合并结果后才能合并；旧 CI 不可复用。

### 2026-11-19 读取链逐步账本转移归入 ActiveReadAttemptContext（独立 P3 静态片）

- **范围**：将执行器中每个实际 reader-chain step 的外部尝试标记、游标 outcome、失败投影与读取观测，收归 `ActiveReadAttemptContext.record_chain_attempts()`。上下文只持有 per-run breaker/观测依赖；每一步都通过显式回调将新游标交还给调用方，不捕获旧 cursor/context。
- **冻结契约**：逐步保持 `begin external → finish external → append outcome → observe → append failure` 顺序；诊断失败时，调用方游标已包含本次 outcome。Wigolo escalation signal 仍在所有 step 记录后产生，原有时钟采样次数不变。**不改** specialist/default chain 选择、调度、checkpoint 时点、预算结算、来源投影、证据提取或发布。
- **边界**：`ActiveResearchRuntimeExecutor` 仍负责 ensure-active、每候选 checkpoint、预算、selected_sources、projection 和持久化；本片只归拢真实链步骤的审计/观测转移。
- **测试**：新增独立纯单元测试覆盖双 backend 的标记/游标/失败/escalation 顺序，以及观测异常时游标先发布的负控；本地读取上下文与执行器影响集 **86 passed**。原精确 HEAD `728ce16e` 的 CI `44535451124` 五个作业全部通过，但主线随后前移，不将旧 CI 复用为重挂后提交的验收证据。
- **基线**：`main@37dc889b`；独立分支 `codex/read-attempt-cursor-context-20261119`。本片不依赖仍在验收的 #533。
- **重挂**：相同的运行时代码与测试重挂到 `main@57f0ad1e`；只合并此节交接文字与主线已有的 P1 空白答复、旧面板清理记录，保持和 #533 代码独立。重挂后须取得自己的精确 HEAD CI 与审阅验收，才能按顺序合并。


### 2026-11-20 主动研究实时值回调与 lead 候选诊断归属（独立 P3 静态片）

- **范围**：执行器将读取观测的 `context/cursor` getter、评估/提案/域定向/晚到候选的 `live_context` 以及读链的 cursor 回写，统一绑定到既有 `ActiveRuntimeLiveValues.current_context/current_cursor/set_cursor`；不再让这些调用点各自定义等价匿名闭包。lead 新候选 ID 的诊断投影从执行器移入既有 `ActiveDiscoveryDiagnosticsContext.record_lead_candidate_ids()`；每次读取最新 cursor，并向最新 context 写入相同 ID 列表。新负控在替换 cursor 与 context 后检查旧字典不被污染、当前列表顺序不变且不修改游标。
- **冻结契约**：`ActiveRuntimeLiveValues` 仍是运行期状态、游标、持久化上下文的唯一可变所有者，诊断上下文不缓存旧值；lead 仅在确实追加新候选后记录，键 `claim_engine_metrics.lead_discovered_candidate_ids`、来源过滤 `discovery_method == lead_url` 与既有顺序保持不变。没有修改模型/真实读取调用次数、预算结算/波次额度、恢复格式、checkpoint 时点或调用栈观测、证据资格和发布。通用阶段计时回调仍在执行器原位置，没有不合职责地迁入读取观测。
- **验证**：完整主动研究/模型尝试/读取观测及诊断影响集 **118 passed**；晚到候选、域定向、模型提案、选源权威、单一读取链、检查点与波次结算相邻影响集 **88 passed**，合计 **206 passed**；全库 Ruff、编译、差异检查通过；mypy **115/125，无新增**。均为离线静态验证，未运行 L3 全量。
- **状态**：基线 `main@ff619094`，独立分支 `codex/live-observer-bindings-20261120`；不依赖开放中的 #549–#552，尤其不触碰 #550 的 checkpoint 会话和 #552 的模型尝试编号。`priority=P3`、`loop=static`、`owner=orchestration/diagnostics`、`dynamic_evidence=not_run`、`budget_authorization=not_applicable`、`decision=engineering-only`。静态影响集与精确 PR HEAD CI 验收独立记录；未发起真实搜索或付费模型调用。
- **重挂收口（#553）**：在已合入 #549/#550/#551/#554 的 `main@a1dd6159` 上复用原运行时代码和负控，解决顶部交接插入冲突并将本节放入稳定历史位置。旧 `50fdf132` CI 成功不可代替新 HEAD 的独立验收。

### 2026-11-19 伪量化 Golden Journey 预算测试退役（P3 测试减负）

- `frontend/src/product-flow/goldenJourneyAudit.ts` 仅供测试使用，没有运行时消费者。其中“产品界面数量”“恢复前决策次数”等并非读取组件或浏览器实际状态，而是在测试里赋固定整数后与同模块中的固定预算比较；末尾测试甚至只检查这些静态预算常量本身，不能证明交互摩擦达标。
- 当时整体删除此伪量化测试配置和自证式预算测试，并同步清除 `githubEvidenceBoundary.test.ts` 对其中文描述常量的存在性断言。该次验收仍保留 `goldenJourneys.test.tsx` 的五个组件场景；**这是 11-19 的历史范围，不代表当前仍保留该文件**：11-20 的独立组件/E2E 去重片将其正式退役，见下文。本次没有汇报虚假的产品预算合格。
- 不改变组件、路由、会话、模型、检索、持久化和预算逻辑。定向 Vitest **4 files / 12 tests passed**（`goldenJourneys`、`githubEvidenceBoundary`、`ChatPanelBoundary`、`FireflyLessonBoundary`），`npm run build` 通过，`git diff --check` 通过；远端 CI 待核。分类为 `priority=P3`、`loop=static`、`owner=UI/tests`、`dynamic_evidence=not_run`、`budget_authorization=not_applicable`、`decision=engineering-only`。
### 2026-11-19 每波读取额度共享状态归入 ReadWaveQuotaContext（独立 P3 静态片）

- **范围**：把 `execute()` 内原本跨证据读取、Deep 本地材料化与线索读取共享的 `successful_reads`、`used_chars` 归入每波新建的 `ReadWaveQuotaContext`；初始化仍复用原读取诊断与已保存 Deep seed 的一次性字符计费。物理成功读取耗一读槽并按最终正文长度计费，材料化仅耗字符、不耗读槽；线索读取与证据读取共用两项额度。
- **冻结契约**：每次入场仍读取当前 `live.state.budget.max_reads/max_total_chars`，绝不缓存恢复/steering 后的额度上限。Deep 材料化仍可使用全部剩余字符，真实 reader 与 lead 仍以 6000 字符为单次上限；零/负额度按原算式返回，由原入场判断拦截。更新 `ResearchState`、诊断、检查点及其顺序、外部调用、来源 upsert/视觉材料、证据发布和持久化格式均保持在原执行器原位置。
- **验证/交接**：新增纯单元回归验证历史读取加 seed 去重恢复、两个波次对象互不污染、动态更改预算上限、材料化/证据/线索共享计数与负额度不钳制的负控。当前候选基于 `main@5ce868e9`，分支 `codex/read-quota-context-20261119`；本地读取额度/投影/完整主动执行影响集 **91 passed**，相邻 Deep/恢复/预算/检查点/调度集 **54 passed**，两组合计 **145 passed**；Ruff、差异检查及 mypy **115/125、无新增**通过。远端精确 HEAD CI 仍须收口。`priority=P3`、`loop=static`、`owner=read-quota-accounting`、`dynamic_evidence=not_run`、`budget_authorization=not_applicable`。无真实付费模型或在线搜索。
- **主线重挂**：首次本地候选 `f6718638` 后主线又合入前端实验室清理与 GitHub 静态回放退役（`main@1ce267a5`）；仅交接文档顶部有冲突，保留两项独立清理记录。读取运行时代码、新额度上下文与测试均无交叉修改；新精确 PR HEAD 的 CI 与审阅仍须独立验收，不借用前一候选测试作远端 CI 结论。
- **下一片**：本片独立通过完整门禁、主线整合后，再考虑从执行器拆分来源记录及视觉附件写回；不要同时把 `selected_sources` 的发布所有权移出 `ActiveResearchResultBuffers`。

### 2026-11-20 GitHub 证据与学习会话旧源码归属快照测试退役（P3 静态减负）

- 两份 App 层测试 `githubEvidenceBoundary.test.ts`（2 项）和 `learningSessionViewBoundary.test.ts`（2 项）只读取 TS/TSX 源码，查某些函数名/字面量是否存在、某些历史变量名是否缺席；不执行真实 API、证据归一化、会话切换或渲染，且代码重命名即可引发误报。
- 直接删除合计 82 行的旧源码归属快照，没有独占运行时函数、适配层、开关或显式 CI 注册需要保留。**保留** `evidenceHelpers.test.ts` 对服务器证据契约/来源 ID 的实际归一化测试、`EvidenceTrail.test.tsx` 的可见证据状态、`learningSessionViewModel.test.ts` 对当前 thread 与恢复摘要优先级的选择结果，以及 `evidence-journeys.spec.ts` / `closure-session-journeys.spec.ts` 实际浏览器旅程。
- 不删除有独特运行契约的 Firefly 教学、聊天恢复/控制器边界测试；不更改任何生产 UI、恢复、研究执行、模型预算、checkpoint 或证据发布。基线 `main@a1dd6159`，独立 `codex/retire-source-owner-boundary-tests-20261120`，`priority=P3`、`loop=static`、`owner=UI/tests`、`dynamic_evidence=not_run`、`budget_authorization=not_applicable`、`decision=engineering-only`；以精确 PR HEAD CI 验收，不宣称真实浏览器质量提升。

### 2026-11-20 已下线的手动任务意图选择器整链退役（P3 静态减负）

- **调用证据**：现行 ChatPanel 只有「对话/搜索」两个输入模式；全前端没有 `setPendingTaskIntentOverride()` 的生产调用，`TURN_TASK_INTENT_OPTIONS` 仅供旧测试读取。旧全局一次性覆盖变量只会在 API 请求构造时被消费，值恒为 `undefined`，旧请求因此恒发送 `task_intent: null`。服务端 `ChatRequest.task_intent` 默认为 `None`，去掉这个前端字段不改变自动任务判定；保留服务端供其它直接调用者使用的显式意图契约与已持久化 route 的显示逻辑。
- **成组删除**：旧选项表、全局 set/consume/clear 状态及调用、没有真实 UI 操作对象的 `taskIntentApi.test.ts` 两项人工覆盖传输专项、`taskContract.test.ts` 中选项/消费两项专项，及独立样式文件 `task-intent-selector.css` 和入口 CSS 导入；去掉 ChatPanel 测试针对不存在的芯片和覆盖状态的旧断言。原专项中独有的「流式无响应体时复用相同请求」契约迁至正式 `api.test.ts`，增加附件 ID 不丢失检查。旧 CSS 中唯一仍在用的 `.composer-main` 网格布局迁至 `styles.css`，保留触屏/无障碍响应式覆盖及实用的恢复/搜索行为测试。没有相关环境配置、阶段门或 CI 明确注册。
- **冻结/非范围**：正式任务分类、服务端 `task_intent` 可选 API 字段、学习/研究收束按钮、会话恢复、消息发送/重试/附件/预算/证据发布均不改；仅从浏览器移除未接线的人工覆盖管道。`priority=P3`、`loop=static`、`owner=UI/task-intent`、`dynamic_evidence=not_run`、`budget_authorization=not_applicable`、`decision=engineering-only`；本地差异检查与精确 PR HEAD CI 分别记录，不声称真实模型或浏览器体验已经验证。

### 2026-11-20 旧 Vitest Golden Journey 重复造景退役（独立 P3 静态片）

- **重复层级核实**：`frontend/src/product-flow/goldenJourneys.test.tsx` 的 5 项“旅程”实质是分别渲染 ChatPanel、RestoreCard、UploadLearningPrompt、ChatResearchRecovery 和 LearningStrip 的离线 DOM 快照，没有发送消息、持久化恢复、跨轮跳转或真实浏览器交互。五条行为均已有更直接的组件契约测试；其中首轮零配置、返回学习继续、失败研究恢复等由正式 `frontend/e2e/golden-journeys.spec.ts` 实测浏览器动作、刷新恢复和可交付产物，E2E 的两个 Playwright 项目配置继续运行。上传行动、研究重试及 durable 学习内容也各有组件直接交互测试。
- **整组退役**：删除唯一存在于 `frontend/src/product-flow/` 的旧 310 行综合渲染测试及其重复的情景工厂和文本断言，不补空壳或兼容重导出；无专用功能、API、CSS、环境变量、测试阶段注册或 CI 豁免需要保留。正式组件、真实浏览器 Golden Journey、状态恢复、源证据展示、预算与发布逻辑一律不动。
- `priority=P3`、`loop=static`、`owner=UI/tests`、`dynamic_evidence=not_run`、`budget_authorization=not_applicable`、`decision=engineering-only`。本地差异检查与精确 PR HEAD CI 分别验收，不能把删除测试说成用户体验改善。

### 2026-11-20 晚到候选诊断状态与终态写入显式化（独立 P3 静态片）

- **范围**：将研究执行器 `_late_admission_tail` 中的 `_live` / `_store` 隐式闭包及 `§70/B5` / `§71A` 六个仅用于该路径的诊断 helper 收归 `research_runtime_late_tail_diagnostics.py`。一个 `LateTailDiagnosticsContext` 明确持有本次评估的原始上下文、实时上下文提供者、预算时钟、截止时间及诊断 invocation；`begin/phase/store/finish` 操作都在原业务分支的相同位置调用，实时重新获取指标映射，不缓存被 steering/checkpoint 更换的字典。
- **冻结不变量**：无晚到候选时先记 `no_late_ids`；读槽/时限/政策/模型拒绝及失败时记相同 `skipped_reason`，异常路径写 `aborted:<type>`；正常评估的 `late_assessment_tail` / `late_tail_invocations` / `b1_critical_path` 键、长度上限、时钟采样和四舍五入、`recovered`/映射 identity 差异均保持原位置与算法。绝不重排模型尝试、阶段计时、已评估候选写回、预算结算或检查点，不改持久化 schema、来源阅读次数和证据 Gate/发布。
- **验证与交接**：新增三项直接离线负控（上下文替换、两个终态、只读指标映射）**3 passed**；两份源码编译和 `git diff --check` 通过。原有 `test_late_admission_tail.py` 的成功/拒绝/中止/替换/只读状态行为及研究执行器影响集必须由候选**精确 HEAD CI** 运行；本地缺少 pytest、Ruff 和 openai 运行依赖，未谎称完成整合测试。`priority=P3`、`loop=static`、`owner=diagnostics/late-tail`、`dynamic_evidence=not_run`、`budget_authorization=not_applicable`、`decision=engineering-only`，未发起真实搜索、模型、付费实验。

### 2026-11-19 Firefly/Doupo 历史源码文案测试退役（P3 静态减负）

- 旧 `FireflyCopyStyle.test.ts` 的 5 项测试读取六个 TS/TSX **源码字符串**，禁止某些历史词或要求常量字面量存在。它们无法证明这些内容实际呈现在界面，且与正式 `FireflyDefaultLesson.test.tsx`、`DoupoDefaultLesson.test.tsx`、`LearningStrip.doupo.test.tsx` 的真实组件断言多处重复。
- 删除这份源码文字扫描专项测试，不再用硬编码文风禁词充当产品质量指标。将仍有价值的用户可见契约收进真实渲染测试：默认流萤卡展示起步/低金/老牌配置/高配四阶段、旧数据库索引教材不出现；斗破循环确实展示“公开硬证据”。现有 10 张内容卡、交互、实际爽点循环、叙事节奏与信息呈现测试全部保留。
- 没有运行时功能、接口、配置或 CI 单独入口需要删除。只属 `priority=P3`、`loop=static`、`owner=UI/tests` 的工程减负，不声明产品体验实测改善；精确 PR HEAD 的前端 Vitest/TypeScript/Vite CI 待验，付费模型与真实浏览器 `not_run`。

### 2026-11-19 P1 聊天空白终态防护（独立候选）

- **真实历史样本与当前缺口分开归因**：`docs/research_quality/ANSWER_AB.md` 的
  N16（2026-10-30）记录了研究结果 `completed` 但 `source_block_chars=0`、用户
  无最终答案；现行 `WebLookupRepository.complete` 已将“尝试读取且全部失败、无正文”
  改为 `partial`，`tests/test_web_lookup_run.py` 已有负控，不重复更改该修复。
  这条历史样本**不是**本片聊天模型空白输出的直接复现。
- **本片独立静态复现**：普通聊天模型返回 `""` / 纯空白，以及 SSE 无 token /
  只有空白 token，修复前四项负控均失败：后端持久化 `completed`，SSE 发送
  `done` 且无可见回答。`ChatService._complete_turn` 现在在真正完成写入前
  拒绝空白发布内容，写入 `failed` 与 generation `error`，释放操作所有权，
  让现有重试逻辑可在新 operation 下成功；SSE 发 `error` 而非 `done`。
- **边界**：不改已有非空答复、资料绑定、研究证据发布、预算、数据库结构、
  取消优先级或续写契约。原始负控 **4 failed**，修复后 **4 passed**；
  完整聊天/发布/中断/恢复影响集 **238 passed**，历史研究终态对照
  **3 passed**，全库 Ruff 与差异检查通过；mypy 已有债务基线
  **115/125（无新增）**。
  priority **P1**（无有效终态），loop **static**，owner **orchestration-contract**；
  dynamic_evidence **not_run**，budget_authorization **not_applicable**，
  decision **engineering-only**，不能据此宣称真实模型端到端答案质量改善。
- 独立分支 `codex/p1-empty-chat-final-20261119` 基于
  `main@3d048553f6c16305677a55aa95fb49d49d0c3541`；精确 PR-head
  CI 与审阅是合并前的剩余门。后续最小产品验证仍应在用户授权的真实
  运行环境检查一次最终消息确实可见，并对历史真实失败任务做零费回放。

### 2026-11-19 实验室入口重复源码断言收敛（独立测试减负片）

- 前端实验室入口拥有三层验证：`extensionLabBoundary.test.ts`、
  `extensionViewBoundary.test.ts` 和 `useExtensionRuntimeBoundary.test.ts`，
  其中菜单唯一入口、延迟加载分支和三种能力选择多次按源码字符串重复断言。
- 保留真实浏览器 `extension-lab-journeys.spec.ts`（直接菜单中只有实验室、
  三种选项可见、选择前零扩展请求、选择后正确读取、返回焦点恢复），以及
  `useExtensionRuntimeBoundary.test.ts` 的控制器归属、恢复、按需加载和协调权威
  负控；`extensionViewBoundary.test.ts` 继续验证组件绑定和宿主隔离。
- 删除全为旧入口快照断言的 `extensionLabBoundary.test.ts`（4 项），并删除
  `extensionViewBoundary.test.ts` 中已经由运行期边界测试保护的 1 项重复
  能力加载断言。没有更改在用实验室、路由/权限、运行配置或 E2E 注册；
  这是 P3 离线测试减负，不是体验改善结论，精确 PR CI 另行验收。

### 2026-11-19 未挂载的旧回答检查器退役（独立 UI 减负片）

- `frontend/src/features/route/RoutePanel.tsx` 的唯一组件调用方为自己的
  `RoutePanel.test.tsx`；当前 App、路由及其它组件没有挂载该旧“回答检查器”。
  2026-07 的界面设计文档已要求将展示职责收敛到 EvidenceTrail，不再独立
  挂载旧面板；本片只删除从未呈现的遗留 UI，不重新设计现行诊断展示。
- 将该组件与 6 项专属组件测试、仅用于它的 `.route-grid` 样式、
  `AppBoundary` 中已无意义的禁用导入名称、CI 前端目录清单的 `route` 项
  一并退役；保留 `ToolPanel` 使用的 `.metric-row`、EvidenceTrail、
  正式后端 route 元数据与其现行安全/诊断测试。
- 无专属 API、适配层或运行时配置；只跑静态离线门禁，精确 PR HEAD 的 CI
  和审阅仍须单独通过，不能以本地删除结果宣称真实回答质量提升。

### 2026-11-20 旧单体新闻执行与审计产物整链退役（P3 静态减负）

- **调用核对**：旧 `wechat_service.run_news_round()` / `RuntimeContext` 与搜索、正文读取包装函数只有 `test_wechat_service.py` 中 4 项专项测试调用；正式 API 的新闻流程由 `NewsService` 经 `NewsRepository` 分阶段提交搜索、读取、摘要与讨论，调用的是仍在使用的 `run_digest_stage`、`run_discussion_stage`，不是单体入口。
- **成组删除**：旧单体 runner、独占的 `src/news/audit.py` JSON/Markdown 审计落盘器、`build_pipeline_trace` 整轮汇总/Markdown 展示及 `feed_health_rows` 适配、专属 `test_wechat_service.py` 和 `test_news_audit.py`。原 pipeline 测试中仅服务旧整轮报告的 3 项一并删除；保留并改名为 `test_news_item_trace.py` 的 2 项仍验证在线源块使用的逐条证据、域名策略与跳转链。仓内无该旧链专用 CI、阶段门或运行时开关需要额外清理。
- **保留的现行契约**：`format_news_source_block` → `build_item_trace`、摘要覆盖率与警告、群聊状态同步、`NewsService` 失败回滚/重试/持久化以及活跃的 API、群聊与来源追溯测试不变；不更改查询/读文章预算、模型次数、checkpoint、对外接口或证据展示。同步修正 `docs/NEWS_PIPELINE.md` 对已不存在审计文件的描述。
- `priority=P3`、`loop=static`、`owner=news/legacy-audit`、`dynamic_evidence=not_run`、`budget_authorization=not_applicable`、`decision=engineering-only`。本地静态检查及精确 PR HEAD CI、审阅单独记录；无真实检索或付费模型实测。

### GitHub PR 历史静态回放评估链退役（2026-11-19，独立减负片）

- `record_github_replay.py` / `evaluate_github_replay.py`、三份专属
  `github_pr_review_{recording,replay,evaluation}` 模块及其专项测试，
  只在彼此之间调用；正式 API、`studyctl`、现行 CI/阶段门、前端均不依赖。
  17 份已录制的 PR 上下文及配套 manifest 仅被这条手工回放测试链读取。
- 此回放统计的是**固定 JSON 快照**的符号映射/CI 关联精确率，
  并不重新执行当前审查实现，历史分数不应被当成当前产品的回归门禁。
  本片连同静态测试数据整体退役，不另立兼容入口；归档报告仍可供历史核对。
- **保留** `GitHubPRReviewContextService`、GitHub Provider 分页和现行
  `test_github_pr_review_context*` / `test_github_provider_pagination.py`，
  真实 API 审查、固定 SHA、预算边界与缓存行为不变；不发起外部 GitHub 请求。

### 2026-11-19 读取计划的累计来源簇覆盖职责提取（独立 P3 静态片）

- **范围**：从 `active_research_runtime.execute()` 的读取计划阶段提取 `merge_covered_clusters(context, selected_sources)` 至 `research_runtime_read_coverage.py`；执行器只传递当前持久化上下文与实际来源列表，覆盖合并及排序回写由读取覆盖模块负责。原 `ACTIVE_RESEARCH_COVERED_CLUSTERS_KEY` 在执行器中继续可导入，持久化键值不变。
- **冻结契约**：已有波次的累计簇覆盖不能丢失；一份物理读取的来源簇同时归属 assessment 所有者及 extraction map 绑定的其他 claim；失败读取及缺少合法 assessment 的记录不新增覆盖，旧数据格式的宽容处理与稳定排序保留。**不改**候选选择、读取额度、恢复游标、模型尝试/预算、检查点位置/顺序或证据发布。
- **证据**：改动前两项真实执行器累计/共享来源簇回归 **2 passed**；改动后覆盖专项及研究执行/恢复/检查点/预算/读取关联测试 **131 passed**，Ruff、差异检查、mypy **115/125（无新增）**通过。基线 `main@56e2f23e`；单独分支 `codex/research-read-coverage-20261119`，与正在等候精确 CI 的 #517 测试去重 PR **没有代码依赖**。`priority=P3`，`loop=static`，`owner=retrieval/read-planning`，`dynamic_evidence=not_run`，`budget_authorization=not_applicable`。无真实付费模型/浏览器/外部搜索或产品动态对比。
- **下一执行片**：完成本独立片的干净提交、PR 推送及精确 HEAD CI 记录；仅当该 SHA CI 全绿、审阅无阻断且无冲突才合并。#517 仍按其独立精确 CI 完成收口，不能复用其它提交的绿色结果。

### 2026-11-20 无效新闻已读条目持久化链退役（P3 静态减负）

- **证据**：`fetch_news_items()` 在每轮搜索后调用 `mark_seen_entries()` 把历史 URL 写入 `logs/news_feed_state.json`；但生产调用方从未读取 `seen_entries` 决定候选、排序、去重或结果，`filter_unseen_entries()` 的仅有调用是自身 2 项测试。结果是新闻历史键随检索增长，文件写入却无实际效果。
- **成组删除**：去掉每轮无效写入、`FeedState.seen_entries` 持久化字段、读/写转发、`entry_key`、`mark_seen_entries`、`filter_unseen_entries`、2 项独占测试，以及零调用方的 `fetch_latest_news_items` 单行历史包装入口。不保留新兼容方法，也无专属配置/CI 项；旧状态中的 `seen_entries` 被宽容忽略并在后续健康状态写入时淘汰，其他字段仍按原 schema 读取。
- **保留**：SearXNG/RSS 搜索及单次检索的标题、规范 URL 去重与缓存；有实际消费方的 feed 健康成功/失败、错误、ETag、Last-Modified 记录、重试与警告，以及正式 `NewsService`。健康写入测试继续校验有效字段，并核对输出仅含 `health`；不更改返回的新闻项目、模型、检索预算、checkpoint 或研究证据发布。
- **基线/边界**：基于已合并 #549、#551、#550 的 `main@c5174e19`，独立 `codex/retire-news-seen-state-20261120`；另有 #552 精确 CI 已成功但仍须核对可合并性，#553/#554 在本轮首次 CI 查询时尚在运行。`priority=P3`、`loop=static`、`owner=news/feed-state`、`dynamic_evidence=not_run`、`budget_authorization=not_applicable`、`decision=engineering-only`；精确候选 CI/审阅待验，不发起真实 RSS/付费模型。

### 2026-11-19 旧迁移路线图展示组件退役（独立减负片）

- `frontend/src/features/migration/RoadmapPanel.tsx` 只被自己的两项组件测试引用；
  应用入口、路由、构建入口、其它功能和 E2E 均未挂载该组件。原静态内容仍在
  叙述已完成的 Streamlit→React 迁移，并非在用产品功能。
- 连同 `RoadmapPanel.test.tsx` 和 `styles.css` 中仅服务该面板的
  `.roadmap-list` 样式一起退役；保留与之共用原选择器的 `.session-list`、
  `.session-row` 样式。历史设计文档已允许移除旧面板，仍按原文归档。
- 首次 PR CI `44518827611` 前端与构建通过，但全量后端测试
  `test_every_frontend_feature_directory_is_registered_or_declared` 发现
  `tools/ci_scope.py` 仍将已不存在的 `migration` 目录列为“未注册”特例。
  后续连同这项死配置一并删除，保留前端目录清单的完整性校验，不放宽门禁。
  本批不改应用布局、真实聊天/研究功能、迁移机制或运行时配置；新候选
  必须重新取得精确 HEAD CI 成功。历史设计文档继续保留归档。

### 2026-11-19 历史会话导航适配壳退役（独立 P3 静态片）

- 已核实 `WorkspaceView` 的侧栏与抽屉均直接挂载 `SessionNavigator`，不再引用 `SessionsPanel` / `SessionSidebar`；组件、生产入口、E2E、注册表都没有其它调用。两只旧壳只被自己的源码结构测试和重导出测试维持。
- 一并删除两个兼容包装、只验证包装存在的 `SessionNavigatorBoundary.test.ts`、`SessionsPanel.test.ts` 和 `AppBoundary` 对旧类名的禁用断言；原 `sessionIdFromRow` 三种解析场景迁入正式 `sessionNavigation.test.ts`，继续保护实际导航使用的解析函数。保留 `SessionNavigator` 两种展示模式及其真实交互测试、所有在用会话 API 和共用样式。
- 本批只减少过时兼容与重复测试，不改变数据格式、恢复、模型、预算和显示逻辑；定向导航/App 边界 **13 passed**，生产 TypeScript/Vite 构建通过；默认高并发全量 Vitest 曾受资源争用影响，出现 2 个超时与 worker 启动错误，限制为 `--maxWorkers=2` 后完整前端 **126 files / 740 passed**。`git diff --check` 通过；仓库 Ruff 由精确 PR CI 再验。`priority=P3`、`loop=static`、`owner=UI/tests`、`dynamic_evidence=not_run`、`budget_authorization=not_applicable`、`decision=engineering-only`。

### P1 SSE 终态正文与界面一致性（2026-11-19，独立静态片）

- **等级/归属**：P1 预防性修复，UI/传输发布契约；未从真实用户
  任务轨迹归因，故仅为 `static / engineering-only`。假 SSE 负控先红：
  ① 服务端 `done.reply` 已发布修订答案，但前端请求层仍返回先前 token 草稿；
  ② 服务端 `cancelled.partial` 是持久化部分正文，但浏览器没收到 token
  时，请求层返回空串且聊天控制器在取消回调后再次清空已恢复的内容；
  ③ 服务端明确发布空正文时，控制器的 `||` 回退会重新显示未发布草稿。
- **实施**：独立分支 `codex/p1-sse-final-authority-20261119`，基线
  `main@c6e8e6c4af37fd4731d109da584b2914015cbb7c`。SSE `done.reply`
  以服务端最终正文为权威返回值，`cancelled.partial` 以服务端持久化部分为
  权威；控制器保留已结算的取消状态和恢复卡，使用 `null` 区分“没有终态”
  与“终态明确为空”，拒绝草稿回流。仅改前端传输与控制器、相应测试；
  不改后端生成/存储、研究证据门、成本或模型调用。
- **证据/限制**：四项终态负控及相邻影响集与 TS/Vite 构建见对应 PR；
  默认 Playwright 用例尝试时缺少所需 Chromium，系统 Chromium 又因执行
  环境拒绝创建 socket 而退出，故真实浏览器可见性 `not_run`，需要在
  具备浏览器权限的 CI/人工环境再验；真实模型、搜索、付费比较 `not_run`，
  预算授权 `not_applicable`，不据此宣称实际用户体验已验证。
- **主线重新整合**：基于 `main@3ac77fd6` 将 #522 重挂；唯一冲突为本
  交接文档，保留主线检查点修复记录和当前 SSE 契约记录，未改变实现范围。
  前端相邻影响集 **95 passed / 7 files**，TS/Vite 生产构建、全仓 Ruff、
  差异检查与 mypy 基线 **115/125（无新增）**通过；新 HEAD 的远端 CI
  仍须独立验收，不能复用旧提交结果。
- **进一步主线整合**：上一 HEAD `3ee86fb8` 的 CI `44491085376` 已
  成功，但 `main` 又加入模型审计与失败终态发布改动；以 `main@82399918`
  重新挂载 #522，只保留其前端传输、控制器与测试修改。冲突仅为本交接
  文档，已保留研究终态发布记录；新 HEAD 仍需独立 CI 和审阅验收。
- **本轮终态补强**：已核对正式后端的 `finish_cancelled_turn`：SSE
  `cancelled.partial` 只包含本次生成的可发布后缀，续写时会与此前已保存
  的前缀一起持久化。浏览器旧实现却优先拿临时 token 充当恢复正文，
  即使服务端保存为空也残留未发布草稿。三条负控（临时 token 与服务端
  partial 不一致、服务端明确空 partial、续写时前缀 + 服务端后缀）
  先失败后修复；恢复与可见正文现在均从服务端部分正文构造，临时 token
  只用于执行中的预览。属于 P1 静态交付一致性，不宣称实际模型体验已验证。
- **当前整合**：基于 `main@bab64534` 保留 #479 选源观测、#481
  已合并交接记录，唯一冲突仍为本状态文件；#522 前端修复与新增负控
  一起进入精确候选，需在新的 HEAD 上重新跑 CI 才可合并。
- **2026-11-19 收口进度**：上一精确 HEAD `a23c3bba` 的 CI
  `44504307978` 成功、无审阅阻断；随后主线合入 #523 与 #521。
  现重新整合至 `main@77caf8b6`，唯一冲突是本交接标题，保留主线
  附件材料与可读性契约，不改变本 PR 前端 SSE 生产代码；新的精确
  HEAD 必须重新跑 CI，不能沿用上一绿色结果。
- **下一独立片**：#522 与 #524 完成合并后，用 Fake Provider 核验
  附件进入模型入参与用户界面最终交付的完整链路；真实模型和搜索
  需独立授权与预算上限。
- **合并收口**：#522 最新精确 HEAD `fe50537c` 的 CI `44509211830`
  成功，审阅线程为空，已按预期 HEAD 合入 `main@f133aebf`。

### P1 附件异步请求的会话归属（2026-11-19，#524 独立片）

- **等级/归属**：P1 数据归属与消息选中安全，`UI / session-bound async result`；
  基于现有代码与先红负控的工程风险，未从真实用户轨迹归因，属于
  `static / engineering-only`。独立增量分支
  `codex/p1-attachment-session-selection-20261119` 以 #523 的已验证树为
  前置依赖，不把叠加结果误报为直接基于 `main` 的合并资格。
- **根因与修复**：原 Composer 的旧会话附件列表、上传、首次自动建会话、
  删除请求在等待网络结果期间可能遇到导航切换；完成回调仍能写入
  当前附件列表、误选当前消息，或让新会话持续显示旧上传的 busy。
  现在用 `session id + visit generation` 约束异步回写，阻断“切走又
  切回同一 ID”的过期响应；列表、错误与上传忙状态都按所属会话展示。
  首次上传创建的会话如已被父级接管，只有返回同一 ID 才继续上传；
  旧会话删除完成不得清理当前选择。服务端存储与鉴权未更改。
- **离线负控**：旧列表晚返回、旧上传完成后会话变化、首次建会话
  晚返回、父级接管同一新会话、回到同 ID 的旧请求、旧删除晚返回均有
  专属前端用例；先红 3 项，修复后 Composer 与相邻 UI 影响集
  **77 passed / 7 files**，TypeScript/Vite 生产构建、全仓 Ruff、
  差异检查和 mypy 基线 **115/125（零新增）**通过，无 Python 代码变更。
  已再次重挂到 #523 修复浏览器夹具后的精确 HEAD `c94f8f5f`
  （其基线 `main@82399918`），仅带入 #524 的三文件增量；此新树重验
  **77 passed / 7 files**、TS/Vite 构建、Ruff 与 mypy 115/125 通过。
  新 HEAD 的 CI 仍须独立验收，不能借用 #523 或旧 #524 的结论。
  实际浏览器、付费模型、云视觉、搜索与动态竞品对比 `not_run`，
  预算授权 `not_applicable`。
- **后续**：#521 服务端材料绑定与 #523 前端可读性验收合入后，
  用 Fake Provider 完整核验上传→选择→发送→模型收到正文；叠加 PR
  须在前置 #523 合入后重新挂到主线，重新验证精确 HEAD CI。
- **主线收口（2026-11-19）**：#523 精确 HEAD `c6ea4987` 的 CI
  `44502846780` 成功、无审查阻断，已 squash 合并到 `main@2ae50fc7`。
  本片保留原 3 文件会话归属增量，直接重挂到这一最新主线，不再把
  #523 的可读性代码作为 PR 差异；本次本地验收及新精确 HEAD CI
  需分别记录，不能借用叠加分支的绿色结果。下一步是按精确新 HEAD
  验收并合并 #524，再做附件→模型可见材料的零付费闭环。
- **进一步整合（2026-11-19）**：#521 后端可读材料校验的精确 CI
  `44506118129` 成功并合入 `main@77caf8b6`；#524 保持独立 3 文件
  增量，重挂该主线。唯一冲突为本交接记录，前端会话所有权实现未改；
  由于上次在叠加 PR 阶段更新 HEAD、后切换 base 至 `main`，新 HEAD
  未观察到 PR CI，因此本次以正式 `main` 为 base 再发布精确提交，
  必须等待真正针对该提交的 CI 验收。
- **最新整合**：原 HEAD `e877c669` 的精确 CI `44509511046` 成功且
  审阅无阻断，但 #522 合入后交接文档产生唯一冲突；保留两片记录，
  在 `main@f133aebf` 上重新生成本片候选。新提交仍须独立精确 CI。

### P1 本轮附件真正进入模型请求（2026-11-19，独立静态片）

- **等级/归属**：P1，编排契约与附件读取层；无本轮真实用户失败轨迹。
  静态负控复现：① 未开视觉识别的图片为 `ready`，选中后却没有可读内容；
  ② 已就绪文档的临时索引丢失，选中后仍被接受；③ 消息绑定 5 份附件，
  原读取默认只取前 4 份，模型看不到第五份；④ 入口验证通过后附件绑定
  或正文失效，以及重试绑定内容哈希变化，可能不被检测到。
- **本片**：`codex/p1-attachment-visible-material-20261119`，基线
  `main@e5ec70059d35c9e209768d8461b2440ece6da83c`。消息/研究队列/
  研究 steering 选择必须有实际可读的索引内容，否则返回可解释的冲突并阻止提交；
  聊天进入模型/研究工具前再检查已保存的 ID 与内容哈希，并复用同一份
  快照到提示词和研究工具。每条消息最多 10 份的全部已选内容按 12,000
  字符总预算公平节选，不再默默丢失第五份；明确标示截断以及图片描述不等于原图。
  原有存储 `ready` 状态不改：它只证明上传/存储完成，不保证模型可读取。
- **证据边界**：负控旧行为先红后绿，假模型实际入参逐份包含五个附件的标记；
  本地离线 Ruff、相关 L1、mypy 基线和 diff 范围核验见对应 PR。
  未调用付费模型、视觉 API 或真实浏览器，**不宣称真实图片理解或用户任务已成功**。
  不含前端“已就绪”徽标语义调整和完整 SSE 可视化验收。
- **2026-11-19 主线重挂**：主线推进到 `main@3ac77fd6ca2f33c34f639d84993dd6c07361236a`
  （#514 检查点回绑），原 #521 的唯一冲突是本节与 #514 的交接标题。
  两条现状均保留，附件与研究运行期生产代码无语义冲突；更新候选
  在 13 个直接影响模块 **141 passed**，全库 Ruff、差异检查和 mypy
  **115/125（无新增）**通过。新远端 HEAD 须独立通过精确提交 CI，
  上一 SHA 的结果不能替代；真实模型与浏览器 `not_run`。
- **失败 CI 修复与新主线整合**：旧 HEAD `be5f4769` 的 CI `44490460070`
  完成 **6769 passed / 1 failed**；失败只在历史 D1 持久化测试将附件引用
  当作可读取正文，触发新验证器正确拒绝。已在该测试夹具补充与引用哈希
  一致的可读取材料，保留生产 fail-closed 逻辑与负控；受影响后端测试
  **52 passed**。再次整合 `main@82399918` 时仅交接文档有冲突，保留
  主线终态发布记录；Ruff、差异检查、mypy **115/125** 通过。
  浏览器和动态模型调用 `not_run`，新精确 HEAD CI 尚待独立验证。
- **主线收口（2026-11-19）**：原精确 HEAD `41c46fc4` 的 CI
  `44499999149` **success**，无审阅阻断；主线已合入 #479 和 #523，
  此次重挂到 `main@2ae50fc7`。冲突仅涉及本交接章节，保留附件 UI
  可读性与研究观测记录，不改变后端材料验证行为。新的精确 HEAD
  须重新 CI 验收，不能复用旧绿色结果。
- **下一独立片**：#521 合并后，以 Fake Provider 验证“上传→选择→发送→
  模型实际收到全部可读材料→界面显示发布答案”；真实付费模型、视觉和
  搜索需要另外授权，不把离线证明当作动态产品结论。

### P1 附件保存状态与消息可读性分离（2026-11-19，独立静态片）

- **等级/归属**：P1 防止用户把不可用文件当成已交给模型的附件；
  `UI / attachment-readability contract`，仅由服务处理记录与离线
  负控证明，未归因于真实用户轨迹，标记为 `static / engineering-only`。
  基线 `main@c6e8e6c4af37fd4731d109da584b2914015cbb7c`，独立分支
  `codex/p1-attachment-readability-ui-20261119`，不叠加未合并的 #521/#522。
- **证据与修复**：服务端对未启用云端图片理解的图片会写入
  `status=ready`（保存/流程结束）及 `indexing.retrievable=false`
  （无可用正文）。原 Composer 只检验 `ready`，会显示“已就绪”、
  允许手动选中并在上传后自动选入消息。现在只接受末次 indexing
  明确 `completed + retrievable=true` 的附件；无记录时保守拒绝。
  上传混合可用/不可用文件只选可用项，刷新时移除已有不可读选择，
  保留并发上传期间其它有效选择；图片显示“已保存·未识别”并提示
  开启云端图片理解后重新上传。来源面板共用状态判定，不再展示
  不可读正文的阅读入口；文件大小提示在刷新后不被清除。
- **静态门禁**：先红的负控覆盖未识别图片自动/手动选择、混合上传、
  历史选择清理与来源面板不可读正文；重挂 `main@b677d74c` 后的
  前端相邻影响集 **71 passed / 7 files**，TypeScript/Vite 构建、
  全仓 Ruff、`git diff --check` 和 mypy 基线 **115/125（零新增）**通过。
  重挂时唯一冲突为本交接文档，保留主线的模型审计/检查点记录；
  新精确 HEAD 的 CI 仍须独立验收，不能沿用旧提交通过结果。
  真实浏览器、真实图片模型、搜索或付费动态对比 `not_run`，不得据此
  宣称用户任务端到端完成。
- **失败浏览器 CI 修复与新主线整合**：旧 HEAD `2d5c0f59` 的 CI
  `44496632775` 仅在连续研究会话的桌面/移动 Chromium 用例失败：
  `notes.txt` 测试夹具虽为 `ready`，却没有 completed/retrievable 的
  indexing 记录，新 UI 因此正确地拒绝自动选中。已仅修复夹具，
  不放宽生产可读性门。重新整合 `main@82399918`，唯一冲突仍为交接
  文档；相邻前端测试 **71 passed / 7 files**，TS/Vite 构建、Ruff、
  差异检查和 mypy **115/125** 通过。Playwright 用例清单已解析，
  真正浏览器执行仍须在新精确 HEAD 的 CI 重新验收。
- **合并收口重挂**：修复夹具后的 HEAD `c94f8f5f`，CI `44499994030`
  已成功且审阅线程为空。主线随后合入 #479（`main@bab64534`），
  因交接标题冲突无法直接合并；本次保留主线 #479 诊断与 #481 已合并
  记录，仅将 #523 的原 UI/测试增量重挂，新精确 HEAD 必须重新 CI 验收。
- **下一独立片**：待 #521 的服务端选中正文契约验收合入后，使用
  假 Provider 做“上传 → 选中 → 发送 → 模型可见材料”的离线跨层负控；
  同时审计原会话切换与队列发送期间的附件选择隔离，不开付费 API。

### 2026-11-19 选源追踪上下文所有权（独立 P3 静态片）

- 将 `SelectionTraceCollector` 的历史指标恢复、运行期状态持有和指标刷新交给 `research_selection_observability.ResearchSelectionTraceContext`；执行器只在原有位置初始化一次，并在原波次位置调用 `flush(live.context)`。原 `_flush_selection_trace` 私有包装与仅依赖它的测试调用一起删除，测试转为验证新上下文。**不改**选源排序/过滤、trace 字段、指标键、保留上限、恢复游标、模型预算、检查点或发布契约。
- 新负控验证恢复后指标回读、检查点回绑新 context 后的写回、旧映射不被改写、损坏指标与空追踪时无副作用。本地同树选源/执行/读取观测/恢复/检查点/预算组合影响集 **154 passed**，专项测试及 Ruff、差异检查、mypy **115/125（无新增）**通过。基于 `main@964a52cd` 的独立分支 `codex/research-selection-trace-context-20261119`，与待验收 #527 无代码依赖。`priority=P3`，`loop=static`，`owner=observability`，`dynamic_evidence=not_run`，`budget_authorization=not_applicable`，未进行付费模型、搜索或动态对比。
- **下一执行片**：单独推送本批 PR，精确 HEAD CI、审阅和主线无冲突后才能合并；#527 仍须以自己的精确提交 CI 收口。

### 2026-11-19 读取候选测试搭建去重（#517 已合并）

- `tests/research_read_candidate_factory.py` 合并读取调度、执行、投影测试内三份重复的 `CandidatePoolItem` 构造；保留 ID、URL、标题和来源场景原值，不改生产检索、读取、恢复、检查点或预算。
- #479 精确 HEAD `9086a708`、CI `44499513153` 成功且无审阅阻断，已合并 `main@bab64534`。#517 保留 P1 附件/SSE/真实服务栈回归主线内容，仅迁移测试场景去重；新精确 HEAD `4bd57091`、CI `44515032318` 成功、无审阅阻断，已 squash 合并为 `main@964a52cd`。读取/选源影响集 **37 passed**，此前跨恢复、检查点、模型预算、发布、选源和读取组合影响集 **151 passed**，Ruff、差异检查通过。`priority=P3`，`loop=static`，`owner=orchestration-contract`，`dynamic_evidence=not_run`，`budget_authorization=not_applicable`。

### 2026-11-19 选源窗口诊断职责整合（#479 已合并）

- #481 精确 HEAD `b1f2729b` 的 CI `44497014870` 全绿、无审阅阻断，已 squash 合并到 `main@82399918`。#479 基于这条主线重新挂载；`research_selection_observability.record_selection_authority()` 接管选源输入指纹、候选变化数、排除状态变化、独立的开始/结束时钟采样与最近 40 条记录。`active_research_runtime` 仍负责模型准入、选源、退化与实时 context 回读；不转移检索策略或模型预算所有权。
- 专项负控覆盖连续波次输入变化、两个独立计时采样以及损坏历史记录后的 40 条上限。本地相同代码组合影响集 **112 passed**、Ruff 和差异检查通过，mypy **115/125** 无新增。此批 `priority=P3`、`loop=static`、`owner=orchestration-observability`、`dynamic_evidence=not_run`、`budget_authorization=not_applicable`；精确 HEAD `9086a708`、CI `44499513153` 成功，已合并 `main@bab64534`。

### 2026-11-19 失败终态发布上下文整合（#481 已合并）

- 旧 #481 在当前 #512—#515 整合树上重新实现：`ActiveResearchPublisher.fail` 统一持有无证据终态的 repository 调用，三处规划失败与异常无证据路径不再传递四个共享结果列表。`_terminal_unavailable` 从当前结果缓冲区读取证据 ID，仍在原位附加游标、Claim Engine 状态、执行 Stop Gate，再发布；检查点、模型计费、恢复格式、读取策略均不变。
- 新负控固定恢复后 `research_context`、实时查询尝试列表、操作租约与失败原因；本批属于 `priority=P3`、`loop=static`、`owner=orchestration-contract`、`dynamic_evidence=not_run`、`budget_authorization=not_applicable`。精确 HEAD `b1f2729b` 的 CI `44497014870` 成功，已合并 `main@82399918`。

### 2026-11-19 模型尝试实时状态绑定（重新验收候选）

- 在检查点顺序、游标、持久化上下文、波次交接与检查点回绑的最新组合上重挂模型审计绑定；必须以新精确 HEAD 的 CI 验收，不沿用旧提交的结果。

### 2026-11-19 检查点准备回绑单一持有（重新验收候选）

- #510 已在主线，因此本批只保留 `live.bind_prepared_checkpoint` 对 `prepare_and_persist` 的回绑：移除多余内部函数，保证准备抛异常时 state/context 同时回绑。原 #514 的双父合并历史不再重复带入已合并的 #510 内容；新树需精确 HEAD CI。

### 2026-11-19 波次绑定重挂检查点整合树（重新验收候选）

- 将 #513 的波次交接绑定协议重挂在已更新的 #512 上。保留 #510 的检查点顺序和 #511/#512 的单一运行期状态所有权；此候选需要新的精确 HEAD CI，不能沿用旧的绿色结果。

### 2026-11-19 持久化上下文所有权与检查点顺序重新整合（重新验收候选）

- 基于已合并 #510 的 `main@a63e9440` 和重新挂载的 #511，重新应用 #512。冲突点为检查点内的 `nonlocal context`，统一回绑 `live.state/live.context`，但保留 `ActiveRuntimeCheckpointContext.prepare_and_persist` 的准备、回绑、持久化顺序。该候选需独立精确 HEAD CI。

### 2026-11-19 游标单一持有与检查点整合（重新验收候选）

- #510 已以精确 HEAD `36a377e4`、CI `44375838320` 成功验收并合入 `main@a63e9440`。#511 原 HEAD `3d361a39` 的 CI 已成功，但因主线推进产生冲突，基于当前 `main@a63e9440` 重新应用游标所有权变更；恢复与检查点的现有实现保持 #510 语义，重新验证精确 HEAD 后才允许合并。

### 2026-11-19 检查点准备与持久化顺序封装（已合并）

- 后续本地补强：检查点专项测试共用统一构造器，新增成功路径顺序负控，明确 `bind_prepared` 必须先于仓库 `checkpoint`；检查点、实时状态、波次结算和守卫专项集 **10 passed**，未触及生产代码。此补强仍属于未推送的同一候选，不能代替 L3 或远端 CI。
- 基于上一状态单一持有候选 `e13960c8`，分支 `codex/research-cursor-context-20261119`。将主动执行器检查点内的 `prepare → finally 回绑状态/上下文 → persist` 提取为 `ActiveRuntimeCheckpointContext.prepare_and_persist`，明确准备异常后仍回绑已投影的内存值，同时禁止失败后继续持久化；执行器仍唯一持有实时状态、游标和持久化上下文，后两者不作双份镜像。
- 专属负控冻结 Claim Engine 序列化异常时预算投影与游标上下文保留、仓库不写入；检查点、实时状态、波次结算、守卫与主动执行影响集 **93 passed**，Ruff、差异检查及 mypy 基线 **115/125（无新增）**通过。全量 L3 已启动但观察到首 1% 用时较长，为避免无界后台执行而中断，**尚未通过**；远端精确提交 CI 待验收。真实搜索、付费模型与动态比较 `not_run`，预算授权 `not_applicable`。属 P3 / static / orchestration-contract / engineering-only。下一片在主线整合后处理游标、持久化上下文的单一所有权，不在本片同时迁移。
### 2026-11-19 模型审计与实时状态绑定（独立叠加候选，待验证）

- `ActiveModelAttemptContext.for_live_values(live, ...)` 以最小 `LiveModelAttemptValues` 协议统一绑定当次研究的实时状态/游标；执行器不再分别拼接三个状态读取/回写回调。新负控覆盖恢复后状态替换的预算检查、检查点后波次游标替换时审计写回最新游标。
- **冻结契约**：开始审计仍按 `ensure_active → ensure_budget(current_state) → begin_model_attempt → checkpoint`，结束审计仍只在内存完成并在 `ensure_active` 后交还控制；模型网关、真实调用次数、超时预算采样、结算和后续语义检查点均不变。影响集 **104 passed**，Ruff、差异检查及 mypy 基线 **115/125** 通过。本片 P3 / static / orchestration-contract / engineering-only；真实模型/搜索 `not_run`，预算授权 `not_applicable`。依赖前述整合候选，不能直接合并主线。

### 2026-11-19 检查点顺序与实时状态持有者整合演练（本地，待验证）

- 将 #510 检查点 `prepare_and_persist` 与 #511—#513 的 `ActiveRuntimeLiveValues` 在独立演练分支组合。冲突点是旧 #510 的 `nonlocal context` 绑定闭包；改为 `live.bind_prepared_checkpoint` 绑定方法，保证准备阶段异常时仍先回绑最新 state/context，不重引入双重上下文所有权。整合影响集 **123 passed**，Ruff、差异检查及 mypy 基线 **115/125** 通过；真实模型和检索 `not_run`，本地 L3 `not_run`。该演练不代表任何现有 PR 已合并，也不替代精确远端 HEAD CI。

### 2026-11-19 波次交接绑定协议（叠加候选，待验证）

- 在 #512 的上下文单一持有之后，`ActiveWaveSettlementHandoff.for_live_values()` 显式接受仅含 `state/cursor/context` 的 `LiveWaveValues` 协议，负责捕获和回绑快照；`execute()` 不再定义 `bind_wave_snapshot` 内部函数或快照捕获 lambda。测试使用真实 `ActiveRuntimeLiveValues` 构建波次场景，删除测试自己维护的重复绑定逻辑。
- **冻结契约**：`settle()` 的 `try/finally` 回绑、检查点失败后的最新投影回读、steering 处理与发布顺序保持不变；没有更改持久化格式、预算/模型调用、检索策略。本片属 P3 / static / orchestration-contract / engineering-only；真实模型与搜索 `not_run`，预算授权 `not_applicable`。此片是叠加 PR，必须等前序 #511/#512 验收后再重挂主线。

### 2026-11-19 持久化上下文单一持有（叠加候选，待验证）

- 在游标单一持有候选之上，分支 `codex/research-context-single-owner-20261119` 将一次 `execute()` 的持久化 `research_context` 交由同一 `ActiveRuntimeLiveValues.context` 持有；不留与其并行的局部字典。Deep 预检、游标恢复、steering 刷新、规划、检索/读取、模型回调、证据整理和波次交接通过该持有者读取当前上下文。
- **冻结契约**：检查点仍是 `prepare → finally 回绑 state/context → persist → 持久化 context 回读`；波次交接仍一次性回绑 state/cursor/context；模型尝试、预算结算、证据发布、Deep 预检和持久化结构均不增删动作。负控覆盖检查点/波次替换后回调读取最新字典、不同执行默认上下文隔离。本片属 P3 / static / orchestration-contract / engineering-only；动态模型与真实搜索 `not_run`，预算授权 `not_applicable`。
- 此片依赖游标候选；检查点顺序独立 PR #510 尚未整合时，不在本片同时改变检查点实现。验证结果以本分支精确 HEAD 和后续 PR CI 为准。

### 2026-11-19 运行期游标单一持有（当前独立候选）

- 基于 #508 已合并的 `main@455e1105`，分支 `codex/research-cursor-single-owner-20261119`；与仍待 CI 的检查点顺序 PR #510 分开，不提前合并两批语义。`ActiveRuntimeLiveValues` 除 `ResearchState` 外开始唯一持有 `ResearchRuntimeCursor`：执行器内的游标赋值、恢复后替换、外部调用审计、读取观测、模型回调、波次结算与检查点都使用 `live.cursor`；移除专为模型回调回写外围游标而存在的 `set_model_cursor` 闭包。
- **冻结契约**：持久化 `context` 仍只在执行器持有；不复制游标到其他可变持有者。两次中断尝试恢复、模型开始与完成审计、查询开始与结束、波次交接与检查点的位置和次数不变；`ResearchRuntimeCursor` 持久化结构与预算结算不变。新负控覆盖模型/读取回调跨游标替换读取最新值，以及不同运行不共享默认游标。真实检索、付费模型和动态比对 `not_run`。属于 P3 / static / orchestration-contract / engineering-only；整合及 CI 以候选精确 HEAD 为准。

### 2026-11-19 检查点准备与持久化顺序封装（当前候选）

- 后续本地补强：检查点专项测试共用统一构造器，新增成功路径顺序负控，明确 `bind_prepared` 必须先于仓库 `checkpoint`；检查点、实时状态、波次结算和守卫专项集 **10 passed**，未触及生产代码。此补强仍属于未推送的同一候选，不能代替 L3 或远端 CI。
- 基于上一状态单一持有候选 `e13960c8`，分支 `codex/research-cursor-context-20261119`。将主动执行器检查点内的 `prepare → finally 回绑状态/上下文 → persist` 提取为 `ActiveRuntimeCheckpointContext.prepare_and_persist`，明确准备异常后仍回绑已投影的内存值，同时禁止失败后继续持久化；执行器仍唯一持有实时状态、游标和持久化上下文，后两者不作双份镜像。
- 专属负控冻结 Claim Engine 序列化异常时预算投影与游标上下文保留、仓库不写入；检查点、实时状态、波次结算、守卫与主动执行影响集 **93 passed**，Ruff、差异检查及 mypy 基线 **115/125（无新增）**通过。全量 L3 已启动但观察到首 1% 用时较长，为避免无界后台执行而中断，**尚未通过**；远端精确提交 CI 待验收。真实搜索、付费模型与动态比较 `not_run`，预算授权 `not_applicable`。属 P3 / static / orchestration-contract / engineering-only。下一片在主线整合后处理游标、持久化上下文的单一所有权，不在本片同时迁移。

### 2026-11-19 研究状态单一持有（新独立候选）

- #495 的精确 HEAD `cd85309d`、CI `44359098528` 成功，已合并 `main@5c695ff8`；#502 的精确 HEAD `e7d2ebf1`、CI `44361647146` 全部成功、审阅线程为空，已合并 `main@47c8f041`。本片基于这两项收口后的主线，职责属 **P3 / static / orchestration-contract / engineering-only**，付费模型、真实搜索及动态产品比对 `not_run`，预算授权 `not_applicable`。
- `ActiveRuntimeLiveValues` 成为一次主动研究执行中 `ResearchState` 的唯一可变持有者。`execute()` 里的 86 处状态引用统一由 `live.state` 读取；规划、检查点准备、steering、预算刷新、证据投影和波次交接产生的新状态均写回该持有者。预算时钟和模型准入绑定持有者方法，跨检查点/恢复回绑后读到的始终是同一份实时状态。
- **冻结顺序与语义**：检查点仍先准备投影、即使序列化失败也先回绑局部状态/上下文，再持久化；模型尝试的开始审计→检查点→调用、完成计费/游标更新与后续检查点原位保留；波次完成、窗口观测、超时分支的诊断→检查点顺序不变。无持久化格式变更、无额外预算采样、检索/读取、证据发布或模型调用次数变更。`cursor` 和持久化 `context` **暂留执行方法局部变量**，不在本片复制进持有者；后续分别迁移单一所有权。
- 专属负控冻结「状态替换后，预算时钟与模型守卫同时读取恢复后的硬时限」；主动执行、Deep、检查点和恢复影响集 **156 passed / 1 skipped**，Ruff、差异检查及 mypy 基线 **115/125，无新增错误**通过。**全量 L3 与精确远端 HEAD CI 待验收**；不据此宣称产品体验改善。

### 2026-11-19 读取观测实时绑定（已合并）

- #493 的精确 HEAD `cee81a55`、CI `44351248954` 成功并合入 `main@083a0172`；#494 的重挂 HEAD `ee05454e`、CI `44357775209` 成功并合入 `main@cf54cc59`。#495 模型预算状态绑定提交 `cd85309d`、CI `44359098528` 成功合入 `main@5c695ff8`；本片 #502 的精确 HEAD `e7d2ebf1`、CI `44361647146` 全绿，已合入 `main@47c8f041`。
- 新增短生命周期依赖的 `ActiveReadObservationContext`，统一绑定生产读取器需要的最新 `context`、`cursor.wave_index`、相位开始/结束及重试耗时钩子。保留当前值读取回调，且在 `phase_end` 时重新获取可能已被检查点替换的 `context`；观测对象没有修改研究状态、游标、读取重试策略、预算或持久化的权限。
- 两条专属测试共享同一时钟/游标/上下文造景，冻结「相位开始之后上下文被替换，计时仍写入最新上下文」和「波次索引变化、重试计数仍读取最新游标/同一账本」。基于已合并 #494 的主线，生产读取语义、计时、主动执行与恢复整合影响集 **134 passed**，Ruff、差异检查和候选精确 HEAD CI 均通过。**P3 / static / retrieval+orchestration / engineering-only**，付费搜索及模型 `not_run`。

### 2026-11-19 搜索单次执行上下文（已合并）

- #490 已通过精确 HEAD CI `44347405572` 并合入 `main@56ebfd6f`；#493 的整合树已完成精确提交验收并合并，#494 的检索执行独立片以重挂提交 `ee05454e`、CI `44357775209` 成功并合入 `main@cf54cc59`。
- 从主动执行器的逐查询 `search_exact` 闭包抽出短生命周期 `ActiveSearchQueryExecution`；它显式接受本次查询的 `context/cursor/claim_id`、预算时钟、网关和相位计时器，持有该次 provider audit。旧的搜索发现顺序号、最新定向提示解析、可信线索提示提取都移入同一检索/观测模块；旧 `_lead_hints_for_claim` 通过执行器导入兼容现有测试及调用方。
- 冻结边界：`begin_external_attempt → checkpoint → search`、`finally finish_external_attempt → checkpoint`、查询结果归档后再次 `checkpoint` 不变。搜索超时计算仍取当次实时剩余硬预算且保留最终化预留；`last_search_audit → 搜索发现诊断 → phase_timing.end` 顺序不变。上下文不写回持久化、不结算预算，也不发布证据；搜索异常仍由候选池映射为 unavailable。
- 新测试共享搜索场景搭建，覆盖成功时实时截止时间/审计/发现序号/相位计数，以及异常时相位关闭且不伪造审计；影响集 **115 passed**。属 **P3 / static / orchestration+retrieval / engineering-only**；动态搜索与付费模型 `not_run`，预算授权 `not_applicable`。

### 2026-11-19 研究结构整合收口（以精确提交为准）

- #488（研究窗口检查点顺序）CI `44344609900` 成功，合并 `main@caefa350`；#489（执行守卫与实时预算）CI `44345569048` 成功，合并 `main@51da57f2`。两项均已确认无审阅线程，使用精确 PR HEAD 保护合并。
- #490（证据身份实时投影）与 #493（波次状态交接）在同一执行器上有交叠。基于 `main@51da57f2` 依次整合二者，修复 `gain_history` 恢复路径的一处冲突：必须先执行 `ResearchWindowDiagnostics.record_end`、再 `checkpoint()`、最后 `wave_handoff.settle(...)`，不能因替换旧 `settle_wave` 丢掉窗口检查点。合并演练 **96 passed**，Ruff/差异检查通过；该结果仅证明本地整合树，不替代远端精确提交 CI。
- #490 后续 CI `44347405572` 成功并按 HEAD 保护合入 `main@56ebfd6f`；#493 整合树 `cee81a55` 的 CI `44351248954` 成功、审阅线程为空，按 HEAD 保护合入 `main@083a0172`。真实搜索、模型、付费动态测试未运行。

### 2026-11-19 研究窗口检查点顺序显式化（独立候选）

- 基线 `main@739d74f7`，分支 `codex/research-context-next-20261119`。将 `execute()` 内四个 `record_research_window` 闭包调用展开为显式的 `ResearchWindowDiagnostics.record_end(context, hard_seconds=state.budget.hard_timeout_seconds, elapsed=elapsed, exhausted=...)`，随后按原位置调用 `checkpoint()`。诊断仍由专属上下文写入，检查点仍由原执行器控制；观察时钟每次仍取样两次，预算耗尽分支原有的后续额外检查点仍保留。
- 不触及恢复游标、费用预留及结算、状态序列化、模型请求或发布权威；不进行真实搜索/付费调用。下一片聚焦执行器的其他隐式共享变量，优先做具备对应回归用例的窄范围切分；本候选测试与提交状态以实际执行记录为准。
### 未接线的配置缓存与性能日志工具退役（2026-11-19，独立减负片）

- 旧 `src/config.py` 的 `get_config/validate/reload_config` 及模块级缓存没有
  现行调用方；生产 `src/llm_client.py` 已直接从 provider 环境配置读取并以
  凭据、端点和重试配置签名自动刷新缓存。旧 `reset_client()` 唯一调用方
  是 `src/config.py`，其专项测试只检查源码字符串是否存在。
- 旧 `src/perf.py` 的 `PerfTracker/PerfMetrics/write_perf_log` 同样没有
  生产、脚本、CI 或测试调用方；现行性能观测由研究运行器及独立诊断
  模块承担。本片成组移除两个孤立模块、旧重置函数和源码存在性测试，
  用现行同步/异步 Provider 客户端行为测试直接验证凭据变化后的缓存更新。
  Ruff 全库及 `git diff --check` 通过，配置/Provider/会话/打包影响集
  **127 passed**。不更改生产 Provider 调用、真实预算或研究检查点语义，
  且不发起真实模型 API；L3 未运行。
### 未接线的旧 Discovery 适配器退役（2026-11-19，独立减负片）

- `src/web/research/discovery.py` 持有一套历史 `DiscoveryRequest/Hit/Batch`、
  `DiscoveryProvider` 和未注册的 `LegacyDiscoveryAdapter`；全仓生产、测试、
  CLI、路由及注册机制都没有导入它或其符号。正式检索已经使用
  `src/web/research/retrieval_backends.py` 的独立 `DiscoveryRequest` 契约。
- 整个旧模块删除，不增加同名重导出、兼容 shim 或只验证删除结果的测试；
  现行检索、浏览器、查询预算、状态恢复和证据发布契约均不变。
  本片为 P3 离线工程减负：Ruff 全库通过，检索后端/主动研究适配器/
  诊断观测/主动研究运行器影响集 **129 passed**，`git diff --check` 通过。
  不声称提高检索质量，也不发起付费 API 调用；L3 未运行。

### 2026-11-19 模型尝试实时预算状态绑定（独立候选）

- #493 的精确 HEAD `cee81a55`、CI `44351248954` 已成功并合入 `main@083a0172`。#494 搜索执行上下文以相同文件树重新挂到此主线，精确 HEAD `ee05454e` 正在等待新 CI `44357775209`；上一 HEAD 的绿色 CI 不替代本次重挂后的验证。
- `ActiveModelAttemptContext` 现在显式接收 `current_state()` 和 `ensure_budget(state)`，而非隐藏了当前状态读取的无参预算回调。模型网关触发开始回调时，顺序仍为：检查当前操作有效性 → 读取最新 `ResearchState` 并按原硬预算规则验证 → 写入 inflight 模型尝试 → durable checkpoint → 真正发送。模型结束仍只更新内存审计，等语义结果的原检查点一起入库。
- 共享既有模型尝试造景 `_callbacks`，增加检查点/恢复重新绑定后的预算状态身份负控；不改变尝试次数、成本预留/结算、恢复游标、模型网关路由或任何持久化格式。L1 影响集 **108 passed**，Ruff、差异检查通过；mypy **115/125，无新增**。**P3 / static / orchestration+model / engineering-only**；动态搜索、模型和付费调用 `not_run`，预算授权 `not_applicable`。独立 PR 和精确提交 CI 以远端状态为准。

### F2 历史双读取器配对实验退役（独立片）

- `tools/run_f2_paired.py` 对固定六类本地页面重复运行旧 default/Crawl4AI
  采样，是 §143-B 阶段的手工表征实验；无生产、前端、CI/阶段门或其它当前
  资格工具调用。连同只验证其报告逻辑的 `tests/test_f2_paired_harness.py`
  一并退役。**保留**供当前 Crawl4AI 集成测试使用的
  `tools/f2_paired_fixture_server.py`；`tests/test_reader_task_request.py`
  的可选真实环境操作员测试直接指向共享夹具，并将以前从实验脚本导入且
  未撤销的 SSRF 放宽补丁改为 pytest `monkeypatch` 生命周期内的局部放宽。
  生产读取链、安全策略、升级后端、请求契约和历史结果档案不变；不进行外部读取。

### Search-to-Answer-1 历史检索层基线退役（独立减负片）

- 旧 `tools/run_search_to_answer_baseline.py` 只在 2026-10-28 的冻结题库上测量
  搜索和前两个结果的技术读取，不测最终回答、证据判断或多轮研究。实际使用者
  仅是专属 `tests/test_search_to_answer_baseline.py`；生产、前端、其它工具与 CI
  无调用，并且存在独立的当前搜索阶段门覆盖。成组移除该工具、专项测试、仅供
  它们使用的 `tests/fixtures/search_to_answer/baseline_v1.json`，同时从
  `tests/stage_gates.json` 的 `search_flow` 注册中摘除。旧评测报告保留为历史
  档案并注明不可从现行 HEAD 运行；正式 `GeneralWebGateway`、研究路由、
  搜索回退/读取/恢复/预算和当前搜索测试一律不动。无联网或付费测试调用。
### 2026-11-19 波次状态快照回写上下文（独立候选）

- 基线 `main@739d74f7`，分支 `codex/research-wave-state-handoff-20261119`。新增 `ActiveWaveSettlementHandoff`，明确从运行器捕获 `state/cursor/context` 快照、结算后（含异常）将快照写回实时状态，以及检查点执行失败时将内存中部分更新重新交还给结算快照。移除原 `settle_wave` 内部函数，将两个结算入口交给上下文；运行器仅保留一处显式 `bind_wave_snapshot` 写入接口。
- 原 `settle_completed_wave` 函数仍直接调用 `checkpoint()`，因此指标 `checkpoint_timing.caller` 保持现有标签；检查点、预算结算、恢复、波次决策和发布顺序不变。新增异常路径与原调用方标签负控，两条异常测试共享同一运行快照构造，避免重复造景；不调用外部检索或付费模型。#488–#490 各自为独立待审 PR，不混入本候选。

### 旧 HTTP 研究入口退役（待精确提交验收）

- `codex/retire-web-lookup-compat-20261118`：仓内唯一实际使用旧
  `POST /web-lookup-runs` 的真实验收脚本 `tools/studyctl_live.py`
  已迁至正式 `POST /research-runs` 创建、再用 `POST /research-runs/{id}/search`
  执行。完整退役四条 `/web-lookup-runs` 兼容路由、其无用转发函数、
  `NewsLookupRequest` 模型及旧入口专项测试；正式研究恢复测试补足
  `/research-runs` 读取/列表覆盖。`docs/TECH_STACK.md` 的现行调用说明同步迁移。
  **保留**供评测及业务继续调用的 `WebLookupService.lookup()`，研究持久化、
  恢复和预算逻辑不变。本项尚未进行真实服务/付费检索验收；合并状态以对应 PR 为准。

### 2026-11-19 研究检查点证据身份投影（独立候选）

- 分支 `codex/research-checkpoint-live-evidence-20261119`，基线 `main@739d74f7`。`ActiveRuntimeCheckpointContext.prepare()` 使用自身已有的 `results` 和 `run_id`，从当前结果缓冲区直接计算证据 ID；移除只服务该检查点的 `known_evidence_ids` 外部回调传参。波次结算上下文也直接持有结果缓冲区和运行 ID，以现有结算位置生成最新证据 ID。两处回调改为显式依赖后，证据身份仍由单一结果缓冲区投影。
- 新增专属检查点测试、波次结算测试，覆盖两次准备之间结果变化、预算时间重新取样，以及结算上下文创建后新增证据的读取。阶段、预算、游标、Claim Engine 状态与诊断指标的原检查点顺序不变；不修改恢复模式、波次停机决策、持久数据格式和费用语义。前一阶段的 `#488` / `#489` 尚属独立 PR，不并入本片；CI/合并情况以精确提交为准。

### 当前研究结构收口（精确合并）

- **2026-11-18 新收口**：故障游标显式更新 [#454](https://github.com/2002yy/study-agent/pull/454) 的 HEAD `691000e7`、精确 CI `44296684690` 成功，审阅线程为空，已用预期 HEAD 保护合并 `main@4bb5a6bd`。原 17 处故障写入不再经由捕获当前游标的内层闭包；失败标识、去重、恢复与检查点位置不变。
- **预算片已合并**：[#457](https://github.com/2002yy/study-agent/pull/457) HEAD `42850d71`，精确 CI `44301137902` 成功，审阅线程为空，按预期 HEAD 合并 `main@7aa32510`。`execute()` 不再通过捕获 `state/cursor` 的 `update_budget` 闭包更新四处预算；三个读取路径和预算耗尽分支仍各自原位取样、检查点，`reserve_call`、恢复和费用结算不变。整合影响集 **137 passed**、阶段门 **458 passed/4 skipped**、mypy **115/125**。
- **测试造景去重**：[#458](https://github.com/2002yy/study-agent/pull/458) HEAD `bc071bf7`，独立删除 `_cutover_service` 的重复构造，净减 **37 行**，原完整主动研究运行器 **84 passed**；精确 PR CI `44302192557` 最近观察仍在运行，不提前当作已合并。
- **下一独立候选**：`codex/research-window-explicit-state-20261118`（原远端提交 `78e61a80`）；四个 `record_research_window` 调用显式传入当前 `state/context`，保留原诊断→检查点、两次耗时取样及预算/发布权威。已无冲突整合 `main@7aa32510`，本地影响集 **93 passed**、Ruff/diff-check、mypy **115/125** 通过；远端精确 PR CI 尚未执行。
- 本轮核验主线：`main@f7531d19f7716198d97b6c78ea5dcbca7f229e0b`（tree `3e428c04cde38b92d7faafc6d9bde063de7d3f7c`）；这是交接时刻快照，下一窗口仍须重新读取最新主线。
- 研究预算时钟 [#405](https://github.com/2002yy/study-agent/pull/405)：HEAD `8ba1b995`、精确 CI `44161777666` 成功，合并 `3ea013b6`。
- 当前 steering/波次结算 [#409](https://github.com/2002yy/study-agent/pull/409)：HEAD `ff6375a0`、精确 CI `44161971315` 成功，合并 `486bcf78`。
- 当前研究窗口/计时观测 [#420](https://github.com/2002yy/study-agent/pull/420)：HEAD `2d71a79d`、精确 CI `44162132016` 成功，合并 `7cbe6a94`。
- 共享证据结果缓冲区 [#422](https://github.com/2002yy/study-agent/pull/422)：HEAD `878e37d7`、精确 CI `44162348067` 成功，合并 `f7531d19`。
- 四片已依次对齐父分支、核对无冲突的主线合并树，并按预期 HEAD 保护成功合入。**合并后的最新 main CI 仍待独立确认**，不能把 PR 头提交的绿色 CI 冒充主线绿色。动态浏览器、真实模型及付费调用未运行。

### 2026-11-19 研究执行守卫上下文（独立候选）

- 以 `main@739d74f7` 为基线，分支 `codex/research-execution-guard-20261119`。新增 `ActiveResearchExecutionGuard`：取消检查固定使用当前 `run_id/operation_id` 查询仓库，硬预算检查显式接收当前 `ResearchState`，避免持有已被检查点/恢复替换的旧预算。执行器去掉两个捕获外围变量的 `ensure_active`、`ensure_budget` 内部函数；内部模型尝试仍以回调使用最新 `state`，其余五处预算准入显式传 `state`。
- 守卫不改变恢复游标、预算入账、计时样本、模型开始检查点或发布操作；保留既有异常类别及原导出。专项测试覆盖取消实时检查和恢复后预算上限变化，完整回归结果以本候选精确提交为准。#488 另属研究窗口诊断与检查点顺序片，不与本片混合。

### 历史减负候选快照（部分已合入，以下不是当前待办）

#### 历史召回/候选供应商资格工具整链退役（2026-11-19，独立片）

- 旧 §44A/§44C 研究阶段的“已知目标召回审计 → Brave API 资格评估 / URL 提案
  候选替代方案资格评估”未进入生产执行链；三套脚本只被彼此依赖及专属测试
  引用。现行代码、阶段门、CI、活跃文档均无调用方，旧决策背景保存在
  `docs/archive/PROJECT_STATUS_PRE_177_FINAL_REVIEW_2026-10-06.md`。
- 删除 `run_recall_target_audit.py`、`run_brave_qualification.py`、
  `run_url_proposal_qualification.py` 及三份同名专项测试。旧冻结参数不再作为
  产品门槛维护；不补适配层、别名或空测试。正式 `research_url_proposal`、
  Browse 搜索和通用质量门不变。离线影响集 **112 passed**，Ruff 与差异检查
  通过；未执行 Brave API、DeepSeek、真实浏览器或其它付费请求。

#### CL-1D-1 单步会话实验编排器退役（2026-11-19，独立片）

- `run_conversation_step` 只由单步专项和旧 follow-up 集成测试调用；
  正式 `DeepSeekConversationService.start` 直接组合 `run_conversation_loop`，
  并由 `ConversationLoopSession` 管理流。删除旧 `conversation_action_step.py`、
  177 行专项测试及 follow-up 中重复的模型→工具→再决策→答复用例；
  同步移除阶段门 **16 处**无效注册、`tools/ci_scope.py` 的旧命名范围及
  合同测试，更新历史设计文档。保留正式 bounded-loop 的观察、暂停/取消、
  费用准入、终态及恢复测试，**不保留**兼容空壳。
- `TurnLifecycle` 仍涉及未来生产宿主/费用结算边界，不因未接入而删除。
  原定向 **288 passed**、会话 L1 **482 passed**、Ruff、diff-check、
  mypy 基线 **115/125**；未调用模型或付费 API。

- **2026-11-18 RQ1-C 成对归因实验链退役（独立片）**：
  `codex/retire-rq1c-paired-attribution-20261118`。旧 `run_paired_attribution.py`
  只调度同阶段 `run_rq1c_calibration.py` 和
  `run_environment_fingerprint.py`，三套工具没有现行应用、CI、阶段门或
  其他工具调用；旧产物仅供诊断，**不是**正式资格证据。连同唯一专属
  `test_paired_attribution.py`（20 个历史测试）整链删除，净减 **1,941 行**。
  保留正式 `run_rq1c_bounded_qualification`、冻结 holdout 清单、阶段门、
  成本/预算及相关现行测试；不改变生产搜索、研究恢复或预算决策。

- **2026-11-19 RQ1-C 无调用方 guard 二次转发模块退役（独立片）**：
  `tools/run_rq1c_bounded_qualification_guard.py` 只把正式预算守卫及资格
  实现的符号重新导出，重复提供 `main()`，没有活跃代码、测试、CI、
  阶段门或操作文档调用。该兼容壳已删除，不增补空桩、别名或专项测试；
  正式 `run_rq1c_bounded_qualification.py`、预算类型、8 次调用上限、
  硬截止、前置守卫和真实付费 API 权限边界不变。原影响集 **54 passed**；
  本片未执行付费资格实验，精确提交的更新验收以对应 PR 为准。

- **2026-11-18 旧 B-Search 离线目录实验退役（独立片）**：
  OPML 导入工具、静态信源目录、Top-K 目录召回模块及其专项测试只连接
  `tools/run_research_tool_agent.py` 手动实验入口，无生产请求、现行 CI、
  阶段门或用户任务调用方。成组退役该工具链、目录配置和专属测试；
  将唯一被当前 `entry_selection` 使用的中英文分词逻辑移入正式相关性模块，
  以现行准入测试继续覆盖连续中文的二元分词。`research_tool_agent` 本体、
  `research_shadow_seam`、页面准入/证据门、恢复和计费逻辑均保留。
  本次只做离线静态减负，不发起模型、搜索或付费调用。

- **2026-11-18 旧 §44B 提供商归因实验退役（独立片）**：
  `run_provider_attribution.py` 的旧三提供商归因/地区化判定仅由本身的
  专项测试调用，无生产路由、当前 CI/阶段门或在用执行入口；成组移除
  工具及其测试。Brave 资格工具先解除从旧实验导入两个字符串检查函数的
  隐式依赖，直接在自身定义并由现行 Brave 测试覆盖深层路径/CJK 统计。
  不修改实际搜索路由、资格门槛和预算/恢复契约；不运行外部搜索。

- **2026-11-18 付费样本演示入口退役（独立片）**：
  `tools/run_sample_research.py` 的 `--execute` 分支实际上只打印指导文本，
  不发起 Chat/研究请求；仓内没有真实调用方、CI 配置或专属测试。删除这一
  已失去执行价值的示例工具及其独占的 `LLM_SAMPLE_PAID_RUN_CONFIRMED`
  约定。**保留**独立的 `tools/precheck_sample_budget.py`、
  `tests/test_spend_boundary_controls.py` 和生产预算账本/真实验收流程，
  因为它们仍承担有效的费用安全检查；历史文档的原始文件清单不追溯修改。

- **2026-11-18 虚假跨层测试清理（独立片）**：两项 Python 测试
  名为“前端刷新竞态”和“部分接口失败保留旧状态”，实际只重复请求
  `/health`，既未制造竞态也未触发接口失败。移除这些误导性的
  旧专项测试，改由 `frontend/src/api.test.ts` 直接验证旧响应晚到
  不覆盖新结果，以及 RAG 状态暂时失败时保留前次有效快照并显示错误。
  同时删除允许缺少 CORS 响应头仍通过的伪跨层检查；真正的开发环境
  默认允许来源与预检响应已有 `test_cors_policy.py`、`test_api.py` 覆盖。
  此外删除未经注入搜索桩、会意外调用真实检索服务的新闻安全模式专项测试
  （安全模式持久化已由 `test_news_service.py` 覆盖），以及仅断言后端返回
  搜索词、却声称验证前端按钮失效的旧测试；保留能实证正文传入摘要的链路检查。
  另删除手工创建却没有撤销补丁、可能污染后续用例的群聊会话标记专项检查：
  对应标记和群聊隔离已由 `test_wechat_service_news_flow.py`、`test_api.py` 分别覆盖。
  只调整测试与交接，不更改运行时；验证状态以对应 PR 为准。

- **2026-11-18 交互历史阶段一报告脚本退役（独立片）**：
  `tools/interactive_history_report.py` 是仅需手工指定 SQLite 库的阶段一
  压缩前后比较脚本，库内无其它调用方、CI 配置、专属测试或发布依赖。
  删除该一次性报告入口；保留正式聊天上下文使用的
  `src/interactive_history.py` 及 `tests/test_interactive_history.py`，
  继续检查用户原文保留、版本来源和历史压缩契约。

- **2026-11-18 M4-D 一次性补丁演示退役（独立片）**：确认
  `tools/interactive_patch_demo.py` 只作为历史手工演示入口使用，
  `frontend/e2e/acceptance/incrementalPatch.spec.ts` 只在设置
  `M4D_PATCH_DEMO_DIR` 时执行；生产代码、现行 CI 和正式 UI 均无调用。
  整组删除演示运行器及其专属浏览器用例，把原先误从演示工具导入的
  测试构造函数移入 `tests/test_interactive_patch.py`。
  **当时**保留 `src/interactive_patch.py`、恢复契约以及增量修改/能力继承的
  单元测试。后续证实补丁核心 `prepare_patch/PatchCandidate/TextEdit` 仅由
  两份测试调用，未接入正式 API、会话、前端、CLI 或阶段门；本独立片删除
  原型模块与整份专属测试，Three 能力测试改为直接覆盖正式
  `interactive_history` → `interactive_restore` 的版本恢复和冲突语义，
  并在历史原型文档中撤销过时演示命令。保留正式恢复、版本识别、Three
  沙箱加载及其测试；不补兼容空壳。原离线影响集 **82 passed**、Ruff、
  diff-check、mypy 基线 **115/125** 通过；未执行付费 API。

- **2026-11-18 M4-C3 历史实验闭环退役（独立片）**：
  11 月 4 日固定批次已有原始结果和费用回执，今天的产品/CI 不再调用当时的
  付费样本执行器与一次性数据调查工具。成组移除 M4-C3 的五个执行/预算/导出
  脚本、五个专项测试、两个配置、冻结提示清单和已过时的执行说明；
  同时退役旧 SQLite 大范围扫描/导出工具及其一次性浏览器重放用例。
  保留 `docs/M4C3_FIRST_RESULTS_2026-11-04.md` 历史评测事实、
  `frontend/e2e/fixtures/m4c3-first` 的原始失败样本及正式源码恢复测试，
  保留沙箱双视口语义/Three 按需加载用例。真实预算闸门、
  `src/interactive_history.py` 和生成/发布路径不变；无付费调用。

- **2026-11-18 M4-C 候选轨迹离线审计退役（独立片）**：
  `tools/audit_tool_agent_candidates.py` 仅消费旧运行记录生成供人工查看的
  `m4c-tool-agent-candidate-audit-v1` 报告；全库没有正式业务、CI、阶段门或
  其他工具调用它，只有 `tests/test_tool_agent_candidate_audit.py` 检查其输出。
  成组删除这个阶段性报告器和全部专属测试。保留生产运行时真正生成的
  `candidate_trace`、`candidate_audit` 观测字段和现行 Web Tool Agent 测试；
  旧集成收口文档中对应的历史文件列表不追溯篡改。

- **2026-11-18 旧记忆接口与专项测试退役（独立片）**：以
  `main@d879a4af79d99521129f361e07866cedc3fa0064` 为基线。
  前端现行记忆操作已由 `POST /memory-runs` → `POST /memory-runs/{id}/commit`
  承担，仓库内已确认旧 `POST /memory/preview`、`POST /memory/commit` 无生产调用方；
  移除两条兼容路由、旧响应模型、前端无调用封装及其专项测试。
  将剩余的预览格式、非法目标、重复替换、只读模式拒写负控集中到
  `tests/test_memory_run.py` 的正式运行流程，保留运行记录、哈希冻结、权限与恢复契约。
  静态验证与精确提交 CI/合并状态须以对应 PR 为准；无付费模型调用。

- **2026-11-18 RAG 索引旧接口退役（独立片）**：基线
  `main@95fdbe964990eab6329c7e36c244b416eea0afb3`，候选分支
  `codex/retire-rag-index-compat-20261118`。核实前端、工具和 CI 无
  `POST /rag/index` 调用，正式入口是 `POST /rag-runs/index`；删除旧
  同步响应转换适配，8 处测试调用统一改用正式接口。保留仍被前端使用的
  `/rag/upload`、`RagIndexResponse` 和 `/rag` 代理前缀。L1 **57 passed**、
  Ruff 和差异检查通过；无模型调用。精确 HEAD CI/审查及合并状态见对应 PR。

- **2026-11-19 无调用方的研究匹配/调度包装函数退役**：
  `facet_coverage._contains` 和 `scheduler._lead_is_schedulable` 都没有生产、
  工具、测试或阶段门引用，分别是旧的全词匹配和线索调度包装，直接删除，
  不增加空测试、适配或配置。现行 `_pattern/_term_positions`、
  `is_schedulable_lead` 与 `plan_read_wave` 不变。另有 `_prose_score` 疑似死代码，
  但扩展测试的 `test_goal_evidence.py::test_agent_records_evidence_per_goal_and_keeps_records_apart`
  在未改动的主线上已有失败，因此不在此片混删相关证据路径或失败测试。
  原匹配/调度/读取影响集 **84 passed**，Ruff、差异检查与 mypy 基线
  **115/125** 通过；无真实搜索或付费调用。

- 上轮历史减负收口：[#449](https://github.com/2002yy/study-agent/pull/449)
  精确 CI 成功，合并 `32ed94f5`；[#450](https://github.com/2002yy/study-agent/pull/450)
  精确 CI 成功，合并 `92243d58`；[#452](https://github.com/2002yy/study-agent/pull/452)
  精确 CI 成功，合并 `34c02510`。三片删除旧实验执行器及专项测试、合并重复
  的抽屉入口测试、退役 `POST /rag` 根路径别名及其测试；只作为离线工程减负，
  不代表动态检索质量改善。

- **2026-11-18 旧提供商路由实验退役片（独立于研究运行器重构）**：基线
  `main@ee0f7c284c4074d9334efc4f13ce955325a59b0a`，工作分支
  `codex/retire-orphan-tools-20261118`。移除无生产、CI、阶段门调用方的
  `tools/run_provider_routing_replay.py` 与专属 `tests/test_provider_routing_replay.py`，
  不再维护旧 E0–E3 历史重放策略；留存历史数据/报告及当时供 Browse 搜索探针使用的
  `qp1c_queries_v1.json`（探针后于 2026-11-19 退役）。局部检索影响集 **27 passed**；Ruff 通过，
  无模型/API 费用。此项仅为离线工程清理，不代表检索效果变化或动态验收。
  PR #449 已通过精确提交 CI 并合并；不影响独立研究运行器重构片。

- **2026-11-19 旧 Browse 四站点小样本探针退役（独立片）**：
  `tools/probe_browse_engines.py` 只对 QP1-C 的 A01/A05 两题手工循环
  Google、DuckDuckGo、Bing、Brave 打印 URL，没有生产、CI、测试、
  阶段门或其它工具调用方。删除孤立脚本及旧复测命令，但保留历史
  `BROWSE_ENGINE_PROBE_20261115.md` 观测和 `qp1c_queries_v1.json`
  题集来源；正式 Browse 路由、站点选择、SSRF、人机验证终止规则不动。
  离线 Browse/站点池/搜索策略/工具网关影响集 **60 passed**，无真实
  浏览器或付费 API。新精确提交 CI 以本片对应 PR 验收为准。

- #406：移除无前端调用方的新闻运行客户端兼容接口及对应历史测试，约净减 530 行。
- **2026-11-19 微信旧兼容门面退役（独立减负片）**：`src/wechat.py`
  是历史拆分后没有正式生产/路由/CLI 调用方的转发 facade，仓内仅有
  经门面导入的行为测试和 `test_wechat_decoupling.py` 源码存在性检查。
  成组删除门面及其专属架构测试；新闻正文、去重、群聊状态的有效测试
  直接导入现行 `wechat_state/generator/format` 和新闻模块，并在临时目录
  隔离群聊状态。同步修正打包必需文件清单，防止废弃模块误当依赖。
  正式聊天、微信及新闻的业务/费用契约不变；无真实模型或浏览器调用。
- #407：移除 17 份只供历史阶段使用的单次实验脚本及配套专项测试，净减约 4,495 行。
- **2026-11-18 匿名平台探测实验退役（独立片）**：原
  `qualify_anonymous_platforms.py` 只对四个固定公网 URL 发一次匿名 HTTP
  请求，结果始终标为 `qualified=false`，既未接入产品，也无法证明
  视频/站点读取能力。移除脚本、其两类专项模拟测试及阶段门中的旧条目；
  `discovery_platform_contracts_v1` 仍执行正式的来源搜索、来源评估和
  Web Tool Agent 测试。不改平台接入、真实浏览器读取或鉴权流程，
  不发公网请求。
- **2026-11-18 无调用的会话手动落盘链路退役（独立片）**：前端已用
  SQLite 会话列表/详情和正式归档流程，没有 `flushSession` 调用；同步移除
  `POST /sessions/{id}/flush`、后端 `SessionService.flush_session`、
  仅服务该入口的当前 Markdown 导出方法，以及无人引用的前端
  `loadSessions`/`loadRagStatus` 快捷封装。原先以手动落盘制造旧镜像的测试
  改为直接构造历史镜像，继续验证归档清理、失败恢复和清理失败保留归档，
  不删旧版文件导入器，也不改变 SQLite 会话和归档的产品契约。
- **2026-11-19 旧 session logger 镜像整体退役（独立片）**：
  正式聊天与恢复由 SQLite `ChatThread/ChatTurn`、`SessionService`、
  `LegacySessionImporter` 承担。`src/session_logger.py` 的 `log/flush/save`
  从未填充正式会话 `_state`，`src/session_store.py` 只服务这个旧镜像；
  微信群读取最近单聊和写入旧 `wechat_interactive` 标记没有真实上游。
  同步删除两模块、专属 flush 测试、只检查其源码结构的打包断言、
  过时微信状态桩及重复列表用例。历史 Markdown 导入/恢复测试改为
  直接构造旧快照，保留正式 SQLite、学习记忆和预算/恢复行为。
  原离线影响集 **128 passed**、扩展会话/微信 **170 passed**、
  学习记忆 **28 passed**；Ruff、差异检查及 mypy 基线 **115/125**
  通过。无真实模型或付费搜索。
- 本轮独立片：移除 `src.api` 的旧测试打桩重导出和生产 `_api()` 回绕桥接；实际调用改向模块所有者，测试与真实测试入口同步迁移，并让两项微信正文安全测试不再依赖真实域名解析。保留 `from src.api import app` 公共入口；不删除持久数据、恢复和费用约束。此条是本地待提交状态，不代表 CI 通过或已合并。

上述候选都基于同一主线快照开展，合并前须逐个核对最新主线、差异和文档重叠；另一个窗口的研究运行器职责拆分不得与这些减负片混写。

### 研究运行器职责拆分续片（2026-11-18）

- #466 检索库存读取诊断的最新上下文修复已合并 `bf9d39ca`；#470 Tier-2 提议诊断的最新上下文修复，精确 PR CI `44316133679` 成功，已合并 `209f50f7`。
- 基于最新 `main@32ab17cf`，候选选择器显式接收 `live_context`，在模型调用后的上下文回填上记录选择诊断和编排调用次数；保持原候选集兜底、恢复检查点与预算结算时序不变。受测候选 `9d43b667`：161 项影响测试通过，Ruff、mypy 既有基线通过；新 PR / CI 待收口，非真实模型验收。
- 下一独立片：梳理选择诊断记录构造与性能采样的所有者，继续缩短大运行器；先冻结重复调用时的输入变化统计、计时采样顺序与环形记录上限，再迁移纯投影。不得混入新闻/API 清理。

### 权威基线（按精确 SHA 核实）

- 历史基线：`main@265bd4eaa438dafce84bde31eb9535ac17fefc32`（#406 合并后，tree `52147fdb1b0b366dd5ed7bf4e0d713f33c37028a`）；#403 的已验收父树为 `37be116f`。最新研究结构主线见上方当前研究结构收口；**新会话须重新获取最新 main**。
- **研究发布**：#360 已将 `simple` 设为默认：检索、读取正文、生成、检查引用属于已读 URL，再无损发布；`strict` 显式保留旧逐段校验。简单模式**不提供逐条事实已核实**的保证。历史 q9 曾一次完整输出（50.31 秒，3,173 字符），**不能据此认定跨题质量达标**。
- **检索**：#365 双通道与 #366 基于已读正文的缺口查询已入主线；双通道默认关闭。#368 中文社区浏览器在 `main@5f146a67` 合并，修复米游社游戏分区路由。#369 免费覆盖探针见下文；**搜索发现的 URL 不等于正文已读、可以引用的证据**。
- **DeepSeek 官方 Search / Fetch**：#370 于 `main@6a1c880e` 合并，仅预接入。两套 `ENABLED=false`、`MAX_REQUESTS=0` 独立默认关断；敏感 URL 和危险跳转不得发送至外部 Fetch。**未授权真实计费调用，未启用生产路由**。
- **交互 UI**：M4-A/B/C 与后续修复、Three、媒介选择能力已有静态交付；真实模型挑选媒介和自动修复成功率尚无动态验收结论。

### 本轮交付与验证（Static Loop；不冒充产品动态验收）

| PR | 已实施工作 | 精确证据 |
| --- | --- | --- |
| [#368](https://github.com/2002yy/study-agent/pull/368) | 中文站点浏览器及米游社分区修复 | 合并 `5f146a67`；PR 审阅/精确 CI 已收口 |
| [#369](https://github.com/2002yy/study-agent/pull/369) | 免费社区覆盖探针：fast / 浏览器增量 URL、实际读取、失败诊断，禁止继承错误搜索策略，付费开关开启时拒绝执行 | HEAD `9456271e`；合并 `faf1a94b`；CI `44034118706` 成功；审阅 P2 已修复 |
| [#370](https://github.com/2002yy/study-agent/pull/370) | 官方 Search/Fetch 双重默认关闭、安全校验、离线负控 | 合并 `6a1c880e`；精确 PR CI `44031322548` 成功 |
| [#371](https://github.com/2002yy/study-agent/pull/371) | 有日期、可复核的执行审计与工作树整理 | 合并 `e06b882e` |
| [#373](https://github.com/2002yy/study-agent/pull/373) | 研究运行器纯证据投影函数抽离：`active_research_runtime.py` 7,453→7,167 行 | 合并 `92af5937`；CI `44030559637` 成功；AST 函数体一致 |
| [#374](https://github.com/2002yy/study-agent/pull/374) | 网页读取证据与预算纯函数抽离：`web_lookup_service.py` 3,013→2,739 行 | 合并 `e5d4f037`；CI `44032955744` 成功；AST 一致 |
| [#375](https://github.com/2002yy/study-agent/pull/375) | 聊天研究发布策略抽离：`chat_service.py` 2,589→2,361 行 | 合并 `8fe57bc5`；CI `44032951521` 成功；AST 一致 |
| [#376](https://github.com/2002yy/study-agent/pull/376) | 读取调度纯测试独立成模块：`test_active_research_runtime.py` 5,934→5,458 行 | 合并 `fb527250`；CI `44033439005` 成功；67/67 顶层测试 AST 保留；补齐三项阶段门禁登记 |
| [#382](https://github.com/2002yy/study-agent/pull/382)–[#384](https://github.com/2002yy/study-agent/pull/384) | steering 状态投影、模型尝试预算判定归位；读取计划测试净删重 126 行 | 已合并；精确 HEAD CI `44074227494` / `44074756787` / `44075417217` 成功 |
| [#385](https://github.com/2002yy/study-agent/pull/385) | 冻结模型 inflight、阶段检查点及预算单调契约，保留崩溃恢复与费用结算负控 | 已合并 `383e6440`；精确 HEAD CI `44077179183` 成功 |
| [#390](https://github.com/2002yy/study-agent/pull/390) | 读取调度显式传入候选身份，后端尝试历史统一计算 | 已合并 `96ac38b6`；精确 HEAD CI `44086183784` 成功 |
| [#391](https://github.com/2002yy/study-agent/pull/391) | 阶段计时上下文拥有可变计时状态，替代执行闭包 | 已合并 `6e7e6c53`；HEAD `9f1a8c7f`，精确 CI `44089619882` 成功 |
| [#393](https://github.com/2002yy/study-agent/pull/393) | 读取诊断/后端健康记录迁出大运行器，保留旧导入入口 | 已合并 `5bcfc8a0`；HEAD `271010c3`，精确 CI `44100349280` 五项全绿 |
| [#392](https://github.com/2002yy/study-agent/pull/392) | 模型政策审计纯投影独立化，保留请求前持久化和预算结算原顺序 | 已合并 `cfe9ca16`；HEAD `c45b8287`，精确 CI `44106896286` 五项全绿 |
| [#394](https://github.com/2002yy/study-agent/pull/394) | 读取尝试游标/诊断上下文显式化、测试恢复游标重复解码去重 32 处 | 已合并 `b6c98f9d`；HEAD `7f7dbf7a`，精确 CI `44108108094` 五项全绿；#392 合并后同树验收 |
| [#395](https://github.com/2002yy/study-agent/pull/395) | 将读取预调度闭包迁为显式传入当前候选、游标历史、上下文、断路器和研究时钟的函数 | HEAD `f4c63a26`；精确 CI `44125608541` 成功，合并 `bd7fd5dc`；合并后 tree `9d96107b` 与验收树一致 |
| [#396](https://github.com/2002yy/study-agent/pull/396) | 研究窗口诊断独立化；保留两次时间采样和记录后检查点顺序，不改预算准入 | HEAD `bcd8d697`；精确 CI `44126675280` 成功，合并 `30c27cf2`；合并后 tree `02c395cf` 与验收树一致 |
| [#397](https://github.com/2002yy/study-agent/pull/397) | 读取链测试共用服务/运行记录/来源投影，净减 45 行，生产代码不变 | HEAD `8e781a64`；精确 CI `44127618845` 成功，合并 `4f46684d`；合并后 tree `7044d37f` 与验收树一致 |
| [#398](https://github.com/2002yy/study-agent/pull/398) | 模型准入政策以当前 `context` 显式入参；不变回调封装为 `RuntimeModelPolicyContext` | HEAD `25ae27cd`；精确 CI `44135910377` 成功，合并 `b4ae4291`；合并后 tree `69154167` 与验收树一致 |
| [#399](https://github.com/2002yy/study-agent/pull/399) | 故障记录显式读取当前游标/上下文，保持尝试 ID 与去重 | HEAD `b676659b`；精确 CI `44136804289` 成功，合并 `f2666db8`；合并后 tree `618e987f` 与验收树一致 |
| [#400](https://github.com/2002yy/study-agent/pull/400) | 模型尝试回调归入 `ActiveModelAttemptContext`，锁定开始检查点、费用前时序及完成后内存审计 | HEAD `b505fb3f`；精确 CI `44138134273` 成功，合并 `9abe320d`；合并后 tree `8e9fef3e` 与验收树一致 |
| [#401](https://github.com/2002yy/study-agent/pull/401) | 专家读取的路由、预算窗口与来源诊断归入 `ActiveReadSiteContext`；保持默认读取链为兜底 | HEAD `4d01a312`；精确 CI `44140163266` 成功，合并 `8f5a2ff0`；合并后 tree `50211070` 与验收树一致 |
| [#402](https://github.com/2002yy/study-agent/pull/402) | 三类有证据终态统一由 `ActiveResearchPublisher` 接收当前上下文和停止结果；检查点仍在执行器 | HEAD `a7d67a07`；精确 CI `44141917095` 成功，合并 `ef99b162`；合并后 tree `66a33f5f` 与验收树一致 |
| [#403](https://github.com/2002yy/study-agent/pull/403) | 波次结束停止信号纯投影：当前缺口、饱和阈值、恢复后迟到 steering，`ResearchStopGate` 仍独占裁决 | HEAD `3271c810`；133 passed、精确 CI `44145248671` 成功；合并 `f9332655`、tree `37be116f` 与验收树一致 |
| [#404](https://github.com/2002yy/study-agent/pull/404) | 共用切换/普通研究测试工厂，保留升级网关对象身份 | HEAD `ab298385`；84 passed；精确 CI `44146778208` 成功；待独立审阅及合并 |
| [#405](https://github.com/2002yy/study-agent/pull/405) | 独立研究预算时钟、Deep 恢复基线和窗口超时 | 原 HEAD `dec1dd3d`；精确 CI `44149454756` 成功；本次仅处理与 #406 文档冲突，合并修复后的新 HEAD 须重新验收 |
| [#406](https://github.com/2002yy/study-agent/pull/406) | 移除旧新闻前端包装与历史冗余测试 | 精确 CI `44150453199` 成功；已合入 `main@265bd4ea`，保留现存服务端持久化/API |

**当前结构片**：[#387](https://github.com/2002yy/study-agent/pull/387) 的 40 处测试初始化删重已合并 `main@315b07a1`，原 63 个测试函数与 474 条断言保持、84 passed，精确 PR CI `44079893336` 成功；[#386](https://github.com/2002yy/study-agent/pull/386) 将有序检查点封装为执行上下文，精确 HEAD CI `44080509512` 成功、合并 `df6f2a7e`；[#388](https://github.com/2002yy/study-agent/pull/388) 将结果缓冲区显式化，精确 HEAD CI `44080750573` 成功、合并 `0e72901d`。这些是各 PR 头提交的验证，不冒充合并主线后的独立 CI。重复的 #389 已关闭，未入主线。

这四项大文件工作是**职责拆分、单文件认知负担下降**，绝非宣称全库代码行数下降：新模块、测试和导入使合计行数略有增加。没有删除故障、恢复、权限、计费等关键回归。

### 测试与执行成本的量化基线

- 历史结构审计约 **588** 个 `tests/test_*.py` 文件、**5,917** 个测试函数定义；到 `main@f9332655` 增至 **601** 个文件，#406 合并后减至 **597**。预算时钟片（#406 合并前）同口径实测 `src/**/*.py` **149,719 行**、`tests/**/*.py` **152,805 行**，测试/主体约 **1.02:1**；这一数字是历史快照，不冒充当前主线。全仓结构相同的测试函数只发现 9 组、10 个额外定义，**不能仅凭测试行数与主体接近就机械批量删除**。
- #373 的一次完整后端 CI：**7,347 passed、21 skipped、1,376.13 秒**（约 22 分 56 秒）；单个最慢测试约 5.13 秒。主要负担是对小变更触发整套回归，不是个别慢用例。
- `tools/ci_scope.py` 目前只对 `developer-cli`、`conversation-decision`、`standard` 类别登记精准影响集；通用 `learning-backend`、新增纯研究模块仍常走全量。后续应按**明确文件→直接引用测试→下层契约测试**新增影响集，保留 L3 主线/发布门和未知路径保守兜底；不能靠跳过覆盖换速度。
- **2026-11-18 第一批删重（#406 已合入）**：删除无人调用的 6 个 NewsRun 前端包装、配套类型、旧工作台形状测试以及 v0.3 过时冒烟测试；净减 **530 行**、4 个后端和 1 个前端测试文件。保留新闻持久化/API 和当前研究路径；精确 HEAD `cfa14169` 的 CI `44150453199` 五项全绿，已合入 `main@265bd4ea`。
- 该片的本地前端依赖曾因离线缓存缺失而未安装，故本机 Vitest 不构成验证；完整远端 CI 已补齐，且没有发起付费模型或真实浏览器调用。
- **2026-11-18 同一不变量的跨层重复测试收口（独立片）**：
  三个模块原样重复查询 SQLite `sqlite_master`，只断言没有 `deep_` 表；
  保留 `tests/test_deep_trigger.py` 中的数据库负控，删除另两处没有额外造景的
  同义断言。默认读取器链的静态元组断言散落在三处，保留
  `tests/test_crawl4ai_specialist_integration.py` 更完整的专用读取器隔离检查，
  删除另外两处同义断言及不再使用的导入。仅减测试重复，没有降低真实功能门、
  调用预算或恢复保护；正式行为未变。
- **2026-11-19 旧课后 Markdown 更新警告器退役**：
  `src/update_validator.py::validate_updates` 只由
  `tests/test_after_session.py` 的四条专属断言调用；正式课后生成、学习闭环、
  API、工具与阶段门并未接线。函数仅返回提醒，并不拒绝内容，旧测试名
  所称的情绪/隐私/版本“拒绝”从未是产品保证。删除它及四个无效专项测试，
  不迁移启发式提示至正式链，也不削弱现有外部数据保护。保留正在调用的
  `after_session` 解析生成、`safe_writer`、学习闭环及预算安全测试。
  原影响集 **46 passed**，Ruff、差异检查、mypy **115/125**；无模型费用。
- **另一独立清理片（待 PR）**：退役不再被生产、CI、现有工具或当前评测调用的旧网页重试特征统计、学习状态临时方案对照、S1/S2 阶段观察，以及重试统计专属测试。共 4 文件，原始约 639 行；不触碰实际网页读取器、持久学习模型、计费安全和故障恢复用例。旧实验结论仍可从 Git 历史或归档文档查看。
- **后继学习状态实验链（依赖上一片先合并）**：完整移除早期 §164/165/168 的下一步、误解、持续对话、阶段 D 取样、影子采集和 S1/S2 真实观察六份单次脚本；其中唯一跨脚本调用源 `run_phase2_rollout_observation` 已在上一片删除。生产 `learner_state_durable_adapter`、`learner_state_shadow_seam`、持久学习状态及相关测试不动，仅更新说明中对已退役脚本的提及。此片独立验证，不能将未完成的 CI 视为通过。

### 2026-11-18 旧 Wigolo 浏览器对比运行器退役（独立片）

- 早期 A3 的 `tools/run_browser_bakeoff.py` 只有其专属
  `tests/test_browser_bakeoff_harness.py` 调用，不参与现行检索、Crawl4AI
  资格评测或 CI 执行。退役整组脚本和历史联调测试，并移除阶段门中这份
  旧专项测试的两处重复引用；旧测试的浏览器是否升级/壁垒分类行为现由
  `test_chain_executor.py`、`test_progressive_routing.py` 与当时的
  `test_wigolo_browser_executor.py` 验证（后者已在后续独立片退役，
  现行共享安全不变量迁至 `test_browser_honesty.py`）。当时 Crawl4AI cohort v2
  尚调用 `browser_bakeoff.py` 的结果构造/校验与旧 manifest，故暂留旧合同与
  共享 fixture 服务；**后续 §118/§120 整链退役时**，唯一消费者一并移除，
  旧合同、专属测试、manifest 和阶段门注册也同步退役。共用 fixture 服务
  因仍被现行超时/读取测试调用而保留。不修改真实浏览器读取逻辑，
  不执行外部浏览器或付费模型调用。

- **2026-11-19 未注册 Wigolo 后端整体退役（独立片）**：现行
  `ACTIVE_READER_CHAIN`、API、研究执行器、正式 Crawl4AI 专家读取及工具
  均未实例化 `WigoloBrowserBackendExecutor`。删除明确标注 production-inert 的
  `wigolo_browser_executor.py` 及其独占 451 行测试；阶段门两处引用替换为
  正式浏览器链使用的 `test_browser_honesty.py`，冻结壁垒分类、受限前缀
  与故障真实性负控。保留 Crawl4AI/默认读取链、预算恢复、安全开关，
  及仍被结果契约使用的 bakeoff manifest/能力词表。原定向
  **188 passed / 1 skipped**、L2 **414 passed / 4 skipped**，Ruff、
  diff-check、mypy **115/125**；无真实浏览器或付费模型调用。
- 同轮审计发现 `conversation_action_step` 仅被旧集成测试使用，但其仍挂
  大量会话阶段门，须独立重建 bounded-loop 覆盖后退役；
  `ResearchMemoryService` 承担已建持久化契约、`backup_manager` 涉及 `.bak`
  恢复，均不因“无直接导入”而机械删除。

### 2026-11-18 历史诊断脚本退役（独立清理片）

- 代码提交 `ef29cab8`（分支 `codex/retire-oneoff-probes-20261118`，基于 `main@f9332655`）：**17 个文件、4,501 行移除**，含 F2 早期定点延迟/账本脚本，以及 RQ1C 历史实验的答复生成、时间线、推理政策、冻结 A/B、断言形状、选择器格式探针。删除脚本时同步删除其 **6 个专属测试文件、36 个测试函数**。
- 逐个检索生产实现、CI、门禁、测试、前端和配置，没有留下直接引用；共享的 `run_f2_paired`、当前研究/发布功能、真实任务测量工具及历史结果文件保留。代码在 Git 历史中可恢复。
- 验证：`pytest tests --collect-only` **7,420 tests collected**，未出现缺失模块导入；保留的 F2/发布测试 **64 passed**，Ruff 和 `git diff --check` 通过。**不宣称全量 L3、产品效果或动态实验通过**；PR 精确 CI 与审查尚待完成。
- **后继独立清理片（依赖上批先合并）**：删除 5 份旧的选择器/Agent 循环实验工具及 5 份专属测试；这些工具只通过彼此和配套测试互相引用，未接入生产运行器、当前测试门禁、前端、配置或持续集成。唯一额外依赖 `run_selector_schema_probe.py` 已在上批删除，因此两片须按依赖顺序合并。只保留 Git 历史和旧报告，不再维护无产品调用方的第二套模型选择器原型。

### 2026-11-18 §37B 候选来源报告器退役（独立片）

- `tools/run_selection_provenance.py` 是 §37B 评测阶段的离线报告格式转换器，
  用当时双人标注的 `likely_target` 统计首个候选丢失位置；除专属的
  `tests/test_selection_provenance_tool.py` 外，没有生产、CI、阶段门或工具调用方。
  一并删除报告器及四项报告格式测试，避免为旧实验的 JSON 输出继续维护接口。
  **不删除** `src/web/research/selection_trace.py`，也不改变运行时的
  `selection_trace` 字段或候选筛选、调度与读取的正式测试。

### 2026-11-18 无调用方网站池测速器退役（独立片）

- `tools/bench_site_pool.py` 只含固定 12 题和浏览器站点池的单次测速输出；
  全库无生产、CI、阶段门、其它工具或测试调用，也无专项配置和测试。
  移除该无维护价值的外部浏览器实验入口，不触及在用的
  `src/web/site_pool.py`、真实检索路由及其回归测试。未实际运行外部浏览器。

### 安全边界与工作树

- **Quality-0 预演运行器退役候选**：旧 `quality_0_arms` 是仅由自身测试调用的未接线四臂运行器；其计划预演脚本、两组专属测试、预演配置和旧操作文档一并移除。仍保留 20 题离线质量评测、评分脚本、文件资产，以及实际被模型支出门禁引用的 `send_budget`、`llm_spend_guard` 和负控。此变更须通过独立 PR 的精确 CI，不代表当前主线已清理。

- 本轮**0 次真实付费模型、DeepSeek Search/Fetch 调用**；各 CI 使用离线测试，不代表已做真实站点浏览器或动态答案质量对照。
- #371 曾确认 12 个工作树中的七个历史阶段目录干净并移除，Git 分支/提交保留；**用户原工作树五处未提交修改保持原样**（`.env.example`、`src/web/browse_search.py`、`tests/test_browse_search.py` 及两份新增文件）。收尾用精确路径复核并仅移除干净临时工作树。
- 专项安全扫描技能配置不可读，本批以精确差异人工审查、CI 与负控替代，**不宣称专项安全扫描通过**。历史 #367 是被 #371 取代后关闭的重复文档 PR。

### 当前仍开放的工作（按优先级）

| 优先级/归属 | 问题 | 最小下一步 |
| --- | --- | --- |
| P0 / 费用与安全 | DeepSeek Search/Fetch 没有持久跨进程共享费用账本；不得启用 | 新用户授权额度后先接费用准入和多 worker 负控，再考虑带费验收 |
| P1 / 研究最终答案 | 部分真实用户题虽搜索成功，最终答案完整性与引用有效性仍缺跨题验证 | 用已存真实失败轨迹做零费回放；新的真实模型对照单独获预算 |
| P1 / 普通聊天/多模态 | 多轮、图片真正理解、取消/恢复、用户可见终态仍需实际供应商/设备验收 | 选一条真实任务做完整动态端到端，不把模拟测试当用户成功 |
| P2 / 中文社区与延迟 | 实际增量、正文可读率及 P50/P95 未在当前部署环境回放 | 用 #369 工具跑零模型调用探针，区分命中与可用证据；保留社区浏览器能力 |
| P2 / 维护成本 | 大文件第一轮职责拆分完成，但仍有大文件、测试夹具重复与全量 CI 约 23 分钟 | 小范围分析影响集、夹具公共化的实益，逐片拆分，保持全量 L3 门 |
| 待立项 / 部署并发 | 操作心跳续租、设置丢更新、超时线程回收、多用户隔离尚不完整 | 单独设计并发/数据完整性门，不能在清理 PR 中顺手重写 |

### 唯一下一执行片

**已合并的读取边界**：[#434](https://github.com/2002yy/study-agent/pull/434) 将读取准入、实时后端历史和断路器健康归入 `ActiveReadDispatchContext`，精确 HEAD `5ff7b4b4`、CI `44263823378` 成功，合并 `008dc2c1`。[#437](https://github.com/2002yy/study-agent/pull/437) 将专家/默认链派发归入 `ActiveReadExecutionContext`，精确 HEAD `884dc459`、CI `44267030564` 成功，审查没有阻断，合并 `b3350fd2`。两片均保持 `execute()` 对恢复状态、游标、检查点和实际费用的唯一写入权威；无真实付费调用。

**已合并读取投影片**：[#443](https://github.com/2002yy/study-agent/pull/443)，HEAD `4f522e26`，精确 CI `44276778323` 成功、机器人审查无发现，预期 HEAD 保护合并至 `main@b613c96c`。该片把读链单来源投影迁到 `project_read_chain`，纯路由诊断归入读取观测模块；合并前同主线的读取栈回归 **467 passed / 4 skipped**，mypy 基线 **115/125** 通过。真实尝试、失败、读额度、恢复、费用、来源 upsert 与检查点顺序均不动。

**已合并读取历史片**：[#447](https://github.com/2002yy/study-agent/pull/447) HEAD `65deabb9`，精确 CI `44284842449` 成功、机器人审查无发现，预期 HEAD 保护合并至 `main@7da66efb`。将三处 `reads` 快照合并为 `_record_read_history(context, current_outcomes)`，仅真实链结束时额外写 `candidate_resolution`；主线隔离整合影响集 **101 passed**（78.73 秒），此前独立候选 mypy 基线 **115/125**。实时读取历史、检查点及预算结算时序保持不变。

**已合并原子路由诊断片**：[#451](https://github.com/2002yy/study-agent/pull/451) HEAD `cecb9775`，精确 PR CI `44289328844` 成功，审查无未解决线程，预期 HEAD 保护合并至 `main@95fdbe96`。原执行器仍独占 `route_missing_atomic_claims`、`extraction_targets/routed_pairs` 与每次检查点；“决定路由后”和“真实提取后”的两个指标写入移至读取观测模块，保留每项 60 条上限、既有字段及顺序，未改变实际 claim 支持关系。在当时最新主线复核读取栈 **458 passed、4 skipped**、定向 **19 passed**，mypy 仍为 **115/125**；无模型/付费调用。

**共享可变状态边界**：① `execute()` 仍唯一持有、在恢复检查点后重新绑定 `state/cursor/context`；② `ActiveReadDispatchContext`/`ActiveReadExecutionContext` 只留运行期稳定依赖，当前候选和读取历史逐次显式传入；③ 读链投影只返回结果；④ `selected_sources` 在实际提取后由执行器更新；⑤ 观测函数只在调用时写当前 `context.metrics`，不持有旧快照；⑥ 模型 inflight、`reserve_call` 及最终结算、证据发布均由原权威负责。

**历史 read-plan v1 加载器退役（2026-11-19，独立片）**：主动研究运行器中
`_load_read_plan` 与唯一专用的 `_read_plan_entries` 曾将旧版单列表计划转换为
v2 双列表，但在仓内运行、恢复、测试及阶段门已无调用方。二者成组删除，不留
兼容空壳。**保留**现行 `claim_engine_read_plan` 字段、
`ACTIVE_RESEARCH_READ_PLAN_KEY`、活动计划和持久化恢复契约，不修改 schema，
也不声称删除实际数据库迁移能力。原影响集 **96 passed**，Ruff、差异检查、
mypy 基线 **115/125** 通过；真实检索和模型 `not_run`。

**后继故障记录显式游标片（本地独立候选）**：基于 `main@95fdbe96`，直接在 17 个故障分支调用已经存在的 `with_appended_runtime_failure(cursor, context, ...)` 并显式绑定返回游标，移除 `execute()` 内捕获 `cursor/context` 的 `_append_failure` 闭包。未更改已有纯投影函数、失败 ID/去重、异常处理、检查点、恢复、预算或发布代码。冻结契约的基础运行器与故障投影回归 **87 passed**，预算时钟/模型尝试/失败契约/结算/steering **37 passed**；读取栈阶段门 **458 passed、4 skipped**（107.59 秒），全库 Ruff、diff-check 与 mypy 基线（115/125）通过。新候选精确 HEAD CI 另行验收，当前绝不冒充已合并。

**唯一下一收口动作**：完成上述候选的读取栈阶段门、差异范围核对与精确 HEAD CI，审阅通过后独立合并；之后再按真实测试调用方清理重复造景，不重新建立模型、恢复或发布权威。#404 测试造景由另一窗口处理；原 #369 零模型社区覆盖探针仍待真实浏览器与 SearXNG 验证，不构成当前结构片动态 PASS。

### 2026-11-19 一次性实验账本演示退役（独立 P2 减负片）

- `tools/check_experiment_spend_ledger.py` 只在自身 CLI 使用示例和历史
  `CL_M1_REBIND_PREVIEW.md` 快照中出现；现行应用、`studyctl`、CI、阶段门、
  配置及测试没有调用。它模拟两次预留、一次超限与子进程读数，属于
  早期账本能力展示，不承担产品准入或当前人工预检。
- 整体移除该演示入口（109 行），**不**删除生产 `llm_spend_guard`、
  SQLite 实验账本、费用预留/结算、`precheck_sample_budget.py`，
  也**不**删除真实跨进程持久性/超限负控测试。当前正式验收文档仍引用
  `check_llm_spend_guard.py`，因此那条实际预检入口保留。
- 本片没有独占适配层、配置或专属测试可删除；历史文档不追溯改写。
  仅属无调用方实验工具减负，真实模型/搜索与费用支出均未发生。

### 2026-11-19 候选评估旧诊断异常及自证测试退役（P3 静态减负）

- `CompactAssessmentGainSignalDuplicateError` 明确标注只为旧诊断兼容保留；
  仓内从未抛出或捕获，仅由一项测试导入并检查继承关系。删除此孤儿异常和
  `__all__` 导出，连同只断言 Python 类继承关系的四项自证断言一起退役。
- 保留当前真实解析会抛出的 `CompactAssessmentCodeError`、relevance/role/gain
  分类异常、非法枚举与重复/无序响应的 fail-closed 解析，以及直接验证
  这些失败行为的参数化测试。无需适配层或配置调整；生产模型、候选排序、
  恢复与预算逻辑均不变。
- 仅静态验证 Python 编译、全仓孤儿引用和 diff；新精确 PR CI 才能证明
  完整回归。`priority=P3`、`loop=static`、`owner=retrieval/candidate-assessment`、
  `dynamic_evidence=not_run`、`budget_authorization=not_applicable`、
  `decision=engineering-only`。

### 2026-11-19 RQ1-C 双重 `_impl` 兼容转发层退役（P3 静态减负）

- 正式限定资格入口 `run_rq1c_bounded_qualification.py` 与确定性协议探针入口
  `run_rq1c_protocol_probes.py` 原先均经过仅转发符号、CLI 参数和结果的
  `_impl` 兼容模块再进入 `_core`。仓内消费者只有上述正式入口及针对旧层级的
  防绕过专项测试；生产研究、当前 CI/阶段门、发布和运行配置均不引用这两层。
- 删除两个 `_impl.py`，将原有 CLI 参数、输出、退出码保留在正式入口，直接
  调用原 `_core`；资格入口的预算上限、provider monkeypatch 注入点及
  binding-row 默认解析仍由原 guardrails 维护。核心实现、12 个 holdout、
  六个协议探针、失败即 NO-GO 的评估器和运行产物格式均不改变。
- 同步将旧适配层的执行/导入/脏工作树校验迁至正式入口和 `_core` 双边，
  保留精确 HEAD 不匹配、脏跟踪文件时禁止运行的负控，测试文件重命名为
  `test_rq1c_exact_head_entrypoints.py`。无需新适配层或配置；现行
  `tests/stage_gates.json`、`tools/ci_scope.py` 无旧文件显式注册。
- 本地已完成 Python 编译检查、零遗留调用检索与差异检查；执行环境无
  pytest/ruff 离线依赖，完整资格/预算测试与 CI 需在此候选精确 HEAD 验收。
  首轮 CI 发现 4 项预算用例仍经由已删除的 `_impl` 取 guardrails/binding
  provider，且 1 项精确 HEAD 负控仍把私有 `_run_case` 当作公开入口导出；
  已改为直接验证真实 guardrails/core 所有者，公开 `run_qualification` 的
  精确 HEAD 拒绝负控仍保留，不恢复无产品调用方的私有兼容转发。
  本片 `priority=P3`、`loop=static`、`owner=qualification/tooling`、
  `dynamic_evidence=not_run`、`budget_authorization=not_applicable`、
  `decision=engineering-only`，没有调用任何付费模型或外部检索。

## 0A. 已冻结研究路线（摘要）

`Lookup → VERIFIED / SAFE_ABSTAIN / ESCALATE_STANDARD`；Standard 的多源/比较/冲突和 Deep 的计划/缺口/收益/暂停恢复复用既有 `ActiveResearchRuntimeExecutor`，不另起第二套研究引擎。`usable/read_backed/relevant` 不能等同逐条 claim 支持；默认 `simple` 只验证引用 URL 属于已读来源，不标逐条 verified。

## 0B. M4 智能 UI 决策（摘要）

保留 M4-C 测量链路及 M4-D 增量修改基础；M4-E 受控修复须带版本/源码哈希及明确错误判据，失败保留旧版本；M4-F Three/WebGL 在受控沙箱执行，禁止加载任意第三方脚本；M4-G 根据问题选文字、静图、动画、交互或 3D。默认局部修改、修复成功率和媒介选择质量需真实任务验证。

## 历史原文与追踪

- **2026-11-19 §118/§120 Crawl4AI 历史资格工具整链退役（独立片）**：
  `tools/run_crawl4ai_qualification.py` 曾在固定端口启动浏览器夹具和 worker，
  串行执行四项手工门，随后可选调用唯一后继
  `tools/run_crawl4ai_cohort_v2.py` 运行冻结前置状态的 12 行 cohort。
  前者无现行消费者，后者除前者外也没有生产、测试、CI、阶段门、活跃文档
  或其他工具调用方。两份旧脚本成组删除后，历史 bakeoff 结果合同及
  六类冻结 manifest 仅被自己的专属测试引用；故再移除
  `src/web/research/browser_bakeoff.py`、`tests/test_browser_bakeoff_contract.py`、
  旧 manifest、两处阶段门注册及 README 中过时的当前维护承诺。
  不留孤儿 CLI、兼容入口、假产品负控或配置。原始资格观测仍在 Git 历史/归档。
  **保留**真实 Crawl4AI 专家读取、仍被当前超时/集成测试使用的
  `browser_bakeoff_fixture_server.py`，以及 shutdown、安全、预算/读取调度负控。
  本片仅执行离线影响测试，
  不改变生产浏览器路径；真实浏览器资格重跑和付费模型 `not_run`。

- **2026-11-19 无调用方的游标/新鲜度辅助函数退役**：
  `src/web/research/runtime.py::_counter_mapping` 与
  `src/web/github_freshness.py::_payload_compact` 均无生产、工具、测试、
  CI、阶段门调用，也非动态入口，直接删除，不保留空壳或测试/配置。
  正式 `ResearchRuntimeCursor.from_dict` 的 v1/v2 游标格式和逐字段校验、
  GitHub 新鲜度缓存及主/辅证据与漂移判断均不变。原游标恢复和快照
  影响集 **74 passed**，Ruff、差异检查、mypy 基线 **115/125** 通过；
  真实远程 GitHub 请求及付费模型 `not_run`。

- **压缩前原始 1,466 行**：[`main@cf62add5/docs/PROJECT_STATUS.md`](https://github.com/2002yy/study-agent/blob/cf62add59d4a35e9a2060cbeafc68be1572ad570/docs/PROJECT_STATUS.md)，原始记录完整存于 Git 历史。
- [2026-10-24 999 行归档](archive/PROJECT_STATUS_HANDOFF_PRE_CLEANUP_2026-10-24.md)、[2026-10-23 旧档](archive/PROJECT_STATUS_HANDOFF_PRE_CLEANUP_2026-10-23.md)、[2026-10-06 旧档](archive/PROJECT_STATUS_PRE_177_FINAL_REVIEW_2026-10-06.md)。
- 2026-11-17 完整执行链以本文件上方 PR/CI、[有日期执行记录](research_quality/RETRIEVAL_LEAN_EXECUTION_20261117.md)、各 PR 讨论及可还原的提交历史复核。
