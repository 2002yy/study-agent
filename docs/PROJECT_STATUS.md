# Study Agent 当前状态

> **唯一进度入口**
> 更新：2026-10-06
> 产品定义：**Study Agent 是长期保持“正在学什么、已经确认什么、还不会什么、下一步是什么”的个人学习工作台。**

本文件只维护当前权威状态、可复核边界和唯一下一门。2026-10-06 本次收敛前的完整状态原样归档到 [`archive/PROJECT_STATUS_PRE_177_FINAL_REVIEW_2026-10-06.md`](archive/PROJECT_STATUS_PRE_177_FINAL_REVIEW_2026-10-06.md)；更早历史继续由既有 archive 与 Git 历史持有。

## 0. Current Handoff（cold-start 入口）

**当前执行权：Standard handoff 接纳 / 来源复用适配器（未激活）。** #177 已合并，最终 PR head `72fc67e5117757158faf43756bad6058eb325b39` 的 CI run `37418122175` 为 `completed/success`；main merge commit 为 `8a5148e3c7d438e0ad5846b6d901f334d971e781`。本轮查询 exact-main push CI `37420193931` 时仍为 `in_progress`，main 验证未关闭，不重复轮询等待。

**施工身份：** worktree `D:/study-agent-validation/standard-handoff-consumer`，分支 `codex/standard-handoff-consumer`，base `8a5148e3`；本文件所在提交为适配器候选 head。只新增应用适配器、对应测试与命名 impact set，不改变 API、聊天路由、既有研究执行器、数据库 schema 或发布权限。

**本刀行为：**

- 只从服务端 SQLite 加载 parent turn 的 pending handoff，拒绝错误会话／轮次、未完成或已取消记录；核对 source run 归属、原始 query，重新验证 handoff digest 和终态。
- 深拷贝复用已验证相关正文和成功查询，不消耗新 Standard read/query，不赋予 claim 或 publication authority。
- 新工作单独计数，最多 5 reads / 4 queries，失败调用先扣预算；保留 Standard 60 秒窗口和 12 秒收尾余量。整体 deadline 不得晚于原始 turn 创建时间 + Lookup 30 秒 + Standard 60 秒。这是适配器入场边界，尚未约束阻塞 gateway 调用时长，生产 wall-time 未验收。
- 取消或 deadline 到达时，缓存命中也拒绝继续执行。

**验证：** 新模块 23 项 controls PASS；Ruff PASS；mypy baseline `current=122 / baseline=128 / resolved=6`，无新增错误。named `standard_handoff_consumer` 包含自身、Lookup 终态、ChatService、research/semantic recovery、SQLite repository 与 stage policy，最终 171 passed / 58.60s。未激活适配器按 L1 验证；生产接入改变执行权时必须 early L3。

**测试发现：** resolver 当前没有 owner kwargs，fixture 改为真实 ChatService 保存后显式建立带归属的 source run，不能假装生产已传递 owner。取消字段不由 `upsert_chat_turn` 写入，负控改用真实 `request_turn_cancel` 路径；均为夹具修正。

**明确未完成：** 聊天入口尚未把 thread/turn ownership 传给研究 run，旧记录可能无法接纳，本刀严格拒绝归属不完整记录。计数和缓存仅在当前进程有效，不具备 durable lease、跨进程 exactly-once 或 interruption/resume；取消参数未绑定真实运行取消源；Standard 多源／比较／冲突与发布未实施。pending handoff 不等于 Standard 执行，Lookup / Standard / Deep overall 均 **NOT CLOSED**。UI 独立后置。

**唯一下一 slice：** 核 main CI `37420193931`，再独立补齐聊天 → source run 归属和 Standard durable operation/cursor/预算账本（取消／重启不重置、不重复消费）。完成 early L3、exact-head CI 和最终审查后才能激活自动消费；当前适配器仅作为可审查草稿。验证生成的未跟踪 `.mypy_cache/` 不暂存；无其他无关修改。

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
