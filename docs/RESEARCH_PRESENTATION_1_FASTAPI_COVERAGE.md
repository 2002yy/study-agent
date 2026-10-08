# RP-1 S5 / N3 FastAPI 证据覆盖归因

2026-10-09。诊断切片 LOCAL CLOSED；研究质量仍不合格，RP-1 / R6c NO-GO。
基线 `6c539d2b4119ea62fcf9c79ad672a32e42ef1a4a`，branch `codex/reading-notebook-ui`。
仅重放既有真实 SQLite；没有新样本、提供商调用或生产代码变更。

## 可复核证据

原始数据库：`D:/study-agent-validation/reading-notebook-ui-evidence/r6c-qualification-20261009/runtime.db`。
诊断脚本及完整输出：`D:/study-agent-validation/reading-notebook-ui-evidence/r6c-fastapi-coverage/trace.py`、`trace.json`。
用项目 `.venv/Scripts/python.exe` 执行；SQLite `mode=ro`，前后数据库 SHA256 一致。
逐例重用原 claim loader / assessor / projection / writer / auditor / seed validators；
每例九项检查通过：seed/hash/projection、known span/hash、抽取原文跨度、授权引用完整、
首次候选排除、无推断发布日期、未声明字段单元、末两波无增益、默认审计 fail-closed。
原主张规划器只持久化 response SHA256 / schema / token / finish_reason 与验证后的 claims；
**原始 Deep planner 响应 NOT_CAPTURED**，不能冒称已检查 wire 内容。Standard 原输出另在原批次 planner-trace.jsonl。

| 记录 | S5：FastAPI 0.136.0 | N3：FastAPI 0.115.0 |
| --- | --- | --- |
| Deep run | `deep-eb237b65be0dcc5bc5a72226` | `deep-b15609d63fa100a459f91556` |
| Standard parent | `standard-8e261dedf83d9202163443b1` | `standard-3ac3387d360d12d64894c43b` |
| Standard 消耗 | 1 新查询 / 5 新读取 / 1 复用 | 1 新查询 / 5 新读取 / 1 复用 |
| Deep 候选 / evidence payload | 7 / 3 | 10 / 4 |
| 合格支持 cluster / 要求 | 1 / 2 | 1 / 2 |
| Deep 新物理读取结果 | 1 次失败，0 次成功 | 2 次失败，0 次成功 |
| Deep 持久 reads_used | 0（不可当成未尝试读取） | 0（不可当成未尝试读取） |
| Deep 消耗时间 / 硬截止 | 24.826 / 180 秒 | 31.717 / 180 秒 |
| 终态 | partial / evidence_saturated | partial / evidence_saturated |

表中版本与时间只描述既有样本记录，不声明当前最新 FastAPI 或实际发布日期。
完整 thread_id / turn_id / run_id / parent_run_id / version 在 trace.json。

## 1. 发现：已解析出的官方候选在 Standard 白名单首次丢失

两例 Lookup `official_resolve` 已返回精确 PyPI JSON 与
`https://fastapi.tiangolo.com/release-notes/`。PyPI 已读且身份/span/hash 有效；
release-notes 在本次 Lookup 未读。handoff 完整保留 resolver 调用，未丢原记录。

首次排除 owner 是 `src/web/research/standard_plan.py::discovered_urls`：
候选集合仅由 `usable_sources` 与 `attempted[name=web_search]` 组成，
不接纳 `official_resolve` 的未读结果。
`ModelStandardPlanner` 用该集合生成 allowed_candidate_urls，因此这两例只有 PyPI URL 可提议。
模型遵守白名单，未擅造 release-notes URL；严格 validator 不应被放宽。

这是可复现的候选交接缺口，**不是证明 release-notes 一定含有所需日期**。
后续窄修复需显式定义可信 resolver 候选的数据合同，经公共地址/项目/版本约束后
传递为待查候选；不得授予证据身份、读取成功或答案支持权。
正控：已保存 resolver 候选可进入预算内规划；负控：伪造/私有/错项目/错版本/非合同结果仍拒绝。
是否真正取得日期必须另用原样真实回归证明，不能凭白名单恢复宣布覆盖 PASS。

## 2. 读取：额度用在低相关来源；Deep 新读均未取得正文

