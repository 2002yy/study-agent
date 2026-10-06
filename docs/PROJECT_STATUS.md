# Study Agent 当前状态

> **唯一进度入口**
> 更新：2026-10-06
> 产品定义：**Study Agent 是长期保持“正在学什么、已经确认什么、还不会什么、下一步是什么”的个人学习工作台。**

本文件只维护当前权威状态、可复核边界和唯一下一门。2026-10-06 本次收敛前的完整状态原样归档到 [`archive/PROJECT_STATUS_PRE_177_FINAL_REVIEW_2026-10-06.md`](archive/PROJECT_STATUS_PRE_177_FINAL_REVIEW_2026-10-06.md)；更早历史继续由既有 archive 与 Git 历史持有。

## 0. Current Handoff（cold-start 入口）

**当前执行权：#178 Standard durable handoff consumer（未接自动规划）。** #177 的最终 PR head `72fc67e5` CI run `37418122175` 与 exact-main `8a5148e3c7d438e0ad5846b6d901f334d971e781` push CI `37420193931` 均 `completed/success`，main 验证已通过。#178 原 head `c5fe9d896d1a341aa90f59b6213cd025192905bf` 的 CI `37422145467` 也为 success；该绿灯不借给本轮新增代码。

**施工身份：** worktree `D:/study-agent-validation/standard-handoff-consumer`，分支 `codex/standard-handoff-consumer`，base `8a5148e3`，PR #178 draft。本文件所在提交是新候选身份。草稿扩展成同一 handoff consumer 的持久化闭环；没有激活 API／自动续研或修改 UI、publisher、数据库 schema。

**本轮行为：**

- ChatService 将真实 thread/turn owner 传给既有 persistent resolver；测试由 resolver 建立带 owner 的 source run，不再在聊天完成后人工补归属。
- 入场对象只保存已验证快照，不调用 provider；StandardExecution 是唯一 dispatch adapter，预算和结果权威统一到 SQLite。
- 使用现有 research child run / create_request_id 幂等创建一个子运行。`standard-dispatch-journal-v1` 保存在既有 research_context 中，含固定 deadline、来源版本／handoff hash、执行租约 token、cursor、预算和工作结果。
- 每次新网络调用前，在 `BEGIN IMMEDIATE` 事务中核对真实 owner、parent/source/thread、取消、deadline、运行状态与 lease，先记录 reserved 并扣预算；成功结果再由同一 owner 保存。5 reads / 4 queries、单源 6000 / 总正文 24000 chars，失败也计费；Lookup 已读正文和成功搜索直接复用。
- Standard 窗口最多 60 秒，保留 12 秒收尾；整体上限原 turn 创建 + 90 秒。恢复沿用首次 deadline，不能重新开始计时。provider 每次调用最多 8 秒，并观察持久化取消；迟到 worker 不能自行 checkpoint 或发布。
- interrupt 持久化后可由新 token 恢复；lease 到期允许接管，旧 token 无法继续写入。completed 工作重放结果；失败／reserved 后崩溃留下的 unknown 工作禁止自动重发。**不宣称跨崩溃的外部请求 exactly-once**，只保证预算不重置、已知完成结果不重复消费、未知结果不会偷偷重试。

**验证：** 入场／持久化共 50 个 controls；最初 47 项通过，派发边界后的 named impact set `315 passed / 118.97s`（含其中 49 项），独立 Python 子进程追加测试 `1 passed / 0.92s`，含 fresh repository 重建、并发启动／租约、crash-window、旧 owner 回写、取消／deadline、失败计费、正文预算和未知 schema。Ruff／格式／diff check PASS；mypy baseline `122 current / 128 baseline / 6 resolved`，无新增错误。mandatory early L3 修正候选正在运行，结果待记录。由于新增持久化 envelope 和执行合同，本轮必须完整 L3，不能沿用 #178 原 171-test 证据。静态审查发现 reservation 后 deadline 到达仍可能派发网络，已补 caller／worker preflight 和零网络调用负控；此前中止的 L3 不计 PASS，新生产候选重新跑一次完整 L3。

**冻结边界：** Standard planner、claim decomposition、cross-source binding、比较／冲突与发布未接入；当前 primitives 只可由服务端显式消费。pending handoff 不等于自动执行；相关正文不等于事实发布权。Lookup / Standard / Deep overall 均 **NOT CLOSED**，UI 独立后置。

**唯一下一门：** 完成本候选 impact set + L3 → 最终静态审查 → 推送 #178 新 exact head 并核其 CI。绿后再独立接 Standard 受控 planner/claim-binding，验证从 Lookup unresolved gap 到可发布证据的真实路径；不跳过多源／比较／冲突资格验收。

## 0A. 冻结研究路线

```text
Lookup
  → VERIFIED / SAFE_ABSTAIN / pending ESCALATE_STANDARD
Standard
  → 多源补全 / 双方比较 / 冲突处理（尚未接入自动消费）
Deep
  → plan / gap / Evidence Gain / saturation / interruption-resume（后置）
```

共享原则：**模型决定“去哪找、找什么”；程序决定“你到底找到了什么”。** `usable/read_backed/relevant` 不等于 claim support；claim support 不等于 publication authority。

## 0B. 仓库与施工纪律

- 一个 feature slice 尽量整块完成、一次验证、少提交；只在阶段门需要权威 exact-head 证据时触发 CI。
- push/PR 之后只认当前 exact head；旧 HEAD 绿灯不能替代新 HEAD。
- 生产候选只有在 CI、最终审查与 expected-head 一致时才允许合并；merge 与 CLOSED 是不同门。
- UI、研究与其他项目保持独立 bounded slice，禁止为赶门把无关改动混入。
