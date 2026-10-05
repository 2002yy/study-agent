# Lookup 四门资格化合同

当前进度唯一入口：`docs/PROJECT_STATUS.md`。冻结基线为 #173 合并 main
`9a359e2a688fe42166f6cc6ab4eaeed4cf87b782`。本阶段验证运行策略、证据覆盖与
发布安全，不增加网站解析器、不改变预算、不授予语义评审或学习掌握权限。
#173 合入不等于 Lookup CLOSED。Standard、Deep 另行资格化。

## 四门与停止合同

这里的 L1–L4 是 Lookup 验收门，与 AGENTS.md 的回归分层 L0–L3 不同。

| 门 | 必须满足 | 证据 |
| --- | --- | --- |
| L1 预算 | 最多 3 次逻辑读取、2 个调度阶段；30 秒总硬预算，保留 10 秒收尾；足够官方证据后不继续通用搜索 | gateway 调用、实际外部搜索次数、各 reader 后端调用、停止原因；field-backed 答案模型调用为 0 |
| L2 恢复 | 首选候选失败不终止；剩余预算内换候选/读取后端；全部不可用或耗尽时停止 | 初始失败、后续读取与终止轨迹；可读正文和可发布支持分开计分 |
| L3 覆盖 | 支持的明确问题取得所有请求字段，版本/来源身份正确 | official-first、usable read、逐字段/事实 coverage、实际保存的 assertion refs |
| L4 安全拒绝 | 无证据、身份不符、伪绑定时不发布目标事实；危险发布为 0 | ChatService/SQLite 出口、摘要/跨度负控、无模型补写；部分已知字段不冒充完整回答 |

官方解析 → 读取 → 身份/绑定及请求字段足够 → STOP。
不足或失败 → 有界恢复 → 支持足够则 STOP；耗尽/截止/取消则保留缺口、安全拒绝并 STOP。
调度阶段计数不等于外部搜索次数；官方地址解析也占现有阶段预算。
逻辑 read 次数不等于后端请求次数，后端耗时/调用仍须单列，不能借此规避预算。
当前测试用可控时钟核对截止路径；本机小样本耗时不授予 wall-time SLO。

## 固定 16 个案例

执行测试：`tests/test_lookup_tier_qualification.py`。网络边界使用冻结 payload/故障注入，
运行原生 gateway、recovery、reader、publication 与真实临时 SQLite。模型调用哨兵禁止回答补写。
测试参数即固定案例；不新增 benchmark 框架。

| ID | 案例 | 门 | 当前开发结果 |
| --- | --- | --- | --- |
| 01 | FastAPI 当前版本/包上传日期，保留日期语义 | L1/L3/L4 | 通过 |
| 02 | SQLite 指定版本变化，官方充分证据立即停 | L1/L3 | 已知阻断，strict xfail |
| 03 | arXiv 来源实际作者/首次提交时间 | L1/L3/L4 | 通过 |
| 04 | Python 3.14 官方发布日期 | L1/L3/L4 | 通过 |
| 05 | Opus 5.5 官方定位原文 | L1/L3/L4 | 通过 |
| 06 | 官方第一个 URL 超时后换候选 | L2/L4 | 正文恢复通过；可发布覆盖仍有缺口 |
| 07 | 第一候选正文空，第二候选可读 | L2/L4 | 正文恢复通过；可发布覆盖仍有缺口 |
| 08 | 本地 reader 无正文，第二后端成功 | L2 | 读取链通过；不授予字段支持 |
| 09 | 所有 read 不可用 | L1/L2/L4 | 有界停止、安全拒绝 |
| 10 | 全部候选被公共 URL 策略拒绝 | L1/L2/L4 | 零读取、安全拒绝 |
| 11 | Python 目标 3.14，只读到相邻 3.13 | L4 | 安全拒绝 |
| 12 | Opus 正确 model ID 仅在导航栏 | L4 | 安全拒绝 |
| 13 | URL 正确、正文产品版本错误 | L4 | 安全拒绝 |
| 14 | 正文读后摘要/字段跨度被篡改 | L4 | 安全拒绝 |
| 15 | Python release date 缺失 | L3/L4 | 日期不补写；请求 coverage 未通过 |
| 16 | 查询迟到，Lookup 截止且保留收尾 | L1/L4 | 不读迟到候选、安全拒绝 |

开发检查：15 PASS、1 strict xfail。xfail 是明确未满足的合同，不是资格通过；
unexpected pass 会使 CI 失败，修复后须移除标记并重新绑定证据。
保留初次失败样本 `D:/study-agent-validation/lookup-matrix-development.log`。
不是全量网络资格结果：正式真实观察还须 exact-main CI 通过后执行，冻结五个官方问题、
每题最多两次观察，总上限十次；逐项绑定 main/candidate/code/source/answer digests、读取时间、
网络策略、runtime tier、保存的 turn 和 coverage。不能把 field_backed 当作请求覆盖。

## 当前阻断及后续范围

SQLite 指定版本的原生解析成功，但规范化正文 `project: SQLite\nversion: ...`
未通过通用版本 marker，触发救援搜索。此前 latest 查询没有版本 marker，未覆盖此路径。
下一运行策略修复应复用原生身份/字段验证，不能用候选自报 verified 标记，也不新增站点解析。

恢复得到普通正文时，现有保守发布出口缺少该正文的逐事实支持，必须拒绝。
L2 可读性通过不代表 L3 可回答；不得为了验收绿灯放宽 Evidence Gate。
日期缺失负控允许保留已验证版本字段，但缺失的请求日期仍计 coverage 未满足。
Lookup 四门及整体研究均 **NOT CLOSED**。

Standard：S1 独立 claim 多源补全；S2 比较双方分别绑定，仅比较双方支持的事实；
S3 冲突检测，按权威性/时效/来源判 resolved 或保留 unresolved，禁止强行合并。
核心门是多源不降低单条事实可追溯性。

Deep：计划/gaps/waves，逐波新增支持的 Evidence Gain，证据不足继续、无 gain 收敛、
改变搜索方向、截止/取消/恢复；durable 状态、证据与剩余预算保留，避免重复消费已完成工作。
指标为 gain/wave、unresolved gaps、duplicate work、时间/预算、stop reason、resume correctness。