两例 Standard 新读取五次：官方中英文首页、中文镜像首页、教程与 CSDN。
前四份正文可读，最后一份无正文；这些来源未证明精确版本的发布日期。
Standard 以 budget_exhausted 结束，查询额度没有用满，读取额度已用满。
不足以据此推荐扩大 reads：应先恢复已知的具体官方候选，改善预算内来源选择。

Deep 从 Standard seed 复用正文，再经原抽取器判断资格；复用不等于新增独立来源。
后续 GitHub 仓库首页读取为 invalid_content / short_doc，S5 一次、N3 两次失败。
不能把 failed attempts、成功物理读取、seed materialization、payload 数合成一个计数。
两例 Deep 末两波没有 substantive gain，按原饱和规则停止；没有 180 秒耗尽证据。

搜索提供商 raw audit 为 partial：Bing 返回五条首页/教程，SearXNG challenge，
DuckDuckGo wallclock_timeout；这不是全提供商无结果。
另记录一个非阻断观测债务：`active_research_runtime::_runtime_query_status`
把 partial 归为 unavailable，尽管 cursor result_count=5 且实际候选已消费。
本次归因使用原 provider audit 与候选，不用简化状态推断搜索全失败；本轮不混入修复。

## 3. 绑定：身份和引用未丢失，日期含义不足

两例 PyPI 原正文都包含 project、精确 version、distribution_uploaded_at；
known 的内容 hash 与正文跨度逐项一致，seed 验证通过。
原文没有 release_date 字段，Lookup / Standard 持续保留 release_date 未解决。
Deep 抽取也保留“上传时间并非明确发布日期”的 caveat。
不得重命名 distribution_uploaded_at 或借相邻版本日期填补 release_date。

唯一授权支持分别为 `web_cdc6e8cc71a75f8e7cd4ca0a`、`web_8869a3142e92d44b1bd55888`，
强度 0.9 / primary；其他首页/教程为 lead 0.05，不能提升为 supports。
原 assessor 要求两个独立 cluster，而实际只有一个，故 partially_satisfied。
projection → payload → draft 的授权引用集合完全相同；不是 S3 旧 writer 无ref缺陷复发。
这里的 supports 是原粗粒度 claim-link 结构资格，**不表示发布日期已获得语义证明**。

## 4. 问题覆盖与发布：两个独立合同限制

Standard 的 release_date gap 在持久结果中仍在；Deep runtime planner 重新从
run.query 建立整句 critical claim，以 current_fact profile 生成要求。
两例 `required_units=[]`，证据 `units=[]`，assessor 明确报告 no_required_units /
semantic_adequacy=not_evaluated。字段级版本与发布日期无法逐项判定覆盖。
首次缺少覆盖声明的 owner 是 runtime claim planning / policy requirement construction，
不是 synthesis 或 UI；现有 seed 本身也不提供语义权威。
后续如需字段级 claim 单元，应独立合同化服务端 requested-fields 与证据绑定；
禁止让 assessor 从相似字符串自动猜 required_units 或赋予 unit 支持。

最终 `deep_publication` 没有 qualified semantic judge，使用默认 abstaining_judge。
三类 blocking issues：semantic_support_unverified、evidence_grounding_incomplete、unanswered_aspect。
这是 Deep-4B 冻结的 fail-closed 行为，不是证明全部来源都错误，也不是预算故障。
恢复候选、增加独立来源或修复字段表达均不能自行越过此门。
两例合格 TTUV / 真实进程重启仍 NOT_OBSERVED；不填 0，不把 audited 候选视为发布。

## 关闭与下一切片

本轮只关闭归因项，没有关闭证据覆盖或 RP-1。生产 hash、预算、来源资格、发布门与 UI 未变；
延用 `6c539d2b` 已通过的 131 L1 / 373 L2 / Ruff / mypy NEW0，不重复开发测试或真实八样本。
本次只读检查及 docs diff-check 通过，独立文档提交，未 push / PR / CI。
最终 head / dirty state 由 Git 与本证据目录 closeout-state.json 恢复。

**唯一下一执行 slice：真实后台 Deep 进程重启恢复。**
使用原样已登记任务，先保存持久 running phase / cursor / inflight marker / version / lineage，
再停止本窗口拥有的后端进程，重启并验证原 child 的恢复及 exactly-once；
不得以仅终态才填充的 model_calls 指标作为唯一进入条件，不得伪造第二个 child。
候选白名单、字段级覆盖合同和 qualified semantic judge 作为明确未关闭事项保留，
不在恢复切片中混入事实语义或发布修复。
