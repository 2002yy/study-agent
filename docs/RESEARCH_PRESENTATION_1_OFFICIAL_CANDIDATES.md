# RP-1 官方候选交接：合同、修复与真实验收

2026-10-09。官方候选交接切片 LOCAL CLOSED，RP-1 / R6c 仍 NO-GO。
branch `codex/reading-notebook-ui`，base `37c305758ec507660cf53ec603d60141c16a227b`。
本批完成一处生产修复、集中正负控、影响/L2回归、原样 S5/N3 两次真实重放和下一阻断归因；
没有放宽预算、事实身份、支持强度、字段语义、发布门或学习权限，未改另一窗口 UI。

## 候选合同与唯一数据所有权位置

此前 Lookup 保存了 official_resolve 的 release-notes 地址，但
`src/web/research/standard_plan.py::discovered_urls` 只接纳 web_search 与已读 usable_sources。
本批由该 owner 增加 resolver_urls；模型提示和原 validator 仍共享同一候选集合。

新接纳必须同时满足：

- 调用类型 official_resolve，arguments.query 与 handoff.query 完全相同；
- recovery_stage=official_resolver，结果 status=ok、原 registry reason 完全相同；
- results 为列表，候选行是对象且未被 policy_allowed=false 拒绝；
- 通过原公共地址检查，URL 与当前 official_plan(query) 注册地址精确相同；
- 地址必须已经存在于持久调用结果，不能从当前 registry 静默新增未保存地址。

候选稳定去重，既有 usable_sources / web_search 行为未改。通用 release-notes 地址
只证明“可以尝试”，不能证明其中包含请求版本；正文仍须经过精确版本/span/hash/字段资格。
candidate action 在搜索发现动作之前、已读复用之后执行，使用原 Standard 配额。
不修改 handoff、known、unresolved_fields、source/evidence 记录或 publication_authority。
新 URL 不自行取得“官方已核验”的支持身份。

## 正负控与回归

新 `tests/test_standard_official_candidates.py` 15 项：
保存的精确 resolver 候选可以规划且不改变 known/gap/发布权；私有/本机/file 地址、
相邻版本、错误项目、伪造路径/域、不同请求、不同调用阶段、partial/非合同结果、
policy denied、畸形 results、未保存 registry 地址仍拒绝。
先红后绿：旧生产实现 1 失败 / 14 通过；修复后全部通过。

`tests/stage_gates.json` 登记 standard_official_candidates 影响集并将直接相关
Standard loop/execution/continuation 和新负控纳入 research-presentation-v1 L2。
影响 224 PASS / 95.26秒，L2 472 PASS / 177.63秒；Ruff / 两文件格式 / diff-check PASS。
mypy 按 CI `--explicit-package-bases src`：current122 / baseline128 / NEW0 / resolved6。
首次手写影响命令引用不存在的 test_official_resolver.py，在 collection 前终止；
按实际文件清单纠正为 lookup_official_identity / official_source_quality 后取得上述完整结果，
未修改生产以适配命令错误。
候选适配没有 schema/持久兼容/执行权威切换，不触发 L3；不重跑已验证的整仓测试。

## 两条原样真实运行

预登记及证据目录：`D:/study-agent-validation/reading-notebook-ui-evidence/r6c-official-candidates/`。
`registry.json` 在请求前保存 base、生产 patch hash 和原样 payload；S5 沿用原第一批请求，
N3 沿用已更正的既有新资格集请求，无新增题型、无手动路由/升级。
`planner-trace.jsonl` 保存原模型输出/allowed URL 请求和 validator；
`runtime.db` / `result.json` / `audit.json` 保存真实正文、持久 lineage、预算、选择理由与原审计。
audit.py 只读原 DB，前后字节 hash 一致；两例各 11 项检查，合计22 PASS。
后台只读观察 hooks 不改变返回值；本窗口真实 backend 已关闭，未使用 UI/浏览器作为新验收。

