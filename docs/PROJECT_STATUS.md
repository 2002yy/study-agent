# Study Agent 当前状态

> **唯一冷启动/交接入口。** 本文保留已核实的现状、开放阻断和下一执行片；细节证据在 [2026-11-17 收口记录](research_quality/RETRIEVAL_LEAN_EXECUTION_20261117.md)、对应 PR、精确提交 CI 和 Git 历史。稳定规则以 [AGENTS.md](../AGENTS.md)、[产品迭代规则](PRODUCT_ITERATION_POLICY.md) 为准。
>
> **产品目标**：体验接近 ChatGPT 的通用聊天与研究 Agent，覆盖自然聊天、自主研究、持续交互、智能 UI、多模态和工具执行；教学是专业场景。**部署仍限可信环境的单用户**；多用户身份/数据/费用隔离未实现。

## 0. Current Handoff（2026-11-18，冷启动）

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

### 旧 HTTP 研究入口退役（待精确提交验收）

- `codex/retire-web-lookup-compat-20261118`：仓内唯一实际使用旧
  `POST /web-lookup-runs` 的真实验收脚本 `tools/studyctl_live.py`
  已迁至正式 `POST /research-runs` 创建、再用 `POST /research-runs/{id}/search`
  执行。完整退役四条 `/web-lookup-runs` 兼容路由、其无用转发函数、
  `NewsLookupRequest` 模型及旧入口专项测试；正式研究恢复测试补足
  `/research-runs` 读取/列表覆盖。`docs/TECH_STACK.md` 的现行调用说明同步迁移。
  **保留**供评测及业务继续调用的 `WebLookupService.lookup()`，研究持久化、
  恢复和预算逻辑不变。本项尚未进行真实服务/付费检索验收；合并状态以对应 PR 为准。

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

### 历史减负候选快照（部分已合入，以下不是当前待办）

- **2026-11-18 RQ1-C 成对归因实验链退役（独立片）**：
  `codex/retire-rq1c-paired-attribution-20261118`。旧 `run_paired_attribution.py`
  只调度同阶段 `run_rq1c_calibration.py` 和
  `run_environment_fingerprint.py`，三套工具没有现行应用、CI、阶段门或
  其他工具调用；旧产物仅供诊断，**不是**正式资格证据。连同唯一专属
  `test_paired_attribution.py`（20 个历史测试）整链删除，净减 **1,941 行**。
  保留正式 `run_rq1c_bounded_qualification`、冻结 holdout 清单、阶段门、
  成本/预算及相关现行测试；不改变生产搜索、研究恢复或预算决策。

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
  对应标记和群聊隔离已由 `test_wechat_service.py`、`test_api.py` 分别覆盖。
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
  保留 `src/interactive_patch.py`、恢复契约以及增量修改/能力继承的
  现行单元测试，确保退役实验不会顺带移除仍有价值的功能基础。

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
  不再维护旧 E0–E3 历史重放策略；留存历史数据/报告及仍被浏览器搜索探针使用的
  `qp1c_queries_v1.json`。局部检索影响集 **27 passed**；Ruff 通过，
  无模型/API 费用。此项仅为离线工程清理，不代表检索效果变化或动态验收。
  PR #449 已通过精确提交 CI 并合并；不影响独立研究运行器重构片。

- #406：移除无前端调用方的新闻运行客户端兼容接口及对应历史测试，约净减 530 行。
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
- **另一独立清理片（待 PR）**：退役不再被生产、CI、现有工具或当前评测调用的旧网页重试特征统计、学习状态临时方案对照、S1/S2 阶段观察，以及重试统计专属测试。共 4 文件，原始约 639 行；不触碰实际网页读取器、持久学习模型、计费安全和故障恢复用例。旧实验结论仍可从 Git 历史或归档文档查看。
- **后继学习状态实验链（依赖上一片先合并）**：完整移除早期 §164/165/168 的下一步、误解、持续对话、阶段 D 取样、影子采集和 S1/S2 真实观察六份单次脚本；其中唯一跨脚本调用源 `run_phase2_rollout_observation` 已在上一片删除。生产 `learner_state_durable_adapter`、`learner_state_shadow_seam`、持久学习状态及相关测试不动，仅更新说明中对已退役脚本的提及。此片独立验证，不能将未完成的 CI 视为通过。

