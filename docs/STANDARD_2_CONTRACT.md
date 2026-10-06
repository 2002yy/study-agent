# Standard-2：持久化研究计划与执行循环

## 入口与范围

执行前置已满足：#178 exact-main `eb139900` 的 CI `37464024389` completed / success。实现分支 `codex/standard-2-research-loop`。

只做 planner、可恢复循环、观察与 completion artifact。不改 ChatService 自动 continuation、用户模式、UI、Evidence Gate 或事实发布权限。Standard-3 才做新增 claim binding 与冲突裁决，Standard-4 才接自动续研。

## 服务端输入

从持久化 handoff 加载 query、requested_fields、unresolved_fields、known assertion refs、usable_sources、attempted calls、lookup_budget。保持原 query；不根据已经读到的字段反推用户请求。继承 #178 的 owner、source version、handoff digest、deadline 和执行 lease 校验。

Planner 只提出 gap/query/candidate/action plan；计划需有 schema、版本、父运行和 handoff 身份，并在执行前保存。模型不授予 support 或 publication authority。候选和 query 必须与明确 gap 关联；planner 输出不合法时安全停止，不能静默扩问题。

## 唯一执行与预算权威

所有 search/read 都经 StandardExecution；预算、reservation、工作结果、cursor 和 deadline 只认 StandardExecutionRepository / SQLite journal。Planner 只能读取预算视图。

计划与下一动作 cursor 必须持久化；恢复先重放已完成观察，复用 cached/Lookup source，再处理未完成动作。未知 dispatch 不重发；旧 token 不能落结果。模型规划调用亦需有明确可恢复的记录与预算边界，不以重新规划绕过总时限。

本 slice 每运行至多一次规划调用，先保存 planning reservation，再调用模型；8 秒上限、零请求重试。接管时已保存计划直接复用；仅有 reservation 无计划则 result_unknown，不重新调用模型。最多 4 个 query、12 个已发现候选；新 URL 必须来自实际搜索结果，禁止模型虚构 URL。嵌套 `standard-research-loop-v1` 复用现有 journal，不新增数据库表。取消／deadline 只允许当前 owner 保存由已有观察构成的诊断结果，不接受迟到正文或新增计费。

## 循环

持久化输入 → planner proposal → 程序校验并保存 plan → 优先 inspect/reuse → 必要时 search → 验证候选后 read → 保存 observation → 更新待研究 gap → 继续或停止。

暂停/重启不重置计数、deadline、plan 或已完成 cursor。新读正文只能标为 acquired/readable；未经 Standard-3 绑定的 requested field 保持 NOT_EVALUATED / unresolved。不能把 related、read_backed、完成一个 read 或 planner 自评当成 support。

## Completion artifact

StandardResearchResult 含 gap_states、acquired_sources、reused_sources、read_outcomes、unresolved_gaps、conflicts/待核对冲突线索、budget_consumed、stop_reason、parent/source/plan 身份、publication_authority=false。

输出没有生成答案的权限。停止原因区分 plan_exhausted/ready_for_binding、budget_exhausted、deadline、cancelled、result_unknown、planner_invalid、conflict_requires_binding。Standard-2 不自行宣称 SUPPORTED 或裁决冲突。

## 必要控制与验收

- planner 从真实 saved handoff 取输入，不重新猜用户问题；伪 owner/hash/schema 均拒绝。
- 先复用，不重复网络调用或计费；新工作遵守唯一账本与既有预算。
- plan 保存后才执行；执行中断/新进程恢复不重新规划、不重复完成工作。
- provider 超时、取消、deadline、接管与 unknown 均正确停或保留 gap。
- 模型声称事实成立或请求发布时，结果仍无 publication authority。
- 能从 Lookup unresolved gap 产生明确计划、获取新增来源、形成可恢复 artifact；暂不验收发布答案。

实现前按 touched symbols 声明 impact set。**用户 2026-10-06 最新覆盖：Standard 整个阶段完成后才跑一次完整 L3，Standard-2 / 3 / 4 slice 使用 L0、命名 L1 与相应 L2；不按每个 slice 的持久化／authority 修改触发全量。** 总验收仍先冻结 clean exact candidate 并执行 L3 preflight。Standard-2 候选 `02747a42` 的提前全量运行已停止，不计 PASS、不自动重跑。CI 和最终审查只认新候选 head。不开自动 continuation，不宣称任何 tier CLOSED。