| 指标 | S5：FastAPI 0.136.0 | N3：FastAPI 0.115.0 |
| --- | --- | --- |
| 自然 Deep child | `deep-50e46574ac0fc4b0fd93ad25` | `deep-4aecfe63881d1244abb96fff` |
| Standard planner | 两个候选包含 PyPI 与 release-notes，原 validator 接受 | 同左 |
| 真实 release-notes 读取 | 成功，local_trafilatura，1055字符 | 成功，local_trafilatura，1055字符 |
| 截取正文是否含目标版本 | 是，原文含 0.136.0 及日期 | 否，最旧截到0.132.0 |
| Standard 新 search / reads / reuse | 1 / 5 / 1 | 1 / 5 / 1 |
| 未解决字段 | release_date | release_date |
| Deep终态 | partial / evidence_saturated | partial / evidence_saturated |
| 正式发布权 | false，audited-but-not-approved | false，audited-but-not-approved |
| 合格 TTUV | NOT_OBSERVED | NOT_OBSERVED |

两例 release-notes 被真实选择，并在发现首页前读取：原断点已闭环，不是仅改白名单后凭单元测试宣布成功。
既有原 terminal/publication validator、唯一 child、owner、审计 source hash、最终 revision
和冻结预算检查通过。完整 thread/turn/parent/version 在 audit.json。
上述日期只作为原正文证据存在与否的观察，不由本报告或 UI授予事实发布资格。
PyPI 上传时间仍独立字段，没有改名为发布日期。

## 后续断点已定位，不强行拉绿

**Standard 字段绑定：** S5 有精确版本/日期的原文，但本次读取是通用正文，
没有形成原资格合同认可的结构化版本/日期绑定；因此 release_date 仍未解决。
N3 原始截取正文缺少目标版本，不能用相邻版本日期补齐。
这两种情况必须分开：前者需可信原始来源到字段/span/hash 的提取合同，
后者需要版本定向读取能力；不得仅因为日期字符串出现就通过。

**Deep seed 使用：** 两份 release-notes 都已进入原 seed，candidate relevance=answer_relevant。
但 selection_trace 为 covered_cluster / scheduler_not_selected，最终 selected_sources 中
没有 release-notes，也没有对应 EvidencePayload。不能声称 Deep 已抽取/拒绝了其中日期。
首次排除位置：`active_research_runtime` 汇总 read 成功记录的 cluster，再由
`_build_read_plan` 的 fresh 筛选排除所有同 cluster 候选，包括未 materialize 的其他 seed。
主页与 release-notes 同属官方 cluster，主页 lead 并不证明 release-notes 的内容已处理。
独立来源统计仍不能把同域多个页面计成多个独立支持；这个保护必须保留。

**语义与发布：** 原 critical claim required_units=[]、没有 qualified semantic judge，
默认审计 fail-closed；两例问题覆盖/支撑仍未核验。官方候选恢复不关闭这些门。
原进程重启恢复 21 项 PASS 及 S1 严格 TTUV5.166秒保留，不重复验收或扩展为本例证据。

## 唯一下一完整批次

**Deep 已读 seed 的按候选复用合同与修复**：
分开“同一独立 cluster 已使用”与“特定正文已 materialize/extract”。
对于已持久、hash有效、当前 claim 相关且尚未处理的 seed，可在原字符预算内处理；
不额外消耗物理读取、不新增独立 cluster、不改变证据支持强度或发布权。
先重现首页 lead 覆盖同 cluster 后 release-notes seed 被误排除，集中负控：
同候选不可重复、错hash/错claim拒绝、同域不增加独立支持、字符/读取预算仍封顶、
取消/终态/重启不可重复执行；相关回归后原样 S5/N3，允许继续 NO-GO。
字段级 source binding、版本定向读取和 qualified judge 明确保留为独立未关闭项，
不混入本次候选交接提交，也不删除 covered_cluster 的新物理读取保护。

本批独立提交，未 push / PR / CI；最终 head / clean / scope 从 Git 和本证据目录
closeout-state.json 恢复，旧八样本不重复，原main/A线/另一窗口UI未改。