### 2026-11-18 旧 Wigolo 浏览器对比运行器退役（独立片）

- 早期 A3 的 `tools/run_browser_bakeoff.py` 只有其专属
  `tests/test_browser_bakeoff_harness.py` 调用，不参与现行检索、Crawl4AI
  资格评测或 CI 执行。退役整组脚本和历史联调测试，并移除阶段门中这份
  旧专项测试的两处重复引用；旧测试的浏览器是否升级/壁垒分类行为现由
  `test_chain_executor.py`、`test_progressive_routing.py` 与
  `test_wigolo_browser_executor.py` 验证。Crawl4AI cohort v2 **仍调用**
  `browser_bakeoff.py` 的结果构造/校验与旧 manifest，故保留该模块、
  manifest 和共用 fixture 服务，将原专项测试中不可替代的结果真实性负控
  合并进 `test_browser_bakeoff_contract.py`。不修改真实浏览器读取逻辑，
  不执行外部浏览器或付费模型调用。

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

**后继故障记录显式游标片（本地独立候选）**：基于 `main@95fdbe96`，直接在 17 个故障分支调用已经存在的 `with_appended_runtime_failure(cursor, context, ...)` 并显式绑定返回游标，移除 `execute()` 内捕获 `cursor/context` 的 `_append_failure` 闭包。未更改已有纯投影函数、失败 ID/去重、异常处理、检查点、恢复、预算或发布代码。冻结契约的基础运行器与故障投影回归 **87 passed**，预算时钟/模型尝试/失败契约/结算/steering **37 passed**；读取栈阶段门 **458 passed、4 skipped**（107.59 秒），全库 Ruff、diff-check 与 mypy 基线（115/125）通过。新候选精确 HEAD CI 另行验收，当前绝不冒充已合并。

**唯一下一收口动作**：完成上述候选的读取栈阶段门、差异范围核对与精确 HEAD CI，审阅通过后独立合并；之后再按真实测试调用方清理重复造景，不重新建立模型、恢复或发布权威。#404 测试造景由另一窗口处理；原 #369 零模型社区覆盖探针仍待真实浏览器与 SearXNG 验证，不构成当前结构片动态 PASS。

## 0A. 已冻结研究路线（摘要）

`Lookup → VERIFIED / SAFE_ABSTAIN / ESCALATE_STANDARD`；Standard 的多源/比较/冲突和 Deep 的计划/缺口/收益/暂停恢复复用既有 `ActiveResearchRuntimeExecutor`，不另起第二套研究引擎。`usable/read_backed/relevant` 不能等同逐条 claim 支持；默认 `simple` 只验证引用 URL 属于已读来源，不标逐条 verified。

## 0B. M4 智能 UI 决策（摘要）

保留 M4-C 测量链路及 M4-D 增量修改基础；M4-E 受控修复须带版本/源码哈希及明确错误判据，失败保留旧版本；M4-F Three/WebGL 在受控沙箱执行，禁止加载任意第三方脚本；M4-G 根据问题选文字、静图、动画、交互或 3D。默认局部修改、修复成功率和媒介选择质量需真实任务验证。

## 历史原文与追踪

- **压缩前原始 1,466 行**：[`main@cf62add5/docs/PROJECT_STATUS.md`](https://github.com/2002yy/study-agent/blob/cf62add59d4a35e9a2060cbeafc68be1572ad570/docs/PROJECT_STATUS.md)，原始记录完整存于 Git 历史。
- [2026-10-24 999 行归档](archive/PROJECT_STATUS_HANDOFF_PRE_CLEANUP_2026-10-24.md)、[2026-10-23 旧档](archive/PROJECT_STATUS_HANDOFF_PRE_CLEANUP_2026-10-23.md)、[2026-10-06 旧档](archive/PROJECT_STATUS_PRE_177_FINAL_REVIEW_2026-10-06.md)。
- 2026-11-17 完整执行链以本文件上方 PR/CI、[有日期执行记录](research_quality/RETRIEVAL_LEAN_EXECUTION_20261117.md)、各 PR 讨论及可还原的提交历史复核。
